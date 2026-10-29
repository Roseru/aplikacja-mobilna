"""OLD-code stop receipt before integrating new Native adapters.

Run in a fresh interpreter with --checkout pointing at the still-qualified OLD
checkout. This runner lives outside integration/*.py and never changes that code.
It is not an adoption/relabel command and cannot stop restored OwnedPG targets.
"""

import argparse
import hashlib
import importlib
import json
import sys
from pathlib import Path

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


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_path(value, native):
    raw = str(value).replace("\\", "/")
    parts = raw.split("/")
    if len(parts[0]) == 2 and parts[0][1] == ":":
        parts = parts[1:]
    if raw.startswith("//") or any(
        p.endswith((" ", ".")) or ":" in p for p in parts if p not in ("", ".", "..")
    ):
        raise ValueError("Ambiguous state path")
    return native.confined(value)


def stop_old(native, observer, state, destination, expected_generation, binding_file_sha256):
    state = checked_path(state, native)
    destination = checked_path(destination, native)
    if destination.exists() or destination.parent != state:
        raise ValueError("New receipt path required")
    stdout_path = checked_path(
        destination.with_name(destination.name + ".pg-stop.private.log"), native
    )
    if stdout_path.exists() or any(
        p.is_symlink() or p.is_junction() for p in (state, *state.rglob("*"))
    ):
        raise ValueError("Linked state or existing stop log refused")
    stack = native.Native(state)
    if Path(sys.executable).resolve() != Path(stack.python).resolve():
        raise ValueError("Configured qualified OLD Python required")
    if (state / "owner.json").exists():
        raise ValueError("OLD bridge accepts original Native source only")
    with stack.operation():
        raw = (state / "runtime-binding.json").read_bytes()
        if sha(raw) != binding_file_sha256:
            raise ValueError("External OLD binding pin differs")
        binding = stack.require_running()
        if binding != json.loads(raw) or binding["generation"] != expected_generation:
            raise ValueError("OLD generation differs")
        runtime = observer.runtime(stack)
        process = binding["processes"]["postgres.process.json"]
        data = checked_path(state / "postgres", native)
        pid = (data / "postmaster.pid").read_text().splitlines()
        if (
            int(pid[0]) != process["pid"]
            or Path(pid[1]).resolve() != data.resolve()
            or int(pid[3]) != stack.config["pg_port"]
        ):
            raise ValueError("OLD postmaster binding differs")
        database = json.loads(
            stack.sql(
                "calorie_app",
                "SELECT json_build_object('data',current_setting('data_directory'),"
                "'port',inet_server_port(),'listen',current_setting('listen_addresses'),"
                "'epoch',(SELECT sync_epoch FROM app.installation_state),"
                "'revision',(SELECT version_num FROM app.alembic_version));",
            )
        )
        if (
            Path(database["data"]).resolve() != data.resolve()
            or database["port"] != stack.config["pg_port"]
            or database["listen"] != "127.0.0.1"
            or database["revision"] != "0026_ledger_review"
        ):
            raise ValueError("OLD SQL target/schema differs")
        config = {name: sha((state / name).read_bytes()) for name in CONFIG_FILES}
        profile = state / "config-generation/provider-profile.json"
        if profile.exists():
            config["config-generation/provider-profile.json"] = sha(profile.read_bytes())
        hba = (data / "pg_hba.conf").read_bytes()
        if stack.require_running() != binding:
            raise ValueError("OLD generation changed before stop")
        if any(sha((state / name).read_bytes()) != pin for name, pin in config.items()):
            raise ValueError("OLD configuration changed before stop")
        receipt = {
            "format": "native-existing-stop/v1",
            "kind": "source",
            "state": str(state),
            "result": "FAIL",
            "runtime": binding,
            "qualified_runtime": runtime,
            "qualified_binary_hashes": {
                name: sha(path.read_bytes())
                for name, path in {
                    "postgres": stack.pg / "postgres.exe",
                    "python": Path(stack.python),
                    "java": Path(stack.config["java_home"]) / "bin/java.exe",
                    "keycloak_bootstrap": state / "keycloak/lib/quarkus-run.jar",
                    "keycloak_launcher": state / "keycloak/bin/kc.bat",
                    **{
                        "pgtool:" + name: stack.pg / (name + ".exe")
                        for name in (
                            "initdb",
                            "pg_ctl",
                            "postgres",
                            "psql",
                            "pg_dump",
                            "pg_dumpall",
                            "pg_restore",
                        )
                    },
                }.items()
            },
            "database": database,
            "configuration_files": config,
            "original_hba_hex": hba.hex(),
            "original_hba_sha256": sha(hba),
            "control_identity": (data / "global/pg_control").read_bytes()[:8].hex(),
            "bridge_source_sha256": sha(Path(__file__).read_bytes()),
        }
        stops = []
        original_run = stack.run

        def checked_run(arguments, **kwargs):
            result = original_run(arguments, **kwargs)
            if kwargs.get("label") == "pg-stop":
                raw_stdout = (state / "pg-stop.log").read_bytes()
                stdout_path.write_bytes(raw_stdout)
                stops.append(
                    {
                        "exit_code": 0,
                        "stdout_sha256": sha(raw_stdout),
                        "stdout_file": str(stdout_path),
                    }
                )
            return result

        stack.run = checked_run
        try:
            # _down is the OLD implementation, already under its single native.lock.
            down_result = stack._down()
            if down_result is not None and down_result["result"] != "STOPPED":
                raise ValueError("OLD stop has unknown process exit; no resume handoff")
            if (
                len(stops) != 1
                or (data / "postmaster.pid").exists()
                or list(state.glob("*.process.json"))
            ):
                raise ValueError("OLD stop incomplete")
            for record in binding["processes"].values():
                try:
                    if native.identity(record["pid"]) == record:
                        raise ValueError("OLD process still running")
                except ProcessLookupError:
                    pass
            if (data / "pg_hba.conf").read_bytes() != hba:
                raise ValueError("OLD stop changed HBA")
            receipt.update(
                result="STOPPED",
                pg_stop=stops[0],
                actual_markers_absent=True,
                process_identities_absent=True,
            )
        finally:
            encoded = json.dumps(receipt, indent=2) + "\n"
            native.private_write(destination, encoded)
        return sha(encoded.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-generation", required=True)
    parser.add_argument("--binding-file-sha256", required=True)
    args = parser.parse_args()
    if "infra.local.integration.native" in sys.modules:
        raise ValueError("Fresh interpreter required")
    checkout = args.checkout.resolve(strict=True)
    sys.path.insert(0, str(checkout))
    native = importlib.import_module("infra.local.integration.native")
    observer = importlib.import_module("infra.local.integration.observe")
    if native.ROOT.resolve() != checkout:
        raise ValueError("OLD checkout import differs")
    print(
        stop_old(
            native,
            observer,
            args.state,
            args.receipt,
            args.expected_generation,
            args.binding_file_sha256,
        )
    )


if __name__ == "__main__":
    main()
