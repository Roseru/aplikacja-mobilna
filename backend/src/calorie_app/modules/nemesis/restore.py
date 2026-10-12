"""Bounded migrator-only cancellation after an externally restored new epoch.

Traffic/workers stay stopped until this sweep completes. It never rotates the
shared epoch, reopens capability or restores participant consent.
"""

import argparse
import json
import sys

from sqlalchemy import create_engine, text

from calorie_app.core.config import Settings
from calorie_app.health import EXPECTED_REVISION


def restore_batch(engine, batch=100):
    if type(batch) is not int or not 1 <= batch <= 1000:
        raise ValueError("Nemesis batch must be in 1..1000")
    with engine.begin() as connection:
        if not 170000 <= int(connection.scalar(text("SHOW server_version_num"))) < 180000:
            raise ValueError("PostgreSQL 17 required")
        if set(connection.scalars(text("SELECT version_num FROM app.alembic_version"))) != {
            EXPECTED_REVISION
        }:
            raise ValueError("Nemesis schema is not ready")
        result = connection.scalar(
            text("SELECT app.e8n_restore_maintain(:batch)"), {"batch": batch}
        )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="One bounded restore cancellation batch; never reopens Nemesis"
    )
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch <= 1000:
        parser.error("batch must be in 1..1000")
    engine = None
    try:
        settings = Settings()
        engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
        print(json.dumps(restore_batch(engine, args.batch), sort_keys=True))
        return 0
    except Exception:
        print("Nemesis restore failed; inspect privileged diagnostics", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
