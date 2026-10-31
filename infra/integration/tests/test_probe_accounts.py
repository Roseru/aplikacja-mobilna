"""Own synthetic fixture creation: persist Keycloak's actual, verified login name."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify import Probe  # noqa: E402

ORIGIN = "https://127.0.0.1:28443"
BASE = ORIGIN + "/admin/realms/calorie-dev"


def own_probe(tmp_path, monkeypatch, *, email_username=False, changed=None):
    users = {}
    created = {}
    observed = set()
    mapped = []
    requests = []
    login = {}
    role = {"id": "basic-role", "name": "user", "composite": False, "clientRole": True}

    def handle(request):
        requests.append((request.method, request.url.path))
        if (
            request.method == "POST"
            and request.url.path == "/realms/master/protocol/openid-connect/token"
        ):
            return httpx.Response(200, json={"access_token": "synthetic-admin-token"})
        if request.method == "GET" and request.url.path == "/admin/realms/calorie-dev/clients":
            assert request.url.params["clientId"] == "calorie-api"
            return httpx.Response(200, json=[{"id": "api-client"}])
        if request.method == "GET" and str(request.url) == BASE + "/clients/api-client/roles/user":
            return httpx.Response(200, json=role)
        if request.method == "POST" and str(request.url) == BASE + "/users":
            body = json.loads(request.content)
            subject = str(UUID(int=len(users) + 1))
            created[subject] = body
            user = {key: value for key, value in body.items() if key != "credentials"}
            user["id"] = subject
            if email_username:
                user["username"] = user["email"]
            users[subject] = user
            return httpx.Response(201, headers={"Location": BASE + "/users/" + subject})
        for subject, user in users.items():
            if request.method == "GET" and str(request.url) == BASE + "/users/" + subject:
                observed.add(subject)
                return httpx.Response(200, json={**user, **(changed or {})})
            if (
                request.method == "POST"
                and str(request.url)
                == BASE + "/users/" + subject + "/role-mappings/clients/api-client"
            ):
                assert subject in observed, "Verify the exact new user before adding its basic role"
                assert json.loads(request.content) == [role]
                mapped.append(subject)
                return httpx.Response(204)
        if request.method == "GET" and request.url.path.endswith("/protocol/openid-connect/auth"):
            login["state"] = request.url.params["state"]
            login["callback"] = request.url.params["redirect_uri"]
            return httpx.Response(
                200,
                text='<form id="kc-form-login" action="'
                + ORIGIN
                + '/realms/calorie-dev/login-actions/authenticate"></form>',
            )
        if (
            request.method == "POST"
            and request.url.path == "/realms/calorie-dev/login-actions/authenticate"
        ):
            fields = parse_qs(request.content.decode())
            assert fields["username"] == [users[next(iter(users))]["username"]]
            assert fields["password"] == [created[next(iter(created))]["credentials"][0]["value"]]
            return httpx.Response(
                302,
                headers={
                    "Location": login["callback"]
                    + "?state="
                    + login["state"]
                    + "&code=synthetic-code"
                },
            )
        pytest.fail("Unexpected request: " + request.method + " " + request.url.path)

    probe = Probe.__new__(Probe)
    probe.stack = SimpleNamespace(origin=ORIGIN, state=tmp_path)
    probe.issuer = ORIGIN + "/realms/calorie-dev"
    probe.credentials = {
        "admin": {"username": "synthetic-admin", "password": "synthetic-private-admin"}
    }
    monkeypatch.setattr(
        probe,
        "client",
        lambda: httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False),
    )
    return probe, SimpleNamespace(
        users=users, created=created, mapped=mapped, observed=observed, requests=requests
    )


@pytest.mark.parametrize("email_username", [False, True])
def test_actual_username_is_bound_before_credentials_are_saved_and_used_for_login(
    tmp_path, monkeypatch, email_username
):
    probe, state = own_probe(tmp_path, monkeypatch, email_username=email_username)
    probe.fresh_accounts()
    assert len(state.users) == 2 and set(state.mapped) == state.observed == set(state.users)
    for name, (subject, user) in zip(("a", "b"), state.users.items(), strict=True):
        saved = probe.credentials[name]
        assert saved["username"] == user["username"]
        assert saved["password"] == state.created[subject]["credentials"][0]["value"]
        assert saved["username"].endswith("@invalid.example") is email_username
    files = list(tmp_path.glob("probe-credentials-*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text()) == probe.credentials
    assert "synthetic-private-admin" not in files[0].read_text()
    assert probe.code()[0] == "synthetic-code"
    assert not any(method in {"PUT", "DELETE"} for method, _ in state.requests)
    assert not any(path.endswith("/reset-password") for _, path in state.requests)
    assert not any(method == "GET" and path.endswith("/users") for method, path in state.requests)


@pytest.mark.parametrize(
    "changed",
    [
        {"id": str(UUID(int=99))},
        {"username": "another-existing-account"},
        {"email": "another@invalid.example"},
        {"firstName": "Other"},
        {"lastName": "Other"},
        {"enabled": False},
        {"emailVerified": False},
    ],
)
def test_wrong_identity_refuses_before_role_mapping_credentials_or_login(
    tmp_path, monkeypatch, changed
):
    probe, state = own_probe(tmp_path, monkeypatch, changed=changed)
    with pytest.raises(RuntimeError, match="fixture identity"):
        probe.fresh_accounts()
    assert len(state.users) == 1
    assert state.mapped == []
    assert not list(tmp_path.glob("probe-credentials-*.json"))
    assert set(probe.credentials) == {"admin"}
    assert not any(method in {"PUT", "DELETE"} for method, _ in state.requests)
