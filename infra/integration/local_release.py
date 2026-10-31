"""Operate one explicitly bound existing local Docker installation; never initialize it."""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# -I ignores ambient PYTHONPATH; import only these reviewed sibling tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup import capture, digest, execute, private_directory  # noqa: E402
from e8_worker import aggregate, healthy  # noqa: E402
from run import HERE, ROOT, private_write  # noqa: E402
from run_e8 import E8Stack  # noqa: E402

SERVICES = frozenset(
    {
        "postgres",
        "api",
        "keycloak",
        "gateway",
        "retention",
        "ai-worker",
        "mailpit",
        "motivation",
        "nemesis-lifecycle",
        "nemesis-finalizer",
    }
)
ONE_SHOTS = {"migrate", "storage-init", "e8-storage-init", "e8-provision"}
E8 = {
    "motivation": "motivation",
    "nemesis-lifecycle": "lifecycle",
    "nemesis-finalizer": "finalizer",
}
HEX = re.compile(r"[0-9a-f]{64}")
ARCHIVE_LABEL = "pl.roseru.calorie.local-archive-owner"
PROFILE_KEYS = {
    "format",
    "project",
    "state",
    "origin",
    "docker_endpoint",
    "engine_id",
    "source_commit",
    "compose_files",
    "files",
    "containers",
    "volumes",
    "ai_provider",
}
SOURCE_FILES = (
    "local_release.py",
    "run.py",
    "backup.py",
    "run_e8.py",
    "e8_worker.py",
    "worker.py",
    "Caddyfile",
)
LAUNCH_FILES = (
    "START.ps1",
    "STATUS.ps1",
    "STOP.ps1",
    "BACKUP.ps1",
    "Invoke-LocalRelease.ps1",
    "README.txt",
)


def reject(message):
    raise ValueError(message)


def stored_worker_metrics(task, payload):
    """Validate the persisted DTO; motivation's raw CLI status was already consumed."""
    if task != "motivation":
        return aggregate(task, payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("backlog"), dict):
        reject("Invalid stored metrics")
    result = {}
    for field in ("owners_handled", "dates_processed"):
        value = payload[field]
        if type(value) is not int or value < 0:
            reject("Invalid stored aggregate")
        result[field] = value
    result["backlog"] = {}
    for field in ("pending_backfill", "pending_materialization"):
        value = payload["backlog"][field]
        if type(value) is not int or value < 0:
            reject("Invalid stored backlog")
        result["backlog"][field] = value
    oldest = payload["backlog"]["oldest_matures_at"]
    if oldest is not None:
        oldest = datetime.fromisoformat(oldest).isoformat()
    result["backlog"]["oldest_matures_at"] = oldest
    return result


def ordinary(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute():
        reject("Absolute path required")
    if str(path).startswith(("\\\\?\\", "\\\\.\\")):
        reject("Device namespace refused")
    # Windows spelling must not silently alias another file (ADS/trailing dot/space).
    if any(part.endswith((" ", ".")) or ":" in part for part in path.parts[1:]):
        reject("Ambiguous path spelling")
    for parent in (path, *path.parents):
        if parent.is_symlink() or (
            parent.exists() and getattr(parent.stat(), "st_file_attributes", 0) & 0x400
        ):
            reject("Path redirection refused")
    if directory and not path.is_dir() or not directory and not path.is_file():
        reject("Required ordinary path missing")
    return path.resolve()


def new_private_target(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(("\\\\?\\", "\\\\.\\")):
        reject("Absolute new private destination required")
    if any(part.endswith((" ", ".")) or ":" in part for part in path.parts[1:]):
        reject("Ambiguous private destination")
    for parent in (path, *path.parents):
        if parent.is_symlink() or (
            parent.exists() and getattr(parent.stat(), "st_file_attributes", 0) & 0x400
        ):
            reject("Private destination redirection refused")
    target = path.resolve()
    if (
        target.exists()
        or target.is_relative_to(ROOT)
        or any((parent / ".git").exists() for parent in target.parents)
    ):
        reject("Destination must be new and outside the source checkout")
    return target


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            reject("Duplicate configuration key")
        result[key] = value
    return result


def read_json(path):
    raw = ordinary(path).read_bytes()
    if len(raw) > 128 * 1024:
        reject("Operational configuration too large")
    return json.loads(raw, object_pairs_hook=pairs)


@contextmanager
def operation(profile):
    path = ordinary(profile).with_suffix(".operation.lock")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, str(os.getpid()).encode())
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def pin(path):
    value = ordinary(path)
    return {"path": str(value), "sha256": digest(value)}


def transport_environment():
    return {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DOCKER_CONTEXT",
            "DOCKER_HOST",
            "DOCKER_TLS",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }


def local_endpoint(value):
    if not isinstance(value, str) or not value.startswith(("npipe://", "unix://")):
        reject("Local Docker socket required")
    return value


def docker(endpoint, *args):
    result = subprocess.run(
        ["docker", "--host", local_endpoint(endpoint), *args],
        env=transport_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    if result.returncode:
        raise RuntimeError("Qualified Docker operation failed")
    return result.stdout.strip()


def configuration_hash(value):
    bound = {
        "config": value["Config"],
        "host": value["HostConfig"],
        "mounts": value.get("Mounts", []),
        "networks": sorted(value.get("NetworkSettings", {}).get("Networks", {})),
    }
    return hashlib.sha256(
        json.dumps(bound, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def inspect_project(endpoint, project):
    identifiers = docker(
        endpoint,
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "label=com.docker.compose.project=" + project,
        "--format",
        "{{.ID}}",
    ).split()
    if not identifiers:
        reject("Bound installation has no existing containers")
    values = json.loads(docker(endpoint, "inspect", *identifiers))
    result = {}
    for value in values:
        labels = value.get("Config", {}).get("Labels", {})
        service = labels.get("com.docker.compose.service")
        if labels.get("com.docker.compose.project") != project:
            reject("Container project ownership mismatch")
        if service in ONE_SHOTS and not value.get("State", {}).get("Running"):
            continue
        if service not in SERVICES or service in result:
            reject("Unexpected or duplicate project service")
        result[service] = value
    if set(result) != SERVICES:
        reject("Complete existing installation, including E8, required")
    return result


def check_runtime(values, provider="mock"):
    volumes = set()
    for value in values.values():
        for ports in (value.get("HostConfig", {}).get("PortBindings") or {}).values():
            for port in ports or ():
                if port.get("HostIp") not in {"127.0.0.1", "::1"}:
                    reject("Published port is not loopback-only")
        for mount in value.get("Mounts", []):
            if mount["Type"] == "volume":
                volumes.add(mount["Name"])
    if values["keycloak"]["Config"].get("Cmd") != ["start", "--optimized"]:
        reject("Keycloak must start without realm import")
    for service in ("api", "ai-worker"):
        environment = dict(
            value.split("=", 1)
            for value in values[service]["Config"].get("Env", [])
            if "=" in value
        )
        if environment.get("AI_PROVIDER") != provider:
            reject("Provider differs from the explicitly bound configuration")
        if provider == "mock" and environment.get("GEMINI_API_KEY"):
            reject("MOCK installation must not have a live key")
        if provider == "gemini" and not all(
            environment.get(name)
            for name in (
                "GEMINI_API_KEY",
                "AI_PROJECT_ID",
                "AI_ENVIRONMENT_ID",
                "AI_MODEL",
                "AI_LIVE_CONFIRMATION",
            )
        ):
            reject("Live provider prerequisites missing; use existing E7 configuration procedure")
    return volumes


def photo_volume(values):
    selected = []
    for service in ("api", "ai-worker"):
        mounts = [
            mount
            for mount in values[service].get("Mounts", [])
            if mount["Destination"] == "/photos" and mount["Type"] == "volume"
        ]
        if len(mounts) != 1:
            reject("Shared durable photo volume required")
        selected.append(mounts[0]["Name"])
    if selected[0] != selected[1]:
        reject("API and AI worker photo volume differ")
    return selected[0]


def owned_volumes(endpoint, names, project):
    values = json.loads(docker(endpoint, "volume", "inspect", *sorted(names)))
    if {value["Name"] for value in values} != set(names) or any(
        value.get("Labels", {}).get("com.docker.compose.project") != project for value in values
    ):
        reject("Volume project ownership mismatch")


def validate_profile(value):
    if not isinstance(value, dict) or set(value) != PROFILE_KEYS or value["format"] != 1:
        reject("Unsupported operational configuration")
    if not isinstance(value["project"], str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{0,50}", value["project"]
    ):
        reject("Invalid project")
    local_endpoint(value["docker_endpoint"])
    if value["ai_provider"] not in {"mock", "gemini"}:
        reject("Explicit AI provider required")
    if (
        not isinstance(value["engine_id"], str)
        or not value["engine_id"]
        or len(value["engine_id"]) > 200
    ):
        reject("Engine identity required")
    if not isinstance(value["source_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40}", value["source_commit"]
    ):
        reject("Exact source commit required")
    url = urllib.parse.urlsplit(value["origin"])
    if (
        url.scheme != "https"
        or url.hostname != "127.0.0.1"
        or url.port is None
        or url.username
        or url.password
        or url.path
        or url.query
        or url.fragment
    ):
        reject("Exact loopback HTTPS origin required")
    if (
        set(value["containers"]) != SERVICES
        or not isinstance(value["volumes"], list)
        or not value["volumes"]
    ):
        reject("Complete services and named volumes required")
    if not 3 <= len(value["compose_files"]) <= 8 or not 1 <= len(value["files"]) <= 256:
        reject("Complete bounded Compose chain and file pins required")
    paths = set()
    for item in value["compose_files"] + value["files"]:
        if (
            set(item) != {"path", "sha256"}
            or not isinstance(item["sha256"], str)
            or not HEX.fullmatch(item["sha256"])
        ):
            reject("Invalid file pin")
        path = ordinary(item["path"])
        if path in paths:
            reject("Repeated pinned file")
        paths.add(path)
        if digest(path) != item["sha256"]:
            reject("Pinned operational file changed")
    for item in value["containers"].values():
        if set(item) != {"id", "image", "configuration_sha256"} or not HEX.fullmatch(item["id"]):
            reject("Exact existing container identity required")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", item["image"]) or not HEX.fullmatch(
            item["configuration_sha256"]
        ):
            reject("Exact image and container configuration required")
    ordinary(value["state"], directory=True)
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ReleaseStack(E8Stack):
    def __init__(self, profile):
        self.profile_path = ordinary(profile)
        self.profile = validate_profile(read_json(self.profile_path))
        self.profile_sha256 = digest(self.profile_path)
        value = self.profile
        super().__init__(
            Path(value["state"]),
            compose_files=[Path(item["path"]) for item in value["compose_files"]],
            docker_endpoint=value["docker_endpoint"],
        )
        if self.config["project"] != value["project"] or self.origin != value["origin"]:
            reject("Existing state binding changed")
        required = {
            self.state / "config.json",
            self.state / "compose.env",
            self.state / "worker.env",
            self.state / "tls" / "ca.pem",
            *(HERE / name for name in SOURCE_FILES),
        }
        pinned = {Path(item["path"]) for item in value["files"]}
        if not required <= pinned:
            reject("Required runtime/source/CA files are not pinned")
        if (
            HERE / "compose.yaml" != self.compose_files[0]
            or HERE / "compose.e8.yaml" not in self.compose_files
        ):
            reject("Base and E8 Compose chain required")

    def e8(self, *args):
        # E8 is already in the same qualified chain, including binary backup calls.
        return self.compose(*args)

    def owned(self):
        value = self.profile
        if digest(self.profile_path) != self.profile_sha256:
            reject("Operational profile changed during this operation")
        validate_profile(value)
        if docker(self.docker_endpoint, "info", "--format", "{{.ID}}") != value["engine_id"]:
            reject("Docker engine changed")
        if docker(
            self.docker_endpoint,
            "ps",
            "--quiet",
            "--filter",
            "label=" + ARCHIVE_LABEL + "=" + self.profile_sha256,
        ):
            reject("Previous archive helper still has physical IO")
        observed = inspect_project(self.docker_endpoint, value["project"])
        for service, expected in value["containers"].items():
            actual = observed[service]
            if (
                actual["Id"] != expected["id"]
                or actual["Image"] != expected["image"]
                or configuration_hash(actual) != expected["configuration_sha256"]
            ):
                reject("Bound container identity, image or configuration changed")
        names = check_runtime(observed, value["ai_provider"])
        if names != set(value["volumes"]):
            reject("Bound volume set changed")
        owned_volumes(self.docker_endpoint, names, value["project"])
        return observed

    def assert_closed(self, *, database=False):
        observed = self.owned()
        selected = SERVICES if database else SERVICES - {"postgres"}
        if any(
            observed[service]["State"].get("Running")
            or observed[service]["State"].get("Pid", 0) != 0
            for service in selected
        ):
            reject("Writer processes are not stopped")

    def close_writers(self):
        self.owned()
        self.compose("stop", "gateway")
        self.compose("stop", *sorted(SERVICES - {"gateway", "postgres"}))
        self.assert_closed()

    def https_ready(self):
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            NoRedirect(),
            urllib.request.HTTPSHandler(
                context=ssl.create_default_context(cafile=self.state / "tls/ca.pem")
            ),
        )
        try:
            with opener.open(self.origin + "/health/ready", timeout=5) as response:
                if response.status != 200:
                    return False
            with opener.open(
                self.origin + "/realms/calorie-dev/.well-known/openid-configuration", timeout=5
            ) as response:
                return (
                    response.status == 200
                    and json.load(response)["issuer"] == self.origin + "/realms/calorie-dev"
                )
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            return False

    def worker_status(self, service, state):
        try:
            result = json.loads(
                self.compose(
                    "exec",
                    "-T",
                    service,
                    ".venv/bin/python",
                    "-I",
                    "-c",
                    "from pathlib import Path; print(Path('/worker/status.json').read_text())",
                )
            )
            metrics = (
                stored_worker_metrics(E8[service], result["metrics"])
                if "metrics" in result
                else None
            )
            success = (
                datetime.fromisoformat(result["last_success"].replace("Z", "+00:00"))
                if result.get("last_success") is not None
                else None
            )
            started = datetime.fromisoformat(state["StartedAt"].replace("Z", "+00:00"))
            return {
                "state": result["state"]
                if result["state"]
                in {"running", "ok", "pending", "disabled", "timeout", "stopped", "failed"}
                else "unknown",
                "fresh_success": healthy(result) and success is not None and success >= started,
                "last_success": success.isoformat() if success is not None else None,
                "metrics": metrics,
            }
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError):
            return {"state": "unavailable", "fresh_success": False}

    def wait_workers(self, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            observed = self.owned()
            if all(
                self.worker_status(name, observed[name]["State"])["fresh_success"] for name in E8
            ):
                return
            time.sleep(1)
        reject("E8 successful cycles after process start not observed")

    def status(self):
        observed = self.owned()
        services = {}
        for service, value in observed.items():
            state = value["State"]
            item = {
                "running": state["Running"],
                "health": state.get("Health", {}).get("Status", "not_configured"),
            }
            if service in E8 and state["Running"]:
                item["worker"] = self.worker_status(service, state)
            services[service] = item
        return {
            "scope": "LOCAL_BOUND_INSTALLATION",
            "https_api_issuer_ready": self.https_ready(),
            "services": services,
        }

    def start(self):
        observed = self.owned()
        if all(value["State"]["Running"] for value in observed.values()):
            current = self.status()
            if current["https_api_issuer_ready"] and all(
                current["services"][name].get("worker", {}).get("fresh_success") for name in E8
            ):
                return current
        # Hold ingress while restarting existing processes. Never create/build/import/migrate.
        self.compose("stop", "gateway")
        try:
            for services in (
                ("postgres",),
                ("mailpit", "keycloak"),
                (
                    "api",
                    "retention",
                    "ai-worker",
                    "motivation",
                    "nemesis-lifecycle",
                    "nemesis-finalizer",
                ),
            ):
                self.owned()
                self.compose("start", "--wait", "--wait-timeout", "180", *services)
            self.wait_workers()
            self.owned()
            self.compose("start", "--wait", "--wait-timeout", "180", "gateway")
            if not self.https_ready():
                reject("HTTPS API or issuer is not ready")
            report = self.status()
            if any(
                not report["services"][service].get("worker", {}).get("fresh_success")
                for service in E8
            ):
                reject("E8 successful cycles not observed")
            return report
        except Exception:
            self.close_writers()
            raise

    def stop(self):
        self.close_writers()
        self.compose("stop", "postgres")
        self.assert_closed(database=True)
        return {"scope": "LOCAL_BOUND_INSTALLATION", "result": "STOPPED", "data_removed": False}

    def archive_volume(self, directory, volume, mount, source, output):
        """A pinned read-only helper has no network or privileged service environment."""
        self.assert_closed()
        if volume not in self.profile["volumes"] or mount not in {"/catalog", "/photos"}:
            reject("Only bound archive volumes are permitted")
        image = self.profile["containers"]["api"]["image"]
        if docker(self.docker_endpoint, "image", "inspect", "--format", "{{.Id}}", image) != image:
            reject("Pinned archive helper image unavailable")
        name = self.profile["project"] + "-archive-" + secrets.token_hex(12)
        command = [
            "docker",
            "--host",
            self.docker_endpoint,
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            ARCHIVE_LABEL + "=" + self.profile_sha256,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user=10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=256m",
            "--pids-limit=64",
            "--mount",
            "type=volume,source=" + volume + ",target=" + mount + ",readonly",
            "--workdir=/app",
            "--entrypoint=/app/.venv/bin/python",
            image,
            "-I",
            "-B",
            "-c",
            source,
        ]
        try:
            execute(directory, command, output_path=output, environment=self.compose_environment())
        except Exception:
            # Killing the Docker CLI on timeout is not proof that its container died.
            # Inspect exact random name/image/owner before stopping only this helper.
            try:
                observed = json.loads(docker(self.docker_endpoint, "inspect", name))[0]
            except RuntimeError:
                raise
            if (
                observed.get("Name") != "/" + name
                or observed.get("Image") != image
                or observed.get("Config", {}).get("Labels", {}).get(ARCHIVE_LABEL)
                != self.profile_sha256
            ):
                reject("Archive helper cleanup ownership mismatch")
            if observed.get("State", {}).get("Running") or observed.get("State", {}).get("Pid"):
                docker(self.docker_endpoint, "stop", "--time", "5", name)
            raise

    def backup(self, destination):
        observed = self.owned()
        destination = new_private_target(destination)
        if destination.is_relative_to(self.state) or self.state.is_relative_to(destination):
            reject("Backup and live state must be disjoint")
        files = {"release/runtime.json": self.profile_path}
        for index, item in enumerate(self.profile["compose_files"]):
            files[f"release/compose-{index:02d}.yaml"] = Path(item["path"])
        for name in SOURCE_FILES:
            files["release/source/" + name] = HERE / name
        # Stopping all services except PG includes MOCK, SMTP and every optional writer.
        result = capture(
            self.state,
            destination,
            stack=self,
            writers=tuple(sorted(SERVICES - {"gateway", "postgres"})),
            verify_closed=self.assert_closed,
            extra_config=files,
            photo_volume=photo_volume(observed),
            volume_archiver=self.archive_volume,
        )
        return {
            **result,
            "scope": "LOCAL_PAIRED_BACKUP",
            "traffic_reopened": False,
            "manifest_sha256": digest(destination / "manifest.json"),
        }


def bind(args):
    """One-time operator binding after acceptance; reads Docker, writes only NEW private config."""
    destination = new_private_target(args.profile)
    if destination.parent.exists():
        reject("Binding requires a new private directory")
    endpoint = local_endpoint(args.docker_endpoint)
    state = ordinary(args.state, directory=True)
    config = read_json(state / "config.json")
    if config["project"] != args.project:
        reject("Explicit project differs from existing state")
    if docker(endpoint, "info", "--format", "{{.ID}}") != args.engine_id:
        reject("Explicit engine identity differs")
    values = inspect_project(endpoint, args.project)
    volumes = check_runtime(values, args.provider)
    owned_volumes(endpoint, volumes, args.project)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if changed:
        reject("Commit the reviewed source before operational binding")
    compose_files = [pin(path) for path in args.compose_file]
    compose_paths = {Path(item["path"]) for item in compose_files}
    files = {
        state / "config.json",
        state / "compose.env",
        *(state.glob("*.env")),
        *(HERE / name for name in SOURCE_FILES),
    }
    files.update(path for path in (state / "tls").iterdir() if path.is_file())
    # Compose resolves Windows host paths; Docker inspect may expose VM-internal paths.
    probe = E8Stack(
        state,
        compose_files=[Path(item["path"]) for item in compose_files],
        docker_endpoint=endpoint,
    )
    metadata = subprocess.run(
        probe.compose_command("config", "--format", "json"),
        env=probe.compose_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=30,
    )
    expanded = json.loads(metadata.stdout)
    for service in expanded["services"].values():
        for mount in service.get("volumes", []):
            if mount.get("type") == "bind" and Path(mount["source"]).is_file():
                files.add(Path(mount["source"]))
    files.update(HERE / "local_release" / name for name in LAUNCH_FILES)
    value = {
        "format": 1,
        "project": args.project,
        "state": str(state),
        "origin": config["origin"],
        "docker_endpoint": endpoint,
        "engine_id": args.engine_id,
        "source_commit": commit,
        "ai_provider": args.provider,
        "compose_files": compose_files,
        "files": [pin(path) for path in sorted(files - compose_paths)],
        "containers": {
            service: {
                "id": item["Id"],
                "image": item["Image"],
                "configuration_sha256": configuration_hash(item),
            }
            for service, item in sorted(values.items())
        },
        "volumes": sorted(volumes),
    }
    validate_profile(value)
    destination = new_private_target(destination)
    if destination.parent.exists():
        reject("Binding requires a new private directory")
    private_directory(destination.parent)
    private_write(destination, json.dumps(value, indent=2))
    for name in LAUNCH_FILES:
        shutil.copy2(HERE / "local_release" / name, destination.parent / name)
    private_write(
        destination.parent / "launcher.private.json",
        json.dumps(
            {
                "python": sys.executable,
                "entrypoint": str(Path(__file__).resolve()),
            },
            indent=2,
        ),
    )
    ReleaseStack(destination).owned()
    return {
        "result": "BOUND_EXISTING_LOCAL_INSTALLATION",
        "runtime_mutated": False,
        "profile_sha256": digest(destination),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "status", "stop", "backup", "bind"))
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--docker-endpoint")
    parser.add_argument("--engine-id")
    parser.add_argument("--compose-file", type=Path, action="append", default=[])
    parser.add_argument("--provider", choices=("mock", "gemini"), default="mock")
    args = parser.parse_args(argv)
    try:
        if args.action == "bind":
            if not all(
                (args.state, args.project, args.docker_endpoint, args.engine_id, args.compose_file)
            ):
                reject("Explicit existing installation binding inputs required")
            result = bind(args)
        else:
            stack = ReleaseStack(args.profile)
            if args.action == "status":
                result = stack.status()
            else:
                with operation(args.profile):
                    if args.action == "backup":
                        if args.backup is None or not args.backup.is_absolute():
                            reject("Absolute new private backup destination required")
                        result = stack.backup(args.backup)
                    else:
                        result = getattr(stack, args.action)()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        # Do not expose env, SQL, tokens, private paths or process output.
        print(
            json.dumps(
                {
                    "result": "REFUSED_OR_FAILED",
                    "action": args.action,
                    "error_kind": type(error).__name__,
                    "runtime_success": False,
                }
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
