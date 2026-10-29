"""Owned Windows Mailpit sink. Mail, credentials and runtime state stay under .tools."""

import argparse
import base64
import ctypes
import hashlib
import io
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
VERSION = "1.32.0"
ASSET_URL = f"https://github.com/axllent/mailpit/releases/download/v{VERSION}/mailpit-windows-amd64.zip"
# Official GitHub release asset 667222096.digest (there is no checksums.txt asset).
ZIP_SHA256 = "16915767a6c95dca569336e8f561f91cf355e9a33c57b91deedcc10a4bba7fd4"
EXE_SHA256 = "9276bbcd182565f2acd594ca1178da667c6b5b716a75e8da979c103c38fc1280"
SMTP_PORT, HTTP_PORT = 26525, 28025
RECIPIENTS = r"^[^@]+@(invalid[.]example|example[.]test|calorie-demo[.]test)$"
FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def powershell(script):
    return subprocess.check_output(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=20,
        env=clean_env(),
        **FLAGS,
    ).strip()


def ps_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def confined(value):
    path = Path(os.path.abspath(value))
    if ROOT / ".tools" not in path.parents or any(
        p.is_symlink() or p.is_junction() for p in (path, *path.parents)
    ):
        raise ValueError("State must be below this checkout's .tools without links")
    return path


def protect(path):
    if os.name != "nt":
        path.chmod(0o700)
        return
    powershell(
        "$ErrorActionPreference='Stop';"
        "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;"
        "$acl=New-Object Security.AccessControl.DirectorySecurity;"
        "$acl.SetOwner($sid);$acl.SetAccessRuleProtection($true,$false);"
        "foreach($id in @($sid.Value,'S-1-5-18')){"
        "$rule=New-Object Security.AccessControl.FileSystemAccessRule("
        "(New-Object Security.Principal.SecurityIdentifier($id)),"
        "'FullControl','ContainerInherit,ObjectInherit','None','Allow');"
        "$acl.AddAccessRule($rule)};"
        f"Set-Acl -LiteralPath {ps_string(path)} -AclObject $acl"
    )


def private_acl(path):
    if os.name != "nt":
        return path.stat().st_mode & 0o077 == 0
    # Inspect descendants too: copied binaries and future DB/WAL files must inherit.
    result = powershell(
        "$ErrorActionPreference='Stop';"
        "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        f"$items=@(Get-Item -LiteralPath {ps_string(path)})+"
        f"@(Get-ChildItem -LiteralPath {ps_string(path)} -Recurse -Force);"
        "$ok=$true;foreach($item in $items){$a=Get-Acl -LiteralPath $item.FullName;"
        "if($item.FullName -eq $items[0].FullName -and !$a.AreAccessRulesProtected){$ok=$false};"
        "foreach($r in $a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){"
        "if($r.AccessControlType -eq 'Allow' -and $r.IdentityReference.Value "
        "-notin @($sid,'S-1-5-18')){$ok=$false}}};$ok"
    )
    return result == "True"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(state):
    return [
        str(state / "mailpit.exe"),
        "--database",
        str(state / "mailpit.db"),
        "--smtp",
        f"127.0.0.1:{SMTP_PORT}",
        "--listen",
        f"127.0.0.1:{HTTP_PORT}",
        "--allowed-hosts",
        "127.0.0.1,localhost",
        "--ui-auth-file",
        str(state / "auth.txt"),
        "--smtp-allowed-recipients",
        RECIPIENTS,
        "--smtp-max-recipients",
        "10",
        "--max",
        "100",
        "--max-message-size",
        "1",
        "--disable-version-check",
        "--smtp-disable-rdns",
        "--block-remote-css-and-fonts",
        "--quiet",
    ]


def clean_env():
    # In particular, no inherited MP_* relay/forward/webhook/auth/config options.
    allowed = {"SYSTEMROOT", "WINDIR", "OS", "PATH", "PATHEXT", "TEMP", "TMP"}
    return {k: v for k, v in os.environ.items() if k.upper() in allowed}


def initialize(state, archive=None, download=False):
    state = confined(state)
    if state.exists():
        raise FileExistsError("Existing mailbox is preserved; use up")
    if bool(archive) == bool(download):
        raise ValueError("Choose a local pinned archive or explicit download")
    if os.name != "nt":
        raise ValueError("This pinned binary requires Windows amd64")
    state.mkdir(parents=True)
    protect(state)
    if not private_acl(state):
        raise PermissionError("Mailbox ACL is not private")
    if download:
        # Setup only; lifecycle never downloads or checks for a latest release.
        with urllib.request.urlopen(ASSET_URL, timeout=60) as response:
            payload = response.read(12 * 1024 * 1024)
    else:
        payload = Path(archive).read_bytes()
    if hashlib.sha256(payload).hexdigest() != ZIP_SHA256:
        raise ValueError(
            "Pinned archive checksum mismatch; state preserved for diagnosis"
        )
    (state / "mailpit-windows-amd64.zip").write_bytes(payload)
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        # Never extract archive paths, and never execute before both hash checks.
        (state / "mailpit.exe").write_bytes(bundle.read("mailpit.exe"))
        (state / "LICENSE").write_bytes(bundle.read("LICENSE"))
    if digest(state / "mailpit.exe") != EXE_SHA256:
        raise ValueError("Pinned executable checksum mismatch")
    (state / "auth.txt").write_text(
        "local:" + secrets.token_urlsafe(32) + "\n", encoding="utf-8"
    )
    write_json(
        state / "config.json",
        {
            "format": "calorie-native-mail/v1",
            "state": str(state),
            "version": VERSION,
            "zip_sha256": ZIP_SHA256,
            "exe_sha256": EXE_SHA256,
            "command": command(state),
        },
    )
    return {"initialized": True, "version": VERSION}


def validate(state):
    state = confined(state)
    if not private_acl(state):
        raise PermissionError("Mailbox ACL is not private")
    config = json.loads((state / "config.json").read_text(encoding="utf-8"))
    expected = {
        "format": "calorie-native-mail/v1",
        "state": str(state),
        "version": VERSION,
        "zip_sha256": ZIP_SHA256,
        "exe_sha256": EXE_SHA256,
        "command": command(state),
    }
    if config != expected or digest(state / "mailpit.exe") != EXE_SHA256:
        raise ValueError("Mailbox configuration or executable differs from pin")
    return state


@contextmanager
def lifecycle_lock(state):
    import msvcrt

    with (state / "lifecycle.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def identity(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError("Invalid owned PID")
    data = powershell(
        "$ErrorActionPreference='Stop';"
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
        "if($null -eq $p){'null'}else{"
        "@{pid=[int]$p.ProcessId;"
        "executable=$p.ExecutablePath;command=$p.CommandLine}|ConvertTo-Json -Compress}"
    )
    result = json.loads(data)
    if result is None:
        raise ProcessLookupError("Owned process is stopped")
    if not result["executable"] or not result["command"]:
        raise PermissionError("Cannot qualify owned process")
    kernel, handle, created = process_handle(pid)
    kernel.CloseHandle(handle)
    result["created"] = created
    return result


def process_handle(pid, terminate=False):
    """Open an exact process object; a retained handle prevents PID-reuse stop races."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000 | int(terminate), False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            raise ProcessLookupError("Owned process is stopped")
        raise PermissionError("Cannot open owned process")
    times = [wintypes.FILETIME() for _ in range(4)]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(wintypes.FILETIME)
    ] * 4
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        kernel.CloseHandle(handle)
        raise OSError("Cannot qualify owned process birth time")
    return kernel, handle, (times[0].dwHighDateTime << 32) + times[0].dwLowDateTime


def listeners():
    data = powershell(
        "$ErrorActionPreference='Stop';"
        f"$rows=@(Get-NetTCPConnection -State Listen -LocalPort {SMTP_PORT},{HTTP_PORT} "
        "-ErrorAction SilentlyContinue | ForEach-Object {"
        "@{address=$_.LocalAddress;port=[int]$_.LocalPort;pid=[int]$_.OwningProcess}});"
        "ConvertTo-Json -InputObject $rows -Compress"
    )
    return json.loads(data)


def qualify(state, record):
    expected_command = subprocess.list2cmdline(command(state))
    if (
        set(record) != {"pid", "created", "executable", "command"}
        or record["executable"].casefold() != str(state / "mailpit.exe").casefold()
        or record["command"] != expected_command
        or identity(record["pid"]) != record
    ):
        raise RuntimeError(
            "Saved process identity or exact command mismatch; no stop authorized"
        )


def owned_ports(record):
    expected = [
        {"address": "127.0.0.1", "port": p, "pid": record["pid"]}
        for p in (SMTP_PORT, HTTP_PORT)
    ]
    if sorted(listeners(), key=lambda p: p["port"]) != expected:
        raise RuntimeError(
            "Mailbox ports do not belong exclusively to the exact saved process"
        )


def available():
    if listeners():
        raise RuntimeError("Mailbox port conflict; no process stopped")
    for port in (SMTP_PORT, HTTP_PORT):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))


def mailbox_json(state, endpoint="/api/v1/messages"):
    """Private in-memory read for the owning verifier; callers must not print mail."""
    state = validate(state)
    record = saved_record(state)
    if not record:
        raise RuntimeError("Mailbox has no owned running process")
    qualify(state, record)
    owned_ports(record)
    return _mailbox_json(state, endpoint)


def _mailbox_json(state, endpoint="/api/v1/messages"):
    if not re.fullmatch(r"/api/v1/(messages|message/[a-zA-Z0-9_-]{22})", endpoint):
        raise ValueError("Only local mailbox read endpoints are supported")
    credential = (state / "auth.txt").read_text(encoding="utf-8").strip()
    request = urllib.request.Request(
        f"http://127.0.0.1:{HTTP_PORT}{endpoint}",
        headers={
            "Authorization": "Basic " + base64.b64encode(credential.encode()).decode()
        },
    )

    # Ignore machine proxy settings even for loopback. No redirects to other hosts.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=3) as response:
        return json.load(response)


def saved_record(state):
    path = state / "process.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def event(state, action, record):
    directory = state / "history"
    directory.mkdir(exist_ok=True)
    write_json(
        directory / (uuid4().hex + ".json"), {"action": action, "process": record}
    )


def stop_exact(state, record):
    # Recheck immediately before stopping one PID, never taskkill /T or name matching.
    qualify(state, record)
    kernel, handle, created = process_handle(record["pid"], terminate=True)
    try:
        if created != record["created"]:
            raise RuntimeError("PID reused before termination; no process stopped")
        from ctypes import wintypes

        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        if not kernel.TerminateProcess(handle, 0):
            raise OSError("Owned process refused termination")
    finally:
        kernel.CloseHandle(handle)
    for _ in range(50):
        try:
            identity(record["pid"])
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError("Owned process did not stop; mailbox data preserved")


def status(state):
    state = validate(state)
    record = saved_record(state)
    if record:
        try:
            qualify(state, record)
        except ProcessLookupError:
            record = None
    if not record:
        if listeners():
            raise RuntimeError("Foreign listener occupies mailbox ports")
        return public_status(False)
    owned_ports(record)
    return public_status(True) | {"messages": _mailbox_json(state)["total"]}


def public_status(running):
    return {
        "running": running,
        "version": VERSION,
        "host": "127.0.0.1",
        "smtp_port": SMTP_PORT,
        "http_port": HTTP_PORT,
        "zip_sha256": ZIP_SHA256,
        "exe_sha256": EXE_SHA256,
    }


def up(state):
    state = validate(state)
    with lifecycle_lock(state):
        current = status(state)
        if current["running"]:
            return current
        available()
        log = (state / "private-mailpit.log").open("ab")
        try:
            child = subprocess.Popen(
                command(state),
                cwd=state,
                env=clean_env(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                **FLAGS,
            )
        finally:
            log.close()
        record = identity(child.pid)
        qualify(state, record)
        write_json(state / "process.json", record)
        event(state, "started", record)
        for _ in range(50):
            if child.poll() is not None:
                raise RuntimeError(
                    "Owned Mailpit exited; private log and mailbox preserved"
                )
            try:
                owned_ports(record)
                _mailbox_json(state)
                return status(state)
            except (OSError, RuntimeError):
                time.sleep(0.2)
        stop_exact(state, record)
        event(state, "startup-failed-stopped", record)
        raise RuntimeError("Mailbox readiness failed; private evidence preserved")


def down(state):
    state = validate(state)
    with lifecycle_lock(state):
        record = saved_record(state)
        if record:
            try:
                qualify(state, record)
            except ProcessLookupError:
                record = None
        if not record:
            if listeners():
                raise RuntimeError("Foreign listener occupies mailbox ports")
            return {"running": False, "preserved": True}
        owned_ports(record)
        stop_exact(state, record)
        event(state, "stopped", record)
        return {"running": False, "preserved": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "up", "down", "status"))
    parser.add_argument("--state", required=True)
    install = parser.add_mutually_exclusive_group()
    install.add_argument("--archive", type=Path)
    install.add_argument("--download", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action != "init" and (args.archive or args.download):
            raise ValueError("Install options are only allowed with init")
        if args.action == "init":
            result = initialize(args.state, args.archive, args.download)
        else:
            result = globals()[args.action](args.state)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:  # noqa: BLE001 - CLI boundary must never expose mail or secrets.
        # Never render arbitrary HTTP/process/SMTP errors containing credentials or links.
        print(
            json.dumps({"ok": False, "error_type": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
