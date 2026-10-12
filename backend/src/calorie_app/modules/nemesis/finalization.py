"""One bounded projection-only batch with transaction-safe transient retry."""

import argparse
import json
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from calorie_app.core.config import Settings
from calorie_app.health import EXPECTED_REVISION


def finalize(engine, batch=100):
    if type(batch) is not int or not 1 <= batch <= 1000:
        raise ValueError("Nemesis batch must be in 1..1000")
    for attempt in range(3):
        try:
            # Each retry receives a new transaction and a new database clock.
            with engine.begin() as connection:
                if not 170000 <= int(connection.scalar(text("SHOW server_version_num"))) < 180000:
                    raise ValueError("PostgreSQL 17 required")
                if set(connection.scalars(text("SELECT version_num FROM app.alembic_version"))) != {
                    EXPECTED_REVISION
                }:
                    raise ValueError("Nemesis schema is not ready")
                result = connection.scalar(
                    text("SELECT app.e8n_finalize_batch(:batch)"), {"batch": batch}
                )
            return result
        except DBAPIError as error:
            sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
            if sqlstate not in {"40001", "40P01"} or attempt == 2:
                raise


def main():
    parser = argparse.ArgumentParser(description="Bounded Nemesis projection-only finalization")
    parser.add_argument("--batch", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.batch <= 1000:
        parser.error("batch must be in 1..1000")
    engine = None
    try:
        settings = Settings()
        engine = create_engine(settings.database_url.get_secret_value(), hide_parameters=True)
        result = finalize(engine, args.batch)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ready") else 2
    except Exception:
        print("Nemesis finalization failed; inspect privileged diagnostics", file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
