"""Local-only Compose lifecycle. Secrets and proof remain in ignored/private state."""

import argparse
import csv
import ipaddress
import json
import os
import re
import secrets
import ssl
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_STATE = ROOT / ".tools" / "local-integration"


def private_write(path, text, *, public=False):
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o644 if public else 0o600)


def host_address(value):
    address = ipaddress.IPv4Address(value)
    if not (
        address.is_loopback
        or any(
            address in network
            for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            )
        )
    ):
        raise ValueError("Choose loopback or a local RFC1918 IPv4 address")
    return str(address)


def certificates(destination, host):
    destination.mkdir(mode=0o755)
    now = datetime.now(UTC)
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Calorie local integration CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(authority.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=730))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(authority.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(authority.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), True
        )
        .sign(authority, hashes.SHA256())
    )
    private_write(
        destination / "ca.key",
        authority.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    private_write(
        destination / "ca.pem", ca.public_bytes(serialization.Encoding.PEM).decode(), public=True
    )
    renew_certificate(destination, host)


def renew_certificate(destination, host):
    """Renew only the server leaf; CA, issuer, database credentials and signing key stay fixed."""
    ca = x509.load_pem_x509_certificate((destination / "ca.pem").read_bytes())
    authority = serialization.load_pem_private_key((destination / "ca.key").read_bytes(), None)
    now = datetime.now(UTC)
    if ca.not_valid_after_utc <= now + timedelta(days=1):
        raise ValueError(
            "CA expiry requires a separate trust migration; do not replace it implicitly"
        )
    server = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
        .issuer_name(ca.subject)
        .public_key(server.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(server.public_key()), False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(authority.public_key()), False
        )
        .add_extension(
            x509.KeyUsage(True, False, True, False, False, False, False, False, False), True
        )
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(host)), x509.DNSName("gateway")]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(authority, hashes.SHA256())
    )
    private_write(
        destination / "server.key",
        server.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    )
    private_write(
        destination / "server.pem",
        leaf.public_bytes(serialization.Encoding.PEM).decode(),
        public=True,
    )


def env_file(state, name, values):
    private_write(state / name, "".join(f"{key}={value}\n" for key, value in values.items()))


def prepare_worker(state):
    """Upgrade existing private state without rotating any database password or other secret."""
    target = state / "worker.env"
    if target.exists():
        return
    values = dict(line.split("=", 1) for line in (state / "postgres.env").read_text().splitlines())
    password = values["APP_WORKER_PASSWORD"]
    if not re.fullmatch(r"[0-9a-f]{64}", password):
        raise ValueError("Unexpected existing worker credential format; preserve state")
    env_file(
        state,
        "worker.env",
        {
            "DATABASE_URL": f"postgresql+psycopg://calorie_app_worker:{password}@postgres/calorie_app",
            "ENVIRONMENT": "development",
        },
    )


def safe_compose_error(state, message):
    """Allow CI diagnostics without publishing generated credentials or token-shaped strings."""
    values = []
    for path in state.glob("*.env"):
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if value and any(word in key for word in ("PASSWORD", "SECRET", "DATABASE_URL")):
                values.append(value)
    for path in state.glob("*credentials*.json"):
        for credential in json.loads(path.read_text()).values():
            values.append(credential["password"])
    for value in sorted(values, key=len, reverse=True):
        message = message.replace(value, "[redacted]")
    message = re.sub(
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[redacted-jwt]", message
    )
    return message[-4000:]


def initialize(state, host="127.0.0.1", port=18443, project="calorie-integration"):
    host = host_address(host)
    if not 1024 <= port <= 65535 or not re.fullmatch(r"[a-z][a-z0-9-]{0,50}", project):
        raise ValueError("Invalid local port or Compose project name")
    if state.exists():
        raise ValueError("State already exists; initialization never overwrites data or secrets")
    if ROOT in state.parents and ROOT / ".tools" not in state.parents:
        raise ValueError("State inside the checkout must be under ignored .tools")
    state.mkdir(parents=True, mode=0o700)
    if os.name == "nt":
        identity = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader([identity.strip()]))[1]
        subprocess.run(
            [
                "icacls",
                str(state),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    certificates(state / "tls", host)
    origin = f"https://{host}:{port}"
    passwords = {
        name: secrets.token_hex(32) for name in ("admin", "migrator", "api", "worker", "kc")
    }
    env_file(
        state,
        "postgres.env",
        {
            "POSTGRES_PASSWORD": passwords["admin"],
            "APP_MIGRATOR_PASSWORD": passwords["migrator"],
            "APP_API_PASSWORD": passwords["api"],
            "APP_WORKER_PASSWORD": passwords["worker"],
            "KEYCLOAK_DB_PASSWORD": passwords["kc"],
        },
    )
    common = {
        "CATALOG_PAGE_TOKEN_SECRET": secrets.token_hex(32),
        "CATALOG_ARTIFACT_ROOT": "/catalog",
    }
    env_file(
        state,
        "api.env",
        common
        | {
            "DATABASE_URL": f"postgresql+psycopg://calorie_app_api:{passwords['api']}@postgres/calorie_app",
            "ENVIRONMENT": "development",
            "OIDC_ISSUER": origin + "/realms/calorie-dev",
            "OIDC_JWKS_URL": "https://gateway:8443/realms/calorie-dev/protocol/openid-connect/certs",
            "OIDC_CA_BUNDLE": "/run/trust/ca.pem",
            "OIDC_ALLOW_LOCAL_HTTP": "false",
        },
    )
    env_file(
        state,
        "migrate.env",
        {
            "DATABASE_URL": f"postgresql+psycopg://calorie_app_migrator:{passwords['migrator']}@postgres/calorie_app",
        },
    )
    admin_password = secrets.token_hex(32)
    env_file(
        state,
        "keycloak.env",
        {
            "KC_DB": "postgres",
            "KC_DB_URL": "jdbc:postgresql://postgres:5432/keycloak",
            "KC_DB_USERNAME": "keycloak",
            "KC_DB_PASSWORD": passwords["kc"],
            "KC_HOSTNAME": origin,
            "KC_HTTP_ENABLED": "true",
            "KC_PROXY_HEADERS": "xforwarded",
            "KC_HTTP_ACCESS_LOG_ENABLED": "false",
            "KC_HTTP_MANAGEMENT_SCHEME": "http",
            "KC_BOOTSTRAP_ADMIN_USERNAME": "local-admin",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": admin_password,
        },
    )
    realm = json.loads((ROOT / "infra/local/keycloak/realm.json").read_text(encoding="utf-8"))
    realm["sslRequired"] = "all"
    # O1 requests openid profile. Keep the O2 harness template untouched and add only
    # the optional standard scope to the actual Android client in local integration.
    for client in realm["clients"]:
        if client["clientId"] == "calorie-android":
            client["optionalClientScopes"] = ["profile"]
    users = {
        name: {"username": f"integration-{name}", "password": secrets.token_hex(32)}
        for name in ("a", "b")
    }
    realm["users"] = [
        {
            "username": value["username"],
            "enabled": True,
            "emailVerified": True,
            "firstName": "Integration",
            "lastName": name.upper(),
            "email": f"integration-{name}@invalid.example",
            "requiredActions": [],
            "credentials": [{"type": "password", "value": value["password"], "temporary": False}],
            "clientRoles": {"calorie-api": ["user"]},
        }
        for name, value in users.items()
    ]
    (state / "realm").mkdir(mode=0o755)
    # Container UID 1000 must read this file. Its parent state directory is private.
    private_write(
        state / "realm/calorie-dev.json", json.dumps(realm, ensure_ascii=False), public=True
    )
    private_write(
        state / "credentials.json",
        json.dumps(users | {"admin": {"username": "local-admin", "password": admin_password}}),
    )
    config = {"host": host, "port": port, "origin": origin, "project": project}
    private_write(state / "config.json", json.dumps(config))
    env_file(
        state,
        "compose.env",
        {
            "INTEGRATION_STATE": state.as_posix(),
            "INTEGRATION_HOST": host,
            "INTEGRATION_PORT": port,
            "INTEGRATION_PROJECT": project,
        },
    )
    return config


class Stack:
    def __init__(self, state):
        self.state = state.resolve()
        self.config = json.loads((self.state / "config.json").read_text())
        self.origin = self.config["origin"]

    def compose(self, *arguments, input_text=None):
        prepare_worker(self.state)
        command = [
            "docker",
            "compose",
            "--env-file",
            str(self.state / "compose.env"),
            "--project-name",
            self.config["project"],
            "-f",
            str(HERE / "compose.yaml"),
            *arguments,
        ]
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
        )
        with (self.state / "compose.log").open("a", encoding="utf-8") as output:
            output.write(result.stdout + result.stderr)
        if result.returncode:
            if os.environ.get("CI") == "true":
                print(safe_compose_error(self.state, result.stderr), file=sys.stderr)
            raise RuntimeError("Compose failed; inspect private state/compose.log")
        return result.stdout

    def sql(self, database, sql, *, user="postgres"):
        return self.compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            input_text=sql,
        ).strip()

    def up(self):
        leaf = x509.load_pem_x509_certificate((self.state / "tls/server.pem").read_bytes())
        if leaf.not_valid_after_utc <= datetime.now(UTC):
            raise RuntimeError(
                "Local server certificate expired; renew explicitly, keep CA/issuer/data"
            )
        self.compose("up", "--build", "--detach", "--wait", "--wait-timeout", "360")
        self.ready()

    def ready(self):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(
                context=ssl.create_default_context(cafile=self.state / "tls/ca.pem")
            ),
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                with opener.open(self.origin + "/health/ready", timeout=3) as response:
                    assert response.status == 200
                with opener.open(
                    self.origin + "/realms/calorie-dev/.well-known/openid-configuration", timeout=3
                ) as response:
                    assert json.load(response)["issuer"] == self.origin + "/realms/calorie-dev"
                return
            except (urllib.error.URLError, OSError, AssertionError):
                time.sleep(2)
        raise RuntimeError("HTTPS API/issuer readiness failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("init", "up", "verify", "status", "down", "renew-tls", "worker-status")
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--host", help="Local IPv4; use the host LAN address for emulator access")
    parser.add_argument("--port", type=int)
    parser.add_argument("--project")
    args = parser.parse_args()
    state = args.state.resolve()
    try:
        if args.action == "init" or (args.action == "up" and not state.exists()):
            project = args.project or "calorie-integration"
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,50}", project):
                raise ValueError("Invalid Compose project name")
            existing = subprocess.run(
                [
                    "docker",
                    "volume",
                    "ls",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{.Name}}",
                ],
                capture_output=True,
                text=True,
            )
            if existing.returncode or existing.stdout.strip():
                raise RuntimeError(
                    "Docker unavailable or project volumes exist; preserve original state"
                )
            initialize(
                state, args.host or "127.0.0.1", 18443 if args.port is None else args.port, project
            )
        stack = Stack(state)
        if args.host is not None and host_address(args.host) != stack.config["host"]:
            raise ValueError(
                "Existing issuer is immutable; use its host or a separate new environment"
            )
        if args.port is not None and args.port != stack.config["port"]:
            raise ValueError("Existing issuer port cannot change implicitly")
        if args.project is not None and args.project != stack.config["project"]:
            raise ValueError("Existing volume project cannot change implicitly")
        if args.action == "up":
            stack.up()
        elif args.action == "down":
            stack.compose("down")  # Never --volumes: data survive down/up.
        elif args.action == "status":
            print(stack.compose("ps"))
        elif args.action == "worker-status":
            print(
                stack.compose(
                    "exec",
                    "-T",
                    "retention",
                    ".venv/bin/python",
                    "/opt/retention/worker.py",
                    "status",
                )
            )
        elif args.action == "verify":
            from verify import verify

            verify(stack)
        elif args.action == "renew-tls":
            stack.compose("stop", "gateway")
            renew_certificate(state / "tls", stack.config["host"])
            stack.compose("up", "--detach", "--no-deps", "--force-recreate", "gateway")
            stack.ready()
        print(f"{args.action}: OK | {stack.origin} | issuer={stack.origin}/realms/calorie-dev")
    except Exception as error:
        # Do not expose subprocess buffers, env files, passwords or token responses.
        if state.exists():
            private_write(state / "operation-error.log", traceback.format_exc())
        print(
            f"Integration operation failed: {type(error).__name__}; inspect private state/logs",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
