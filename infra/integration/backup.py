"""Private paired local backup and offline restore rehearsal; never reopens traffic."""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from monitor import console_options
from run import HERE, ROOT, host_address, private_write
from run_e8 import SERVICES, E8Stack

IMAGE = (
    "docker.io/library/postgres:17@sha256:"
    "2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
LABEL = "calorie.local-restore-rehearsal"
ARCHIVES = {"roles.sql", "calorie_app.dump", "keycloak.dump", "catalog.tar"}
FINGERPRINTS = {
    "calorie_app": "SELECT coalesce(jsonb_agg("
    "jsonb_build_array(id,issuer,subject,state,generation) "
    "ORDER BY id),'[]'::jsonb)::text FROM app.user_accounts;",
    "keycloak": "SELECT coalesce(jsonb_agg(jsonb_build_array(id,realm_id,username,enabled) "
    "ORDER BY id),'[]'::jsonb)::text FROM user_entity;",
}


def private_directory(path):
    path.mkdir(mode=0o700, parents=True)
    if os.name == "nt":
        identity = subprocess.check_output(
            ["whoami", "/user", "/fo", "csv", "/nh"], text=True, **console_options()
        )
        sid = next(csv.reader([identity.strip()]))[1]
        if not re.fullmatch(r"S-1-[0-9-]+", sid):
            raise ValueError("Invalid local identity")
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
            **console_options(),
        )


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def execute(directory, command, *, input_path=None, output_path=None, environment=None):
    """Stream archives without decoding bytes or exposing privileged diagnostics."""
    with (directory / "operation-private.log").open("ab") as errors:
        incoming = None if input_path is None else input_path.open("rb")
        outgoing = subprocess.PIPE if output_path is None else output_path.open("wb")
        try:
            result = subprocess.run(
                command,
                stdin=incoming,
                stdout=outgoing,
                stderr=errors,
                env=environment,
                check=True,
                timeout=300,
                **console_options(),
            )
            return result.stdout
        finally:
            if incoming is not None:
                incoming.close()
            if output_path is not None:
                outgoing.close()
                output_path.chmod(0o600)


def verify_archive(directory):
    directory = directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != 1 or manifest.get("writers_stopped") is not True:
        raise ValueError("Incomplete backup")
    UUID(manifest["source_epoch"])
    datetime.fromisoformat(manifest["captured_at"])
    files = manifest["files"]
    if not ARCHIVES <= set(files):
        raise ValueError("Missing paired archive")
    for name, expected in files.items():
        relative = Path(name)
        path = directory / relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink():
            raise ValueError("Invalid archive path")
        if path.resolve().parent != directory and directory not in path.resolve().parents:
            raise ValueError("Archive escaped backup directory")
        if path.stat().st_size != expected["size"] or digest(path) != expected["sha256"]:
            raise ValueError("Archive checksum mismatch")
    return manifest


def capture(state, destination):
    stack = E8Stack(state)
    host_address(stack.config["host"])
    private_directory(destination)  # Never overwrite an earlier backup.
    started = time.monotonic()
    stack.compose("stop", "gateway")
    if (state / "e8-admin.env").exists():
        stack.e8("stop", *SERVICES.values())
    stack.compose("stop", "api", "retention", "keycloak")
    if (
        stack.sql(
            "postgres",
            "SELECT count(*) FROM pg_stat_activity WHERE "
            "backend_type='client backend' AND pid<>pg_backend_pid();",
        )
        != "0"
    ):
        raise RuntimeError("Other database clients remain; writers must be fenced")
    captured_at = datetime.now(UTC).isoformat()
    epoch = stack.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;")
    accounts = int(stack.sql("calorie_app", "SELECT count(*) FROM app.user_accounts;"))
    identities = int(stack.sql("keycloak", "SELECT count(*) FROM user_entity;"))
    revision = stack.sql("calorie_app", "SELECT version_num FROM app.alembic_version;")
    from calorie_app.health import EXPECTED_REVISION

    if revision != EXPECTED_REVISION:
        raise ValueError("Backup source schema mismatch")
    fingerprints = {
        database: hashlib.sha256(stack.sql(database, query).encode()).hexdigest()
        for database, query in FINGERPRINTS.items()
    }
    private_write(
        destination / "roles.sql",
        stack.compose("exec", "-T", "postgres", "pg_dumpall", "-U", "postgres", "--globals-only"),
    )
    command = [
        "docker",
        "compose",
        "--env-file",
        str(state / "compose.env"),
        "--project-name",
        stack.config["project"],
        "-f",
        str(HERE / "compose.yaml"),
    ]
    for database in ("calorie_app", "keycloak"):
        execute(
            destination,
            command
            + ["exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-Fc", "--create", database],
            output_path=destination / (database + ".dump"),
        )
    config = destination / "config"
    config.mkdir(mode=0o700)
    for path in state.glob("*.env"):
        if path.is_symlink():
            raise ValueError("Unexpected configuration symlink")
        shutil.copy2(path, config / path.name)
    for name in ("config.json", "credentials.json"):
        shutil.copy2(state / name, config / name)
    for name in ("tls", "realm"):
        if any(p.is_symlink() for p in (state / name).rglob("*")):
            raise ValueError("Unexpected configuration symlink")
        shutil.copytree(state / name, config / name)
    code = (
        "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
        "t.add('/catalog',arcname='catalog'); t.close()"
    )
    execute(
        destination,
        command
        + [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "-v",
            stack.config["project"] + "_catalog_data:/catalog:ro",
            "migrate",
            ".venv/bin/python",
            "-I",
            "-c",
            code,
        ],
        output_path=destination / "catalog.tar",
    )
    paths = [destination / name for name in ARCHIVES] + [
        p for p in config.rglob("*") if p.is_file()
    ]
    manifest = {
        "format": 1,
        "captured_at": captured_at,
        "source_epoch": epoch,
        "accounts": accounts,
        "identities": identities,
        "revision": revision,
        "writers_stopped": True,
        "fingerprints": fingerprints,
        "capture_seconds": round(time.monotonic() - started, 3),
        "files": {
            p.relative_to(destination).as_posix(): {"size": p.stat().st_size, "sha256": digest(p)}
            for p in paths
        },
    }
    private_write(destination / "manifest.json", json.dumps(manifest, indent=2))
    verify_archive(destination)
    # Keep ingress and all writers stopped. Resuming is an explicit operator action.
    return {"result": "PASS", "paired_backup": True, "writers_stopped": True}


def rehearse(directory):
    manifest = verify_archive(directory)
    roles = (directory / "roles.sql").read_text()
    if roles.count("CREATE ROLE postgres;") != 1:
        raise ValueError("Unexpected bootstrap role archive")
    scratch = directory / ("rehearsal-" + uuid4().hex)
    private_directory(scratch)
    private_write(
        scratch / "roles.sql",
        roles.replace(
            "CREATE ROLE postgres;",
            "-- initdb postgres exists; restore its archived attributes below.",
            1,
        ),
    )
    original = dict(
        line.split("=", 1) for line in (directory / "config/postgres.env").read_text().splitlines()
    )
    environment = os.environ | {"POSTGRES_PASSWORD": original["POSTGRES_PASSWORD"]}
    container = "calorie-restore-rehearsal-" + uuid4().hex[:12]
    started = time.monotonic()
    checks = []

    def sql(statement, database="calorie_app"):
        path = scratch / "query.sql"
        private_write(path, statement)
        return (
            execute(
                scratch,
                [
                    "docker",
                    "exec",
                    "-i",
                    container,
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-qAt",
                ],
                input_path=path,
            )
            .decode()
            .strip()
        )

    try:
        execute(
            scratch,
            [
                "docker",
                "run",
                "--detach",
                "--network",
                "none",
                "--name",
                container,
                "--label",
                LABEL + "=owned",
                "-e",
                "POSTGRES_PASSWORD",
                IMAGE,
            ],
            environment=environment,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=15,
                **console_options(),
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Rehearsal PostgreSQL did not start")
        execute(
            scratch,
            [
                "docker",
                "exec",
                "-i",
                container,
                "psql",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            input_path=scratch / "roles.sql",
            output_path=scratch / "roles-private.log",
        )
        for database in ("calorie_app", "keycloak"):
            execute(
                scratch,
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
                input_path=directory / (database + ".dump"),
                output_path=scratch / (database + "-private.log"),
            )
        if (
            int(sql("SELECT count(*) FROM app.user_accounts;")) != manifest["accounts"]
            or int(sql("SELECT count(*) FROM user_entity;", "keycloak")) != manifest["identities"]
            or sql("SELECT sync_epoch FROM app.installation_state;") != manifest["source_epoch"]
        ):
            raise ValueError("Restored identity/account/epoch mismatch")
        checks.append(
            "Real app/Keycloak archives and globals restored; original counts/epoch match"
        )
        new_epoch = uuid4()
        from calorie_app.health import EXPECTED_REVISION

        if sql("SELECT version_num FROM app.alembic_version;") != EXPECTED_REVISION:
            raise ValueError("Restored schema does not match installed source")
        for database, query in FINGERPRINTS.items():
            restored = hashlib.sha256(sql(query, database).encode()).hexdigest()
            if restored != manifest["fingerprints"][database]:
                raise ValueError("Restored account/identity fingerprint mismatch")
        checks.append("Subjects/generation/state and Keycloak identities match fingerprints")
        sql(
            "BEGIN; UPDATE app.nemesis_control SET enabled=false; "
            f"UPDATE app.installation_state SET sync_epoch='{new_epoch}'; "
            "DELETE FROM app.sync_sessions; COMMIT;"
        )
        for _ in range(10000):
            result = json.loads(
                sql("SET ROLE calorie_app_migrator; SELECT app.e8n_restore_maintain(100);")
            )
            if result["pending"] == 0:
                break
        else:
            raise RuntimeError("Bounded restore cleanup remains pending")
        if (
            sql("SELECT sync_epoch FROM app.installation_state;") != str(new_epoch)
            or sql("SELECT enabled FROM app.nemesis_control;") != "f"
            or sql("SELECT dispatch_open FROM app.ai_controls;") != "f"
            or sql("SELECT count(*) FROM app.nemesis_challenges WHERE status<>'cancelled';") != "0"
            or sql("SELECT count(*) FROM app.sync_sessions;") != "0"
        ):
            raise ValueError("Restore fencing failed")
        checks.append(
            "New committed epoch; old snapshots cancelled, Nemesis closed/cleanup and AI fenced"
        )
        restore_catalog(directory / "catalog.tar", scratch / "catalog")
        checks.append(
            "Catalog safely extracted and content verified in a private scratch directory"
        )
        worker_configuration = directory / "config/e8-finalizer.env"
        if worker_configuration.exists():
            from sqlalchemy.engine import make_url

            values = dict(
                line.split("=", 1) for line in worker_configuration.read_text().splitlines()
            )
            url = make_url(values["DATABASE_URL"])
            result = (
                execute(
                    scratch,
                    [
                        "docker",
                        "exec",
                        "-e",
                        "PGPASSWORD",
                        container,
                        "psql",
                        "-h",
                        "127.0.0.1",
                        "-U",
                        url.username,
                        "-d",
                        "calorie_app",
                        "-At",
                        "-c",
                        "SELECT app.e8n_finalize_batch(100);",
                    ],
                    environment=os.environ | {"PGPASSWORD": url.password},
                )
                .decode()
                .strip()
            )
            if json.loads(result).get("ready") is not False:
                raise ValueError("Restored finalizer is not fenced")
            checks.append("Restored SCRAM finalizer LOGIN works; closed gate stays disabled")
        receipt = {
            "result": "PASS",
            "checks": checks,
            "offline_rehearsal_seconds": round(time.monotonic() - started, 3),
            "traffic_reopened": False,
            "production_rpo_rto": False,
            "waiting_external": [
                "Authoritative deletion registry reconciliation",
                "Old JWT/refresh/session revocation",
                "Client recovery and complete rollout acceptance",
            ],
        }
        private_write(scratch / "receipt.json", json.dumps(receipt, indent=2))
        return receipt
    finally:
        inspected = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                '{{index .Config.Labels "' + LABEL + '"}}',
                container,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            **console_options(),
        )
        if inspected.returncode == 0 and inspected.stdout.strip() == "owned":
            execute(scratch, ["docker", "rm", "--force", "--volumes", container])


def restore_catalog(archive, destination):
    import tarfile

    destination.mkdir(mode=0o700)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if any(
            not (m.isdir() or m.isfile())
            or Path(m.name).parts[0] != "catalog"
            or ".." in Path(m.name).parts
            for m in members
        ):
            raise ValueError("Catalog must contain only directories and regular files")
        source.extractall(destination, members=members, filter="data")
        for member in members:
            if member.isfile():
                extracted = destination / member.name
                with source.extractfile(member) as original:
                    expected = hashlib.file_digest(original, "sha256").hexdigest()
                if digest(extracted) != expected:
                    raise ValueError("Catalog restore content mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "verify", "rehearse"))
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    try:
        directory = args.backup.resolve()
        if ROOT in directory.parents and ROOT / ".tools" not in directory.parents:
            raise ValueError("Backup inside checkout must be ignored under .tools")
        if args.action == "capture":
            if args.state is None:
                raise ValueError("Explicit own local state required")
            result = capture(args.state.resolve(), directory)
        elif args.action == "verify":
            verify_archive(directory)
            result = {"result": "PASS", "archive_integrity": True}
        else:
            result = rehearse(directory)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print("Local backup operation failed; inspect private backup/state logs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
