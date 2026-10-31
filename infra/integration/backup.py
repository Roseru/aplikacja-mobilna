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
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from monitor import console_options
from run import ROOT, host_address, private_write
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


class RehearsalFailure(RuntimeError):
    def __init__(self, stage, error):
        self.receipt = {
            "result": "FAIL",
            "stage": stage,
            "error_kind": type(error).__name__,
            "exit_code": error.returncode
            if isinstance(error, subprocess.CalledProcessError)
            else None,
        }
        super().__init__("Offline restore rehearsal failed")


def wait_postgres(container, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
            capture_output=True,
            timeout=15,
            **console_options(),
        )
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("Rehearsal PostgreSQL TCP listener did not start")


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
    photos = manifest.get("optional_photos")
    if photos is not None and photos != {"format": 1, "archive": "photos.tar", "root": "photos"}:
        raise ValueError("Unsupported optional photo archive")
    if (photos is not None) != ("photos.tar" in files):
        raise ValueError("Photo payload and explicit format marker must be paired")
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


def capture(
    state,
    destination,
    *,
    stack=None,
    writers=(),
    verify_closed=None,
    extra_config=None,
    photo_volume=None,
    volume_archiver=None,
):
    """Capture the legacy stack or an explicitly qualified complete installation."""
    stack = stack if stack is not None else E8Stack(state)
    if photo_volume is not None and not re.fullmatch(
        re.escape(stack.config["project"]) + r"_[a-z0-9_-]+", photo_volume
    ):
        raise ValueError("Photo archive requires an owned named volume")
    host_address(stack.config["host"])
    private_directory(destination)  # Never overwrite an earlier backup.
    started = time.monotonic()
    stack.compose("stop", "gateway")
    if (state / "e8-admin.env").exists():
        stack.e8("stop", *SERVICES.values())
    if writers:
        stack.compose("stop", *writers)
    stack.compose("stop", "api", "retention", "keycloak")
    if verify_closed is not None:
        verify_closed()
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
    command = stack.compose_command()

    def archive_volume(volume, mount, source, name):
        if volume_archiver is not None:
            volume_archiver(destination, volume, mount, source, destination / name)
        else:
            execute(
                destination,
                command
                + [
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    "-v",
                    volume + ":" + mount + ":ro",
                    "migrate",
                    ".venv/bin/python",
                    "-I",
                    "-c",
                    source,
                ],
                output_path=destination / name,
                environment=stack.compose_environment(),
            )

    for database in ("calorie_app", "keycloak"):
        execute(
            destination,
            command
            + ["exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-Fc", "--create", database],
            output_path=destination / (database + ".dump"),
            environment=stack.compose_environment(),
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
    for name, source in (extra_config or {}).items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or ":" in name or "\\" in name:
            raise ValueError("Invalid extra backup configuration path")
        target = config / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if source.is_symlink() or not source.is_file() or target.exists():
            raise ValueError("Extra backup configuration must be a new ordinary file")
        shutil.copy2(source, target)
    code = (
        "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); "
        "t.add('/catalog',arcname='catalog'); t.close()"
    )
    archive_volume(stack.config["project"] + "_catalog_data", "/catalog", code, "catalog.tar")
    if photo_volume is not None:
        # Read the durable payload after all writers are physically closed. Preserve
        # JPEG/staging names and mtimes; do not run retention, change quota or jobs.
        photo_code = """
import os,re,stat,sys,tarfile
from pathlib import Path
from calorie_app.modules.ai.storage import MAX_IMAGE_BYTES
root=Path('/photos')
info=root.stat()
assert stat.S_IMODE(info.st_mode)==0o700 and info.st_uid==10001
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as target:
    target.add(root,arcname='photos',recursive=False)
    for item in sorted(root.iterdir()):
        info=item.lstat()
        assert re.fullmatch(r'[0-9a-f]{32}\\.(jpg|staging)',item.name)
        assert stat.S_ISREG(info.st_mode) and info.st_nlink==1
        assert stat.S_IMODE(info.st_mode)==0o600 and info.st_uid==10001
        assert 0<=info.st_size<=MAX_IMAGE_BYTES
        assert item.suffix=='.staging' or info.st_size>0
        target.add(item,arcname='photos/'+item.name,recursive=False)
"""
        archive_volume(photo_volume, "/photos", photo_code, "photos.tar")
    if verify_closed is not None:
        verify_closed()
    paths = [destination / name for name in ARCHIVES] + [
        p for p in config.rglob("*") if p.is_file()
    ]
    if photo_volume is not None:
        paths.append(destination / "photos.tar")
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
    if photo_volume is not None:
        manifest["optional_photos"] = {"format": 1, "archive": "photos.tar", "root": "photos"}
    private_write(destination / "manifest.json", json.dumps(manifest, indent=2))
    verify_archive(destination)
    # Keep ingress and all writers stopped. Resuming is an explicit operator action.
    return {"result": "PASS", "paired_backup": True, "writers_stopped": True}


def restore_photos(archive, destination):
    """Stage optional payload privately; no DB/queue/quota/retention mutation or job resume."""
    import tarfile

    from calorie_app.modules.ai.storage import MAX_IMAGE_BYTES

    private_directory(destination)
    root = destination / "photos"
    seen = set()
    files = total = 0
    with tarfile.open(archive) as source:
        for member in source:
            if member.name in seen:
                raise ValueError("Duplicate photo archive member")
            seen.add(member.name)
            if member.name == "photos":
                if not member.isdir() or member.mode != 0o700:
                    raise ValueError("Private photo directory required")
                root.mkdir(mode=0o700)
                continue
            if (
                not root.exists()
                or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                or member.sparse is not None
                or member.mode != 0o600
                or not re.fullmatch(r"photos/[0-9a-f]{32}\.(jpg|staging)", member.name)
                or not 0 <= member.size <= MAX_IMAGE_BYTES
                or member.name.endswith(".jpg")
                and member.size == 0
            ):
                raise ValueError("Photo archive must contain bounded private prepared objects")
            target = destination / member.name
            with source.extractfile(member) as incoming, target.open("xb") as output:
                target.chmod(0o600)
                shutil.copyfileobj(incoming, output, length=1024 * 1024)
            if target.stat().st_size != member.size:
                raise ValueError("Photo payload size mismatch")
            # Retention's orphan grace must not be extended by restoring a file.
            os.utime(target, (member.mtime, member.mtime))
            files += 1
            total += member.size
    if not root.is_dir():
        raise ValueError("Photo archive root missing")
    return {"files": files, "bytes": total}


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
    stage = "start_postgres"
    failure = None

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
        stage = "postgres_tcp_ready"
        wait_postgres(container)
        stage = "restore_roles"
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
            stage = "restore_" + database
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
        stage = "verify_identity_epoch"
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
        stage = "fence_restored_copy"
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
        stage = "restore_catalog"
        restore_catalog(directory / "catalog.tar", scratch / "catalog")
        checks.append(
            "Catalog safely extracted and content verified in a private scratch directory"
        )
        worker_configuration = directory / "config/e8-finalizer.env"
        if worker_configuration.exists():
            stage = "verify_scram_closed_gate"
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
    except Exception as error:
        failure = RehearsalFailure(stage, error)
        private_write(scratch / "failure-private.log", traceback.format_exc())
        private_write(scratch / "receipt.json", json.dumps(failure.receipt, indent=2))
        raise failure from None
    finally:
        try:
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
        except Exception as error:
            if failure is None:
                raise RehearsalFailure("cleanup", error) from None
            failure.receipt["cleanup_failed"] = True


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
    except RehearsalFailure as error:
        print(json.dumps(error.receipt, sort_keys=True))
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "stage": "prepare_or_validate_archive",
                    "error_kind": type(error).__name__,
                },
                sort_keys=True,
            )
        )
        print("Local backup operation failed; inspect private backup/state logs", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
