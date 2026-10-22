import hashlib
import json
import sys
from copy import deepcopy
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
        "envelope_sha256": "c" * 64,
        "expected_meal": {
            **json.loads(
                (
                    Path(__file__).resolve().parents[3] / "contracts/examples/valid/meal.json"
                ).read_text(encoding="utf-8")
            ),
            "local_date": "2026-10-19",
            "occurred_at": "2026-10-19T06:00:00Z",
        },
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


def snapshots(plan):
    common = {
        "format": 2,
        "plan_sha256": observer.validate_plan(plan),
        "read_only": "on",
        "schema": [plan["expected_schema"]],
        "epoch": plan["sync_epoch"],
        "api_image": plan["expected_api_image"],
        "postgres_container": "synthetic",
        "account": {"id": plan["owner_id"], "generation": 1, "state": "active"},
    }
    c0 = dict(
        common,
        phase="C0",
        observed_at="2026-10-20T10:00:00Z",
        meal=None,
        items=0,
        meal_content=None,
        receipt=None,
        day=None,
        position=None,
        tables={t: {"count": 0, "sha256": "before"} for t in observer.TABLES},
    )
    c1 = dict(
        common,
        phase="C1",
        observed_at="2026-10-20T10:00:01Z",
        meal={
            "id": plan["entity_id"],
            "revision": 1,
            "local_date": plan["local_date"],
            "deleted": False,
        },
        items=1,
        meal_content=deepcopy(plan["expected_meal"]),
        day={"id": str(uuid4()), "revision": 1, "deleted": False},
        position=2,
        receipt={
            "operation_id": plan["operation_id"],
            "entity_id": plan["entity_id"],
            "entity_type": "meal",
            "action": "upsert",
            "status": "accepted",
            "code": None,
            "revision": 1,
            "request_hash": plan["operation_sha256"],
            "source_epoch": plan["sync_epoch"],
            "recovery_epoch": None,
            "recovery_entity_id": None,
        },
        tables={
            t: {"count": 2 if t == "sync_changes" else 1, "sha256": "after"}
            for t in observer.TABLES
        },
    )
    c2 = deepcopy(c1)
    c2.update(phase="C2", observed_at="2026-10-20T10:00:02Z")
    return [c0, c1, c2]


@pytest.mark.parametrize(
    "path,value",
    [
        (("title",), "wrong title"),
        (("occurred_at",), "2026-10-19T06:00:01Z"),
        (("items", 0, "quantity", "amount"), "151"),
        (("items", 0, "nutrition_per_100", "protein_g"), None),
        (("items", 0, "density_g_per_ml"), "0"),
        (("items", 0, "nutrition_origin"), "ai_estimate"),
        (("items", 0, "item_id"), "b1111111-1111-4111-8111-111111111111"),
    ],
)
def test_wrong_initial_content_rejected_even_if_replay_and_receipt_unchanged(plan, path, value):
    observations = snapshots(plan)
    for snapshot in observations[1:]:
        target = snapshot["meal_content"]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        # Both observations contain the same wrong row fingerprints, counts and receipt.
        snapshot["tables"]["meal_items"]["sha256"] = "same-wrong-content"
    assert observations[1]["receipt"] == observations[2]["receipt"]
    with pytest.raises(ValueError, match="C1 Meal content"):
        observer.compare(plan, observations)


def test_storage_normalization_preserves_null_zero_and_text(plan):
    plan["expected_meal"]["items"][0]["nutrition_per_100"].update(protein_g=None, fat_g="0")
    observations = snapshots(plan)
    for snapshot in observations[1:]:
        payload = snapshot["meal_content"]
        payload["occurred_at"] = "2026-10-19T08:00:00.000000+02:00"
        item = payload["items"][0]
        item["quantity"]["amount"] = "150.000000"
        item["nutrition_per_100"]["fat_g"] = "0.000000"
    assert observer.compare(plan, observations)["server_observations"] == "PASS"
    observations[1]["meal_content"]["items"][0]["nutrition_per_100"]["protein_g"] = "0"
    with pytest.raises(ValueError, match="C1 Meal content"):
        observer.compare(plan, observations)


def test_expected_projection_is_bound_to_c0_before_trial(plan):
    observations = snapshots(plan)
    plan["expected_meal"]["title"] = "retroactive expectation"
    with pytest.raises(ValueError, match="context"):
        observer.compare(plan, observations)


@pytest.fixture
def frozen_request(plan):
    return {
        "protocol_version": 1,
        "sync_epoch": plan["sync_epoch"],
        "checkpoint": "private-checkpoint",
        "operations": [
            {
                **{k: plan[k] for k in ("operation_id", "entity_id", "sync_epoch")},
                "entity_type": "meal",
                "action": "upsert",
                "base_revision": None,
                "payload": deepcopy(plan["expected_meal"]),
            }
        ],
    }


def context(plan):
    return {k: plan[k] for k in ("trial_id", "owner_id", "expected_schema", "expected_api_image")}


def test_prepare_binds_validated_operation_and_exact_envelope(plan, frozen_request):
    from calorie_app.modules.sync.service import fingerprint

    raw = json.dumps(frozen_request).encode()
    prepared = observer.prepare_plan(context(plan), raw)
    assert prepared["expected_meal"] == frozen_request["operations"][0]["payload"]
    assert prepared["operation_sha256"] == fingerprint(frozen_request["operations"][0])
    assert prepared["envelope_sha256"] == hashlib.sha256(raw).hexdigest()
    # Byte identity belongs to O1; semantically equal JSON still changes the envelope digest.
    spaced = observer.prepare_plan(context(plan), raw + b"\n")
    assert spaced["operation_sha256"] == prepared["operation_sha256"]
    assert spaced["envelope_sha256"] != prepared["envelope_sha256"]


@pytest.mark.parametrize("fault", ["update", "epoch", "invalid_payload", "duplicate_json"])
def test_prepare_rejects_unqualified_input(plan, frozen_request, fault):
    operation = frozen_request["operations"][0]
    if fault == "update":
        operation["base_revision"] = 1
    elif fault == "epoch":
        operation["sync_epoch"] = str(uuid4())
    elif fault == "invalid_payload":
        operation["payload"]["items"][0]["quantity"]["amount"] = 1.5
    raw = json.dumps(frozen_request).encode()
    if fault == "duplicate_json":
        raw = b'{"protocol_version":1,' + raw[1:]
    with pytest.raises(ValueError):
        observer.prepare_plan(context(plan), raw)


def test_prepare_error_is_private_and_output_is_create_new(
    plan, frozen_request, tmp_path, monkeypatch, capsys
):
    context_path, request_path, output = (tmp_path / n for n in ("context", "request", "output"))
    context_path.write_text(json.dumps(context(plan)), encoding="utf-8")
    frozen_request["operations"][0]["payload"]["title"] = "private meal name"
    request_path.write_text(json.dumps(frozen_request), encoding="utf-8")
    output.write_text("original", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observer",
            "--plan",
            str(context_path),
            "prepare",
            "--request",
            str(request_path),
            "--output",
            str(output),
        ],
    )
    assert observer.main() == 1 and output.read_text() == "original"
    assert "private" not in capsys.readouterr().out
