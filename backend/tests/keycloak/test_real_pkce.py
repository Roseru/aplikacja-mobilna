import base64
import hashlib
import secrets
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from calorie_app.core.config import Settings
from calorie_app.main import create_app

CALLBACK = "http://127.0.0.1:8765/callback"
# Keycloak 26.8 treats loopback as a secure context and sets Secure cookies.
# The stdlib CookieJar used by HTTPX cannot implement browser loopback handling.
# Keycloak's supported Safari profile emits ordinary cookies over isolated HTTP:
# services/.../utils/SecureContextResolver.java at the pinned 26.8.0 release.
HARNESS_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "kc-form-login":
            self.action = attributes.get("action")


def callback_code(location, state, redirect_uri):
    parsed = urlsplit(location.get_secret_value() if isinstance(location, SecretStr) else location)
    expected = urlsplit(redirect_uri)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        expected.scheme,
        expected.netloc,
        expected.path,
    ), "Unexpected authorization redirect"
    params = parse_qs(parsed.query)
    assert params.get("state") == [state], "Authorization state mismatch"
    assert len(params.get("code", [])) == 1, "Authorization code missing"
    return params["code"][0]


def authorization_code(provider, who, *, client_id="calorie-pkce-harness", redirect_uri=CALLBACK):
    issuer, credentials = provider
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    with httpx.Client(
        timeout=10,
        trust_env=False,
        follow_redirects=False,
        headers={"User-Agent": HARNESS_USER_AGENT},
    ) as browser:
        login = browser.get(issuer + "/protocol/openid-connect/auth?" + urlencode(params))
        assert login.status_code == 200, "Real authorization page unavailable"
        form = LoginForm()
        form.feed(login.text)
        assert form.action and form.action.startswith(issuer + "/login-actions/"), (
            "Trusted form missing"
        )
        try:
            response = browser.post(
                form.action,
                data={
                    "username": credentials[who]["username"],
                    "password": credentials[who]["password"].get_secret_value(),
                    "credentialId": "",
                },
            )
        except httpx.HTTPError:
            raise AssertionError("Real authorization login transport failed") from None
        assert response.status_code in {302, 303}, "Real user login failed"
        code = callback_code(SecretStr(response.headers["location"]), state, redirect_uri)
    return SecretStr(code), SecretStr(verifier), nonce


def exchange(provider, code, verifier, *, client_id="calorie-pkce-harness", redirect_uri=CALLBACK):
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        try:
            return client.post(
                provider[0] + "/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "code": code.get_secret_value(),
                    "code_verifier": verifier.get_secret_value(),
                },
            )
        except httpx.HTTPError:
            raise AssertionError("Real PKCE exchange transport failed") from None


def tokens(provider, who, **kwargs):
    code, verifier, nonce = authorization_code(provider, who, **kwargs)
    response = exchange(provider, code, verifier, **kwargs)
    assert response.status_code == 200, "Real PKCE token exchange failed"
    payload = response.json()
    # These are client nonce/profile assertions; backend verifies cryptographic trust independently.
    id_claims = jwt.decode(payload["id_token"], options={"verify_signature": False})
    assert secrets.compare_digest(id_claims["nonce"], nonce)
    return {
        name: SecretStr(value) if name in {"access_token", "id_token", "refresh_token"} else value
        for name, value in payload.items()
    }


@pytest.fixture
def api(provider, database):
    engine, _, url = database
    issuer = provider[0]
    settings = Settings(
        database_url=url,
        environment="test",
        oidc_allow_local_http=True,
        oidc_issuer=issuer,
        oidc_jwks_url=issuer + "/protocol/openid-connect/certs",
        catalog_page_token_secret="e2" * 32,
    )
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client


def auth(token):
    return {"Authorization": "Bearer " + token.get_secret_value()}


def decoded(token):
    return jwt.decode(token.get_secret_value(), options={"verify_signature": False})


def expect_status(response, status):
    if response.status_code != status:
        raise AssertionError(f"Unexpected HTTP status {response.status_code}; expected {status}")


def test_real_pkce_a_b_bootstrap_private_me_consents_and_id_token_rejection(provider, api):
    a, b = tokens(provider, "a"), tokens(provider, "b")
    a_claims = decoded(a["access_token"])
    b_claims = decoded(b["access_token"])
    assert a_claims["sub"] != b_claims["sub"]
    assert a_claims["iss"] == provider[0]
    assert a_claims["typ"] == "Bearer"
    assert 0 < a_claims["exp"] - a_claims["iat"] <= 300
    assert "user" in a_claims["resource_access"]["calorie-api"]["roles"]
    assert "nbf" not in a_claims or isinstance(a_claims["nbf"], (int, float))
    denied = api.get("/api/v1/me", headers=auth(a["id_token"]))
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"].startswith("Bearer")
    accounts = []
    for payload in (a, b):
        headers = {**auth(payload["access_token"]), "Idempotency-Key": str(uuid4())}
        response = api.post("/api/v1/me/bootstrap", headers=headers)
        assert response.status_code == 200
        accounts.append(response.json()["account_id"])
        repeated = api.post("/api/v1/me/bootstrap", headers=headers)
        assert repeated.json() == response.json()
        read = api.get("/api/v1/me", headers=auth(payload["access_token"]))
        assert read.status_code == 200
        assert read.json()["profile"] is None
    assert accounts[0] != accounts[1]
    a_me = api.get("/api/v1/me", headers=auth(a["access_token"])).json()
    b_before = api.get("/api/v1/me", headers=auth(b["access_token"])).json()
    headers = {
        **auth(a["access_token"]),
        "Idempotency-Key": str(uuid4()),
        "If-Match": f'"{a_me["consents"]["revision"]}"',
    }
    body = {"ranking": True, "automatic_energy_adjustment": False}
    changed = api.put("/api/v1/me/consents", headers=headers, json=body)
    assert changed.status_code == 200
    replay = api.put("/api/v1/me/consents", headers=headers, json=body)
    assert replay.json() == changed.json()
    b_after = api.get("/api/v1/me", headers=auth(b["access_token"])).json()
    assert b_before == b_after
    assert b_after["consents"]["ranking"] is False


def test_real_provider_rejects_wrong_pkce_and_code_reuse(provider):
    code, verifier, _ = authorization_code(provider, "a")
    denied = exchange(provider, code, SecretStr(secrets.token_urlsafe(48)))
    assert denied.status_code == 400
    assert denied.json()["error"] == "invalid_grant"
    code, verifier, _ = authorization_code(provider, "a")
    expect_status(exchange(provider, code, verifier), 200)
    expect_status(exchange(provider, code, verifier), 400)


def test_real_android_only_access_token_is_rejected(provider, api):
    payload = tokens(provider, "a", client_id="calorie-pkce-android-only")
    access = decoded(payload["access_token"])
    assert access["typ"] == "Bearer"
    assert access["aud"] == "calorie-android"
    expect_status(api.get("/api/v1/me", headers=auth(payload["access_token"])), 401)


def test_client_checks_exact_callback_and_state():
    with pytest.raises(AssertionError, match="state mismatch"):
        callback_code(CALLBACK + "?code=c&state=forged", "expected", CALLBACK)
    with pytest.raises(AssertionError, match="Unexpected authorization redirect"):
        callback_code("http://evil/callback?code=c&state=expected", "expected", CALLBACK)


@pytest.mark.parametrize(
    "redirect",
    ["pl.roseru.kalorie:/oauth2redirect", "pl.roseru.kalorie.validation:/oauth2redirect"],
)
def test_real_mobile_client_allowlist_tokens_without_claiming_apk_integration(
    provider, api, redirect
):
    payload = tokens(provider, "a", client_id="calorie-android", redirect_uri=redirect)
    access = decoded(payload["access_token"])
    audience = access["aud"]
    assert audience == "calorie-api" or "calorie-api" in audience
    assert access["typ"] == "Bearer"
    expect_status(
        api.post(
            "/api/v1/me/bootstrap",
            headers={**auth(payload["access_token"]), "Idempotency-Key": str(uuid4())},
        ),
        200,
    )
    expect_status(api.get("/api/v1/me", headers=auth(payload["id_token"])), 401)


def test_real_provider_rejects_redirect_wildcard_password_grant_and_missing_pkce(provider):
    issuer, credentials = provider
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
        params = {
            "client_id": "calorie-pkce-harness",
            "redirect_uri": CALLBACK + "/unapproved",
            "response_type": "code",
            "scope": "openid",
            "state": secrets.token_urlsafe(32),
        }
        assert (
            client.get(issuer + "/protocol/openid-connect/auth", params=params).status_code == 400
        )
        params["redirect_uri"] = CALLBACK
        denied_pkce = client.get(issuer + "/protocol/openid-connect/auth", params=params)
        if denied_pkce.status_code == 302:
            redirect = urlsplit(denied_pkce.headers["location"])
            callback = urlsplit(CALLBACK)
            assert (redirect.scheme, redirect.netloc, redirect.path) == (
                callback.scheme,
                callback.netloc,
                callback.path,
            )
            error = parse_qs(redirect.query)
            assert error.get("error") == ["invalid_request"]
            assert error.get("state") == [params["state"]]
            assert "code" not in error
        else:
            assert denied_pkce.status_code == 400
        denied = client.post(
            issuer + "/protocol/openid-connect/token",
            data={
                "client_id": "calorie-pkce-harness",
                "grant_type": "password",
                "username": credentials["a"]["username"],
                "password": credentials["a"]["password"].get_secret_value(),
            },
        )
        assert denied.status_code == 400
        assert denied.json()["error"] == "unauthorized_client"
