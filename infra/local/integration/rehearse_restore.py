"""One owned offline paired restore and service-level KO32 rehearsal (no listeners)."""

import argparse
import ctypes
import json
import secrets
import shutil
import socket
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

# native establishes the existing shared helper/backend import roots.
# isort: off
from . import native, restore, restore_trust
from backup import digest, private_directory
# isort: on


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def memory_available():
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "total_page",
                "available_page",
                "total_virtual",
                "available_virtual",
                "extended",
            )
        ]

    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        raise OSError("Cannot qualify available memory")
    return value.available


def finish_checks(receipt, binding, **proof):
    receipt["result"] = "FAIL"
    receipt["stage"] = "verify_final_source_binding"
    if native.source(binding["commit"]) != binding:
        raise ValueError("Source changed during rehearsal")
    receipt.update(result="PASS", stage="complete", **proof)


def stop_owned_clusters(clusters, receipt):
    receipt["stopped_owned_clusters"] = []
    errors = []
    for pg in reversed(clusters):
        try:
            pg.stop()
            receipt["stopped_owned_clusters"].append(pg.config["owner"])
        except Exception as error:  # noqa: BLE001 - record every stop failure, then fail caller
            receipt["result"] = "FAIL"
            errors.append(
                {"owner": pg.config["owner"], "error_kind": type(error).__name__}
            )
    if errors:
        receipt["cleanup_errors"] = errors
    return errors


def run(state, pg_bin, keycloak_home, java_home):
    from sqlalchemy import create_engine

    from . import restore_oracle

    state = restore.owned_path(state)
    if state.exists():
        raise FileExistsError("Fresh rehearsal directory required")
    binding = native.source("ee7d2da2db6fc5bca1d9dacd5b1bbca4281030d7")
    available = memory_available()
    if available < 2 * 1024**3:
        raise RuntimeError("Insufficient memory for bounded offline Keycloak import")
    private_directory(state)
    receipt = {
        "format": "calorie-native-restore-rehearsal/v1",
        "result": "FAIL",
        "started_at": datetime.now(UTC).isoformat(),
        "source": binding,
        "memory_available_before_import": available,
        "google_io": 0,
        "full_ko32": False,
        "room27": "NOT_RUN",
        "jwt_refresh_pkce": "NOT_RUN",
        "issuer_api_listeners": 0,
        "production_rpo_rto": False,
        "git": {
            name: subprocess.check_output(
                ["git", "rev-parse", value], cwd=native.ROOT, **native.FLAGS
            )
            .decode()
            .strip()
            for name, value in (
                ("head", "HEAD"),
                ("tree", "HEAD^{tree}"),
                ("parent", "HEAD^"),
            )
        },
        "runtime": {
            "python_version": sys.version,
            "python_sha256": digest(Path(sys.executable)),
            "java_sha256": digest(java_home / "bin/java.exe"),
            "keycloak_launcher_sha256": digest(keycloak_home / "bin/kc.bat"),
        },
    }
    clusters = []
    engine = None
    try:
        receipt["stage"] = "source_cluster"
        source = restore.OwnedPG.create(state / "source", pg_bin, free_port())
        clusters.append(source)
        passwords = {
            key: secrets.token_hex(32)
            for key in (
                "APP_MIGRATOR_PASSWORD",
                "APP_API_PASSWORD",
                "APP_WORKER_PASSWORD",
                "KEYCLOAK_DB_PASSWORD",
            )
        }
        script = (
            (native.ROOT / "infra/local/init-db.sh")
            .read_text()
            .split("<<'SQL'\n", 1)[1]
            .rsplit("\nSQL", 1)[0]
        )
        native.private_write(state / "bootstrap.private.sql", script)
        source.command(
            "psql",
            source.connection("postgres") + ["-X", "-v", "ON_ERROR_STOP=1"],
            environment=source.env() | passwords,
            input_path=state / "bootstrap.private.sql",
            output_path=state / "bootstrap.private.log",
        )
        env = native.clean_env() | {
            "PYTHONPATH": str(native.ROOT / "backend/src"),
            "DATABASE_URL": source.url()
            .set(
                username="calorie_app_migrator",
                password=passwords["APP_MIGRATOR_PASSWORD"],
            )
            .render_as_string(hide_password=False),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        execute = lambda args, label, environment=env: private_command(
            state, args, label, environment
        )
        receipt["stage"] = "migrate_catalog"
        execute(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                native.ROOT / "backend/alembic.ini",
                "upgrade",
                "head",
            ],
            "migrate",
        )
        seed = native.ROOT / "backend/data/demo/seed.json"
        execute(
            [
                sys.executable,
                "-m",
                "calorie_app.modules.catalog.cli",
                "import",
                "--input",
                seed,
            ],
            "catalog-import",
        )
        execute(
            [
                sys.executable,
                "-m",
                "calorie_app.modules.catalog.cli",
                "export",
                "--package-id",
                "47bdff67-e58b-5437-919b-ec00159afbc5",
                "--release",
                "1",
                "--output",
                source.state / "catalog",
            ],
            "catalog-export",
        )
        receipt["stage"] = "offline_keycloak_import"
        kc = state / "keycloak-home"
        shutil.copytree(keycloak_home, kc, ignore=shutil.ignore_patterns("data"))
        realm = json.loads(
            (native.ROOT / "infra/local/keycloak/realm.json").read_text()
        )
        realm["users"] = [
            {
                "username": "restore-" + name,
                "enabled": True,
                "email": f"restore-{name}@invalid.example",
                "emailVerified": True,
                "credentials": [
                    {
                        "type": "password",
                        "value": secrets.token_hex(32),
                        "temporary": False,
                    }
                ],
            }
            for name in ("a", "b")
        ]
        native.write_json(state / "realm.private.json", realm)
        kcenv = native.clean_env() | {
            "JAVA_HOME": str(java_home),
            "KC_DB": "postgres",
            "KC_DB_URL": f"jdbc:postgresql://127.0.0.1:{source.port}/keycloak",
            "KC_DB_USERNAME": "keycloak",
            "KC_DB_PASSWORD": passwords["KEYCLOAK_DB_PASSWORD"],
            "JAVA_OPTS_KC_HEAP": "-Xms64m -Xmx512m",
            "KC_HTTP_ENABLED": "false",
        }
        execute(
            [kc / "bin/kc.bat", "import", "--file", state / "realm.private.json"],
            "keycloak-import",
            kcenv,
        )
        execute([java_home / "bin/java.exe", "--version"], "java-version", kcenv)
        receipt["runtime"]["java_version"] = (
            (state / "java-version.private.log").read_text().splitlines()[0]
        )
        subjects = json.loads(
            source.sql(
                "keycloak",
                "SELECT json_object_agg(username,id) FROM user_entity WHERE username LIKE 'restore-%';",
            )
        )
        if set(subjects) != {"restore-a", "restore-b"}:
            raise ValueError("Real imported identity cohort differs")
        engine = create_engine(source.url(), hide_parameters=True)
        receipt["stage"] = "prepare_service_oracle"
        scenario = restore_oracle.prepare(
            engine,
            "https://restore.invalid/realms/calorie-dev",
            subjects["restore-a"],
            deleted_subject=subjects["restore-b"],
            witness_directory=state / "external-witness",
        )
        native.write_json(state / "scenario-before.private.json", scenario)
        engine.dispose()
        receipt["stage"] = "capture_pair"
        source.seal()
        manifest = restore.capture(source, state / "paired-backup")
        receipt["stage"] = "post_backup_accepted_meal"
        scenario = restore_oracle.after_capture(engine, scenario)
        native.write_json(state / "scenario-after.private.json", scenario)
        engine.dispose()
        source.offline()
        source.stop()
        receipt["source_stopped"] = {
            "owner": source.config["owner"],
            "process": source.config["process"],
            "identity_revalidated": True,
        }
        clusters.remove(source)
        receipt["stage"] = "restore_pair_new_target"
        checkpoint = state / "trusted-checkpoint.private.json"
        checkpoint_sha = restore_trust.write_checkpoint(checkpoint, manifest, scenario)
        target, paired = restore.restore(
            state / "paired-backup",
            state / "target",
            pg_bin,
            free_port(),
            checkpoint=checkpoint,
            checkpoint_sha256=checkpoint_sha,
        )
        clusters.append(target)
        engine = create_engine(target.url(), hide_parameters=True)
        receipt["stage"] = "verify_service_and_ledger_oracles"
        checks = restore_oracle.verify(engine, scenario)
        native.write_json(state / "scenario-final.private.json", scenario)
        engine.dispose()
        source_files = {
            p.relative_to(source.state / "catalog").as_posix(): digest(p)
            for p in (source.state / "catalog").rglob("*")
            if p.is_file()
        }
        restored_files = {
            p.relative_to(target.state / "catalog-restored/catalog").as_posix(): digest(
                p
            )
            for p in (target.state / "catalog-restored/catalog").rglob("*")
            if p.is_file()
        }
        if not source_files or source_files != restored_files:
            raise ValueError("Catalog file cohort differs")
        finish_checks(
            receipt,
            binding,
            paired=paired,
            service_checks=checks,
            catalog_files=source_files,
            manifest_sha256=digest(state / "paired-backup/manifest.json"),
            app_accounts=manifest["accounts"],
            keycloak_identities=manifest["identities"],
        )
    except Exception as error:
        receipt["result"] = "FAIL"
        receipt["error_kind"] = type(error).__name__
        native.private_write(state / "failure.private.log", traceback.format_exc())
        raise
    finally:
        if engine is not None:
            engine.dispose()
        cleanup_errors = stop_owned_clusters(clusters, receipt)
        receipt["ended_at"] = datetime.now(UTC).isoformat()
        native.write_json(state / "execution.json", receipt)
        if cleanup_errors:
            raise RuntimeError(
                "Owned cluster cleanup failed; inspect execution receipt"
            )
    return receipt


def private_command(state, arguments, label, environment):
    with (state / (label + ".private.log")).open("wb") as output:
        result = subprocess.run(
            list(map(str, arguments)),
            env=environment,
            cwd=native.ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            timeout=300,
            check=False,
            **native.FLAGS,
        )
    if result.returncode:
        raise RuntimeError(f"{label} failed; inspect private log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("state", "pg-bin", "keycloak-home", "java-home"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.state, args.pg_bin, args.keycloak_home, args.java_home)
    print(json.dumps({"result": result["result"], "full_ko32": False, "google_io": 0}))


if __name__ == "__main__":
    main()
