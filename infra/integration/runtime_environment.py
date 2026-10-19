"""Install and qualify a locked backend for an archived maintenance runtime."""

import argparse
import ast
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PROBE = """
import json, sys
from pathlib import Path
import calorie_app.health as health
print(json.dumps({'prefix': str(Path(sys.prefix).resolve()),
                  'module': str(Path(health.__file__).resolve()),
                  'revision': health.EXPECTED_REVISION}))
"""


def native_path(path):
    value = str(Path(path).resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        if value.startswith("\\\\"):
            return "\\\\?\\UNC\\" + value[2:]
        return "\\\\?\\" + value
    return value


def canonical_path(path):
    value = str(path)
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
    return Path(value).resolve()


def source_revision(backend):
    tree = ast.parse((backend / "src/calorie_app/health.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "EXPECTED_REVISION" for t in node.targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, str) and value:
                    return value
    raise ValueError("Archived backend revision missing")


def qualify(runtime, python, uv):
    runtime = Path(runtime).resolve(strict=True)
    backend = runtime / "backend"
    for name in ("pyproject.toml", "uv.lock", "src/calorie_app/health.py"):
        path = (backend / name).resolve(strict=True)
        if not path.is_relative_to(runtime):
            raise ValueError("Backend must remain inside its runtime")
    expected = source_revision(backend)
    environment = backend / ".venv"
    if environment.exists() and environment.resolve() != environment:
        raise ValueError("Runtime environment must not be redirected")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "UV_")) and key != "VIRTUAL_ENV"
    }
    env.update(UV_PROJECT_ENVIRONMENT=native_path(environment), UV_NO_PROGRESS="1")
    # Build backends may strip the Windows extended-path prefix. Build the wheel
    # from a short-lived source copy; installed code remains wholly in this runtime.
    with tempfile.TemporaryDirectory(prefix="o3-runtime-") as temporary:
        staged = Path(temporary) / "backend"
        shutil.copytree(
            native_path(backend),
            staged,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", ".pytest_cache", ".ruff_cache"),
        )
        install = subprocess.run(
            [
                str(uv),
                "--no-config",
                "sync",
                "--project",
                str(staged),
                "--locked",
                "--offline",
                "--no-editable",
                "--link-mode",
                "copy",
                "--no-dev",
                "--no-python-downloads",
                "--python",
                str(python),
            ],
            cwd=temporary,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
    if install.returncode:
        (runtime / "runtime-install-error.log").write_text(
            install.stderr or "Locked dependency installation failed", encoding="utf-8"
        )
        raise RuntimeError("Locked offline installation failed; inspect runtime-install-error.log")
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    executable = scripts / ("python.exe" if os.name == "nt" else "python")
    result = subprocess.run(
        [native_path(executable), "-I", "-c", PROBE],
        cwd=native_path(runtime),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    proof = json.loads(result.stdout)
    if canonical_path(proof["prefix"]) != environment.resolve():
        raise ValueError("Interpreter does not belong to this runtime")
    if not canonical_path(proof["module"]).is_relative_to(environment.resolve()):
        raise ValueError("Backend imported from outside its runtime environment")
    if proof["revision"] != expected:
        raise ValueError("Installed backend differs from archived revision")
    if os.name == "nt" and not (scripts / "pythonw.exe").is_file():
        raise ValueError("Windowless runtime interpreter missing")
    proof.update(
        python=native_path(executable), pythonw=native_path(scripts / "pythonw.exe"), result="PASS"
    )
    (runtime / "runtime-environment.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.runtime, args.python, args.uv)))


if __name__ == "__main__":
    main()
