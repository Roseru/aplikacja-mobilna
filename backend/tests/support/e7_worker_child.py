"""Test-only real Runner process; bounded stdin config, IPC hooks, no API bypass."""

import json
import os
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.integrations.gemini import transport as provider_transport
from calorie_app.modules.ai.cleanup import sweep
from calorie_app.modules.jobs.runner import Runner


def emit(event, **fields):
    print(json.dumps({"event": event, **fields}, separators=(",", ":")), flush=True)


def barrier():
    if sys.stdin.readline(128).strip() != "continue":
        raise SystemExit(2)


def main():
    raw = sys.stdin.readline(65537)
    if not raw or len(raw.encode("utf-8")) > 65536:
        return 2
    request = json.loads(raw)
    engine = create_engine(request["database_url"], hide_parameters=True)
    settings = Settings(
        database_url=request["database_url"],
        environment="test",
        ai_photo_root=Path(request["photo_root"]),
    )
    occurrences = {}
    targets = {(item["boundary"], item["occurrence"]) for item in request.get("pause", [])}

    def hook(boundary, claimed):
        occurrences[boundary] = occurrences.get(boundary, 0) + 1
        occurrence = occurrences[boundary]
        paused = (boundary, occurrence) in targets
        emit(
            "hook",
            boundary=boundary,
            occurrence=occurrence,
            paused=paused,
            job_id=claimed["job_id"],
            pid=os.getpid(),
        )
        if paused:
            barrier()

    original_popen = provider_transport.subprocess.Popen

    def observed_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        communicate = process.communicate

        def observed_communicate(input=None, timeout=None):
            if input is not None:
                payload = json.loads(input)
                emit("transport_child", pid=process.pid, deadline=payload["deadline_monotonic"])
                # The parent test opens an exact handle/pidfd before send.
                barrier()
            return communicate(input, timeout=timeout)

        process.communicate = observed_communicate
        return process

    provider_transport.subprocess.Popen = observed_popen

    def fake_rest(provider, call_kind, image, config, timeout_seconds):
        # Real Runner/profile/consent/pool/dispatch; redirect only this test's IO.
        return provider_transport.execute(
            "gemini",
            call_kind,
            image,
            {
                "_test_base_url": request["fake_url"],
                "test_fixture_adapter": True,
                "environment": "test",
                "model": "gemini-3.5-flash-lite",
                "api_key": "synthetic-process-fixture",
            },
            min(timeout_seconds, request.get("transport_seconds", 20)),
        )

    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT current_user").scalar()
            assert connection.exec_driver_sql(
                "SELECT pg_has_role(current_user,'calorie_app_ai_worker','MEMBER')"
            ).scalar()
            assert not connection.exec_driver_sql(
                "SELECT pg_has_role(current_user,'calorie_app_worker','MEMBER')"
            ).scalar()
            assert connection.exec_driver_sql(
                "SELECT NOT(rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                "OR rolbypassrls) FROM pg_roles WHERE rolname=current_user"
            ).scalar()
        runner = Runner(engine, lambda: Session(engine), settings, hook=hook, transport=fake_rest)
        emit("ready", pid=os.getpid())
        barrier()
        handled = runner.process(UUID(request["job_id"]))
        sweep(engine, lambda: Session(engine), settings.ai_photo_root, 100)
        emit("done", handled=handled, pid=os.getpid())
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
