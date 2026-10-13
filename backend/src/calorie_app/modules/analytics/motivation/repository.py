"""Narrow source-derived database calls; no points supplied by the caller."""

from sqlalchemy import text


def refresh(session, owner_id, dates=None, batch=256):
    return session.scalar(
        text("SELECT app.e8_refresh(:owner,CAST(:dates AS date[]),:batch)"),
        {"owner": owner_id, "dates": dates, "batch": batch},
    )


def process_owner(session, owner_id, batch=256):
    return session.scalar(
        text("SELECT app.e8_process(:owner,:batch)"), {"owner": owner_id, "batch": batch}
    )


def candidates(session, batch=100):
    return list(session.scalars(text("SELECT app.e8_candidates(:batch)"), {"batch": batch}))


def backlog(session):
    return session.scalar(text("SELECT app.e8_status()"))


def account_projection(session, owner_id):
    return (
        session.execute(
            text("SELECT * FROM app.motivation_accounts WHERE owner_id=:owner"),
            {"owner": owner_id},
        )
        .mappings()
        .one_or_none()
    )


def badges(session, owner_id):
    return list(
        session.execute(
            text("SELECT * FROM app.motivation_badges WHERE owner_id=:owner ORDER BY badge_code"),
            {"owner": owner_id},
        ).mappings()
    )


def goal_probe(session, owner_id, dates):
    """Bounded winning heads at source boundaries, without capping goal history.

    SQL resolves the complete correction graph. Surviving heads are normalized
    to immutable decisions for the existing pure resolve_goal_dates sweep.
    A probe never limits the full source-derived refresh of an accepted axis.
    """
    from types import SimpleNamespace

    rows = session.execute(
        text(
            "SELECT f.local_date,v.id,v.timeline_revision,v.effective_from "
            "FROM app.e8_day_facts(:owner,CAST(:dates AS date[])) f "
            "JOIN app.goal_versions v ON v.owner_id=:owner AND v.id=f.goal_id"
        ),
        {"owner": owner_id, "dates": list(dates)},
    ).mappings()
    return [
        SimpleNamespace(
            id=row["id"],
            timeline_revision=row["timeline_revision"],
            effective_from=row["effective_from"],
            correction_of=None,
        )
        for row in rows
    ]
