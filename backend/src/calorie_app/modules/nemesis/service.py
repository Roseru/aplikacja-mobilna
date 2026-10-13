"""Caller-owned lifecycle transactions with committed, replayable domain refusals."""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.nemesis import repository
from calorie_app.modules.nemesis.addressing import (
    canonical_request_hash,
    share_code_digest,
)


@dataclass(frozen=True)
class LifecycleResult:
    response: dict
    replayed: bool
    http_status: int


def unwrap(envelope):
    if not isinstance(envelope, dict):
        raise DomainError(503, "service_unavailable")
    if not envelope.get("ok"):
        raise DomainError(
            int(envelope.get("http_status", 503)), envelope.get("code", "service_unavailable")
        )
    return LifecycleResult(
        envelope["response"], bool(envelope.get("replayed")), int(envelope.get("http_status", 200))
    )


def transact(engine, action: Callable, after_accept=None):
    """A refused create commits admission before its safe HTTP error is raised.

    Only deadlock/serialization restarts the complete transaction, up to three
    attempts. Each attempt reacquires all locks and reads a fresh DB clock.
    Unknown SQL failures roll back and never become durable domain refusals.
    """
    for attempt in range(3):
        try:
            with Session(engine) as session, session.begin():
                envelope = action(session)
                if after_accept is not None and envelope.get("ok") and not envelope.get("replayed"):
                    after_accept(session, envelope["response"])
            return unwrap(envelope)
        except DBAPIError as error:
            code = getattr(error.orig, "sqlstate", None)
            if code in {"40001", "40P01"} and attempt < 2:
                continue
            raise DomainError(503, "service_unavailable") from None
        except SQLAlchemyError:
            raise DomainError(503, "service_unavailable") from None
    raise DomainError(503, "service_unavailable")


def mutate(
    engine,
    principal,
    epoch,
    operation,
    key,
    body=None,
    challenge_id=None,
    revision=None,
    projection_initializer=None,
):
    if "user" not in principal.roles:
        raise DomainError(403, "forbidden")
    wire = body.model_dump(mode="json") if body is not None else {}
    fingerprint = canonical_request_hash(operation, wire, epoch, revision, challenge_id)
    payload = dict(wire)
    if operation == "issue":
        payload = {}  # SQL owns CSPRNG issuance; raw callers cannot supply a weak code.
    elif operation == "create":
        payload.pop("destination_code")
        payload["destination_digest"] = share_code_digest(wire["destination_code"])
    if challenge_id is not None:
        payload["challenge_id"] = str(challenge_id)
        payload["revision"] = revision
    # Production accept is initialized inside DB lifecycle, including direct
    # EXECUTE. An explicit test callback may inject failure after the DB seed.
    initializer = projection_initializer if operation == "accept" else None
    return transact(
        engine,
        lambda session: repository.execute(
            session, principal, epoch, operation, key, fingerprint, payload
        ),
        after_accept=initializer,
    )


def read(engine, principal, epoch, challenge_id=None, limit=30, cursor=None):
    if "user" not in principal.roles:
        raise DomainError(403, "forbidden")
    return transact(
        engine,
        lambda session: repository.read(session, principal, epoch, challenge_id, limit, cursor),
    )


def statistics(engine, principal, epoch, challenge_id):
    if "user" not in principal.roles:
        raise DomainError(403, "forbidden")
    return transact(
        engine, lambda session: repository.statistics(session, principal, epoch, challenge_id)
    )
