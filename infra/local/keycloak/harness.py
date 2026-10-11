"""Isolated real Keycloak runtime. Credentials are ephemeral and never printed."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_STATE = ROOT / ".tools" / "e3-keycloak"


def acquire(destination):
    lock = json.loads((HERE / "distribution.lock.json").read_text())
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "keycloak.zip"
    if not archive.exists():
        with (
            urllib.request.urlopen(lock["url"], timeout=60) as source,
            archive.open("wb") as target,
        ):
            shutil.copyfileobj(source, target)
    with archive.open("rb") as downloaded:
        digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
    if digest != lock["sha256"]:
        raise RuntimeError("Keycloak distribution checksum mismatch")
    home = destination / f"keycloak-{lock['version']}"
    if not home.exists():
        with zipfile.ZipFile(archive) as source:
            source.extractall(destination)
        if os.name != "nt":
            (home / "bin" / "kc.sh").chmod(0o755)
    return home


def prepare(home, state):
    if state.exists():
        raise RuntimeError("State already exists; choose a fresh isolated --state directory")
    state.mkdir(parents=True, mode=0o700)
    runtime = state / "runtime"
    shutil.copytree(home, runtime)
    realm = json.loads((HERE / "realm.json").read_text())
    users = []
    credentials = {}
    for name in ("a", "b", "delete_a"):
        username, password = f"e3-{name}", secrets.token_urlsafe(32)
        credentials[name] = {"username": username, "password": password}
        users.append(
            {
                "username": username,
                "enabled": True,
                "emailVerified": True,
                "firstName": "E3",
                "lastName": name.upper(),
                "email": f"{username}@invalid.example",
                "requiredActions": [],
                "credentials": [{"type": "password", "value": password, "temporary": False}],
                "clientRoles": {"calorie-api": ["user"]},
            }
        )
    admin_secret = secrets.token_urlsafe(48)
    denied_secret = secrets.token_urlsafe(48)
    for client_id, secret in (
        ("calorie-deletion-operator", admin_secret),
        ("calorie-deletion-denied", denied_secret),
    ):
        realm["clients"].append(
            {
                "clientId": client_id,
                "secret": secret,
                "enabled": True,
                "publicClient": False,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": True,
                "protocol": "openid-connect",
                "defaultClientScopes": ["basic", "roles"],
            }
        )
        users.append(
            {
                "username": "service-account-" + client_id,
                "enabled": True,
                "serviceAccountClientId": client_id,
                "clientRoles": {"realm-management": ["manage-users"]}
                if client_id == "calorie-deletion-operator"
                else {},
            }
        )
    realm["users"] = users
    imports = runtime / "data" / "import"
    imports.mkdir(parents=True, exist_ok=True)
    realm_path = imports / "calorie-dev.json"
    realm_path.write_text(json.dumps(realm), encoding="utf-8")
    realm_path.chmod(0o600)
    credentials_path = state / "credentials.json"
    credentials_path.write_text(json.dumps(credentials), encoding="utf-8")
    credentials_path.chmod(0o600)
    # These secrets are local harness state, never realm.json or test output.
    admin_path = state / "admin-secrets.json"
    admin_path.write_text(
        json.dumps(
            {
                "calorie-deletion-operator": admin_secret,
                "calorie-deletion-denied": denied_secret,
            }
        ),
        encoding="utf-8",
    )
    admin_path.chmod(0o600)
    return runtime, credentials_path


def start(home, state, java_home, port):
    runtime, credentials = prepare(home.resolve(), state.resolve())
    state = state.resolve()
    env = dict(os.environ, JAVA_HOME=str(java_home.resolve()))
    env["PATH"] = str(java_home.resolve() / "bin") + os.pathsep + env.get("PATH", "")
    command = [
        str(runtime / "bin" / ("kc.bat" if os.name == "nt" else "kc.sh")),
        "start-dev",
        "--http-host=127.0.0.1",
        f"--http-port={port}",
        f"--http-management-port={port + 1000}",
        f"--hostname=http://127.0.0.1:{port}",
        "--import-realm",
        "--health-enabled=true",
        "--http-access-log-enabled=false",
    ]
    kwargs = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with (state / "service.log").open("wb") as output:
        process = subprocess.Popen(
            command, env=env, stdout=output, stderr=subprocess.STDOUT, **kwargs
        )
    marker = {"pid": process.pid, "runtime": str(runtime), "port": port}
    (state / "process.json").write_text(json.dumps(marker))
    issuer = f"http://127.0.0.1:{port}/realms/calorie-dev"
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Keycloak exited before readiness; inspect local service.log")
        try:
            with urllib.request.urlopen(
                issuer + "/.well-known/openid-configuration", timeout=2
            ) as response:
                if response.status == 200:
                    return process, issuer, credentials
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    terminate(process)
    raise RuntimeError("Keycloak readiness timed out; inspect local service.log")


def terminate(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=30)


def stop(state):
    marker = json.loads((state / "process.json").read_text())
    pid, runtime = marker["pid"], marker["runtime"]
    # Verify the saved PID still belongs to this runtime before stopping a tree.
    if os.name == "nt":
        inspection = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    else:
        inspection = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True
        ).stdout
    if runtime not in inspection:
        raise RuntimeError("Saved PID no longer identifies the owned Keycloak runtime")
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=True)
    else:
        os.killpg(pid, signal.SIGTERM)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["download", "start", "stop", "test"])
    parser.add_argument("--home", type=Path)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--java-home", type=Path, default=Path(os.environ.get("JAVA_HOME", ".")))
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    if args.action == "download":
        print(acquire(args.home or ROOT / ".tools" / "keycloak-distribution"))
        return
    if args.action == "stop":
        stop(args.state.resolve())
        print("Owned Keycloak process stopped")
        return
    if args.home is None:
        parser.error("--home is required")
    process, issuer, credentials = start(args.home, args.state, args.java_home, args.port)
    if args.action == "start":
        print(f"Keycloak ready: {issuer}; credentials stored locally; PID {process.pid}")
        return
    try:
        env = dict(
            os.environ,
            E3_KEYCLOAK_ISSUER=issuer,
            E3_KEYCLOAK_CREDENTIALS=str(credentials),
        )
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "backend/tests/keycloak", "-q"],
            cwd=ROOT,
            env=env,
        )
        if result.returncode:
            raise SystemExit(result.returncode)
    finally:
        terminate(process)


if __name__ == "__main__":
    main()
