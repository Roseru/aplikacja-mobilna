import os
import stat
import subprocess
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.image_preparation import prepare_image
from calorie_app.modules.ai.storage import PhotoStorage, _Windows


def make_private(root):
    root.mkdir()
    if os.name == "nt":
        sid = _Windows().sid
        subprocess.run(
            [
                "icacls",
                str(root),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    else:
        root.chmod(0o700)
    return root


@pytest.fixture
def private_root(tmp_path):
    return make_private(tmp_path / "private-photos")


@pytest.fixture
def jpeg():
    output = BytesIO()
    Image.new("RGB", (30, 20), "red").save(output, format="PNG")
    return prepare_image(output.getvalue()).data


def test_real_activation_read_cleanup_idempotent_and_permissions(private_root, jpeg):
    storage, key = PhotoStorage(private_root), uuid4().hex
    assert storage.availability()
    storage.activate(key, jpeg)
    assert storage.read(key) == jpeg
    assert list(private_root.iterdir()) == [private_root / (key + ".jpg")]
    if os.name != "nt":
        assert stat.S_IMODE((private_root / (key + ".jpg")).stat().st_mode) == 0o600
    storage.delete(key)
    storage.delete(key)
    assert list(private_root.iterdir()) == []
    with pytest.raises(DomainError) as error:
        storage.read(key)
    assert error.value.status == 410


def test_root_missing_relative_or_traversal_never_created(tmp_path, jpeg):
    for root in (tmp_path / "missing", Path("relative"), tmp_path / ".." / "root"):
        storage = PhotoStorage(root)
        assert not storage.availability()
        with pytest.raises(DomainError) as error:
            storage.activate(uuid4().hex, jpeg)
        assert error.value.status == 503
        with pytest.raises(DomainError) as error:
            storage.read(uuid4().hex)
        assert error.value.status == 503
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    "key",
    [
        "../outside",
        "x/y",
        "C:\\private",
        "A" * 32,
        "f" * 31,
        "f" * 33,
        "f" * 32 + ".jpg",
        "",
        ".",
        "..",
    ],
)
def test_key_has_no_path_or_user_filename(private_root, jpeg, key):
    storage = PhotoStorage(private_root)
    for call in (
        lambda: storage.activate(key, jpeg),
        lambda: storage.read(key),
        lambda: storage.delete(key),
    ):
        with pytest.raises(DomainError) as error:
            call()
        assert error.value.status == 503
    assert list(private_root.iterdir()) == []


def test_preexisting_key_never_overwritten(private_root, jpeg):
    storage, key = PhotoStorage(private_root), uuid4().hex
    storage.activate(key, jpeg)
    with pytest.raises(DomainError):
        storage.activate(key, jpeg)
    assert storage.read(key) == jpeg
    assert not (private_root / (key + ".staging")).exists()


def test_only_bounded_prepared_jpeg_can_be_written(private_root):
    storage = PhotoStorage(private_root)
    for raw in (b"", b"PNG-original", b"\xff\xd8unfinished", b"x" * (5 * 1024 * 1024 + 1)):
        with pytest.raises(DomainError):
            storage.activate(uuid4().hex, raw)
    assert list(private_root.iterdir()) == []


def test_write_fsync_precedes_atomic_activation(private_root, jpeg, monkeypatch):
    storage, key = PhotoStorage(private_root), uuid4().hex
    calls = []
    real_sync = os.fsync

    def sync(descriptor):
        calls.append("fsync")
        assert (private_root / (key + ".staging")).exists() or os.name != "nt"
        return real_sync(descriptor)

    monkeypatch.setattr(os, "fsync", sync)
    if os.name == "nt":
        # Actual Win32 atomic MoveFileExW(WRITE_THROUGH) follows file fsync.
        storage.activate(key, jpeg)
        assert calls == ["fsync"]
    else:
        real_rename = os.rename

        def rename(*args, **kwargs):
            assert calls == ["fsync"]
            calls.append("rename")
            return real_rename(*args, **kwargs)

        monkeypatch.setattr(os, "rename", rename)
        storage.activate(key, jpeg)
        assert calls == ["fsync", "rename", "fsync"]
    assert storage.read(key) == jpeg


def test_fsync_failure_compensates_staging(private_root, jpeg, monkeypatch):
    def failure(*args):
        raise OSError("synthetic-fsync-failure")

    monkeypatch.setattr(os, "fsync", failure)
    with pytest.raises(DomainError) as error:
        PhotoStorage(private_root).activate(uuid4().hex, jpeg)
    assert error.value.status == 503
    assert list(private_root.iterdir()) == []


def test_orphan_candidates_grace_limit_and_staging(private_root, jpeg):
    storage = PhotoStorage(private_root)
    old, fresh, staged = uuid4().hex, uuid4().hex, uuid4().hex
    storage.activate(old, jpeg)
    storage.activate(fresh, jpeg)
    staging = private_root / (staged + ".staging")
    staging.write_bytes(jpeg)
    if os.name != "nt":
        staging.chmod(0o600)
    os.utime(private_root / (old + ".jpg"), (100, 100))
    os.utime(staging, (100, 100))
    assert set(storage.candidates(60, 1000)) == {old, staged}
    assert len(storage.candidates(60, 1)) == 1
    assert fresh not in storage.candidates(60, 1000)
    storage.delete(staged)
    assert not staging.exists()


def test_fresh_staging_protects_old_active_key(private_root, jpeg):
    storage, key = PhotoStorage(private_root), uuid4().hex
    storage.activate(key, jpeg)
    os.utime(private_root / (key + ".jpg"), (100, 100))
    staging = private_root / (key + ".staging")
    staging.write_bytes(jpeg)
    if os.name != "nt":
        staging.chmod(0o600)
    assert storage.candidates(60, 1000) == []


def test_world_readable_root_fail_closed(tmp_path, jpeg):
    root = make_private(tmp_path / "public-root")
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(root), "/grant", "*S-1-1-0:(OI)(CI)R"], check=True, capture_output=True
        )
    else:
        root.chmod(0o755)
    storage = PhotoStorage(root)
    assert not storage.availability()
    with pytest.raises(DomainError) as error:
        storage.activate(uuid4().hex, jpeg)
    assert error.value.status == 503 and list(root.iterdir()) == []


def test_world_readable_file_and_hardlink_rejected(private_root, jpeg):
    storage, key = PhotoStorage(private_root), uuid4().hex
    storage.activate(key, jpeg)
    source = private_root / (key + ".jpg")
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(source), "/grant", "*S-1-1-0:R"], check=True, capture_output=True
        )
    else:
        source.chmod(0o644)
    with pytest.raises(DomainError):
        storage.read(key)
    with pytest.raises(DomainError):
        storage.delete(key)
    if os.name == "nt":
        subprocess.run(
            ["icacls", str(source), "/remove:g", "*S-1-1-0"], check=True, capture_output=True
        )
    else:
        source.chmod(0o600)
    linked = private_root / (uuid4().hex + ".jpg")
    os.link(source, linked)
    with pytest.raises(DomainError):
        storage.read(key)
    with pytest.raises(DomainError):
        storage.delete(key)
    assert source.exists() and linked.exists()


def test_real_symlink_or_windows_junction_root_and_component_rejected(tmp_path, private_root):
    link = tmp_path / "linked-root"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(private_root)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(private_root, target_is_directory=True)
    assert not PhotoStorage(link).availability()
    child = make_private(private_root / "child")
    assert not PhotoStorage(link / "child").availability()
    assert PhotoStorage(child).availability()


def test_directory_in_place_of_object_rejected(private_root):
    key = uuid4().hex
    (private_root / (key + ".jpg")).mkdir()
    storage = PhotoStorage(private_root)
    for call in (
        lambda: storage.read(key),
        lambda: storage.delete(key),
        lambda: storage.candidates(0, 1000),
    ):
        with pytest.raises(DomainError) as error:
            call()
        assert error.value.status == 503


@pytest.mark.parametrize("grace,limit", [(-1, 1), (0, 0), (0, 1001), (0, 1.5), (True, 1)])
def test_invalid_sweep_limit(private_root, grace, limit):
    with pytest.raises(ValueError):
        PhotoStorage(private_root).candidates(grace, limit)
