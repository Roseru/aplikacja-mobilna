"""Owned PG17 paired backup/restore transport. No issuer, API or worker startup."""

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import tarfile
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from uuid import UUID, uuid4

# native establishes the existing shared helper/backend import roots.
# isort: off
from . import native
from backup import (
    FINGERPRINTS,
    digest,
    execute,
    private_directory,
    restore_catalog,
    verify_archive,
)
from calorie_app.health import EXPECTED_REVISION

# isort: on

DATABASES = ("calorie_app", "keycloak")
FORMAT = "calorie-native-restore/v1"


def owned_path(value):
    # Reject Win32 aliases before resolving or reading any path.
    raw = str(value).replace("\\", "/")
    parts = raw.split("/")
    if re.fullmatch(r"[a-zA-Z]:", parts[0]):
        parts = parts[1:]
    if raw.startswith("//") or any(
        part.endswith((" ", ".")) or ":" in part
        for part in parts
        if part not in ("", ".", "..")
    ):
        raise ValueError("Ambiguous state path")
    return native.confined(value)


def check_tree(path):
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.rglob("*"))):
        raise ValueError("Linked archive material refused")


def locked(function):
    @wraps(function)
    def operation(pg, *args, **kwargs):
        with pg.operation():
            return function(pg, *args, **kwargs)

    return operation


def disjoint(*paths):
    paths = [owned_path(p) for p in paths]
    if any(
        a == b or a in b.parents or b in a.parents
        for i, a in enumerate(paths)
        for b in paths[i + 1 :]
    ):
        raise ValueError("Source/archive/target paths must not overlap")


class OwnedPG:
    """A fresh physical cluster, bound to one datadir/port/binary/process birth."""

    operation = native.Native.operation

    def __init__(self, state):
        self.state = owned_path(state)
        self.marker = self.state / "owner.json"
        self.config = json.loads(self.marker.read_text())
        UUID(self.config["owner"])
        if self.config.get("format") != FORMAT or self.config["state"] != str(
            self.state
        ):
            raise ValueError("Not this owned restore state")
        self.pg = Path(self.config["pg_bin"])
        self.port = self.config["port"]
        self.user = self.config["user"]
        self.data = self.state / "postgres"
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ValueError("Invalid owned port")
        if self.user != "postgres":
            raise ValueError("Unexpected bootstrap role")
        check_tree(self.state)
        for name, expected in self.config["binaries"].items():
            if digest(self.pg / name) != expected["sha256"]:
                raise ValueError("PG binary changed")

    @classmethod
    def create(cls, state, pg_bin, port):
        state = owned_path(state)
        if state.exists():
            raise FileExistsError("Existing target preserved")
        native.available("127.0.0.1", [port])
        pg_bin = Path(pg_bin).resolve()
        binaries = {}
        for name in (
            "initdb",
            "pg_ctl",
            "postgres",
            "psql",
            "pg_dump",
            "pg_dumpall",
            "pg_restore",
        ):
            path = pg_bin / (name + ".exe")
            version = (
                subprocess.check_output([str(path), "--version"], **native.FLAGS)
                .decode()
                .strip()
            )
            if "(PostgreSQL) 17." not in version:
                raise ValueError("PG17 tools required")
            binaries[path.name] = {"version": version, "sha256": digest(path)}
        private_directory(state)
        native.private_write(state / "password.private", secrets.token_hex(32) + "\n")
        native.write_json(
            state / "owner.json",
            {
                "format": FORMAT,
                "owner": str(uuid4()),
                "state": str(state),
                "pg_bin": str(pg_bin),
                "port": port,
                "user": "postgres",
                "binaries": binaries,
                "status": "INITIALIZING",
            },
        )
        pg = cls(state)
        pg.command(
            "initdb",
            [
                "-D",
                pg.data,
                "-U",
                pg.user,
                "--encoding=UTF8",
                "--locale=C",
                "--auth=scram-sha-256",
                "--pwfile=" + str(state / "password.private"),
            ],
        )
        native.private_write(
            pg.data / "postgresql.conf",
            (pg.data / "postgresql.conf").read_text()
            + f"\nlisten_addresses='127.0.0.1'\nport={port}\n"
            + "log_statement='none'\nlog_min_error_statement='panic'\n",
        )
        pg.command(
            "pg_ctl",
            ["-D", pg.data, "-l", state / "postgres.log", "-w", "start"],
            output_path=state / "pg-start.private.log",
        )
        pid = int((pg.data / "postmaster.pid").read_text().splitlines()[0])
        record = native.identity(pid)
        if Path(record["executable"]).resolve() != (pg_bin / "postgres.exe").resolve():
            raise ValueError("Unexpected postgres executable; no stop authorized")
        pg.config.update(status="RUNNING", process=record)
        native.write_json(pg.marker, pg.config)
        pg.qualify()
        (state / "catalog").mkdir()
        return pg

    def env(self):
        return native.clean_env() | {
            "PGPASSWORD": (self.state / "password.private").read_text().strip(),
            "PGCLIENTENCODING": "UTF8",
        }

    def command(
        self, name, args, *, input_path=None, output_path=None, environment=None
    ):
        return execute(
            self.state,
            [str(self.pg / (name + ".exe")), *map(str, args)],
            input_path=input_path,
            output_path=output_path,
            environment=environment or self.env(),
        )

    def connection(self, database):
        if database not in (*DATABASES, "postgres"):
            raise ValueError("Unexpected database")
        return [
            "-h",
            "127.0.0.1",
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            database,
        ]

    def sql(self, database, statement):
        # SQL is streamed privately; no statement or password is put in argv.
        path = self.state / ("sql-" + uuid4().hex + ".private")
        native.private_write(path, statement)
        try:
            return (
                self.command(
                    "psql",
                    self.connection(database) + ["-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
                    input_path=path,
                )
                .decode("utf-8")
                .strip()
            )
        finally:
            path.unlink()

    def url(self, database="calorie_app"):
        from sqlalchemy import URL

        self.connection(database)
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.env()["PGPASSWORD"],
            host="127.0.0.1",
            port=self.port,
            database=database,
        )

    def qualify(self):
        owned_path(self.state)
        check_tree(self.data)
        record = self.config["process"]
        if native.identity(record["pid"]) != record:
            raise ValueError("Owned PID identity changed")
        pid = (self.data / "postmaster.pid").read_text().splitlines()
        if (
            int(pid[0]) != record["pid"]
            or Path(pid[1]).resolve() != self.data.resolve()
            or int(pid[3]) != self.port
        ):
            raise ValueError("Postmaster binding differs")
        proof = json.loads(
            self.sql(
                "postgres",
                "SELECT json_build_object('data',current_setting('data_directory'),"
                "'port',inet_server_port(),'address',inet_server_addr()::text,"
                "'listen',current_setting('listen_addresses'),'user',current_user);",
            )
        )
        if (
            Path(proof["data"]).resolve() != self.data.resolve()
            or proof["port"] != self.port
            or proof["address"] != "127.0.0.1/32"
            or proof["listen"] != "127.0.0.1"
            or proof["user"] != self.user
        ):
            raise ValueError("SQL target differs from owner")
        return proof

    @locked
    def seal(self):
        self.qualify()
        # Authentication is closed to application/KC/worker roles before quiescence.
        native.private_write(
            self.data / "pg_hba.conf",
            "host all postgres 127.0.0.1/32 scram-sha-256\nhost all all 0.0.0.0/0 reject\n"
            "host all all ::0/0 reject\n",
        )
        self.sql("postgres", "SELECT pg_reload_conf();")
        if (
            self.sql(
                "postgres",
                "SELECT count(*) FROM pg_stat_activity WHERE "
                "backend_type='client backend' AND pid<>pg_backend_pid();",
            )
            != "0"
        ):
            raise ValueError("Writers remain; stop own clients before capture")
        self.config["status"] = "SEALED"
        self.config["hba_sha256"] = digest(self.data / "pg_hba.conf")
        native.write_json(self.marker, self.config)

    def offline(self):
        self.qualify()
        if (
            self.config["status"] != "SEALED"
            or digest(self.data / "pg_hba.conf") != self.config["hba_sha256"]
        ):
            raise ValueError("Source must be sealed offline")
        if (
            self.sql(
                "postgres",
                "SELECT count(*) FROM pg_stat_activity WHERE "
                "backend_type='client backend' AND pid<>pg_backend_pid();",
            )
            != "0"
        ):
            raise ValueError("Other clients remain")

    @locked
    def stop(self):
        self._stop()

    def _stop(self):
        self.qualify()  # Re-check immediately before the one datadir-specific stop.
        self.command("pg_ctl", ["-D", self.data, "-w", "-m", "fast", "stop"])
        self.config["status"] = "STOPPED"
        native.write_json(self.marker, self.config)


@locked
def capture(pg, destination):
    destination = owned_path(destination)
    disjoint(pg.state, destination)
    pg.offline()
    catalog = pg.state / "catalog"
    check_tree(catalog)
    revision = pg.sql("calorie_app", "SELECT version_num FROM app.alembic_version;")
    if revision != EXPECTED_REVISION:
        raise ValueError("Backup schema mismatch")
    private_directory(destination)
    pg.command(
        "pg_dumpall",
        ["-h", "127.0.0.1", "-p", str(pg.port), "-U", pg.user, "--globals-only"],
        output_path=destination / "roles.sql",
    )
    for database in DATABASES:
        pg.command(
            "pg_dump",
            pg.connection(database) + ["-Fc", "--create"],
            output_path=destination / (database + ".dump"),
        )
    with tarfile.open(destination / "catalog.tar", "w") as archive:
        archive.add(catalog, arcname="catalog")
    pg.offline()
    manifest = {
        "format": 1,
        "transport": FORMAT,
        "captured_at": datetime.now(UTC).isoformat(),
        "source_owner": pg.config["owner"],
        "source_epoch": pg.sql(
            "calorie_app", "SELECT sync_epoch FROM app.installation_state;"
        ),
        "revision": revision,
        "writers_stopped": True,
        "accounts": int(
            pg.sql("calorie_app", "SELECT count(*) FROM app.user_accounts;")
        ),
        "identities": int(pg.sql("keycloak", "SELECT count(*) FROM user_entity;")),
        "fingerprints": {
            db: hashlib.sha256(pg.sql(db, q).encode()).hexdigest()
            for db, q in FINGERPRINTS.items()
        },
        "native_source": {
            "binaries": pg.config["binaries"],
            "process": pg.config["process"],
        },
        "files": {
            p.name: {"size": p.stat().st_size, "sha256": digest(p)}
            for p in destination.iterdir()
            if p.is_file()
        },
    }
    # pg_dumpall may include diagnostics in the source private log, never in the archive.
    native.write_json(destination / "manifest.json", manifest)
    verify_native_archive(destination)
    return manifest


def verify_native_archive(directory):
    directory = owned_path(directory)
    check_tree(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("transport") != FORMAT or manifest["revision"] != EXPECTED_REVISION:
        raise ValueError("Not a compatible native archive")
    if set(manifest["files"]) != {
        "roles.sql",
        "calorie_app.dump",
        "keycloak.dump",
        "catalog.tar",
    }:
        raise ValueError("Unexpected native archive member")
    UUID(manifest["source_owner"])
    manifest = verify_archive(directory)
    preflight_catalog(directory / "catalog.tar")
    return manifest


def preflight_catalog(path):
    """Reject dangerous portable tar names before creating a restore target."""
    seen = {}
    with tarfile.open(path) as archive:
        for member in archive:
            parts = member.name.split("/")
            key = member.name.casefold()
            if (
                not (member.isdir() or member.isfile())
                or parts[0] != "catalog"
                or key in seen
                or len(seen) >= 100000
                or any(
                    part in ("", ".", "..")
                    or part.endswith((" ", "."))
                    or any(c in part for c in '\\:<>"|?*')
                    or any(ord(c) < 32 for c in part)
                    or re.fullmatch(
                        r"(?i)(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", part
                    )
                    for part in parts
                )
            ):
                raise ValueError("Unsafe catalog member")
            seen[key] = member.isdir()
    if seen.get("catalog") is not True:
        raise ValueError("Missing catalog root")
    for name in seen:
        if any(
            seen.get("/".join(name.split("/")[:end])) is False
            for end in range(1, len(name.split("/")))
        ):
            raise ValueError("Catalog file is a parent directory")


def restore(archive, target, pg_bin, port):
    archive, target = owned_path(archive), owned_path(target)
    disjoint(archive, target)
    manifest = verify_native_archive(archive)
    if target.exists():
        raise FileExistsError("Existing target preserved")
    roles = (archive / "roles.sql").read_text(encoding="utf-8")
    if roles.count("CREATE ROLE postgres;") != 1:
        raise ValueError("Unexpected bootstrap role archive")
    pg = OwnedPG.create(target, pg_bin, port)
    pg.seal()
    with pg.operation():
        return restore_into(pg, archive, manifest, roles)


def restore_into(pg, archive, manifest, roles):
    target = pg.state
    # Keep target postgres credential rather than archive's credential; restore all
    # other role attributes/passwords. pg_dumpall's SETs and grants still execute.
    roles = "\n".join(
        line
        for line in roles.splitlines()
        if line != "CREATE ROLE postgres;"
        and not line.startswith("ALTER ROLE postgres ")
    )
    native.private_write(target / "roles.private.sql", roles)
    try:
        pg.command(
            "psql",
            pg.connection("postgres") + ["-X", "-v", "ON_ERROR_STOP=1"],
            input_path=target / "roles.private.sql",
            output_path=target / "roles-restore.private.log",
        )
        for database in DATABASES:
            pg.offline()
            pg.command(
                "pg_restore",
                pg.connection("postgres") + ["--create", "--exit-on-error"],
                input_path=archive / (database + ".dump"),
                output_path=target / (database + "-restore.private.log"),
            )
        if (
            pg.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;")
            != manifest["source_epoch"]
            or pg.sql("calorie_app", "SELECT version_num FROM app.alembic_version;")
            != manifest["revision"]
        ):
            raise ValueError("Restored schema/epoch mismatch")
        for db, query in FINGERPRINTS.items():
            if (
                hashlib.sha256(pg.sql(db, query).encode()).hexdigest()
                != manifest["fingerprints"][db]
            ):
                raise ValueError("Restored identity mismatch")
        epoch = str(uuid4())
        pg.sql(
            "calorie_app",
            "BEGIN; UPDATE app.nemesis_control SET enabled=false; "
            f"UPDATE app.installation_state SET sync_epoch='{epoch}'; DELETE FROM app.sync_sessions; "
            "UPDATE app.ai_controls SET dispatch_open=false,closed_at=coalesce(closed_at,clock_timestamp()); COMMIT;",
        )
        for _ in range(10000):
            cleanup = json.loads(
                pg.sql(
                    "calorie_app",
                    "SET ROLE calorie_app_migrator; SELECT app.e8n_restore_maintain(100);",
                )
            )
            if cleanup["pending"] == 0:
                break
        else:
            raise ValueError("Bounded cleanup incomplete")
        fence = json.loads(
            pg.sql(
                "calorie_app",
                "SELECT json_build_object('epoch',sync_epoch,"
                "'sessions',(SELECT count(*) FROM app.sync_sessions),'ai',(SELECT dispatch_open FROM app.ai_controls),"
                "'nemesis',(SELECT enabled FROM app.nemesis_control)) FROM app.installation_state;",
            )
        )
        if fence != {"epoch": epoch, "sessions": 0, "ai": False, "nemesis": False}:
            raise ValueError("Restored gates are not closed")
        restore_catalog(archive / "catalog.tar", target / "catalog-restored")
        pg.offline()
        receipt = {
            "format": FORMAT,
            "result": "PASS",
            "paired_restore": True,
            "source_epoch": manifest["source_epoch"],
            "restored_epoch": epoch,
            "fingerprints_verified_before_fence": True,
            "cleanup": cleanup,
            "archive_manifest_sha256": digest(archive / "manifest.json"),
            "traffic_reopened": False,
            "issuer_started": False,
            "google_io": 0,
            "full_ko32": False,
            "production_rpo_rto": False,
        }
        native.write_json(target / "receipt.json", receipt)
        return pg, receipt
    except Exception:
        native.write_json(
            target / "receipt.json", {"result": "FAIL", "traffic_reopened": False}
        )
        pg._stop()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "capture", "restore", "stop"))
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--pg-bin", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.action == "init":
        OwnedPG.create(args.state, args.pg_bin, args.port)
    elif args.action == "capture":
        pg = OwnedPG(args.state)
        pg.seal()
        capture(pg, args.archive)
    elif args.action == "restore":
        restore(args.archive, args.state, args.pg_bin, args.port)
    else:
        OwnedPG(args.state).stop()
    print(
        json.dumps({"result": "PASS", "action": args.action, "traffic_reopened": False})
    )


if __name__ == "__main__":
    main()
