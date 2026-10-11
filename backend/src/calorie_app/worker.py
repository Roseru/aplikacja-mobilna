"""AI worker CLI. Startup and every minute sweep private photos; no external scheduler."""

import argparse
import json
import signal
import threading
from time import monotonic

from sqlalchemy import text

from calorie_app.core.config import Settings
from calorie_app.db.session import make_engine, session_factory
from calorie_app.health import EXPECTED_REVISION
from calorie_app.modules.ai.cleanup import sweep
from calorie_app.modules.jobs.runner import Runner


def main(argv=None):
    parser = argparse.ArgumentParser(description="Durable consent-bound AI worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sweep-only", action="store_true")
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args(argv)
    if not 1 <= args.batch <= 1000:
        parser.error("batch must be 1..1000")
    settings = Settings()
    engine = make_engine(settings)
    factory = session_factory(engine)
    stopped = threading.Event()
    cleanup_thread = None
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    try:
        with engine.connect() as connection:
            role = connection.scalar(text("SELECT current_user"))
            allowed = connection.scalar(
                text("SELECT pg_has_role(current_user,'calorie_app_ai_worker','MEMBER')")
            )
            head = connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            privileged = connection.scalar(
                text(
                    "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            )
            writes = connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='app' AND "
                    "(has_table_privilege(current_user,format('%I.%I',schemaname,tablename),"
                    "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN') OR "
                    "has_any_column_privilege(current_user,format('%I.%I',schemaname,tablename),"
                    "'INSERT,UPDATE,REFERENCES'))) OR "
                    "has_schema_privilege(current_user,'app','CREATE')"
                )
            )
        if (
            not allowed
            or privileged
            or writes
            or role
            in {
                "calorie_app_api",
                "calorie_app_worker",
                "calorie_app_migrator",
                "calorie_app_deletion_operator",
            }
            or head != EXPECTED_REVISION
        ):
            print(json.dumps({"status": "unavailable", "code": "worker_role_or_schema_invalid"}))
            return 2
        sweep(engine, factory, settings.ai_photo_root, args.batch)
        if not args.sweep_only:

            def periodic_cleanup():
                while not stopped.wait(60):
                    try:
                        sweep(engine, factory, settings.ai_photo_root, args.batch)
                    except Exception:
                        print(json.dumps({"event": "photo_cleanup_failed"}), flush=True)

            cleanup_thread = threading.Thread(
                target=periodic_cleanup, daemon=True, name="photo-cleanup"
            )
            cleanup_thread.start()
        runner = Runner(engine, factory, settings, stop=stopped.is_set)
        while not stopped.is_set():
            started = monotonic()
            if args.sweep_only:
                result = sweep(engine, factory, settings.ai_photo_root, args.batch)
            else:
                result = {"handled": runner.cycle(args.batch)}
            if args.once:
                print(json.dumps({"status": "ok", **result}))
                return 0
            stopped.wait(max(0, min(60 if args.sweep_only else 1, 60 - (monotonic() - started))))
        return 0
    except Exception:
        print(json.dumps({"status": "unavailable", "code": "ai_worker_unavailable"}))
        return 2
    finally:
        stopped.set()
        if cleanup_thread is not None:
            cleanup_thread.join(timeout=5)
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
