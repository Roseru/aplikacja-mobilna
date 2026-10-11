"""One catalog lock serializes community decisions and official activation."""

from sqlalchemy import text


def catalog_lock(session, *, shared=False):
    """Acquire transaction-held lock after account locks, before package locks."""
    return session.execute(
        text("SELECT * FROM app.lock_community_catalog(:shared)"), {"shared": shared}
    ).one()


def bump_catalog(session, *, queue=False):
    return session.scalar(text("SELECT app.bump_community_catalog(:queue)"), {"queue": queue})
