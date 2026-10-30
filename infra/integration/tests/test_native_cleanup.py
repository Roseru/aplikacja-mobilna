"""Partial-resource cleanup cannot weaken admission or mint resume authority."""

import pytest

from infra.integration.tests.test_native_existing import bound_target, load, world
from infra.local.integration import native_existing as e

# Importing this fixture reuses synthetic files and fully mocked command/HTTP
# boundaries. No real Native state, database, process or network is accessed.
__all__ = ["world"]


def partial_failed_with_dead(world, monkeypatch, name):
    state, descriptor = bound_target(world, monkeypatch)
    original = e.native.Native.launch

    def started_then_died(stack, service, arguments, env):
        result = original(stack, service, arguments, env)
        if service == "gateway":
            record = load(state / (name + ".process.json"))
            world.live.pop(record["pid"])
            raise RuntimeError("Synthetic partial startup death")
        return result

    monkeypatch.setattr(e.native.Native, "launch", started_then_died)
    with pytest.raises(RuntimeError, match="partial startup death"):
        e.start_existing(
            state,
            descriptor["path"],
            descriptor["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )
    world.events.clear()
    return state, load(state / "runtime-binding.json")


@pytest.mark.parametrize("dead_service", ["keycloak", "gateway"])
def test_partial_cleanup_dead_service_and_live_own_resources(world, monkeypatch, dead_service):
    state, binding = partial_failed_with_dead(world, monkeypatch, dead_service)
    stopped = e.stop_existing(state, binding["generation"])
    receipt = load(stopped["path"])
    assert receipt["result"] == "STOPPED" and receipt["pg_stop"]["exit_code"] == 0
    dead = receipt["service_stops"][dead_service]
    assert dead["already_dead"] and not dead["termination_helper_called"]
    assert dead["process_exit"] == "UNKNOWN"
    assert load(state / "owner.json")["status"] == "STOPPED"
    assert not list(state.glob("*.process.json"))


@pytest.mark.parametrize("mismatch", ["birth", "exe"])
def test_cleanup_live_reused_pid_refuses_before_any_stop(world, monkeypatch, mismatch):
    state, binding = partial_failed_with_dead(world, monkeypatch, "keycloak")
    old = binding["processes"]["keycloak.process.json"]
    foreign = dict(old)
    if mismatch == "birth":
        foreign["created"] += 1
    else:
        foreign["executable"] = str(world.root / "foreign.exe")
    world.live[old["pid"]] = foreign
    with pytest.raises(ValueError, match="reused PID"):
        e.stop_existing(state, binding["generation"])
    assert world.events == [] and world.live[old["pid"]] == foreign
    assert (state / "postgres/postmaster.pid").exists()


def test_async_maintenance_death_keeps_admission_strict_but_allows_cleanup(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    result = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    record = load(state / "keycloak.process.json")
    world.live.pop(record["pid"])
    with pytest.raises(ProcessLookupError):
        e.qualified_runtime(e.native.Native(state), {"MAINTENANCE"})
    stopped = e.stop_existing(state, result["generation"])
    assert load(stopped["path"])["service_stops"]["keycloak"]["process_exit"] == "UNKNOWN"


@pytest.mark.parametrize(
    "member", ["tls/ca.pem", "keycloak.env", "config-generation/provider-profile.json"]
)
def test_cleanup_nonbootstrap_drift_is_reported_and_not_resume_authority(
    world, monkeypatch, member
):
    state, descriptor = bound_target(world, monkeypatch)
    result = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    path = state / member
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"untrusted drift; not valid env/json/TLS")
    world.events.clear()
    stopped = e.stop_existing(state, result["generation"])
    receipt = load(stopped["path"])
    assert member in receipt["configuration_drift"] and not receipt["automatic_resume_authorized"]
    assert receipt["result"] == "STOPPED_COHORT_DRIFT"
    with pytest.raises(ValueError, match="not eligible"):
        e.start_existing(
            state,
            stopped["path"],
            stopped["sha256"],
            source_pin="e" * 40,
            source_sha256=world.code_sha,
        )


def test_cleanup_bootstrap_drift_remains_critical(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    result = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    (state / "postgres.env").write_bytes(b"POSTGRES_PASSWORD=" + b"d" * 64 + b"\n")
    world.events.clear()
    with pytest.raises(ValueError, match="bootstrap differs"):
        e.stop_existing(state, result["generation"])
    assert world.events == []


def test_dead_pg_cleanup_records_unknown_and_keeps_pidfile_not_resume(world, monkeypatch):
    state, descriptor = bound_target(world, monkeypatch)
    result = e.start_existing(
        state,
        descriptor["path"],
        descriptor["sha256"],
        source_pin="e" * 40,
        source_sha256=world.code_sha,
    )
    record = load(state / "postgres.process.json")
    world.live.pop(record["pid"])
    world.events.clear()
    cleaned = e.stop_existing(state, result["generation"])
    receipt = load(cleaned["path"])
    assert receipt["result"] == "CLEANED_UNKNOWN_EXIT" and receipt["pg_stop"]["exit_code"] is None
    assert (
        receipt["pg_stop"]["process_exit"] == "UNKNOWN"
        and not receipt["automatic_resume_authorized"]
    )
    assert not any(x[0] == "pg-stop" for x in world.events)
    assert (state / "postgres/postmaster.pid").exists() and not list(state.glob("*.process.json"))
    assert load(state / "owner.json")["status"] == "DEAD_UNKNOWN_EXIT"
