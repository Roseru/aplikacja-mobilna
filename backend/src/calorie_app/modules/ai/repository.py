"""Small SQL reads and qualified functions; caller owns every commit."""

from sqlalchemy import text

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.identity.service import current_epoch, require_account


def context(session, principal, epoch):
    account = require_account(session, principal)
    actual = current_epoch(session)
    if actual != epoch:
        raise DomainError(
            409, "sync_epoch_changed", [{"field": "sync_epoch", "reason": str(actual)}]
        )
    return account


def row(session, sql, **params):
    return session.execute(text(sql), params).mappings().one_or_none()


def call(session, sql, **params):
    return session.scalar(text(sql), params)


def encoded(value):
    return canonical_json(value).decode("utf-8")


def analysis(session, owner, analysis_id):
    found = row(
        session,
        "SELECT a.*,j.queue_deadline FROM app.ai_analyses a "
        "JOIN app.ai_jobs j ON j.analysis_id=a.id WHERE a.owner_id=:owner AND a.id=:id",
        owner=owner,
        id=analysis_id,
    )
    if found is None:
        raise DomainError(404, "not_found")
    return found


def receipt(session, owner, key):
    return row(
        session,
        "SELECT * FROM app.ai_receipts WHERE owner_id=:owner AND operation_id=:key",
        owner=owner,
        key=key,
    )


def save_receipt(session, account, epoch, key, kind, request_hash, status, payload, minimal):
    call(
        session,
        "SELECT app.e7_save_receipt(:owner,:generation,:epoch,:key,:kind,:hash,:status,"
        "CAST(:payload AS jsonb),CAST(:minimal AS jsonb))",
        owner=account.id,
        generation=account.generation,
        epoch=epoch,
        key=key,
        kind=kind,
        hash=request_hash,
        status=status,
        payload=encoded(payload),
        minimal=encoded(minimal),
    )


def lock_session(session, name, *, wait=False):
    function = "pg_advisory_lock" if wait else "pg_try_advisory_lock"
    result = call(session, f"SELECT {function}(hashtextextended(:name,73317))", name=name)
    return True if wait else result


def unlock_session(session, name):
    return call(session, "SELECT pg_advisory_unlock(hashtextextended(:name,73317))", name=name)


def pool_available(session, profile, limits=None):
    limits = limits or {}
    return call(
        session,
        "SELECT EXISTS(SELECT 1 FROM app.ai_pools p JOIN app.ai_controls c ON c.id=1 "
        "JOIN app.installation_state i ON i.id=c.id WHERE p.scope=:scope AND p.enabled "
        "AND p.provider=:provider AND p.model=:model AND c.dispatch_open "
        "AND c.sync_epoch=i.sync_epoch AND (CAST(:rpm AS integer) IS NULL OR "
        "(p.rpm=:rpm AND p.tpm=:tpm AND p.rpd=:rpd)))",
        scope=profile["pool_scope"],
        provider=profile["provider"],
        model=profile["model"],
        rpm=limits.get("rpm"),
        tpm=limits.get("tpm"),
        rpd=limits.get("rpd"),
    )
