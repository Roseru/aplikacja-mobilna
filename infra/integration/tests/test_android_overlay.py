"""Ensure local Android trust stays scoped and cannot copy secrets into an APK."""

import json
from xml.etree import ElementTree as ET

import pytest

from infra.integration.android_overlay import prepare
from infra.integration.run import certificates, initialize


def state(tmp_path):
    source = tmp_path / "state"
    source.mkdir()
    (source / "config.json").write_text(json.dumps({"host": "192.168.1.50", "port": 18443}))
    certificates(source / "tls", "192.168.1.50")
    (source / "credentials.json").write_text('{"password":"do-not-copy"}')
    return source


def test_scoped_validation_only_public_certificate(tmp_path):
    source = state(tmp_path)
    output = tmp_path / "o3-$scope'overlay"
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    receipt = prepare(source, output)
    assert receipt["application_id"] == "pl.roseru.kalorie.validation"
    config = ET.parse(output / "res/xml/o3_network_security.xml").getroot()
    domain = config.find("domain-config/domain")
    assert domain.text == "192.168.1.50"
    assert domain.attrib == {"includeSubdomains": "false"}
    assert config.find("domain-config/trust-anchors/certificates").attrib == {
        "src": "@raw/o3_local_ca"
    }
    assert config.find("base-config").get("cleartextTrafficPermitted") == "false"
    assert 'maybeCreate("validation")' in (output / "init.gradle").read_text()
    assert "o3-$scope\\'overlay'" in (output / "init.gradle").read_text()
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    for path in output.rglob("*"):
        if path.is_file():
            value = path.read_bytes()
            assert b"PRIVATE KEY" not in value
            assert b"do-not-copy" not in value
            assert b'src="user"' not in value


def test_private_key_in_ca_input_is_rejected_before_output(tmp_path):
    source = state(tmp_path)
    ca = source / "tls/ca.pem"
    ca.write_bytes(ca.read_bytes() + (source / "tls/ca.key").read_bytes())
    output = tmp_path / "overlay"
    with pytest.raises(ValueError, match="public certificate"):
        prepare(source, output)
    assert not output.exists()


@pytest.mark.parametrize("host", ["8.8.8.8", "0.0.0.0", "192.0.0.8", "169.254.1.50"])
def test_non_integration_host_is_rejected(tmp_path, host):
    source = state(tmp_path)
    (source / "config.json").write_text(json.dumps({"host": host, "port": 443}))
    with pytest.raises(ValueError, match="local integration"):
        prepare(source, tmp_path / "overlay")


def test_existing_overlay_cannot_be_overwritten(tmp_path):
    source = state(tmp_path)
    output = tmp_path / "overlay"
    output.mkdir()
    sentinel = output / "preserve.txt"
    sentinel.write_text("existing work")
    with pytest.raises(FileExistsError):
        prepare(source, output)
    assert sentinel.read_text() == "existing work"


def test_new_local_realm_supports_o1_scope_without_changing_harness(tmp_path):
    source = tmp_path / "state"
    initialize(source)
    realm = json.loads((source / "realm/calorie-dev.json").read_text(encoding="utf-8"))
    android = next(c for c in realm["clients"] if c["clientId"] == "calorie-android")
    assert android["optionalClientScopes"] == ["profile"]
    assert android["defaultClientScopes"] == ["basic", "roles"]
    assert android["attributes"]["pkce.code.challenge.method"] == "S256"
    assert android["directAccessGrantsEnabled"] is False
    assert android["implicitFlowEnabled"] is False
    for client in realm["clients"]:
        if client["clientId"] != "calorie-android":
            assert "profile" not in client.get("optionalClientScopes", [])
