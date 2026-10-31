"""Restore an owned paired backup into a NEW isolated Docker target.

Materialization never publishes a port or starts API/AI. Traffic admission is a
separate, real provider fence, then old-token probes. The source is only observed;
this module never stops, restores, drops or migrates its databases.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from uuid import UUID, uuid4

from backup import (
    ARCHIVES,
    FINGERPRINTS,
    digest,
    execute,
    private_directory,
    restore_catalog,
    verify_archive,
)
from maintenance import lock
from monitor import console_options
from recovery_o2 import admin, wait_maintenance
from run import HERE, Stack, host_address, private_write
from verify import Probe, expect

FORMAT = "calorie-owned-docker-restore/v1"
LABEL = "calorie.owned-d2-target"
MIN_FENCE_SECONDS = 421
KC_VALIDATE = [
    "start",
    "--optimized",
    "--spi-connections-jpa--quarkus--migration-strategy=validate",
    "--spi-connections-jpa--quarkus--initialize-empty=false",
]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    private_write(Path(path), json.dumps(value, indent=2))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative(name):
    path = Path(name)
    require(
        isinstance(name, str)
        and name
        and "\\" not in name
        and ":" not in name
        and not name.startswith("/")
        and not PureWindowsPath(name).drive
        and not path.is_absolute()
        and all(
            part and part not in (".", "..") and part.rstrip(" .") == part
            for part in name.split("/")
        ),
        "Unsafe paired payload path",
    )
    return path


def unlinked(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists():
            info = part.lstat()
            require(
                not part.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Linked/reparse input refused",
            )
    return path


def pinned_archive(archive, expected):
    archive = unlinked(archive).resolve(strict=True)
    require(re.fullmatch(r"[0-9a-f]{64}", expected or ""), "Independent manifest SHA required")
    raw = unlinked(archive / "manifest.json").read_bytes()
    require(sha(raw) == expected, "Independent manifest pin differs")
    manifest = json.loads(raw)
    for name in manifest.get("files", {}):
        path = archive / relative(name)
        require(path.resolve().is_relative_to(archive), "Payload escapes archive")
        unlinked(path)
    checked = verify_archive(archive)
    require(checked == manifest, "Manifest changed during preflight")
    required = {
        "config/config.json",
        "config/credentials.json",
        "config/postgres.env",
        "config/api.env",
        "config/keycloak.env",
        "config/tls/ca.pem",
        "config/tls/server.pem",
        "config/tls/server.key",
    }
    require(ARCHIVES | required <= set(manifest["files"]), "Missing paired runtime configuration")
    return archive, raw, manifest


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, encoding="utf-8", timeout=30, **console_options()
    ).strip()


def empty_project(project):
    require(re.fullmatch(r"[a-z][a-z0-9-]{0,50}", project or ""), "Invalid target project")
    selector = "label=com.docker.compose.project=" + project
    for kind, args in (
        ("container", ["ps", "-aq"]),
        ("volume", ["volume", "ls", "-q"]),
        ("network", ["network", "ls", "-q"]),
    ):
        require(not docker(*args, "--filter", selector), "Existing target " + kind + " refused")
    for name in ("postgres", "keycloak", "api", "gateway", "retention", "catalog-init"):
        require(
            not docker("ps", "-aq", "--filter", "name=^/" + project + "-" + name + "-1$"),
            "Existing target container name refused",
        )
    existing = set(docker("volume", "ls", "-q").splitlines())
    require(
        not existing.intersection(
            project + "_" + n
            for n in ("postgres_data", "catalog_data", "worker_data", "photo_data")
        ),
        "Existing named target volume refused",
    )


def configuration(state, project, source, images, owner):
    """Only immutable existing images; no build, migrate, import or init-app."""
    require(
        set(images) == {"postgres", "keycloak", "backend", "gateway"}, "Exact image set required"
    )
    for key in ("postgres", "keycloak", "backend", "gateway"):
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", images.get(key, "")),
            "Immutable local image IDs required",
        )

    def p(name):
        return (state / name).as_posix()

    labels = {LABEL: owner}
    backend = {
        "image": images["backend"],
        "labels": labels,
        "read_only": True,
        "tmpfs": ["/tmp"],
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }
    services = {
        "postgres": {
            "image": images["postgres"],
            "labels": labels,
            "env_file": [p("postgres.env")],
            "volumes": ["postgres_data:/var/lib/postgresql/data"],
            "healthcheck": {
                "test": ["CMD-SHELL", "pg_isready -U postgres -d postgres"],
                "interval": "2s",
                "timeout": "3s",
                "retries": 60,
            },
        },
        "keycloak": {
            "image": images["keycloak"],
            "labels": labels,
            "env_file": [p("keycloak.env")],
            "command": KC_VALIDATE,
            "healthcheck": {
                "test": [
                    "CMD-SHELL",
                    "bash -c 'exec 3<>/dev/tcp/127.0.0.1/9000; "
                    'printf "GET /health/ready HTTP/1.0\\r\\n\\r\\n" >&3; '
                    'head -1 <&3 | grep -q " 200 "\'',
                ],
                "interval": "5s",
                "timeout": "3s",
                "retries": 60,
                "start_period": "30s",
            },
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
        },
        "api": {
            **backend,
            "env_file": [p("api.env")],
            "volumes": [
                p("tls/ca.pem") + ":/run/trust/ca.pem:ro",
                "catalog_data:/catalog:ro",
                "photo_data:/photos",
            ],
        },
        "gateway": {
            "image": images["gateway"],
            "labels": labels,
            "volumes": [
                p("gateway-open.Caddyfile") + ":/etc/caddy/Caddyfile:ro",
                p("tls/server.pem") + ":/run/tls/server.pem:ro",
                p("tls/server.key") + ":/run/tls/server.key:ro",
            ],
            "read_only": True,
            "tmpfs": ["/tmp", "/data", "/config"],
        },
        "catalog-init": {
            **backend,
            "user": "0:0",
            "cap_add": ["CHOWN", "DAC_OVERRIDE", "FOWNER"],
            "volumes": [
                p("catalog-restored/catalog") + ":/input:ro",
                "catalog_data:/catalog",
                "photo_data:/photos",
                "worker_data:/worker",
            ],
            "command": [
                ".venv/bin/python",
                "-c",
                "import os,shutil; shutil.copytree('/input','/catalog',dirs_exist_ok=True); "
                "[(os.chown(r,10001,10001),os.chmod(r,0o700),"
                "[(os.chown(os.path.join(r,f),10001,10001),"
                "os.chmod(os.path.join(r,f),0o600)) for f in fs]) "
                "for p in ['/catalog','/photos','/worker'] for r,ds,fs in os.walk(p)]",
            ],
        },
    }
    return {
        "name": project,
        "services": services,
        "volumes": {
            n: {"labels": labels}
            for n in ("postgres_data", "catalog_data", "worker_data", "photo_data")
        },
        "networks": {"default": {"labels": labels}},
    }


class Target:
    def __init__(self, state):
        self.state = unlinked(state).resolve(strict=True)
        self.record = read(self.state / "restore-target.json")
        require(self.record["format"] == FORMAT, "Owned target marker required")
        self.config = read(self.state / "config.json")
        self.origin = self.config["origin"]
        require(self.config["project"] == self.record["project"], "Target project drift")
        for name, expected in self.record["files"].items():
            require(digest(self.state / name) == expected, "Target configuration drift")

    def save(self):
        write(self.state / "restore-target.json", self.record)

    def compose(self, *args, maintenance=False):
        selector = "label=com.docker.compose.project=" + self.config["project"]
        for kind, listing in (
            ("container", ("ps", "-aq")),
            ("volume", ("volume", "ls", "-q")),
            ("network", ("network", "ls", "-q")),
        ):
            for resource in docker(*listing, "--filter", selector).splitlines():
                field = ".Config.Labels" if kind == "container" else ".Labels"
                require(
                    docker(
                        kind,
                        "inspect",
                        "--format",
                        "{{index " + field + ' "' + LABEL + '"}}',
                        resource,
                    )
                    == self.record["owner"],
                    "Foreign target resource refused",
                )
        command = [
            "docker",
            "compose",
            "--project-name",
            self.config["project"],
            "-f",
            str(self.state / "compose.restore.json"),
        ]
        if maintenance:
            command += ["-f", str(self.state / "compose.maintenance.json")]
        return execute(self.state, command + list(args)).decode().strip()

    def sql(self, database, statement):
        container = self.compose("ps", "-q", "postgres")
        require(container, "Owned target postgres is absent")
        require(
            docker("inspect", "--format", '{{index .Config.Labels "' + LABEL + '"}}', container)
            == self.record["owner"],
            "Foreign target container refused",
        )
        query = self.state / "query-private.sql"
        private_write(query, statement)
        return (
            execute(
                self.state,
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-X",
                    "-qAt",
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                input_path=query,
            )
            .decode()
            .strip()
        )


def materialize(archive, state, project, manifest_sha256, images):
    archive, raw, manifest = pinned_archive(archive, manifest_sha256)
    from calorie_app.health import EXPECTED_REVISION

    require(manifest["revision"] == EXPECTED_REVISION, "Backup/source schema mismatch")
    state = unlinked(state).resolve()
    require(
        not state.exists()
        and not state.is_relative_to(archive)
        and not archive.is_relative_to(state),
        "New disjoint target required",
    )
    source = read(archive / "config/config.json")
    require(source["project"] != project, "Source project cannot be a restore target")
    host_address(source["host"])
    require(
        source["origin"] == f"https://{source['host']}:{int(source['port'])}",
        "Paired origin mismatch",
    )
    empty_project(project)
    # Validate all image pins before creating state or Docker resources.
    configuration(state, project, source, images, "preflight")
    for image in images.values():
        require(
            docker("image", "inspect", "--format", "{{.Id}}", image) == image,
            "Pinned image unavailable",
        )
    private_directory(state)
    with lock(state):
        sealed = state / "paired-input"
        private_directory(sealed)
        for name, expected in manifest["files"].items():
            destination = sealed / relative(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive / name, destination)
            require(digest(destination) == expected["sha256"], "Changed payload during staging")
        private_write(sealed / "manifest.json", raw.decode())
        verify_archive(sealed)
        for name in ("postgres.env", "api.env", "keycloak.env", "credentials.json"):
            shutil.copyfile(sealed / "config" / name, state / name)
        shutil.copytree(sealed / "config/tls", state / "tls")
        config = source | {"project": project}
        write(state / "config.json", config)
        owner = str(uuid4())
        write(state / "compose.restore.json", configuration(state, project, source, images, owner))
        private_write(state / "gateway-open.Caddyfile", (HERE / "Caddyfile").read_text())
        record = {
            "format": FORMAT,
            "owner": owner,
            "project": project,
            "source_project": source["project"],
            "phase": "MATERIALIZING",
            "manifest_sha256": manifest_sha256,
            "images": images,
            "adapter_sha256": digest(Path(__file__).resolve()),
            "source_epoch": manifest["source_epoch"],
            "files": {},
            "full_ko32": False,
            "created_at": datetime.now(UTC).isoformat(),
        }
        for path in state.iterdir():
            if path.is_file() and path.name not in ("operation.lock", "restore-target.json"):
                record["files"][path.name] = digest(path)
        for path in (state / "tls").iterdir():
            record["files"][path.relative_to(state).as_posix()] = digest(path)
        write(state / "restore-target.json", record)
        target = Target(state)
        try:
            target.compose("up", "--detach", "--no-deps", "--wait", "postgres")
            container = target.compose("ps", "-q", "postgres")
            roles = (sealed / "roles.sql").read_text()
            require(roles.count("CREATE ROLE postgres;") == 1, "Unexpected bootstrap role archive")
            target.sql("postgres", roles.replace("CREATE ROLE postgres;", "-- initdb postgres", 1))
            for database in ("calorie_app", "keycloak"):
                execute(
                    state,
                    [
                        "docker",
                        "exec",
                        "-i",
                        container,
                        "pg_restore",
                        "-U",
                        "postgres",
                        "-d",
                        "postgres",
                        "--create",
                        "--exit-on-error",
                    ],
                    input_path=sealed / (database + ".dump"),
                    output_path=state / (database + "-restore-private.log"),
                )
            require(
                target.sql("calorie_app", "SELECT version_num FROM app.alembic_version")
                == manifest["revision"],
                "Restored schema mismatch",
            )
            for database, query in FINGERPRINTS.items():
                require(
                    sha(target.sql(database, query).encode()) == manifest["fingerprints"][database],
                    "Restored account or identity fingerprint differs",
                )
            require(
                target.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state")
                == manifest["source_epoch"],
                "Restored epoch differs before fencing",
            )
            epoch = str(uuid4())
            target.sql(
                "calorie_app",
                "BEGIN; UPDATE app.nemesis_control SET enabled=false; "
                f"UPDATE app.installation_state SET sync_epoch='{epoch}'; "
                "DELETE FROM app.sync_sessions; UPDATE app.ai_controls SET dispatch_open=false, "
                "closed_at=coalesce(closed_at,clock_timestamp()); COMMIT;",
            )
            for _ in range(10000):
                result = read_result(
                    target.sql(
                        "calorie_app",
                        "SET ROLE calorie_app_migrator; SELECT app.e8n_restore_maintain(100)",
                    )
                )
                if result["pending"] == 0:
                    break
            else:
                raise RuntimeError("Bounded restored cleanup incomplete")
            require(
                target.sql("calorie_app", "SELECT dispatch_open FROM app.ai_controls") == "f",
                "Restored AI must remain closed",
            )
            require(
                target.sql("calorie_app", "SELECT enabled FROM app.nemesis_control") == "f"
                and target.sql("calorie_app", "SELECT count(*) FROM app.sync_sessions") == "0"
                and target.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state")
                == epoch,
                "Restored epoch/session/Nemesis fencing incomplete",
            )
            restore_catalog(sealed / "catalog.tar", state / "catalog-restored")
            target.compose("run", "--rm", "--no-deps", "catalog-init")
            target.compose(
                "up", "--detach", "--no-deps", "--wait", "--wait-timeout", "360", "keycloak"
            )
            target.record.update(
                phase="OFFLINE_TARGET_READY",
                target_epoch=epoch,
                api_started=False,
                ports_published=False,
                ai_started=False,
                materialized_at=datetime.now(UTC).isoformat(),
            )
            target.save()
            return target.record
        except Exception:
            target.record["phase"] = "MATERIALIZATION_FAILED_CLOSED"
            target.save()
            private_write(state / "failure-private.log", traceback.format_exc())
            raise


def read_result(value):
    return json.loads(value)


def hold_sessions(source_state, output):
    source = Stack(Path(source_state).resolve(strict=True))
    probe = Probe(source)
    output = unlinked(output).resolve()
    require(output.is_relative_to(source.state), "Old tokens must remain in private source state")
    require(not Path(output).exists(), "Existing old-session evidence preserved")
    sessions = {}
    for who in ("a", "b"):
        session = probe.login(who)
        response = expect(probe.api("GET", "/api/v1/me", token=session["access_token"]), 200)
        sessions[who] = session | {"source_http_status": response.status_code}
    result = {
        "format": FORMAT + "/old-sessions",
        "origin": source.origin,
        "ca_sha256": digest(source.state / "tls/ca.pem"),
        "sessions": sessions,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    write(output, result)
    return {"old_sessions_sha256": digest(output), "source_authentication": "PASS"}


def source_closed(target):
    project = target.record["source_project"]
    names = docker("ps", "-q", "--filter", "label=com.docker.compose.project=" + project)
    for container in names.splitlines():
        service = docker(
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.service"}}',
            container,
        )
        require(service == "postgres", "Source writer/issuer still running; no cutover")
    # This local path refuses all account/deletion drift. It is not a production ledger importer.
    pg = docker(
        "ps",
        "-q",
        "--filter",
        "label=com.docker.compose.project=" + project,
        "--filter",
        "label=com.docker.compose.service=postgres",
    )
    require(pg and len(pg.splitlines()) == 1, "Exact source PG witness required")
    clients = target.state / "source-clients-readonly.sql"
    private_write(
        clients,
        "BEGIN READ ONLY; SELECT count(*) FROM pg_stat_activity WHERE "
        "backend_type='client backend' AND pid<>pg_backend_pid(); ROLLBACK;",
    )
    count = (
        execute(
            target.state,
            [
                "docker",
                "exec",
                "-i",
                pg,
                "psql",
                "-X",
                "-qAt",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input_path=clients,
        )
        .decode()
        .strip()
    )
    require(count == "0", "Source database clients remain")
    manifest = read(target.state / "paired-input/manifest.json")
    for database, query in FINGERPRINTS.items():
        path = target.state / "source-readonly-query.sql"
        private_write(path, "BEGIN READ ONLY; " + query + " ROLLBACK;")
        observed = (
            execute(
                target.state,
                [
                    "docker",
                    "exec",
                    "-i",
                    pg,
                    "psql",
                    "-X",
                    "-qAt",
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                input_path=path,
            )
            .decode()
            .strip()
        )
        require(
            sha(observed.encode()) == manifest["fingerprints"][database],
            "Account/identity drift requires authenticated deletion-ledger reconciliation",
        )
    # Password resets and role/profile edits must not silently roll back either.
    # Session tables are deliberately excluded: real post-T0 logins change them.
    for table in ("user_entity", "credential", "user_role_mapping", "user_group_membership"):
        query = (
            "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),"
            "'[]'::jsonb)::text FROM public." + table + " t;"
        )
        path = target.state / "source-identity-readonly.sql"
        private_write(path, "BEGIN READ ONLY; " + query + " ROLLBACK;")
        observed = (
            execute(
                target.state,
                [
                    "docker",
                    "exec",
                    "-i",
                    pg,
                    "psql",
                    "-X",
                    "-qAt",
                    "-U",
                    "postgres",
                    "-d",
                    "keycloak",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                input_path=path,
            )
            .decode()
            .strip()
        )
        require(
            sha(observed.encode()) == sha(target.sql("keycloak", query).encode()),
            "Provider credentials/roles/profile drift since T0 requires separate reconciliation",
        )


def maintenance_configuration(target):
    content = """{
 admin off
 auto_https off
 persist_config off
}
https://:8443 {
 tls /run/tls/server.pem /run/tls/server.key
 header Cache-Control "no-store"
 @noncanonical expression `{http.request.uri}.contains("%") || {http.request.uri}.contains("?")`
 respond @noncanonical "Recovery maintenance" 503
 @master {
  method POST
  path /realms/master/protocol/openid-connect/token
 }
 @logout {
  method POST
  path /admin/realms/calorie-dev/logout-all
 }
 @jwks {
  method GET
  path /realms/calorie-dev/protocol/openid-connect/certs
 }
 @sessions {
  method GET
  path_regexp sessions ^/admin/realms/calorie-dev/users/[0-9a-f-]{36}/sessions$
 }
 handle @master {
  reverse_proxy keycloak:8080
 }
 handle @logout {
  reverse_proxy keycloak:8080
 }
 handle @jwks {
  reverse_proxy keycloak:8080
 }
 handle @sessions {
  reverse_proxy keycloak:8080
 }
 handle {
  respond "Recovery maintenance" 503
 }
}
"""
    private_write(target.state / "gateway-maintenance.Caddyfile", content)
    override = {
        "services": {
            "gateway": {
                "ports": [f"{target.config['host']}:{target.config['port']}:8443"],
                "volumes": [
                    (target.state / "gateway-maintenance.Caddyfile").as_posix()
                    + ":/etc/caddy/Caddyfile:ro"
                ],
            }
        }
    }
    write(target.state / "compose.maintenance.json", override)
    for name in ("gateway-maintenance.Caddyfile", "compose.maintenance.json"):
        target.record["files"][name] = digest(target.state / name)
    target.save()


def fence(state):
    target = Target(state)
    with lock(target.state):
        require(
            target.record["phase"] in ("OFFLINE_TARGET_READY", "MAINTENANCE"),
            "Target not awaiting provider fence",
        )
        source_closed(target)
        maintenance_configuration(target)
        target.record["phase"] = "MAINTENANCE"
        target.record["ports_published"] = "PENDING_OR_UNKNOWN"
        target.save()
        target.compose(
            "up", "--detach", "--no-deps", "--force-recreate", "gateway", maintenance=True
        )
        probe = Probe(target)
        wait_maintenance(probe)
        target.record["ports_published"] = True
        target.save()
        # The issuer and verifier use at most 300s access lifetime and 60s skew.
        lifetime = int(
            target.sql(
                "keycloak", "SELECT access_token_lifespan FROM realm WHERE name='calorie-dev'"
            )
        )
        require(0 < lifetime <= 300, "Provider lifetime exceeds qualified 421s bound")
        result = admin(probe, "POST", "/logout-all").json()
        require(
            isinstance(result, dict) and not result.get("failedRequests"),
            "Provider logout-all partially failed",
        )
        subjects = target.sql(
            "keycloak",
            "SELECT id FROM user_entity WHERE realm_id="
            "(SELECT id FROM realm WHERE name='calorie-dev') ORDER BY id",
        )
        empty = 0
        for subject in subjects.splitlines():
            UUID(subject)
            sessions = admin(probe, "GET", "/users/" + subject + "/sessions").json()
            require(sessions == [], "Restored provider sessions remain")
            empty += 1
        require(empty > 0, "No provider subjects witnessed")
        start = time.monotonic()
        closed_at = datetime.now(UTC)
        while time.monotonic() - start < MIN_FENCE_SECONDS:
            wait_maintenance(probe)
            source_closed(target)
            time.sleep(min(10, max(0, MIN_FENCE_SECONDS - (time.monotonic() - start))))
        elapsed = time.monotonic() - start
        require(
            (datetime.now(UTC) - closed_at).total_seconds() >= MIN_FENCE_SECONDS,
            "Wall and monotonic fence disagree",
        )
        target.record.update(
            phase="FENCE_COMPLETE",
            real_fence_seconds=elapsed,
            provider_subjects_with_zero_sessions=empty,
            closed_after_logout_at=closed_at.isoformat(),
        )
        target.save()
        return {"phase": "FENCE_COMPLETE", "real_fence_seconds": elapsed}


def activate(state, sessions_path, sessions_sha256):
    target = Target(state)
    with lock(target.state):
        require(target.record["phase"] == "FENCE_COMPLETE", "Real provider fence required")
        source_closed(target)
        require(digest(sessions_path) == sessions_sha256, "Old-session evidence pin differs")
        old = read(sessions_path)
        require(
            old["format"] == FORMAT + "/old-sessions"
            and old["origin"] == target.origin
            and old["ca_sha256"] == digest(target.state / "tls/ca.pem"),
            "Old sessions belong to another cohort",
        )
        require(
            old["sessions"]
            and all(s.get("source_http_status") == 200 for s in old["sessions"].values()),
            "Observed source-authenticated tokens required",
        )
        # Publish the same origin only after source closure and measured fencing.
        data = read(target.state / "compose.restore.json")
        data["services"]["gateway"]["ports"] = [
            f"{target.config['host']}:{target.config['port']}:8443"
        ]
        write(target.state / "compose.restore.json", data)
        target.record["files"]["compose.restore.json"] = digest(
            target.state / "compose.restore.json"
        )
        target.record["api_started"] = "PENDING_OR_UNKNOWN"
        target.save()
        try:
            target.compose("up", "--detach", "--no-deps", "api")
            target.compose("up", "--detach", "--no-deps", "--force-recreate", "gateway")
            probe = Probe(target)
            probe.ready()
            for session in old["sessions"].values():
                expect(probe.api("GET", "/api/v1/me", token=session["access_token"]), 401)
                with probe.client() as client:
                    result = expect(
                        client.post(
                            probe.issuer + "/protocol/openid-connect/token",
                            data={
                                "grant_type": "refresh_token",
                                "client_id": "calorie-android",
                                "refresh_token": session["refresh_token"],
                            },
                        ),
                        400,
                    )
                    require(result.json().get("error") == "invalid_grant", "Old refresh accepted")
            target.record.update(
                phase="TARGET_AUTH_QUALIFIED",
                api_started=True,
                ports_published=True,
                old_access_refresh="REFUSED",
                client_recovery="NOT_RUN",
                ai_started=False,
            )
            target.save()
            return {"phase": "TARGET_AUTH_QUALIFIED", "client_recovery": "NOT_RUN"}
        except Exception:
            # Close ingress again on any failed admission; preserve all target data.
            try:
                target.compose("stop", "gateway", "api")
            except Exception:
                target.record.update(
                    phase="ADMISSION_CLOSE_FAILED", api_started="UNKNOWN", ports_published="UNKNOWN"
                )
                target.save()
                raise
            else:
                target.record.update(
                    phase="ADMISSION_FAILED_CLOSED", api_started=False, ports_published=False
                )
                target.save()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("materialize", "hold-sessions", "fence", "activate"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--project")
    parser.add_argument("--images", type=Path)
    parser.add_argument("--sessions", type=Path)
    parser.add_argument("--sessions-sha256")
    args = parser.parse_args()
    try:
        if args.action == "materialize":
            result = materialize(
                args.archive, args.state, args.project, args.manifest_sha256, read(args.images)
            )
            result = {k: result[k] for k in ("phase", "project", "api_started", "ports_published")}
        elif args.action == "hold-sessions":
            result = hold_sessions(args.state, args.sessions)
        elif args.action == "fence":
            result = fence(args.state)
        else:
            result = activate(args.state, args.sessions, args.sessions_sha256)
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({"result": "FAIL", "error_kind": type(error).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
