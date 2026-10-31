"""Opt-in isolated Keycloak26.8.1/H2/HTTP/SMTP functional acceptance.

Never updates an existing realm or stack. Raw cookies/tokens/mail/credentials stay
in a new ACL-private directory outside Git. Only own labeled test containers stop.
"""

import argparse
import base64
import hashlib
import hmac
import html
import http.cookiejar
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODULE = Path(__file__).resolve().parent
IMAGE = (
    "quay.io/keycloak/keycloak:26.8.1@sha256:"
    "a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b"
)
MAIL_IMAGE = (
    "axllent/mailpit@sha256:"
    "0790692be935ea4420d085694f7985b1f692ca6a8771ab0e0bd8ba75ac180498"
)
LABEL = "pl.roseru.calorie.emailproof.owner"
ROOT = JAR = HTTP_DIR = None
ORIGIN = ISSUER = MAIL = CALLBACK = REALM = NET = KC = SMTP = OWNER = None
HTTP_PORT = MAIL_PORT = None
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
RESULTS = {}
checks = {}
counter = 0


def save(name, value):
    path = ROOT / name
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def docker(*args):
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(
            "Docker operation failed: "
            + " ".join(args[:2])
            + ": "
            + result.stderr[:1000]
        )
    return result.stdout.strip()


def prepare():
    if (ROOT / "credentials.json").exists():
        raise RuntimeError("State already initialized")
    creds = {
        "username": "proof-admin",
        "password": secrets.token_urlsafe(30),
        "user_password": secrets.token_urlsafe(24) + "Aa1!",
        "reset_password": secrets.token_urlsafe(24) + "Bb2!",
    }
    save("credentials.json", creds)
    (ROOT / "admin.env").write_text(
        "KC_BOOTSTRAP_ADMIN_USERNAME="
        + creds["username"]
        + "\nKC_BOOTSTRAP_ADMIN_PASSWORD="
        + creds["password"]
        + "\nJAVA_OPTS_APPEND=-Xms64m -Xmx384m -XX:MaxMetaspaceSize=192m\n",
        encoding="utf-8",
    )
    realm = json.loads(
        (REPO / "infra/keycloak-email-proof/realm-flow.json").read_text(
            encoding="utf-8"
        )
    )
    realm.update(
        {
            "realm": REALM,
            "enabled": True,
            "sslRequired": "none",
            "accessTokenLifespan": 300,
            "internationalizationEnabled": True,
            "supportedLocales": ["pl", "en"],
            "defaultLocale": "en",
            "smtpServer": {
                "host": SMTP,
                "port": "1025",
                "from": "noreply@proof.test",
                "auth": "false",
                "ssl": "false",
                "starttls": "false",
            },
            "roles": {
                "realm": [
                    {
                        "name": "default-roles-" + REALM,
                        "composite": True,
                        "composites": {"client": {"calorie-api": ["user"]}},
                    }
                ],
                "client": {"calorie-api": [{"name": "user", "composite": False}]},
            },
            "defaultRole": {"name": "default-roles-" + REALM},
            "clients": [
                {
                    "clientId": "calorie-api",
                    "bearerOnly": True,
                    "protocol": "openid-connect",
                },
                {
                    "clientId": "calorie-pkce-harness",
                    "enabled": True,
                    "publicClient": True,
                    "standardFlowEnabled": True,
                    "implicitFlowEnabled": False,
                    "directAccessGrantsEnabled": False,
                    "serviceAccountsEnabled": False,
                    "protocol": "openid-connect",
                    "redirectUris": [CALLBACK],
                    "webOrigins": [],
                    "attributes": {"pkce.code.challenge.method": "S256"},
                    "defaultClientScopes": ["basic", "roles", "profile", "email"],
                    "protocolMappers": [
                        {
                            "name": "api-audience",
                            "protocol": "openid-connect",
                            "protocolMapper": "oidc-audience-mapper",
                            "config": {
                                "included.client.audience": "calorie-api",
                                "access.token.claim": "true",
                                "id.token.claim": "false",
                            },
                        }
                    ],
                },
            ],
        }
    )
    save("realm.json", realm)
    docker(
        "network",
        "create",
        "--label",
        LABEL + "=" + OWNER,
        "--opt",
        "com.docker.network.bridge.host_binding_ipv4=127.0.0.1",
        NET,
    )
    docker(
        "run",
        "-d",
        "--label",
        LABEL + "=" + OWNER,
        "--name",
        SMTP,
        "--network",
        NET,
        "--memory",
        "64m",
        "--cpus",
        "0.5",
        "--publish",
        "127.0.0.1:" + str(MAIL_PORT) + ":8025",
        MAIL_IMAGE,
    )
    jar = JAR
    docker(
        "run",
        "-d",
        "--label",
        LABEL + "=" + OWNER,
        "--name",
        KC,
        "--network",
        NET,
        "--memory",
        "768m",
        "--cpus",
        "1.0",
        "--publish",
        "127.0.0.1:" + str(HTTP_PORT) + ":8080",
        "--env-file",
        str(ROOT / "admin.env"),
        "--mount",
        "type=bind,source="
        + str(jar)
        + ",target=/opt/keycloak/providers/calorie-email-proof.jar,readonly",
        "--mount",
        "type=bind,source="
        + str(ROOT / "realm.json")
        + ",target=/opt/keycloak/data/import/"
        + REALM
        + "-realm.json,readonly",
        IMAGE,
        "start-dev",
        "--import-realm",
        "--http-host=0.0.0.0",
        "--hostname=" + ORIGIN,
        "--http-access-log-enabled=false",
    )
    save(
        "source-binding.json",
        {
            "source_digest": source_digest(),
            "jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
            "image": IMAGE,
            "keycloak_container": KC,
            "smtp_container": SMTP,
            "network": NET,
            "scope": "ISOLATED_H2_HTTP_FUNCTIONAL_ONLY",
        },
    )
    print("STARTED_ISOLATED_TEST_STACK", flush=True)


class Forms(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.forms = []
        self.current = None
        self.links = []
        self.visible = []
        self.hidden = 0
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "form":
            self.current = {
                "id": a.get("id"),
                "action": html.unescape(a.get("action", "")),
                "fields": {},
            }
            self.forms.append(self.current)
        if tag == "input" and self.current is not None and a.get("name"):
            if a.get("type") not in {"checkbox", "radio"} or "checked" in a:
                self.current["fields"][a["name"]] = a.get("value", "")
        if tag == "a" and a.get("href"):
            self.links.append(html.unescape(a["href"]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag == "form":
            self.current = None

    def handle_data(self, data):
        if data.strip() and not self.hidden:
            self.visible.append(data.strip())

    def form(self, name=None):
        found = [x for x in self.forms if name is None or x["id"] == name]
        if len(found) != 1:
            raise AssertionError(
                "Expected form "
                + str(name)
                + "; found "
                + str([x["id"] for x in self.forms])
            )
        return found[0]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Browser:
    def __init__(self):
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookies),
            NoRedirect(),
        )
        self.verifier = secrets.token_urlsafe(48)
        self.state = secrets.token_urlsafe(24)
        self.nonce = secrets.token_urlsafe(24)

    def request(self, url, data=None, follow=True, headers=None):
        global counter
        url = urllib.parse.urljoin(ORIGIN, url)
        for _ in range(12):
            body = (
                urllib.parse.urlencode(data, doseq=True).encode()
                if data is not None
                else None
            )
            check_url(url)
            req = urllib.request.Request(
                url, data=body, headers={"User-Agent": UA, **(headers or {})}
            )
            try:
                res = self.opener.open(req, timeout=25)
            except urllib.error.HTTPError as e:
                res = e
            text = res.read().decode("utf-8", errors="replace")
            status = res.code
            location = res.headers.get("Location")
            counter += 1
            HTTP_DIR.mkdir(exist_ok=True)
            (HTTP_DIR / f"{counter:04d}.html").write_text(text, encoding="utf-8")
            (HTTP_DIR / f"{counter:04d}.meta.json").write_text(
                json.dumps(
                    {
                        "url": url,
                        "method": req.get_method(),
                        "status": status,
                        "location": location,
                    }
                ),
                encoding="utf-8",
            )
            if follow and status in (301, 302, 303, 307, 308) and location:
                url = urllib.parse.urljoin(url, location)
                if is_callback(url):
                    return status, text, url
                if status in (301, 302, 303):
                    data = None
                continue
            return status, text, location
        raise AssertionError("Too many redirects")

    def begin(self, registration=False):
        path = "/protocol/openid-connect/" + (
            "registrations" if registration else "auth"
        )
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        return self.request(
            ISSUER
            + path
            + "?"
            + urllib.parse.urlencode(
                {
                    "client_id": "calorie-pkce-harness",
                    "redirect_uri": CALLBACK,
                    "response_type": "code",
                    "scope": "openid profile email",
                    "state": self.state,
                    "nonce": self.nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    def post_form(self, text, name, values, extra=()):
        form = Forms(text).form(name)
        data = {**form["fields"], **values}
        return self.request(form["action"], list(data.items()) + list(extra))


def api(url, data=None, token=None, method=None):
    headers = {"User-Agent": UA}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers=headers,
        method=method,
    )
    try:
        r = local_open(req)
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    return r.code, json.loads(raw) if raw else None


def form_request(url, data):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), headers={"User-Agent": UA}
    )
    try:
        r = local_open(req)
    except urllib.error.HTTPError as e:
        r = e
    return r.code, json.loads(r.read())


def admin_token(creds):
    status, data = form_request(
        ORIGIN + "/realms/master/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": creds["username"],
            "password": creds["password"],
        },
    )
    assert status == 200
    return data["access_token"]


def provider_users(base, token):
    status, value = api(base + "/users", token=token)
    if status != 200 or not isinstance(value, list):
        raise ValueError(
            "The provider user-count oracle did not return a successful list"
        )
    return value


def message(address, exclude=()):
    for _ in range(20):
        status, data = api(MAIL + "/api/v1/messages")
        assert status == 200
        items = [
            x
            for x in data["messages"]
            if x["ID"] not in exclude and any(y["Address"] == address for y in x["To"])
        ]
        if items:
            status, value = api(MAIL + "/api/v1/message/" + items[0]["ID"])
            assert status == 200
            save(
                "mail-" + hashlib.sha256(address.encode()).hexdigest()[:10] + ".json",
                value,
            )
            return value
        time.sleep(0.5)
    raise AssertionError("Expected SMTP message was not delivered")


def request_email(browser, address):
    status, text, _ = browser.begin(True)
    assert status == 200
    status, text, _ = browser.post_form(text, "calorie-email-proof", {"email": address})
    assert status == 200
    assert "If the address is valid" in text
    msg = message(address)
    link = re.findall(r"http://[^\s]+", msg["Text"])[-1]
    return text, link, msg


def basic_acceptance():
    for _ in range(100):
        try:
            if api(ISSUER + "/.well-known/openid-configuration")[0] == 200:
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        raise AssertionError("Keycloak did not become ready")
    creds = json.loads((ROOT / "credentials.json").read_text())
    token = admin_token(creds)
    base = ORIGIN + "/admin/realms/" + REALM
    assert (
        api(ORIGIN + "/admin/serverinfo", token=token)[1]["systemInfo"]["version"]
        == "26.8.1"
    )
    RESULTS["actual_keycloak_26_8_1"] = True
    existing = "existing-" + secrets.token_hex(5) + "@proof.test"
    new = "new-" + secrets.token_hex(5) + "@proof.test"

    def users():
        return provider_users(base, token)

    present = users()
    assert not present, "A new owned realm must begin without users"
    status, _ = api(
        base + "/users",
        {
            "username": existing,
            "email": existing,
            "emailVerified": True,
            "enabled": True,
            "credentials": [
                {
                    "type": "password",
                    "value": creds["user_password"],
                    "temporary": False,
                }
            ],
        },
        token,
        "POST",
    )
    assert status == 201
    baseline = len(users())
    b1 = Browser()
    old_text, old_link, old_mail = request_email(b1, existing)
    b2 = Browser()
    new_text, new_link, new_mail = request_email(b2, new)
    assert Forms(old_text).visible == Forms(new_text).visible
    assert old_mail["Subject"] == new_mail["Subject"]
    assert len(users()) == baseline
    RESULTS["neutral_existing_new_before_proof"] = True
    RESULTS["no_users_before_proof"] = True
    status, confirm, _ = b2.request(new_link)
    assert status == 200
    Forms(confirm).form("calorie-email-proof-confirm")
    status, confirm, _ = b2.request(new_link)
    assert status == 200
    Forms(confirm).form("calorie-email-proof-confirm")
    assert len(users()) == baseline
    RESULTS["get_does_not_consume_proof"] = True
    status, register, _ = b2.post_form(confirm, "calorie-email-proof-confirm", {})
    assert status == 200
    assert any(x["id"] == "kc-register-form" for x in Forms(register).forms)
    RESULTS["proof_post_reaches_registration"] = True
    save("progress.json", RESULTS)
    (ROOT / "register.html").write_text(register, encoding="utf-8")
    save(
        "live-context.json",
        {
            "existing": existing,
            "new": new,
            "old_link": old_link,
            "new_link": new_link,
            "verifier": b2.verifier,
            "state": b2.state,
            "nonce": b2.nonce,
        },
    )
    # Continue while preserving live cookies and the original one-use authorization context.
    values = {
        "email": new,
        "username": new,
        "firstName": "Synthetic",
        "lastName": "Proof",
        "password": creds["user_password"],
        "password-confirm": creds["user_password"],
    }
    for name, changes, extra in [
        ("email", {"email": existing}, ()),
        ("username", {"username": existing}, ()),
        ("multi-email", {}, (("email", existing),)),
    ]:
        status, register, _ = b2.post_form(
            register, "kc-register-form", {**values, **changes}, extra
        )
        assert status == 200
        assert "First confirm this exact email address" in register
        assert len(users()) == baseline
        RESULTS["tampering_" + name + "_blocked"] = True
    status, done, callback = b2.post_form(register, "kc-register-form", values)
    if status == 200 and any(
        x["id"] == "kc-passwd-update-form" for x in Forms(done).forms
    ):
        # Keycloak26.8.1 deliberately defers password entry until the verification stage.
        status, done, callback = b2.post_form(
            done,
            "kc-passwd-update-form",
            {
                "password-new": creds["user_password"],
                "password-confirm": creds["user_password"],
            },
        )
    assert callback and callback.startswith(CALLBACK), (status, Forms(done).visible)
    assert len(users()) == baseline + 1
    added = [x for x in users() if x["email"] == new]
    assert len(added) == 1 and added[0]["emailVerified"] is True
    RESULTS["registration_one_verified_account"] = True
    clients = api(base + "/clients?clientId=calorie-api", token=token)[1]
    assert len(clients) == 1
    roles = api(
        base
        + "/users/"
        + added[0]["id"]
        + "/role-mappings/clients/"
        + clients[0]["id"]
        + "/composite",
        token=token,
    )[1]
    assert [r["name"] for r in roles] == ["user"]
    RESULTS["minimal_api_role_only_user"] = True
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(callback).query)
    assert query["state"] == [b2.state]
    status, tokens = form_request(
        ISSUER + "/protocol/openid-connect/token",
        {
            "grant_type": "authorization_code",
            "client_id": "calorie-pkce-harness",
            "code": query["code"][0],
            "redirect_uri": CALLBACK,
            "code_verifier": b2.verifier,
        },
    )
    assert status == 200
    save("private-token-response.json", tokens)
    RESULTS["pkce_registration_code_exchange"] = True
    status, _ = form_request(
        ISSUER + "/protocol/openid-connect/token",
        {
            "grant_type": "authorization_code",
            "client_id": "calorie-pkce-harness",
            "code": query["code"][0],
            "redirect_uri": CALLBACK,
            "code_verifier": b2.verifier,
        },
    )
    assert status == 400
    RESULTS["authorization_code_replay_rejected"] = True
    status, text, _ = b2.request(new_link)
    assert "kc-register-form" not in text
    assert len(users()) == baseline + 1
    RESULTS["proof_link_replay_no_duplicate"] = True
    save(
        "results.json",
        {
            "scope": "ISOLATED_H2_HTTP_FUNCTIONAL_ONLY",
            "checks": RESULTS,
            "live_pg_tls": False,
            "production_release": False,
            "raw_http_directory": str(HTTP_DIR),
        },
    )
    print(json.dumps(RESULTS), flush=True)


def decode(part):
    return base64.urlsafe_b64decode(part + "=" * ((-len(part)) % 4))


def jwt(token, audience, nonce=None):
    header, payload, signature = token.split(".")
    h = json.loads(decode(header))
    p = json.loads(decode(payload))
    assert h["alg"] == "RS256"
    keys = api(ISSUER + "/protocol/openid-connect/certs")[1]["keys"]
    found = [k for k in keys if k["kid"] == h["kid"] and k["kty"] == "RSA"]
    assert len(found) == 1
    k = found[0]
    n = int.from_bytes(decode(k["n"]))
    e = int.from_bytes(decode(k["e"]))
    size = (n.bit_length() + 7) // 8
    assert size >= 256
    encoded = pow(int.from_bytes(decode(signature)), e, n).to_bytes(size)
    digest_info = (
        bytes.fromhex("3031300d060960864801650304020105000420")
        + hashlib.sha256((header + "." + payload).encode()).digest()
    )
    assert hmac.compare_digest(
        encoded,
        b"\x00\x01" + b"\xff" * (size - 3 - len(digest_info)) + b"\x00" + digest_info,
    )
    assert (
        p["iss"] == ISSUER and p["exp"] > time.time() and p["iat"] <= time.time() + 60
    )
    assert audience in ([p["aud"]] if isinstance(p["aud"], str) else p["aud"])
    if nonce is not None:
        assert p["nonce"] == nonce
    return p


def login(address, password):
    b = Browser()
    status, page, _ = b.begin()
    assert status == 200
    return b, b.post_form(
        page, "kc-form-login", {"username": address, "password": password}
    )


def exchange(b, callback, verifier=None):
    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(callback).query)
    assert parsed["state"] == [b.state]
    return form_request(
        ISSUER + "/protocol/openid-connect/token",
        {
            "grant_type": "authorization_code",
            "client_id": "calorie-pkce-harness",
            "code": parsed["code"][0],
            "redirect_uri": CALLBACK,
            "code_verifier": verifier or b.verifier,
        },
    )


def extended_acceptance():
    previous = json.loads((ROOT / "results.json").read_text())
    checks.update(previous["checks"])
    creds = json.loads((ROOT / "credentials.json").read_text())
    token = admin_token(creds)
    base = ORIGIN + "/admin/realms/" + REALM

    def users():
        return provider_users(base, token)

    count = len(users())
    # Start a real 300-second expiration window before the remaining checks.
    expiry = Browser()
    expiry_email = "expiry-" + secrets.token_hex(5) + "@proof.test"
    _, expiry_link, _ = request_email(expiry, expiry_email)
    expiry_token = urllib.parse.parse_qs(urllib.parse.urlsplit(expiry_link).query)[
        "email_proof"
    ][0]
    expiry_claims = json.loads(decode(expiry_token.split(".")[1]))
    deadline = expiry_claims["exp"]
    assert 295 <= deadline - time.time() <= 300
    save(
        "expiry-issued.json",
        {
            "issued_at": time.time(),
            "deadline": deadline,
            "token_sha256": hashlib.sha256(expiry_token.encode()).hexdigest(),
        },
    )
    # Mailbox possession permits the stock duplicate decision, never password overwrite.
    existing = "existing-extended-" + secrets.token_hex(5) + "@proof.test"
    status, _ = api(
        base + "/users",
        {
            "username": existing,
            "email": existing,
            "emailVerified": True,
            "enabled": True,
            "firstName": "Synthetic",
            "lastName": "Existing",
            "credentials": [
                {
                    "type": "password",
                    "value": creds["user_password"],
                    "temporary": False,
                }
            ],
        },
        token,
        "POST",
    )
    assert status == 201
    count += 1
    existing_row = next(u for u in users() if u["email"] == existing)
    existing_id = existing_row["id"]
    b = Browser()
    _, link, _ = request_email(b, existing)
    status, confirm, _ = b.request(link)
    assert status == 200
    status, form, _ = b.post_form(confirm, "calorie-email-proof-confirm", {})
    assert status == 200
    status, page, _ = b.post_form(
        form,
        "kc-register-form",
        {
            "email": existing,
            "username": existing,
            "firstName": "Synthetic",
            "lastName": "Existing",
            "password": creds["reset_password"],
            "password-confirm": creds["reset_password"],
        },
    )
    assert status == 200
    assert "This email is already associated with an existing account." in page
    assert (
        len(users()) == count
        and next(u for u in users() if u["email"] == existing)["id"] == existing_id
    )
    checks["existing_email_only_after_possession_no_new_user"] = True
    failed, (_, bad_page, bad_callback) = login(existing, creds["reset_password"])
    assert not (bad_callback or "").startswith(CALLBACK)
    assert "Invalid username or password" in bad_page
    good, (status, _, callback) = login(existing, creds["user_password"])
    assert callback.startswith(CALLBACK)
    checks["existing_password_not_overwritten_by_registration"] = True
    status, data = exchange(good, callback, "wrong-proof-verifier")
    assert status == 400
    checks["wrong_pkce_verifier_rejected"] = True
    good, (status, _, callback) = login(existing, creds["user_password"])
    assert callback.startswith(CALLBACK)
    status, data = exchange(good, callback)
    assert status == 200
    access = jwt(data["access_token"], "calorie-api")
    identity = jwt(data["id_token"], "calorie-pkce-harness", good.nonce)
    assert access["sub"] == existing_id and identity["sub"] == existing_id
    assert access["resource_access"]["calorie-api"]["roles"] == ["user"]
    checks["real_rsa_jwt_nonce_subject_audience_and_basic_role"] = True
    checks["access_token_lifetime_seconds"] = access["exp"] - access["iat"]
    status, _ = form_request(
        ISSUER + "/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": "calorie-pkce-harness",
            "username": existing,
            "password": creds["user_password"],
        },
    )
    assert status in (400, 401)
    checks["public_client_password_grant_refused"] = True
    # A direct registration form execution without proof cannot reach stock lookup/create.
    status, executions = api(
        base + "/authentication/flows/calorie-email-proof-v1/executions", token=token
    )
    assert status == 200
    target = next(
        x["id"]
        for x in executions
        if x.get("providerId") == "calorie-proven-email-user-creation"
    )
    direct = Browser()
    status, first, _ = direct.begin(True)
    assert status == 200
    action = Forms(first).form("calorie-email-proof")["action"]
    parts = urllib.parse.urlsplit(action)
    query = urllib.parse.parse_qs(parts.query)
    query["execution"] = [target]
    action = urllib.parse.urlunsplit(
        (*parts[:3], urllib.parse.urlencode(query, doseq=True), parts.fragment)
    )
    status, direct_page, _ = direct.request(
        action,
        {
            "email": existing,
            "username": existing,
            "firstName": "Synthetic",
            "lastName": "Bypass",
            "password": creds["reset_password"],
            "password-confirm": creds["reset_password"],
        },
    )
    assert (
        not any(
            s in direct_page
            for s in (
                "This email is already associated",
                "Username already exists",
                "Email already exists",
            )
        )
        and len(users()) == count
    )
    checks["direct_post_without_proof_no_lookup_or_account"] = True
    # Real foreign tab plus a corrupted signature; neither creates an account.
    bad = Browser()
    bad_email = "signature-" + secrets.token_hex(5) + "@proof.test"
    _, bad_link, _ = request_email(bad, bad_email)
    parts = urllib.parse.urlsplit(bad_link)
    query = urllib.parse.parse_qs(parts.query)
    query["tab_id"] = ["not-the-original-tab"]
    foreign = urllib.parse.urlunsplit(
        (*parts[:3], urllib.parse.urlencode(query, doseq=True), parts.fragment)
    )
    status, foreign_page, _ = Browser().request(foreign)
    assert "kc-register-form" not in foreign_page and len(users()) == count
    checks["foreign_tab_browser_fenced"] = True
    query = urllib.parse.parse_qs(parts.query)
    proof = query["email_proof"][0]
    seg = proof.split(".")
    sig = bytearray(decode(seg[2]))
    sig[0] ^= 1
    seg[2] = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    query["email_proof"] = [".".join(seg)]
    altered = urllib.parse.urlunsplit(
        (*parts[:3], urllib.parse.urlencode(query, doseq=True), parts.fragment)
    )
    status, confirm, _ = bad.request(altered)
    assert status == 200
    status, page, _ = bad.post_form(confirm, "calorie-email-proof-confirm", {})
    assert status == 200 and "The link is invalid" in page
    assert len(users()) == count
    checks["real_signature_tampering_refused"] = True
    # Standard reset flow stays usable, preserves the subject and invalidates the old password.
    reset = Browser()
    status, login_page, _ = reset.begin()
    assert status == 200
    reset_url = next(
        x for x in Forms(login_page).links if "/login-actions/reset-credentials" in x
    )
    status, reset_page, _ = reset.request(reset_url)
    assert status == 200
    old_message_ids = {x["ID"] for x in api(MAIL + "/api/v1/messages")[1]["messages"]}
    status, sent, _ = reset.post_form(
        reset_page, "kc-reset-password-form", {"username": existing}
    )
    assert status == 200
    reset_mail = message(existing, old_message_ids)
    reset_link = re.findall(r"http://[^\s]+", reset_mail["Text"])[-1]
    status, password_page, _ = reset.request(reset_link)
    assert status == 200
    status, _, reset_callback = reset.post_form(
        password_page,
        "kc-passwd-update-form",
        {
            "password-new": creds["reset_password"],
            "password-confirm": creds["reset_password"],
            "logout-sessions": "on",
        },
    )
    assert status in (200, 302, 303)
    _, (_, old_page, old_callback) = login(existing, creds["user_password"])
    assert not (old_callback or "").startswith(CALLBACK)
    assert "Invalid username or password" in old_page
    good, (_, _, callback) = login(existing, creds["reset_password"])
    assert callback.startswith(CALLBACK)
    status, data = exchange(good, callback)
    assert (
        status == 200 and jwt(data["access_token"], "calorie-api")["sub"] == existing_id
    )
    assert len(users()) == count
    checks["standard_reset_then_fresh_pkce_same_subject"] = True
    # A stopped owned SMTP container causes an explicit error without creating a user.
    docker("stop", SMTP)
    try:
        outage = Browser()
        status, first, _ = outage.begin(True)
        assert status == 200
        status, page, _ = outage.post_form(
            first,
            "calorie-email-proof",
            {"email": "outage-" + secrets.token_hex(5) + "@proof.test"},
        )
        assert (
            status == 200
            and "The message could not be sent" in page
            and len(users()) == count
        )
        checks["real_smtp_outage_visible_no_account"] = True
    finally:
        docker("start", SMTP)
    save("extended-progress.json", checks)
    while time.time() <= deadline + 2:
        print(
            "WAITING_REAL_EXPIRY " + str(max(0, int(deadline + 2 - time.time()))) + "s",
            flush=True,
        )
        time.sleep(min(30, max(0.1, deadline + 3 - time.time())))
    token = admin_token(creds)
    status, page, _ = expiry.request(expiry_link)
    assert "kc-register-form" not in page
    if any(x["id"] == "calorie-email-proof-confirm" for x in Forms(page).forms):
        status, page, _ = expiry.post_form(page, "calorie-email-proof-confirm", {})
        assert "The link is invalid" in page
    assert len(users()) == count
    checks["actual_300_second_proof_expiry_no_account"] = True
    save(
        "extended-results.json",
        {
            "scope": "ISOLATED_H2_HTTP_FUNCTIONAL_ONLY",
            "checks": checks,
            "live_pg_tls": False,
            "raw_http_directory": str(HTTP_DIR),
            "production_release": False,
        },
    )
    print(json.dumps(checks), flush=True)


def check_url(url):
    p = urllib.parse.urlsplit(url)
    if (
        p.scheme != "http"
        or p.hostname != "127.0.0.1"
        or p.port not in {HTTP_PORT, MAIL_PORT}
        or p.username is not None
        or p.password is not None
    ):
        raise ValueError("Only the owned loopback test endpoints are permitted")


def is_callback(url):
    p = urllib.parse.urlsplit(url)
    target = urllib.parse.urlsplit(CALLBACK)
    return (p.scheme, p.netloc, p.path) == (
        target.scheme,
        target.netloc,
        target.path,
    ) and not p.fragment


def local_open(request):
    check_url(request.full_url)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    ).open(request, timeout=20)


def source_digest():
    h = hashlib.sha256()
    for path in sorted(MODULE.rglob("*")):
        if path.is_file() and not any(
            part in {"build", ".gradle", "__pycache__"}
            for part in path.relative_to(MODULE).parts
        ):
            h.update(path.relative_to(MODULE).as_posix().encode())
            h.update(b"\0")
            h.update(path.read_bytes())
    return h.hexdigest()


def owned_container(name):
    result = subprocess.run(
        ["docker", "inspect", name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        return None
    value = json.loads(result.stdout)[0]
    if (
        value.get("Name") != "/" + name
        or value.get("Config", {}).get("Labels", {}).get(LABEL) != OWNER
    ):
        raise ValueError("Cleanup refused for a container not owned by this trial")
    return value


def stop_owned():
    # Validate both before stopping either. Retain stopped containers/H2 for review.
    observed = [(name, owned_container(name)) for name in (KC, SMTP)]
    for name, value in observed:
        if value:
            logs = subprocess.run(
                ["docker", "logs", name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            (ROOT / (name + ".log")).write_text(
                logs.stdout + logs.stderr, encoding="utf-8"
            )
            save(name + "-inspection.json", value)
            if value.get("State", {}).get("Running"):
                docker("stop", name)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--run-isolated-http-h2",
        action="store_true",
        help="Explicitly create a new test-only stack, never production",
    )
    p.add_argument(
        "--state",
        type=Path,
        required=True,
        help="New private directory outside the repository",
    )
    p.add_argument(
        "--jar",
        type=Path,
        required=True,
        help="Built provider JAR for this exact source",
    )
    p.add_argument("--http-port", type=int, default=29480)
    p.add_argument("--mail-port", type=int, default=29425)
    return p


def configure(args):
    global \
        ROOT, \
        JAR, \
        HTTP_DIR, \
        ORIGIN, \
        ISSUER, \
        MAIL, \
        CALLBACK, \
        REALM, \
        NET, \
        KC, \
        SMTP, \
        OWNER, \
        HTTP_PORT, \
        MAIL_PORT
    if not args.run_isolated_http_h2:
        raise ValueError("The explicit isolated test flag is required")
    if not args.state.is_absolute():
        raise ValueError("Absolute new private state path required")
    target = args.state.resolve()
    if target.exists() or target.is_relative_to(REPO):
        raise ValueError("State must be new and outside the repository")
    jar = args.jar.resolve(strict=True)
    if not jar.is_file() or jar.suffix != ".jar":
        raise ValueError("Provider JAR required")
    if (
        not (1024 <= args.http_port < 65535 and 1024 <= args.mail_port <= 65535)
        or len({args.http_port, args.http_port + 1, args.mail_port}) != 3
    ):
        raise ValueError("Distinct nonprivileged test ports required")
    context = json.loads(docker("context", "inspect"))[0]["Endpoints"]["docker"]["Host"]
    endpoint = os.environ.get("DOCKER_HOST", context)
    if not endpoint.startswith(("npipe://", "unix://")):
        raise ValueError("Only a local Docker engine is permitted")
    for port in (args.http_port, args.mail_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    target.mkdir(parents=True, mode=0o700)
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami"], capture_output=True, text=True, check=True
        ).stdout.strip()
        subprocess.run(
            [
                "icacls",
                str(target),
                "/inheritance:r",
                "/grant:r",
                identity + ":(OI)(CI)F",
            ],
            capture_output=True,
            check=True,
        )
    ROOT = target
    JAR = jar
    HTTP_PORT = args.http_port
    MAIL_PORT = args.mail_port
    OWNER = secrets.token_hex(12)
    REALM = NET = "calorie-email-proof-" + OWNER
    KC = NET + "-keycloak"
    SMTP = NET + "-mail"
    ORIGIN = "http://127.0.0.1:" + str(HTTP_PORT)
    ISSUER = ORIGIN + "/realms/" + REALM
    MAIL = "http://127.0.0.1:" + str(MAIL_PORT)
    CALLBACK = "http://127.0.0.1:" + str(HTTP_PORT + 1) + "/callback"
    HTTP_DIR = ROOT / "http"
    save(
        "ownership.json",
        {"owner": OWNER, "containers": [KC, SMTP], "network": NET, "realm": REALM},
    )


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        configure(args)
        prepare()
        basic_acceptance()
        extended_acceptance()
        print(
            "ISOLATED_H2_HTTP_FUNCTIONAL_PASS; private evidence: " + str(ROOT),
            flush=True,
        )
        return 0
    except Exception:
        if ROOT is not None:
            (ROOT / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(
            "ISOLATED_ACCEPTANCE_FAILED; no production verdict",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if ROOT is not None and OWNER is not None:
            stop_owned()


if __name__ == "__main__":
    raise SystemExit(main())
