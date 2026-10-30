"""Synthetic four-process metadata shared by the affected Native unit fixtures."""

from datetime import UTC, datetime
from pathlib import Path

from infra.local.integration import native, retention

RUNNER_BYTES = (Path(__file__).resolve().parents[1] / "worker.py").read_bytes()


def worker_files(stack):
    runner = native.ROOT / retention.ENTRYPOINT
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_bytes(RUNNER_BYTES)
    control = stack.state / "postgres/global/pg_control"
    control.parent.mkdir(parents=True, exist_ok=True)
    if not control.exists():
        control.write_bytes(b"ID123456synthetic control")
    if not (stack.state / "worker.env").exists():
        (stack.state / "worker.env").write_text(
            f"DATABASE_URL=postgresql+psycopg://calorie_app_worker:synthetic@127.0.0.1:{stack.config['pg_port']}/calorie_app\n"
        )


def seed_worker(stack, binding, record):
    worker_files(stack)
    path = stack.state / "retention-worker" / binding["generation"]
    path.mkdir(parents=True)
    value = {
        "generation": binding["generation"],
        "state": str(path),
        "argv": retention.argv(stack, path),
        "configuration": stack.worker_configuration()[1],
        "launched_at": datetime.now(UTC).isoformat(),
        "process": record,
        "log": str(path / "stdout.private.log"),
        "data": str(stack.state / "postgres"),
        "control_identity": (stack.state / "postgres/global/pg_control").read_bytes()[:8].hex(),
    }
    native.write_json(
        path / "status.json",
        {
            "state": "pending",
            "last_attempt": datetime.now(UTC).isoformat(),
            "last_success": datetime.now(UTC).isoformat(),
            "errors": 0,
            "pending": True,
        },
    )
    (path / "stdout.private.log").write_bytes(b"synthetic retention log\n")
    native.write_json(stack.state / "worker.process.json", record)
    binding["retention"] = value
    binding["processes"]["worker.process.json"] = record
    binding["configuration"] = stack.configuration_binding()
    return value
