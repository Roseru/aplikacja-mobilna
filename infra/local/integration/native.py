"""Opt-in isolated native lifecycle sharing the local integration configuration."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import tomllib
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "backend/src"))
sys.path.insert(0, str(ROOT / "infra/integration"))
from run import initialize, prepare_worker, private_write  # noqa: E402

FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
SHARED_HELPERS = (
    "infra/integration/run.py",
    "infra/integration/verify.py",
    "infra/local/init-db.sh",
    "infra/local/keycloak/realm.json",
    "infra/integration/e4_observer.py",
    "infra/integration/worker.py",
)


def write_json(path, value):
    private_write(path, json.dumps(value, indent=2) + "\n")


def confined(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("Linked state paths are refused")
    if ROOT / ".tools" not in path.parents:
        raise ValueError("Native state must be a new directory under this checkout's .tools")
    return path


def available(host, ports):
    if len(set(ports)) != len(ports) or any(
        type(p) is not int or not 1024 <= p <= 65535 for p in ports
    ):
        raise ValueError("Distinct nonprivileged ports required")
    for port in ports:
        for address in {host, "127.0.0.1"} if port == ports[0] else {"127.0.0.1"}:
            with socket.socket() as listener:
                if os.name == "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                listener.bind((address, port))


def clean_env():
    # Do not inherit another installation's provider, credentials, Java agents or DB.
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "OS",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "COMSPEC",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "PROCESSOR_ARCHITECTURE",
    }
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def source(pin):
    if len(pin) != 40 or any(c not in "0123456789abcdef" for c in pin):
        raise ValueError("Full source commit required")
    subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            pin,
            "--",
            "backend",
            "contracts",
            *SHARED_HELPERS,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        **FLAGS,
    )
    lock = tomllib.loads((ROOT / "backend/uv.lock").read_text(encoding="utf-8"))
    packages = {p["name"]: p["version"] for p in lock["package"] if "registry" in p["source"]}
    if any(importlib.metadata.version(name) != version for name, version in packages.items()):
        raise ValueError("Python environment differs from the pinned backend lock")
    import calorie_app

    if not Path(calorie_app.__file__).resolve().is_relative_to(ROOT / "backend/src"):
        raise ValueError("Backend import came from another checkout")
    return {
        "commit": pin,
        "backend_tree": subprocess.check_output(
            ["git", "rev-parse", pin + ":backend"], cwd=ROOT, **FLAGS
        )
        .decode()
        .strip(),
        "contracts_tree": subprocess.check_output(
            ["git", "rev-parse", pin + ":contracts"], cwd=ROOT, **FLAGS
        )
        .decode()
        .strip(),
        "lock_sha256": hashlib.sha256((ROOT / "backend/uv.lock").read_bytes()).hexdigest(),
        "packages": packages,
        "adapter_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.py"))
        },
        "shared_helper_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SHARED_HELPERS
        },
        "adapter_profile_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(HERE.glob("*.json"))
        },
    }


def process_kernel():
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    return kernel


def handle_identity(kernel, handle, pid):
    from ctypes import wintypes

    times = [wintypes.FILETIME() for _ in range(4)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise OSError("Cannot qualify owned process creation time")
    name = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(name))
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
        raise OSError("Cannot qualify owned process executable")
    return {
        "pid": pid,
        "created": (times[0].dwHighDateTime << 32) + times[0].dwLowDateTime,
        "executable": name.value,
    }


def identity(pid):
    """Exact Windows process birth time and executable, never process-wide enumeration."""
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid owned PID")
    kernel = process_kernel()
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            raise ProcessLookupError("Owned process is unavailable")
        raise PermissionError("Cannot qualify saved process; no stop authorized")
    try:
        return handle_identity(kernel, handle, pid)
    finally:
        kernel.CloseHandle(handle)


def stop_owned(record):
    """Windows forced stop on one qualified retained handle; never taskkill exit."""
    from ctypes import wintypes

    kernel = process_kernel()
    handle = kernel.OpenProcess(0x1000 | 0x100000 | 1, False, record["pid"])
    if not handle:
        if ctypes.get_last_error() == 87:
            return {
                "method": "already_absent",
                "forced": False,
                "graceful": False,
                "wait": "NOT_OBSERVED",
                "exit_observed": False,
                "exit_code": None,
            }
        raise PermissionError("Cannot acquire owned stop handle")
    try:
        if handle_identity(kernel, handle, record["pid"]) != record:
            raise RuntimeError("Saved PID was reused; no process stopped")
        wait = kernel.WaitForSingleObject(handle, 0)
        forced = wait == 0x102
        if forced:
            if not kernel.TerminateProcess(handle, 1):
                raise OSError("Owned process termination failed")
            wait = kernel.WaitForSingleObject(handle, 10000)
        if wait != 0:
            raise RuntimeError("Owned process did not confirm termination")
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise OSError("Cannot observe owned process exit")
        return {
            "method": "TerminateProcess" if forced else "already_exited_handle",
            "forced": forced,
            "graceful": False,
            "wait": "SIGNALED",
            "exit_observed": True,
            "exit_code": code.value,
        }
    finally:
        kernel.CloseHandle(handle)


def terminate(record):
    try:
        current = identity(record["pid"])
    except ProcessLookupError:
        return
    if current != record:
        raise RuntimeError("Saved PID was reused; no process stopped")
    subprocess.run(
        ["taskkill", "/PID", str(record["pid"]), "/T", "/F"],
        check=True,
        capture_output=True,
        **FLAGS,
    )


def prepare(
    state,
    *,
    host,
    port,
    pg_port,
    keycloak_port,
    management_port,
    pg_bin,
    java_home,
    keycloak_home,
    python,
    pin,
):
    state = confined(state)
    if state.exists():
        raise FileExistsError("Existing state is preserved; choose a fresh directory")
    address = ipaddress.IPv4Address(host)
    if not any(
        address in ipaddress.ip_network(n)
        for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ):
        raise ValueError("Use one RFC1918 identity shared with the later AVD transport")
    binding = source(pin)
    available(host, [port, pg_port, keycloak_port, management_port])
    paths = {
        "pg_bin": Path(pg_bin).resolve(),
        "java_home": Path(java_home).resolve(),
        "keycloak_home": Path(keycloak_home).resolve(),
        "python": Path(python).resolve(),
    }
    if paths["python"] != Path(sys.executable).resolve():
        raise ValueError("Run the adapter with the same qualified Python selected for its services")
    for item in [
        paths["pg_bin"] / "initdb.exe",
        paths["java_home"] / "bin/java.exe",
        paths["keycloak_home"] / "bin/kc.bat",
        paths["python"],
    ]:
        if not item.is_file():
            raise ValueError("Native runtime input is missing")
    config = initialize(state, host, port, "calorie-native-o2")
    prepare_worker(state)
    config.update(
        format="calorie-native/v1",
        state=str(state),
        pg_port=pg_port,
        keycloak_port=keycloak_port,
        management_port=management_port,
        source=binding,
        **{k: str(v) for k, v in paths.items()},
    )
    for name in ("api", "migrate", "worker", "keycloak"):
        path = state / f"{name}.env"
        text = path.read_text().replace("@postgres/", f"@127.0.0.1:{pg_port}/")
        text = text.replace("postgres:5432", f"127.0.0.1:{pg_port}")
        text = text.replace("https://gateway:8443", config["origin"])
        text = text.replace("/run/trust/ca.pem", (state / "tls/ca.pem").as_posix())
        text = text.replace(
            "CATALOG_ARTIFACT_ROOT=/catalog",
            "CATALOG_ARTIFACT_ROOT=" + (state / "catalog").as_posix(),
        )
        if name == "api":
            text += "AI_PROVIDER=mock\nAI_PHOTO_ROOT=" + (state / "photos").as_posix() + "\n"
        private_write(path, text)
    for name in ("catalog", "photos"):
        (state / name).mkdir()
    write_json(state / "native.json", config)
    shutil.copytree(
        paths["keycloak_home"],
        state / "keycloak",
        ignore=shutil.ignore_patterns("data"),
    )
    imports = state / "keycloak/data/import"
    imports.mkdir(parents=True)
    shutil.copyfile(state / "realm/calorie-dev.json", imports / "calorie-dev.json")
    return config


class Native:
    def __init__(self, state):
        self.state = confined(state)
        self.config = json.loads((self.state / "native.json").read_text())
        if self.config.get("format") != "calorie-native/v1" or self.config["state"] != str(
            self.state
        ):
            raise ValueError("Not an owned native state")
        host = str(ipaddress.IPv4Address(self.config["host"]))
        if self.config["origin"] != f"https://{host}:{self.config['port']}":
            raise ValueError("Native origin must preserve the configured exact HTTPS identity")
        if json.loads((self.state / "config.json").read_text()) != {
            k: self.config[k] for k in ("host", "port", "origin", "project")
        }:
            raise ValueError("Native and shared integration configuration differ")
        self.origin = self.config["origin"]
        self.pg = Path(self.config["pg_bin"])
        self.python = self.config["python"]

    def env(self, name=None):
        env = clean_env()
        env.update(
            PYTHONPATH=os.pathsep.join([str(ROOT / "backend/src"), str(ROOT)]),
            CALORIE_NATIVE_STATE=str(self.state),
            PYTHONUNBUFFERED="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        if name:
            env.update(
                dict(
                    line.split("=", 1)
                    for line in (self.state / f"{name}.env").read_text().splitlines()
                )
            )
        if name == "api" and (env.get("AI_PROVIDER") != "mock" or env.get("GEMINI_API_KEY")):
            raise ValueError("Native rehearsal requires mock AI, without a Google key")
        return env

    @contextmanager
    def operation(self):
        descriptor = os.open(self.state / "native.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(descriptor)

    def run(self, arguments, *, env=None, input_text=None, label="command"):
        log = self.state / f"{label}.log"
        # A PostgreSQL background child can inherit a pipe on Windows. A private
        # file avoids waiting for that child's stdout EOF after pg_ctl exits.
        with log.open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [str(p) for p in arguments],
                cwd=self.state,
                env=env or self.env(),
                input=input_text,
                text=True,
                stdout=output,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                **FLAGS,
            )
        if result.returncode:
            raise RuntimeError(f"Native {label} failed; inspect its private log")
        return log.read_text(encoding="utf-8", errors="replace")

    def sql(self, database, sql, *, user="postgres"):
        env = self.env()
        passwords = dict(
            line.split("=", 1) for line in (self.state / "postgres.env").read_text().splitlines()
        )
        env.update(passwords, PGPASSWORD=passwords["POSTGRES_PASSWORD"])
        return self.run(
            [
                self.pg / "psql.exe",
                "-h",
                "127.0.0.1",
                "-p",
                str(self.config["pg_port"]),
                "-U",
                user,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
            ],
            env=env,
            input_text=sql,
            label="sql",
        ).strip()

    def launch(self, name, command, env, *, cwd=None, log_path=None):
        marker = self.state / f"{name}.process.json"
        if marker.exists():
            raise RuntimeError("Existing process marker requires an explicit down")
        if name == "worker":
            pending = json.loads((self.state / "runtime-binding.json").read_bytes())
            pending["retention_launch_unresolved"] = True
            write_json(self.state / "runtime-binding.json", pending)
        with (log_path or self.state / f"{name}.log").open("ab") as output:
            process = subprocess.Popen(
                command,
                cwd=cwd or self.state,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                **FLAGS,
            )
        try:
            if name == "worker" and process.poll() is not None:
                raise RuntimeError("Owned child exited before identity publication")
            record = identity(process.pid)
            if name == "worker" and process.poll() is not None:
                raise RuntimeError("Owned child exited during identity publication")
            write_json(marker, record)
        except BaseException:
            if name == "worker":
                # This original Popen handle still owns the child even when no
                # safe PID marker could be published. Never target a raw PID.
                failure = {
                    "pid": process.pid,
                    "ownership": "original_Popen_handle",
                    "forced": None,
                    "graceful": False,
                    "exit_observed": False,
                    "exit_code": None,
                    "unresolved_launch": True,
                }
                try:
                    code = process.poll()
                    failure["forced"] = code is None
                    if code is None:
                        process.terminate()
                        code = process.wait(timeout=10)
                    failure.update(exit_observed=True, exit_code=code)
                except BaseException as cleanup_error:
                    failure["cleanup_error_kind"] = type(cleanup_error).__name__
                finally:
                    write_json(
                        (cwd or self.state) / ("launch-failed-" + uuid4().hex + ".private.json"),
                        failure,
                    )
            raise
        if name == "worker":
            pending["retention_launch_unresolved"] = False
            write_json(self.state / "runtime-binding.json", pending)
        return process

    def worker_configuration(self, raw=None):
        from .retention import configuration

        return configuration(self, raw)

    def start_worker(self, binding, **kwargs):
        from .retention import start

        return start(self, binding, **kwargs)

    def qualify_worker(self, binding):
        from .retention import qualify

        return qualify(self, binding)

    def stop_worker(self, binding):
        from .retention import stop

        return stop(self, binding)

    def configuration_binding(self):
        path = confined(self.state / "config-generation/provider-profile.json")
        retention = {"retention": self.worker_configuration()[1]}
        if not path.exists():
            return retention
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError("Invalid provider configuration record")
        raw = path.read_bytes()
        value = json.loads(raw)
        if value.get("format") != "calorie-native-provider-profile/v1" or value.get(
            "result"
        ) not in {"CONFIGURED", "PARTIAL", "FAIL"}:
            raise ValueError("Invalid provider configuration result")
        return retention | {
            "provider_profile_sha256": hashlib.sha256(raw).hexdigest(),
            "provider_profile_result": value["result"],
        }

    def require_running(self):
        binding = json.loads((self.state / "runtime-binding.json").read_text())
        if binding["state"] != "RUNNING" or binding["source"] != source(
            self.config["source"]["commit"]
        ):
            raise ValueError("Runtime generation is stale; restart this owned stack explicitly")
        if binding.get("configuration", {}) != self.configuration_binding():
            raise ValueError("Runtime provider configuration differs from its binding")
        markers = {p.name: json.loads(p.read_text()) for p in self.state.glob("*.process.json")}
        if (
            set(markers)
            != {
                "postgres.process.json",
                "keycloak.process.json",
                "gateway.process.json",
                "worker.process.json",
            }
            or markers != binding["processes"]
        ):
            raise ValueError("Runtime process generation differs from its binding")
        if any(identity(record["pid"]) != record for record in markers.values()):
            raise ValueError("Runtime process identity differs from its binding")
        self.qualify_worker(binding)
        return binding

    def up(self):
        with self.operation():
            self._up()

    def _up(self):
        if Path(self.python).resolve() != Path(sys.executable).resolve():
            raise ValueError("Lifecycle must use the configured qualified Python")
        binding = {
            "generation": str(uuid4()),
            "state": "STARTING",
            "source": source(self.config["source"]["commit"]),
            "configuration": self.configuration_binding(),
        }
        if list(self.state.glob("*.process.json")):
            raise RuntimeError("Existing process markers require an explicit down before up")
        write_json(self.state / "runtime-binding.json", binding)
        available(
            self.config["host"],
            [self.config[k] for k in ("port", "pg_port", "keycloak_port", "management_port")],
        )
        data = self.state / "postgres"
        if not data.exists():
            values = dict(
                line.split("=", 1)
                for line in (self.state / "postgres.env").read_text().splitlines()
            )
            private_write(self.state / "pg-password.txt", values["POSTGRES_PASSWORD"] + "\n")
            self.run(
                [
                    self.pg / "initdb.exe",
                    "-D",
                    data,
                    "-U",
                    "postgres",
                    "--encoding=UTF8",
                    "--locale=C",
                    "--auth=scram-sha-256",
                    "--pwfile=" + str(self.state / "pg-password.txt"),
                ],
                label="initdb",
            )
            private_write(
                data / "postgresql.conf",
                (data / "postgresql.conf").read_text()
                + "\nlisten_addresses='127.0.0.1'\n"
                + f"port={self.config['pg_port']}\n"
                + "log_statement='none'\nlog_min_error_statement='panic'\n",
            )
        self.run(
            [
                self.pg / "pg_ctl.exe",
                "-D",
                data,
                "-l",
                self.state / "postgres.log",
                "-w",
                "start",
            ],
            label="pg-start",
        )
        pg_pid = int((data / "postmaster.pid").read_text().splitlines()[0])
        write_json(self.state / "postgres.process.json", identity(pg_pid))
        if not (self.state / "provisioned.json").exists():
            script = (
                (ROOT / "infra/local/init-db.sh")
                .read_text()
                .split("<<'SQL'\n", 1)[1]
                .rsplit("\nSQL", 1)[0]
            )
            self.sql("postgres", script)
            self.run(
                [
                    self.python,
                    "-m",
                    "alembic",
                    "-c",
                    ROOT / "backend/alembic.ini",
                    "upgrade",
                    "head",
                ],
                env=self.env("migrate"),
                label="migrate",
            )
            write_json(
                self.state / "provisioned.json",
                {"source": self.config["source"], "at": datetime.now(UTC).isoformat()},
            )
        self.start_worker(binding)
        env = self.env("keycloak")
        # Keycloak's code-replay WARN otherwise includes an authorization-code ID.
        env["KC_LOG_LEVEL"] = (
            "info,org.keycloak.events:off,org.keycloak.protocol.oidc.utils.OAuth2CodeParser:off"
        )
        env.update(
            JAVA_HOME=self.config["java_home"],
            PATH=str(Path(self.config["java_home"]) / "bin") + os.pathsep + env.get("PATH", ""),
        )
        self.launch(
            "keycloak",
            [
                str(self.state / "keycloak/bin/kc.bat"),
                "start-dev",
                "--http-host=127.0.0.1",
                f"--http-port={self.config['keycloak_port']}",
                f"--http-management-port={self.config['management_port']}",
                "--import-realm",
            ],
            env,
        )
        self.launch(
            "gateway",
            [self.python, "-m", "infra.local.integration.gateway"],
            self.env("api"),
        )
        from verify import Probe

        Probe(self).ready()
        if source(self.config["source"]["commit"]) != binding["source"]:
            raise RuntimeError("Sources changed during startup; no qualified generation")
        binding.update(
            state="RUNNING",
            processes={
                p.name: json.loads(p.read_text()) for p in self.state.glob("*.process.json")
            },
        )
        write_json(self.state / "runtime-binding.json", binding)

    def down(self):
        with self.operation():
            self._down()

    def _down(self):
        # Preserve all DB files, realms, CA, secrets, data and evidence.
        value = json.loads((self.state / "runtime-binding.json").read_bytes())
        before = dict(value)
        markers = {p.name: json.loads(p.read_bytes()) for p in self.state.glob("*.process.json")}
        if value.get("retention_launch_unresolved", False) and "worker.process.json" not in markers:
            raise ValueError("Unresolved worker launch; no safe PG stop or resume")
        if not set(markers) <= {
            n + ".process.json" for n in ("postgres", "keycloak", "gateway", "worker")
        }:
            raise ValueError("Unknown owned process marker")
        for marker in self.state.glob("*.process.json"):
            record = json.loads(marker.read_text())
            try:
                current = identity(record["pid"])
            except ProcessLookupError:
                continue
            if current != record:
                raise RuntimeError("Saved PID was reused; no process stopped")
        if "worker.process.json" in markers:
            from .retention import descriptor

            descriptor(self, value)
            if value["retention"]["process"] != markers["worker.process.json"]:
                raise ValueError("Worker stop binding differs")
        worker_stop = None
        for name in ("gateway", "worker", "keycloak"):
            marker = self.state / f"{name}.process.json"
            if marker.exists():
                if name == "worker":
                    worker_stop = self.stop_worker(value)
                else:
                    record = json.loads(marker.read_text())
                    terminate(record)
                    try:
                        remains = identity(record["pid"]) == record
                    except ProcessLookupError:
                        remains = False
                    if remains:
                        raise RuntimeError("Owned service remains after stop")
                    marker.unlink()
        pg_stop = {"exit_code": None, "observed": False}
        marker = self.state / "postgres.process.json"
        if marker.exists():
            record = json.loads(marker.read_text())
            try:
                current = identity(record["pid"])
            except ProcessLookupError:
                current = None
            if current is not None:
                if current != record:
                    raise RuntimeError("PostgreSQL PID reused; no stop attempted")
                self.run(
                    [
                        self.pg / "pg_ctl.exe",
                        "-D",
                        self.state / "postgres",
                        "-w",
                        "-m",
                        "fast",
                        "stop",
                    ],
                    label="pg-stop",
                )
                if (self.state / "postgres/postmaster.pid").exists():
                    raise RuntimeError("PG stop did not remove its PID file")
                try:
                    if identity(record["pid"]) == record:
                        raise RuntimeError("PG remains after stop")
                except ProcessLookupError:
                    pass
                stdout = (self.state / "pg-stop.log").read_bytes()
                log = self.state / ("pg-stop-" + uuid4().hex + ".private.log")
                log.write_bytes(stdout)
                log.chmod(0o600)
                pg_stop = {
                    "exit_code": 0,
                    "observed": True,
                    "stdout_file": str(log),
                    "stdout_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                }
            marker.unlink()
        known = (
            pg_stop["observed"]
            and not value.get("retention_unknown_exit", False)
            and (worker_stop is None or worker_stop["result"] == "STOPPED")
        )
        result = "STOPPED" if known else "STOPPED_UNKNOWN_EXIT"
        write_json(self.state / "runtime-binding.json", before | {"state": result})
        receipt = {
            "result": result,
            "generation": value["generation"],
            "processes_before": markers,
            "worker_stop": worker_stop,
            "pg_stop": pg_stop,
            "automatic_resume_authorized": known,
        }
        write_json(self.state / ("down-" + uuid4().hex + ".private.json"), receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "up", "down", "status"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int, default=28443)
    parser.add_argument("--pg-port", type=int, default=25432)
    parser.add_argument("--keycloak-port", type=int, default=28080)
    parser.add_argument("--management-port", type=int, default=29000)
    for name in ("pg-bin", "java-home", "keycloak-home", "python", "source-commit"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.action == "init":
        config = prepare(
            args.state,
            host=args.host,
            port=args.port,
            pg_port=args.pg_port,
            keycloak_port=args.keycloak_port,
            management_port=args.management_port,
            pg_bin=args.pg_bin,
            java_home=args.java_home,
            keycloak_home=args.keycloak_home,
            python=args.python,
            pin=args.source_commit,
        )
        print(
            json.dumps(
                {
                    "state": "INITIALIZED",
                    "origin": config["origin"],
                    "source": config["source"],
                }
            )
        )
    else:
        stack = Native(args.state)
        if args.action in {"up", "down"}:
            getattr(stack, args.action)()
        qualified = False
        worker_witness = {"state": "NOT_QUALIFIED"}
        if args.action in {"up", "status"}:
            try:
                binding = stack.require_running()
                worker_witness = stack.qualify_worker(binding)
                qualified = True
            except (OSError, ValueError):
                pass
        print(
            json.dumps(
                {
                    "state": args.action,
                    "process_generation_qualified": qualified,
                    "retention": worker_witness,
                    "origin": stack.origin,
                    "processes": {
                        p.stem: json.loads(p.read_text())
                        for p in stack.state.glob("*.process.json")
                    },
                }
            )
        )


if __name__ == "__main__":
    main()
