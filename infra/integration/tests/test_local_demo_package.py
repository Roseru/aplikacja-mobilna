"""Preparation cannot promote received bytes or self-declared receipts to live acceptance."""

import hashlib
import json
import subprocess

import pytest

from infra.integration.local_demo_package import InvalidPackage, prepare, verify

GATE_IDS = {"108", "110", "119", "185", "184", "backup_restore", "final120"}
MANIFEST = "manifest-demo.json"


def file_reference(path, *, source=None):
    data = path.read_bytes()
    return {
        "source": str(source if source is not None else path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def save_recipe(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def candidate(tmp_path):
    source = tmp_path / "sources" / "app.input"
    source.parent.mkdir()
    source.write_bytes(b"synthetic pre-sign app bytes; no actual APK or runtime")
    recipe = {
        "format": 1,
        "bindings": {
            "api": {
                "image": "sha256:" + "a" * 64,
                "schema": "0024_e9_history_graph",
                "full_git_source": None,
            },
            "android": {
                "source_commit": "b" * 40,
                "android_tree": "c" * 40,
                "room": 27,
                "stage": "PRE_SIGN_INPUT",
            },
        },
        "inputs": [
            {
                "id": "app",
                "role": "apk_presign",
                **file_reference(source),
                "destination": "artifacts/app.apk",
            }
        ],
        "gates": [
            {
                "id": name,
                "owner": "owner/" + name,
                "required": "Actual independently qualified evidence for " + name,
                "receipt": None,
            }
            for name in sorted(GATE_IDS)
        ],
    }
    path = save_recipe(tmp_path / "recipe.json", recipe)
    return {
        "recipe": recipe,
        "path": path,
        "source": source,
        "output": tmp_path / "bundle",
    }


def assert_preparation_only(manifest):
    assert manifest["format"] == "calorie-local-demo-preparation/v1"
    assert manifest["state"] == "PREPARATION_ONLY"
    assert manifest["sealed"] is False
    assert manifest["runtime_authorized"] is False


def test_unknown_api_source_and_separate_android_pin_remain_preparation(candidate):
    original_recipe = candidate["path"].read_bytes()
    original_input = candidate["source"].read_bytes()

    manifest = prepare(candidate["path"], candidate["output"])

    assert_preparation_only(manifest)
    assert manifest["bindings"]["api"]["full_git_source"] is None
    assert manifest["bindings"]["android"]["source_commit"] == "b" * 40
    assert manifest["bindings"]["android"]["stage"] == "PRE_SIGN_INPUT"
    missing = {entry["id"] for entry in manifest["missing_inputs"]}
    assert GATE_IDS <= missing
    assert any("final" in name.lower() for name in missing - GATE_IDS)
    assert {entry["id"] for entry in manifest["unqualified_gates"]} == GATE_IDS
    assert candidate["source"].read_bytes() == original_input
    assert candidate["path"].read_bytes() == original_recipe
    assert (candidate["output"] / "artifacts/app.apk").read_bytes() == original_input
    assert json.loads((candidate["output"] / MANIFEST).read_text(encoding="utf-8")) == manifest
    assert manifest["files"]["artifacts/app.apk"]["role"] == "apk_presign"
    assert MANIFEST not in manifest["files"]
    assert len(manifest["files"]) > 1  # Includes the bundled verifier and preparation helpers.
    assert isinstance(verify(candidate["output"]), dict)


def test_relative_input_is_resolved_from_recipe_not_process_directory(
    candidate, tmp_path, monkeypatch
):
    candidate["recipe"]["inputs"][0]["source"] = "sources/app.input"
    save_recipe(candidate["path"], candidate["recipe"])
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    prepare(candidate["path"], candidate["output"])

    copied = candidate["output"] / "artifacts/app.apk"
    assert copied.read_bytes() == candidate["source"].read_bytes()


def test_present_self_declared_pass_receipts_do_not_authorize_runtime_or_seal(
    candidate,
):
    receipts = {}
    for gate in candidate["recipe"]["gates"]:
        path = candidate["path"].parent / ("receipt-" + gate["id"] + ".json")
        raw = json.dumps({"task": gate["id"], "status": "PASS", "qualified": True}).encode()
        path.write_bytes(raw)
        gate["receipt"] = file_reference(path)
        receipts[gate["id"]] = raw
    save_recipe(candidate["path"], candidate["recipe"])

    manifest = prepare(candidate["path"], candidate["output"])

    assert_preparation_only(manifest)
    assert {entry["id"] for entry in manifest["unqualified_gates"]} == GATE_IDS
    assert not (GATE_IDS & {entry["id"] for entry in manifest["missing_inputs"]})
    assert any("final" in entry["id"].lower() for entry in manifest["missing_inputs"])
    for name, raw in receipts.items():
        relative = "evidence/gate-" + name + ".json"
        assert (candidate["output"] / relative).read_bytes() == raw
        assert manifest["files"][relative]["role"] == "evidence"
    assert isinstance(verify(candidate["output"]), dict)


@pytest.mark.parametrize("field", ["bytes", "sha256"])
def test_invalid_last_input_is_rejected_before_creating_output(candidate, field):
    other = candidate["source"].with_name("second.input")
    other.write_bytes(b"a second valid source with incorrect declared metadata")
    record = {
        "id": "second",
        "role": "instructions",
        **file_reference(other),
        "destination": "instructions/second.txt",
    }
    record[field] = record[field] + 1 if field == "bytes" else "0" * 64
    candidate["recipe"]["inputs"].append(record)
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()
    assert other.read_bytes() == b"a second valid source with incorrect declared metadata"


def test_missing_input_is_rejected_before_creating_output(candidate):
    candidate["recipe"]["inputs"][0]["source"] = str(candidate["source"].with_name("absent"))
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


@pytest.mark.parametrize("damage", ["corrupt", "missing", "extra"])
def test_verification_rejects_changed_missing_or_unlisted_payload(candidate, damage):
    prepare(candidate["path"], candidate["output"])
    app = candidate["output"] / "artifacts/app.apk"
    if damage == "corrupt":
        original = app.read_bytes()
        app.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    elif damage == "missing":
        app.unlink()
    else:
        (candidate["output"] / "unlisted.txt").write_text("unexpected payload", encoding="utf-8")

    with pytest.raises(InvalidPackage):
        verify(candidate["output"])


@pytest.mark.parametrize(
    "destination",
    [
        "../outside.apk",
        "/outside.apk",
        r"..\outside.apk",
        r"C:\outside.apk",
        "a/../outside.apk",
        "CON .txt",
        "NUL .txt",
        "COM¹",
        "LPT².txt",
        "nested/AUX .pem",
        "CONIN$",
        "CONOUT$.txt",
    ],
)
def test_destination_cannot_escape_bundle_on_windows_or_posix(candidate, destination):
    candidate["recipe"]["inputs"][0]["destination"] = destination
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()
    assert not (candidate["output"].parent / "outside.apk").exists()


def test_case_colliding_destinations_are_rejected_before_any_copy(candidate):
    first = candidate["recipe"]["inputs"][0]
    second = {**first, "id": "other-app", "destination": "ARTIFACTS/APP.APK"}
    candidate["recipe"]["inputs"].append(second)
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


@pytest.mark.parametrize("location", ["top", "nested"])
def test_duplicate_json_fields_are_rejected_even_when_values_match(candidate, location):
    raw = candidate["path"].read_text(encoding="utf-8")
    old, replacement = (
        ('"format": 1', '"format": 1, "format": 1')
        if location == "top"
        else ('"room": 27', '"room": 27, "room": 27')
    )
    assert old in raw
    candidate["path"].write_text(raw.replace(old, replacement, 1), encoding="utf-8")

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


def make_symlink(link, target):
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Host cannot create a test symlink: {type(error).__name__}")


def test_redirected_source_is_refused(candidate):
    redirected = candidate["source"].with_name("linked.input")
    make_symlink(redirected, candidate["source"])
    candidate["recipe"]["inputs"][0]["source"] = str(redirected)
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


def test_bundle_member_replaced_by_identical_external_symlink_is_refused(candidate):
    prepare(candidate["path"], candidate["output"])
    app = candidate["output"] / "artifacts/app.apk"
    app.unlink()
    make_symlink(app, candidate["source"])

    with pytest.raises(InvalidPackage):
        verify(candidate["output"])


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_existing_output_is_preserved(candidate, kind):
    if kind == "directory":
        candidate["output"].mkdir()
        sentinel = candidate["output"] / "keep.txt"
    else:
        sentinel = candidate["output"]
    sentinel.write_bytes(b"existing user data")

    with pytest.raises((InvalidPackage, FileExistsError)):
        prepare(candidate["path"], candidate["output"])

    assert sentinel.read_bytes() == b"existing user data"
    if kind == "directory":
        assert list(candidate["output"].iterdir()) == [sentinel]


@pytest.mark.parametrize("role", ["public_ca", "evidence", "apk_presign"])
@pytest.mark.parametrize("key_type", ["PRIVATE KEY", "RSA PRIVATE KEY", "ENCRYPTED PRIVATE KEY"])
def test_private_pem_is_not_packaged_even_under_an_allowed_role(candidate, role, key_type):
    private = candidate["source"].with_name("not-a-public-ca.pem")
    private.write_bytes(
        f"-----BEGIN {key_type}-----\nU1lOVEhFVElD\n-----END {key_type}-----\n".encode()
    )
    candidate["recipe"]["inputs"].append(
        {
            "id": "private-material",
            "role": role,
            **file_reference(private),
            "destination": "artifacts/not-public.pem",
        }
    )
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()
    assert private.is_file()


@pytest.mark.parametrize("damage", ["missing", "duplicate", "unknown"])
def test_required_gate_set_cannot_be_weakened(candidate, damage):
    gates = candidate["recipe"]["gates"]
    if damage == "missing":
        gates.pop()
    elif damage == "duplicate":
        gates.append(dict(gates[0]))
    else:
        gates[-1]["id"] = "optional-replacement"
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


def test_tampered_receipt_reference_cannot_be_promoted_by_pass_text(candidate):
    receipt = candidate["path"].parent / "purported-pass.json"
    receipt.write_text('{"status":"PASS"}', encoding="utf-8")
    candidate["recipe"]["gates"][0]["receipt"] = {
        **file_reference(receipt),
        "sha256": "0" * 64,
    }
    save_recipe(candidate["path"], candidate["recipe"])

    with pytest.raises(InvalidPackage):
        prepare(candidate["path"], candidate["output"])

    assert not candidate["output"].exists()


def test_verification_does_not_depend_on_original_sources(candidate, tmp_path):
    prepare(candidate["path"], candidate["output"])
    relocated = tmp_path / "relocated"
    candidate["output"].rename(relocated)
    candidate["source"].rename(candidate["source"].with_suffix(".unavailable"))

    assert isinstance(verify(relocated), dict)


@pytest.mark.parametrize("field", ["sealed", "runtime_authorized"])
def test_editing_manifest_cannot_authorize_execution_or_seal(candidate, field):
    prepare(candidate["path"], candidate["output"])
    manifest_path = candidate["output"] / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = True
    save_recipe(manifest_path, manifest)

    with pytest.raises(InvalidPackage):
        verify(candidate["output"])


def test_prepare_and_verify_never_execute_runtime_commands(candidate, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline preparation unexpectedly attempted a subprocess")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    manifest = prepare(candidate["path"], candidate["output"])
    assert_preparation_only(manifest)
    assert isinstance(verify(candidate["output"]), dict)


def test_private_key_marker_across_hashing_blocks_is_refused(candidate):
    candidate["source"].write_bytes(
        b"x" * (1024 * 1024 - 10) + b"-----BEGIN RSA PRIVATE KEY-----\nsynthetic-only\n"
    )
    candidate["recipe"]["inputs"][0].update(file_reference(candidate["source"]))
    save_recipe(candidate["path"], candidate["recipe"])
    with pytest.raises(InvalidPackage, match="Private key"):
        prepare(candidate["path"], candidate["output"])
    assert not candidate["output"].exists()


@pytest.mark.parametrize(
    "field", ["claims", "missing_inputs", "unqualified_gates", "qualification"]
)
def test_semantically_false_preparation_manifest_is_refused(candidate, field):
    prepare(candidate["path"], candidate["output"])
    path = candidate["output"] / MANIFEST
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if field == "claims":
        manifest["claims"]["final120"] = True
    elif field == "qualification":
        manifest["gates"][0]["qualification"] = "PASS"
    else:
        manifest[field] = []
    save_recipe(path, manifest)
    with pytest.raises(InvalidPackage):
        verify(candidate["output"])
