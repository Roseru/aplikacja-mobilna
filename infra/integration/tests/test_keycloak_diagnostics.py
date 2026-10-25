"""Synthetic offline diagnostics and a component reproducer, never real PKCE."""

import asyncio
import base64
import io
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import AuthFailure, OIDCVerifier
from infra.local.keycloak import token_diagnostics as diagnostics

CANARY = "PRIVATE-CANARY-never-emit"
REPORT_KEYS = {
    "kind",
    "status",
    "signature_verified",
    "iat_type",
    "exp_type",
    "nbf_type",
    "numeric_dates_finite",
    "lifetime_seconds",
    "age_seconds",
    "nbf_offset_seconds",
    "lifetime_exceeds_300",
}


def segment(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def compact(payload, header=b'{"alg":"RS256","kid":"PRIVATE-CANARY-never-emit"}'):
    return b".".join((segment(header), segment(payload), segment(b"unverified-signature")))


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / (CANARY + ".jwt")
    path.write_bytes(compact(json.dumps({"iat": 1000, "exp": 1300}).encode()))
    path.chmod(0o600)
    return path


def write_claims(path, claims):
    path.write_bytes(compact(json.dumps(claims).encode()))


def test_fixed_allowlist_never_returns_identifiers_or_absolute_times(token_file):
    write_claims(
        token_file,
        {
            "iat": 1000,
            "exp": 1301,
            "nbf": 1002,
            **dict.fromkeys(("sub", "iss", "aud", "jti", "password", "access_token"), CANARY),
            "resource_access": {CANARY: {"roles": [CANARY]}},
            CANARY: {"nested": CANARY},
        },
    )
    report = diagnostics.diagnose_file(token_file, now=1010)
    assert set(report) == REPORT_KEYS
    assert report == {
        "kind": "UNVERIFIED_DIAGNOSTIC",
        "status": "DECODED",
        "signature_verified": False,
        "iat_type": "number",
        "exp_type": "number",
        "nbf_type": "number",
        "numeric_dates_finite": True,
        "lifetime_seconds": 301,
        "age_seconds": 10,
        "nbf_offset_seconds": -8,
        "lifetime_exceeds_300": True,
    }
    assert CANARY not in json.dumps(report)


@pytest.mark.parametrize("lifetime", [-1, 0, 0.001, 299, 300, 300.001, 301])
def test_numeric_boundaries_are_measurements_not_auth_decisions(token_file, lifetime):
    write_claims(token_file, {"iat": 1000, "exp": 1000 + lifetime})
    report = diagnostics.diagnose_file(token_file, now=999)
    assert report["lifetime_seconds"] == pytest.approx(lifetime)
    assert report["lifetime_exceeds_300"] is (lifetime > 300)
    assert report["age_seconds"] == -1
    assert report["nbf_type"] == "missing" and report["nbf_offset_seconds"] is None
    assert report["signature_verified"] is False


@pytest.mark.parametrize("name", ["iat", "exp", "nbf"])
@pytest.mark.parametrize(
    "value,label",
    [
        (None, "null"),
        (True, "boolean"),
        (False, "boolean"),
        (CANARY, "string"),
        ([CANARY], "array"),
        ({CANARY: CANARY}, "object"),
    ],
)
def test_types_never_coerce_or_echo_private_values(token_file, name, value, label):
    claims = {"iat": 1000, "exp": 1300, "nbf": 1000, name: value}
    write_claims(token_file, claims)
    report = diagnostics.diagnose_file(token_file, now=1001)
    assert report[f"{name}_type"] == label
    assert report["numeric_dates_finite"] is False
    assert CANARY not in json.dumps(report)
    if name in ("iat", "exp"):
        assert report["lifetime_seconds"] is report["lifetime_exceeds_300"] is None
    else:
        assert report["nbf_offset_seconds"] is None


def test_missing_and_extreme_numeric_dates_remain_bounded_json(token_file):
    for claims in ({}, {"iat": -(10**308), "exp": 1e308, "nbf": 10**1000}):
        write_claims(token_file, claims)
        report = diagnostics.diagnose_file(token_file, now=1e308)
        assert report["lifetime_seconds"] is None
        assert report["age_seconds"] is None
        assert report["nbf_offset_seconds"] is None
        assert report["numeric_dates_finite"] is False
        assert len(json.dumps(report, allow_nan=False)) < 500


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not-a-token",
        b"Bearer abc.def.ghi",
        b"a.b.c.d",
        b"e30.e30.",
        b"e30=.e30.c2ln",
        b"e31.e30.c2ln",
        b"a.e30.c2ln",
        b"e30.e30.c2ln!",
        b"\xff",
        compact(b"[]"),
        compact(b"null"),
        compact(b"{}", header=b"[]"),
        compact(b'{"iat":1000,"iat":1001}'),
        compact(b'{"a":{"x":1,"x":2}}'),
        compact(b'{"iat":NaN}'),
        compact(b'{"exp":Infinity}'),
        compact(b'{"nbf":-Infinity}'),
        compact(b'{"ignored":1e999}'),
        compact(b'{"iat":'),
        compact(b'{"iat":"\xff"}'),
        compact(b'{"' + CANARY.encode() + b'":'),
        compact(b"[" * 1100 + b"]" * 1100),
        compact(b'{"iat":' + b"9" * 4400 + b"}"),
        b"\xef\xbb\xbf" + compact(b"{}"),
    ],
)
def test_bad_format_has_only_neutral_cli_output(token_file, capsys, raw):
    token_file.write_bytes(raw)
    assert diagnostics.main(["--token-file", str(token_file)]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == diagnostics.REJECTED
    assert captured.err == "" and CANARY not in captured.out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        [CANARY],
        ["--token", CANARY],
        ["--token-file"],
        ["--token-file", CANARY, "--jwt", CANARY],
        ["--token-file", "-"],
    ],
)
def test_argument_errors_never_echo_arguments_or_accept_stdin(argv, capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(CANARY))
    assert diagnostics.main(argv) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == diagnostics.REJECTED
    assert captured.err == "" and CANARY not in captured.out
    assert sys.stdin.tell() == 0


def test_exact_16kib_limit_includes_surrounding_whitespace(token_file, capsys):
    token = token_file.read_bytes()
    token_file.write_bytes(token + b"\n" * (diagnostics.MAX_FILE_BYTES - len(token)))
    assert diagnostics.main(["--token-file", str(token_file)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "DECODED"
    token_file.write_bytes(token_file.read_bytes() + b"\n")
    assert diagnostics.main(["--token-file", str(token_file)]) == 2
    assert json.loads(capsys.readouterr().out) == diagnostics.REJECTED


def test_oversized_file_rejected_before_open_or_json(token_file, monkeypatch):
    token_file.write_bytes(b"x" * (diagnostics.MAX_FILE_BYTES + 1))

    def forbidden(*args, **kwargs):
        pytest.fail("oversized input reached open/parser")

    monkeypatch.setattr(diagnostics.os, "open", forbidden)
    monkeypatch.setattr(diagnostics.json, "loads", forbidden)
    with pytest.raises(diagnostics.DiagnosticInputError, match="^diagnostic input rejected$"):
        diagnostics.diagnose_file(token_file)


def test_growing_file_is_read_at_most_limit_plus_one_before_parser(token_file, monkeypatch):
    fdopen = os.fdopen
    reads = []

    class GrowingFile:
        def __init__(self, fd, mode):
            self.stream = fdopen(fd, mode)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            reads.append(size)
            return b"x" * size

    def forbidden(*args, **kwargs):
        pytest.fail("growing oversized input reached parser")

    monkeypatch.setattr(diagnostics.os, "fdopen", GrowingFile)
    monkeypatch.setattr(diagnostics.json, "loads", forbidden)
    with pytest.raises(diagnostics.DiagnosticInputError):
        diagnostics.diagnose_file(token_file)
    assert reads == [diagnostics.MAX_FILE_BYTES + 1]


@pytest.mark.parametrize("kind", ["missing", "directory", "hardlink", "checkout"])
def test_only_selected_private_regular_file_is_accepted(token_file, monkeypatch, kind):
    path = token_file
    if kind == "missing":
        path = path.with_name(CANARY + "missing")
    elif kind == "directory":
        path = path.parent
    elif kind == "hardlink":
        os.link(path, path.with_suffix(".link"))
    else:
        monkeypatch.setattr(diagnostics, "ROOT", path.parent)
    with pytest.raises(diagnostics.DiagnosticInputError) as error:
        diagnostics.diagnose_file(path)
    assert str(error.value) == "diagnostic input rejected"


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission/owner checks; Windows uses operator ACL"
)
def test_posix_group_readable_or_foreign_owned_file_is_rejected(token_file, monkeypatch):
    token_file.chmod(0o640)
    with pytest.raises(diagnostics.DiagnosticInputError):
        diagnostics.diagnose_file(token_file)
    token_file.chmod(0o600)
    monkeypatch.setattr(os, "getuid", lambda: token_file.stat().st_uid + 1)
    with pytest.raises(diagnostics.DiagnosticInputError):
        diagnostics.diagnose_file(token_file)


@pytest.mark.parametrize("parent", [False, True])
def test_symlinks_are_rejected(token_file, parent):
    link = token_file.parent / "redirect"
    try:
        link.symlink_to(token_file.parent if parent else token_file, target_is_directory=parent)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(diagnostics.DiagnosticInputError):
        diagnostics.diagnose_file(link / token_file.name if parent else link)


def test_read_only_offline_no_subprocess_no_claim_directed_io(token_file, monkeypatch, capsys):
    write_claims(
        token_file,
        {
            "iat": 1000,
            "exp": 1300,
            "iss": "https://" + CANARY,
            "jku": "https://" + CANARY,
            "x5u": str(token_file.with_suffix(".unread")),
        },
    )
    before = token_file.read_bytes(), token_file.stat().st_mtime_ns
    opened = []
    original_open = os.open

    def only_input(path, flags, *args, **kwargs):
        assert Path(path) == token_file
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0
        opened.append(path)
        return original_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("diagnostics attempted network or subprocess")

    monkeypatch.setattr(os, "open", only_input)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert diagnostics.main(["--token-file", str(token_file)]) == 0
    captured = capsys.readouterr()
    assert CANARY not in captured.out and captured.err == ""
    assert len(opened) == 1
    assert (token_file.read_bytes(), token_file.stat().st_mtime_ns) == before
    assert list(token_file.parent.iterdir()) == [token_file]


def test_unexpected_file_errors_and_bad_clock_are_neutral(token_file, monkeypatch, capsys):
    for now in (True, float("nan"), float("inf"), "1000"):
        with pytest.raises(diagnostics.DiagnosticInputError):
            diagnostics.diagnose_file(token_file, now=now)

    def fail(*args):
        raise PermissionError(CANARY)

    monkeypatch.setattr(diagnostics, "_read_file", fail)
    assert diagnostics.main(["--token-file", str(token_file)]) == 2
    assert capsys.readouterr().out.strip() == json.dumps(diagnostics.REJECTED, sort_keys=True)


def test_cli_entry_point_and_help_are_safe(token_file):
    script = Path(diagnostics.__file__)
    for args, expected in ((["--token-file", str(token_file)], 0), ([CANARY], 2)):
        result = subprocess.run(
            [sys.executable, "-I", str(script), *args], capture_output=True, text=True, timeout=10
        )
        assert result.returncode == expected and result.stderr == ""
        assert CANARY not in result.stdout
        assert json.loads(result.stdout)["kind"] == "UNVERIFIED_DIAGNOSTIC"
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--help"], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0 and result.stderr == ""
    assert "UNVERIFIED_DIAGNOSTIC" in result.stdout


@pytest.mark.parametrize("expiration_read_ms,expected_lifetime", [(1000999, 300), (1001000, 301)])
def test_two_clock_reads_component_reproducer_with_real_signature_and_strict_verifier(
    token_file,
    expiration_read_ms,
    expected_lifetime,
):
    # Model only TokenManager 26.8.0 initToken/getTokenExpiration and
    # JsonWebToken.issuedNow. Session expiry is later and does not clamp exp.
    # Deterministic clock sequence straddles a second; no sleeps or Keycloak.
    reads = iter((1000999, expiration_read_ms))
    issued = next(reads) // 1000
    expires = (next(reads) + 300 * 1000) // 1000
    assert expires - issued == expected_lifetime
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    public.update(kid="synthetic", alg="RS256", use="sig")
    claims = {
        "iss": "https://identity.example/realms/test",
        "aud": "calorie-api",
        "sub": "synthetic",
        "typ": "Bearer",
        "iat": issued,
        "exp": expires,
        "resource_access": {"calorie-api": {"roles": ["user"]}},
    }
    token = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "synthetic"})
    token_file.write_text(token, encoding="ascii")
    report = diagnostics.diagnose_file(token_file, now=1001)
    assert report["lifetime_seconds"] == expected_lifetime
    assert report["signature_verified"] is False

    # Independent cryptographic check proves the failing 301-second case has
    # a good signature. Every other trust/claim input is held constant.
    assert (
        jwt.decode(
            token,
            private.public_key(),
            algorithms=["RS256"],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        == claims
    )
    requests = []

    def jwks(request):
        requests.append(request)
        return httpx.Response(200, json={"keys": [public]})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(jwks)) as client:
            verifier = OIDCVerifier(
                Settings(
                    database_url="postgresql+psycopg://unused@localhost/calorie_test",
                    oidc_issuer=claims["iss"],
                    oidc_jwks_url="https://keys.example/certs",
                ),
                client=client,
                wall_clock=lambda: 1001,
                monotonic=lambda: 0,
            )
            assert verifier.SKEW == 60
            if expected_lifetime == 300:
                assert (await verifier.verify(token)).roles == frozenset({"user"})
            else:
                with pytest.raises(AuthFailure) as failure:
                    await verifier.verify(token)
                assert (failure.value.status, failure.value.code) == (401, "unauthorized")
                assert token not in str(failure.value)

    asyncio.run(scenario())
    assert len(requests) == 1  # Mock transport only; no real JWKS or PKCE.
    # Altered signatures still decode diagnostically. The report is never auth.
    prefix = token.rsplit(".", 1)[0].encode()
    token_file.write_bytes(prefix + b"." + segment(b"invalid-signature"))
    assert diagnostics.diagnose_file(token_file, now=1001) == report
