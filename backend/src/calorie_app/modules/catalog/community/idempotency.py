"""One account-locked transaction records effects or durable safe denials."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from calorie_app.core.errors import DomainError, error_response
from calorie_app.modules.catalog.community.models import CommunityReceipt
from calorie_app.modules.catalog.community.repository import admit, lock_catalog
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.identity.service import current_epoch, require_account


@dataclass(frozen=True)
class MutationOutcome:
    status: int
    payload: dict | None = None
    error: DomainError | None = None
    replayed: bool = False


def semantic_hash(method: str, path: str, body: dict, *, versions=None) -> str:
    return hashlib.sha256(
        canonical_json({"method": method, "path": path, "body": body, "versions": versions})
    ).hexdigest()


def execute_mutation(
    session, principal, operation_kind: str, operation_id: UUID, epoch: UUID, semantic: dict, action
) -> MutationOutcome:
    """Caller must commit outcome, including denials, before returning HTTP ACK."""
    account = require_account(session, principal)
    actual_epoch = current_epoch(session)
    if epoch != actual_epoch:
        raise DomainError(
            409, "sync_epoch_changed", [{"field": "sync_epoch", "reason": str(actual_epoch)}]
        )
    request_hash = hashlib.sha256(canonical_json(semantic)).hexdigest()
    lock_catalog(session)
    receipt = session.scalar(
        select(CommunityReceipt).where(
            CommunityReceipt.owner_id == account.id,
            CommunityReceipt.operation_kind == operation_kind,
            CommunityReceipt.operation_id == operation_id,
        )
    )
    if receipt is not None:
        if receipt.sync_epoch != actual_epoch:
            raise DomainError(409, "sync_epoch_changed")
        if receipt.generation != account.generation:
            raise DomainError(409, "account_generation_changed")
        if receipt.request_hash != request_hash:
            return MutationOutcome(
                409, error=DomainError(409, "idempotency_key_reused"), replayed=True
            )
        if receipt.response_payload is None:
            disposition = "executed" if receipt.status_code < 400 else "denied"
            return MutationOutcome(
                409,
                error=DomainError(
                    409,
                    "idempotency_result_expired",
                    [{"field": "operation", "reason": disposition}],
                ),
                replayed=True,
            )
        if receipt.status_code >= 400:
            saved = receipt.response_payload
            return MutationOutcome(
                receipt.status_code,
                error=DomainError(receipt.status_code, saved["code"], saved.get("details")),
                replayed=True,
            )
        return MutationOutcome(receipt.status_code, payload=receipt.response_payload, replayed=True)
    admit(session, account.id, "receipts")
    try:
        with session.begin_nested():
            result = action(account)
            status, payload = result if isinstance(result, tuple) else (200, result)
            session.flush()
        outcome = MutationOutcome(status, payload=payload)
        stored = payload
        minimal = payload
    except DomainError as error:
        if error.status not in {403, 404, 409, 422, 429}:
            raise
        outcome = MutationOutcome(error.status, error=error)
        stored = {"code": error.code, "details": error.details}
        minimal = {"disposition": "denied", "code": error.code}
    session.add(
        CommunityReceipt(
            owner_id=account.id,
            operation_kind=operation_kind,
            operation_id=operation_id,
            request_hash=request_hash,
            generation=account.generation,
            sync_epoch=actual_epoch,
            status_code=outcome.status,
            response_payload=stored,
            result_minimal=minimal,
        )
    )
    session.flush()
    return outcome


def outcome_response(request, outcome: MutationOutcome):
    if outcome.error is not None:
        error = outcome.error
        headers = {"Cache-Control": "no-store"}
        if error.status == 429:
            headers["Retry-After"] = "86400"
        return error_response(
            request, error.status, error.code, "Nie można wykonać żądania.", headers, error.details
        )
    return outcome.payload
