"""Worker LOGIN configuration and secret handling; no database mutations here."""

import importlib.util
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ai_worker_provision_unit", ROOT / "infra/local/provision_ai_worker.py"
)
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


@pytest.mark.parametrize(
    "login,password",
    [
        ("worker", " "),
        ("ai-'\"-😀", " '\" zażółć 😀 "),
        ("a" * 63, "strong-unit-password"),
        ("ż" * 31 + "a", "utf8-unit-password"),
    ],
)
def test_configuration_preserves_password_and_login_bytes(login, password):
    assert helper.configuration({"AI_WORKER_LOGIN": login, "AI_WORKER_PASSWORD": password}) == (
        login.encode(),
        password.encode(),
    )


@pytest.mark.parametrize(
    "login,password",
    [
        ("", "secret"),
        ("worker", ""),
        ("a" * 64, "secret"),
        ("ż" * 32, "secret"),
        ("worker\x00", "secret"),
        ("worker", "secret\x00"),
        ("worker", "\ud800"),
        ("\ud800", "secret"),
        ("pg_privileged", "secret"),
        *[(name, "secret") for name in sorted(helper.RESERVED)],
    ],
)
def test_invalid_or_reserved_configuration_has_only_controlled_code(login, password):
    with pytest.raises(helper.ProvisionError) as error:
        helper.configuration({"AI_WORKER_LOGIN": login, "AI_WORKER_PASSWORD": password})
    assert str(error.value) == "invalid_configuration"


def test_same_17_startup_protections_are_reused_unchanged():
    assert len(helper._GUARD.SESSION_SETTINGS) == 17
    assert helper.STARTUP_OPTIONS == helper._GUARD.STARTUP_OPTIONS
    assert helper.verify_session is helper._GUARD.verify_session
    assert "track_activities=off" in helper.STARTUP_OPTIONS
    assert "log_parameter_max_length_on_error=0" in helper.STARTUP_OPTIONS


def test_local_scram_and_role_checks_precede_password_write(monkeypatch):
    password = secrets.token_urlsafe(32).encode()
    verifier = b"SCRAM-SHA-256$synthetic-unit-verifier"
    events, statements = [], []

    class Context:
        def __enter__(self):
            return connection

        def __exit__(self, kind, *_):
            events.append("rollback" if kind else "commit")

    class Connection(Context):
        def transaction(self):
            return Context()

        def execute(self, statement, params=None):
            statements.append((statement, params))
            if statement == helper.PREPARE_SQL:
                events.append("prepare")
            elif statement == helper.VERIFY_ACL_SQL:
                events.append("ACL")
            elif statement == helper.PASSWORD_SQL:
                events.append("password")
            assert password.decode() not in statement

    def encrypt(actual, login, *, algorithm):
        assert actual == password and login == b"owned-worker"
        assert algorithm == b"scram-sha-256"
        events.append("encrypt")
        return verifier

    connection = Connection()
    connection.pgconn = SimpleNamespace(encrypt_password=encrypt)

    def connect(*args, **kwargs):
        assert args == ("",)
        assert kwargs["options"] == helper.STARTUP_OPTIONS
        assert kwargs["autocommit"] is True and kwargs["client_encoding"] == "UTF8"
        assert "password" not in kwargs
        return connection

    monkeypatch.setattr(helper.psycopg, "connect", connect)
    monkeypatch.setattr(helper, "verify_session", lambda connection: events.append("verify"))
    helper.provision(b"owned-worker", password)
    assert events == ["verify", "prepare", "ACL", "encrypt", "password", "ACL", "commit", "commit"]
    assert any(params == (verifier.decode(),) for _, params in statements)
    assert all(password.decode() not in str(params) for _, params in statements)


def test_provider_exception_diagnostics_are_never_printed(monkeypatch, capsys):
    secret = secrets.token_urlsafe(32)
    verifier = "SCRAM-SHA-256$" + secrets.token_urlsafe(64)
    monkeypatch.setenv("AI_WORKER_LOGIN", "owned-worker")
    monkeypatch.setenv("AI_WORKER_PASSWORD", secret)
    monkeypatch.setattr(sys, "argv", ["provision_ai_worker.py"])

    def failure(*args):
        raise RuntimeError("SQL/DSN/password/verifier " + secret + verifier)

    monkeypatch.setattr(helper, "provision", failure)
    assert helper.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "provisioning_failed\n"
    assert secret not in captured.out + captured.err and verifier not in captured.out + captured.err


def test_cli_does_not_accept_or_echo_secret_arguments(monkeypatch, capsys):
    secret = secrets.token_urlsafe(32)
    monkeypatch.setattr(sys, "argv", ["provision_ai_worker.py", secret])
    assert helper.main() == 3
    assert capsys.readouterr().err == "invalid_arguments\n"


def test_callable_revalidation_fails_before_connect(monkeypatch):
    monkeypatch.setattr(helper.psycopg, "connect", lambda *a, **k: pytest.fail("unsafe connect"))
    with pytest.raises(helper.ProvisionError):
        helper.provision(b"calorie_app_worker", b"secret")
