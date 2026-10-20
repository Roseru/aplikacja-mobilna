"""Read-only integration monitoring; private measurements, neutral GitHub incidents."""

import argparse
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import time
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY = "Roseru/aplikacja-mobilna"
CHECKS = (
    "api",
    "keycloak",
    "postgres",
    "retention",
    "motivation",
    "lifecycle",
    "finalizer",
    "disk",
    "tls",
    "backup",
    "local_backup",
    "startup",
    "ai",
)


def utc():
    return datetime.now(UTC).isoformat()


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def age(timestamp):
    return (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds()


def offsite_reading(path):
    try:
        receipt = json.loads(Path(path).read_text())
        recent = 0 <= age(receipt["verified_at"]) <= 86400
        if "archive_captured_at" in receipt:
            recent = recent and 0 <= age(receipt["archive_captured_at"]) <= 86400
        return {"state": "ok" if recent and receipt["offsite_verified"] is True else "failed"}
    except Exception:
        return {"state": "failed"}


def command(arguments, *, status=False):
    result = subprocess.run(
        arguments, capture_output=True, text=True, timeout=15, **console_options()
    )
    if result.returncode and not (status and result.returncode == 1):
        raise RuntimeError("probe unavailable")
    return result.stdout


def console_options():
    # pythonw has no console to inherit; its console children need this flag too.
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class LocalHTTPS(http.client.HTTPSConnection):
    """Connect locally while retaining the configured issuer's TLS identity."""

    def connect(self):
        raw = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def https(config, state, path):
    origin = urlsplit(config["origin"])
    if origin.scheme != "https" or origin.hostname != config["host"]:
        raise ValueError("invalid configured origin")
    context = ssl.create_default_context(cafile=str(state / "tls/ca.pem"))
    with closing(
        LocalHTTPS(origin.hostname, origin.port, timeout=5, context=context)
    ) as connection:
        connection.connect()
        expires = ssl.cert_time_to_seconds(connection.sock.getpeercert()["notAfter"])
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536 or response.status != 200:
            raise ValueError("readiness unavailable")
        return json.loads(body), (expires - time.time()) / 86400


def worker_ok(status, *, disabled=False):
    try:
        if disabled:
            return (
                status["state"] == "disabled"
                and status["metrics"]["ready"] is False
                and 0 <= age(status["last_attempt"]) <= 180
            )
        return (
            status["state"] in {"ok", "pending", "running"}
            and 0 <= age(status["last_success"]) <= 180
        )
    except (KeyError, TypeError, ValueError):
        return False


def operation_reading(path, *, backup=False):
    if not path:
        return {"state": "not_configured"}
    try:
        receipt = json.loads(Path(path).read_text(encoding="utf-8"))
        running = backup and receipt.get("result") == "RUNNING"
        current = receipt["last_good"] if running else receipt
        valid = current["result"] == "PASS"
        if backup:
            valid = (
                valid
                and 0 <= age(current["verified_at"]) <= 86400
                and current.get("archive_integrity") is True
                and current.get("restore_rehearsal") is True
                and current.get("services_resumed") is True
            )
        if running and valid and 0 <= age(receipt["started_at"]) <= 45 * 60:
            return {"state": "running"}
        if running:
            return {"state": "failed"}
        return {"state": "ok" if valid else "failed"}
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "failed"}


def sample(state, settings):
    config = json.loads((state / "config.json").read_text())
    project = config["project"]
    docker = settings.get("docker", "docker")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", project):
        raise ValueError("invalid project")
    readings = {key: {"state": "failed"} for key in CHECKS}
    for key, path in (
        ("api", "/health/ready"),
        ("keycloak", "/realms/calorie-dev/.well-known/openid-configuration"),
    ):
        try:
            body, days = https(config, state, path)
            if key == "keycloak" and body.get("issuer") != config["origin"] + "/realms/calorie-dev":
                raise ValueError("issuer mismatch")
            readings[key] = {"state": "ok"}
            readings["tls"] = {
                "state": "ok" if days >= 14 else "failed",
                "days_left": round(days, 2),
            }
        except Exception:
            pass  # Never publish an exception, response body or configured address.
    for key, service in (
        ("postgres", "postgres"),
        ("retention", "retention"),
        ("motivation", "motivation"),
        ("lifecycle", "nemesis-lifecycle"),
        ("finalizer", "nemesis-finalizer"),
    ):
        container = project + "-" + service + "-1"
        try:
            info = json.loads(
                command(
                    [
                        docker,
                        "inspect",
                        "--format",
                        "{{json .State}}",
                        container,
                    ]
                )
            )
            # Container naming alone is insufficient to authorize probing a service.
            owner = command(
                [
                    docker,
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "com.docker.compose.project"}}',
                    container,
                ]
            ).strip()
            if owner != project or not info["Running"] or info["Paused"]:
                continue
            healthy = info.get("Health", {}).get("Status") == "healthy"
            if key == "finalizer" and settings.get("finalizer_disabled") is True:
                status = json.loads(
                    command(
                        [
                            docker,
                            "exec",
                            container,
                            ".venv/bin/python",
                            "-I",
                            "/opt/e8/e8_worker.py",
                            "finalizer",
                            "status",
                        ],
                        status=True,
                    )
                )
                healthy = worker_ok(status, disabled=True)
                readings[key] = {"state": "expected_disabled" if healthy else "failed"}
            else:
                readings[key] = {"state": "ok" if healthy else "failed"}
        except Exception:
            pass
    disk = shutil.disk_usage(state)
    readings["disk"] = {
        "state": "ok" if disk.free >= 2 * 1024**3 and disk.free / disk.total >= 0.1 else "failed",
        "free_percent": round(100 * disk.free / disk.total, 2),
    }
    # Missing external prerequisites remain explicit, never a green backup/AI claim.
    readings["backup"] = {"state": "not_configured"}
    if settings.get("backup_receipt"):
        readings["backup"] = offsite_reading(settings["backup_receipt"])
    readings["ai"] = {"state": "not_deployed"}
    readings["local_backup"] = operation_reading(settings.get("local_backup_receipt"), backup=True)
    readings["startup"] = operation_reading(settings.get("startup_receipt"))
    return {"observed_at": utc(), "checks": readings}


class GitHub:
    def __init__(self, checkout, git="git"):
        env = dict(os.environ, GCM_INTERACTIVE="Never", GIT_TERMINAL_PROMPT="0")
        result = subprocess.run(
            [git, "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            cwd=checkout,
            env=env,
            timeout=20,
            **console_options(),
        )
        self.token = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        ).get("password")
        if result.returncode or not self.token:
            raise RuntimeError("notification credential unavailable")

    def request(self, path, method="GET", data=None):
        request = urllib.request.Request(
            "https://api.github.com/repos/" + REPOSITORY + "/" + path,
            data=None if data is None else json.dumps(data).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "O3-integration-monitor",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def incident(self, key, number, failed, test=False):
        title = "[O3 monitoring" + (" test" if test else "") + "] " + key
        marker = "<!-- o3-monitor:" + ("test:" if test else "live:") + key + " -->"
        # Reconcile an uncertain POST or lost local receipt before creating another issue.
        if not number:
            for page in range(1, 21):
                issues = self.request(f"issues?state=all&per_page=100&page={page}")
                matches = [
                    issue
                    for issue in issues
                    if issue["title"] == title
                    and marker in (issue.get("body") or "")
                    and "pull_request" not in issue
                ]
                if matches:
                    number = max(issue["number"] for issue in matches)
                    break
                if len(issues) < 100:
                    break
            else:
                raise RuntimeError("incident reconciliation incomplete")
        body = marker + "\n\nŚrodowisko: lokalna integracja.\nPomiar UTC: " + utc()
        body += "\nStan: " + ("awaria" if failed else "przywrócono działanie")
        if test:
            body += "\nKontrolowana próba monitoringu O3."
        desired = "open" if failed else "closed"
        payload = {"title": title, "body": body, "state": desired}
        if number:
            self.request("issues/" + str(number), "PATCH", payload)
        elif failed:
            number = self.request("issues", "POST", payload)["number"]
        else:
            return None
        verified = self.request("issues/" + str(number))
        if verified["state"] != desired or marker not in (verified["body"] or ""):
            raise RuntimeError("incident delivery unconfirmed")
        return number


def deliver(measurement, ledger, sender, *, threshold=2, test=False):
    for key in CHECKS:
        current = ledger.setdefault(key, {"failures": 0, "active": False, "issue": None})
        state = measurement["checks"][key]["state"]
        if state in {"not_configured", "not_deployed", "running"}:
            continue
        failed = state == "failed"
        current["failures"] = current["failures"] + 1 if failed else 0
        if failed and current["failures"] < threshold:
            continue
        if failed == current["active"]:
            continue
        current["issue"] = sender.incident(key, current["issue"], failed, test)
        # Update active only after remote read-back; a failed delivery is retried.
        current["active"] = failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("once", "serve"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()
    settings = json.loads(args.settings.read_text(encoding="utf-8-sig"))
    directory = args.settings.parent
    ledger_path = directory / "incidents.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    while True:
        try:
            measurement = sample(args.state, settings)
            write(directory / "measurements.json", measurement)
            if args.notify:
                deliver(
                    measurement, ledger, GitHub(settings["checkout"], settings.get("git", "git"))
                )
                write(ledger_path, ledger)
            write(
                directory / "heartbeat.json",
                {"observed_at": utc(), "delivery": "ok" if args.notify else "disabled"},
            )
            if args.action == "once":
                print(json.dumps(measurement))
                return 0
        except Exception:
            write(directory / "heartbeat.json", {"observed_at": utc(), "delivery": "failed"})
            if args.action == "once":
                print('{"monitor":"failed"}')
                return 1
        time.sleep(60)


if __name__ == "__main__":
    raise SystemExit(main())
