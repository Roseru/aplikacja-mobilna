"""Durable anonymous intent before unlink; orphan sweep respects active IO locks."""

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai import repository as repo
from calorie_app.modules.ai.storage import PhotoStorage


def sweep(engine, factory, root, batch=100):
    if not 1 <= batch <= 1000:
        raise ValueError("invalid cleanup batch")
    # Retention also runs in a quiet environment with unavailable image storage.
    with factory() as session:
        owners = list(
            session.scalars(text("SELECT app.e7_receipt_cleanup_owners(:batch)"), {"batch": batch})
        )
        session.commit()
    for owner in owners:
        with factory() as session:
            repo.call(
                session, "SELECT app.e7_prune_receipts(:owner,:batch)", owner=owner, batch=batch
            )
            session.commit()
    with factory() as session:
        repo.call(session, "SELECT app.e7_prune_ledger(:batch)", batch=batch)
        session.commit()
    if root is None:
        return {"expired": 0, "removed": 0, "storage_available": False}
    storage = PhotoStorage(root)
    if not storage.availability():
        return {"expired": 0, "removed": 0, "storage_available": False}
    with factory() as session:
        ids = list(
            session.scalars(
                text(
                    "SELECT id FROM app.ai_analyses WHERE storage_key IS NOT NULL "
                    "AND (photo_expires_at<=clock_timestamp() OR state IN ('succeeded','failed')) "
                    "ORDER BY photo_expires_at,id LIMIT :batch"
                ),
                {"batch": batch},
            )
        )
    for analysis_id in ids:
        with factory() as session:
            repo.call(session, "SELECT app.e7_expire_photo(:id)", id=analysis_id)
            session.commit()
    with factory() as session:
        intents = list(
            session.scalars(
                text(
                    "SELECT storage_key FROM app.ai_cleanup_intents "
                    "ORDER BY created_at,storage_key LIMIT :batch"
                ),
                {"batch": batch},
            )
        )
    candidates = storage.candidates(grace_seconds=300, limit=batch)
    removed = 0
    for key in dict.fromkeys(intents + candidates):
        with engine.connect() as connection, Session(bind=connection) as session:
            lock = "e7-storage:" + key
            if not repo.lock_session(session, lock):
                session.rollback()
                continue
            try:
                if not repo.call(session, "SELECT app.e7_cleanup_candidate(:key)", key=key):
                    session.commit()
                    continue
                session.commit()
                # No transaction or row lock is open during filesystem operations.
                storage.delete(key)
                repo.call(session, "SELECT app.e7_cleanup_ack(:key)", key=key)
                session.commit()
                removed += 1
            except (OSError, DomainError, SQLAlchemyError):
                session.rollback()  # Intent stays durable for the next sweep.
            finally:
                session.rollback()
                repo.unlock_session(session, lock)
                session.commit()
    return {"expired": len(ids), "removed": removed, "storage_available": True}
