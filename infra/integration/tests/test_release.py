import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release  # noqa: E402

COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
SIGNER = "c" * 64
REVISION = "0024_e9_history_graph"


class Inspector:
    def __init__(self):
        self.debuggable = True
        self.commit = COMMIT
        self.revision = REVISION
        self.signer = SIGNER
        self.app_id = "pl.roseru.kalorie"

    def apk(self, _):
        return {
            "application_id": self.app_id,
            "version_code": 21,
            "version_name": "0.8.10",
            "debuggable": self.debuggable,
            "signer_sha256": self.signer,
        }

    def image(self, _):
        return {
            "Id": IMAGE,
            "Config": {"Labels": {"org.opencontainers.image.revision": self.commit}},
        }

    def schema(self, _):
        return self.revision


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def candidate(tmp_path):
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"fixture, inspection is a separate tool boundary")
    write(
        tmp_path / "android.json",
        {
            "application_id": "pl.roseru.kalorie",
            "version_code": 21,
            "version_name": "0.8.10",
            "variant": "debug",
            "commit": COMMIT,
            "apk": apk.name,
            "sha256": release.file_digest(apk),
        },
    )
    demo = Path(__file__).resolve().parents[3] / "backend/data/demo/export"
    manifest = json.loads((demo / "manifest.json").read_text())
    shutil.copyfile(demo / "manifest.json", tmp_path / "catalog.json")
    shutil.copyfile(demo / manifest["path"], tmp_path / manifest["path"])
    evidence = {}
    for name in release.EVIDENCE:
        receipt = {"result": "PASS", "commit": COMMIT}
        if name == "android_acceptance":
            receipt.update(
                apk_sha256=release.file_digest(apk), catalog_reader_version=1, room_version=8
            )
        if name == "backend_acceptance":
            receipt.update(image=IMAGE, schema_revision=REVISION)
        if name == "migration":
            receipt.update(
                from_revision="0023_e9_history", to_revision=REVISION, data_preserved=True
            )
        if name == "rollback":
            receipt.update(strategy="restore", for_revision=REVISION)
        path = tmp_path / (name + ".json")
        write(path, receipt)
        evidence[name] = {"path": path.name, "sha256": release.file_digest(path)}
    spec = {
        "format": 1,
        "channel": "integration",
        "commit": COMMIT,
        "android": {
            "apk": "app.apk",
            "manifest": "android.json",
            "signer_sha256": SIGNER,
            "catalog_reader_version": 1,
        },
        "backend": {"image": IMAGE, "schema_revision": REVISION},
        "catalog": {"manifest": "catalog.json", "package": manifest["path"]},
        "evidence": evidence,
    }
    path = tmp_path / "release.json"
    write(path, spec)
    return path, spec, Inspector()


def test_integration_candidate_validates_real_catalog_without_authorizing_deploy(candidate):
    path, _, inspector = candidate
    report = release.validate(path, inspector)
    assert report["result"] == "CANDIDATE_VALIDATED"
    assert report["deployment_authorized"] is False
    assert report["components"]["catalog"]["kind"] == "demo"
    assert set(report["components"]) == {"android", "backend", "catalog", "evidence"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("commit", "d" * 40),
        ("revision", "old_schema"),
        ("signer", "e" * 64),
        ("app_id", "pl.roseru.kalorie.validation"),
    ],
)
def test_actual_image_schema_signer_and_application_must_match(candidate, field, value):
    path, _, inspector = candidate
    setattr(inspector, field, value)
    assert release.validate(path, inspector)["result"] == "BLOCKED"


def test_collects_all_production_blockers_without_mislabeling_demo(candidate):
    path, spec, inspector = candidate
    spec["channel"] = "production"
    write(path, spec)
    report = release.validate(path, inspector)
    assert {b["component"] for b in report["blockers"]} == {
        "android",
        "backend",
        "catalog",
        "evidence",
    }


def test_tampered_apk_is_rejected_before_inspection(candidate):
    path, _, inspector = candidate
    (path.parent / "app.apk").write_bytes(b"replaced artifact")
    report = release.validate(path, inspector)
    assert {b["component"] for b in report["blockers"]} == {"android", "evidence"}


def test_catalog_hash_and_reader_are_enforced(candidate):
    path, spec, inspector = candidate
    target = path.parent / spec["catalog"]["package"]
    target.write_bytes(target.read_bytes() + b"untrusted trailing data")
    assert any(b["component"] == "catalog" for b in release.validate(path, inspector)["blockers"])


def test_missing_acceptance_is_not_assumed_from_artifact_integrity(candidate):
    path, spec, inspector = candidate
    del spec["evidence"]["restore"]
    write(path, spec)
    report = release.validate(path, inspector)
    assert report["blockers"][0]["component"] == "evidence"


def test_modified_evidence_is_rejected(candidate):
    path, _, inspector = candidate
    (path.parent / "migration.json").write_text('{"result":"PASS"}')
    assert release.validate(path, inspector)["result"] == "BLOCKED"


def test_migration_must_cover_target_schema_and_preserve_data(candidate):
    path, spec, inspector = candidate
    migration = path.parent / "migration.json"
    receipt = json.loads(migration.read_text())
    receipt["data_preserved"] = False
    write(migration, receipt)
    spec["evidence"]["migration"]["sha256"] = release.file_digest(migration)
    write(path, spec)
    assert release.validate(path, inspector)["result"] == "BLOCKED"


def test_duplicate_json_fields_are_rejected(candidate):
    path, _, inspector = candidate
    path.write_text('{"format":1,"format":1}')
    with pytest.raises(release.InvalidCandidate, match="Duplicate"):
        release.validate(path, inspector)


def test_path_traversal_cannot_read_external_artifact(candidate, tmp_path):
    path, spec, inspector = candidate
    spec["android"]["apk"] = "../outside.apk"
    write(path, spec)
    assert release.validate(path, inspector)["result"] == "BLOCKED"


def test_wrong_reader_rejected_before_import(candidate):
    path, spec, inspector = candidate
    manifest_path = path.parent / "catalog.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["min_reader_version"] = 2
    write(manifest_path, manifest)
    report = release.validate(path, inspector)
    assert any("newer Android reader" in b["reason"] for b in report["blockers"])
