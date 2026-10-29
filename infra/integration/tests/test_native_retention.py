"""R1 source-only boundaries. Every command/SQL/HTTP/process operation is fake."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from infra.integration.tests.test_native_existing import (
    bound_target,
    captured,
    load,
    maintenance_proof,
    world,
)
from infra.local.integration import native, retention
from infra.local.integration import native_existing as e

__all__ = ["world"]
REAL_LAUNCH = native.Native.launch


@pytest.mark.parametrize(
    "change",
    [
        "@postgres:",
        "@127.0.0.2:",
        ":25431/",
        "/keycloak",
        "calorie_app_api:",
        "postgresql+psycopg2:",
        "?host=foreign",
        "?service=foreign",
        "broken-url",
        "PGHOST=foreign",
        "PYTHONPATH=foreign",
        "RETENTION_UNKNOWN=1",
        "RETENTION_INTERVAL_SECONDS=0",
        "RETENTION_MAX_OWNERS=10001",
        "duplicate",
    ],
)
def test_worker_target_and_environment_refuse_before_launch(world, change):
    raw = (world.source.state / "worker.env").read_bytes().decode()
    if change.startswith("@"):
        raw = raw.replace("@127.0.0.1:", change)
    elif change.startswith(":"):
        raw = raw.replace(":25432/", change)
    elif change.startswith("/"):
        raw = raw.replace("/calorie_app", change)
    elif change.startswith("calorie_"):
        raw = raw.replace("calorie_app_worker:", change)
    elif change.startswith("postgresql"):
        raw = raw.replace("postgresql+psycopg:", change)
    elif change.startswith("?"):
        raw = raw.strip() + change + "\n"
    elif change == "broken-url":
        raw = "DATABASE_URL=not-a-url\n"
    elif change == "duplicate":
        raw += "DATABASE_URL=foreign\n"
    else:
        raw += change + "\n"
    world.events.clear()
    with pytest.raises(ValueError, match="retention environment/target"):
        world.source.worker_configuration(raw.encode())
    assert world.events == []


def test_defaults_and_explicit_bounded_overrides_preserve_password(world):
    raw = (world.source.state / "worker.env").read_bytes()
    env, spec = world.source.worker_configuration(raw)
    assert env["DATABASE_URL"].endswith("restored@127.0.0.1:25432/calorie_app")
    assert env["RETENTION_INTERVAL_SECONDS"] == env["RETENTION_RETRY_SECONDS"] == "60"
    env, changed = world.source.worker_configuration(
        raw + b"RETENTION_INTERVAL_SECONDS=90\nRETENTION_BATCH=70\n"
    )
    assert env["DATABASE_URL"] == (raw.decode().strip().split("=", 1)[1])
    assert changed["schedule"]["RETENTION_INTERVAL_SECONDS"] == 90
    assert changed["schedule"]["RETENTION_BATCH"] == 70
    assert "restored" not in json.dumps(spec) and "DATABASE_URL" not in json.dumps(spec)


@pytest.mark.parametrize(
    "damage", ["failed", "stopped", "old", "future", "no-first", "dead", "reused", "dotenv"]
)
def test_running_needs_fresh_live_worker_not_cached_success(world, damage):
    binding = load(world.source.state / "runtime-binding.json")
    value = binding["retention"]
    path = Path(value["state"])
    status = load(path / "status.json")
    if damage in {"failed", "stopped"}:
        status["state"] = damage
    if damage in {"old", "no-first"}:
        status["last_success"] = (
            datetime.fromisoformat(value["launched_at"]) - timedelta(seconds=1)
        ).isoformat()
        if damage == "no-first":
            status["state"] = "running"
    if damage == "future":
        status["last_success"] = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
    if damage == "dead":
        world.live.pop(value["process"]["pid"])
    if damage == "reused":
        world.live[value["process"]["pid"]] = value["process"] | {"created": 9}
    if damage == "dotenv":
        (path / ".env").write_text("DATABASE_URL=foreign")
    native.write_json(path / "status.json", status)
    world.events.clear()
    with pytest.raises((ValueError, ProcessLookupError)):
        world.source.require_running()
    assert world.events == []  # no automatic worker restart


def test_pending_health_is_separate_witness_and_does_not_mutate_binding(world):
    before = (world.source.state / "runtime-binding.json").read_bytes()
    a = world.source.require_running()
    witness = world.source.qualify_worker(a)
    assert witness["pending"] and not witness["zero_backlog_claim"]
    assert world.source.require_running() == a
    assert (world.source.state / "runtime-binding.json").read_bytes() == before


@pytest.mark.parametrize("reuse", [False, True])
def test_windows_stop_qualifies_waits_reads_exit_on_same_handle(monkeypatch, reuse):
    record = {"pid": 123, "created": 456, "executable": "qualified-python.exe"}
    handle = object()
    calls = []

    class Kernel:
        def OpenProcess(self, rights, inherit, pid):
            calls.append(("open", pid))
            return handle

        def WaitForSingleObject(self, current, milliseconds):
            assert current is handle
            calls.append(("wait", milliseconds))
            return 258 if milliseconds == 0 else 0

        def TerminateProcess(self, current, code):
            assert current is handle
            calls.append(("forced", code))
            return True

        def GetExitCodeProcess(self, current, output):
            assert current is handle
            calls.append(("exit",))
            output._obj.value = 37  # actual simulated handle exit, not command code0
            return True

        def CloseHandle(self, current):
            assert current is handle
            calls.append(("close",))

    kernel = Kernel()
    monkeypatch.setattr(native, "process_kernel", lambda: kernel)

    def qualify(k, h, pid):
        assert k is kernel and h is handle and pid == 123
        calls.append(("identity",))
        return record | {"created": 9} if reuse else record

    monkeypatch.setattr(native, "handle_identity", qualify)
    if reuse:
        with pytest.raises(RuntimeError, match="reused"):
            native.stop_owned(record)
        assert calls == [("open", 123), ("identity",), ("close",)]
    else:
        stopped = native.stop_owned(record)
        assert calls == [
            ("open", 123),
            ("identity",),
            ("wait", 0),
            ("forced", 1),
            ("wait", 10000),
            ("exit",),
            ("close",),
        ]
        assert stopped["exit_code"] == 37 and stopped["forced"] and not stopped["graceful"]


def test_fast_worker_exit_cannot_publish_reused_pid(world, monkeypatch):
    state = world.source.state
    (state / "worker.process.json").unlink()
    polls = iter([None, 2, 2])
    child = SimpleNamespace(pid=987, poll=lambda: next(polls))
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_a, **_k: child)
    monkeypatch.setattr(
        native, "identity", lambda _pid: {"pid": 987, "created": 999, "executable": "foreign"}
    )
    with pytest.raises(native.WorkerLaunchFailed, match="identity publication"):
        REAL_LAUNCH(world.source, "worker", [world.source.python], {}, cwd=state)
    assert not (state / "worker.process.json").exists()
    receipt = load(next(state.glob("launch-failed-*.private.json")))
    assert receipt["exit_code"] == 2 and not receipt["forced"]


def test_worker_confirmed_dead_before_capture_and_original_progress_retained(world, monkeypatch):
    original = load(world.source.state / "runtime-binding.json")["retention"]
    progress = Path(original["state"]) / "progress.json"
    progress.write_bytes(
        b'{"cursor":"00000000-0000-4000-8000-000000000007","sweep_pending":true}\n'
    )
    old_hba = (world.source.state / "postgres/pg_hba.conf").read_bytes()
    state, binding, proof = maintenance_proof(world, monkeypatch)
    assert not (state / "worker.process.json").exists()
    stops = list(Path(original["state"]).glob("stop-*.private.json"))
    assert len(stops) == 1 and load(stops[0])["termination"]["wait"] == "SIGNALED"
    ref = e.write_new(state / "r1-fence.private.json", proof)
    result = e.activate(state, binding["generation"], ref["path"], ref["sha256"])
    current = load(state / "runtime-binding.json")["retention"]
    assert current["state"] != original["state"] and current["generation"] == result["generation"]
    assert (Path(current["state"]) / "progress.json").read_bytes() == progress.read_bytes()
    assert (state / "postgres/pg_hba.conf").read_bytes() == old_hba


def test_capture_waits_for_worker_death_before_hba_zero_clients_and_dump(world, monkeypatch):
    state = world.source.state
    old_hba = (state / "postgres/pg_hba.conf").read_bytes()
    process = load(state / "worker.process.json")
    original_stop = native.stop_owned

    def checked_stop(record):
        assert record == process
        assert (state / "postgres/pg_hba.conf").read_bytes() == old_hba
        return original_stop(record)

    monkeypatch.setattr(native, "stop_owned", checked_stop)
    zero = e.zero_clients

    def checked_zero(pg):
        assert process["pid"] not in world.live and not (state / "worker.process.json").exists()
        return zero(pg)

    monkeypatch.setattr(e, "zero_clients", checked_zero)
    captured(world, monkeypatch)
    worker_index = world.events.index(("stop-service", process["pid"]))
    assert worker_index < next(i for i, x in enumerate(world.events) if x[0] == "reload")
    assert worker_index < next(i for i, x in enumerate(world.events) if x[0] == "dump")


def test_failed_or_unknown_worker_stop_refuses_seal_and_cannot_mint_resume(world, monkeypatch):
    hba = (world.source.state / "postgres/pg_hba.conf").read_bytes()
    original = native.stop_owned

    def unobserved(record):
        original(record)
        return {
            "method": "already_absent",
            "forced": False,
            "graceful": False,
            "wait": "NOT_OBSERVED",
            "exit_observed": False,
            "exit_code": None,
        }

    monkeypatch.setattr(native, "stop_owned", unobserved)
    with pytest.raises(ValueError, match="exit is unknown"):
        captured(world, monkeypatch)
    assert (world.source.state / "postgres/pg_hba.conf").read_bytes() == hba
    assert not any(x[0] == "dump" for x in world.events)
    binding = load(world.source.state / "runtime-binding.json")
    assert binding["retention_unknown_exit"]
    stopped = e.stop_existing(world.source.state, binding["generation"])
    assert load(stopped["path"])["result"] == "STOPPED_WORKER_UNKNOWN_EXIT"
    assert not load(stopped["path"])["automatic_resume_authorized"]


def test_worker_reuse_batch_refuses_before_any_service_or_hba_change(world):
    state = world.source.state
    binding = load(state / "runtime-binding.json")
    record = binding["retention"]["process"]
    world.live[record["pid"]] = record | {"created": 1}
    hba = (state / "postgres/pg_hba.conf").read_bytes()
    world.events.clear()
    with pytest.raises(ValueError, match="reused PID"):
        e.stop_existing(state, binding["generation"])
    assert world.events == [] and (state / "postgres/pg_hba.conf").read_bytes() == hba


def test_admitted_worker_env_is_held_and_drift_cleanup_has_no_resume(world, monkeypatch):
    stack = world.source
    binding = load(stack.state / "runtime-binding.json")
    stack.stop_worker(binding)
    binding["generation"] = str(__import__("uuid").uuid4())
    binding["state"] = "STARTING"
    raw = (stack.state / "worker.env").read_bytes()
    original = native.Native.launch

    def drift(stack, name, arguments, env, **kwargs):
        (stack.state / "worker.env").write_bytes(b"DATABASE_URL=foreign\n")
        return original(stack, name, arguments, env, **kwargs)

    monkeypatch.setattr(native.Native, "launch", drift)
    ticks = iter([0, 1000])
    monkeypatch.setattr(retention.time, "monotonic", lambda: next(ticks))
    world.events.clear()
    with pytest.raises(RuntimeError, match="fresh successful"):
        stack.start_worker(binding, raw=raw)
    launch = next(x for x in world.events if x[0] == "launch")
    assert launch[3]["DATABASE_URL"] == raw.decode().strip().split("=", 1)[1]
    stopped = e.stop_existing(stack.state, binding["generation"])
    assert load(stopped["path"])["result"] == "STOPPED_COHORT_DRIFT"
    assert not load(stopped["path"])["automatic_resume_authorized"]


def test_activation_worker_async_death_cleans_partial_resources_without_resume(world, monkeypatch):
    state, binding, proof = maintenance_proof(world, monkeypatch)
    original = native.Native.launch

    def dies(stack, name, arguments, env, **kwargs):
        result = original(stack, name, arguments, env, **kwargs)
        if name == "worker":
            world.live.pop(result.pid)
            raise RuntimeError("Synthetic worker async death")
        return result

    monkeypatch.setattr(native.Native, "launch", dies)
    ref = e.write_new(state / "r1-dies-fence.private.json", proof)
    with pytest.raises(RuntimeError, match="async death"):
        e.activate(state, binding["generation"], ref["path"], ref["sha256"])
    failed = load(state / "runtime-binding.json")
    assert failed["state"] == "ACTIVATION_FAILED" and failed["retention_unknown_exit"]
    assert not (state / "worker.process.json").exists()
    stopped = e.stop_existing(state, failed["generation"])
    assert load(stopped["path"])["result"] == "STOPPED_WORKER_UNKNOWN_EXIT"


def test_failed_worker_cleanup_still_closes_gateway_and_preserves_live_marker(world, monkeypatch):
    state, binding, proof = maintenance_proof(world, monkeypatch)
    original = native.stop_owned

    def denied(_record):
        raise PermissionError("Synthetic handle unavailable")

    monkeypatch.setattr(native, "stop_owned", denied)
    monkeypatch.setattr(
        e, "ready", lambda _s: (_ for _ in ()).throw(RuntimeError("Synthetic readiness failure"))
    )
    ref = e.write_new(state / "r1-cleanup-fence.private.json", proof)
    with pytest.raises(RuntimeError, match="readiness failure"):
        e.activate(state, binding["generation"], ref["path"], ref["sha256"])
    failed = load(state / "runtime-binding.json")
    assert failed["cleanup_errors"] == [{"service": "worker", "error_kind": "PermissionError"}]
    assert (
        not (state / "gateway.process.json").exists() and (state / "worker.process.json").exists()
    )
    worker = load(state / "worker.process.json")
    assert world.live[worker["pid"]] == worker
    receipt = load(next(Path(failed["retention"]["state"]).glob("stop-*.private.json")))
    assert receipt["result"] == "FAIL" and receipt["termination"]["exit_code"] is None
    monkeypatch.setattr(native, "stop_owned", original)
    stopped = e.stop_existing(state, failed["generation"])
    assert load(stopped["path"])["result"] == "STOPPED" and not list(state.glob("*.process.json"))


@pytest.mark.parametrize("change", ["argv", "entrypoint"])
def test_worker_launch_binding_cannot_be_substituted_before_stop(world, change):
    state = world.source.state
    binding = load(state / "runtime-binding.json")
    if change == "argv":
        binding["retention"]["argv"][2] = "foreign-entrypoint.py"
        native.write_json(state / "runtime-binding.json", binding)
    else:
        (native.ROOT / retention.ENTRYPOINT).write_bytes(b"changed entrypoint")
    world.events.clear()
    with pytest.raises(ValueError):
        e.stop_existing(state, binding["generation"])
    assert world.events == []


def test_absent_process_without_handle_has_unknown_exit(monkeypatch):
    monkeypatch.setattr(
        native, "process_kernel", lambda: SimpleNamespace(OpenProcess=lambda *_a: None)
    )
    monkeypatch.setattr(native.ctypes, "get_last_error", lambda: 87, raising=False)
    result = native.stop_owned({"pid": 123})
    assert result["exit_code"] is None and not result["exit_observed"] and not result["forced"]


@pytest.mark.parametrize("io_failure", ["stop-write", "log-read"])
def test_unknown_exit_io_failure_retains_marker_and_cannot_mint_resume(
    world, monkeypatch, io_failure
):
    state = world.source.state
    original_stop = native.stop_owned

    def unknown(record):
        original_stop(record)
        return {
            "method": "already_absent",
            "forced": False,
            "graceful": False,
            "wait": "NOT_OBSERVED",
            "exit_observed": False,
            "exit_code": None,
        }

    monkeypatch.setattr(native, "stop_owned", unknown)
    original_write, original_read = native.private_write, Path.read_bytes

    def failed_write(path, text, **kwargs):
        if path.name.startswith("stop-"):
            raise OSError("Synthetic receipt write failure")
        return original_write(path, text, **kwargs)

    def failed_read(path):
        if path.name == "stdout.private.log":
            raise OSError("Synthetic stop log read failure")
        return original_read(path)

    monkeypatch.setattr(
        native, "private_write", failed_write if io_failure == "stop-write" else original_write
    )
    monkeypatch.setattr(
        Path, "read_bytes", failed_read if io_failure == "log-read" else original_read
    )
    with pytest.raises(OSError):
        captured(world, monkeypatch)
    assert (state / "worker.process.json").exists()
    worker = load(state / "worker.process.json")
    assert worker["pid"] not in world.live
    monkeypatch.setattr(native, "private_write", original_write)
    monkeypatch.setattr(Path, "read_bytes", original_read)
    binding = load(state / "runtime-binding.json")
    stopped = e.stop_existing(state, binding["generation"])
    receipt = load(stopped["path"])
    assert (
        receipt["result"] == "STOPPED_WORKER_UNKNOWN_EXIT"
        and not receipt["automatic_resume_authorized"]
    )


@pytest.mark.parametrize("lifecycle", ["native-down", "existing-stop"])
def test_unexpected_worker_executable_refuses_batch_before_first_effect(world, lifecycle):
    state = world.source.state
    binding = load(state / "runtime-binding.json")
    record = binding["retention"]["process"] | {"executable": str(world.root / "foreign.exe")}
    binding["retention"]["process"] = record
    binding["processes"]["worker.process.json"] = record
    native.write_json(state / "worker.process.json", record)
    native.write_json(state / "runtime-binding.json", binding)
    world.live[record["pid"]] = record
    hba = (state / "postgres/pg_hba.conf").read_bytes()
    world.events.clear()
    with pytest.raises(ValueError, match="configured executable"):
        if lifecycle == "native-down":
            world.source.down()
        else:
            e.stop_existing(state, binding["generation"])
    assert world.events == [] and (state / "postgres/pg_hba.conf").read_bytes() == hba


@pytest.mark.parametrize("cleanup_fault", ["terminate", "wait"])
def test_unresolved_popen_child_blocks_pg_stop_without_forging_marker(
    world, monkeypatch, cleanup_fault
):
    stack = world.source
    binding = load(stack.state / "runtime-binding.json")
    stack.stop_worker(binding)
    binding["state"] = "STARTING"
    binding["generation"] = str(__import__("uuid").uuid4())
    original_identity = native.identity

    def identity(pid):
        if pid == 987:
            raise PermissionError("Synthetic identity publication failure")
        return original_identity(pid)

    def terminate():
        if cleanup_fault == "terminate":
            raise PermissionError("Synthetic original handle failure")

    child = SimpleNamespace(
        pid=987,
        poll=lambda: None,
        terminate=terminate,
        wait=lambda **_k: (_ for _ in ()).throw(TimeoutError("Synthetic wait failure")),
    )
    monkeypatch.setattr(native, "identity", identity)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_a, **_k: child)
    monkeypatch.setattr(native.Native, "launch", REAL_LAUNCH)
    with pytest.raises(native.WorkerLaunchFailed, match="identity publication"):
        stack.start_worker(binding)
    assert not (stack.state / "worker.process.json").exists()
    failed = load(stack.state / "runtime-binding.json")
    assert failed["retention_launch_unresolved"] and failed["retention"]["process"] is None
    receipt = load(next(Path(failed["retention"]["state"]).glob("launch-failed-*.private.json")))
    assert not receipt["exit_observed"] and receipt["exit_code"] is None
    world.events.clear()
    with pytest.raises(ValueError, match="Unresolved worker launch"):
        e.stop_existing(stack.state, failed["generation"])
    with pytest.raises(ValueError, match="Unresolved worker launch"):
        stack.down()
    assert world.events == [] and (stack.state / "postgres/postmaster.pid").exists()


@pytest.mark.parametrize("exit_kind", ["poll", "forced-wait"])
@pytest.mark.parametrize("cleanup", ["native-down", "existing-stop"])
def test_known_original_child_exit_allows_partial_cleanup(world, monkeypatch, exit_kind, cleanup):
    stack = world.source
    binding = load(stack.state / "runtime-binding.json")
    stack.stop_worker(binding)
    binding["state"] = "STARTING"
    binding["generation"] = str(__import__("uuid").uuid4())
    events = []
    child = SimpleNamespace(
        pid=987,
        poll=lambda: 2 if exit_kind == "poll" else None,
        terminate=lambda: events.append("original-handle-terminate"),
        wait=lambda **_k: events.append("original-handle-wait") or 37,
    )
    original_identity = native.identity

    def identity(pid):
        if pid == 987:
            raise PermissionError("Synthetic identity publication failure")
        return original_identity(pid)

    monkeypatch.setattr(native, "identity", identity)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_a, **_k: child)
    monkeypatch.setattr(native.Native, "launch", REAL_LAUNCH)
    with pytest.raises((RuntimeError, PermissionError)):
        stack.start_worker(binding)
    failed = load(stack.state / "runtime-binding.json")
    assert not (stack.state / "worker.process.json").exists()
    assert not failed["retention_launch_unresolved"]
    reference = failed["retention_failed_launch"]
    receipt = load(reference["path"])
    assert e.sha(Path(reference["path"]).read_bytes()) == reference["sha256"]
    assert receipt["exit_observed"] and receipt["exit_code"] == (2 if exit_kind == "poll" else 37)
    assert receipt["forced"] == (exit_kind == "forced-wait") and not receipt["graceful"]
    if exit_kind == "forced-wait":
        assert events == ["original-handle-terminate", "original-handle-wait"]
    world.events.clear()
    if cleanup == "native-down":
        stack.down()
    else:
        stopped = e.stop_existing(stack.state, failed["generation"])
        assert load(stopped["path"])["result"] == "STOPPED"
    assert load(stack.state / "runtime-binding.json")["state"] == "STOPPED"
    assert not list(stack.state.glob("*.process.json"))
    assert not (stack.state / "postgres/postmaster.pid").exists()


def test_known_exit_without_durable_receipt_does_not_clear_unresolved(world, monkeypatch):
    stack = world.source
    binding = load(stack.state / "runtime-binding.json")
    stack.stop_worker(binding)
    binding["state"] = "STARTING"
    binding["generation"] = str(__import__("uuid").uuid4())
    monkeypatch.setattr(native.Native, "launch", REAL_LAUNCH)
    monkeypatch.setattr(
        native.subprocess, "Popen", lambda *_a, **_k: SimpleNamespace(pid=987, poll=lambda: 2)
    )
    write = native.private_write

    def io_failure(path, text, **kwargs):
        if path.name.startswith("launch-failed-"):
            raise OSError("Synthetic durable launch receipt failure")
        return write(path, text, **kwargs)

    monkeypatch.setattr(native, "private_write", io_failure)
    with pytest.raises(OSError, match="durable launch receipt"):
        stack.start_worker(binding)
    failed = load(stack.state / "runtime-binding.json")
    assert (
        failed["retention_launch_unresolved"] and not (stack.state / "worker.process.json").exists()
    )
    world.events.clear()
    with pytest.raises(ValueError, match="Unresolved worker launch"):
        e.stop_existing(stack.state, failed["generation"])
    assert world.events == []


@pytest.mark.parametrize("exit_kind", ["poll", "forced-wait"])
def test_known_exit_cleanup_source_restarts_full_path_with_previous_progress(
    world, monkeypatch, exit_kind
):
    old = load(world.source.state / "runtime-binding.json")["retention"]
    progress = b'{"cursor":"00000000-0000-4000-8000-000000000009","sweep_pending":true}\n'
    (Path(old["state"]) / "progress.json").write_bytes(progress)
    hba = (world.source.state / "postgres/pg_hba.conf").read_bytes()
    epoch = world.facts[world.source.state]["epoch"]
    state, binding, proof = maintenance_proof(world, monkeypatch)
    fixture_launch, fixture_identity = native.Native.launch, native.identity
    child = SimpleNamespace(
        pid=987,
        poll=lambda: 2 if exit_kind == "poll" else None,
        terminate=lambda: None,
        wait=lambda **_k: 37,
    )
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_a, **_k: child)

    def failed_identity(pid):
        if pid == 987:
            raise PermissionError("Synthetic worker identity failure")
        return fixture_identity(pid)

    monkeypatch.setattr(native, "identity", failed_identity)

    def only_worker_real(stack, name, arguments, env, **kwargs):
        if name == "worker":
            return REAL_LAUNCH(stack, name, arguments, env, **kwargs)
        return fixture_launch(stack, name, arguments, env, **kwargs)

    monkeypatch.setattr(native.Native, "launch", only_worker_real)
    ref = e.write_new(state / "known-first-fence.private.json", proof)
    with pytest.raises(native.WorkerLaunchFailed):
        e.activate(state, binding["generation"], ref["path"], ref["sha256"])
    failed = load(state / "runtime-binding.json")
    stopped = e.stop_existing(state, failed["generation"])
    assert load(stopped["path"])["result"] == "STOPPED"
    monkeypatch.setattr(native.Native, "launch", fixture_launch)
    monkeypatch.setattr(native, "identity", fixture_identity)
    e.start_existing(
        state, stopped["path"], stopped["sha256"], source_pin="e" * 40, source_sha256=world.code_sha
    )
    resumed = load(state / "runtime-binding.json")
    control = resumed["lifecycle"]
    closed_at = datetime.fromisoformat(control["started_at"]) + timedelta(seconds=1)
    closed_mono = control["started_monotonic"] + 1

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return closed_at + timedelta(seconds=500)

    monkeypatch.setattr(e, "datetime", Clock)
    monkeypatch.setattr(e.time, "monotonic", lambda: closed_mono + 500)
    next_proof = proof | {
        "generation": resumed["generation"],
        "closed_after_logout_at": closed_at.isoformat(),
        "closed_after_logout_monotonic": closed_mono,
    }
    ref2 = e.write_new(state / "known-second-fence.private.json", next_proof)
    e.activate(state, resumed["generation"], ref2["path"], ref2["sha256"])
    running = world.source.require_running()
    assert (Path(running["retention"]["state"]) / "progress.json").read_bytes() == progress
    assert len(running["processes"]) == 4 and running["state"] == "RUNNING"
    assert (
        world.facts[state]["epoch"] == epoch
        and (state / "postgres/pg_hba.conf").read_bytes() == hba
    )


def test_target_retention_release_uses_own_port_restored_role_and_fresh_state(world, monkeypatch):
    source_worker = load(world.source.state / "runtime-binding.json")["retention"]
    (Path(source_worker["state"]) / "progress.json").write_text(
        '{"cursor":"00000000-0000-4000-8000-000000000008","sweep_pending":true}'
    )
    state, descriptor = bound_target(world, monkeypatch)
    e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    binding = load(state / "runtime-binding.json")
    assert (
        not (state / "worker.process.json").exists()
        and b"calorie_app_worker" not in (state / "postgres/pg_hba.conf").read_bytes()
    )
    control = binding["lifecycle"]
    closed_at = datetime.fromisoformat(control["started_at"]) + timedelta(seconds=1)
    closed_mono = control["started_monotonic"] + 1

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return closed_at + timedelta(seconds=500)

    monkeypatch.setattr(e, "datetime", Clock)
    monkeypatch.setattr(e.time, "monotonic", lambda: closed_mono + 500)
    proof = {
        "format": "native-existing-auth-fence/v1",
        "generation": binding["generation"],
        "issuer": world.source.origin + "/realms/calorie-dev",
        "qualified_minimum_seconds": 421,
        "qualified_token_settings_sha256": "d" * 64,
        "logout_all_succeeded": True,
        "issuance_api_503_observed": True,
        "provider_user_session_counts": {"fake": 0},
        "closed_after_logout_at": closed_at.isoformat(),
        "closed_after_logout_monotonic": closed_mono,
    }
    ref = e.write_new(state / "r1-target-fence.private.json", proof)
    before = deepcopy(world.facts[state])
    e.activate(state, binding["generation"], ref["path"], ref["sha256"])
    current = load(state / "runtime-binding.json")["retention"]
    assert Path(current["state"]).is_relative_to(state)
    assert not (Path(current["state"]) / "progress.json").exists()
    launch = next(x for x in world.events if x[0] == "launch" and x[1] == "worker")
    assert (
        launch[3]["DATABASE_URL"]
        == "postgresql+psycopg://calorie_app_worker:restored@127.0.0.1:25433/calorie_app"
    )
    assert world.facts[state] == before and before["ai"] is False
    assert (state / "postgres/pg_hba.conf").read_bytes() == e.RUNNING_HBA
    assert set(load(state / "runtime-binding.json")["processes"]) == {
        n + ".process.json" for n in ("postgres", "keycloak", "gateway", "worker")
    }
