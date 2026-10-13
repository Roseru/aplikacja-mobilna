"""Independent source-derived motivation worker; immediate startup catch-up."""

import argparse
import json
import signal
import threading
from time import monotonic

from sqlalchemy import text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.db.session import make_engine
from calorie_app.health import EXPECTED_REVISION
from calorie_app.modules.analytics.motivation import repository


def valid_role(connection):
    return (
        bool(
            connection.scalar(
                text("""
        SELECT pg_has_role(current_user,'calorie_app_motivation_worker','MEMBER')
        AND NOT (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole
                 OR r.rolreplication OR r.rolbypassrls)
        AND NOT has_schema_privilege(current_user,'app','CREATE')
        AND NOT EXISTS(SELECT 1 FROM pg_tables t WHERE schemaname='app' AND (
            has_table_privilege(current_user,format('%I.%I',schemaname,tablename),
                'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
            OR has_any_column_privilege(current_user,format('%I.%I',schemaname,tablename),
                'INSERT,UPDATE,REFERENCES')
            OR (tablename NOT IN('alembic_version','installation_state') AND
                has_any_column_privilege(current_user,format('%I.%I',schemaname,tablename),'SELECT'))))
        FROM pg_roles r WHERE r.rolname=current_user
    """)
            )
        )
        and connection.scalar(text("SELECT version_num FROM app.alembic_version"))
        == EXPECTED_REVISION
    )


def cycle(engine, owner_batch=100, date_batch=256):
    # Candidate discovery takes no projection lock. Each owner is rechecked in
    # its own transaction, with account -> counter -> projections lock order.
    with Session(engine) as session, session.begin():
        owners = repository.candidates(session, owner_batch)
    processed, handled = 0, 0
    for owner in owners:
        with Session(engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout='5s'"))
            result = repository.process_owner(session, owner, date_batch)
            processed += result.get("processed", 0)
            handled += 1
    with Session(engine) as session, session.begin():
        session.scalar(text("SELECT app.e8_prune_ranking_sessions(:batch)"), {"batch": owner_batch})
        status = repository.backlog(session)
    return {"owners_handled": handled, "dates_processed": processed, "backlog": status}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Server-confirmed regularity motivation worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--batch", type=int, default=100)
    parser.add_argument("--date-batch", type=int, default=256)
    args = parser.parse_args(argv)
    if not 1 <= args.batch <= 1000 or not 1 <= args.date_batch <= 1000:
        parser.error("batch and date-batch must be 1..1000")
    engine = make_engine(Settings())
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    try:
        with engine.connect() as connection:
            if not valid_role(connection):
                print(
                    json.dumps(
                        {
                            "status": "unavailable",
                            "code": "motivation_worker_role_or_schema_invalid",
                        }
                    )
                )
                return 2
        if args.status:
            with Session(engine) as session, session.begin():
                print(
                    json.dumps(
                        {"status": "ok", "backlog": repository.backlog(session)}, default=str
                    )
                )
            return 0
        while not stopped.is_set():
            started = monotonic()
            result = cycle(engine, args.batch, args.date_batch)
            print(json.dumps({"status": "ok", **result}, default=str), flush=True)
            if args.once:
                return 0
            # Startup immediately processes the first bounded catch-up portion.
            # Backlog remains observable during downtime recovery; repeat cycles
            # never depend on a new client write and cannot duplicate a day key.
            stopped.wait(max(0, 60 - (monotonic() - started)))
        return 0
    except Exception:
        print(
            json.dumps({"status": "unavailable", "code": "motivation_worker_unavailable"}),
            flush=True,
        )
        return 2
    finally:
        stopped.set()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
