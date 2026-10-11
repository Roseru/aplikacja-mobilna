"""Identity writes hold the account lock through the caller's commit."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.models import InstallationState, OnlineReceipt, UserAccount
from calorie_app.modules.profiles.models import UserConsent


def current_epoch(session) -> UUID:
    epoch = session.scalar(select(InstallationState.sync_epoch).where(InstallationState.id == 1))
    if epoch is None:
        raise DomainError(503, "service_unavailable")
    return epoch


def lock_account(session, account_id: UUID, expected_generation: int | None = None) -> UserAccount:
    account = session.scalar(
        select(UserAccount)
        .where(UserAccount.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise DomainError(403, "account_bootstrap_required")
    if account.state != "active":
        raise DomainError(403, "account_deleting")
    if expected_generation is not None and account.generation != expected_generation:
        raise DomainError(409, "account_generation_changed")
    return account


def require_account(session, principal) -> UserAccount:
    require_unblocked_subject(session, principal)
    account_id = session.scalar(
        select(UserAccount.id).where(
            UserAccount.issuer == principal.issuer, UserAccount.subject == principal.subject
        )
    )
    if account_id is None:
        raise DomainError(403, "account_bootstrap_required")
    return lock_account(session, account_id)


def require_unblocked_subject(session, principal):
    if session.scalar(
        text("SELECT app.subject_blocked(:issuer,:subject)"),
        {"issuer": principal.issuer, "subject": principal.subject},
    ):
        raise DomainError(403, "account_deleting")


def begin_deleting(session, account_id: UUID, expected_generation: int | None = None):
    account = lock_account(session, account_id, expected_generation)
    if account.generation == 2147483647:
        raise DomainError(409, "revision_exhausted")
    account.state = "deleting"
    account.generation += 1
    session.flush()
    return account


def check_receipt_context(receipt, account, epoch):
    if receipt.sync_epoch != epoch:
        raise DomainError(
            409, "sync_epoch_changed", details=[{"field": "sync_epoch", "reason": str(epoch)}]
        )
    if receipt.generation != account.generation:
        raise DomainError(
            409,
            "account_generation_changed",
            details=[{"field": "account_generation", "reason": str(account.generation)}],
        )


def bootstrap(session, principal, key: UUID) -> dict:
    require_unblocked_subject(session, principal)
    existing = session.scalar(
        select(UserAccount.id).where(
            UserAccount.issuer == principal.issuer, UserAccount.subject == principal.subject
        )
    )
    if existing is not None:
        # Lock an existing account before an INSERT can wait on its removal.
        # A bootstrap begun before deleting must never retry that INSERT after
        # purge and recreate the old subject using its earlier statement view.
        lock_account(session, existing)
    else:
        session.execute(
            insert(UserAccount)
            .values(id=uuid4(), issuer=principal.issuer, subject=principal.subject)
            .on_conflict_do_nothing(index_elements=[UserAccount.issuer, UserAccount.subject])
        )
    account = require_account(session, principal)
    # Initialising consents belongs to the account transaction, never to a read.
    session.execute(insert(UserConsent).values(owner_id=account.id).on_conflict_do_nothing())
    epoch = current_epoch(session)
    receipt = session.get(OnlineReceipt, (account.id, "bootstrap", key))
    if receipt is not None:
        check_receipt_context(receipt, account, epoch)
        return receipt.response
    result = {
        "account_id": str(account.id),
        "sync_epoch": str(epoch),
        "account_generation": account.generation,
        "server_time": utc_text(database_now(session)),
    }
    session.add(
        OnlineReceipt(
            owner_id=account.id,
            operation="bootstrap",
            key=key,
            request_hash=hashlib.sha256(b"bootstrap:no-body:v1").hexdigest(),
            generation=account.generation,
            sync_epoch=epoch,
            response=result,
        )
    )
    session.flush()
    return result
