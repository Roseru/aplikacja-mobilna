"""Small ownership guards plus an explicit Windows-only real SMTP acceptance."""

import contextlib
import hashlib
import json
import os
import re
import smtplib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

import pytest

from infra.local.integration import mail_sink as mail


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setattr(mail, "ROOT", tmp_path)
    state = tmp_path / ".tools/mail"
    state.mkdir(parents=True)
    (state / "mailpit.exe").write_bytes(b"fixture binary")
    monkeypatch.setattr(mail, "EXE_SHA256", mail.digest(state / "mailpit.exe"))
    monkeypatch.setattr(mail, "private_acl", lambda _: True)
    mail.write_json(
        state / "config.json",
        {
            "format": "calorie-native-mail/v1",
            "state": str(state),
            "version": mail.VERSION,
            "zip_sha256": mail.ZIP_SHA256,
            "exe_sha256": mail.EXE_SHA256,
            "command": mail.command(state),
        },
    )
    record = {
        "pid": 123,
        "created": 1000,
        "executable": str(state / "mailpit.exe"),
        "command": subprocess.list2cmdline(mail.command(state)),
    }
    mail.write_json(state / "process.json", record)
    monkeypatch.setattr(mail, "identity", lambda _: record.copy())
    monkeypatch.setattr(
        mail,
        "listeners",
        lambda: [
            {"address": "127.0.0.1", "port": p, "pid": record["pid"]}
            for p in (mail.SMTP_PORT, mail.HTTP_PORT)
        ],
    )
    monkeypatch.setattr(mail, "lifecycle_lock", lambda _: contextlib.nullcontext())
    return state, record


@pytest.mark.parametrize("relative", ["elsewhere", ".tools", ".tools/../escape"])
def test_state_cannot_escape_own_tools(tmp_path, monkeypatch, relative):
    monkeypatch.setattr(mail, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        mail.confined(tmp_path / relative)


def test_existing_state_is_preserved_before_archive_is_read(owned):
    state, _ = owned
    before = {p.name: p.read_bytes() for p in state.iterdir()}
    with pytest.raises(FileExistsError):
        mail.initialize(state, archive=Path("does-not-exist.zip"))
    assert before == {p.name: p.read_bytes() for p in state.iterdir()}


def test_command_is_loopback_bounded_and_without_external_features(owned):
    state, _ = owned
    command = mail.command(state)
    assert command[command.index("--smtp") + 1] == "127.0.0.1:26525"
    assert command[command.index("--listen") + 1] == "127.0.0.1:28025"
    assert command[command.index("--max") + 1] == "100"
    assert command[command.index("--max-message-size") + 1] == "1"
    assert "--ui-auth-file" in command and "--allowed-hosts" in command
    assert "--disable-version-check" in command and "--smtp-disable-rdns" in command
    assert not any(
        "relay" in value or "forward" in value or "webhook" in value for value in command
    )


@pytest.mark.parametrize("domain", ["invalid.example", "example.test", "calorie-demo.test"])
def test_exact_allowed_domains(domain):
    assert re.fullmatch(mail.RECIPIENTS, "test@" + domain)


@pytest.mark.parametrize(
    "recipient",
    [
        "x@external.example",
        "x@example.test.evil",
        "x@sub.example.test",
        "x@y@example.test",
        "x@exampleXtest",
        "x@EXAMPLE.TEST",
    ],
)
def test_other_recipient_spellings_are_refused(recipient):
    assert not re.fullmatch(mail.RECIPIENTS, recipient)


def test_no_inherited_provider_options(monkeypatch):
    monkeypatch.setenv("MP_SMTP_RELAY_ALL", "true")
    monkeypatch.setenv("MP_SMTP_FORWARD_CONFIG", "foreign")
    monkeypatch.setenv("MP_WEBHOOK_URL", "https://foreign.invalid")
    monkeypatch.setenv("MP_DATABASE", "foreign")
    monkeypatch.setenv("HTTP_PROXY", "http://foreign.invalid")
    assert not any(key.startswith("MP_") or "PROXY" in key for key in mail.clean_env())


@pytest.mark.parametrize(
    "field,value",
    [
        ("pid", 321),
        ("created", 2000),
        ("executable", "foreign.exe"),
        ("command", "foreign command"),
    ],
)
def test_reused_pid_or_other_command_never_stopped(owned, monkeypatch, field, value):
    state, record = owned
    changed = record | {field: value}
    monkeypatch.setattr(mail, "identity", lambda _: changed)
    stopped = []
    monkeypatch.setattr(mail, "stop_exact", lambda *_: stopped.append(True))
    with pytest.raises(RuntimeError):
        mail.down(state)
    assert stopped == []


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"address": "0.0.0.0", "port": 26525, "pid": 123}],
        [{"address": "127.0.0.1", "port": 26525, "pid": 456}],
        [{"address": "::", "port": 28025, "pid": 123}],
    ],
)
def test_missing_wildcard_or_foreign_ports_block_stop(owned, monkeypatch, rows):
    state, _ = owned
    monkeypatch.setattr(mail, "listeners", lambda: rows)
    stopped = []
    monkeypatch.setattr(mail, "stop_exact", lambda *_: stopped.append(True))
    with pytest.raises(RuntimeError):
        mail.down(state)
    assert stopped == []


def test_stale_record_with_foreign_listener_blocks_up(owned, monkeypatch):
    state, _ = owned
    monkeypatch.setattr(mail, "identity", lambda _: (_ for _ in ()).throw(ProcessLookupError()))
    with pytest.raises(RuntimeError, match="Foreign listener"):
        mail.up(state)


def test_down_stopped_process_preserves_mail_and_history(owned, monkeypatch):
    state, _ = owned
    (state / "mailpit.db").write_bytes(b"retained database")
    monkeypatch.setattr(mail, "identity", lambda _: (_ for _ in ()).throw(ProcessLookupError()))
    monkeypatch.setattr(mail, "listeners", list)
    assert mail.down(state) == {"running": False, "preserved": True}
    assert (state / "mailpit.db").read_bytes() == b"retained database"
    assert (state / "process.json").exists()


def test_up_is_idempotent_for_exact_owned_process(owned, monkeypatch):
    state, _ = owned
    monkeypatch.setattr(mail, "_mailbox_json", lambda _: {"total": 2})
    monkeypatch.setattr(mail.subprocess, "Popen", lambda *_a, **_k: pytest.fail("duplicate start"))
    assert mail.up(state)["messages"] == 2


@pytest.mark.parametrize("change", ["binary", "command", "acl"])
def test_changed_pin_config_or_acl_blocks_lifecycle(owned, monkeypatch, change):
    state, _ = owned
    if change == "binary":
        (state / "mailpit.exe").write_bytes(b"changed")
    elif change == "command":
        config = json.loads((state / "config.json").read_text())
        config["command"].append("--smtp-relay-all")
        mail.write_json(state / "config.json", config)
    else:
        monkeypatch.setattr(mail, "private_acl", lambda _: False)
    with pytest.raises((ValueError, PermissionError)):
        mail.down(state)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://external.example",
        "//external.example",
        "/api/v1/send",
        "/api/v1/messages?x=1",
    ],
)
def test_private_reader_cannot_send_or_redirect_to_arbitrary_endpoint(owned, endpoint):
    state, _ = owned
    with pytest.raises(ValueError):
        mail._mailbox_json(state, endpoint)


def test_cli_never_renders_untrusted_secret_exception(owned, monkeypatch, capsys):
    state, _ = owned
    secret = "secret-action-link-and-password"
    monkeypatch.setattr(mail, "status", lambda _: (_ for _ in ()).throw(RuntimeError(secret)))
    assert mail.main(["status", "--state", str(state)]) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert json.loads(output.err) == {"ok": False, "error_type": "RuntimeError"}


@pytest.mark.skipif(
    os.name != "nt" or not os.environ.get("NATIVE_MAIL_SINK_ARCHIVE"),
    reason="Explicit pinned local archive required for Windows real SMTP acceptance",
)
def test_real_smtp_read_refusal_restart_and_foreign_process_preservation():
    state = mail.ROOT / ".tools" / ("mail-acceptance-" + uuid4().hex)
    mail.initialize(state, archive=Path(os.environ["NATIVE_MAIL_SINK_ARCHIVE"]))
    receipt = {"format": "native-mail-acceptance/v1", "passed": False}
    try:
        first = mail.up(state)
        saved = mail.saved_record(state)
        assert mail.up(state)["running"]
        assert mail.saved_record(state) == saved
        synthetic = "synthetic-mail-" + uuid4().hex
        wire = (
            "From: noreply@calorie-demo.test\r\nTo: synthetic@example.test\r\n"
            "Subject: local synthetic verification\r\n\r\n" + synthetic + "\r\n"
        ).encode()
        with smtplib.SMTP("127.0.0.1", mail.SMTP_PORT, timeout=5) as smtp:
            assert (
                smtp.sendmail("noreply@calorie-demo.test", ["synthetic@example.test"], wire) == {}
            )
            smtp.mail("noreply@calorie-demo.test")
            assert smtp.rcpt("synthetic@outside.invalid")[0] == 550
            smtp.rset()
            assert smtp.mail("noreply@calorie-demo.test", options=["SIZE=1048577"])[0] == 552
        listing = mail.mailbox_json(state)
        assert listing["total"] == first["messages"] + 1
        message_id = listing["messages"][0]["ID"]
        content = mail.mailbox_json(state, "/api/v1/message/" + message_id)
        assert synthetic in content["Text"]
        content_hash = hashlib.sha256(content["Text"].encode()).hexdigest()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            opener.open(f"http://127.0.0.1:{mail.HTTP_PORT}/api/v1/messages", timeout=3)
        assert unauthorized.value.code == 401
        hostile = urllib.request.Request(
            f"http://127.0.0.1:{mail.HTTP_PORT}/api/v1/messages",
            headers={"Host": "outside.invalid"},
        )
        with pytest.raises(urllib.error.HTTPError) as rebinding:
            opener.open(hostile, timeout=3)
        assert rebinding.value.code == 403
        assert mail.private_acl(state)
        assert mail.down(state)["preserved"]
        assert not mail.status(state)["running"]
        assert mail.up(state)["messages"] == listing["total"]
        after = mail.mailbox_json(state, "/api/v1/message/" + message_id)
        assert hashlib.sha256(after["Text"].encode()).hexdigest() == content_hash
        assert mail.saved_record(state)["created"] != saved["created"]
        mail.down(state)
        # A separate owned test child occupies the target SMTP port. The helper
        # must refuse both up and down without stopping that child.
        child_code = (
            "import socket,time; s=socket.socket(); "
            f"s.bind(('127.0.0.1',{mail.SMTP_PORT})); s.listen(); time.sleep(45)"
        )
        foreign = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **mail.FLAGS,
        )
        try:
            for _ in range(50):
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", mail.SMTP_PORT)) == 0:
                        break
                time.sleep(0.1)
            assert foreign.poll() is None
            with pytest.raises(RuntimeError, match="Foreign listener"):
                mail.up(state)
            with pytest.raises(RuntimeError, match="Foreign listener"):
                mail.down(state)
            assert foreign.poll() is None
        finally:
            foreign.terminate()
            foreign.wait(timeout=10)
        receipt |= {
            "passed": True,
            "smtp_to_private_http": True,
            "recipient_refused": True,
            "size_refused": True,
            "ui_auth_required": True,
            "host_refused": True,
            "restart_preserved": True,
            "foreign_process_preserved": True,
            "messages": listing["total"],
            "synthetic_text_sha256": content_hash,
            "exe_sha256": mail.EXE_SHA256,
            "zip_sha256": mail.ZIP_SHA256,
        }
    finally:
        # Stop only an exactly qualified helper, retaining all mail and FAIL data.
        try:
            mail.down(state)
        finally:
            mail.write_json(state / "acceptance.json", receipt)
