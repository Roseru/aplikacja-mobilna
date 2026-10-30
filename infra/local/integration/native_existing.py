"""Explicit existing-only Native capture/lifecycle; no provision/migrate/import.

Operator-only: these functions are not run by importing this module. Each public
operation owns one native.lock. OLD-code stop receipts come from the external
tools/native_stop_bridge.py runner BEFORE this module is integrated.
"""

import argparse
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

from . import native  # isort: skip
from backup import digest, execute, private_directory

from . import restore

CONFIG_FILES = (
    "native.json",
    "config.json",
    "postgres.env",
    "api.env",
    "migrate.env",
    "worker.env",
    "keycloak.env",
    "credentials.json",
    "tls/ca.pem",
    "tls/server.pem",
    "tls/server.key",
)
SEALED_HBA = (
    b"host all postgres 127.0.0.1/32 scram-sha-256\n"
    b"host all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n"
)
SERVICE_HBA = (
    b"host all postgres 127.0.0.1/32 scram-sha-256\n"
    b"host all calorie_app_api 127.0.0.1/32 scram-sha-256\n"
    b"host all keycloak 127.0.0.1/32 scram-sha-256\n"
    b"host all all 0.0.0.0/0 reject\nhost all all ::0/0 reject\n"
)
RUNNING_HBA = SERVICE_HBA.replace(
    b"host all all 0.0.0.0/0 reject",
    b"host all calorie_app_worker 127.0.0.1/32 scram-sha-256\nhost all all 0.0.0.0/0 reject",
)
PG_TOOLS = (
    "initdb",
    "pg_ctl",
    "postgres",
    "psql",
    "pg_dump",
    "pg_dumpall",
    "pg_restore",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(path, expected):
    path = restore.owned_path(path)
    restore.check_tree(path)
    raw = path.read_bytes()
    require(
        isinstance(expected, str)
        and re.fullmatch(r"[0-9a-f]{64}", expected)
        and sha(raw) == expected,
        "External receipt pin differs",
    )
    return json.loads(raw)


def write_new(path, value):
    require(not path.exists(), "Existing receipt preserved")
    encoded = json.dumps(value, indent=2) + "\n"
    native.private_write(path, encoded)
    return {"path": str(path), "sha256": sha(encoded.encode())}


def operation_directory(stack):
    path = stack.state / "existing-lifecycle" / uuid4().hex
    private_directory(path)
    return path


def stack_at(state):
    state = restore.owned_path(state)
    restore.check_tree(state)
    stack = native.Native(state)
    require(
        type(stack.config["pg_port"]) is int and 1024 <= stack.config["pg_port"] <= 65535,
        "Invalid PG port",
    )
    require(
        (state / "postgres/PG_VERSION").read_text().strip() == "17",
        "Existing PG17 required",
    )
    require(
        Path(stack.python).resolve() == Path(sys.executable).resolve(),
        "Configured qualified Python required",
    )
    return stack


def env_bytes(raw):
    values = {}
    for line in raw.decode("utf-8").splitlines():
        key, separator, value = line.partition("=")
        require(
            separator and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) and key not in values,
            "Invalid or duplicate environment field",
        )
        values[key] = value
    return values


def runtime_env(stack, files, name):
    env = stack.env() | env_bytes(files[name + ".env"])
    require(
        name != "api" or (env.get("AI_PROVIDER") == "mock" and not env.get("GEMINI_API_KEY")),
        "Only mock AI is authorized",
    )
    return env


def hold_bootstrap(pg):
    raw = (pg.state / "password.private").read_bytes()
    require(re.fullmatch(rb"[0-9a-f]{64}\n", raw), "Target bootstrap password format differs")
    pg.env = lambda: (
        native.clean_env() | {"PGPASSWORD": raw.decode().strip(), "PGCLIENTENCODING": "UTF8"}
    )
    return raw


def cohort(stack):
    names = list(CONFIG_FILES)
    if (stack.state / "config-generation/provider-profile.json").exists():
        names.append("config-generation/provider-profile.json")
    data = {name: (stack.state / name).read_bytes() for name in names}
    require(json.loads(data["native.json"]) == stack.config, "Native configuration changed")
    require(
        json.loads(data["config.json"])
        == {k: stack.config[k] for k in ("host", "port", "origin", "project")},
        "Shared configuration changed",
    )
    return data


def runtime_binaries(stack):
    return {
        name: digest(path)
        for name, path in {
            "postgres": stack.pg / "postgres.exe",
            "python": Path(stack.python),
            "java": Path(stack.config["java_home"]) / "bin/java.exe",
            "keycloak_bootstrap": stack.state / "keycloak/lib/quarkus-run.jar",
            "keycloak_launcher": stack.state / "keycloak/bin/kc.bat",
            **{"pgtool:" + name: stack.pg / (name + ".exe") for name in PG_TOOLS},
        }.items()
    }


def pinned_cohort(stack, hashes):
    data = cohort(stack)
    require(set(hashes) == set(data), "Configuration cohort members differ")
    require(
        all(sha(raw) == hashes[name] for name, raw in data.items()),
        "Configuration cohort changed",
    )
    return data  # Consumers copy these held bytes, never reopen the original.


def absent(record):
    try:
        return native.identity(record["pid"]) != record
    except ProcessLookupError:
        return True


def database_facts(pg):
    return json.loads(
        pg.sql(
            "calorie_app",
            "SELECT json_build_object('data',current_setting('data_directory'),"
            "'port',inet_server_port(),'listen',current_setting('listen_addresses'),"
            "'epoch',(SELECT sync_epoch FROM app.installation_state),"
            "'revision',(SELECT version_num FROM app.alembic_version),"
            "'sessions',(SELECT count(*) FROM app.sync_sessions),"
            "'ai',(SELECT dispatch_open FROM app.ai_controls),"
            "'closed_at',(SELECT closed_at FROM app.ai_controls),"
            "'nemesis',(SELECT enabled FROM app.nemesis_control));",
        )
    )


class NativePG:
    """Original Native PG transport: never creates an OwnedPG owner marker."""

    def __init__(self, stack, record, files):
        self.stack, self.state = stack, stack.state
        self.files = files
        self.pg, self.port, self.user = stack.pg, stack.config["pg_port"], "postgres"
        self.data, self.process = self.state / "postgres", record

    def env(self):
        return self.stack.env() | {
            "PGPASSWORD": env_bytes(self.files["postgres.env"])["POSTGRES_PASSWORD"]
        }

    def command(self, name, args, *, input_path=None, output_path=None):
        require(name in {"psql", "pg_dump", "pg_dumpall"}, "Existing-only capture PG command")
        return execute(
            self.state,
            [str(self.pg / (name + ".exe")), *map(str, args)],
            input_path=input_path,
            output_path=output_path,
            environment=self.env(),
        )

    def connection(self, database):
        require(database in (*restore.DATABASES, "postgres"), "Unexpected database")
        return [
            "-h",
            "127.0.0.1",
            "-p",
            str(self.port),
            "-U",
            "postgres",
            "-d",
            database,
        ]

    def sql(self, database, statement):
        path = self.state / ("existing-sql-" + uuid4().hex + ".private")
        native.private_write(path, statement)
        try:
            return (
                self.command(
                    "psql",
                    self.connection(database) + ["-X", "-qAt", "-v", "ON_ERROR_STOP=1"],
                    input_path=path,
                )
                .decode()
                .strip()
            )
        finally:
            path.unlink()

    def qualify(self):
        require(
            native.identity(self.process["pid"]) == self.process,
            "Native PG process identity changed",
        )
        require(
            Path(self.process["executable"]).resolve() == (self.pg / "postgres.exe").resolve(),
            "Native PG executable differs",
        )
        pid = (self.data / "postmaster.pid").read_text().splitlines()
        require(
            int(pid[0]) == self.process["pid"]
            and Path(pid[1]).resolve() == self.data.resolve()
            and int(pid[3]) == self.port,
            "Native postmaster binding differs",
        )
        facts = database_facts(self)
        require(
            Path(facts["data"]).resolve() == self.data.resolve()
            and facts["port"] == self.port
            and facts["listen"] == "127.0.0.1"
            and facts["revision"] == restore.EXPECTED_REVISION,
            "Native SQL target/schema differs",
        )
        return facts


def zero_clients(pg):
    require(
        pg.sql(
            "postgres",
            "SELECT count(*) FROM pg_stat_activity WHERE "
            "backend_type='client backend' AND pid<>pg_backend_pid();",
        )
        == "0",
        "Other PG clients remain",
    )


def stop_services(stack, binding):
    stopped = {}
    processes = binding["processes"]
    for name in ("gateway", "worker", "keycloak"):
        path = stack.state / (name + ".process.json")
        record = json.loads(path.read_bytes())
        require(
            record == processes[path.name] and native.identity(record["pid"]) == record,
            "Service marker/identity changed",
        )
        if name == "worker":
            stopped[name] = stack.stop_worker(binding)
            require(stopped[name]["result"] == "STOPPED", "Worker exit is unknown; capture refused")
            continue
        native.terminate(record)  # Existing exact-identity checked owned-tree stop.
        require(absent(record), "Service remains after checked stop")
        path.unlink()
        stopped[name] = record
    return stopped


class NativeCaptureSource(NativePG):
    """Admitted running Native source, qualified before any stop/HBA mutation."""

    def __init__(self, stack, expected_generation):
        require(not (stack.state / "owner.json").exists(), "Original Native source required")
        binding = stack.require_running()
        require(binding["generation"] == expected_generation, "Native generation differs")
        UUID(expected_generation)
        require(
            binding.get("binary_sha256") == runtime_binaries(stack),
            "Capture runtime binaries changed",
        )
        require(
            binding["lifecycle"]["kind"] == "source"
            and (stack.state / "postgres/pg_hba.conf").read_bytes().hex()
            == binding["lifecycle"]["original_hba_hex"],
            "Original source HBA changed",
        )
        files = cohort(stack)
        require(
            binding.get("configuration_files") == {name: sha(raw) for name, raw in files.items()},
            "Capture needs the existing-only qualified configuration cohort",
        )
        super().__init__(stack, binding["processes"]["postgres.process.json"], files)
        self.binding = binding
        self.facts = self.qualify()
        self.catalog = restore.owned_path(runtime_env(stack, files, "api")["CATALOG_ARTIFACT_ROOT"])
        require(self.catalog == stack.state / "catalog", "Original Native catalog differs")
        restore.check_tree(self.catalog)
        self.binaries = {
            name + ".exe": {"sha256": digest(self.pg / (name + ".exe"))} for name in PG_TOOLS
        }

    def capture_identity(self):
        return restore.CaptureIdentity(
            self.binding["generation"],
            self.binaries,
            self.process,
            {"kind": "native-runtime", "binding": self.binding},
        )

    def offline(self):
        self.qualify()
        require(
            native.source(self.stack.config["source"]["commit"]) == self.binding["source"],
            "Capture source changed",
        )
        require((self.data / "pg_hba.conf").read_bytes() == SEALED_HBA, "Source not sealed")
        require(
            not any(
                (self.state / (n + ".process.json")).exists()
                for n in ("gateway", "worker", "keycloak")
            ),
            "Source services remain",
        )
        zero_clients(self)


def capture_native(state, expected_generation, destination):
    stack = stack_at(state)
    destination = restore.owned_path(destination)
    restore.disjoint(stack.state, destination)
    require(not destination.exists(), "Existing archive preserved")
    with stack.operation():
        source = NativeCaptureSource(stack, expected_generation)
        files = source.files
        hba = (source.data / "pg_hba.conf").read_bytes()
        folder = operation_directory(stack)
        for name, raw in files.items():
            path = folder / "configuration" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        receipt = {
            "format": "native-existing-capture/v1",
            "kind": "source",
            "state": str(stack.state),
            "result": "FAIL",
            "runtime": source.binding,
            "configuration_files": {name: sha(raw) for name, raw in files.items()},
            "configuration_directory": str(folder / "configuration"),
            "keycloak_software": software_hashes(stack.state / "keycloak"),
            "qualified_binary_hashes": runtime_binaries(stack),
            "original_hba_hex": hba.hex(),
            "original_hba_sha256": sha(hba),
            "control_identity": (source.data / "global/pg_control").read_bytes()[:8].hex(),
        }
        # Preserve original HBA before the first mutating action, including failures.
        write_new(folder / "admission.private.json", receipt)
        try:
            require(
                stack.require_running() == source.binding,
                "Generation changed before seal",
            )
            source.binding["state"] = "QUIESCING"
            publish(stack, source.binding)
            receipt["service_stops"] = stop_services(stack, source.binding)
            (source.data / "pg_hba.conf").write_bytes(SEALED_HBA)
            require(source.sql("postgres", "SELECT pg_reload_conf();") == "t", "HBA reload failed")
            source.offline()
            receipt["database"] = database_facts(source)
            captured = restore._capture_locked(source, destination)
            receipt.update(result="SEALED", capture=captured, sealed_hba_sha256=sha(SEALED_HBA))
            handoff = write_new(folder / "capture.private.json", receipt)
            binding = source.binding | {
                "state": "CAPTURE_SEALED",
                "processes": {"postgres.process.json": source.process},
                "sealed_capture": handoff,
            }
            native.write_json(stack.state / "runtime-binding.json", binding)
            return {"capture": captured, "handoff": handoff}
        except BaseException:
            publish(stack, source.binding | {"state": "CAPTURE_FAILED"})
            write_new(folder / "failed.private.json", receipt)
            raise


def software_hashes(root):
    restore.check_tree(root)
    return {
        p.relative_to(root).as_posix(): digest(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0] not in {"data", "logs"}
    }


def source_handoff(stack, receipt, reference):
    require(not (stack.state / "owner.json").exists(), "Original source marker required")
    require(
        receipt["kind"] == "source" and receipt["state"] == str(stack.state),
        "Foreign source handoff",
    )
    require(
        receipt["format"] in {"native-existing-stop/v1", "native-existing-capture/v1"}
        and receipt["result"] in {"STOPPED", "SEALED"},
        "Incomplete source handoff",
    )
    UUID(receipt["runtime"]["generation"])
    files = pinned_cohort(stack, receipt["configuration_files"])
    expected_binaries = receipt.get("qualified_binary_hashes")
    if expected_binaries is None:
        old = receipt["qualified_runtime"]["binary_sha256"]
        expected_binaries = {name: old[name] for name in runtime_binaries(stack)}
    require(runtime_binaries(stack) == expected_binaries, "Source runtime binaries changed")
    hba = bytes.fromhex(receipt["original_hba_hex"])
    require(sha(hba) == receipt["original_hba_sha256"], "Original HBA pin differs")
    database = receipt["database"]
    require(
        Path(database["data"]).resolve() == (stack.state / "postgres").resolve()
        and database["port"] == stack.config["pg_port"]
        and database["revision"] == restore.EXPECTED_REVISION,
        "Source handoff DB differs",
    )
    UUID(database["epoch"])
    require(
        (stack.state / "postgres/global/pg_control").read_bytes()[:8].hex()
        == receipt["control_identity"],
        "Source physical cluster identity changed",
    )
    current = json.loads((stack.state / "runtime-binding.json").read_bytes())
    if receipt["result"] == "STOPPED":
        require(
            receipt["pg_stop"]["exit_code"] == 0
            and receipt["actual_markers_absent"]
            and receipt["process_identities_absent"],
            "Incomplete stop proof",
        )
        require(
            current == receipt["runtime"] | {"state": "STOPPED"},
            "Stopped binding differs",
        )
        require(
            not list(stack.state.glob("*.process.json"))
            and not (stack.state / "postgres/postmaster.pid").exists(),
            "Stopped source has processes",
        )
        require(
            all(absent(p) for p in receipt["runtime"]["processes"].values()),
            "Previous source process remains",
        )
        require(
            sha((stack.state / "postgres/pg_hba.conf").read_bytes())
            == receipt.get("stopped_hba_sha256", receipt["original_hba_sha256"]),
            "Source HBA changed",
        )
        return hba, None, files
    process = receipt["runtime"]["processes"]["postgres.process.json"]
    require(
        current
        == receipt["runtime"]
        | {
            "state": "CAPTURE_SEALED",
            "processes": {"postgres.process.json": process},
            "sealed_capture": reference,
        },
        "Captured binding differs",
    )
    require(
        {p.name for p in stack.state.glob("*.process.json")} == {"postgres.process.json"},
        "Captured source service markers differ",
    )
    require(
        json.loads((stack.state / "postgres.process.json").read_bytes()) == process,
        "Captured PG marker differs",
    )
    pg = NativePG(stack, process, files)
    facts = pg.qualify()
    require(facts["epoch"] == database["epoch"], "Captured source epoch changed")
    require((pg.data / "pg_hba.conf").read_bytes() == SEALED_HBA, "Captured HBA changed")
    zero_clients(pg)
    return hba, pg, files


def target_pg(stack, descriptor, files=None):
    require(
        descriptor["kind"] == "target" and descriptor["state"] == str(stack.state),
        "Foreign target binding",
    )
    pg = restore.OwnedPG(stack.state)
    password = hold_bootstrap(pg)
    require(
        {k: v for k, v in stack.config.items() if k != "source"} == descriptor["native_base"],
        "Target service state/config differs",
    )
    files = cohort(stack) if files is None else files
    target_files = {name: raw for name, raw in files.items() if name != "native.json"}
    require(
        {name: sha(raw) for name, raw in target_files.items()} == descriptor["configuration_files"],
        "Target service credential/CA cohort differs",
    )
    require(
        pg.config["owner"] == descriptor["owner"] and pg.port == stack.config["pg_port"],
        "OwnedPG target differs",
    )
    receipt = read_pinned(
        descriptor["restore_receipt"]["path"], descriptor["restore_receipt"]["sha256"]
    )
    require(
        receipt["result"] == "PASS"
        and receipt["paired_restore"]
        and receipt["external_evidence_validated_before_target_create"],
        "Unqualified restore receipt",
    )
    require(
        env_bytes(target_files["postgres.env"])["POSTGRES_PASSWORD"] == password.decode().strip(),
        "Target bootstrap password differs",
    )
    return pg, receipt, files


def descends_from_capture(stop, capture_sha256):
    reference = stop["runtime"]["parent"]
    require(reference == stop["parent_handoff"], "Stop parent/runtime binding differs")
    seen = set()
    for _ in range(32):
        require(reference["sha256"] not in seen, "Cyclic generation ancestry")
        seen.add(reference["sha256"])
        parent = read_pinned(reference["path"], reference["sha256"])
        require(
            parent["state"] == stop["state"] and parent["kind"] == "source",
            "Foreign generation ancestor",
        )
        if reference["sha256"] == capture_sha256:
            require(
                parent["format"] == "native-existing-capture/v1" and parent["result"] == "SEALED",
                "Invalid capture ancestor",
            )
            return
        require(
            parent["format"] == "native-existing-stop/v1" and parent["result"] == "STOPPED",
            "Missing capture ancestor",
        )
        reference = parent["runtime"]["parent"]
        require(reference == parent["parent_handoff"], "Ancestor parent/runtime differs")
    raise ValueError("Bounded generation ancestry exceeded")


def bind_target(
    state,
    *,
    capture_path,
    capture_sha256,
    source_stop_path,
    source_stop_sha256,
    restore_receipt_sha256,
):
    """Materialize target service config from the pinned T0 cohort, never prepare()."""
    state = restore.owned_path(state)
    pg = restore.OwnedPG(state)
    password = hold_bootstrap(pg)
    capture = read_pinned(capture_path, capture_sha256)
    source_stop = read_pinned(source_stop_path, source_stop_sha256)
    restored = read_pinned(state / "receipt.json", restore_receipt_sha256)
    require(
        capture["format"] == "native-existing-capture/v1" and capture["result"] == "SEALED",
        "Qualified capture required",
    )
    require(
        source_stop["format"] == "native-existing-stop/v1"
        and source_stop["kind"] == "source"
        and source_stop["result"] == "STOPPED"
        and source_stop["state"] == capture["state"],
        "Source stop does not match capture",
    )
    require(
        source_stop["pg_stop"]["exit_code"] == 0
        and source_stop["actual_markers_absent"]
        and source_stop["process_identities_absent"],
        "Source stop incomplete",
    )
    require(
        source_stop.get("capture_sha256") == capture_sha256
        and source_stop["database"]["epoch"] == capture["database"]["epoch"]
        and source_stop["configuration_files"] == capture["configuration_files"],
        "Source stop/capture generation cohort differs",
    )
    descends_from_capture(source_stop, capture_sha256)
    source = restore.owned_path(capture["state"])
    restore.disjoint(source, state)
    require(
        not (source / "postgres/postmaster.pid").exists()
        and not list(source.glob("*.process.json"))
        and all(absent(p) for p in source_stop["runtime"]["processes"].values()),
        "Original issuer/source still active",
    )
    require(
        json.loads((source / "runtime-binding.json").read_bytes())
        == source_stop["runtime"] | {"state": "STOPPED"},
        "Source stopped binding changed",
    )
    require(
        restored["result"] == "PASS"
        and restored["paired_restore"]
        and restored["external_evidence_validated_before_target_create"]
        and restored["archive_manifest_sha256"] == capture["capture"]["trusted_manifest_sha256"]
        and restored["source_epoch"] == capture["database"]["epoch"],
        "Target receipt/capture mismatch",
    )
    require(
        not (state / "native.json").exists()
        and not (state / "existing-target.private.json").exists(),
        "Existing service configuration preserved",
    )
    require(
        not any((state / name).exists() for name in CONFIG_FILES)
        and not (state / "keycloak").exists()
        and not (state / "photos").exists()
        and not (state / "config-generation").exists(),
        "Existing target service member preserved",
    )
    frozen = restore.owned_path(capture["configuration_directory"])
    require(
        frozen == restore.owned_path(capture_path).parent / "configuration"
        and frozen.parent.parent == source / "existing-lifecycle",
        "Frozen configuration handoff location differs",
    )
    require(
        set(capture["configuration_files"])
        in (
            set(CONFIG_FILES),
            set(CONFIG_FILES) | {"config-generation/provider-profile.json"},
        ),
        "Unexpected configuration members",
    )
    restore.check_tree(frozen)
    data = {name: (frozen / name).read_bytes() for name in capture["configuration_files"]}
    require(
        all(sha(raw) == capture["configuration_files"][name] for name, raw in data.items()),
        "Frozen configuration changed",
    )
    config = json.loads(data["native.json"])
    require(config["state"] == str(source), "Frozen Native configuration differs")
    software = capture["keycloak_software"]
    require(
        software and software_hashes(source / "keycloak") == software,
        "Qualified Keycloak software changed",
    )
    require((state / "catalog-restored/catalog").is_dir(), "Restored catalog missing")
    restore.check_tree(state / "catalog-restored")
    with pg.operation():
        pg.qualify()
        facts = database_facts(pg)
        require(
            facts["epoch"] == restored["restored_epoch"]
            and facts["ai"] is False
            and facts["nemesis"] is False
            and facts["sessions"] == 0,
            "Target gates/epoch differ",
        )
        require(
            (pg.data / "pg_hba.conf").read_bytes() == SEALED_HBA,
            "Target must remain sealed",
        )
        folder = operation_directory(type("State", (), {"state": state})())
        for name, pin in software.items():
            path = Path(name)
            require(
                not path.is_absolute() and ".." not in path.parts,
                "Unsafe software member",
            )
            destination = folder / "keycloak" / path
            destination = restore.owned_path(destination)
            require(destination.is_relative_to(folder / "keycloak"), "Software escaped staging")
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw = (source / "keycloak" / path).read_bytes()
            require(sha(raw) == pin, "Software changed during materialization")
            destination.write_bytes(raw)
            require(digest(destination) == pin, "Copied software differs")
        config.update(state=str(state), pg_port=pg.port, pg_bin=str(pg.pg))
        derived = {}
        for name, raw in data.items():
            if name in {"native.json", "postgres.env"}:
                continue
            if name.endswith(".env"):
                values = env_bytes(raw)
                values = {
                    key: value.replace(
                        f"127.0.0.1:{json.loads(data['native.json'])['pg_port']}",
                        f"127.0.0.1:{pg.port}",
                    )
                    for key, value in values.items()
                }
                if name == "api.env":
                    values.update(
                        CATALOG_ARTIFACT_ROOT=(state / "catalog-restored/catalog").as_posix(),
                        AI_PHOTO_ROOT=(state / "photos").as_posix(),
                        OIDC_CA_BUNDLE=(state / "tls/ca.pem").as_posix(),
                    )
                raw = (
                    "\n".join(key + "=" + value for key, value in values.items()) + "\n"
                ).encode()
            path = folder / "config" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            derived[name] = raw
        require(
            re.fullmatch(rb"[0-9a-f]{64}\n", password),
            "Target bootstrap password format differs",
        )
        postgres = env_bytes(data["postgres.env"])
        postgres["POSTGRES_PASSWORD"] = password.decode().strip()
        derived["postgres.env"] = (
            "\n".join(key + "=" + value for key, value in postgres.items()) + "\n"
        ).encode()
        derived["native.json"] = (json.dumps(config, indent=2) + "\n").encode()
        for name in ("postgres.env", "native.json"):
            (folder / "config" / name).write_bytes(derived[name])
        require(not (state / "keycloak").exists(), "Existing target software preserved")
        shutil.move(str(folder / "keycloak"), str(state / "keycloak"))
        for path in sorted((folder / "config").rglob("*")):
            if path.is_file():
                destination = state / path.relative_to(folder / "config")
                require(not destination.exists(), "Existing target configuration member")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(destination))
        (state / "photos").mkdir()
        require(
            all(sha((state / name).read_bytes()) == sha(raw) for name, raw in derived.items()),
            "Materialized configuration changed",
        )
        descriptor = {
            "format": "native-existing-target/v1",
            "kind": "target",
            "state": str(state),
            "owner": pg.config["owner"],
            "source_state": str(source),
            "source_stop": {
                "path": str(source_stop_path),
                "sha256": source_stop_sha256,
            },
            "capture": {"path": str(capture_path), "sha256": capture_sha256},
            "restore_receipt": {
                "path": str(state / "receipt.json"),
                "sha256": restore_receipt_sha256,
            },
        }
        descriptor["native_base"] = {k: v for k, v in config.items() if k != "source"}
        descriptor["qualified_binary_hashes"] = capture["qualified_binary_hashes"] | {
            "postgres": pg.config["binaries"]["postgres.exe"]["sha256"],
            **{
                "pgtool:" + name: pg.config["binaries"][name + ".exe"]["sha256"]
                for name in PG_TOOLS
            },
        }
        descriptor["configuration_files"] = {
            name: sha(raw) for name, raw in derived.items() if name != "native.json"
        }
        return write_new(state / "existing-target.private.json", descriptor)


def code_binding(pin, expected_sha256):
    binding = native.source(pin)
    require(
        sha(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()) == expected_sha256,
        "Reviewed new source binding differs",
    )
    return binding


def publish(stack, binding):
    # Only genuine current process markers enter a new runtime generation.
    binding["processes"] = {
        p.name: json.loads(p.read_bytes()) for p in stack.state.glob("*.process.json")
    }
    native.write_json(stack.state / "runtime-binding.json", binding)


def launch_services(stack, binding, files):
    env = runtime_env(stack, files, "keycloak") | {
        "JAVA_HOME": stack.config["java_home"],
        "PATH": str(Path(stack.config["java_home"]) / "bin")
        + os.pathsep
        + os.environ.get("PATH", ""),
        "JAVA_OPTS_KC_HEAP": "-Xms64m -Xmx512m",
        "KC_LOG_LEVEL": (
            "info,org.keycloak.events:off,org.keycloak.protocol.oidc.utils.OAuth2CodeParser:off"
        ),
    }
    stack.launch(
        "keycloak",
        [
            str(stack.state / "keycloak/bin/kc.bat"),
            "start-dev",
            "--http-host=127.0.0.1",
            f"--http-port={stack.config['keycloak_port']}",
            f"--http-management-port={stack.config['management_port']}",
            "--spi-connections-jpa--quarkus--migration-strategy=validate",
            "--spi-connections-jpa--quarkus--initialize-empty=false",
        ],
        env,
    )
    publish(stack, binding)
    stack.launch(
        "gateway",
        [stack.python, "-m", "infra.local.integration.live_restore", "serve"],
        runtime_env(stack, files, "api") | {"RESTORE_MAINTENANCE": "1"},
    )
    publish(stack, binding)


def start_existing(state, handoff_path, handoff_sha256, *, source_pin, source_sha256):
    """Start in maintenance only; never initialize an absent or foreign PG."""
    stack = stack_at(state)
    handoff = read_pinned(handoff_path, handoff_sha256)
    new_source = code_binding(source_pin, source_sha256)
    reference = {"path": str(handoff_path), "sha256": handoff_sha256}
    with stack.operation():
        kind = handoff["kind"]
        if kind == "source":
            hba, pg, files = source_handoff(stack, handoff, reference)
            expected_epoch, expected_sessions = handoff["database"]["epoch"], None
            capture_sha = (
                handoff_sha256 if handoff["result"] == "SEALED" else handoff.get("capture_sha256")
            )
        else:
            require(
                kind == "target"
                and handoff["format"] in {"native-existing-target/v1", "native-existing-stop/v1"},
                "Unknown lifecycle handoff",
            )
            descriptor = handoff
            stopped = handoff["format"] == "native-existing-stop/v1"
            if stopped:
                require(
                    handoff["result"] == "STOPPED"
                    and handoff.get("automatic_resume_authorized", True),
                    "Cleanup handoff is not eligible for automatic resume",
                )
                reference = handoff["target_binding"]
                descriptor = read_pinned(reference["path"], reference["sha256"])
                require(
                    handoff["state"] == str(stack.state)
                    and handoff["result"] == "STOPPED"
                    and handoff["pg_stop"]["exit_code"] == 0
                    and handoff["actual_markers_absent"]
                    and handoff["process_identities_absent"],
                    "Target stop handoff incomplete",
                )
                pinned_cohort(stack, handoff["configuration_files"])
                require(
                    json.loads((stack.state / "runtime-binding.json").read_bytes())
                    == handoff["runtime"] | {"state": "STOPPED"},
                    "Target stopped generation differs",
                )
            else:
                require(
                    not (stack.state / "runtime-binding.json").exists(),
                    "Target needs its current stop handoff",
                )
            pg, receipt, files = target_pg(stack, descriptor)
            verify_source_stopped(descriptor)
            require(
                runtime_binaries(stack) == descriptor["qualified_binary_hashes"],
                "Target runtime binaries changed",
            )
            require(
                not list(stack.state.glob("*.process.json")), "Existing target markers preserved"
            )
            require(stopped == (pg.config["status"] == "STOPPED"), "Target PG/stop state differs")
            if stopped:
                require(
                    handoff["runtime"]["processes"]["postgres.process.json"] == pg.config["process"]
                    and absent(pg.config["process"])
                    and not (pg.data / "postmaster.pid").exists(),
                    "Target stop receipt differs",
                )
                require(
                    (pg.data / "global/pg_control").read_bytes()[:8].hex()
                    == handoff["control_identity"],
                    "Target physical cluster identity changed",
                )
            else:
                require(pg.config["status"] in {"RUNNING", "SEALED"}, "Target PG state differs")
            require(
                sha((pg.data / "pg_hba.conf").read_bytes())
                == (handoff["stopped_hba_sha256"] if stopped else sha(SEALED_HBA)),
                "Target admission HBA differs",
            )
            expected_epoch = receipt["restored_epoch"]
            expected_sessions = handoff["database"]["sessions"] if stopped else 0
            hba, capture_sha = SERVICE_HBA, descriptor["capture"]["sha256"]
        require(
            not any(
                (stack.state / (n + ".process.json")).exists() for n in ("keycloak", "gateway")
            ),
            "Existing services preserved",
        )
        pg_started = pg is None or (kind == "target" and pg.config["status"] == "STOPPED")
        if not pg_started:
            validate_data(pg, kind, expected_epoch, expected_sessions)
            zero_clients(pg)
        native.available(
            "127.0.0.1", [stack.config[n] for n in ("port", "keycloak_port", "management_port")]
        )
        native.available(stack.config["host"], [stack.config["port"]])
        if pg_started:
            native.available("127.0.0.1", [stack.config["pg_port"]])
        folder = operation_directory(stack)
        stack.config["source"] = new_source
        encoded = (json.dumps(stack.config, indent=2) + "\n").encode()
        files = files | {"native.json": encoded}
        native.private_write(stack.state / "native.json", encoded.decode())
        binding = {
            "generation": str(uuid4()),
            "state": "STARTING",
            "source": new_source,
            "configuration": stack.configuration_binding(),
            "binary_sha256": runtime_binaries(stack),
            "bootstrap_sha256": sha(env_bytes(files["postgres.env"])["POSTGRES_PASSWORD"].encode()),
            "configuration_files": {name: sha(raw) for name, raw in files.items()},
            "parent": {"path": str(handoff_path), "sha256": handoff_sha256},
        }
        control = {
            "generation": binding["generation"],
            "kind": kind,
            "original_hba_hex": hba.hex(),
            "capture_sha256": capture_sha,
            "parent_handoff": binding["parent"],
            "started_at": datetime.now(UTC).isoformat(),
            "started_monotonic": time.monotonic(),
        }
        if kind == "target":
            control["target_binding"] = reference
        binding["lifecycle"] = control
        if kind == "source":
            previous = handoff["runtime"]
            cursor_source = previous.get("retention")
            # A markerless failed launch never qualified this fresh slot. Keep
            # only the last qualified original-source cursor, or start fresh.
            if cursor_source is None or cursor_source.get("process") is None:
                cursor_source = previous.get("retention_resume")
            binding["retention_resume"] = cursor_source
        if not pg_started:
            process = pg.process if kind == "source" else pg.config["process"]
            native.write_json(stack.state / "postgres.process.json", process)
        publish(stack, binding)
        try:
            if pg_started:
                (stack.state / "postgres/pg_hba.conf").write_bytes(SEALED_HBA)
                stack.run(
                    [
                        stack.pg / "pg_ctl.exe",
                        "-D",
                        stack.state / "postgres",
                        "-l",
                        stack.state / "postgres.log",
                        "-w",
                        "start",
                    ],
                    label="existing-pg-start",
                )
                process = native.identity(
                    int((stack.state / "postgres/postmaster.pid").read_text().splitlines()[0])
                )
                require(
                    Path(process["executable"]).resolve() == (stack.pg / "postgres.exe").resolve(),
                    "Started PG executable differs",
                )
                if kind == "source":
                    pg = NativePG(stack, process, files)
                else:
                    pg.config.update(status="RUNNING", process=process)
                    native.write_json(pg.marker, pg.config)
                native.write_json(stack.state / "postgres.process.json", process)
                publish(stack, binding)
            facts = validate_data(pg, kind, expected_epoch, expected_sessions)
            (stack.state / "postgres/pg_hba.conf").write_bytes(hba)
            require(pg.sql("postgres", "SELECT pg_reload_conf();") == "t", "HBA reload failed")
            if kind == "target":
                pg.config.update(status="RUNNING", hba_sha256=sha(hba))
                native.write_json(pg.marker, pg.config)
            binding["database"] = facts
            launch_services(stack, binding, files)
            binding["state"] = "MAINTENANCE"
            publish(stack, binding)
            write_new(
                folder / "start.private.json",
                {
                    "result": "MAINTENANCE",
                    "runtime": binding,
                    "pg_started": pg_started,
                    "traffic_open": False,
                },
            )
            return {
                "generation": binding["generation"],
                "phase": "MAINTENANCE",
                "kind": kind,
                "pg_started": pg_started,
                "traffic_open": False,
            }
        except BaseException as error:
            # pg_ctl may fail after starting its child. Publish only a genuinely
            # qualified own PG record; never guess a PID or invent a stop exit.
            if (
                not (stack.state / "postgres.process.json").exists()
                and (stack.state / "postgres/postmaster.pid").exists()
            ):
                try:
                    process = native.identity(
                        int((stack.state / "postgres/postmaster.pid").read_text().splitlines()[0])
                    )
                    NativePG(stack, process, files).qualify()
                    native.write_json(stack.state / "postgres.process.json", process)
                    if kind == "target":
                        pg.config.update(status="RUNNING", process=process)
                        native.write_json(pg.marker, pg.config)
                except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                    binding["unqualified_pg_pid_file"] = True
            binding["state"] = "START_FAILED"
            publish(stack, binding)
            write_new(
                folder / "start-failed.private.json",
                {
                    "result": "FAIL",
                    "runtime": binding,
                    "error_kind": type(error).__name__,
                    "pg_started": pg_started,
                    "traffic_open": False,
                },
            )
            raise


def validate_data(pg, kind, epoch, sessions):
    pg.qualify()
    facts = database_facts(pg)
    require(
        facts["epoch"] == epoch and facts["revision"] == restore.EXPECTED_REVISION,
        "Existing data epoch/schema changed",
    )
    if kind == "target":
        require(
            facts["ai"] is False and facts["nemesis"] is False and facts["sessions"] == sessions,
            "Restored target gates/sessions differ",
        )
    return facts


def verify_source_stopped(descriptor):
    source = restore.owned_path(descriptor["source_state"])
    proof = read_pinned(descriptor["source_stop"]["path"], descriptor["source_stop"]["sha256"])
    require(
        not (source / "postgres/postmaster.pid").exists()
        and not list(source.glob("*.process.json"))
        and all(absent(p) for p in proof["runtime"]["processes"].values()),
        "Original source/issuer is not stopped",
    )
    require(
        json.loads((source / "runtime-binding.json").read_bytes())
        == proof["runtime"] | {"state": "STOPPED"},
        "Source stop generation changed",
    )


PARTIAL_PHASES = {
    "STARTING",
    "START_FAILED",
    "STOP_FAILED",
    "ACTIVATION_FAILED",
    "CAPTURE_FAILED",
    "MAINTENANCE",
    "QUIESCING",
}
CLEANUP_PHASES = PARTIAL_PHASES | {"RUNNING"}


def runtime_metadata(stack, phases):
    binding = json.loads((stack.state / "runtime-binding.json").read_bytes())
    require(binding["state"] in phases, "Existing runtime phase differs")
    require(
        binding["source"] == native.source(stack.config["source"]["commit"]),
        "Existing runtime source stale",
    )
    require(binding["binary_sha256"] == runtime_binaries(stack), "Existing runtime binaries stale")
    actual = {p.name: json.loads(p.read_bytes()) for p in stack.state.glob("*.process.json")}
    require(
        actual == binding["processes"]
        and set(actual)
        <= {
            "postgres.process.json",
            "keycloak.process.json",
            "gateway.process.json",
            "worker.process.json",
        },
        "Existing process marker set differs",
    )
    return binding, actual


def qualified_runtime(stack, phases):
    """Admission stays strict, including every live process and full config cohort."""
    binding, actual = runtime_metadata(stack, phases)
    require(
        binding["configuration"] == stack.configuration_binding(), "Existing runtime config stale"
    )
    files = cohort(stack)
    require(
        binding["configuration_files"] == {name: sha(raw) for name, raw in files.items()},
        "Existing runtime credential cohort stale",
    )
    require(
        all(native.identity(r["pid"]) == r for r in actual.values()),
        "Existing process generation differs",
    )
    if "worker.process.json" in actual:
        stack.qualify_worker(binding)
    if binding["state"] == "RUNNING":
        require(
            set(actual)
            == {n + ".process.json" for n in ("postgres", "keycloak", "gateway", "worker")},
            "Running worker missing",
        )
    return binding, files


def qualified_cleanup(stack):
    """Stop only: dead markers/drift never authorize admission or a fresh launch."""
    binding, actual = runtime_metadata(stack, CLEANUP_PHASES)
    require(
        not binding.get("retention_launch_unresolved", False) or "worker.process.json" in actual,
        "Unresolved worker launch; no safe PG stop or resume",
    )
    expected = binding["configuration_files"]
    require(
        set(expected)
        in (set(CONFIG_FILES), set(CONFIG_FILES) | {"config-generation/provider-profile.json"}),
        "Unknown configuration member",
    )
    files, drift = {}, {}
    names = set(expected)
    if (stack.state / "config-generation/provider-profile.json").exists():
        names.add("config-generation/provider-profile.json")
    for name in names:
        try:
            raw = (stack.state / name).read_bytes()
        except OSError:
            raw = None
        observed = sha(raw) if raw is not None else "UNAVAILABLE"
        if observed != expected.get(name):
            drift[name] = {"expected": expected.get(name), "observed": observed}
        else:
            files[name] = raw
        if name in {"native.json", "config.json"}:
            require(observed == expected[name], "Cleanup critical state/config differs")
        if name == "postgres.env":
            require(raw is not None, "Cleanup bootstrap unavailable")
            password = env_bytes(raw)["POSTGRES_PASSWORD"]
            if "bootstrap_sha256" in binding:
                require(
                    sha(password.encode()) == binding["bootstrap_sha256"],
                    "Cleanup bootstrap differs",
                )
            else:
                require(observed == expected[name], "Legacy cleanup bootstrap cohort differs")
            # Ignore other fields; never pass unverified env keys to a process.
            files[name] = ("POSTGRES_PASSWORD=" + password + "\n").encode()
    dead = {}
    for name, record in actual.items():
        try:
            observed = native.identity(record["pid"])
        except ProcessLookupError:
            dead[name] = record
        else:
            require(observed == record, "Live reused PID/birth/exe differs; cleanup refused")
    if "postgres.process.json" in dead:
        pidfile = stack.state / "postgres/postmaster.pid"
        require(
            not pidfile.exists()
            or int(pidfile.read_text().splitlines()[0]) == dead["postgres.process.json"]["pid"],
            "Untracked postmaster PID; cleanup refused",
        )
    if "worker.process.json" in actual:
        from .retention import descriptor

        metadata, _path = descriptor(stack, binding)
        require(
            metadata["process"] == actual["worker.process.json"], "Worker cleanup marker differs"
        )
    return binding, files, dead, drift


def stop_existing(state, expected_generation):
    stack = stack_at(state)
    with stack.operation():
        phase = json.loads((stack.state / "runtime-binding.json").read_bytes())["state"]
        dead, drift = {}, {}
        if phase in CLEANUP_PHASES:
            binding, files, dead, drift = qualified_cleanup(stack)
        else:
            binding, files = qualified_runtime(stack, {"RUNNING", "CAPTURE_SEALED"})
        require(binding["generation"] == expected_generation, "Stop generation differs")
        control = binding["lifecycle"]
        kind = control["kind"]
        pg = (
            restore.OwnedPG(stack.state)
            if kind == "target"
            else NativePG(stack, binding["processes"]["postgres.process.json"], files)
        )
        if kind == "target":
            password = hold_bootstrap(pg)
            require(
                env_bytes(files["postgres.env"])["POSTGRES_PASSWORD"] == password.decode().strip(),
                "Target bootstrap password differs",
            )
            require(
                pg.config["process"] == binding["processes"]["postgres.process.json"],
                "Target marker families differ",
            )
        pg_dead = "postgres.process.json" in dead
        if not pg_dead:
            pg.qualify()
            facts = database_facts(pg)
        else:
            facts = binding.get("database")
        folder = operation_directory(stack)
        service_stops = {}
        try:
            for name in ("gateway", "worker", "keycloak"):
                if (stack.state / (name + ".process.json")).exists():
                    record = binding["processes"][name + ".process.json"]
                    if name == "worker":
                        service_stops[name] = stack.stop_worker(binding)
                        continue
                    already_dead = name + ".process.json" in dead
                    if not already_dead:
                        native.terminate(record)
                    require(absent(record), "Service remains after stop")
                    (stack.state / (name + ".process.json")).unlink()
                    service_stops[name] = {
                        "process": record,
                        "already_dead": already_dead,
                        "termination_helper_called": not already_dead,
                        "process_exit": "UNKNOWN",
                    }
            if pg_dead:
                # Remove only our stale lifecycle marker, never the postmaster
                # PID file or a guessed process. This is not a resume handoff.
                (stack.state / "postgres.process.json").unlink()
                if kind == "target":
                    pg.config["status"] = "DEAD_UNKNOWN_EXIT"
                    native.write_json(pg.marker, pg.config)
                publish(stack, binding | {"state": "CLEANED_UNKNOWN_EXIT"})
                return write_new(
                    folder / "cleanup-unknown.private.json",
                    {
                        "format": "native-existing-stop/v1",
                        "kind": kind,
                        "state": str(stack.state),
                        "result": "CLEANED_UNKNOWN_EXIT",
                        "runtime": binding,
                        "configuration_drift": drift,
                        "service_stops": service_stops,
                        "pg_stop": {
                            "exit_code": None,
                            "process_exit": "UNKNOWN",
                            "command_attempted": False,
                        },
                        "automatic_resume_authorized": False,
                    },
                )
            zero_clients(pg)
            # Final session/data facts belong to the quiesced cohort, not to an
            # earlier request which may finish while services are stopping.
            facts = database_facts(pg)
            stack.run(
                [
                    stack.pg / "pg_ctl.exe",
                    "-D",
                    stack.state / "postgres",
                    "-w",
                    "-m",
                    "fast",
                    "stop",
                ],
                label="existing-pg-stop",
            )
            raw_stdout = (stack.state / "existing-pg-stop.log").read_bytes()
            (folder / "pg-stop.private.log").write_bytes(raw_stdout)
            require(not (stack.state / "postgres/postmaster.pid").exists(), "PG stop incomplete")
            process = binding["processes"]["postgres.process.json"]
            require(absent(process), "PG remains after stop")
            (stack.state / "postgres.process.json").unlink()
            if kind == "target":
                pg.config["status"] = "STOPPED"
                native.write_json(pg.marker, pg.config)
            worker_unknown = (
                binding.get("retention_unknown_exit", False)
                or service_stops.get("worker", {}).get("result", "STOPPED") != "STOPPED"
            )
            result = (
                "STOPPED_COHORT_DRIFT"
                if drift
                else "STOPPED_WORKER_UNKNOWN_EXIT"
                if worker_unknown
                else "STOPPED"
            )
            native.write_json(stack.state / "runtime-binding.json", binding | {"state": result})
        except BaseException as error:
            failed = binding | {"state": "STOP_FAILED"}
            publish(stack, failed)
            write_new(
                folder / "stop-failed.private.json",
                {
                    "result": "FAIL",
                    "runtime": failed,
                    "runtime_before": binding,
                    "service_stops": service_stops,
                    "error_kind": type(error).__name__,
                    "successful_stop_claim": False,
                },
            )
            raise
        receipt = {
            "format": "native-existing-stop/v1",
            "kind": kind,
            "state": str(stack.state),
            "result": result,
            "runtime": binding,
            "database": facts,
            "configuration_files": binding["configuration_files"],
            "configuration_drift": drift,
            "automatic_resume_authorized": result == "STOPPED",
            "service_stops": service_stops,
            "qualified_binary_hashes": runtime_binaries(stack),
            "original_hba_hex": control["original_hba_hex"],
            "original_hba_sha256": sha(bytes.fromhex(control["original_hba_hex"])),
            "stopped_hba_sha256": sha((stack.state / "postgres/pg_hba.conf").read_bytes()),
            "control_identity": (stack.state / "postgres/global/pg_control").read_bytes()[:8].hex(),
            "capture_sha256": binding.get("sealed_capture", {}).get(
                "sha256", control["capture_sha256"]
            ),
            "parent_handoff": control["parent_handoff"],
            "pg_stop": {
                "exit_code": 0,
                "stdout_sha256": sha(raw_stdout),
                "stdout_file": str(folder / "pg-stop.private.log"),
            },
            "actual_markers_absent": not list(stack.state.glob("*.process.json")),
            "process_identities_absent": all(absent(r) for r in binding["processes"].values()),
        }
        if kind == "target":
            receipt["target_binding"] = control["target_binding"]
        return write_new(folder / "stop.private.json", receipt)


def activate(state, expected_generation, fence_path, fence_sha256):
    """Require the controller's independently pinned, actual auth/fence evidence.

    This consumes evidence; it never manufactures logout/session/token witnesses.
    Both real elapsed clocks must satisfy the controller's qualified token bound.
    """
    stack = stack_at(state)
    proof = read_pinned(fence_path, fence_sha256)
    with stack.operation():
        binding, files = qualified_runtime(stack, {"MAINTENANCE"})
        require(
            binding["generation"] == expected_generation,
            "Maintenance generation differs",
        )
        require(
            set(binding["processes"])
            == {name + ".process.json" for name in ("postgres", "keycloak", "gateway")},
            "Maintenance processes incomplete",
        )
        require(
            proof["format"] == "native-existing-auth-fence/v1"
            and proof["generation"] == expected_generation
            and proof["issuer"] == stack.origin + "/realms/calorie-dev",
            "Foreign auth/fence proof",
        )
        minimum = proof["qualified_minimum_seconds"]
        require(
            type(minimum) is int
            and minimum >= 421
            and re.fullmatch(r"[0-9a-f]{64}", proof["qualified_token_settings_sha256"]),
            "Qualified token/fence bound required",
        )
        require(
            all(
                proof[key] is True
                for key in (
                    "logout_all_succeeded",
                    "issuance_api_503_observed",
                )
            ),
            "Actual auth/fence observations incomplete",
        )
        counts = proof["provider_user_session_counts"]
        require(
            isinstance(counts, dict)
            and counts
            and all(type(n) is int and n == 0 for n in counts.values()),
            "Provider sessions remain",
        )
        control = binding["lifecycle"]
        require(
            control["generation"] == expected_generation,
            "Maintenance timer belongs to another generation",
        )
        closed_mono = proof["closed_after_logout_monotonic"]
        closed_at = datetime.fromisoformat(proof["closed_after_logout_at"])
        require(
            type(closed_mono) in (int, float)
            and closed_mono >= control["started_monotonic"]
            and closed_at >= datetime.fromisoformat(control["started_at"]),
            "Logout/session fence predates this maintenance generation",
        )
        elapsed = time.monotonic() - closed_mono
        elapsed_utc = (datetime.now(UTC) - closed_at).total_seconds()
        require(
            elapsed >= minimum and elapsed_utc >= minimum,
            "Real maintenance fence incomplete",
        )
        if control["kind"] == "target":
            descriptor = read_pinned(
                control["target_binding"]["path"], control["target_binding"]["sha256"]
            )
            verify_source_stopped(descriptor)
            pg, receipt, _files = target_pg(stack, descriptor, files)
            pg.qualify()
            facts = database_facts(pg)
            require(
                facts["epoch"] == receipt["restored_epoch"]
                and facts["ai"] is False
                and facts["nemesis"] is False,
                "Target epoch/gates changed",
            )
        marker = stack.state / "gateway.process.json"
        record = binding["processes"]["gateway.process.json"]
        native.terminate(record)
        require(absent(record), "Maintenance gateway remains")
        marker.unlink()
        # A new actual gateway process means a new generation, never a relabel.
        opened = binding | {
            "generation": str(uuid4()),
            "state": "STARTING",
            "maintenance_generation": expected_generation,
            "auth_fence_sha256": fence_sha256,
        }
        publish(stack, opened)
        try:
            if control["kind"] == "target":
                (pg.data / "pg_hba.conf").write_bytes(RUNNING_HBA)
                require(
                    pg.sql("postgres", "SELECT pg_reload_conf();") == "t",
                    "Retention HBA reload failed",
                )
                pg.config.update(hba_sha256=sha(RUNNING_HBA))
                native.write_json(pg.marker, pg.config)
            stack.start_worker(
                opened, raw=files["worker.env"], resume=opened.get("retention_resume")
            )
            publish(stack, opened)
            stack.launch(
                "gateway",
                [stack.python, "-m", "infra.local.integration.gateway"],
                runtime_env(stack, files, "api"),
            )
            publish(stack, opened)
            ready(stack)
            qualified_runtime(stack, {"STARTING"})
            opened["state"] = "RUNNING"
            publish(stack, opened)
            stack.require_running()
        except BaseException:
            cleanup_errors = []
            if (stack.state / "worker.process.json").exists():
                try:
                    stack.stop_worker(opened)
                except BaseException as cleanup_error:
                    cleanup_errors.append(
                        {"service": "worker", "error_kind": type(cleanup_error).__name__}
                    )
            if marker.exists():
                try:
                    failed_gateway = json.loads(marker.read_bytes())
                    native.terminate(failed_gateway)
                    require(absent(failed_gateway), "Failed activation gateway remains")
                    marker.unlink()
                except BaseException as cleanup_error:
                    cleanup_errors.append(
                        {"service": "gateway", "error_kind": type(cleanup_error).__name__}
                    )
            publish(
                stack, opened | {"state": "ACTIVATION_FAILED", "cleanup_errors": cleanup_errors}
            )
            raise
        return {
            "generation": opened["generation"],
            "previous_generation": expected_generation,
            "real_fence_seconds": elapsed,
            "traffic_open": True,
            "old_token_refusals": "REQUIRED_AFTER_OPEN_BEFORE_CLIENT_ADMISSION",
        }


def ready(stack):
    # D2 only. Unit tests replace this transport boundary; import has no IO.
    from verify import Probe

    Probe(stack).ready()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("capture", "bind-target", "start", "stop", "activate"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--generation")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--handoff-sha256")
    parser.add_argument("--source-pin")
    parser.add_argument("--source-sha256")
    parser.add_argument("--source-stop", type=Path)
    parser.add_argument("--source-stop-sha256")
    parser.add_argument("--restore-receipt-sha256")
    args = parser.parse_args()
    if args.action == "bind-target":
        require(
            args.handoff
            and args.handoff_sha256
            and args.source_stop
            and args.source_stop_sha256
            and args.restore_receipt_sha256,
            "Bind-target needs pinned capture, source stop and restore receipt",
        )
        print(
            json.dumps(
                bind_target(
                    args.state,
                    capture_path=args.handoff,
                    capture_sha256=args.handoff_sha256,
                    source_stop_path=args.source_stop,
                    source_stop_sha256=args.source_stop_sha256,
                    restore_receipt_sha256=args.restore_receipt_sha256,
                )
            )
        )
    elif args.action == "capture":
        require(args.generation and args.archive, "Capture generation/archive required")
        result = capture_native(args.state, args.generation, args.archive)
        print(json.dumps(result["handoff"]))
    elif args.action == "start":
        require(
            args.handoff and args.handoff_sha256 and args.source_pin and args.source_sha256,
            "Start needs pinned handoff and reviewed source binding",
        )
        print(
            json.dumps(
                start_existing(
                    args.state,
                    args.handoff,
                    args.handoff_sha256,
                    source_pin=args.source_pin,
                    source_sha256=args.source_sha256,
                )
            )
        )
    elif args.action == "stop":
        require(args.generation, "Stop generation required")
        print(json.dumps(stop_existing(args.state, args.generation)))
    else:
        require(
            args.generation and args.handoff and args.handoff_sha256,
            "Pinned fence handoff required",
        )
        print(json.dumps(activate(args.state, args.generation, args.handoff, args.handoff_sha256)))


if __name__ == "__main__":
    main()
