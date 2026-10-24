import hashlib
import io
import json
import shutil
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release  # noqa: E402

COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
SIGNER = "c" * 64
REVISION = "0024_e9_history_graph"


def imported_candidate(candidate):
    path, spec, inspector = candidate
    config = {
        "os": "linux",
        "architecture": "amd64",
        "rootfs": {"diff_ids": ["sha256:" + "d" * 64]},
        "config": {"Labels": {"org.opencontainers.image.revision": COMMIT}},
    }
    raw = json.dumps(config).encode()
    config_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    manifest = json.dumps({"config": {"digest": config_digest}}).encode()
    runtime = "sha256:" + hashlib.sha256(manifest).hexdigest()
    index = json.dumps({"manifests": [{"digest": runtime}]}).encode()
    archive = path.parent / "image.tar"
    with tarfile.open(archive, "w") as stream:
        for name, data in (
            ("index.json", index),
            ("blobs/sha256/" + runtime[7:], manifest),
            ("blobs/sha256/" + config_digest[7:], raw),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            stream.addfile(info, io.BytesIO(data))
    spec["backend"].update(
        image=runtime,
        image_archive={
            "path": archive.name,
            "sha256": release.file_digest(archive),
            "config_digest": config_digest,
        },
    )
    image = {
        "Id": runtime,
        "Config": config["config"],
        "RootFS": {"Layers": config["rootfs"]["diff_ids"]},
        "Os": "linux",
        "Architecture": "amd64",
    }
    inspector.image = lambda _: image
    receipt_path = path.parent / spec["evidence"]["backend_acceptance"]["path"]
    receipt = json.loads(receipt_path.read_text())
    receipt["image"] = config_digest
    write(receipt_path, receipt)
    spec["evidence"]["backend_acceptance"]["sha256"] = release.file_digest(receipt_path)
    write(path, spec)
    return path, spec, inspector, image


def test_imported_manifest_id_accepts_original_config_receipt(candidate):
    path, spec, inspector, _ = imported_candidate(candidate)
    result = release.validate(path, inspector)
    assert result["result"] == "CANDIDATE_VALIDATED"
    assert (
        result["components"]["backend"]["receipt_config_digest"]
        == spec["backend"]["image_archive"]["config_digest"]
    )


@pytest.mark.parametrize(
    "damage", ["archive_hash", "config", "runtime", "layers", "os", "missing_archive", "bad_tar"]
)
def test_imported_identity_mismatch_blocks_release(candidate, damage):
    path, spec, inspector, image = imported_candidate(candidate)
    if damage == "archive_hash":
        spec["backend"]["image_archive"]["sha256"] = "0" * 64
    elif damage == "config":
        spec["backend"]["image_archive"]["config_digest"] = "sha256:" + "0" * 64
    elif damage == "runtime":
        spec["backend"]["image"] = "sha256:" + "e" * 64
        image["Id"] = spec["backend"]["image"]
    elif damage == "layers":
        image["RootFS"]["Layers"] = []
    elif damage == "os":
        image["Os"] = "windows"
    elif damage == "missing_archive":
        del spec["backend"]["image_archive"]
    elif damage == "bad_tar":
        archive = path.parent / "image.tar"
        archive.write_bytes(b"broken archive")
        spec["backend"]["image_archive"]["sha256"] = release.file_digest(archive)
    write(path, spec)
    result = release.validate(path, inspector)
    assert result["result"] == "BLOCKED"
    assert result["deployment_authorized"] is False


def write_image_archive(path, entries):
    with tarfile.open(path, "w") as stream:
        for name, raw in entries:
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            stream.addfile(member, io.BytesIO(raw))


@pytest.mark.parametrize("blob", ["manifest", "config"])
def test_rehashed_archive_rejects_changed_blob(candidate, blob):
    path, spec, inspector, _ = imported_candidate(candidate)
    archive = path.parent / spec["backend"]["image_archive"]["path"]
    digest = (
        spec["backend"]["image"]
        if blob == "manifest"
        else spec["backend"]["image_archive"]["config_digest"]
    )
    target = "blobs/sha256/" + digest[7:]
    with tarfile.open(archive, "r:") as stream:
        entries = [(member.name, stream.extractfile(member).read()) for member in stream]
    changed = []
    for name, raw in entries:
        if name == target:
            value = json.loads(raw)
            if blob == "manifest":
                value["annotations"] = {"review": "changed manifest bytes"}
            else:
                value["config"]["Env"] = ["REVIEW_CHANGED=1"]
            raw = json.dumps(value).encode()
        changed.append((name, raw))
    # Keep descriptor names, runtime ID and receipts pinned; only rehash the TAR.
    write_image_archive(archive, changed)
    spec["backend"]["image_archive"]["sha256"] = release.file_digest(archive)
    write(path, spec)
    report = release.validate(path, inspector)
    assert report["result"] == "BLOCKED"
    assert report["deployment_authorized"] is False
    assert report["blockers"] == [
        {"component": "backend", "reason": "Image metadata digest mismatch"}
    ]


def test_rehashed_archive_rejects_duplicate_member(candidate):
    path, spec, inspector, _ = imported_candidate(candidate)
    archive = path.parent / spec["backend"]["image_archive"]["path"]
    with tarfile.open(archive, "r:") as stream:
        entries = [(member.name, stream.extractfile(member).read()) for member in stream]
    # Duplicate identical bytes so only ambiguity, rather than a hash mismatch, fails.
    write_image_archive(archive, [*entries, entries[-1]])
    spec["backend"]["image_archive"]["sha256"] = release.file_digest(archive)
    write(path, spec)
    report = release.validate(path, inspector)
    assert report["result"] == "BLOCKED"
    assert report["deployment_authorized"] is False
    assert report["blockers"] == [{"component": "backend", "reason": "Ambiguous image archive"}]


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


def test_apk_inspector_preserves_unicode_directory_and_verifies_signature(tmp_path, monkeypatch):
    directory = tmp_path / "Zażółć gęślą jaźń"
    directory.mkdir()
    apk = directory / "regular.apk"
    apk.write_bytes(b"fixture")
    calls = []

    def run(arguments, *, cwd=None):
        calls.append((arguments, cwd))
        if arguments[0] == "aapt":
            assert arguments[-1] == "regular.apk" and cwd == directory
            return "package: name='pl.roseru.kalorie' versionCode='21' versionName='0.8.10'\n"
        assert arguments[:5] == ["java", "-jar", "apksigner.jar", "verify", "--verbose"]
        return "Signer #1 certificate SHA-256 digest: " + SIGNER + "\n"

    monkeypatch.setattr(release, "command", run)
    inspector = release.Inspector(
        docker="docker", aapt="aapt", java="java", apksigner="apksigner.jar"
    )
    assert inspector.apk(apk)["signer_sha256"] == SIGNER
    assert len(calls) == 2


def report_candidate(candidate, blocked=False):
    path, spec, inspector, _ = imported_candidate(candidate)
    if blocked:
        receipt = path.parent / spec["evidence"]["restore"]["path"]
        value = json.loads(receipt.read_text())
        value["result"] = "FAIL"
        write(receipt, value)
        spec["evidence"]["restore"]["sha256"] = release.file_digest(receipt)
        write(path, spec)
    expected = "BLOCKED" if blocked else "CANDIDATE_VALIDATED"
    assert release.validate(path, inspector)["result"] == expected
    sources = {
        "manifest": path,
        "apk": path.parent / spec["android"]["apk"],
        "android_manifest": path.parent / spec["android"]["manifest"],
        "backend_archive": path.parent / spec["backend"]["image_archive"]["path"],
        "catalog_manifest": path.parent / spec["catalog"]["manifest"],
        "catalog_package": path.parent / spec["catalog"]["package"],
        **{name: path.parent / entry["path"] for name, entry in spec["evidence"].items()},
    }
    return path, spec, inspector, sources


def report_arguments(monkeypatch, manifest, output, **tools):
    arguments = ["release.py", "--manifest", str(manifest), "--output", str(output)]
    for flag in ("docker", "aapt", "java", "apksigner-jar"):
        arguments.extend(["--" + flag, str(tools.get(flag, "unused-report-test-" + flag))])
    monkeypatch.setattr(sys, "argv", arguments)


def report_alias(source, kind):
    if kind == "direct":
        return source
    target = source.parent / (source.name + ".report-" + kind)
    try:
        if kind == "symlink":
            target.symlink_to(source.name)
        else:
            target.hardlink_to(source)
    except OSError as error:
        pytest.skip(f"File {kind} unavailable: {error}")
    return target


def forbid_report_inspection(monkeypatch):
    def forbidden(**_kwargs):
        pytest.fail("An input collision must be rejected before constructing the inspector")

    monkeypatch.setattr(release, "Inspector", forbidden)


@pytest.mark.parametrize("blocked", [False, True], ids=["valid", "blocked"])
@pytest.mark.parametrize(
    "source",
    [
        "manifest",
        "apk",
        "android_manifest",
        "backend_archive",
        "catalog_manifest",
        "catalog_package",
        "android_acceptance",
        "backend_acceptance",
        "migration",
        "rollback",
        "restore",
    ],
)
def test_report_output_preserves_each_release_input(candidate, monkeypatch, source, blocked):
    path, _, _, sources = report_candidate(candidate, blocked)
    before = {item: item.read_bytes() for item in sources.values()}
    report_arguments(monkeypatch, path, sources[source])
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert all(item.read_bytes() == content for item, content in before.items())


@pytest.mark.parametrize("source", ["manifest", "apk", "backend_archive", "restore"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_report_output_preserves_input_aliases(candidate, monkeypatch, source, kind):
    path, _, inspector, sources = report_candidate(candidate, blocked=True)
    before = {item: item.read_bytes() for item in sources.values()}
    output = report_alias(sources[source], kind)
    report_arguments(monkeypatch, path, output)
    # Also prove preservation with a working inspector, not only an inspection sentinel.
    monkeypatch.setattr(release, "Inspector", lambda **_kwargs: inspector)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert all(item.read_bytes() == content for item, content in before.items())
    assert output.read_bytes() == before[sources[source]]


@pytest.mark.parametrize("tool", ["docker", "aapt", "java", "apksigner-jar"])
def test_report_output_preserves_explicit_inspection_tools(candidate, monkeypatch, tool):
    path, _, _, _ = report_candidate(candidate)
    binary = path.parent / "inspection-tool"
    binary.write_bytes(b"synthetic inspection tool, never executed")
    report_arguments(monkeypatch, path, binary, **{tool: binary})
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert binary.read_bytes() == b"synthetic inspection tool, never executed"


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_report_output_preserves_inspection_tool_aliases(candidate, monkeypatch, kind):
    path, _, _, _ = report_candidate(candidate)
    binary = path.parent / "java-tool"
    binary.write_bytes(b"synthetic Java tool")
    report_arguments(monkeypatch, path, report_alias(binary, kind), java=binary)
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert binary.read_bytes() == b"synthetic Java tool"


def test_report_output_preserves_tool_resolved_from_path(candidate, monkeypatch):
    path, _, _, _ = report_candidate(candidate)
    directory = path.parent / "bin"
    directory.mkdir()
    binary = directory / "report-tool.exe"
    binary.write_bytes(b"synthetic PATH tool")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(directory))
    report_arguments(monkeypatch, path, binary, docker=binary.name)
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert binary.read_bytes() == b"synthetic PATH tool"


@pytest.mark.parametrize("tool", ["aapt", "java"])
def test_report_output_preserves_relative_apk_inspection_tools(candidate, monkeypatch, tool):
    path, _, _, _ = report_candidate(candidate)
    binary = path.parent / "relative-inspection-tool.exe"
    binary.write_bytes(b"synthetic APK directory tool")
    binary.chmod(0o700)
    report_arguments(monkeypatch, path, binary, **{tool: binary.name})
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert binary.read_bytes() == b"synthetic APK directory tool"


def test_report_output_preserves_tool_from_relative_apk_path(candidate, monkeypatch):
    path, _, _, _ = report_candidate(candidate)
    directory = path.parent / "bin"
    directory.mkdir()
    binary = directory / "report-tool.exe"
    binary.write_bytes(b"synthetic relative PATH tool")
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", "bin")
    report_arguments(monkeypatch, path, binary, aapt=binary.name)
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert binary.read_bytes() == b"synthetic relative PATH tool"


@pytest.mark.parametrize("context", ["cli", "apk"])
def test_report_output_preserves_windows_exe_when_pathext_prefers_com(
    candidate, monkeypatch, context
):
    path, _, _, _ = report_candidate(candidate)
    cli = path.parent / "cli"
    cli.mkdir()
    monkeypatch.chdir(cli)
    directory = (cli if context == "cli" else path.parent) / "bin"
    directory.mkdir()
    executable = directory / "review-inspector.exe"
    executable.write_bytes(b"synthetic CreateProcess executable")
    preferred = directory / "review-inspector.com"
    preferred.write_bytes(b"synthetic PATHEXT preferred executable")
    monkeypatch.setattr(release, "os", SimpleNamespace(name="nt", get_exec_path=lambda: ["bin"]))
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: str(preferred) if Path(name) == directory / "review-inspector" else None,
    )
    report_arguments(monkeypatch, path, executable, java="review-inspector")
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert executable.read_bytes() == b"synthetic CreateProcess executable"
    assert preferred.read_bytes() == b"synthetic PATHEXT preferred executable"


def test_report_output_preserves_relative_jar_used_by_real_apk_inspector(candidate, monkeypatch):
    path, spec, _, _ = report_candidate(candidate)
    apk = path.parent / spec["android"]["apk"]
    jar = apk.parent / "review-relative-apksigner.jar"
    jar.write_bytes(b"synthetic JAR beside APK")
    calls = []

    def run(arguments, *, cwd=None):
        calls.append(arguments)
        assert cwd == apk.parent
        if arguments[1:3] == ["dump", "badging"]:
            return "package: name='pl.roseru.kalorie' versionCode='21' versionName='0.8.10'\n"
        assert arguments[1:3] == ["-jar", jar.name]
        assert (cwd / arguments[2]).read_bytes() == b"synthetic JAR beside APK"
        return "Signer #1 certificate SHA-256 digest: " + SIGNER + "\n"

    def inspect(_manifest, inspector):
        assert inspector.apk(apk)["signer_sha256"] == SIGNER
        return {"result": "BLOCKED", "deployment_authorized": False}

    monkeypatch.setattr(release, "command", run)
    monkeypatch.setattr(release, "validate", inspect)
    report_arguments(monkeypatch, path, jar, **{"apksigner-jar": jar.name})
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert jar.read_bytes() == b"synthetic JAR beside APK"
    assert calls == []


@pytest.mark.parametrize("blocked", [False, True], ids=["valid", "blocked"])
@pytest.mark.parametrize("existing", [False, True], ids=["new-report", "old-report"])
def test_report_output_still_creates_and_updates_reports(candidate, monkeypatch, blocked, existing):
    path, _, inspector, sources = report_candidate(candidate, blocked)
    before = {item: item.read_bytes() for item in sources.values()}
    output = path.parent / "report.json"
    if existing:
        write(output, {"previous": "report"})
    report_arguments(monkeypatch, path, output)
    monkeypatch.setattr(release, "Inspector", lambda **_kwargs: inspector)
    assert release.main() == int(blocked)
    report = json.loads(output.read_text())
    assert report["result"] == ("BLOCKED" if blocked else "CANDIDATE_VALIDATED")
    assert report["deployment_authorized"] is False
    assert all(item.read_bytes() == content for item, content in before.items())


def test_report_output_ignores_unavailable_unused_path_entries(candidate, monkeypatch):
    path, _, inspector, _ = report_candidate(candidate)
    unavailable = path.parent / "unavailable-bin"
    output = path.parent / "report.json"
    write(output, {"previous": "report"})
    resolve = Path.resolve

    def inaccessible(self, *args, **kwargs):
        if unavailable in self.parents:
            raise PermissionError("Unused PATH directory cannot be inspected")
        return resolve(self, *args, **kwargs)

    monkeypatch.setenv("PATH", str(unavailable))
    monkeypatch.setattr(Path, "resolve", inaccessible)
    monkeypatch.setattr(release, "Inspector", lambda **_kwargs: inspector)
    report_arguments(monkeypatch, path, output)
    assert release.main() == 0
    assert json.loads(output.read_text())["result"] == "CANDIDATE_VALIDATED"


@pytest.mark.parametrize("source", ["apk", "restore", "old_report"])
def test_report_output_malformed_manifest_preserves_existing_targets(
    candidate, monkeypatch, source
):
    path, _, _, sources = report_candidate(candidate)
    path.write_text("{broken JSON", encoding="utf-8")
    if source == "old_report":
        sources[source] = path.parent / "old-report.json"
        write(sources[source], {"result": "BLOCKED", "deployment_authorized": False})
    before = {item: item.read_bytes() for item in sources.values()}
    report_arguments(monkeypatch, path, sources[source])
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Unreadable release specification"):
        release.main()
    assert all(item.read_bytes() == content for item, content in before.items())


def test_report_output_malformed_manifest_allows_new_blocked_report(candidate, monkeypatch):
    path, _, _, _ = report_candidate(candidate)
    path.write_text("{broken JSON", encoding="utf-8")
    output = path.parent / "new-report.json"
    before = path.read_bytes()
    report_arguments(monkeypatch, path, output)
    assert release.main() == 1
    assert json.loads(output.read_text())["result"] == "BLOCKED"
    assert path.read_bytes() == before


@pytest.mark.parametrize("selected", ["first.apk", "second.apk"])
def test_report_output_protects_both_duplicate_artifact_references(tmp_path, monkeypatch, selected):
    path = tmp_path / "duplicate.json"
    path.write_text('{"android":{"apk":"first.apk","apk":"second.apk"}}', encoding="utf-8")
    for name in ("first.apk", "second.apk"):
        (tmp_path / name).write_bytes(name.encode())
    before = {item: item.read_bytes() for item in tmp_path.iterdir()}
    report_arguments(monkeypatch, path, tmp_path / selected)
    forbid_report_inspection(monkeypatch)
    with pytest.raises(ValueError, match="Report must not overwrite"):
        release.main()
    assert all(item.read_bytes() == content for item, content in before.items())
