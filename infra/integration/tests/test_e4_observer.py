import hashlib
import io
import json
import socket
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
        labels = {
            "com.docker.compose.project": "owned-test",
            "com.docker.compose.service": service,
        }
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


@pytest.fixture
def driver_prepared(plan, frozen_request):
    """Public synthetic data in the guard2/Room23 prepared.json wire format."""
    payload = frozen_request["operations"][0]["payload"]
    payload["title"] = "Prywatny posiłek Żółć 🍲"
    payload["items"][0]["nutrition_per_100"].update(protein_g=None, fat_g="0")
    # The inner request is already frozen: outer JSON escaping must not rewrite it.
    request = (
        " \t\r\n"
        + json.dumps(frozen_request, ensure_ascii=False, indent=2).replace("\n", "\r\n")
        + "\r\n\t "
    )
    tables = [
        "products",
        "meals",
        "meal_items",
        "goals",
        "outbox",
        "rations",
        "ration_components",
        "profiles",
        "weights",
        "diary_days",
        "catalog_generations",
        "catalog_records",
        "catalog_members",
        "catalog_active",
        "meal_photo_drafts",
        "photo_analysis_requests",
        "photo_materializations",
        "photo_confirmation_history",
        "sync_push_batches",
        "canonical_weights",
        "sync_conflict_decisions",
        "canonical_domains",
        "canonical_goal_timelines",
        "import_plans",
        "guest_assignments",
        "import_sources",
        "import_identities",
        "import_item_identities",
        "import_decisions",
        "reconciliation_batches",
        "reconciliation_evidence",
        "reconciliation_pulls",
        "import_origins",
        "snapshot_archive_receipts",
        "sync_work_state",
        "reconciliation_completions",
        "community_cache",
        "community_attempts",
        "community_backoff",
    ]
    return {
        "trial": plan["trial_id"],
        "owner": str(uuid4()),  # Local storageScope is independent of the PostgreSQL owner.
        "driver_guard_version": 2,
        "isolation_deadline": 1_800_001_200_000,
        "meal": plan["entity_id"],
        "operation": plan["operation_id"],
        "batch": str(uuid4()),
        "request": request,
        "hash": hashlib.sha256(request.encode("utf-8")).hexdigest(),
        "context": json.dumps(
            {
                "account_id": plan["owner_id"],
                "generation": 1,
                "sync_epoch": plan["sync_epoch"],
                "context_revision": 1,
            }
        ),
        "room": 23,
        "protected_tables": tables,
        "protected": json.dumps({name: "0" * 64 for name in [*tables, "__schema__"]}),
    }


def encoded_driver_prepared(prepared):
    # Android JSONObject and independent exports may escape the outer document differently.
    return json.dumps(prepared, ensure_ascii=True).encode("utf-8")


def replace_driver_request(prepared, request):
    prepared["request"] = json.dumps(request, ensure_ascii=False)
    prepared["hash"] = hashlib.sha256(prepared["request"].encode("utf-8")).hexdigest()


def test_driver_prepare_preserves_exact_unicode_envelope_and_legacy_plan(plan, driver_prepared):
    from calorie_app.modules.sync.service import fingerprint

    raw = driver_prepared["request"].encode("utf-8")
    outer = encoded_driver_prepared(driver_prepared)
    assert b"\\ud83c" in outer and b"\r\n" in raw
    assert driver_prepared["owner"] != plan["owner_id"]
    prepared = observer.prepare_driver_plan(context(plan), outer)
    assert prepared == observer.prepare_plan(context(plan), raw)
    operation = json.loads(raw)["operations"][0]
    assert prepared["envelope_sha256"] == hashlib.sha256(raw).hexdigest()
    assert prepared["operation_sha256"] == fingerprint(operation)
    assert prepared["expected_meal"]["title"] == "Prywatny posiłek Żółć 🍲"
    nutrition = prepared["expected_meal"]["items"][0]["nutrition_per_100"]
    assert nutrition["protein_g"] is None and nutrition["fat_g"] == "0"


@pytest.mark.parametrize(
    "field,value",
    [
        ("hash", "0" * 64),
        ("trial", "d1111111-1111-4111-8111-111111111111"),
        ("meal", "d2222222-2222-4222-8222-222222222222"),
        ("operation", "d3333333-3333-4333-8333-333333333333"),
        ("request", None),
        ("context", {}),
        ("driver_guard_version", True),
        ("driver_guard_version", 1),
        ("driver_guard_version", "2"),
        ("room", True),
        ("room", 22),
        ("room", 24),
        ("room", "23"),
    ],
)
def test_driver_prepare_rejects_changed_identity_or_unsupported_shape(
    plan, driver_prepared, field, value
):
    driver_prepared[field] = value
    with pytest.raises(ValueError):
        observer.prepare_driver_plan(context(plan), encoded_driver_prepared(driver_prepared))


@pytest.mark.parametrize(
    "fault",
    [
        "changed_body",
        "account",
        "epoch",
        "operation_epoch",
        "update",
        "numeric_payload",
    ],
)
def test_driver_prepare_binds_context_and_reuses_normative_preflight(plan, driver_prepared, fault):
    request = json.loads(driver_prepared["request"])
    wire_context = json.loads(driver_prepared["context"])
    if fault == "changed_body":
        driver_prepared["request"] += "\n"  # A semantic no-op still breaks the frozen byte hash.
    elif fault == "account":
        wire_context["account_id"] = str(uuid4())
        driver_prepared["context"] = json.dumps(wire_context)
    elif fault == "epoch":
        wire_context["sync_epoch"] = str(uuid4())
        driver_prepared["context"] = json.dumps(wire_context)
    else:
        operation = request["operations"][0]
        if fault == "operation_epoch":
            operation["sync_epoch"] = str(uuid4())
        elif fault == "update":
            operation["base_revision"] = 1
        else:
            operation["payload"]["items"][0]["quantity"]["amount"] = 1.5
        replace_driver_request(driver_prepared, request)
    with pytest.raises(ValueError):
        observer.prepare_driver_plan(context(plan), encoded_driver_prepared(driver_prepared))


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_outer",
        "duplicate_context",
        "duplicate_body",
        "nan_outer",
        "nan_context",
        "nonobject_outer",
        "empty",
        "partial_json",
        "invalid_utf8",
        "surrogate_request",
    ],
)
def test_driver_prepare_rejects_ambiguous_or_unencodable_documents(plan, driver_prepared, fault):
    if fault == "duplicate_context":
        driver_prepared["context"] = (
            '{"account_id":' + json.dumps(plan["owner_id"]) + "," + driver_prepared["context"][1:]
        )
    elif fault == "duplicate_body":
        driver_prepared["request"] = (
            '{"protocol_version":1,' + driver_prepared["request"].lstrip()[1:]
        )
        driver_prepared["hash"] = hashlib.sha256(
            driver_prepared["request"].encode("utf-8")
        ).hexdigest()
    elif fault == "nan_outer":
        driver_prepared["extra"] = float("nan")
    elif fault == "nan_context":
        wire_context = json.loads(driver_prepared["context"])
        wire_context["generation"] = float("nan")
        driver_prepared["context"] = json.dumps(wire_context)
    elif fault == "surrogate_request":
        driver_prepared["request"] = "\ud800"
    raw = encoded_driver_prepared(driver_prepared)
    if fault == "duplicate_outer":
        raw = b'{"request":"ignored private request",' + raw[1:]
    elif fault == "nonobject_outer":
        raw = b"[]"
    elif fault == "empty":
        raw = b""
    elif fault == "partial_json":
        raw = raw[:-1]
    elif fault == "invalid_utf8":
        raw += b"\xff"
    with pytest.raises(ValueError):
        observer.prepare_driver_plan(context(plan), raw)


@pytest.mark.parametrize("size", [65_536, 65_537])
def test_driver_request_limit_counts_utf8_bytes(plan, driver_prepared, size):
    original = driver_prepared["request"]
    driver_prepared["request"] += " " * (size - len(original.encode("utf-8")))
    raw = driver_prepared["request"].encode("utf-8")
    assert len(raw) == size and len(driver_prepared["request"]) < size
    driver_prepared["hash"] = hashlib.sha256(raw).hexdigest()
    outer = encoded_driver_prepared(driver_prepared)
    if size == 65_536:
        assert observer.prepare_driver_plan(context(plan), outer) == observer.prepare_plan(
            context(plan), raw
        )
    else:
        with pytest.raises(ValueError):
            observer.prepare_driver_plan(context(plan), outer)


@pytest.mark.parametrize("size", [5_000_000, 5_000_001])
def test_driver_receipt_limit_accepts_boundary_but_rejects_extra_byte(plan, driver_prepared, size):
    raw = encoded_driver_prepared(driver_prepared)
    raw += b" " * (size - len(raw))
    assert len(raw) == size
    if size == 5_000_000:
        assert (
            observer.prepare_driver_plan(context(plan), raw)["envelope_sha256"]
            == driver_prepared["hash"]
        )
    else:
        with pytest.raises(ValueError):
            observer.prepare_driver_plan(context(plan), raw)


@pytest.fixture
def no_prepare_external_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline plan preparation must not contact services or start a subprocess")

    monkeypatch.setattr(observer, "capture", forbidden)
    monkeypatch.setattr(observer, "docker_command", forbidden)
    monkeypatch.setattr(observer.subprocess, "run", forbidden)
    monkeypatch.setattr(observer.subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def driver_cli_inputs(tmp_path, plan, prepared):
    context_path, source = tmp_path / "context.json", tmp_path / "prepared.json"
    context_path.write_text(json.dumps(context(plan)), encoding="utf-8")
    source.write_bytes(encoded_driver_prepared(prepared))
    return context_path, source


def prepare_cli_arguments(monkeypatch, context_path, output, *inputs):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "observer",
            "--plan",
            str(context_path),
            "prepare",
            *map(str, inputs),
            "--output",
            str(output),
        ],
    )


@pytest.mark.parametrize("input_flag", ["--request", "--driver-prepared"])
def test_prepare_cli_alternatives_are_private_offline_and_preserve_inputs(
    plan,
    driver_prepared,
    tmp_path,
    monkeypatch,
    capsys,
    no_prepare_external_io,
    input_flag,
):
    context_path, source = driver_cli_inputs(tmp_path, plan, driver_prepared)
    raw_request = driver_prepared["request"].encode("utf-8")
    if input_flag == "--request":
        source.write_bytes(raw_request)
    output = tmp_path / "pg-plan.json"
    before = {path: path.read_bytes() for path in (context_path, source)}
    expected = observer.prepare_plan(context(plan), raw_request)
    prepare_cli_arguments(monkeypatch, context_path, output, input_flag, source)
    assert observer.main() == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert all(path.read_bytes() == value for path, value in before.items())
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "private_plan": "SAVED",
        "overall_apk_api_trial": "NOT_ASSESSED",
    }
    assert captured.err == ""
    for private in (
        "Prywatny posiłek",
        "private-checkpoint",
        plan["owner_id"],
        driver_prepared["owner"],
    ):
        assert private not in captured.out + captured.err


@pytest.mark.parametrize("selection", ["neither", "both"])
def test_prepare_cli_requires_exactly_one_input(
    plan, driver_prepared, tmp_path, monkeypatch, capsys, selection
):
    context_path, source = driver_cli_inputs(tmp_path, plan, driver_prepared)
    output = tmp_path / "pg-plan.json"
    inputs = () if selection == "neither" else ("--request", source, "--driver-prepared", source)
    prepare_cli_arguments(monkeypatch, context_path, output, *inputs)
    with pytest.raises(SystemExit) as error:
        observer.main()
    assert error.value.code == 2 and not output.exists()
    assert "private-checkpoint" not in "".join(capsys.readouterr())


@pytest.mark.parametrize("target", ["existing", "context", "prepared", "hardlink"])
def test_driver_prepare_cli_never_overwrites_inputs_or_prior_output(
    plan, driver_prepared, tmp_path, monkeypatch, capsys, no_prepare_external_io, target
):
    context_path, source = driver_cli_inputs(tmp_path, plan, driver_prepared)
    output = tmp_path / "pg-plan.json"
    if target == "context":
        output = context_path
    elif target == "prepared":
        output = source
    elif target == "hardlink":
        try:
            output.hardlink_to(source)
        except OSError as error:
            pytest.skip(f"Hardlink unavailable: {error}")
    else:
        output.write_bytes(b"existing private evidence")
    before = {path: path.read_bytes() for path in (context_path, source, output)}
    prepare_cli_arguments(monkeypatch, context_path, output, "--driver-prepared", source)
    assert observer.main() == 1
    assert all(path.read_bytes() == value for path, value in before.items())
    assert "private-checkpoint" not in "".join(capsys.readouterr())


def test_invalid_driver_cli_creates_no_plan_and_does_not_leak_private_content(
    plan, driver_prepared, tmp_path, monkeypatch, capsys, no_prepare_external_io
):
    driver_prepared["hash"] = "0" * 64
    context_path, source = driver_cli_inputs(tmp_path, plan, driver_prepared)
    before = {path: path.read_bytes() for path in (context_path, source)}
    output = tmp_path / "pg-plan.json"
    prepare_cli_arguments(monkeypatch, context_path, output, "--driver-prepared", source)
    assert observer.main() == 1 and not output.exists()
    assert all(path.read_bytes() == value for path, value in before.items())
    captured = capsys.readouterr()
    assert json.loads(captured.out)["server_observations"] == "UNQUALIFIED"
    assert captured.err == ""
    for private in (
        "Prywatny posiłek",
        "private-checkpoint",
        plan["owner_id"],
        driver_prepared["owner"],
    ):
        assert private not in captured.out + captured.err


def test_driver_cli_bounds_read_before_parsing_oversized_receipt(
    plan, driver_prepared, tmp_path, monkeypatch, capsys
):
    from calorie_app.modules.catalog import validation

    context_path, source = driver_cli_inputs(tmp_path, plan, driver_prepared)
    output = tmp_path / "pg-plan.json"
    raw = encoded_driver_prepared(driver_prepared)
    raw += b" " * (5_000_002 - len(raw))
    reads = []
    original_open = Path.open

    class BoundedReceipt(io.BytesIO):
        def read(self, size=-1):
            assert 0 < size <= 5_000_001, "CLI must not read the whole private receipt"
            reads.append(size)
            return super().read(size)

    def open_receipt(path, *args, **kwargs):
        if path == source:
            assert args[0] == "rb"
            return BoundedReceipt(raw)
        return original_open(path, *args, **kwargs)

    def forbidden_parser(_raw):
        pytest.fail("An oversized receipt must be rejected before JSON parsing")

    monkeypatch.setattr(Path, "open", open_receipt)
    monkeypatch.setattr(validation, "parse_json", forbidden_parser)
    prepare_cli_arguments(monkeypatch, context_path, output, "--driver-prepared", source)
    assert observer.main() == 1 and not output.exists()
    assert reads == [5_000_001]
    assert "private-checkpoint" not in "".join(capsys.readouterr())
