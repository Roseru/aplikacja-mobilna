"""Native adapter boundaries; these unit checks do not assert live Android acceptance."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from infra.integration.tests.native_retention_fixture import seed_worker
from infra.local.integration import gateway, native, verify_runtime


def test_module_cli_imports_in_fresh_interpreter_without_prior_test_imports():
    environment = native.clean_env() | {
        "PYTHONPATH": os.pathsep.join([str(native.ROOT), str(native.ROOT / "backend/src")])
    }
    result = subprocess.run(
        [sys.executable, "-m", "infra.local.integration.verify_runtime", "--help"],
        cwd=native.ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        **native.FLAGS,
    )
    assert result.returncode == 0
    assert "bootstrap" in result.stdout and "sync" in result.stdout


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    state = tmp_path / ".tools/state"
    state.mkdir(parents=True)
    config = {
        "host": "172.16.0.2",
        "port": 28443,
        "origin": "https://172.16.0.2:28443",
        "project": "calorie-native-o2",
    }
    native.write_json(state / "config.json", config)
    native.write_json(
        state / "native.json",
        config
        | {
            "format": "calorie-native/v1",
            "state": str(state),
            "pg_bin": str(state / "pg-bin"),
            "python": "python.exe",
            "pg_port": 25432,
            "source": {"commit": "a" * 40},
        },
    )
    stack = native.Native(state)
    source = {"commit": "a" * 40, "adapter_sha256": {"gateway.py": "b" * 64}}
    monkeypatch.setattr(native, "source", lambda _pin: source)
    processes = {
        name + ".process.json": {
            "pid": number,
            "created": 1000 + number,
            "executable": name + ".exe",
        }
        for number, name in enumerate(("postgres", "keycloak", "gateway"), 100)
    }
    for name, record in processes.items():
        native.write_json(state / name, record)
    binding = {
        "state": "RUNNING",
        "generation": "00000000-0000-4000-8000-000000000001",
        "source": source,
        "processes": processes,
    }
    seed_worker(stack, binding, {"pid": 104, "created": 1104, "executable": stack.python})
    native.write_json(
        state / "runtime-binding.json",
        binding,
    )
    by_pid = {record["pid"]: record for record in processes.values()}
    monkeypatch.setattr(native, "identity", lambda pid: by_pid[pid])
    return stack, source, processes


def test_existing_state_preserved_before_any_runtime_or_input_read(owned):
    stack, *_ = owned
    sentinel = stack.state / "keep"
    sentinel.write_bytes(b"old private state")
    with pytest.raises(FileExistsError):
        native.prepare(
            stack.state,
            host=None,
            port=None,
            pg_port=None,
            keycloak_port=None,
            management_port=None,
            pg_bin=None,
            java_home=None,
            keycloak_home=None,
            python=None,
            pin=None,
        )
    assert sentinel.read_bytes() == b"old private state"


def test_state_outside_owned_tools_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="under this checkout"):
        native.confined(tmp_path / "other")


def test_junction_state_refused_before_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "is_junction", lambda p: p.name == "redirect")
    with pytest.raises(ValueError, match="Linked"):
        native.confined(tmp_path / "redirect/state")


@pytest.mark.parametrize("ports", [[1000, 2000], [28443, 28443], [True, 25432], [70000, 25432]])
def test_bad_or_colliding_port_inventory_refused(ports):
    with pytest.raises(ValueError):
        native.available("127.0.0.1", ports)


def test_real_foreign_listening_port_refused_without_touching_it():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(OSError):
            native.available("127.0.0.1", [listener.getsockname()[1]])
        assert listener.fileno() >= 0


def test_foreign_secrets_and_java_agents_are_not_inherited(monkeypatch):
    for key in (
        "GEMINI_API_KEY",
        "DATABASE_URL",
        "KC_DB_PASSWORD",
        "JAVA_TOOL_OPTIONS",
    ):
        monkeypatch.setenv(key, "synthetic-foreign-value")
    monkeypatch.setenv("OS", "Windows_NT")
    actual = native.clean_env()
    assert (
        not {"GEMINI_API_KEY", "DATABASE_URL", "KC_DB_PASSWORD", "JAVA_TOOL_OPTIONS"}
        & actual.keys()
    )
    assert actual["OS"] == "Windows_NT"


@pytest.mark.parametrize("pin", ["main", "a" * 39, "b" * 41, "G" * 40])
def test_inexact_source_pin_refused(pin):
    with pytest.raises(ValueError, match="Full source"):
        native.source(pin)


@pytest.mark.parametrize("helper", native.SHARED_HELPERS)
def test_shared_helper_change_requires_a_new_qualified_source(tmp_path, monkeypatch, helper):
    repository = tmp_path / "source"
    repository.mkdir()
    monkeypatch.setattr(native, "ROOT", repository)
    adapter = repository / "infra/local/integration"
    adapter.mkdir(parents=True)
    monkeypatch.setattr(native, "HERE", adapter)
    (adapter / "native.py").write_bytes(b"# isolated adapter\n")
    backend = repository / "backend/src/calorie_app"
    backend.mkdir(parents=True)
    (backend / "__init__.py").write_bytes(b"")
    (repository / "backend/uv.lock").write_bytes(b"package = []\n")
    contracts = repository / "contracts"
    contracts.mkdir()
    (contracts / "fixture.json").write_bytes(b"{}\n")
    for path in native.SHARED_HELPERS:
        target = repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"original helper\n")
    monkeypatch.setitem(
        sys.modules,
        "calorie_app",
        SimpleNamespace(__file__=str(backend / "__init__.py")),
    )

    def git(*arguments):
        return (
            subprocess.check_output(
                [
                    "git",
                    "-c",
                    "user.name=Native Test",
                    "-c",
                    "user.email=native-test@invalid.example",
                    "-c",
                    "commit.gpgsign=false",
                    "-c",
                    f"core.hooksPath={repository / 'no-hooks'}",
                    *arguments,
                ],
                cwd=repository,
                stderr=subprocess.PIPE,
                **native.FLAGS,
            )
            .decode()
            .strip()
        )

    git("init", "--quiet")
    git("add", ".")
    git("commit", "--quiet", "-m", "isolated source fixture")
    pin = git("rev-parse", "HEAD")
    qualified = native.source(pin)
    (repository / helper).write_bytes(b"changed shared runtime helper\n")
    with pytest.raises(subprocess.CalledProcessError):
        native.source(pin)
    git("add", helper)
    git("commit", "--quiet", "-m", "change shared helper")
    refreshed = native.source(git("rev-parse", "HEAD"))
    assert qualified["shared_helper_sha256"][helper] != refreshed["shared_helper_sha256"][helper]


def test_shared_origin_config_cannot_drift(owned):
    stack, *_ = owned
    path = stack.state / "native.json"
    value = json.loads(path.read_text())
    value["origin"] = "https://10.0.2.2:28443"
    native.write_json(path, value)
    with pytest.raises(ValueError, match="exact HTTPS identity"):
        native.Native(stack.state)


def test_live_generation_is_bound_to_source_and_exact_processes(owned):
    stack, *_ = owned
    assert stack.require_running()["generation"] == "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("result", ["CONFIGURED", "PARTIAL", "FAIL"])
def test_provider_configuration_change_requires_explicit_generation_binding(owned, result):
    stack, *_ = owned
    assert "retention" in stack.configuration_binding()
    path = stack.state / "config-generation/provider-profile.json"
    path.parent.mkdir()
    native.write_json(path, {"format": "calorie-native-provider-profile/v1", "result": result})
    with pytest.raises(ValueError, match="provider configuration"):
        stack.require_running()
    binding_path = stack.state / "runtime-binding.json"
    binding = json.loads(binding_path.read_text())
    native.write_json(binding_path, binding | {"configuration": stack.configuration_binding()})
    assert stack.require_running()["configuration"]["provider_profile_result"] == result
    native.write_json(
        path, {"format": "calorie-native-provider-profile/v1", "result": result, "changed": True}
    )
    with pytest.raises(ValueError, match="provider configuration"):
        stack.require_running()


def test_malformed_provider_configuration_cannot_be_qualified(owned):
    stack, *_ = owned
    path = stack.state / "config-generation/provider-profile.json"
    path.parent.mkdir()
    path.write_bytes(b"\0" * 40)
    with pytest.raises(ValueError):
        stack.require_running()


@pytest.mark.parametrize("damage", ["source", "stopped", "missing", "marker", "reused"])
def test_stale_generation_is_refused(owned, monkeypatch, damage):
    stack, source, processes = owned
    if damage == "source":
        monkeypatch.setattr(native, "source", lambda pin: source | {"adapter_sha256": {}})
    elif damage == "stopped":
        path = stack.state / "runtime-binding.json"
        value = json.loads(path.read_text())
        native.write_json(path, value | {"state": "STOPPED"})
    elif damage == "missing":
        (stack.state / "gateway.process.json").unlink()
    elif damage == "marker":
        native.write_json(
            stack.state / "gateway.process.json",
            processes["gateway.process.json"] | {"created": 7},
        )
    else:
        monkeypatch.setattr(native, "identity", lambda pid: {"pid": pid, "created": 7})
    with pytest.raises(ValueError):
        stack.require_running()


def test_down_checks_every_pid_before_stopping_anything(owned, monkeypatch):
    stack, *_ = owned
    monkeypatch.setattr(native, "identity", lambda pid: {"pid": pid, "created": -1})
    monkeypatch.setattr(
        native,
        "terminate",
        lambda record: pytest.fail("stopped before identity checks"),
    )
    with pytest.raises(RuntimeError, match="reused"):
        stack.down()
    assert len(list(stack.state.glob("*.process.json"))) == 4


def test_concurrent_lifecycle_is_refused(owned):
    stack, *_ = owned
    with stack.operation():
        with pytest.raises(OSError):
            with stack.operation():
                pytest.fail("concurrent native lifecycle admitted")


def test_fixture_independent_units_and_null_oracle():
    operations = verify_runtime.fixture("00000000-0000-4000-8000-000000000064")
    assert {op["entity_type"] for op in operations} == {
        "profile",
        "goal",
        "diary_day",
        "meal",
        "weight",
        "product_draft",
    }
    items = next(op["payload"]["items"] for op in operations if op["entity_type"] == "meal")
    assert items[1]["quantity"] == {"amount": "250", "unit": "ml"}
    assert items[1]["nutrition_per_100"]["protein_g"] is None
    assert items[0]["quantity"]["amount"] == "150"


def test_static_pass_file_cannot_promote_stale_runtime_or_reach_network(owned, monkeypatch):
    stack, source, _ = owned
    monkeypatch.setattr(verify_runtime, "source", lambda pin: source)
    monkeypatch.setattr(
        verify_runtime,
        "Probe",
        lambda stack: pytest.fail("network before generation qualification"),
    )
    native.write_json(stack.state / "verification.json", {"result": "PASS", "full_user_flow": True})
    (stack.state / "gateway.process.json").unlink()
    with pytest.raises(ValueError):
        verify_runtime.verify(stack, "sync")
    result = json.loads(next((stack.state / "evidence").glob("*/receipt.json")).read_text())
    assert result["result"] == "FAIL"
    assert result["full_user_flow"] is False
    assert result["release_authorized"] is False
    assert result["failure_stage"] == 0


def test_lost_ack_waits_for_pg_witness_without_receiving(monkeypatch):
    events = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("disconnect")

        def sendall(self, raw):
            assert b"POST /api/v1/sync/push" in raw
            events.append("sent")

        def recv(self, *args):
            pytest.fail("client consumed ACK")

    connection = Connection()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: connection)
    trust = SimpleNamespace(wrap_socket=lambda *a, **k: connection)
    probe = SimpleNamespace(
        stack=SimpleNamespace(config={"host": "172.16.0.2", "port": 28443}), trust=trust
    )

    def witness():
        events.append("pg_commit")
        return True

    verify_runtime.lost_response(probe, "synthetic-token", {"operations": []}, witness)
    assert events[:3] == ["sent", "pg_commit", "disconnect"]


def test_gateway_keeps_multiple_cookies_and_replaces_untrusted_proxy_headers(
    monkeypatch,
):
    actual_client = httpx.AsyncClient

    def upstream(request):
        assert str(request.url) == "http://127.0.0.1:28080/realms/test?code=synthetic"
        assert request.headers["host"] == "172.16.0.2:28443"
        assert request.headers["x-forwarded-proto"] == "https"
        assert "forwarded" not in request.headers
        assert "x-forwarded-for" not in request.headers
        return httpx.Response(
            302,
            headers=[
                ("set-cookie", "one=1"),
                ("set-cookie", "two=2"),
                ("location", "pl.test:/callback"),
                ("connection", "close"),
            ],
        )

    def proxy_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return actual_client(transport=httpx.MockTransport(upstream), **kwargs)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", proxy_client)

    async def backend(*args):
        pytest.fail("identity request routed to backend")

    app = gateway.Gateway(backend, "https://172.16.0.2:28443", 28080)

    async def attempt():
        async with actual_client(
            transport=httpx.ASGITransport(app), base_url="https://test"
        ) as client:
            response = await client.get(
                "/realms/test?code=synthetic",
                headers={
                    "Forwarded": "host=evil",
                    "X-Forwarded-Proto": "http",
                    "X-Forwarded-For": "evil",
                },
            )
        assert response.status_code == 302
        assert response.headers.get_list("set-cookie") == ["one=1", "two=2"]
        assert response.headers["cache-control"] == "no-store"
        assert "connection" not in response.headers

    asyncio.run(attempt())
