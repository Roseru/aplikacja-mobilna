import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e4_observer as observer


@pytest.fixture
def plan():
    return {
        **{
            key: str(uuid4())
            for key in (
                "trial_id",
                "owner_id",
                "operation_id",
                "entity_id",
                "sync_epoch",
            )
        },
        "local_date": "2026-10-19",
        "operation_sha256": "a" * 64,
        "item_count": 1,
        "expected_schema": "0024_e9_history_graph",
        "expected_api_image": "sha256:" + "b" * 64,
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("owner_id", "'; DELETE FROM app.meals; --"),
        ("local_date", "2026-10-19'; DELETE FROM app.meals; --"),
        ("expected_schema", "0024'; SELECT 1; --"),
        ("operation_sha256", "not-a-hash"),
        ("item_count", True),
        ("item_count", 0),
        ("item_count", 101),
    ],
)
def test_invalid_input_cannot_generate_sql(plan, key, value):
    plan[key] = value
    with pytest.raises(ValueError):
        observer.observation_sql(plan, "C0")


def test_failed_command_does_not_expose_captured_credentials_or_payload(monkeypatch):
    def fail(*args, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(args[0], 1, "private bearer/body", "private DB rows")

    monkeypatch.setattr(observer.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="raw database output withheld") as error:
        observer.docker_command("docker", "exec")
    assert "private" not in str(error.value)


def test_existing_receipt_cannot_be_overwritten(plan, tmp_path, monkeypatch, capsys):
    plan_path, settings, receipt = (tmp_path / p for p in ("plan.json", "settings.json", "c0.json"))
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    settings.write_text("{}", encoding="utf-8")
    receipt.write_text("original evidence", encoding="utf-8")
    monkeypatch.setattr(observer, "capture", lambda *args: {"secret": "not printed"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observer",
            "--plan",
            str(plan_path),
            "capture",
            "--settings",
            str(settings),
            "--phase",
            "C0",
            "--output",
            str(receipt),
        ],
    )
    assert observer.main() == 1
    assert receipt.read_text() == "original evidence"
    assert "not printed" not in capsys.readouterr().out


@pytest.mark.parametrize("wrong", ["postgres_label", "api_label", "image"])
def test_wrong_container_or_image_prevents_database_query(plan, tmp_path, monkeypatch, wrong):
    (tmp_path / "config.json").write_text('{"project":"owned-test"}', encoding="utf-8")
    calls = []

    def inspect(docker, *arguments, **kwargs):
        calls.append(arguments)
        assert arguments[0] == "inspect", "Database must not be queried after identity failure"
        service = "postgres" if len(calls) == 1 else "api"
        labels = {"com.docker.compose.project": "owned-test", "com.docker.compose.service": service}
        if wrong == service + "_label":
            labels["com.docker.compose.project"] = "another-installation"
        return json.dumps(
            [
                {
                    "Id": "owned-" + service,
                    "Config": {"Labels": labels},
                    "State": {"Running": True},
                    "Image": "sha256:" + "f" * 64
                    if wrong == "image"
                    else plan["expected_api_image"],
                }
            ]
        )

    monkeypatch.setattr(observer, "docker_command", inspect)
    with pytest.raises(ValueError, match="mismatch|differs"):
        observer.capture({"state": str(tmp_path), "docker": "docker"}, plan, "C0")
