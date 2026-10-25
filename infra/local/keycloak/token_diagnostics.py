"""Offline, unverified time measurements from one explicitly selected private file.

This module never authenticates a token, fetches keys, logs claims or changes services.
Only the fixed report below may leave the process, including on CLI errors.
"""

import argparse
import base64
import json
import math
import os
import re
import stat
import time
from pathlib import Path

MAX_FILE_BYTES = 16 * 1024
ROOT = Path(__file__).resolve().parents[3]
MARKER = "UNVERIFIED_DIAGNOSTIC"
REJECTED = {"kind": MARKER, "status": "INPUT_REJECTED"}


class DiagnosticInputError(ValueError):
    def __init__(self):
        super().__init__("diagnostic input rejected")


def _regular_private(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or getattr(info, "st_file_attributes", 0) & 0x400  # Windows reparse point
        or info.st_size > MAX_FILE_BYTES
    ):
        raise DiagnosticInputError()
    # POSIX modes have no equivalent meaning for Windows DACLs. The operator
    # must select an ACL-private directory on Windows; no ACL is changed here.
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise DiagnosticInputError()


def _drive_type(root):
    import ctypes

    drive_type = ctypes.WinDLL("kernel32", use_last_error=True).GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    return drive_type(root)


def _read_file(path):
    # Reject network/device namespaces before any filesystem metadata lookup.
    if os.fspath(path).replace("/", "\\").startswith("\\\\"):
        raise DiagnosticInputError()
    requested = Path(path).absolute()
    if os.name == "nt" and (
        requested.anchor.startswith("\\\\") or _drive_type(requested.anchor) not in (2, 3, 6)
    ):
        # Only local removable/fixed/RAM drives. Unknown and mapped network
        # drives fail closed; querying the local drive type does not read a file.
        raise DiagnosticInputError()
    # Inspect ancestors first so a redirected parent cannot cause a lookup of
    # the leaf on a remote filesystem before that parent is refused.
    if any(
        part.is_symlink() or part.is_junction()
        for part in reversed((requested, *requested.parents))
    ):
        raise DiagnosticInputError()
    resolved = requested.resolve(strict=True)
    if resolved == ROOT or ROOT in resolved.parents:
        raise DiagnosticInputError()
    before = resolved.lstat()
    _regular_private(before)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(resolved, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        _regular_private(opened)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise DiagnosticInputError()
        raw = stream.read(MAX_FILE_BYTES + 1)
    if not 1 <= len(raw) <= MAX_FILE_BYTES:
        raise DiagnosticInputError()
    return raw


def _segment(raw):
    if not re.fullmatch(rb"[A-Za-z0-9_-]+", raw):
        raise DiagnosticInputError()
    decoded = base64.b64decode(raw + b"=" * (-len(raw) % 4), altchars=b"-_", validate=True)
    if base64.urlsafe_b64encode(decoded).rstrip(b"=") != raw:
        raise DiagnosticInputError()
    return decoded


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticInputError()
        result[key] = value
    return result


def _reject_constant(_value):
    raise DiagnosticInputError()


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise DiagnosticInputError()
    return result


def _object(raw):
    result = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )
    if not isinstance(result, dict):
        raise DiagnosticInputError()
    return result


def _date_type(claims, name):
    if name not in claims:
        return "missing"
    return {
        type(None): "null",
        bool: "boolean",
        int: "number",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }[type(claims[name])]


def _number(value):
    try:
        if type(value) in (int, float) and math.isfinite(value):
            return value
    except OverflowError:
        pass
    return None


def _difference(left, right):
    if left is None or right is None:
        return None
    try:
        return _number(left - right)
    except OverflowError:
        return None


def diagnose_file(path, *, now=None):
    """Read only this file; return a fixed allowlist, never raw times or claims.

    A decoded report (and exit 0) means only that parsing completed. The data
    and signature remain unverified. All failures have the same neutral error.
    """
    try:
        raw = _read_file(path).strip(b" \t\r\n")
        parts = raw.split(b".")
        if len(parts) != 3:
            raise DiagnosticInputError()
        header, payload, _signature = (_segment(part) for part in parts)
        _object(header)
        claims = _object(payload)
        instant = _number(time.time() if now is None else now)
        if instant is None:
            raise DiagnosticInputError()
        issued, expires, not_before = (_number(claims.get(name)) for name in ("iat", "exp", "nbf"))
        lifetime = _difference(expires, issued)
        return {
            "kind": MARKER,
            "status": "DECODED",
            "signature_verified": False,
            "iat_type": _date_type(claims, "iat"),
            "exp_type": _date_type(claims, "exp"),
            "nbf_type": _date_type(claims, "nbf"),
            "numeric_dates_finite": issued is not None
            and expires is not None
            and ("nbf" not in claims or not_before is not None),
            "lifetime_seconds": lifetime,
            "age_seconds": _difference(instant, issued),
            "nbf_offset_seconds": _difference(not_before, instant),
            "lifetime_exceeds_300": None if lifetime is None else lifetime > 300,
        }
    except Exception:
        # File/JSON/OS exceptions may contain private paths or input fragments.
        raise DiagnosticInputError() from None


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise DiagnosticInputError()


def main(argv=None):
    parser = _Parser(
        prog="token_diagnostics",
        description="UNVERIFIED_DIAGNOSTIC: offline measurements; no authentication decision.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--token-file", required=True, help="Private token file outside the checkout"
    )
    try:
        args = parser.parse_args(argv)
        report = diagnose_file(args.token_file)
    except Exception:
        print(json.dumps(REJECTED, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
