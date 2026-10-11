"""P2 downstream proof: real REST/subprocess/PG, no Google or live credentials."""

import base64
import copy
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_e7_processes import attempts, create_job, permits, workers
from test_e7_runtime import client, counts, headers
from test_e7_runtime import e7 as _runtime_e7

pytestmark = pytest.mark.integration
e7 = _runtime_e7
ROOT = Path(__file__).resolve().parents[3]
FOOD = json.loads((ROOT / "contracts/examples/e7/provider-result.json").read_text(encoding="utf-8"))
SIGNATURE_BYTES = b"\xfb\xef\xffOPAQUE_SIGNATURE_METADATA_not_food"
SIGNATURE = base64.b64encode(SIGNATURE_BYTES).decode("ascii")
SIGNATURE_URL = base64.urlsafe_b64encode(SIGNATURE_BYTES).decode("ascii").rstrip("=")
FINISH_MESSAGE = "FINISH_ONLY_METADATA_not_a_food_note"
RAW_ID = "RAW_RESPONSE_ID_METADATA_should_not_persist"
OPTIONAL_KEYS = {"thoughtSignature", "tokenCount", "finishMessage", "avgLogprobs", "thought"}


def baseline():
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [{"text": json.dumps(FOOD, ensure_ascii=False)}],
                },
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "modelVersion": "metadata-fixture-v1",
        "responseId": RAW_ID,
        "usageMetadata": {
            "promptTokenCount": 512,
            "candidatesTokenCount": 256,
            "thoughtsTokenCount": 128,
            "totalTokenCount": 896,
        },
    }


def envelope(case):
    value = baseline()
    candidate = value["candidates"][0]
    part = candidate["content"]["parts"][0]
    if case in {"thoughtSignature", "combo", "thought_false"}:
        part["thoughtSignature"] = SIGNATURE_URL if case == "combo" else SIGNATURE
    if case in {"tokenCount", "combo"}:
        candidate["tokenCount"] = 0  # Deliberately differs from trusted usage.
    if case in {"finishMessage", "combo"}:
        candidate["finishMessage"] = FINISH_MESSAGE
    if case in {"avgLogprobs", "combo"}:
        candidate["avgLogprobs"] = -0.125
    if case == "thought_false":
        part["thought"] = False
    return value


def rejected(case):
    value = envelope("combo")
    candidate = value["candidates"][0]
    part = candidate["content"]["parts"][0]
    if case == "signature_type":
        part["thoughtSignature"] = 7
    elif case == "token_type":
        candidate["tokenCount"] = True
    elif case == "finish_type":
        candidate["finishMessage"] = {"unsafe": "not text"}
    elif case == "avg_type":
        candidate["avgLogprobs"] = False
    elif case == "unknown_candidate":
        candidate["unknownMetadata"] = "unrecognized must stay rejected"
    elif case == "unknown_food":
        food = copy.deepcopy(FOOD)
        food["items"][0]["account_id"] = "cannot become food authority"
        part["text"] = json.dumps(food)
    elif case == "thought_true":
        part["thought"] = True
    elif case in {"function", "tool", "image"}:
        part[{"function": "functionCall", "tool": "toolCall", "image": "inlineData"}[case]] = {
            "name": "forbidden-content"
        }
    elif case == "split":
        candidate["content"]["parts"].append(copy.deepcopy(part))
    elif case == "safety":
        candidate["finishReason"] = "SAFETY"
    elif case == "truncated":
        candidate["finishReason"] = "MAX_TOKENS"
    elif case == "usage":
        value["usageMetadata"]["totalTokenCount"] = 0
    else:
        raise AssertionError("unknown local test case")
    return value


@contextmanager
def provider(response):
    """Separate HTTP server records only call kinds, never emits raw responses."""
    records, finished = [], []
    lock = threading.Lock()
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            size = int(self.headers["Content-Length"])
            assert 0 < size <= 8 * 1024 * 1024
            self.rfile.read(size)
            kind = self.path.rsplit(":", 1)[-1]
            done = threading.Event()
            with lock:
                records.append(kind)
                finished.append(done)
            raw = b'{"totalTokens":512}' if kind == "countTokens" else encoded
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                self.wfile.flush()
            finally:
                done.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Fixture:
        url = f"http://127.0.0.1:{server.server_port}"

    try:
        yield Fixture(), records
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert all(done.wait(5) for done in finished)


def keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(item) for item in value))
    return set()


def assert_discarded(state, api_value, worker, captured):
    documents = [api_value, worker.events]
    with state["admin"].connect() as connection:
        for table in (
            "ai_analyses",
            "ai_jobs",
            "ai_attempts",
            "ai_receipts",
            "ai_decisions",
            "ai_photo_consents",
        ):
            documents.extend(connection.scalars(text(f"SELECT to_jsonb(t) FROM app.{table} t")))
    assert not OPTIONAL_KEYS.intersection(keys(documents))
    serialized = json.dumps(documents, ensure_ascii=False, default=str)
    assert all(
        marker not in serialized + captured
        for marker in (SIGNATURE, SIGNATURE_URL, FINISH_MESSAGE, RAW_ID)
    )
    assert all(key not in captured for key in OPTIONAL_KEYS)
    # E6 matching legitimately contains candidates. A raw Gemini candidate
    # would additionally retain content/parts/finishReason or wrapper keys.
    assert not {
        "content",
        "parts",
        "finishReason",
        "usageMetadata",
        "responseId",
        "modelVersion",
        "safetyRatings",
        "raw_response",
    }.intersection(keys(documents))


def confirm_then_standard_sync(state, http, path, analysis):
    item = analysis["proposal"]["items"][0]
    meal = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
    meal["items"] = [
        {
            "item_id": str(uuid4()),
            "name": item["name"],
            "product": None,
            "quantity": item["quantity"],
            "basis_unit": item["basis_unit"],
            "nutrition_per_100": item["nutrition_per_100"],
            "density_g_per_ml": None,
            "density_source": None,
            "nutrition_origin": "ai_estimate",
            "formula_version": "nutrition_v1",
            "ration_component_position": None,
        }
    ]
    draft = {
        "name": item["name"],
        "brand": None,
        "variant": None,
        "basis_unit": item["basis_unit"],
        "nutrition_per_100": item["nutrition_per_100"],
        "package_quantity": item["quantity"],
        "density_g_per_ml": None,
        "density_source": None,
        "source_description": "AI fixture: explicitly confirmed estimate",
    }
    body = {
        "expected_revision": analysis["revision"],
        "meal": {"meal_id": str(uuid4()), "payload": meal},
        "drafts": [{"draft_id": str(uuid4()), "payload": draft}],
    }
    result = http.post(path + "/confirm", headers=headers(state), json=body)
    assert result.status_code == 200
    templates = result.json()
    assert counts(state)["meals"] == counts(state)["product_drafts"] == 0
    checkpoint = http.get(
        "/api/v1/sync/pull", params={"sync_epoch": state["boots"][0]["sync_epoch"]}
    )
    assert checkpoint.status_code == 200
    push = json.loads(
        (ROOT / "contracts/examples/valid/sync-push-request.json").read_text(encoding="utf-8")
    )
    push.update(
        sync_epoch=state["boots"][0]["sync_epoch"], checkpoint=checkpoint.json()["checkpoint"]
    )
    push["operations"] = [
        {
            "operation_id": str(uuid4()),
            "entity_type": kind,
            "entity_id": template[field],
            "action": "upsert",
            "base_revision": None,
            "sync_epoch": push["sync_epoch"],
            "payload": template["payload"],
        }
        for kind, template, field in (
            ("product_draft", templates["drafts"][0], "draft_id"),
            ("meal", templates["meal"], "meal_id"),
        )
    ]
    ack = http.post("/api/v1/sync/push", json=push)
    assert ack.status_code == 200 and [row["status"] for row in ack.json()["results"]] == [
        "accepted",
        "accepted",
    ]
    replay = http.post("/api/v1/sync/push", json=push)
    assert replay.status_code == 200 and [row["status"] for row in replay.json()["results"]] == [
        "already_applied",
        "already_applied",
    ]
    assert counts(state)["meals"] == counts(state)["product_drafts"] == 1
    return templates


@pytest.mark.parametrize(
    "case",
    [
        "baseline",
        "thoughtSignature",
        "tokenCount",
        "finishMessage",
        "avgLogprobs",
        "combo",
        "thought_false",
    ],
)
def test_optional_provider_metadata_has_identical_food_usage_and_no_persistence(
    e7, case, capfd, caplog
):
    job, analysis_id = create_job(e7)
    with provider(envelope(case)) as (fake, records), workers(e7, fake) as spawn:
        worker = spawn(job)
        worker.start()
        assert worker.finish()["handled"] is True
        assert len(worker.children) == 2 and all(child.wait(0) for child, _ in worker.children)
        assert records == ["countTokens", "generateContent"] and permits(e7) == 0
        ledger = attempts(e7, job)
        assert [(row["kind"], row["reserved_tokens"]) for row in ledger] == [
            ("count_tokens", 10240),
            ("generate", 896),
        ]
        assert (
            ledger[1]["input_tokens"],
            ledger[1]["output_tokens"],
            ledger[1]["thoughts_tokens"],
        ) == (512, 256, 128)
        assert all(row["status"] == "ok" and row["io_finished_at"] is not None for row in ledger)
        assert counts(e7)["meals"] == counts(e7)["product_drafts"] == 0
        path = "/api/v1/ai/food-analyses/" + str(analysis_id)
        with client(e7) as http:
            found = http.get(path)
            assert found.status_code == 200 and found.headers["cache-control"] == "no-store"
            value = found.json()
            assert value["state"] == "succeeded"
            proposal = value["proposal"]
            food = {
                "items": [
                    {
                        key: val
                        for key, val in item.items()
                        if key not in {"component_id", "matches"}
                    }
                    for item in proposal["items"]
                ],
                "notes": proposal["notes"],
            }
            assert food == FOOD and proposal["model_version"] == "metadata-fixture-v1"
            assert proposal["totals"] == {
                field: {
                    "known_sum": expected,
                    "missing_count": 0,
                    "complete": True,
                    "display": display,
                }
                for field, expected, display in (
                    ("energy_kcal", "106.8", "107"),
                    ("protein_g", "1.32", "1.3"),
                    ("fat_g", "0.36", "0.4"),
                    ("carbs_g", "27.36", "27.4"),
                )
            }
            if case == "combo":
                value["confirmation"] = confirm_then_standard_sync(e7, http, path, value)
        captured = capfd.readouterr()
        assert_discarded(e7, value, worker, captured.out + captured.err + caplog.text)
        assert records == ["countTokens", "generateContent"]
        assert list(e7["root"].iterdir()) == []


@pytest.mark.parametrize(
    "case,code",
    [
        ("signature_type", "provider_parts_invalid"),
        ("token_type", "provider_result_invalid"),
        ("finish_type", "provider_result_invalid"),
        ("avg_type", "provider_result_invalid"),
        ("unknown_candidate", "provider_result_invalid"),
        ("unknown_food", "provider_result_invalid"),
        ("thought_true", "provider_parts_invalid"),
        ("function", "provider_parts_invalid"),
        ("tool", "provider_parts_invalid"),
        ("image", "provider_parts_invalid"),
        ("split", "provider_parts_invalid"),
        ("safety", "provider_safety_block"),
        ("truncated", "provider_result_truncated"),
        ("usage", "provider_usage_invalid"),
    ],
)
def test_optional_metadata_never_turns_invalid_or_unsafe_content_into_a_proposal(
    e7, case, code, capfd, caplog
):
    job, analysis_id = create_job(e7)
    with provider(rejected(case)) as (fake, records), workers(e7, fake) as spawn:
        worker = spawn(job)
        worker.start()
        worker.finish()
        assert records == ["countTokens", "generateContent"] and len(worker.children) == 2
        with client(e7) as http:
            response = http.get("/api/v1/ai/food-analyses/" + str(analysis_id))
            assert response.status_code == 200
            value = response.json()
        assert (
            value["state"] == "failed" and value["proposal"] is None and value["error_code"] == code
        )
        assert (
            counts(e7)["meals"] == counts(e7)["product_drafts"] == counts(e7)["ai_decisions"] == 0
        )
        assert permits(e7) == 0 and list(e7["root"].iterdir()) == []
        captured = capfd.readouterr()
        assert_discarded(e7, value, worker, captured.out + captured.err + caplog.text)
