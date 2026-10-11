"""Private domain operations; each caller owns its encompassing transaction."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from sqlalchemy import func, select, text

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.catalog.validation import canonical, canonical_json
from calorie_app.modules.identity.models import OnlineReceipt
from calorie_app.modules.identity.service import check_receipt_context, current_epoch, lock_account
from calorie_app.modules.profiles.models import GoalTimeline, GoalVersion, Profile, UserConsent
from calorie_app.modules.profiles.schemas import (
    ConsentInput,
    EstimateInput,
    GoalPayload,
    ProfilePayload,
)

MAX_REVISION = 2147483647


def estimate_energy(data: EstimateInput, now: datetime | None = None) -> dict:
    with localcontext() as ctx:
        ctx.prec = 50
        resting = (
            Decimal(10) * data.weight_kg
            + Decimal("6.25") * data.height_cm
            - Decimal(5) * data.age_years
            + Decimal(5 if data.equation_variant == "plus_5" else -161)
        )
        pal = {"stationary": "1.5", "line": "1.8", "commando": "2.2"}[data.activity_class]
        maintenance = resting * Decimal(pal)
        if resting <= 0 or maintenance > Decimal("999999.999999999999"):
            raise DomainError(422, "invalid_request")
        return {
            "method": "mifflin_pal_v1",
            "input": data.model_dump(mode="json"),
            "resting_kcal": canonical(resting),
            "pal": pal,
            "maintenance_kcal": canonical(maintenance),
            "estimated_at": utc_text(now or datetime.now(UTC)),
        }


def consent_data(consent):
    return {
        "revision": consent.revision,
        "ranking": consent.ranking,
        "automatic_energy_adjustment": consent.automatic_energy_adjustment,
        "updated_at": utc_text(consent.updated_at),
    }


def profile_data(profile):
    return {
        "entity_id": str(profile.id),
        "revision": profile.revision,
        "payload": {
            "pseudonym": profile.pseudonym,
            "height_cm": canonical(profile.height_cm) if profile.height_cm else None,
            "activity_class": profile.activity_class,
            "time_zone": profile.time_zone,
        },
    }


def read_profile(session, owner_id: UUID) -> dict:
    account = lock_account(session, owner_id)
    profile = session.scalar(
        select(Profile).where(Profile.owner_id == owner_id, Profile.deleted_at.is_(None))
    )
    consents = session.get(UserConsent, owner_id)
    if consents is None:
        raise DomainError(503, "service_unavailable")
    timeline = session.get(GoalTimeline, owner_id, populate_existing=True)
    return {
        "account_id": str(account.id),
        "sync_epoch": str(current_epoch(session)),
        "profile": profile_data(profile) if profile else None,
        "consents": consent_data(consents),
        "goal_timeline_revision": timeline.revision if timeline else 0,
    }


def put_consents(
    session,
    owner_id: UUID,
    data: ConsentInput,
    base_revision: int,
    key: UUID,
    expected_generation: int | None = None,
) -> dict:
    account = lock_account(session, owner_id, expected_generation)
    from calorie_app.modules.sync.repository import append_change, lock_counter

    counter = lock_counter(session, owner_id)
    epoch = current_epoch(session)
    fingerprint = hashlib.sha256(
        canonical_json({"body": data.model_dump(mode="json"), "if_match": base_revision})
    ).hexdigest()
    receipt = session.get(OnlineReceipt, (owner_id, "consents", key))
    if receipt is not None:
        check_receipt_context(receipt, account, epoch)
        if receipt.request_hash != fingerprint:
            raise DomainError(409, "idempotency_key_reused")
        if receipt.response is None:
            raise DomainError(
                409,
                "idempotency_result_expired",
                details=[{"field": "accepted_revision", "reason": str(receipt.accepted_revision)}],
            )
        return receipt.response
    consent = session.get(UserConsent, owner_id, populate_existing=True)
    if consent is None:
        raise DomainError(503, "service_unavailable")
    if consent.revision != base_revision:
        raise DomainError(409, "version_conflict")
    if consent.revision == MAX_REVISION:
        raise DomainError(409, "revision_exhausted")
    consent.revision += 1
    consent.ranking = data.ranking
    consent.automatic_energy_adjustment = data.automatic_energy_adjustment
    consent.updated_at = database_now(session)
    # Online state can advance H without pretending to be a seventh wire entity.
    append_change(session, counter, None)
    result = consent_data(consent)
    session.add(
        OnlineReceipt(
            owner_id=owner_id,
            operation="consents",
            key=key,
            request_hash=fingerprint,
            generation=account.generation,
            sync_epoch=epoch,
            response=result,
            accepted_revision=consent.revision,
            created_at=database_now(session),
        )
    )
    session.flush()
    return result


def prune_consent_responses(session) -> int:
    """Bounded cleanup; minimal receipts remain, bootstrap's small result is permanent."""
    return session.scalar(text("SELECT app.prune_consent_responses()"))


def save_profile(
    session,
    owner_id: UUID,
    entity_id: UUID,
    data: ProfilePayload,
    base_revision: int = 0,
    expected_generation: int | None = None,
) -> Profile:
    lock_account(session, owner_id, expected_generation)
    current = session.scalar(
        select(Profile).where(Profile.owner_id == owner_id, Profile.id == entity_id)
    )
    if current is None:
        if base_revision != 0:
            raise DomainError(409, "version_conflict")
        if session.get(Profile, entity_id) is not None:
            raise DomainError(404, "not_found")
        other = session.scalar(
            select(Profile.id).where(Profile.owner_id == owner_id, Profile.deleted_at.is_(None))
        )
        if other is not None:
            raise DomainError(409, "profile_already_exists")
        current = Profile(id=entity_id, owner_id=owner_id, revision=1)
        session.add(current)
    else:
        if current.deleted_at is not None or current.revision != base_revision:
            raise DomainError(409, "version_conflict")
        if current.revision == MAX_REVISION:
            raise DomainError(409, "revision_exhausted")
        current.revision += 1
    for field, value in data.model_dump().items():
        setattr(current, field, value)
    session.flush()
    return current


def delete_profile(
    session,
    owner_id: UUID,
    entity_id: UUID,
    base_revision: int,
    expected_generation: int | None = None,
):
    lock_account(session, owner_id, expected_generation)
    profile = session.scalar(
        select(Profile).where(Profile.owner_id == owner_id, Profile.id == entity_id)
    )
    if profile is None:
        raise DomainError(404, "not_found")
    if profile.deleted_at is not None or profile.revision != base_revision:
        raise DomainError(409, "version_conflict")
    if profile.revision == MAX_REVISION:
        raise DomainError(409, "revision_exhausted")
    profile.revision += 1
    profile.deleted_at = database_now(session)
    session.flush()


def create_goal(
    session,
    owner_id: UUID,
    entity_id: UUID,
    data: GoalPayload,
    expected_generation: int | None = None,
) -> GoalVersion:
    lock_account(session, owner_id, expected_generation)
    timeline = session.get(GoalTimeline, owner_id, populate_existing=True)
    revision = timeline.revision if timeline else 0
    if revision != data.timeline_base_revision:
        raise DomainError(409, "goal_timeline_conflict")
    if revision == MAX_REVISION:
        raise DomainError(409, "revision_exhausted")
    if session.get(GoalVersion, entity_id) is not None:
        raise DomainError(409, "entity_id_reused")
    if data.correction_of is not None:
        corrected = session.scalar(
            select(GoalVersion).where(
                GoalVersion.owner_id == owner_id, GoalVersion.id == data.correction_of
            )
        )
        if corrected is None:
            raise DomainError(404, "not_found")
    if data.estimate is not None:
        expected = estimate_energy(
            data.estimate.input, datetime.fromisoformat(data.estimate.estimated_at)
        )
        if expected != data.estimate.model_dump(mode="json"):
            raise DomainError(422, "invalid_request")
    if timeline is None:
        timeline = GoalTimeline(owner_id=owner_id, revision=0)
        session.add(timeline)
    timeline.revision = revision + 1
    session.flush()
    values = data.model_dump(exclude={"estimate", "decided_at"})
    values["decided_at"] = datetime.fromisoformat(data.decided_at)
    goal = GoalVersion(
        id=entity_id,
        owner_id=owner_id,
        revision=1,
        timeline_revision=revision + 1,
        payload=data.model_dump(mode="json"),
        **values,
    )
    session.add(goal)
    session.flush()
    return goal


def goal_for_date(session, owner_id: UUID, day, snapshot_revision: int | None = None):
    lock_account(session, owner_id)
    # Every correction remains immutable. Select the latest accepted version of
    # each original decision before applying its (possibly corrected) date. This
    # also resolves two audited correction branches without reviving an old head.
    bound = snapshot_revision if snapshot_revision is not None else MAX_REVISION
    roots = (
        select(GoalVersion.id.label("id"), GoalVersion.id.label("root"))
        .where(
            GoalVersion.owner_id == owner_id,
            GoalVersion.correction_of.is_(None),
            GoalVersion.timeline_revision <= bound,
        )
        .cte("goal_roots", recursive=True)
    )
    roots = roots.union_all(
        select(GoalVersion.id, roots.c.root)
        .join(roots, GoalVersion.correction_of == roots.c.id)
        .where(GoalVersion.owner_id == owner_id, GoalVersion.timeline_revision <= bound)
    )
    heads = (
        select(
            GoalVersion.id,
            func.row_number()
            .over(partition_by=roots.c.root, order_by=GoalVersion.timeline_revision.desc())
            .label("position"),
        )
        .join(roots, roots.c.id == GoalVersion.id)
        .subquery()
    )
    query = (
        select(GoalVersion)
        .join(heads, heads.c.id == GoalVersion.id)
        .where(
            heads.c.position == 1,
            GoalVersion.owner_id == owner_id,
            GoalVersion.effective_from <= day,
        )
    )
    return session.scalar(
        query.order_by(
            GoalVersion.effective_from.desc(), GoalVersion.timeline_revision.desc()
        ).limit(1)
    )
