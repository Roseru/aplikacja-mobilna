"""Real HTTPS/PKCE/API/ACL/restart checks; no mocks, secrets or token output."""

import base64
import hashlib
import json
import secrets
import ssl
import subprocess
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from run import private_write

from calorie_app.health import EXPECTED_REVISION

MOBILE_CALLBACK = "pl.roseru.kalorie:/oauth2redirect"
VALIDATION_CALLBACK = "pl.roseru.kalorie.validation:/oauth2redirect"
PROBE_CALLBACK = "http://127.0.0.1:8765/callback"


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and values.get("id") == "kc-form-login":
            self.action = values.get("action")


def expect(response, status):
    if response.status_code != status:
        raise RuntimeError(f"Integration HTTP check expected {status}, got {response.status_code}")
    return response


class Probe:
    def __init__(self, stack):
        self.stack = stack
        self.issuer = stack.origin + "/realms/calorie-dev"
        self.trust = ssl.create_default_context(cafile=stack.state / "tls/ca.pem")
        self.credentials = json.loads((stack.state / "credentials.json").read_text())

    def client(self):
        return httpx.Client(verify=self.trust, trust_env=False, timeout=15, follow_redirects=False)

    def fresh_accounts(self):
        """Own fixture accounts; never reset shared data or relax sync limits."""
        suffix = secrets.token_hex(8)
        with self.client() as client:
            # Password grant is only for Keycloak's administrative CLI in the master realm.
            # The public Android clients in calorie-dev continue to forbid it.
            admin = expect(
                client.post(
                    self.stack.origin + "/realms/master/protocol/openid-connect/token",
                    data={
                        "grant_type": "password",
                        "client_id": "admin-cli",
                        **self.credentials["admin"],
                    },
                ),
                200,
            ).json()["access_token"]
            headers = {"Authorization": "Bearer " + admin}
            base = self.stack.origin + "/admin/realms/calorie-dev"
            api = expect(
                client.get(base + "/clients", params={"clientId": "calorie-api"}, headers=headers),
                200,
            ).json()
            if len(api) != 1:
                raise RuntimeError("API client unavailable for fixture role mapping")
            api_id = api[0]["id"]
            role = expect(
                client.get(base + f"/clients/{api_id}/roles/user", headers=headers), 200
            ).json()
            credentials = {}
            for name in ("a", "b"):
                username = f"integration-probe-{suffix}-{name}"
                email = username + "@invalid.example"
                password = secrets.token_hex(32)
                created = expect(
                    client.post(
                        base + "/users",
                        headers=headers,
                        json={
                            "username": username,
                            "enabled": True,
                            "emailVerified": True,
                            "firstName": "Integration",
                            "lastName": name.upper(),
                            "email": email,
                            "requiredActions": [],
                            "credentials": [
                                {"type": "password", "value": password, "temporary": False}
                            ],
                        },
                    ),
                    201,
                )
                location = created.headers["location"]
                prefix = base + "/users/"
                if not location.startswith(prefix):
                    raise RuntimeError("Untrusted administrative user location")
                subject = location.removeprefix(prefix)
                subject = str(UUID(subject))
                # email-as-username realms persist the email instead of the requested
                # bare name. Read only this newly created subject; never search/reset
                # accounts or assume that accepting a POST preserved the login name.
                persisted = expect(
                    client.get(base + f"/users/{subject}", headers=headers), 200
                ).json()
                if (
                    persisted.get("id") != subject
                    or persisted.get("username") not in {username, email}
                    or persisted.get("email") != email
                    or persisted.get("firstName") != "Integration"
                    or persisted.get("lastName") != name.upper()
                    or persisted.get("enabled") is not True
                    or persisted.get("emailVerified") is not True
                ):
                    raise RuntimeError("Created fixture identity does not match the requested user")
                expect(
                    client.post(
                        base + f"/users/{subject}/role-mappings/clients/{api_id}",
                        headers=headers,
                        json=[role],
                    ),
                    204,
                )
                credentials[name] = {"username": persisted["username"], "password": password}
        self.credentials = credentials
        private_write(
            self.stack.state / f"probe-credentials-{suffix}.json", json.dumps(credentials)
        )

    def code(self, who="a", *, client_id="calorie-android", callback=MOBILE_CALLBACK):
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(
            b"="
        )
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.client() as browser:
            response = expect(
                browser.get(
                    self.issuer + "/protocol/openid-connect/auth",
                    params={
                        "client_id": client_id,
                        "redirect_uri": callback,
                        "response_type": "code",
                        "scope": "openid profile" if client_id == "calorie-android" else "openid",
                        "state": state,
                        "nonce": nonce,
                        "code_challenge": challenge.decode(),
                        "code_challenge_method": "S256",
                    },
                ),
                200,
            )
            form = LoginForm()
            form.feed(response.text)
            if not form.action or not form.action.startswith(self.issuer + "/login-actions/"):
                raise RuntimeError("Trusted login form missing")
            credential = self.credentials[who]
            response = browser.post(
                form.action,
                data={
                    "username": credential["username"],
                    "password": credential["password"],
                    "credentialId": "",
                },
            )
            if response.status_code not in {302, 303}:
                raise RuntimeError("Real login failed")
            parsed, target = urlsplit(response.headers["location"]), urlsplit(callback)
            query = parse_qs(parsed.query)
            if (
                (parsed.scheme, parsed.netloc, parsed.path)
                != (target.scheme, target.netloc, target.path)
                or query.get("state") != [state]
                or len(query.get("code", [])) != 1
            ):
                raise RuntimeError("Callback/state validation failed")
            return query["code"][0], verifier, nonce

    def exchange(self, code, verifier, *, client_id="calorie-android", callback=MOBILE_CALLBACK):
        with self.client() as client:
            return client.post(
                self.issuer + "/protocol/openid-connect/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "redirect_uri": callback,
                    "code": code,
                    "code_verifier": verifier,
                },
            )

    def login(self, who="a", *, client_id="calorie-android", callback=MOBILE_CALLBACK):
        code, verifier, nonce = self.code(who, client_id=client_id, callback=callback)
        payload = expect(
            self.exchange(code, verifier, client_id=client_id, callback=callback), 200
        ).json()
        with self.client() as client:
            keys = expect(client.get(self.issuer + "/protocol/openid-connect/certs"), 200).json()[
                "keys"
            ]
        header = jwt.get_unverified_header(payload["id_token"])
        key = next(key for key in keys if key["kid"] == header["kid"])
        identity = jwt.decode(
            payload["id_token"],
            RSAAlgorithm.from_jwk(key),
            algorithms=["RS256"],
            issuer=self.issuer,
            audience=client_id,
        )
        if identity["nonce"] != nonce:
            raise RuntimeError("OIDC nonce validation failed")
        return payload

    def api(self, method, path, *, token=None, **kwargs):
        headers = kwargs.pop("headers", {})
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        with self.client() as client:
            response = client.request(method, self.stack.origin + path, headers=headers, **kwargs)
        if "no-store" not in response.headers.get("cache-control", ""):
            raise RuntimeError("Private API response lost no-store")
        return response

    def ready(self):
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                with self.client() as client:
                    health = client.get(self.stack.origin + "/health/ready")
                    discovery = client.get(self.issuer + "/.well-known/openid-configuration")
                if health.status_code == discovery.status_code == 200:
                    if discovery.json()["issuer"] != self.issuer:
                        raise RuntimeError("Issuer changed")
                    return
            except httpx.TransportError:
                pass
            time.sleep(2)
        raise RuntimeError("Services did not become ready over verified HTTPS")


def verify(stack):
    private_write(stack.state / "verification.json", json.dumps({"result": "RUNNING"}))
    probe = Probe(stack)
    checks = []

    def passed(name):
        checks.append(name)
        print("PASS " + name, flush=True)

    probe.ready()
    passed("HTTPS discovery / exact issuer / API readiness")
    try:
        with httpx.Client(trust_env=False, timeout=5) as untrusted:
            untrusted.get(stack.origin + "/health/live")
    except httpx.ConnectError as error:
        if "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise RuntimeError("Unknown-CA probe failed for a non-TLS reason") from None
        passed("Unknown CA rejected (TLS verification remains enabled)")
    else:
        raise RuntimeError("Untrusted TLS unexpectedly accepted")

    probe.fresh_accounts()
    passed("Fresh fixture accounts; existing accounts/history and sync resource limits preserved")

    expect(probe.api("GET", "/api/v1/me"), 401)
    expect(probe.api("GET", "/api/v1/me", token="invalid"), 401)
    a, b = probe.login("a"), probe.login("b", callback=VALIDATION_CALLBACK)
    expect(probe.api("GET", "/api/v1/me", token=a["id_token"]), 401)
    wrong = probe.login(client_id="calorie-pkce-android-only", callback=PROBE_CALLBACK)
    expect(probe.api("GET", "/api/v1/me", token=wrong["access_token"]), 401)
    passed("Both Android callbacks / signed nonce / bad JWT, ID token and wrong audience rejected")

    code, verifier, _ = probe.code()
    expect(probe.exchange(code, secrets.token_urlsafe(48)), 400)
    code, verifier, _ = probe.code()
    expect(probe.exchange(code, verifier), 200)
    expect(probe.exchange(code, verifier), 400)
    with probe.client() as client:
        expect(
            client.post(
                probe.issuer + "/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "calorie-android",
                    **probe.credentials["a"],
                },
            ),
            400,
        )
        expect(
            client.get(
                probe.issuer + "/protocol/openid-connect/auth",
                params={
                    "client_id": "calorie-android",
                    "redirect_uri": "https://invalid.example/callback",
                    "response_type": "code",
                    "scope": "openid",
                },
            ),
            400,
        )
        missing = client.get(
            probe.issuer + "/protocol/openid-connect/auth",
            params={
                "client_id": "calorie-android",
                "redirect_uri": MOBILE_CALLBACK,
                "response_type": "code",
                "scope": "openid",
                "state": "probe-missing-pkce",
            },
        )
        if missing.status_code == 302:
            query = parse_qs(urlsplit(missing.headers["location"]).query)
            if query.get("error") != ["invalid_request"] or "code" in query:
                raise RuntimeError("Missing PKCE not rejected")
        else:
            expect(missing, 400)
    passed("Wrong/missing PKCE, code replay, password grant and unapproved redirect rejected")

    pairs = [(a, str(uuid4())), (b, str(uuid4()))]
    bootstrap = []
    for payload, key in pairs:
        headers = {"Idempotency-Key": key}
        first = expect(
            probe.api(
                "POST", "/api/v1/me/bootstrap", token=payload["access_token"], headers=headers
            ),
            200,
        ).json()
        repeated = expect(
            probe.api(
                "POST", "/api/v1/me/bootstrap", token=payload["access_token"], headers=headers
            ),
            200,
        ).json()
        if first != repeated:
            raise RuntimeError("Bootstrap replay changed")
        bootstrap.append(first)
    if bootstrap[0]["account_id"] == bootstrap[1]["account_id"]:
        raise RuntimeError("Account isolation failed")
    before = [
        expect(probe.api("GET", "/api/v1/me", token=t["access_token"]), 200).json() for t in (a, b)
    ]
    value = {"ranking": not before[0]["consents"]["ranking"], "automatic_energy_adjustment": False}
    expect(
        probe.api(
            "PUT",
            "/api/v1/me/consents",
            token=a["access_token"],
            json=value,
            headers={
                "Idempotency-Key": str(uuid4()),
                "If-Match": f'"{before[0]["consents"]["revision"]}"',
            },
        ),
        200,
    )
    after = [
        expect(probe.api("GET", "/api/v1/me", token=t["access_token"]), 200).json() for t in (a, b)
    ]
    if before[1] != after[1] or after[0]["consents"]["ranking"] != value["ranking"]:
        raise RuntimeError("Account A mutation affected B")
    pull = expect(
        probe.api(
            "GET",
            "/api/v1/sync/pull",
            token=a["access_token"],
            params={
                "sync_epoch": bootstrap[0]["sync_epoch"],
                "limit": 500,
            },
        ),
        200,
    ).json()
    checkpoint = pull.get("checkpoint")
    if not checkpoint:
        raise RuntimeError("Completed sync checkpoint missing")
    passed("A/B isolation / bootstrap idempotency / consent write / full sync checkpoint")

    revision = stack.sql("calorie_app", "SELECT version_num FROM app.alembic_version;")
    if revision != EXPECTED_REVISION:
        raise RuntimeError("Unexpected migration head")
    permissions = stack.sql(
        "calorie_app",
        """
SELECT (NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole)::text
FROM pg_roles WHERE rolname IN ('calorie_app_api','calorie_app_worker','keycloak');
SELECT has_database_privilege('calorie_app_api','keycloak','CONNECT')::text;
SELECT has_database_privilege('keycloak','calorie_app','CONNECT')::text;
SELECT has_schema_privilege('calorie_app_api','app','CREATE')::text;
SELECT has_table_privilege('calorie_app_api','app.user_accounts','INSERT')::text;
""",
    )
    if permissions.splitlines() != ["true", "true", "true", "false", "false", "false", "true"]:
        raise RuntimeError("Database privilege boundaries failed")
    # Exercise a denied DDL statement as the actual API role; no state is changed.
    api_ddl = stack.sql(
        "calorie_app",
        """
SET ROLE calorie_app_api;
DO $$ BEGIN
  BEGIN EXECUTE 'CREATE TABLE app.integration_ddl_probe(id integer)';
    RAISE EXCEPTION 'API unexpectedly has DDL';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
""",
    )
    if "DO" not in api_ddl:
        raise RuntimeError("DDL rejection probe failed")
    # Docker Compose emits NDJSON; assert only the TLS gateway publishes a host port.
    rows = stack.compose("ps", "--all", "--format", "json").strip()
    containers = [json.loads(row) for row in rows.splitlines()]
    for container in containers:
        published = [
            port
            for port in container.get("Publishers", []) or []
            if port.get("PublishedPort", 0) > 0
        ]
        if published and container["Service"] != "gateway":
            raise RuntimeError("A database/internal service publishes a host port")
    for service, expected in (("api", "10001"), ("retention", "10001"), ("keycloak", "1000")):
        actual = stack.compose("exec", "-T", service, "id", "-u").strip()
        if actual != expected:
            raise RuntimeError("Unexpected runtime service UID")
    passed("Current migration / least privilege / denied API DDL / internal DB / non-root services")

    marker = secrets.token_hex(16)
    stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "-v",
        stack.config["project"] + "_catalog_data:/catalog",
        "migrate",
        ".venv/bin/python",
        "-c",
        "from pathlib import Path; Path('/catalog/integration-probe').write_text('" + marker + "')",
    )
    stack.compose(
        "exec",
        "-T",
        "api",
        ".venv/bin/python",
        "-c",
        """
import errno
from pathlib import Path
try:
    Path('/catalog/integration-denied').write_text('forbidden')
except OSError as error:
    assert error.errno in (errno.EROFS, errno.EACCES)
else:
    raise AssertionError('API unexpectedly can write catalog artifacts')
""",
    )
    passed("Catalog storage is writable by a separate operator, read-only for API")

    stack.compose("down")  # Preserve volumes and the exact secret/certificate files.
    stack.up()
    probe.ready()
    fresh = [probe.login("a"), probe.login("b", callback=VALIDATION_CALLBACK)]
    for index, payload in enumerate(fresh):
        current = expect(probe.api("GET", "/api/v1/me", token=payload["access_token"]), 200).json()
        if current != after[index]:
            raise RuntimeError("Account/data/epoch changed across down/up")
        replay = expect(
            probe.api(
                "POST",
                "/api/v1/me/bootstrap",
                token=payload["access_token"],
                headers={"Idempotency-Key": pairs[index][1]},
            ),
            200,
        ).json()
        if replay != bootstrap[index]:
            raise RuntimeError("Receipt changed across restart")
    expect(
        probe.api(
            "GET",
            "/api/v1/sync/pull",
            token=fresh[0]["access_token"],
            params={
                "sync_epoch": bootstrap[0]["sync_epoch"],
                "checkpoint": checkpoint,
                "limit": 500,
            },
        ),
        200,
    )
    content = stack.compose(
        "exec",
        "-T",
        "api",
        ".venv/bin/python",
        "-c",
        "from pathlib import Path; print(Path('/catalog/integration-probe').read_text())",
    )
    if content.strip() != marker:
        raise RuntimeError("Catalog storage did not survive restart")
    stack.compose(
        "run",
        "--rm",
        "--no-deps",
        "-v",
        stack.config["project"] + "_catalog_data:/catalog",
        "migrate",
        ".venv/bin/python",
        "-c",
        "from pathlib import Path; Path('/catalog/integration-probe').unlink()",
    )
    passed("Down/up preserves both DBs, identities, epoch, receipts, signed checkpoint and catalog")

    status = json.loads(
        stack.compose(
            "exec", "-T", "retention", ".venv/bin/python", "/opt/retention/worker.py", "status"
        )
    )
    if status["state"] not in {"ok", "pending"} or not status["last_success"]:
        raise RuntimeError("Retention worker did not finish a healthy bounded pass after restart")
    worker_acl = stack.sql(
        "calorie_app",
        """
SELECT has_schema_privilege('calorie_app_worker','app','CREATE')::text;
SELECT has_database_privilege('calorie_app_worker','keycloak','CONNECT')::text;
SELECT pg_has_role('calorie_app_worker','calorie_app_deletion_operator','MEMBER')::text;
""",
    )
    if worker_acl.splitlines() != ["false", "false", "false"]:
        raise RuntimeError("Worker privilege boundaries failed")
    passed(
        "Periodic retention worker healthy after restart; own role/UID, no DDL/deletion/identity DB"
    )

    private_write(
        stack.state / "verification.json",
        json.dumps(
            {
                "verified_at": datetime.now(UTC).isoformat(),
                "origin": stack.origin,
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
                "worktree_dirty": bool(
                    subprocess.check_output(
                        ["git", "status", "--porcelain", "--untracked-files=normal"]
                    ).strip()
                ),
                "migration": revision,
                "checks": checks,
                "result": "PASS",
                "scope": "Local infra; excludes APK, official catalog, SMTP and restore",
            },
            indent=2,
        ),
    )
