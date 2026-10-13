"""Archive proof uses realPG17 and never inherits a different connection target."""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL

from tests.support import e8_3_archive as tools


def test_archive_environment_binds_source_and_preserves_parent(monkeypatch):
    inherited = {
        "PGSERVICE": "audit",
        "PGHOSTADDR": "192.0.2.1",
        "PGPASSFILE": "other",
        "PGDATABASE": "wrong",
    }
    for key, value in inherited.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("E8_3_REVIEW_LABEL", "kept")
    source = URL.create(
        "postgresql+psycopg",
        host="127.0.0.1",
        port=55513,
        username="migrator",
        password="private-secret",
        database="owned_source_test",
    )
    environment = tools.archive_environment(source)
    assert {k: v for k, v in environment.items() if k.startswith("PG")} == {
        "PGHOST": "127.0.0.1",
        "PGPORT": "55513",
        "PGUSER": "migrator",
        "PGPASSWORD": "private-secret",
        "PGDATABASE": "owned_source_test",
    }
    assert environment["E8_3_REVIEW_LABEL"] == "kept"
    assert all(os.environ[key] == value for key, value in inherited.items())


def test_explicit_pg17_binary_is_used_without_secret_arguments(monkeypatch, tmp_path):
    suffix = ".exe" if os.name == "nt" else ""
    path = tmp_path / ("pg_dump" + suffix)
    path.touch()
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(returncode=0, stdout="pg_dump (PostgreSQL) 17.11")

    monkeypatch.setattr(tools.subprocess, "run", run)
    env = {"E8_3_POSTGRES_BIN": str(tmp_path), "PGPASSWORD": "private-secret"}
    result = tools.pg_command("pg_dump", ["--dbname", "owned_source_test"], env)
    assert result == [str(path), "--dbname", "owned_source_test"]
    assert calls == [[str(path), "--version"]]
    assert "private-secret" not in " ".join(result)


def test_explicit_wrong_major_fails_without_fallback(monkeypatch, tmp_path):
    suffix = ".exe" if os.name == "nt" else ""
    (tmp_path / ("pg_restore" + suffix)).touch()
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="pg_restore (PostgreSQL) 16.13"),
    )
    monkeypatch.setattr(
        tools.shutil,
        "which",
        lambda name: pytest.fail("explicitwrongclient cannot silentlyfallback"),
    )
    with pytest.raises(RuntimeError, match="PostgreSQL17"):
        tools.pg_command("pg_restore", [], {"E8_3_POSTGRES_BIN": str(tmp_path)})


def test_linux_uses_verified_pinned_client_and_streams_restore(monkeypatch, tmp_path):
    native = tmp_path / "pg_dump16"
    native.touch()
    monkeypatch.setattr(tools, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(
        tools.shutil, "which", lambda name: str(native) if name == "pg_restore" else "docker"
    )
    calls = []

    def run(arguments, **kwargs):
        calls.append(arguments)
        return SimpleNamespace(
            returncode=0,
            stdout="PostgreSQL 17.11" if arguments[0] == "docker" else "PostgreSQL 16.13",
        )

    monkeypatch.setattr(tools.subprocess, "run", run)
    result = tools.pg_command(
        "pg_restore",
        ["--dbname", "owned_source_test", "--exit-on-error"],
        {"PGPASSWORD": "private-secret"},
        interactive=True,
    )
    assert calls[-1] == ["docker", "run", "--rm", tools.IMAGE, "pg_restore", "--version"]
    assert "--network" in result and "host" in result and "--interactive" in result
    assert result[result.index(tools.IMAGE) + 1 :] == [
        "pg_restore",
        "--dbname",
        "owned_source_test",
        "--exit-on-error",
    ]
    assert "PGPASSWORD" in result and "private-secret" not in " ".join(result)
    assert "--volume" not in result and "--mount" not in result


def test_missing_or_unverified_docker_client_is_error(monkeypatch):
    monkeypatch.setattr(tools, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="PostgreSQL17"):
        tools.pg_command("pg_dump", [], {})
    monkeypatch.setattr(tools.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="PostgreSQL 16.13"),
    )
    with pytest.raises(RuntimeError, match="PostgreSQL17"):
        tools.pg_command("pg_dump", [], {})


@pytest.mark.parametrize(
    "host,database", [("127.0.0.1", "calorie_app"), ("192.0.2.1", "owned_test")]
)
def test_archive_environment_refuses_non_owned_target(host, database):
    source = URL.create(
        "postgresql+psycopg",
        host=host,
        port=5432,
        username="migrator",
        password="private-secret",
        database=database,
    )
    with pytest.raises(ValueError, match="owned loopback"):
        tools.archive_environment(source)
