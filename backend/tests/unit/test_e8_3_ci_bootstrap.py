"""CI environment contract; actual Docker/SCRAM remains a separate integration proof."""

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import URL

from tests.support import e8_3_ci as bootstrap


def test_incomplete_explicit_files_are_rejected_instead_of_skipping_operator(tmp_path):
    files = {key: str(tmp_path / key) for key in bootstrap.CREDENTIAL_KEYS}
    for name in files.values():
        Path(name).write_text("{}", encoding="utf-8")
    assert bootstrap.explicit_credentials_complete({}) is False
    assert bootstrap.explicit_credentials_complete(files)
    for key in bootstrap.CREDENTIAL_KEYS:
        partial = dict(files)
        del partial[key]
        with pytest.raises(ValueError, match="together"):
            bootstrap.explicit_credentials_complete(partial)
    Path(files[bootstrap.CREDENTIAL_KEYS[-1]]).unlink()
    with pytest.raises(ValueError, match="missing"):
        bootstrap.explicit_credentials_complete(files)


@pytest.mark.parametrize("fail_consumer", [False, True])
def test_clean_ci_exports_all_consumer_files_and_restores_environment(
    monkeypatch, tmp_path, fail_consumer
):
    for key in (*bootstrap.CREDENTIAL_KEYS, "E8_3_HTTP_PROBE_PORT_BASE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("E8_3_HTTP_PROBE_PORT_BASE", "original-port")
    paths = {name: str(tmp_path / name) for name in ("source", "audit", "operator")}
    for path in paths.values():
        Path(path).write_text("{}", encoding="utf-8")
    events = []

    @contextmanager
    def services(folder):
        events.append("started")
        try:
            yield paths
        finally:
            events.append("closed")

    monkeypatch.setattr(bootstrap, "private_servers", services)
    try:
        with bootstrap.configured_servers(tmp_path):
            assert [os.environ[key] for key in bootstrap.CREDENTIAL_KEYS] == [
                paths[name] for name in ("source", "audit", "operator")
            ]
            assert os.environ["E8_3_HTTP_PROBE_PORT_BASE"] == "18181"
            if fail_consumer:
                raise RuntimeError("consumer failed")
    except RuntimeError:
        assert fail_consumer
    assert events == ["started", "closed"]
    assert all(key not in os.environ for key in bootstrap.CREDENTIAL_KEYS)
    assert os.environ["E8_3_HTTP_PROBE_PORT_BASE"] == "original-port"


def test_bootstrap_calls_hardened_provision_and_binds_operator_to_source(monkeypatch, tmp_path):
    commands, provisions, migrations = [], [], []
    run_id = None

    def docker(*arguments, environment=None):
        nonlocal run_id
        commands.append(arguments)
        if arguments[0] == "run":
            run_id = arguments[arguments.index("--label") + 1].split("=", 1)[1]
            assert "--env" in arguments and "POSTGRES_PASSWORD" in arguments
            return (
                "source-container"
                if len([c for c in commands if c[0] == "run"]) == 1
                else "audit-container"
            )
        if arguments[0] == "port":
            return "127.0.0.1:55483" if arguments[1] == "source-container" else "127.0.0.1:55493"
        if arguments[0] == "inspect":
            return run_id
        return ""

    @contextmanager
    def connected(**kwargs):
        yield

    def initialized(host, port, name, passwords):
        urls = {
            key + "_url": URL.create(
                "postgresql+psycopg",
                username=key,
                password=passwords[key],
                host=host,
                port=port,
                database=name,
            ).render_as_string(hide_password=False)
            for key in ("admin", "migrator", "api", "worker")
        }
        return SimpleNamespace(
            **urls,
            __dataclass_fields__=urls,
            migrate=lambda revision: migrations.append((name, revision)),
        )

    def provision(arguments, **kwargs):
        provisions.append((arguments, kwargs["env"]))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bootstrap, "docker", docker)
    monkeypatch.setattr(bootstrap.psycopg, "connect", connected)
    monkeypatch.setattr(bootstrap, "initialize_empty_cluster", initialized)
    monkeypatch.setattr(bootstrap.subprocess, "run", provision)
    with bootstrap.private_servers(tmp_path) as services:
        from sqlalchemy.engine import make_url

        operator = make_url(json.loads(Path(services["operator"]).read_text())["operator_url"])
        source = make_url(json.loads(Path(services["source"]).read_text())["admin_url"])
        assert (operator.host, operator.port, operator.database) == (
            source.host,
            source.port,
            source.database,
        )
        assert operator.username == "e8_3_parent_deletion_login" and operator.password
        assert len(provisions) == 1
        argv, environment = provisions[0]
        assert Path(argv[-1]).parts[-3:] == ("infra", "local", "provision_deletion_operator.py")
        assert operator.password == environment["DELETION_OPERATOR_PASSWORD"]
        assert operator.password not in " ".join(argv)
        assert migrations == [
            ("e8_3_ci_source_test", "0020_e8_nemesis_integration"),
            ("e8_3_ci_audit_test", "0017_e8_purge_commit"),
        ]
    assert [c for c in commands if c[0] == "rm"] == [
        ("rm", "--force", "audit-container"),
        ("rm", "--force", "source-container"),
    ]
