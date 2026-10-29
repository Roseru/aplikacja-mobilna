"""Owned Native retention port; reuses worker.py, without a supervisor or SQL IO."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from . import native

ENTRYPOINT = "infra/integration/worker.py"
LIMITS = {
    "RETENTION_INTERVAL_SECONDS": (60, 5, 86400),
    "RETENTION_RETRY_SECONDS": (60, 1, 3600),
    "RETENTION_PASS_SECONDS": (120, 1, 300),
    "RETENTION_BATCH": (1000, 1, 1000),
    "RETENTION_MAX_OWNERS": (1000, 1, 10000),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def configuration(stack, raw=None):
    """Hash, parse and launch from the same bytes; never return a public DSN."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    raw = (stack.state / "worker.env").read_bytes() if raw is None else raw
    try:
        require(
            type(stack.config["pg_port"]) is int and 1024 <= stack.config["pg_port"] <= 65535,
            "Invalid PG port",
        )
        values = {}
        for line in raw.decode().splitlines():
            key, separator, value = line.partition("=")
            require(separator and key not in values, "Invalid retention environment")
            values[key] = value
        require(set(values) <= {"DATABASE_URL", "ENVIRONMENT", *LIMITS}, "Unsafe retention field")
        url = make_url(values["DATABASE_URL"])
        require(
            url.drivername == "postgresql+psycopg"
            and url.host == "127.0.0.1"
            and url.port == stack.config["pg_port"]
            and url.database == "calorie_app"
            and url.username == "calorie_app_worker"
            and bool(url.password)
            and not url.query,
            "Retention target differs",
        )
        require(
            values.get("ENVIRONMENT", "development") in {"development", "test"},
            "Retention environment differs",
        )
        values.setdefault("ENVIRONMENT", "development")
        schedule = {}
        for key, (default, low, high) in LIMITS.items():
            value = int(values.get(key, default))
            require(low <= value <= high, "Retention bound differs")
            values[key] = str(value)
            schedule[key] = value
    except (KeyError, ValueError, TypeError, UnicodeError, ArgumentError):
        raise ValueError("Invalid Native retention environment/target") from None
    metadata = {
        "target": {
            "driver": "postgresql+psycopg",
            "host": "127.0.0.1",
            "port": url.port,
            "database": "calorie_app",
            "role": "calorie_app_worker",
        },
        "env_file_sha256": digest(raw),
        "effective_sha256": digest(json.dumps(values, sort_keys=True).encode()),
        "schedule": schedule,
        "entrypoint_sha256": digest((native.ROOT / ENTRYPOINT).read_bytes()),
    }
    return stack.env() | values, metadata


def argv(stack, state):
    return [str(stack.python), "-B", str(native.ROOT / ENTRYPOINT), "serve", "--state", str(state)]


def descriptor(stack, binding):
    value = binding["retention"]
    process = value["process"]
    require(
        isinstance(process, dict)
        and set(process) == {"pid", "created", "executable"}
        and type(process["pid"]) is int
        and process["pid"] > 0
        and type(process["created"]) is int
        and process["created"] > 0
        and Path(process["executable"]).resolve() == Path(stack.python).resolve(),
        "Worker configured executable differs",
    )
    UUID(value["generation"])
    require(
        "generation" not in binding or value["generation"] == binding["generation"],
        "Worker generation differs",
    )
    path = native.confined(Path(value["state"]))
    require(path == stack.state / "retention-worker" / value["generation"], "Foreign worker state")
    require(value["argv"] == argv(stack, path), "Worker argv differs")
    require(
        value["configuration"]["target"]
        == {
            "driver": "postgresql+psycopg",
            "host": "127.0.0.1",
            "port": stack.config["pg_port"],
            "database": "calorie_app",
            "role": "calorie_app_worker",
        },
        "Worker target differs",
    )
    require(
        value["configuration"]["entrypoint_sha256"]
        == digest((native.ROOT / ENTRYPOINT).read_bytes()),
        "Worker source changed",
    )
    require(value["log"] == str(path / "stdout.private.log"), "Foreign worker log")
    require(not (path / ".env").exists(), "Worker cwd has dotenv fallback")
    require(
        value["data"] == str(stack.state / "postgres")
        and value["control_identity"]
        == (stack.state / "postgres/global/pg_control").read_bytes()[:8].hex(),
        "Worker physical PG differs",
    )
    return value, path


def qualify(stack, binding):
    try:
        return _qualify(stack, binding)
    except (KeyError, TypeError, ValueError):
        raise ValueError("Worker pass/identity/configuration is not qualified") from None


def _qualify(stack, binding):
    require(not binding.get("retention_launch_unresolved", False), "Unresolved worker launch")
    value, path = descriptor(stack, binding)
    require(value["configuration"] == configuration(stack)[1], "Worker configuration drift")
    record = json.loads((stack.state / "worker.process.json").read_bytes())
    require(
        record == value["process"]
        and native.identity(record["pid"]) == record
        and Path(record["executable"]).resolve() == Path(stack.python).resolve(),
        "Worker identity differs",
    )
    raw = native.confined(path / "status.json").read_bytes()
    require(len(raw) <= 65536, "Worker status oversized")
    status = json.loads(raw)
    instant = datetime.now(UTC)
    launched = datetime.fromisoformat(value["launched_at"])
    success = datetime.fromisoformat(status["last_success"])
    attempt = datetime.fromisoformat(status["last_attempt"])
    maximum_age = (
        value["configuration"]["schedule"]["RETENTION_INTERVAL_SECONDS"]
        + 2 * value["configuration"]["schedule"]["RETENTION_PASS_SECONDS"]
        + value["configuration"]["schedule"]["RETENTION_RETRY_SECONDS"]
    )
    require(
        status["state"] in {"ok", "pending", "running"}
        and status["errors"] == 0
        and launched <= success <= instant
        and launched <= attempt <= instant
        and (instant - success).total_seconds() <= maximum_age,
        "Worker pass unhealthy/stale",
    )
    # This witness is deliberately separate from the immutable runtime binding.
    return {
        "state": status["state"],
        "last_success": status["last_success"],
        "maximum_age_seconds": maximum_age,
        "status_sha256": digest(raw),
        "bounded_pass_healthy": True,
        "pending": status.get("pending"),
        "zero_backlog_claim": False,
    }


def publish(stack, binding):
    binding["processes"] = {
        p.name: json.loads(p.read_bytes()) for p in stack.state.glob("*.process.json")
    }
    native.write_json(stack.state / "runtime-binding.json", binding)


def start(stack, binding, *, raw=None, resume=None):
    env, config = configuration(stack, raw)
    require(config == binding["configuration"]["retention"], "Retention admission cohort differs")
    require(not (stack.state / "worker.process.json").exists(), "Existing worker marker preserved")
    pg = json.loads((stack.state / "postgres.process.json").read_bytes())
    pid = (stack.state / "postgres/postmaster.pid").read_text().splitlines()
    require(
        native.identity(pg["pid"]) == pg
        and Path(pg["executable"]).resolve() == (stack.pg / "postgres.exe").resolve()
        and int(pid[0]) == pg["pid"]
        and Path(pid[1]).resolve() == stack.state / "postgres"
        and int(pid[3]) == stack.config["pg_port"],
        "Worker PG target identity differs",
    )
    generation = binding["generation"]
    UUID(generation)
    path = native.confined(stack.state / "retention-worker" / generation)
    require(not path.exists(), "Existing worker state preserved")
    from backup import private_directory

    private_directory(path)
    value = {
        "generation": generation,
        "state": str(path),
        "argv": argv(stack, path),
        "configuration": config,
        "launched_at": datetime.now(UTC).isoformat(),
        "process": None,
        "log": str(path / "stdout.private.log"),
        "data": str(stack.state / "postgres"),
        "control_identity": (stack.state / "postgres/global/pg_control").read_bytes()[:8].hex(),
    }
    if resume is not None:
        # Only the never-restored original source may preserve its fairness cursor.
        require(binding.get("lifecycle", {}).get("kind") == "source", "Target cursor reuse refused")
        previous, previous_path = descriptor(stack, {"retention": resume})
        require(previous["state"] != str(path), "Worker state reuse refused")
        progress = native.confined(previous_path / "progress.json")
        if progress.exists():
            raw_progress = progress.read_bytes()
            require(len(raw_progress) <= 65536, "Worker progress oversized")
            parsed = json.loads(raw_progress)
            UUID(parsed["cursor"])
            require(type(parsed["sweep_pending"]) is bool, "Invalid source cursor")
            native.private_write(path / "progress.json", raw_progress.decode())
            value["source_progress_sha256"] = digest(raw_progress)
    binding["retention"] = value
    binding["retention_launch_unresolved"] = True
    publish(stack, binding)
    try:
        stack.launch("worker", value["argv"], env, cwd=path, log_path=Path(value["log"]))
        binding["retention_launch_unresolved"] = False
    finally:
        marker = stack.state / "worker.process.json"
        if marker.exists():
            value["process"] = json.loads(marker.read_bytes())
        publish(stack, binding)
    # A new private generation has no inherited last_success/status. No supervisor:
    # one bounded startup wait, and later qualification fails rather than restarts.
    deadline = time.monotonic() + config["schedule"]["RETENTION_PASS_SECONDS"] + 10
    while True:
        require(
            native.identity(value["process"]["pid"]) == value["process"], "Worker died during start"
        )
        try:
            witness = qualify(stack, binding)
            break
        except (OSError, ValueError, KeyError, TypeError):
            if time.monotonic() >= deadline:
                raise RuntimeError("No fresh successful retention pass") from None
            time.sleep(0.1)
    native.write_json(path / "launch.private.json", value | {"first_pass": witness})
    return value


def stop(stack, binding):
    value, path = descriptor(stack, binding)
    record = json.loads((stack.state / "worker.process.json").read_bytes())
    require(
        record == value["process"]
        and Path(record["executable"]).resolve() == Path(stack.python).resolve(),
        "Worker stop marker differs",
    )
    receipt = {
        "format": "native-retention-stop/v1",
        "generation": value["generation"],
        "process": record,
        "argv": value["argv"],
        "configuration": value["configuration"],
        "at": datetime.now(UTC).isoformat(),
        "result": "FAIL",
        "termination": {
            "method": "qualified_handle_attempt",
            "forced": None,
            "graceful": False,
            "wait": "UNKNOWN",
            "exit_observed": False,
            "exit_code": None,
        },
    }
    target = path / ("stop-" + uuid4().hex + ".private.json")
    try:
        receipt["termination"] = native.stop_owned(record)
        try:
            current = native.identity(record["pid"])
        except ProcessLookupError:
            current = None
        require(current != record, "Worker remains after stop")
        receipt["result"] = (
            "STOPPED" if receipt["termination"]["exit_observed"] else "STOPPED_UNKNOWN_EXIT"
        )
    finally:
        receipt["log_sha256"] = (
            digest(Path(value["log"]).read_bytes()) if Path(value["log"]).exists() else None
        )
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        encoded = (json.dumps(receipt, indent=2) + "\n").encode()
        native.private_write(target, encoded.decode())
    reference = {"path": str(target), "sha256": digest(encoded), "result": receipt["result"]}
    binding["retention_last_stop"] = reference
    binding["retention_launch_unresolved"] = False
    if reference["result"] != "STOPPED":
        binding["retention_unknown_exit"] = True
    # Keep the stale marker until receipt and sticky uncertainty are durable.
    # An IO failure must not erase the only evidence that this exit is unknown.
    publish(stack, binding)
    (stack.state / "worker.process.json").unlink()
    publish(stack, binding)
    return reference
