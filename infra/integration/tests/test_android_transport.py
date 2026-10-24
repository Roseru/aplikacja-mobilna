"""Ownership fences prevent changing another device, route or ADB mapping."""

import json

import pytest

from infra.integration.android_transport import Transport


def tunnel(monkeypatch):
    transport = Transport("adb", "emulator-5560", "owned-test", "192.168.3.162", 18443)
    monkeypatch.setattr(transport, "guard", lambda: "current-boot")
    monkeypatch.setattr(transport, "rules", lambda: [])
    monkeypatch.setattr(transport, "reverse", lambda: [])
    mutations = []
    monkeypatch.setattr(transport, "ipt", lambda *args: mutations.append(args))
    monkeypatch.setattr(transport, "call", lambda *args: mutations.append(args))
    return transport, mutations


@pytest.mark.parametrize("serial", ["physical-phone", "127.0.0.1:5555", "emulator-5560;id"])
def test_refuses_non_emulator_or_injected_serial(serial):
    with pytest.raises(ValueError, match="emulator"):
        Transport("adb", serial, "owned-test", "192.168.3.162", 18443)


@pytest.mark.parametrize("host", ["8.8.8.8", "127.0.0.1", "169.254.1.2"])
def test_refuses_non_private_identity(host):
    with pytest.raises(ValueError, match="private IPv4"):
        Transport("adb", "emulator-5560", "owned-test", host, 18443)


def test_connect_preserves_foreign_reverse_mapping(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    monkeypatch.setattr(transport, "reverse", lambda: [["host-1", "tcp:18443", "tcp:19999"]])
    lease = tmp_path / "lease.json"
    with pytest.raises(RuntimeError, match="not overwritten"):
        transport.connect(lease)
    assert mutations == []
    assert not lease.exists()


def test_connect_preserves_existing_chain(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    monkeypatch.setattr(transport, "rules", lambda: ["-N O3_APK_18443"])
    with pytest.raises(RuntimeError, match="not overwritten"):
        transport.connect(tmp_path / "lease.json")
    assert mutations == []


def test_connect_preserves_existing_lease(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    lease.write_text("previous owner")
    with pytest.raises(FileExistsError):
        transport.connect(lease)
    assert lease.read_text() == "previous owner"
    assert mutations == []


def test_disconnect_refuses_previous_boot(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    lease.write_text(json.dumps(transport.specification("old-boot")))
    with pytest.raises(RuntimeError, match="another origin, AVD or boot"):
        transport.disconnect(lease)
    assert mutations == []
    assert lease.exists()


def test_disconnect_does_not_flush_foreign_chain_rule(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    lease.write_text(json.dumps(transport.specification("current-boot")))
    monkeypatch.setattr(transport, "rules", lambda: ["-N O3_APK_18443", "-A O3_APK_18443 -j DROP"])
    with pytest.raises(RuntimeError, match="unrelated rules"):
        transport.disconnect(lease)
    assert mutations == []
    assert lease.exists()


def test_wrong_avd_refused_before_mutation(monkeypatch, tmp_path):
    transport = Transport("adb", "emulator-5560", "owned-test", "192.168.3.162", 18443)
    calls = []

    def wrong_device(*args):
        calls.append(args)
        return "someone-else\nOK"

    monkeypatch.setattr(transport, "call", wrong_device)
    with pytest.raises(RuntimeError, match="owned AVD"):
        transport.connect(tmp_path / "lease.json")
    assert calls == [("emu", "avd", "name")]


def test_ensure_preserves_old_boot_receipt_before_new_connect(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    original = json.dumps(transport.specification("old-boot")).encode()
    lease.write_bytes(original)
    connected = []
    monkeypatch.setattr(transport, "connect", lambda path: connected.append(path))
    transport.ensure(lease)
    assert connected == [lease] and mutations == [] and not lease.exists()
    assert [p.read_bytes() for p in tmp_path.glob("lease.json.stale-*.json")] == [original]


@pytest.mark.parametrize("collision", ["chain", "reverse", "foreign", "archive"])
def test_ensure_never_retires_ambiguous_ownership(monkeypatch, tmp_path, collision):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    record = transport.specification("old-boot")
    if collision == "foreign":
        record["avd"] = "someone-else"
    raw = json.dumps(record).encode()
    lease.write_bytes(raw)
    if collision == "chain":
        monkeypatch.setattr(transport, "rules", lambda: ["-N O3_APK_18443"])
    if collision == "reverse":
        monkeypatch.setattr(transport, "reverse", lambda: [["host-1", "tcp:18443", "tcp:19999"]])
    if collision == "archive":
        import hashlib

        archive = lease.with_name(
            lease.name + ".stale-" + hashlib.sha256(raw).hexdigest() + ".json"
        )
        archive.write_text("preserved")
    with pytest.raises((RuntimeError, FileExistsError)):
        transport.ensure(lease)
    assert lease.read_bytes() == raw and mutations == []


def test_ensure_rechecks_current_boot_instead_of_replacing_it(monkeypatch, tmp_path):
    transport, mutations = tunnel(monkeypatch)
    lease = tmp_path / "lease.json"
    lease.write_text(json.dumps(transport.specification("current-boot")))
    checked = []
    monkeypatch.setattr(transport, "check", lambda path: checked.append(path))
    transport.ensure(lease)
    assert checked == [lease] and mutations == []
    assert not list(tmp_path.glob("*.stale-*"))
