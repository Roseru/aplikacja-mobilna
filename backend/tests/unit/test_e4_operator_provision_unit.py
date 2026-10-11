"""Client validation and fail-closed secret handling for administrative provisioning."""

import importlib.util
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "operator_provision", ROOT / "infra/local/provision_deletion_operator.py"
)
PROVISION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROVISION)


@pytest.mark.parametrize(
    "case", ["whitespace", "quotes_unicode", "63_ascii_bytes", "63_utf8_bytes"]
)
def test_client_validation_preserves_password_and_utf8_login(case):
    password = secrets.token_urlsafe(32)
    login = "operator"
    if case == "whitespace":
        password = " "
    elif case == "quotes_unicode":
        password = " '\" Zażółć 😀 " + password + " "
        login = "operator-'\"-😀"
    elif case == "63_ascii_bytes":
        login = "a" * 63
    else:
        login = "ż" * 31 + "a"
    result = PROVISION.configuration(
        {"DELETION_OPERATOR_LOGIN": login, "DELETION_OPERATOR_PASSWORD": password}
    )
    if result != (login.encode("utf-8"), password.encode("utf-8")):
        pytest.fail("Client validation changed login/password bytes")


@pytest.mark.parametrize(
    "case", ["missing_login", "missing_password", "64_bytes", "utf8_overflow", "nul", "surrogate"]
)
def test_invalid_client_configuration_is_rejected_without_sensitive_diagnostics(case):
    login, password = "operator", secrets.token_urlsafe(32)
    if case == "missing_login":
        login = ""
    elif case == "missing_password":
        password = ""
    elif case == "64_bytes":
        login = "a" * 64
    elif case == "utf8_overflow":
        login = "ż" * 32
    elif case == "nul":
        password += "\x00"
    else:
        password += "\ud800"
    with pytest.raises(PROVISION.ProvisionError, match="^invalid_configuration$"):
        PROVISION.configuration(
            {"DELETION_OPERATOR_LOGIN": login, "DELETION_OPERATOR_PASSWORD": password}
        )


@pytest.mark.parametrize("setting", list(PROVISION.SESSION_SETTINGS))
def test_session_verification_rejects_each_ineffective_protection(setting):
    settings = PROVISION.SESSION_SETTINGS | {setting: "unexpected"}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, statement, parameters):
            assert "pg_settings" in statement
            assert set(parameters[0]) == set(PROVISION.SESSION_SETTINGS)

        def fetchall(self):
            return list(settings.items())

    connection = SimpleNamespace(info=SimpleNamespace(server_version=170011), cursor=Cursor)
    with pytest.raises(PROVISION.ProvisionError, match="^unsafe_session_configuration$"):
        PROVISION.verify_session(connection)


@pytest.mark.parametrize("version", [160000, 180000])
def test_unsupported_server_is_rejected_before_any_sql(version):
    connection = SimpleNamespace(info=SimpleNamespace(server_version=version))
    with pytest.raises(PROVISION.ProvisionError, match="^unsupported_server$"):
        PROVISION.verify_session(connection)


def test_raw_provider_exception_cannot_expose_secret_or_verifier(monkeypatch, capsys):
    secret = secrets.token_urlsafe(32)
    verifier = "SCRAM-SHA-256$" + secrets.token_urlsafe(64)
    monkeypatch.setenv("DELETION_OPERATOR_LOGIN", "operator")
    monkeypatch.setenv("DELETION_OPERATOR_PASSWORD", secret)
    monkeypatch.setattr(sys, "argv", ["provision_deletion_operator.py"])

    def fail(*_):
        raise ValueError("query/password/connection diagnostic: " + secret + verifier)

    monkeypatch.setattr(PROVISION, "provision", fail)
    assert PROVISION.main() == 1
    captured = capsys.readouterr()
    if secret in captured.out + captured.err or verifier in captured.out + captured.err:
        pytest.fail("Client diagnostic leaked confidential material")
    assert captured.out == ""
    assert captured.err == "provisioning_failed\n"


def test_secret_arguments_are_not_supported_or_echoed(monkeypatch, capsys):
    secret = secrets.token_urlsafe(32)
    monkeypatch.setattr(sys, "argv", ["provision_deletion_operator.py", secret])
    assert PROVISION.main() == 3
    captured = capsys.readouterr()
    if secret in captured.out + captured.err:
        pytest.fail("Client diagnostic echoed a confidential argument")
    assert captured.err == "invalid_arguments\n"
