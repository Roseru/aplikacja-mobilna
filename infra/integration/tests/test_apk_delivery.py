"""Synthetic delivery matrix: inspect bytes/SDK evidence, never run an APK or an AVD."""

import json
import os
import struct
import sys
import warnings
import zipfile
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from infra.integration import apk_delivery as delivery

SOURCE = "a" * 40
TREE = "b" * 40
SIGNER = "c" * 64
API = "https://192.168.1.50:18443/api/v1"
ISSUER = "https://192.168.1.50:18443/realms/calorie-dev"
CA_ENTRY = "res/raw/o3_local_ca.pem"
NETWORK_ENTRY = "res/xml/o3_network_security.xml"
APP = "pl.roseru.kalorie"
RUNNER = "androidx.test.runner.AndroidJUnitRunner"
GRADLE = """
applicationId = "pl.roseru.kalorie"
versionCode = 42
versionName = "0.8.31"
targetSdk = 35
create("validation") { applicationIdSuffix = ".validation" }
testBuildType = "validation"
testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
output.versionCode.set(1000 + checkNotNull(android.defaultConfig.versionCode))
output.versionName.set(checkNotNull(android.defaultConfig.versionName) + ".validation")
if (providers.gradleProperty("O1_LIVE_E4_REPLAY_TEST").orElse("false").get() == "true") {
    sourceSets.getByName("androidTest").java.srcDir("src/liveReplay/java")
}
"""


def node(name, attrs=None, children=None, text=None):
    return {"name": name, "attrs": attrs or {}, "children": children or [], "text": text or []}


def trust_policy():
    def anchors(src):
        return node("trust-anchors", children=[node("certificates", {"src": src})])

    return node(
        "network-security-config",
        children=[
            node(
                "base-config",
                {"cleartextTrafficPermitted": "(type 0x12)0x0"},
                [anchors('"system"')],
            ),
            node(
                "domain-config",
                {"cleartextTrafficPermitted": "(type 0x12)0x0"},
                [
                    node("domain", {"includeSubdomains": "(type 0x12)0x0"}, text=["192.168.1.50"]),
                    anchors("@0x7f020001"),
                ],
            ),
        ],
    )


def dump_xml(root):
    def lines(item, depth):
        prefix = " " * depth
        result = [prefix + "E: " + item["name"] + " (line=1)"]
        result += [prefix + "  A: " + k + "=" + v for k, v in item["attrs"].items()]
        result += [prefix + "  C: " + json.dumps(v) for v in item["text"]]
        for child in item["children"]:
            result += lines(child, depth + 2)
        return result

    return "\n".join(lines(root, 0))


def dex(definitions, *, unused=()):
    """Minimal definition-index fixture; unused strings must never count as definitions."""
    strings = list(definitions) + list(unused)
    raw = bytearray(112 + len(strings) * 4 + len(definitions) * 4 + len(definitions) * 32)
    string_start = 112
    type_start = string_start + len(strings) * 4
    class_start = type_start + len(definitions) * 4
    for index, value in enumerate(strings):
        struct.pack_into("<I", raw, string_start + index * 4, len(raw))
        assert len(value) < 128
        raw.extend(bytes([len(value)]) + value + b"\0")
    for index in range(len(definitions)):
        struct.pack_into("<I", raw, type_start + index * 4, index)
        struct.pack_into("<I", raw, class_start + index * 32, index)
    raw[:8] = b"dex\n035\0"
    struct.pack_into("<III", raw, 32, len(raw), 112, 0x12345678)
    struct.pack_into("<II", raw, 56, len(strings), string_start)
    struct.pack_into("<II", raw, 64, len(definitions), type_start)
    struct.pack_into("<II", raw, 96, len(definitions), class_start)
    return bytes(raw)


def public_ca(is_ca=True):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic APK inspection CA")])
    now = datetime(2026, 10, 25, tzinfo=UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


class SyntheticInspector:
    def __init__(self, folder, records):
        self.paths = []
        for name in ("aapt.exe", "java.exe", "apksigner.jar", "git.exe"):
            path = folder / name
            path.write_bytes(name.encode())
            self.paths.append(path)
        self.records = {r["filename"]: deepcopy(r) for r in records}
        self.policy = trust_policy()
        self.source_value = delivery.source_declarations(
            GRADLE,
            "@Database(version = 23, exportSchema = true)",
            {"database": {"version": 23}},
            23,
        )
        self.signer_values = {}
        self.table_suffix = ""
        self.mutate_xml = lambda role, root: root
        self.calls = []

    def source(self, checkout, source):
        self.calls.append(("source", source["commit"], source["android_tree"]))
        assert source == {"commit": SOURCE, "android_tree": TREE, "room": 23}
        return deepcopy(self.source_value)

    def signers(self, apk):
        self.calls.append(("signers", apk.name))
        return self.signer_values.get(apk.name, [SIGNER])

    def xml(self, apk, entry):
        self.calls.append(("xml", apk.name, entry))
        if entry == NETWORK_ENTRY:
            return delivery.xml_nodes(dump_xml(self.policy))
        record = self.records[apk.name]
        attrs = {"package": json.dumps(record["application_id"])}
        if record["version_code"] is not None:
            attrs["android:versionCode"] = "(type 0x10)" + hex(record["version_code"])
        if record["version_name"] is not None:
            attrs["android:versionName"] = json.dumps(record["version_name"])
        children = [node("uses-sdk", {"android:targetSdkVersion": "(type 0x10)0x23"})]
        app_attrs = {
            "android:usesCleartextTraffic": "(type 0x12)0x0",
            "android:debuggable": "(type 0x12)0xffffffff",
        }
        if record["role"] == "validation-configured":
            app_attrs["android:networkSecurityConfig"] = "@0x7f030001"
        children.append(node("application", app_attrs))
        if record["instrumentation"] is not None:
            pair = record["instrumentation"]
            children.append(
                node(
                    "instrumentation",
                    {
                        "android:targetPackage": json.dumps(pair["target_package"]),
                        "android:name": json.dumps(pair["runner"]),
                    },
                )
            )
        root = self.mutate_xml(record["role"], node("manifest", attrs, children))
        return delivery.xml_nodes(dump_xml(root))

    def aapt(self, apk, *args):
        self.calls.append(("resources", apk.name, args))
        record = self.records[apk.name]

        def resource(number, name, value):
            return f"resource 0x7f{number} {APP}:{name}: t=0x03\n  (string8) {json.dumps(value)}\n"

        table = resource("010001", "string/api_base_url", record["endpoints"]["api_base_url"])
        table += resource("010002", "string/oidc_issuer", record["endpoints"]["oidc_issuer"])
        if record["role"] == "validation-configured":
            table += resource("020001", "raw/o3_local_ca", CA_ENTRY)
            table += resource("030001", "xml/o3_network_security", NETWORK_ENTRY)
            table += self.table_suffix
        return table


@pytest.fixture
def candidate(tmp_path):
    ca = tmp_path / "ca.pem"
    ca.write_bytes(public_ca())
    records = []
    for index, role in enumerate(delivery.ROLES):
        app = role in delivery.APP_ROLES
        # Deliberately DIFFERENT targets. Neither binary may borrow the other's target evidence.
        target_role = "debug" if role == "test-default" else "validation-configured"
        target_id = APP if target_role == "debug" else APP + ".validation"
        app_id = (APP if role == "debug" else APP + ".validation") if app else target_id + ".test"
        apk = tmp_path / (role + ".apk")
        classes = [b"Lexample/Role" + str(index).encode() + b";"]
        if role == delivery.ROLES[3]:
            classes += [delivery.DRIVER + b";", delivery.DRIVER + b"$Inner;"]
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"synthetic binary XML; SDK is injected")
            archive.writestr("classes.dex", dex(classes))
            if role == "validation-configured":
                archive.writestr(CA_ENTRY, ca.read_bytes())
                archive.writestr(NETWORK_ENTRY, b"synthetic compiled policy")
        records.append(
            {
                "role": role,
                "filename": apk.name,
                "bytes": apk.stat().st_size,
                "sha256": delivery.digest(apk),
                "signer_sha256": SIGNER,
                "application_id": app_id,
                "version_code": (42 if role == "debug" else 1042) if app else None,
                "version_name": ("0.8.31" if role == "debug" else "0.8.31.validation")
                if app
                else None,
                "endpoints": (
                    {"api_base_url": "", "oidc_issuer": ""}
                    if role == "debug"
                    else {"api_base_url": API, "oidc_issuer": ISSUER}
                )
                if app
                else None,
                "instrumentation": None
                if app
                else {"target_role": target_role, "target_package": target_id, "runner": RUNNER},
            }
        )
    spec = {
        "schema_version": 1,
        "source": {"commit": SOURCE, "android_tree": TREE, "room": 23},
        "configuration": {
            "api_base_url": API,
            "oidc_issuer": ISSUER,
            "ca_sha256": delivery.digest(ca),
            "ca_entry": CA_ENTRY,
            "network_xml_entry": NETWORK_ENTRY,
        },
        "artifacts": records,
    }
    manifest = tmp_path / "delivery.json"
    inspector = SyntheticInspector(tmp_path, records)
    result = SimpleNamespace(
        spec=spec,
        ca=ca,
        manifest=manifest,
        inspector=inspector,
        root=tmp_path,
        output=tmp_path / "static-report.json",
    )

    def save():
        manifest.write_text(json.dumps(spec), encoding="utf-8")

    def inspect(**overrides):
        save()
        return delivery.inspect_delivery(
            manifest,
            **(
                {
                    "expected_manifest_sha256": delivery.digest(manifest),
                    "source_commit": SOURCE,
                    "android_tree": TREE,
                    "checkout": tmp_path,
                    "ca": ca,
                    "inspector": inspector,
                    "report_path": result.output,
                }
                | overrides
            ),
        )

    result.save = save
    result.inspect = inspect
    save()
    return result


def failed(report, role, name):
    assert {"role": role, "name": name, "status": "FAIL"} in report["checks"]
    assert report["result"] == "STATIC_FAIL"


def test_four_roles_with_separate_explicit_targets_are_static_only(candidate):
    before = {p: p.read_bytes() for p in candidate.root.iterdir() if p.is_file()}
    result = candidate.inspect()
    assert result["result"] == "STATIC_PASS"
    assert len(result["artifacts"]) == 4
    assert result["android_acceptance"] == "NOT_CREATED"
    assert result["live_trial"] == result["driver_execution"] == "NOT_RUN"
    assert result["room_runtime"] == result["runtime_tls_chain"] == "NOT_CHECKED"
    assert result["apk_source_provenance"] == "DECLARED_NOT_REPRODUCED"
    assert result["deployment_authorized"] is False
    assert json.loads(candidate.output.read_text("utf-8")) == result
    assert len([c for c in candidate.inspector.calls if c[0] == "signers"]) == 4
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("first,second", [(0, 1), (2, 3), (0, 2), (1, 3)])
def test_swapped_apk_bytes_cannot_borrow_role_or_pair(candidate, first, second):
    left, right = [
        candidate.root / candidate.spec["artifacts"][i]["filename"] for i in (first, second)
    ]
    original = left.read_bytes(), right.read_bytes()
    left.write_bytes(original[1])
    right.write_bytes(original[0])
    result = candidate.inspect()
    failed(result, delivery.ROLES[first], "apk_sha256")
    failed(result, delivery.ROLES[second], "apk_sha256")
    assert left.read_bytes() == original[1] and right.read_bytes() == original[0]


@pytest.mark.parametrize("index", [0, 1, 2, 3])
@pytest.mark.parametrize(
    "field,value,check",
    [
        ("bytes", 1, "apk_bytes"),
        ("sha256", "0" * 64, "apk_sha256"),
        ("version_code", 7, "compiled_package_version"),
        ("version_name", "wrong", "compiled_package_version"),
        ("application_id", "wrong.package", "compiled_package_version"),
    ],
)
def test_observed_binary_identity_must_match_each_record(candidate, index, field, value, check):
    record = candidate.spec["artifacts"][index]
    if field in {"application_id", "version_code", "version_name"}:
        candidate.inspector.records[record["filename"]][field] = value
    else:
        record[field] = value
    failed(candidate.inspect(), delivery.ROLES[index], check)


@pytest.mark.parametrize("index", [2, 3])
@pytest.mark.parametrize("damage", ["target", "runner", "missing", "duplicate"])
def test_instrumentation_uses_its_own_binary_manifest(candidate, index, damage):
    role = delivery.ROLES[index]

    def change(actual_role, root):
        if actual_role == role:
            items = [n for n in root["children"] if n["name"] == "instrumentation"]
            if damage in {"target", "runner"}:
                attr = "android:targetPackage" if damage == "target" else "android:name"
                items[0]["attrs"][attr] = '"wrong.package"'
            elif damage == "missing":
                root["children"].remove(items[0])
            else:
                root["children"].append(deepcopy(items[0]))
        return root

    candidate.inspector.mutate_xml = change
    failed(candidate.inspect(), role, "instrumentation_pair")


@pytest.mark.parametrize("values", [[], ["d" * 64], [SIGNER, SIGNER], [SIGNER, "d" * 64]])
def test_signature_verification_requires_exactly_one_expected_signer(candidate, values):
    candidate.inspector.signer_values["test-default.apk"] = values
    failed(candidate.inspect(), "test-default", "verified_single_signer")


@pytest.mark.parametrize(
    "role,damage",
    [
        (delivery.ROLES[3], "missing"),
        *[(role, damage) for role in delivery.ROLES for damage in ("extra", "receipt")],
    ],
)
def test_driver_definitions_are_exclusive_to_optin(candidate, role, damage):
    path = candidate.root / (role + ".apk")
    classes = [b"Lexample/Placeholder;"]
    if damage == "extra":
        if role == delivery.ROLES[3]:
            classes += [delivery.DRIVER + b"$Inner;"]  # Inner alone is not a defined driver.
        else:
            classes += [delivery.DRIVER + b";"]
    elif damage == "receipt":
        classes += [delivery.OTHER_DRIVER + b";"]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("classes.dex", dex(classes, unused=[delivery.DRIVER + b";"]))
    failed(candidate.inspect(), role, "driver_definitions")


@pytest.mark.parametrize(
    "damage", ["extra", "missing", "repeat", "unknown", "fields", "pair", "signer", "identical"]
)
def test_incomplete_or_ambiguous_expected_delivery_blocks_before_tools(candidate, damage):
    records = candidate.spec["artifacts"]
    if damage == "extra":
        records.append(deepcopy(records[0]))
    elif damage == "missing":
        records.pop()
    elif damage == "repeat":
        records[3]["role"] = records[2]["role"]
    elif damage == "unknown":
        records[3]["role"] = "live"
    elif damage == "fields":
        del records[3]["version_code"]
    elif damage == "pair":
        records[2]["instrumentation"]["target_package"] = APP + ".validation"
    elif damage == "signer":
        records[2]["signer_sha256"] = "d" * 64
    else:
        records[3]["sha256"] = records[2]["sha256"]
    result = candidate.inspect()
    assert result["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists() and not candidate.inspector.calls


@pytest.mark.parametrize(
    "field",
    [
        "role",
        "filename",
        "bytes",
        "sha256",
        "signer_sha256",
        "application_id",
        "version_code",
        "version_name",
        "endpoints",
        "instrumentation",
    ],
)
def test_all_role_fields_are_required(candidate, field):
    del candidate.spec["artifacts"][3][field]
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("bytes", True),
        ("bytes", 0),
        ("bytes", None),
        ("sha256", "ABC"),
        ("version_code", False),
        ("version_code", 0),
        ("filename", "../x.apk"),
        ("filename", "C:\\x.apk"),
        ("filename", "x.apk:stream"),
        ("filename", "--x.apk"),
        ("filename", "a/b.apk"),
        ("filename", "NUL.apk "),
        ("application_id", None),
    ],
)
def test_bad_manifest_values_fail_closed(candidate, field, value):
    candidate.spec["artifacts"][2][field] = value
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists()


@pytest.mark.parametrize(
    "damage", ["pin", "source", "tree", "missing_room", "nonpositive_room", "config"]
)
def test_expected_manifest_and_source_context_are_independently_pinned(candidate, damage):
    options = {}
    if damage == "pin":
        options["expected_manifest_sha256"] = "0" * 64
    elif damage == "source":
        options["source_commit"] = "d" * 40
    elif damage == "tree":
        candidate.spec["source"]["android_tree"] = "d" * 40
    elif damage == "missing_room":
        del candidate.spec["source"]["room"]
    elif damage == "nonpositive_room":
        candidate.spec["source"]["room"] = True
    else:
        del candidate.spec["configuration"]["ca_sha256"]
    assert candidate.inspect(**options)["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists() and not candidate.inspector.calls


@pytest.mark.parametrize(
    "raw",
    [
        b'{"source": {}, "source": {}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b"\xff",
        b"[",
        b"[" * 5000,
        b" " * (delivery.MAX_JSON + 1),
    ],
    ids=["duplicate", "nan", "infinity", "utf8", "syntax", "depth", "oversize"],
)
def test_ambiguous_or_unbounded_json_is_refused(candidate, raw):
    candidate.manifest.write_bytes(raw)
    result = delivery.inspect_delivery(
        candidate.manifest,
        expected_manifest_sha256=delivery.digest(candidate.manifest),
        source_commit=SOURCE,
        android_tree=TREE,
        checkout=candidate.root,
        ca=candidate.ca,
        inspector=candidate.inspector,
        report_path=candidate.output,
    )
    assert result["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists() and not candidate.inspector.calls


@pytest.mark.parametrize("damage", ["hash", "bytes", "private_key", "not_ca", "two_certs"])
def test_provided_and_embedded_ca_both_require_exact_public_bytes(candidate, damage):
    if damage == "hash":
        candidate.spec["configuration"]["ca_sha256"] = "0" * 64
        failed(candidate.inspect(), "delivery", "provided_ca_sha256")
    elif damage == "bytes":
        candidate.ca.write_bytes(public_ca())
        candidate.spec["configuration"]["ca_sha256"] = delivery.digest(candidate.ca)
        failed(candidate.inspect(), "validation-configured", "embedded_ca_bytes")
    else:
        if damage == "private_key":
            candidate.ca.write_bytes(
                candidate.ca.read_bytes() + b"-----BEGIN PRIVATE KEY-----\nsecret"
            )
        elif damage == "not_ca":
            candidate.ca.write_bytes(public_ca(False))
        else:
            candidate.ca.write_bytes(candidate.ca.read_bytes() * 2)
        assert candidate.inspect()["result"] == "STATIC_BLOCKED"
        assert not candidate.output.exists()


@pytest.mark.parametrize(
    "damage",
    ["user", "cleartext", "subdomains", "host", "debug", "nested", "duplicate", "missing_base"],
)
def test_compiled_network_policy_cannot_widen_trust(candidate, damage):
    root = candidate.inspector.policy
    domain = root["children"][1]
    if damage == "user":
        domain["children"][1]["children"][0]["attrs"]["src"] = '"user"'
    elif damage == "cleartext":
        domain["attrs"]["cleartextTrafficPermitted"] = "(type 0x12)0xffffffff"
    elif damage == "subdomains":
        domain["children"][0]["attrs"]["includeSubdomains"] = "(type 0x12)0xffffffff"
    elif damage == "host":
        domain["children"][0]["text"] = ["other.example"]
    elif damage == "debug":
        root["children"].append(node("debug-overrides"))
    elif damage == "nested":
        domain["children"].append(deepcopy(domain))
    elif damage == "duplicate":
        root["children"].append(deepcopy(domain))
    else:
        root["children"].pop(0)
    failed(candidate.inspect(), "validation-configured", "strict_network_trust")


@pytest.mark.parametrize(
    "name,value,check",
    [
        ("string/api_base_url", "", "compiled_api_base_url"),
        ("string/oidc_issuer", "https://other.example", "compiled_oidc_issuer"),
        ("raw/o3_local_ca", "res/raw/other.pem", "ca_resource"),
        ("xml/o3_network_security", "res/xml/other.xml", "network_resource"),
    ],
)
def test_every_compiled_resource_configuration_is_checked(candidate, name, value, check):
    number = {
        "string/api_base_url": "010001",
        "string/oidc_issuer": "010002",
        "raw/o3_local_ca": "020001",
        "xml/o3_network_security": "030001",
    }[name]
    candidate.inspector.table_suffix = (
        f"resource 0x7f{number} {APP}:{name}:\n  (string16) {json.dumps(value)}\n"
    )
    failed(candidate.inspect(), "validation-configured", check)


@pytest.mark.parametrize("role", delivery.APP_ROLES)
@pytest.mark.parametrize(
    "attribute,value,check",
    [
        ("android:usesCleartextTraffic", "(type 0x12)0xffffffff", "manifest_cleartext"),
        ("android:networkSecurityConfig", "@0x7f030999", "manifest_network_binding"),
        ("android:debuggable", "(type 0x12)0x0", "debuggable_variant"),
    ],
)
def test_compiled_app_manifest_must_bind_the_checked_profile(
    candidate, role, attribute, value, check
):
    def mutate(actual_role, root):
        if actual_role == role:
            next(n for n in root["children"] if n["name"] == "application")["attrs"][attribute] = (
                value
            )
        return root

    candidate.inspector.mutate_xml = mutate
    if attribute == "android:networkSecurityConfig" and role == "debug":
        check = "system_trust_only"
    failed(candidate.inspect(), role, check)


def test_source_profile_reads_pinned_git_objects_without_building_or_executing_source(
    candidate, monkeypatch
):
    inspector = delivery.Inspector(*candidate.inspector.paths)
    source_calls = []

    def run(args, cwd, **kwargs):
        source_calls.append(args)
        assert cwd == candidate.root
        assert kwargs == {"limit": delivery.MAX_JSON}
        if "rev-parse" in args:
            return TREE + "\n"
        assert args[1:3] == ["--no-pager", "show"] and args[3].startswith(SOURCE + ":android/")
        if args[3].endswith("build.gradle.kts"):
            return GRADLE
        if args[3].endswith("Database.kt"):
            return "@Database(version = 23, exportSchema = true)"
        return '{"database":{"version":23}}'

    monkeypatch.setattr(delivery, "command", run)
    actual = inspector.source(candidate.root, candidate.spec["source"])
    assert actual["room"] == 23 and actual["validation-configured"]["version_code"] == 1042
    assert len(source_calls) == 4


@pytest.mark.parametrize(
    "damage", ["ambiguous_version", "missing_gate", "room", "schema", "missing_test_type"]
)
def test_unsupported_source_profile_is_not_silently_inferred(damage):
    gradle, database, schema = (
        GRADLE,
        "version = 23, exportSchema = true",
        {"database": {"version": 23}},
    )
    if damage == "ambiguous_version":
        gradle += '\nversionName = "other"'
    elif damage == "missing_gate":
        gradle = gradle.replace("O1_LIVE_E4_REPLAY_TEST", "WRONG")
    elif damage == "room":
        database = database.replace("23", "22")
    elif damage == "schema":
        schema["database"]["version"] = 22
    else:
        gradle = gradle.replace('testBuildType = "validation"', "")
    with pytest.raises(delivery.Unchecked):
        delivery.source_declarations(gradle, database, schema, 23)


def test_dex_definition_index_ignores_string_decoys_and_scans_secondary_dex(candidate):
    path = candidate.root / "test-default.apk"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("classes.dex", dex([b"Lexample/Only;"], unused=[delivery.DRIVER + b";"]))
        archive.writestr("classes2.dex", dex([delivery.DRIVER + b";"]))
    classes, _ = delivery.archive_evidence(
        path, candidate.spec["configuration"], candidate.ca.read_bytes()
    )
    assert delivery.DRIVER + b";" in classes
    failed(candidate.inspect(), "test-default", "driver_definitions")


@pytest.mark.parametrize(
    "damage",
    ["magic", "header", "class_index", "string_index", "string_offset", "table", "terminator"],
)
def test_malformed_dex_is_incomplete_evidence(damage):
    raw = bytearray(dex([delivery.DRIVER + b";"]))
    offsets = {
        "class_index": (120, 999),
        "string_index": (116, 999),
        "string_offset": (112, 999999),
        "table": (100, 999999),
    }
    if damage == "magic":
        raw[:8] = b"dex\n041\0"
    elif damage == "header":
        struct.pack_into("<I", raw, 36, 120)
    elif damage == "terminator":
        raw[-1] = 1
    else:
        struct.pack_into("<I", raw, *offsets[damage])
    with pytest.raises(delivery.Unchecked):
        delivery.dex_classes(bytes(raw))


@pytest.mark.parametrize("damage", ["duplicate", "bad_dex", "no_dex", "nested_dex"])
def test_ambiguous_zip_cannot_produce_receipt(candidate, damage):
    apk = candidate.root / "debug.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        if damage != "no_dex":
            archive.writestr(
                "classes.dex", b"invalid" if damage == "bad_dex" else dex([b"Lexample/Only;"])
            )
        if damage == "duplicate":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("classes.dex", dex([b"Lexample/Second;"]))
        if damage == "nested_dex":
            archive.writestr("assets/hidden.dex", dex([delivery.DRIVER + b";"]))
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists()


@pytest.mark.parametrize("existing", ["manifest", "ca", "apk", "tool", "other", "hardlink"])
def test_existing_outputs_and_input_aliases_are_preserved(candidate, existing):
    candidate.save()
    if existing == "manifest":
        output = candidate.manifest
    elif existing == "ca":
        output = candidate.ca
    elif existing == "apk":
        output = candidate.root / "debug.apk"
    elif existing == "tool":
        output = candidate.inspector.paths[0]
    else:
        output = candidate.output
        if existing == "hardlink":
            os.link(candidate.manifest, output)
        else:
            output.write_text("existing proof", encoding="utf-8")
    before = output.read_bytes()
    assert candidate.inspect(report_path=output)["result"] == "STATIC_BLOCKED"
    assert output.read_bytes() == before and not candidate.inspector.calls


def test_hardlinked_role_inputs_are_not_independent_artifacts(candidate):
    left, right = candidate.root / "test-default.apk", candidate.root / "test-liveReplay-optin.apk"
    right.unlink()
    os.link(left, right)
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists() and not candidate.inspector.calls


def test_missing_inputs_refuse_without_report(candidate):
    (candidate.root / "test-default.apk").unlink()
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.output.exists() and not candidate.inspector.calls


@pytest.mark.parametrize(
    "error",
    [
        delivery.Unchecked("missing static evidence"),
        OSError("secret-value"),
        ValueError("private-value"),
        RuntimeError("raw diagnostic"),
    ],
)
def test_inspection_failure_never_persists_partial_report_or_raw_output(candidate, error):
    def fail(_):
        raise error

    candidate.inspector.signers = fail
    result = candidate.inspect()
    assert result["result"] == "STATIC_BLOCKED" and not candidate.output.exists()
    encoded = json.dumps(result)
    assert all(v not in encoded for v in ("secret-value", "private-value", "raw diagnostic"))


def test_input_changes_during_inspection_cannot_pass(candidate):
    original = candidate.inspector.signers

    def mutate(apk):
        if apk.name == "test-liveReplay-optin.apk":
            with (candidate.root / "debug.apk").open("ab") as stream:
                stream.write(b"changed")
        return original(apk)

    candidate.inspector.signers = mutate
    failed(candidate.inspect(), "delivery", "inputs_unchanged")


def test_cli_stdout_and_saved_report_remain_neutral(candidate, monkeypatch, capsys):
    monkeypatch.setattr(delivery, "Inspector", lambda *args: candidate.inspector)
    code = delivery.main(
        [
            "--manifest",
            str(candidate.manifest),
            "--ca",
            str(candidate.ca),
            "--checkout",
            str(candidate.root),
            "--aapt",
            "aapt",
            "--java",
            "java",
            "--apksigner-jar",
            "signer",
            "--git",
            "git",
            "--source-commit",
            SOURCE,
            "--source-android-tree",
            TREE,
            "--expected-manifest-sha256",
            delivery.digest(candidate.manifest),
            "--report",
            str(candidate.output),
        ]
    )
    output = capsys.readouterr().out
    assert code == 0 and json.loads(output)["result"] == "STATIC_PASS"
    assert str(candidate.root) not in output and API not in output and ISSUER not in output
    assert "CERTIFICATE" not in output


def test_real_subprocess_is_bounded_and_discards_raw_stderr(tmp_path):
    result = delivery.command([sys.executable, "-c", "print('public metadata')"], tmp_path)
    assert result == "public metadata\n"
    with pytest.raises(delivery.Unchecked, match="output exceeds"):
        delivery.command([sys.executable, "-c", "print('x'*100000)"], tmp_path, limit=100)
    with pytest.raises(delivery.Unchecked, match="raw output discarded") as failure:
        delivery.command(
            [sys.executable, "-c", "import sys;sys.stderr.write('SECRET');sys.exit(1)"], tmp_path
        )
    assert "SECRET" not in str(failure.value)


def test_subprocess_timeout_and_java_option_injection_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "secret-agent")
    result = delivery.command(
        [sys.executable, "-c", "import os;print(os.getenv('JAVA_TOOL_OPTIONS'))"], tmp_path
    )
    assert result == "None\n"
    with pytest.raises(delivery.subprocess.TimeoutExpired):
        delivery.command([sys.executable, "-c", "import time;time.sleep(3)"], tmp_path, timeout=0.1)


def test_xml_duplicates_and_resource_ambiguity_fail_closed():
    with pytest.raises(delivery.Unchecked, match="duplicate"):
        delivery.xml_nodes('E: manifest\n  A: package="a.b"\n  A: package="a.b"')
    with pytest.raises(delivery.Unchecked, match="ambiguous"):
        delivery.resource(
            'resource 0x1 a:string/api_base_url:\n (string8) "a"\n'
            'resource 0x2 a:string/api_base_url:\n (string8) "a"\n',
            "string/api_base_url",
        )


def test_new_report_parent_symlink_is_refused(candidate):
    target = candidate.root / "real-parent"
    target.mkdir()
    link = candidate.root / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit creating symlinks")
    assert candidate.inspect(report_path=link / "report.json")["result"] == "STATIC_BLOCKED"
    assert not list(target.iterdir())


@pytest.mark.parametrize("target", ["debug", "validation-configured"])
def test_default_target_is_explicit_even_when_it_matches_optin(candidate, target):
    test = candidate.spec["artifacts"][2]
    test["instrumentation"]["target_role"] = target
    test["instrumentation"]["target_package"] = candidate.spec["artifacts"][
        delivery.ROLES.index(target)
    ]["application_id"]
    test["application_id"] = test["instrumentation"]["target_package"] + ".test"
    candidate.inspector.records[test["filename"]] = deepcopy(test)
    assert candidate.inspect()["result"] == "STATIC_PASS"


def test_optin_cannot_be_repaired_by_declaring_the_regular_target(candidate):
    test = candidate.spec["artifacts"][3]
    test["instrumentation"]["target_role"] = "debug"
    test["instrumentation"]["target_package"] = APP
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.inspector.calls and not candidate.output.exists()


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://192.168.1.50/api/v1",
        "https://u:p@example.com/api/v1",
        "https://@example.com/api/v1",
        "https://example.com/api/v1?token=x",
        "https://example.com/api/v1?",
        "https://example.com/api/v1#x",
        "https://example.com/api/v1#",
        "https://example.com",
        "https://example.com:0/api/v1",
    ],
)
def test_invalid_or_incomplete_endpoint_configuration_is_refused(candidate, value):
    candidate.spec["configuration"]["api_base_url"] = value
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.inspector.calls and not candidate.output.exists()


@pytest.mark.parametrize("name", ["CON.json", "NUL.json", "report.json:stream", "report.json."])
def test_output_device_stream_and_ambiguous_names_are_refused(candidate, name):
    assert candidate.inspect(report_path=candidate.root / name)["result"] == "STATIC_BLOCKED"
    assert not candidate.inspector.calls


def test_redirected_output_parent_is_refused_without_symlink_privileges(candidate, monkeypatch):
    original = Path.is_junction
    parent = candidate.root / "redirected"
    parent.mkdir()
    monkeypatch.setattr(Path, "is_junction", lambda p: p == parent or original(p))
    assert candidate.inspect(report_path=parent / "receipt.json")["result"] == "STATIC_BLOCKED"
    assert not list(parent.iterdir()) and not candidate.inspector.calls


@pytest.mark.parametrize("damage", ["resource_version", "extended_code", "old_sdk", "no_cleartext"])
def test_unsupported_compiled_metadata_never_passes_as_missing(candidate, damage):
    def mutate(role, root):
        if role == "validation-configured":
            if damage == "resource_version":
                root["attrs"]["android:versionName"] = "@0x7f010010"
            elif damage == "extended_code":
                root["attrs"]["android:versionCodeMajor"] = "(type 0x10)0x1"
            elif damage == "old_sdk":
                next(n for n in root["children"] if n["name"] == "uses-sdk")["attrs"][
                    "android:targetSdkVersion"
                ] = "(type 0x10)0x17"
            else:
                next(n for n in root["children"] if n["name"] == "application")["attrs"].pop(
                    "android:usesCleartextTraffic"
                )
        return root

    candidate.inspector.mutate_xml = mutate
    result = candidate.inspect()
    if damage in {"resource_version", "extended_code"}:
        assert result["result"] == "STATIC_BLOCKED" and not candidate.output.exists()
    else:
        failed(
            result,
            "validation-configured",
            "source_target_sdk" if damage == "old_sdk" else "manifest_cleartext",
        )


@pytest.mark.parametrize("failure_result,code", [("STATIC_FAIL", 1), ("STATIC_BLOCKED", 2)])
def test_cli_failure_exit_codes_are_not_success(
    candidate, monkeypatch, capsys, failure_result, code
):
    monkeypatch.setattr(delivery, "Inspector", lambda *args: candidate.inspector)
    monkeypatch.setattr(
        delivery, "inspect_delivery", lambda *args, **kwargs: {"result": failure_result}
    )
    actual = delivery.main(
        [
            "--manifest",
            str(candidate.manifest),
            "--ca",
            str(candidate.ca),
            "--checkout",
            str(candidate.root),
            "--aapt",
            "aapt",
            "--java",
            "java",
            "--apksigner-jar",
            "signer",
            "--git",
            "git",
            "--source-commit",
            SOURCE,
            "--source-android-tree",
            TREE,
            "--expected-manifest-sha256",
            delivery.digest(candidate.manifest),
        ]
    )
    assert actual == code and json.loads(capsys.readouterr().out)["result"] == failure_result


def test_sdk_command_shapes_use_only_readonly_inspection(candidate, monkeypatch):
    inspector = delivery.Inspector(*candidate.inspector.paths)
    calls = []

    def run(args, cwd, **kwargs):
        calls.append((args, cwd))
        if "xmltree" in args:
            return 'E: manifest\n  A: package="a.b"'
        if "verify" in args:
            return "Signer #1 certificate SHA-256 digest: " + SIGNER + "\n"
        return "compiled resource table"

    monkeypatch.setattr(delivery, "command", run)
    apk = candidate.root / "validation-configured.apk"
    inspector.xml(apk, "AndroidManifest.xml")
    inspector.aapt(apk, "--values", "resources")
    assert inspector.signers(apk) == [SIGNER]
    assert all(cwd == apk.parent and str(apk) not in args for args, cwd in calls)
    assert calls[0][0][1:] == ["dump", "xmltree", apk.name, "AndroidManifest.xml"]
    assert calls[1][0][1:] == ["dump", "--values", "resources", apk.name]
    assert calls[2][0][1:] == [
        "-jar",
        str(inspector.paths[2]),
        "verify",
        "--verbose",
        "--print-certs",
        apk.name,
    ]


@pytest.mark.parametrize("race", [False, True])
def test_report_publication_failure_leaves_no_partial_pass(candidate, monkeypatch, race):
    def fail_link(source, output):
        if race:
            output.write_text("concurrent proof", encoding="utf-8")
        raise OSError("PRIVATE SYSTEM DIAGNOSTIC")

    monkeypatch.setattr(delivery.os, "link", fail_link)
    result = candidate.inspect()
    assert result["result"] == "STATIC_BLOCKED"
    assert "PRIVATE SYSTEM DIAGNOSTIC" not in json.dumps(result)
    assert not list(candidate.root.glob(".apk-static-*"))
    if race:
        assert candidate.output.read_text("utf-8") == "concurrent proof"
    else:
        assert not candidate.output.exists()


def test_test_package_cannot_alias_either_application(candidate):
    candidate.spec["artifacts"][2]["application_id"] = APP + ".validation"
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.inspector.calls


def test_debug_endpoint_pair_cannot_silently_use_another_deployment(candidate):
    candidate.spec["artifacts"][0]["endpoints"] = {
        "api_base_url": "https://other.example/api/v1",
        "oidc_issuer": ISSUER,
    }
    assert candidate.inspect()["result"] == "STATIC_BLOCKED"
    assert not candidate.inspector.calls
