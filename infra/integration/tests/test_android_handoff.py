"""Portable artifact integrity, relocation and exclusion of private operator state."""

import json
import shutil
import zipfile

import pytest

from infra.integration.android_handoff import FILES, digest, export, verify
from infra.integration.android_overlay import prepare
from infra.integration.run import certificates


def source(tmp_path):
    state = tmp_path / "original"
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"host": "192.168.3.162", "port": 18443}))
    certificates(state / "tls", "192.168.3.162")
    prepare(state, state / "overlay")
    ca = (state / "tls/ca.pem").read_bytes()
    (state / "public-ca.pem").write_bytes(ca)
    (state / "validation-0.8.10.apk").write_bytes(b"reference-apk")
    (state / "handoff.json").write_text(
        json.dumps(
            {
                "origin": "https://192.168.3.162:18443",
                "issuer": "https://192.168.3.162:18443/realms/calorie-dev",
                "api_base_url": "https://192.168.3.162:18443/api/v1",
                "application_id": "pl.roseru.kalorie.validation",
                "callback": "pl.roseru.kalorie.validation:/oauth2redirect",
                "apk_source": "b" * 40,
                "apk_version": "0.8.10",
                "apk_version_code": 21,
                "apk_sha256": digest(b"reference-apk"),
                "public_ca_sha256": digest(ca),
                "source_state": "C:/operator-private-path",
                "transport_serial": "emulator-5560",
            }
        )
    )
    (state / "credentials.json").write_text('{"secret": "do-not-export"}')
    (state / "transport-lease.json").write_text("operator-runtime-lease")
    return state


def unpack(tmp_path):
    state = source(tmp_path)
    output = tmp_path / "delivery.zip"
    result = export(state, output)
    target = tmp_path / "different $computer'" / "handoff"
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == set(FILES) | {"SHA256SUMS"}
        archive.extractall(target)
    return state, output, target, result


def test_delivery_relocates_overlay_without_secrets_or_leases(tmp_path):
    state, output, target, receipt = unpack(tmp_path)
    info = verify(target)
    assert receipt["bundle_sha256"] == digest(output.read_bytes())
    assert info["browser_apk_acceptance"] == "NOT_RUN_BY_HANDOFF_EXPORT"
    overlay = tmp_path / "recipient $scope'overlay"
    prepare(target, overlay)
    text = (overlay / "init.gradle").read_text()
    assert overlay.resolve().as_posix().replace("'", "\\'") in text
    assert str(state) not in text
    for path in target.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            for forbidden in (
                b"PRIVATE KEY",
                b"do-not-export",
                b"operator-private-path",
                b"operator-runtime-lease",
                b"emulator-5560",
            ):
                assert forbidden not in content


@pytest.mark.parametrize("member", ["validation.apk", "tls/ca.pem", "config.json"])
def test_changed_member_refused(tmp_path, member):
    _, _, target, _ = unpack(tmp_path)
    with (target / member).open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="Missing or changed"):
        verify(target)


def test_manifest_cannot_reference_private_or_parent_paths(tmp_path):
    _, _, target, _ = unpack(tmp_path)
    (target / "SHA256SUMS").write_text(f"{'0' * 64}  ../credentials.json\n")
    with pytest.raises(ValueError, match="Unexpected"):
        verify(target)


def test_missing_member_refused(tmp_path):
    _, _, target, _ = unpack(tmp_path)
    (target / "SHA256SUMS").write_text(
        "\n".join(
            line
            for line in (target / "SHA256SUMS").read_text().splitlines()
            if not line.endswith("  android_transport.py")
        )
    )
    with pytest.raises(ValueError, match="Incomplete"):
        verify(target)


def test_private_key_and_existing_delivery_are_preserved(tmp_path):
    state = source(tmp_path)
    output = tmp_path / "delivery.zip"
    export(state, output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        export(state, output)
    assert output.read_bytes() == before
    ca = state / "public-ca.pem"
    ca.write_bytes(ca.read_bytes() + (state / "tls/ca.key").read_bytes())
    with pytest.raises(ValueError, match="public CA"):
        export(state, tmp_path / "bad.zip")
    assert not (tmp_path / "bad.zip").exists()


def test_original_identity_mismatch_refused_even_with_updated_hash(tmp_path):
    _, _, target, _ = unpack(tmp_path)
    info = json.loads((target / "handoff.json").read_text())
    info["issuer"] = "https://192.168.1.99:18443/realms/calorie-dev"
    changed = (json.dumps(info) + "\n").encode()
    (target / "handoff.json").write_bytes(changed)
    sums = (target / "SHA256SUMS").read_text().splitlines()
    (target / "SHA256SUMS").write_text(
        "\n".join(
            f"{digest(changed)}  handoff.json" if line.endswith("  handoff.json") else line
            for line in sums
        )
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        verify(target)


def test_portable_copy_needs_no_original_private_state(tmp_path):
    state, _, target, _ = unpack(tmp_path)
    shutil.move(state, tmp_path / "unavailable-original")
    assert verify(target)["apk_source"] == "b" * 40
    prepare(target, tmp_path / "recipient-overlay")
