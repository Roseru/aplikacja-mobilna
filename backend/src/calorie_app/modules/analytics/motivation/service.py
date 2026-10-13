"""Transaction orchestration and honest, bounded own-result freshness."""

from dataclasses import replace

from calorie_app.modules.analytics.motivation import repository
from calorie_app.modules.analytics.motivation.context import SourceMutationContext, SourceProjection
from calorie_app.modules.analytics.motivation.ranking import ranking_publication
from calorie_app.modules.analytics.motivation.rules import BADGE_CODES, rank_for_points
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.catalog.timestamps import utc_text
from calorie_app.modules.identity.service import current_epoch, lock_account


def source_mutated(
    session, context: SourceMutationContext, extensions: tuple[SourceProjection, ...] = ()
):
    """Invoked exactly once for accepted source, within its source savepoint."""
    # One explicit DB refresh owner. Other extensions remain lock/apply only.
    from calorie_app.core.errors import DomainError
    from calorie_app.modules.nemesis.source_guard import NemesisSourceProjection

    nemesis = [item for item in extensions if isinstance(item, NemesisSourceProjection)]
    if len(nemesis) > 1:
        raise DomainError(503, "nemesis_source_unqualified")
    for projection in extensions:
        projection.lock(session, context)
    qualified_at = (
        nemesis[0].refresh(session, context)
        if nemesis
        else repository.refresh(
            session,
            context.owner_id,
            None if context.goal_axis_changed else list(context.affected_dates),
        )
    )
    qualified = replace(context, qualified_at=qualified_at)
    for projection in extensions:
        projection.apply(session, qualified)
    return qualified


def read_motivation(session, owner_id, expected_generation=None):
    account = lock_account(session, owner_id, expected_generation)
    epoch, now = current_epoch(session), database_now(session)
    projection = repository.account_projection(session, owner_id)
    pending_backfill = (
        projection is None
        or projection["sync_epoch"] != epoch
        or projection["backfill_state"] != "ready"
    )
    due = None if projection is None else projection["next_matures_at"]
    status = (
        "pending_backfill"
        if pending_backfill
        else "pending_materialization"
        if due is not None and due <= now
        else "final"
    )
    points = None if pending_backfill else projection["total_points"]
    rows = {row["badge_code"]: row for row in repository.badges(session, owner_id)}
    progress = {} if pending_backfill else projection["progress"]
    result_badges = []
    for code, target in BADGE_CODES.items():
        row = rows.get(code)
        active = row is not None and row["active"] and not pending_backfill
        result_badges.append(
            {
                "code": code,
                "rule_version": "regularity_v1",
                "status": "final"
                if active
                else "revoked"
                if row is not None and not pending_backfill
                else "pending",
                "progress": min(target, progress.get(code, 0)),
                "required": target,
                "witness_dates": row["witness"] if active else [],
                "first_awarded_at": utc_text(row["first_awarded_at"]) if row else None,
                "activated_at": utc_text(row["activated_at"]) if row else None,
                "revoked_at": utc_text(row["revoked_at"]) if row and row["revoked_at"] else None,
            }
        )
    return {
        "account_generation": account.generation,
        "sync_epoch": str(epoch),
        "as_of": utc_text(now),
        "rule_version": "regularity_v1",
        "revision": projection["revision"] if projection else 0,
        "source_position": projection["source_position"] if projection else 0,
        "status": status,
        "points": points,
        "rank": rank_for_points(points) if points is not None else None,
        "badges": result_badges,
        "ranking": ranking_publication(session, owner_id, epoch),
    }
