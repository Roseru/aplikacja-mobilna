"""Replay precedes expensive work; durable denials consume the receipt budget once."""

import hashlib

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai import repository as repo
from calorie_app.modules.catalog.community.idempotency import MutationOutcome
from calorie_app.modules.catalog.community.repository import lock_catalog
from calorie_app.modules.catalog.validation import canonical_json


def semantic_hash(method, path, semantic):
    return hashlib.sha256(
        canonical_json({"method": method, "path": path, "body": semantic})
    ).hexdigest()


def replay(session, account, epoch, key, request_hash):
    saved = repo.receipt(session, account.id, key)
    if saved is None:
        return None
    if saved["sync_epoch"] != epoch:
        raise DomainError(409, "sync_epoch_changed")
    if saved["generation"] != account.generation:
        raise DomainError(409, "account_generation_changed")
    if saved["request_hash"] != request_hash:
        return MutationOutcome(409, error=DomainError(409, "idempotency_key_reused"), replayed=True)
    payload = saved["response_payload"]
    if payload is None:
        minimal = saved["result_minimal"]
        if saved["operation_kind"] in {"create", "cancel"} and saved["status_code"] < 400:
            payload = minimal
        elif saved["operation_kind"] == "confirm" and saved["status_code"] < 400:
            payload = repo.call(
                session,
                "SELECT response FROM app.ai_decisions WHERE owner_id=:owner AND analysis_id=:id",
                owner=account.id,
                id=minimal["analysis_id"],
            )
        elif saved["status_code"] >= 400:
            payload = minimal
        if payload is None:
            return MutationOutcome(
                409, error=DomainError(409, "idempotency_result_expired"), replayed=True
            )
    if saved["status_code"] >= 400:
        return MutationOutcome(
            saved["status_code"],
            error=DomainError(saved["status_code"], payload["code"], payload.get("details")),
            replayed=True,
        )
    return MutationOutcome(saved["status_code"], payload=payload, replayed=True)


def execute_mutation(session, principal, key, epoch, kind, request_hash, action):
    account = repo.context(session, principal, epoch)
    previous = replay(session, account, epoch, key, request_hash)
    if previous is not None:
        return previous
    if kind == "confirm":
        lock_catalog(session, shared=True)
    if not repo.call(session, "SELECT app.e7_admit(:owner,'receipts')", owner=account.id):
        raise DomainError(429, "ai_receipt_quota_exhausted")
    try:
        with session.begin_nested():
            status, payload = action(account)
        outcome = MutationOutcome(status, payload=payload)
        minimal = {"analysis_id": payload["analysis_id"]} if kind == "confirm" else payload
    except DomainError as error:
        if error.status not in {403, 404, 409, 410, 422, 429, 503}:
            raise
        outcome = MutationOutcome(error.status, error=error)
        payload = {"code": error.code, "details": error.details}
        minimal = {"code": error.code}
    repo.save_receipt(
        session, account, epoch, key, kind, request_hash, outcome.status, payload, minimal
    )
    return outcome
