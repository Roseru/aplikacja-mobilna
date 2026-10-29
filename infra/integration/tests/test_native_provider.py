"""Isolated provider configuration guards; no real realm, SMTP or user-flow acceptance."""

import copy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from infra.local.integration import provider


@pytest.fixture
def rehearsal(tmp_path, monkeypatch):
    state = tmp_path / "native"
    state.mkdir()
    (state / "credentials.json").write_text(
        json.dumps(
            {
                "admin": {
                    "username": "synthetic-admin",
                    "password": "synthetic-password-not-a-real-secret",
                }
            }
        )
    )
    original_binding = {
        "state": "RUNNING",
        "generation": "old-generation",
        "source": {"commit": "a" * 40},
        "processes": {"own": "unchanged"},
        "configuration": {},
    }
    (state / "runtime-binding.json").write_text(json.dumps(original_binding))
    default = {
        "id": "default-role",
        "name": "default-roles-calorie-dev",
        "clientRole": False,
        "containerId": "realm-id",
        "composite": True,
    }
    base_role = {
        "id": "offline-role",
        "name": "offline_access",
        "clientRole": False,
        "containerId": "realm-id",
        "composite": False,
    }
    user_role = {
        "id": "user-role",
        "name": "user",
        "clientRole": True,
        "containerId": "api-id",
        "composite": False,
    }
    server = SimpleNamespace(
        realm={
            "id": "realm-id",
            "realm": "calorie-dev",
            "defaultRole": default,
            "registrationAllowed": False,
            "resetPasswordAllowed": False,
            "smtpServer": {"password": "must-never-be-persisted"},
        },
        mobile={
            "id": "mobile-id",
            "clientId": "calorie-android",
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "attributes": {"pkce.code.challenge.method": "S256"},
            "redirectUris": [
                "pl.roseru.kalorie:/oauth2redirect",
                "pl.roseru.kalorie.validation:/oauth2redirect",
            ],
            "defaultClientScopes": ["basic", "roles"],
            "optionalClientScopes": ["profile"],
            "protocolMappers": [
                {
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {
                        "included.client.audience": "calorie-api",
                        "access.token.claim": "true",
                    },
                }
            ],
        },
        roles=[base_role],
        role=user_role,
        users=[{"id": "existing-user"}],
        jwks={"keys": [{"kid": "key-1", "kty": "RSA", "n": "public-modulus"}]},
        issuer="https://172.16.0.2:28443/realms/calorie-dev",
        calls=[],
        fail=None,
        mutation=None,
        epochs=["fd186d6a-9a79-4df1-ab56-fb5d310ced13"],
        constructed=0,
    )

    def handle(request):
        path = request.url.path
        server.calls.append(
            (
                request.method,
                path,
                json.loads(request.content)
                if request.content and request.headers.get("content-type") == "application/json"
                else None,
            )
        )
        if path.endswith("/realms/master/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "synthetic-admin-token"})
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"issuer": server.issuer})
        if path.endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, json=server.jwks)
        relative = path.removeprefix("/admin/realms/calorie-dev")
        if request.method == "GET":
            if relative == "":
                result = server.realm
            elif relative == "/clients":
                name = request.url.params["clientId"]
                result = [
                    {
                        "calorie-android": server.mobile,
                        "calorie-api": {"id": "api-id", "clientId": "calorie-api"},
                        "realm-management": {"id": "management-id", "clientId": "realm-management"},
                    }[name]
                ]
            elif relative == "/clients/api-id/roles/user":
                result = server.role
            elif relative == "/roles-by-id/default-role/composites":
                result = server.roles
            elif relative == "/users":
                result = server.users if request.url.params["first"] == "0" else []
            else:
                raise AssertionError("Unexpected GET endpoint: " + relative)
            return httpx.Response(200, json=copy.deepcopy(result))
        if request.method == "POST" and relative == "/roles-by-id/default-role/composites":
            assert json.loads(request.content) == [server.role]
            server.roles.append(copy.deepcopy(server.role))
            return httpx.Response(204)
        if request.method == "PUT" and relative == "":
            if server.fail == "before-put":
                return httpx.Response(503)
            server.realm.update(json.loads(request.content))
            if server.mutation:
                server.mutation(server)
            if server.fail == "uncertain-put":
                raise httpx.ReadError("synthetic token/action link must not be rendered")
            return httpx.Response(204)
        raise AssertionError("Unexpected mutation endpoint")

    class FakeNative:
        def __init__(self, value):
            assert Path(value) == state
            self.state = state
            self.origin = "https://172.16.0.2:28443"
            server.constructed += 1

        @contextmanager
        def operation(self):
            yield

        def configuration_binding(self):
            path = self.state / provider.PROFILE_STATE
            return (
                {}
                if not path.exists()
                else {
                    "provider_profile_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "provider_profile_result": json.loads(path.read_text())["result"],
                }
            )

        def require_running(self):
            value = json.loads((state / "runtime-binding.json").read_text())
            assert value["configuration"] == self.configuration_binding()
            return value

    sink = {
        "running": True,
        "host": "127.0.0.1",
        "smtp_port": 26525,
        "http_port": 28025,
        "version": "1.32.0",
        "zip_sha256": "a" * 64,
        "exe_sha256": "b" * 64,
        "messages": 0,
    }
    monkeypatch.setattr(provider, "Native", FakeNative)
    monkeypatch.setattr(
        provider, "client", lambda _: httpx.Client(transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(provider.mail_sink, "status", lambda _: dict(sink))
    monkeypatch.setattr(
        provider,
        "app_epoch",
        lambda _: server.epochs.pop(0) if len(server.epochs) > 1 else server.epochs[0],
    )
    return state, server, sink, original_binding


def configure(rehearsal, **kwargs):
    return provider.configure(rehearsal[0], rehearsal[0] / "mail", opt_in=True, **kwargs)


def test_no_opt_in_refused_before_state_or_credentials_read(rehearsal):
    state, server, *_ = rehearsal
    with pytest.raises(ValueError, match="opt-in"):
        provider.configure(state, state / "mail")
    assert server.constructed == 0 and server.calls == []


@pytest.mark.parametrize(
    ("location", "key", "value"),
    [
        ("realm", "registrationAllowed", 1),
        ("realm", "verifyEmail", False),
        ("realm", "defaultLocale", "de"),
        ("realm", "unsupported", True),
        ("smtp", "host", "0.0.0.0"),
        ("smtp", "host", "mail.external.example"),
        ("smtp", "port", "25"),
        ("smtp", "port", "65536"),
        ("smtp", "port", "026525"),
        ("smtp", "port", 26525),
        ("smtp", "auth", "true"),
        ("smtp", "password", "no-secret"),
        ("role", "role", "admin"),
        ("role", "role", "catalog_moderator"),
    ],
)
def test_unsafe_profile_refused_before_runtime_read(rehearsal, tmp_path, location, key, value):
    state, server, *_ = rehearsal
    profile = json.loads(provider.PROFILE.read_text())
    section = (
        profile["realm"]
        if location == "realm"
        else profile["realm"]["smtpServer"]
        if location == "smtp"
        else profile["default_client_role"]
    )
    section[key] = value
    path = tmp_path / "unsafe-profile.json"
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError):
        configure(rehearsal, profile_path=path)
    assert server.constructed == 0 and not (state / provider.PROFILE_STATE).exists()


@pytest.mark.parametrize(
    ("key", "value"), [("running", False), ("host", "0.0.0.0"), ("smtp_port", 28725)]
)
def test_requires_actual_matching_running_sink(rehearsal, key, value):
    state, server, sink, _ = rehearsal
    sink[key] = value
    with pytest.raises(ValueError):
        configure(rehearsal)
    assert server.calls == [] and not (state / provider.PROFILE_STATE).exists()


def test_closed_default_and_successful_additive_configuration(rehearsal):
    state, server, _, binding = rehearsal
    template = provider.HERE.parent / "keycloak/realm.json"
    before = template.read_bytes()
    assert provider.status(state)["result"] == "DEFAULT_CLOSED"
    result = configure(rehearsal)
    assert result["result"] == "CONFIGURED" and result["wf01_acceptance"] == "NOT_RUN"
    assert template.read_bytes() == before
    mutations = [(m, p, body) for m, p, body in server.calls if m != "GET" and "/master/" not in p]
    assert len(mutations) == 2
    assert mutations[0][0] == "POST" and mutations[0][2] == [server.role]
    assert (
        mutations[1][0] == "PUT"
        and mutations[1][2] == provider.load_profile(provider.PROFILE)["realm"]
    )
    report = json.loads((state / provider.PROFILE_STATE).read_text())
    assert report["result"] == "CONFIGURED"
    assert report["before"]["user_ids"] == report["after"]["user_ids"] == ["existing-user"]
    assert report["before"]["jwks_sha256"] == report["after"]["jwks_sha256"]
    assert "must-never-be-persisted" not in json.dumps(report)
    changed = json.loads((state / "runtime-binding.json").read_text())
    assert changed["generation"] != binding["generation"]
    assert changed["source"] == binding["source"] and changed["processes"] == binding["processes"]
    assert changed["configuration"]["provider_profile_result"] == "CONFIGURED"
    assert provider.status(state)["result"] == "MATCH"
    server.users.append({"id": "new-self-registered-user"})
    assert provider.status(state)["result"] == "MATCH"


@pytest.mark.parametrize(
    "damage", ["pkce", "callback", "audience", "composite-user", "elevated-default", "management"]
)
def test_unqualified_client_or_role_fails_before_any_mutation(rehearsal, damage):
    state, server, *_ = rehearsal
    if damage == "pkce":
        server.mobile["attributes"]["pkce.code.challenge.method"] = "plain"
    elif damage == "callback":
        server.mobile["redirectUris"].append("https://foreign.example/callback")
    elif damage == "audience":
        server.mobile["protocolMappers"] = []
    elif damage == "composite-user":
        server.role["composite"] = True
    elif damage == "elevated-default":
        server.roles.append(
            {
                "id": "admin-role",
                "name": "admin",
                "clientRole": True,
                "containerId": "api-id",
                "composite": False,
            }
        )
    else:
        server.roles.append(
            {
                "id": "manage-users",
                "name": "manage-users",
                "clientRole": True,
                "containerId": "management-id",
                "composite": False,
            }
        )
    result = configure(rehearsal)
    assert result["result"] == "FAIL" and not (state / provider.PROFILE_STATE).exists()
    assert not any(
        method == "PUT" or path.endswith("/composites") and method == "POST"
        for method, path, _ in server.calls
    )


@pytest.mark.parametrize("damage", ["keys", "users", "issuer", "mobile", "epoch", "role"])
def test_preservation_failure_never_reports_configured(rehearsal, damage):
    state, server, *_ = rehearsal
    if damage == "epoch":
        server.epochs = [
            "fd186d6a-9a79-4df1-ab56-fb5d310ced13",
            "30617b61-3338-4c5e-a157-57190c2ff0f3",
        ]
    else:

        def mutate(s):
            if damage == "keys":
                s.jwks["keys"][0]["kid"] = "changed-key"
            elif damage == "users":
                s.users = []
            elif damage == "issuer":
                s.issuer = "https://foreign.example/realms/calorie-dev"
            elif damage == "role":
                s.roles[0]["name"] = "unexpected-role-drift"
            else:
                s.mobile["optionalClientScopes"].append("changed-scope")

        server.mutation = mutate
    assert configure(rehearsal)["result"] == "PARTIAL"
    report = json.loads((state / provider.PROFILE_STATE).read_text())
    assert report["result"] == "PARTIAL" and report["wf01_acceptance"] == "NOT_RUN"
    assert len(report["steps"]) == 2


@pytest.mark.parametrize("failure", ["before-put", "uncertain-put"])
def test_partial_failure_keeps_steps_without_rollback_and_allows_status(rehearsal, failure):
    state, server, *_ = rehearsal
    server.fail = failure
    assert configure(rehearsal)["result"] == "PARTIAL"
    report = json.loads((state / provider.PROFILE_STATE).read_text())
    assert report["steps"] == [
        {"operation": "add_default_basic_user_role", "state": "acknowledged"},
        {"operation": "apply_explicit_realm_fields", "state": "attempted"},
    ]
    assert server.role in server.roles
    assert "synthetic token/action link" not in json.dumps(report)
    assert provider.status(state)["result"] == ("DRIFT" if failure == "before-put" else "MATCH")
    assert provider.status(state)["configuration_result"] == "PARTIAL"


def test_status_detects_profile_drift_and_no_mutation(rehearsal):
    state, server, *_ = rehearsal
    configure(rehearsal)
    server.realm["verifyEmail"] = False
    before = len(server.calls)
    assert provider.status(state)["result"] == "DRIFT"
    assert all(method == "GET" or "/master/" in path for method, path, _ in server.calls[before:])


def test_source_process_drift_preserves_partial_evidence_without_binding_fabrication(rehearsal):
    state, server, _, original = rehearsal

    def change_generation(_):
        changed = dict(original, generation="another-generation")
        (state / "runtime-binding.json").write_text(json.dumps(changed))

    server.mutation = change_generation
    result = configure(rehearsal)
    assert result["result"] == "PARTIAL"
    report = json.loads((state / provider.PROFILE_STATE).read_text())
    assert report["binding_verified"] is False
    assert report["binding_error_type"] == "ValueError"
    unchanged = json.loads((state / "runtime-binding.json").read_text())
    assert unchanged == dict(original, generation="another-generation")
    assert len(list((state / "config-generation").glob("*.json"))) == 2


def test_excessive_observation_refused_before_mutation(rehearsal):
    state, server, *_ = rehearsal
    server.users = [{"id": "x" * 15000}]
    assert configure(rehearsal)["result"] == "FAIL"
    assert not (state / provider.PROFILE_STATE).exists()
    assert not any(method == "PUT" for method, _, _ in server.calls)


def test_unknown_cli_failure_redacts_arbitrary_messages(monkeypatch, capsys):
    def fail(_):
        raise RuntimeError("secret token/action link must not be printed")

    monkeypatch.setattr(provider, "status", fail)
    assert provider.main(["status", "--state", "unused"]) == 1
    result = capsys.readouterr().out
    assert "RuntimeError" in result and "secret token" not in result


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://synthetic@foreign.example:25432/calorie_app",
        "postgresql+psycopg://synthetic@127.0.0.1:25433/calorie_app",
        "postgresql+psycopg://synthetic@127.0.0.1:25432/foreign_database",
    ],
)
def test_epoch_never_reads_another_database(monkeypatch, url):
    monkeypatch.setattr(
        provider, "create_engine", lambda *_args, **_kw: pytest.fail("opened a foreign database")
    )
    stack = SimpleNamespace(env=lambda _: {"DATABASE_URL": url}, config={"pg_port": 25432})
    with pytest.raises(ValueError, match="owned native"):
        provider.app_epoch(stack)
