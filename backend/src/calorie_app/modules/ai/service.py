"""Acceptance separates short database transactions from codec/filesystem IO."""

import hashlib
from uuid import uuid4

from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai import repository as repo
from calorie_app.modules.ai.configuration import NOTICE_VERSION, configuration
from calorie_app.modules.ai.idempotency import execute_mutation, replay, semantic_hash
from calorie_app.modules.ai.image_preparation import prepare_image
from calorie_app.modules.ai.schemas import CreateMetadata
from calorie_app.modules.ai.storage import PhotoStorage
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.service import current_epoch, require_account


def public_profile(profile):
    return {key: value for key, value in profile.items() if key != "pool_scope"}


def initial_context(factory, principal, epoch=None):
    with factory() as session:
        account = require_account(session, principal)
        actual = current_epoch(session)
        if epoch is not None and epoch != actual:
            raise DomainError(
                409, "sync_epoch_changed", [{"field": "sync_epoch", "reason": str(actual)}]
            )
        return account.id, account.generation, actual


def capabilities(factory, principal, settings):
    cfg = configuration(settings)
    with factory() as session:
        require_account(session, principal)
        reason = cfg.reason
        if reason is None and not repo.pool_available(session, cfg.profile, cfg.limits):
            reason = "ai_pool_or_restore_unavailable"
    if reason is None and (
        settings.ai_photo_root is None or not PhotoStorage(settings.ai_photo_root).availability()
    ):
        reason = "ai_storage_unavailable"
    return {
        "provider": settings.ai_provider,
        "profile": public_profile(cfg.profile),
        "notice_version": NOTICE_VERSION,
        "available": reason is None,
        "unavailable_reason": reason,
    }


def read_analysis(factory, principal, analysis_id):
    with factory() as session:
        account = require_account(session, principal)
        value = repo.analysis(session, account.id, analysis_id)
        if (
            value["sync_epoch"] != current_epoch(session)
            or value["generation"] != account.generation
        ):
            raise DomainError(409, "analysis_context_changed")
        if value["state"] in {"queued", "running"} and value["photo_expires_at"] <= database_now(
            session
        ):
            raise DomainError(410, "image_expired")
        return {
            "analysis_id": str(value["id"]),
            "revision": value["revision"],
            "state": value["state"],
            "decision_state": value["decision_state"],
            "queue_deadline": utc_text(value["queue_deadline"]),
            "photo_expires_at": utc_text(value["photo_expires_at"]),
            "profile": public_profile(value["profile"]),
            "proposal": value["proposal"],
            "error_code": value["error_code"],
        }


def rejection(result):
    if result is None:
        raise DomainError(409, "analysis_context_changed")
    if "error" in result:
        code = result["error"]
        status = (
            404
            if code == "not_found"
            else 429
            if code in {"ai_user_quota_exhausted", "ai_active_job"}
            else 503
            if code in {"ai_restore_pending", "ai_unavailable"}
            else 409
        )
        raise DomainError(status, code)
    return result


def create_analysis(
    engine, principal, epoch, operation_id, metadata, image, settings, reauthorize=None
):
    if reauthorize is not None:
        principal = reauthorize()
    metadata = CreateMetadata.model_validate(metadata)
    storage = None
    storage_key = None
    storage_locked = False
    accepted = False
    operation_lock = None
    with (
        engine.connect() as connection,
        Session(bind=connection, expire_on_commit=False) as session,
    ):
        try:
            account = repo.context(session, principal, epoch)
            generation = account.generation
            original_hash = hashlib.sha256(image).hexdigest()
            digest = semantic_hash(
                "POST",
                "/api/v1/ai/food-analyses",
                {
                    "metadata": metadata.model_dump(mode="json"),
                    "image_sha256": original_hash,
                },
            )
            operation_lock = f"e7-operation:{account.id}:{operation_id}"
            if not repo.lock_session(session, operation_lock):
                raise DomainError(409, "ai_operation_busy")
            previous = replay(session, account, epoch, operation_id, digest)
            session.commit()
            if previous is not None:
                return previous
            cfg = configuration(settings)
            if metadata.consent.provider != settings.ai_provider:
                raise DomainError(422, "photo_provider_changed")
            if cfg.reason is not None:
                raise DomainError(503, cfg.reason)
            if not repo.pool_available(session, cfg.profile, cfg.limits):
                raise DomainError(503, "ai_pool_or_restore_unavailable")
            session.commit()
            if settings.ai_photo_root is None:
                raise DomainError(503, "ai_storage_unavailable")
            storage = PhotoStorage(settings.ai_photo_root)
            if not storage.availability():
                raise DomainError(503, "ai_storage_unavailable")
            # Consent + raw hash + permanent receipt precede codec and all file IO.
            prepared = prepare_image(image)
            # Recheck after codec, still before staging. No account lock crosses IO.
            account = repo.context(session, principal, epoch)
            if account.generation != generation:
                raise DomainError(409, "account_generation_changed")
            storage_key = uuid4().hex
            storage_locked = repo.lock_session(session, "e7-storage:" + storage_key)
            if not storage_locked:
                raise DomainError(503, "ai_storage_unavailable")
            if not repo.call(session, "SELECT app.e7_compensation_intent(:key)", key=storage_key):
                raise DomainError(503, "ai_storage_unavailable")
            session.commit()
            storage.activate(storage_key, prepared.data)
            if reauthorize is not None:
                principal = reauthorize()

            def accept(account):
                if account.generation != generation:
                    raise DomainError(409, "account_generation_changed")
                if not repo.pool_available(session, cfg.profile, cfg.limits):
                    raise DomainError(503, "ai_pool_or_restore_unavailable")
                result = repo.call(
                    session,
                    "SELECT app.e7_accept(:owner,:generation,:epoch,:id,:job,:original,:prepared,"
                    ":key,:width,:height,CAST(:profile AS jsonb))",
                    owner=account.id,
                    generation=account.generation,
                    epoch=epoch,
                    id=uuid4(),
                    job=uuid4(),
                    original=original_hash,
                    prepared=prepared.sha256,
                    key=storage_key,
                    width=prepared.width,
                    height=prepared.height,
                    profile=repo.encoded(cfg.profile),
                )
                result = rejection(result)
                result["profile"] = public_profile(result["profile"])
                return 202, result

            outcome = execute_mutation(
                session, principal, operation_id, epoch, "create", digest, accept
            )
            # A failed COMMIT ACK can still mean a durable acceptance. Preserve
            # the prepared object for registry-aware sweep instead of deleting it.
            accepted = outcome.error is None and not outcome.replayed
            session.commit()
            return outcome
        finally:
            session.rollback()
            try:
                if storage_locked and not accepted:
                    can_delete = repo.call(
                        session, "SELECT app.e7_compensation_intent(:key)", key=storage_key
                    )
                    session.commit()
                    if can_delete:
                        storage.delete(storage_key)
                        repo.call(session, "SELECT app.e7_compensation_ack(:key)", key=storage_key)
                        session.commit()
            finally:
                session.rollback()
                if storage_locked:
                    repo.unlock_session(session, "e7-storage:" + storage_key)
                if operation_lock is not None:
                    repo.unlock_session(session, operation_lock)
                session.commit()
