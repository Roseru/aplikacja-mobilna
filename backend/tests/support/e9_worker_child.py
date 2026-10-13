"""Actual typed Runner in a minimal worker LOGIN, with bounded test-only barriers."""

import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.modules.jobs.runner import Runner


def main():
    raw = sys.stdin.readline(65537)
    if not raw or len(raw.encode("utf-8")) > 65536:
        return 2
    request = json.loads(raw)
    engine = create_engine(request["database_url"], hide_parameters=True)
    try:
        with engine.connect() as c:
            assert c.scalar(text("SELECT current_user=session_user"))
            for role in ("calorie_app_api", "calorie_app_worker", "calorie_app_migrator"):
                assert not c.scalar(
                    text("SELECT pg_has_role(current_user,:role,'MEMBER')"), {"role": role}
                )
            assert c.scalar(
                text(
                    "SELECT NOT(rolsuper OR rolcreatedb OR rolcreaterole OR rolre"
                    "plication OR rolbypassrls) FROM pg_roles WHERE rolname=curre"
                    "nt_user"
                )
            )
        settings = Settings(
            database_url=request["database_url"],
            environment="test",
            ai_photo_root=Path(request["photo_root"]),
        )
        paused = False

        def hook(boundary, claim):
            nonlocal paused
            if boundary == request.get("pause") and not paused:
                paused = True
                print(json.dumps({"event": "paused", "boundary": boundary}), flush=True)
                if sys.stdin.readline(128).strip() != "continue":
                    raise SystemExit(2)

        print('{"event":"ready"}', flush=True)
        handled = Runner(engine, lambda: Session(engine), settings, hook=hook).process(
            UUID(request["job_id"])
        )
        print(json.dumps({"event": "done", "handled": handled}), flush=True)
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
