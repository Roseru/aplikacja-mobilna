import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime_environment as runtime


@pytest.fixture
def archived(tmp_path):
    backend = tmp_path / "backend"
    health = backend / "src/calorie_app/health.py"
    health.parent.mkdir(parents=True)
    health.write_text('EXPECTED_REVISION = "0024_original"\n', encoding="utf-8")
    (backend / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (backend / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    scripts = backend / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    scripts.mkdir(parents=True)
    (scripts / "pythonw.exe").touch()
    return tmp_path


def fake_install(monkeypatch, archived, mutate=None, fail=False):
    calls = []
    environment = archived / "backend/.venv"

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) == 1:
            if fail:
                return subprocess.CompletedProcess(command, 1, "", "dependency unavailable offline")
            return subprocess.CompletedProcess(command, 0)
        proof = {
            "prefix": str(environment),
            "module": str(environment / "lib/site-packages/calorie_app/health.py"),
            "revision": "0024_original",
        }
        if mutate:
            proof.update(mutate)
        return subprocess.CompletedProcess(command, 0, json.dumps(proof))

    monkeypatch.setattr(runtime.subprocess, "run", run)
    return calls


def test_locked_environment_ignores_editable_checkout_and_ambient_settings(archived, monkeypatch):
    for key in ("UV_PROJECT_ENVIRONMENT", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        monkeypatch.setenv(key, "/other/checkout")
    calls = fake_install(monkeypatch, archived)
    proof = runtime.qualify(archived, "bootstrap-python", "uv")
    command, kwargs = calls[0]
    assert {"--locked", "--offline", "--no-editable", "--no-dev"} <= set(command)
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == runtime.native_path(
        archived / "backend/.venv"
    )
    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & kwargs["env"].keys()
    assert calls[1][0][1:3] == ["-I", "-c"]
    assert proof["revision"] == "0024_original"
    assert json.loads((archived / "runtime-environment.json").read_text())["result"] == "PASS"


@pytest.mark.parametrize(
    "mutate,error",
    [
        ({"module": "/editable-checkout/calorie_app/health.py"}, "outside"),
        ({"prefix": "/another-venv"}, "Interpreter"),
        ({"revision": "0026_other_branch"}, "revision"),
    ],
)
def test_wrong_import_interpreter_or_schema_cannot_qualify(archived, monkeypatch, mutate, error):
    fake_install(monkeypatch, archived, mutate)
    with pytest.raises(ValueError, match=error):
        runtime.qualify(archived, "python", "uv")
    assert not (archived / "runtime-environment.json").exists()


def test_unavailable_locked_dependency_cannot_create_qualification(archived, monkeypatch):
    calls = fake_install(monkeypatch, archived, fail=True)
    with pytest.raises(RuntimeError, match="offline installation failed"):
        runtime.qualify(archived, "python", "uv")
    assert len(calls) == 1
    assert not (archived / "runtime-environment.json").exists()
    assert (archived / "runtime-install-error.log").read_text() == "dependency unavailable offline"


def test_missing_archived_source_refused_before_install(archived, monkeypatch):
    (archived / "backend/src/calorie_app/health.py").unlink()
    calls = fake_install(monkeypatch, archived)
    with pytest.raises(FileNotFoundError):
        runtime.qualify(archived, "python", "uv")
    assert not calls
