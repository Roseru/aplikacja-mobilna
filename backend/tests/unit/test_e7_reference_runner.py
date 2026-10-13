"""Synthetic transport fixtures only; no reference accuracy or Google calls."""

import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest
from PIL import Image

from calorie_app.modules.ai.storage import _Windows
from calorie_app.modules.ai.transport import parse_multipart

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "e7_reference_runner", ROOT / "tools/ai_reference/run.py"
)
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
PROFILE = {
    "provider": "gemini",
    "model": "gemini-3.5-flash-lite",
    "prompt_version": "food-photo-prompt-v1",
    "schema_version": "food-photo-schema-v1",
    "preparation_version": "food-photo-preparation-v1",
    "rest_profile_version": "gemini-rest-v1beta-2026-10-11",
    "mock_scenario": None,
}
TOKEN = "unit-secret-token-never-output"
DATE = "2026-10-10T00:00:00Z"


@pytest.fixture
def corpus(tmp_path):
    cases = []
    for group, count in runner.GROUPS.items():
        for _ in range(count):
            number = len(cases)
            image = BytesIO()
            Image.new("RGB", (9, 11), (number, number + 1, number + 2)).save(image, "PNG")
            raw = image.getvalue()
            name = f"synthetic-{number}.png"
            (tmp_path / name).write_bytes(raw)
            readable = group != "unreadable"
            cases.append(
                {
                    "case_id": f"case-{number}",
                    "group": group,
                    "image": name,
                    "image_sha256": hashlib.sha256(raw).hexdigest(),
                    "legal_source": "Synthetic unit image; not a live reference corpus.",
                    "consent": {
                        "accepted": True,
                        "reference_use_accepted": True,
                        "nonsensitive": True,
                        "provider": "gemini",
                        "scope": "this_photo",
                        "notice_version": "food-photo-notice-v1",
                        "approved_at": DATE,
                        "evidence_ref": "Unit fixture; MockTransport only.",
                    },
                    "reference": {
                        "readable": readable,
                        "criterion": "Exact synthetic label for oracle unit.",
                        "source": "Independent unit expectation; no image recognition claim.",
                        "reviewed_at": DATE,
                        "reviewer": "Unit oracle",
                        "main_components": [
                            {"label": "SyntheticProbe", "accepted_aliases": ["SyntheticProbe"]}
                        ]
                        if readable
                        else [],
                    },
                }
            )
    value = {
        "format_version": "e7-reference-manifest-v1",
        "created_at": DATE,
        "o3_evidence_ref": "Synthetic O3-shaped fixture; not a deployment attestation.",
        "o3_confirmation": {
            "provider": "gemini",
            "project_id": "unit-project",
            "environment_id": "unit-fixture",
            "model": PROFILE["model"],
            "confirmed_at": DATE,
            "free_only": True,
            "billing_disabled": True,
            "development_only": True,
            "rpm": 10,
            "tpm": 100000,
            "rpd": 100,
            "model_verified": True,
            "quota_windows": {},
        },
        "expected_profile": PROFILE,
        "cases": cases,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


class MemoryOutput:
    def __init__(self):
        self.values = {}

    def read(self, name):
        return copy.deepcopy(self.values.get(name))

    def write(self, name, value):
        assert TOKEN not in json.dumps(value)
        self.values[name] = copy.deepcopy(value)


class Server:
    def __init__(self):
        self.requests, self.analyses = [], {}
        self.epoch, self.owner = str(uuid4()), str(uuid4())
        self.lost_ack = False
        self.available = True
        self.profile = copy.deepcopy(PROFILE)
        self.error = None
        self.create_status = 202
        self.poll_states = []

    def __call__(self, request):
        assert request.url.host == "backend.reference.test"
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.url.path.startswith("/api/v1/")
        assert "/confirm" not in request.url.path and "/cancel" not in request.url.path
        self.requests.append((request.method, request.url.path, dict(request.headers)))
        path = request.url.path
        if path.endswith("/capabilities"):
            return httpx.Response(
                200,
                json={
                    "provider": "gemini",
                    "profile": self.profile,
                    "notice_version": "food-photo-notice-v1",
                    "available": self.available,
                    "unavailable_reason": None,
                },
            )
        if path == "/api/v1/me/bootstrap":
            assert request.read() == b""
            runner.canonical_uuid(request.headers["idempotency-key"])
            return httpx.Response(
                200,
                json={
                    "account_id": self.owner,
                    "sync_epoch": self.epoch,
                    "account_generation": 1,
                    "server_time": DATE,
                },
            )
        if path == "/api/v1/ai/food-analyses":
            assert request.headers["x-sync-epoch"] == self.epoch
            metadata, image = parse_multipart(request.read(), request.headers["content-type"])
            assert metadata == {
                "consent": {
                    "accepted": True,
                    "notice_version": "food-photo-notice-v1",
                    "provider": "gemini",
                    "scope": "this_photo",
                }
            }
            assert image.startswith(b"\x89PNG")
            key = request.headers["idempotency-key"]
            identifier = self.analyses.setdefault(key, str(uuid5(NAMESPACE_URL, key)))
            if self.create_status == 429:
                return httpx.Response(
                    429, json={"code": "ai_user_quota_exhausted"}, headers={"Retry-After": "86400"}
                )
            if self.lost_ack:
                self.lost_ack = False
                raise httpx.ReadError(TOKEN, request=request)
            return httpx.Response(
                202,
                json={
                    "analysis_id": identifier,
                    "revision": 1,
                    "state": "queued",
                    "queue_deadline": DATE,
                    "profile": PROFILE,
                },
            )
        identifier = path.rsplit("/", 1)[-1]
        assert identifier in self.analyses.values()
        state = (
            self.poll_states.pop(0) if self.poll_states else "failed" if self.error else "succeeded"
        )
        proposal = None
        if state == "succeeded":
            item = json.loads((ROOT / "contracts/examples/e7/provider-result.json").read_text())[
                "items"
            ][0]
            item["name"] = "SyntheticProbe"
            item.update(
                component_id=str(uuid4()),
                matches={
                    "decision": "new_product",
                    "existing_product": None,
                    "candidates": [],
                    "missing_identity_fields": [],
                    "truncated": False,
                },
            )
            total = {"known_sum": "1", "missing_count": 0, "complete": True, "display": "1"}
            proposal = {
                "items": [item],
                "notes": [],
                "totals": {key: total for key in ("energy_kcal", "protein_g", "fat_g", "carbs_g")},
                "model_version": "unit-fixture",
                "formula_version": "nutrition_v1",
            }
        return httpx.Response(
            200,
            json={
                "analysis_id": identifier,
                "revision": 3,
                "state": state,
                "decision_state": "pending",
                "queue_deadline": DATE,
                "photo_expires_at": DATE,
                "profile": PROFILE,
                "proposal": proposal,
                "error_code": self.error if state == "failed" else None,
            },
        )


def execute(corpus, server, output=None, maximum=1, **kwargs):
    manifest = runner.load_manifest(corpus[0])
    output = output or MemoryOutput()
    api = runner.API("https://backend.reference.test", TOKEN, transport=httpx.MockTransport(server))
    try:
        result = runner.execute(manifest, api, output, maximum=maximum, **kwargs)
    finally:
        api.close()
    return result, output


def test_complete_corpus_has_unique_hashes_and_independent_alias_oracle(corpus):
    manifest = runner.load_manifest(corpus[0])
    assert len(manifest.cases) == 30 and len({case.sha256 for case in manifest.cases}) == 30
    case = manifest.cases[0]
    assert runner.reference_oracle(case, ["  ＳｙｎｔｈｅｔｉｃＰｒｏｂｅ  "])[
        "identification_success"
    ]
    assert not runner.reference_oracle(case, ["SyntheticProbe extra ingredient"])[
        "identification_success"
    ]
    assert (
        runner.reference_oracle(manifest.cases[-1], ["SyntheticProbe"])["identification_success"]
        is None
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(extra="unknown"),
        lambda m: m["o3_confirmation"].update(free_only=False),
        lambda m: m["o3_confirmation"].update(confirmed_at="2999-01-01T00:00:00Z"),
        lambda m: m["o3_confirmation"].update(rpm=True),
        lambda m: m["cases"][0]["consent"].update(accepted=False),
        lambda m: m["cases"][0]["consent"].update(nonsensitive=False),
        lambda m: m["cases"][0]["consent"].update(reference_use_accepted=False),
        lambda m: m["cases"][0].update(image_sha256="0" * 64),
        lambda m: m["cases"][1].update(image_sha256=m["cases"][0]["image_sha256"]),
        lambda m: m["cases"][0].update(image="../private.png"),
        lambda m: m["cases"][0].update(image="C:\\private.png"),
        lambda m: m["cases"][0].update(image="\\private.png"),
        lambda m: m["cases"][0].update(image="photo.png:stream"),
        lambda m: m["cases"][0].update(group="mixed"),
        lambda m: m["cases"].pop(),
        lambda m: m["cases"][0]["reference"]["main_components"][0].update(accepted_aliases=[]),
        lambda m: m["cases"][0]["reference"]["main_components"][0].update(
            accepted_aliases=["rice", "RICE"]
        ),
    ],
)
def test_manifest_fail_closed_without_any_network(corpus, mutation):
    path, value = corpus
    mutation(value)
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runner.ReferenceError):
        runner.load_manifest(path)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":1e999}',
        b'{"x":NaN}',
        b'{"x":"\\ud800"}',
        b'{"x":"\xff"}',
        b"{" * 21,
        b"{}{}",
        b"[]",
    ],
)
def test_strict_json(raw):
    with pytest.raises(runner.ReferenceError):
        runner.strict_json(raw)


def test_bounded_image_read_before_api(corpus):
    image = corpus[0].parent / corpus[1]["cases"][0]["image"]
    image.write_bytes(b"x" * (runner.MAX_IMAGE + 1))
    with pytest.raises(runner.ReferenceError) as error:
        runner.load_manifest(corpus[0])
    assert error.value.code == "input_size_invalid"


@pytest.mark.parametrize(
    "raw, expected",
    [
        (b"\xff\xd8", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"RIFFxxxxWEBP", "image/webp"),
    ],
)
def test_media_type_comes_from_bytes_not_filename(raw, expected):
    assert runner.image_media(raw) == expected


def test_arbitrary_nonimage_corpus_file_cannot_be_uploaded(corpus):
    path, value = corpus
    raw = b"not-an-image"
    (path.parent / value["cases"][0]["image"]).write_bytes(raw)
    value["cases"][0]["image_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runner.ReferenceError) as error:
        runner.load_manifest(path)
    assert error.value.code == "image_format_invalid"


def test_real_symlink_or_windows_junction_input_rejected(corpus):
    root = corpus[0].parent
    link = root / "linked"
    target = root / "images"
    target.mkdir()
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=True
        )
    else:
        link.symlink_to(target, target_is_directory=True)
    with pytest.raises(runner.ReferenceError) as error:
        runner.no_links(link / "image.png")
    assert error.value.code == "unsafe_path"


def test_default_one_photo_through_actual_multipart_and_no_auto_confirmation(corpus):
    server = Server()
    result, output = execute(corpus, server)
    assert result["status"] == "WAITING_EXTERNAL"
    assert result["counts"]["completed"] == 1
    assert result["counts"]["identification_successes"] == 1
    assert result["counts"]["readable_cases"] == 26
    assert result["counts"]["manual_fallback_verified"] == 0
    assert len(server.analyses) == 1
    assert TOKEN not in json.dumps(output.values)
    assert server.requests[0][1].endswith("/capabilities")


def test_lost_ack_reuses_original_key_and_photo_hash_on_explicit_resume(corpus):
    server = Server()
    server.lost_ack = True
    first, output = execute(corpus, server)
    assert first["reason"] == "api_transport_unknown"
    saved = copy.deepcopy(output.values["state.json"])
    second, output = execute(corpus, server, output)
    assert second["counts"]["completed"] == 1 and len(server.analyses) == 1
    state = output.values["state.json"]
    assert state["cases"]["case-0"]["operation_key"] == saved["cases"]["case-0"]["operation_key"]
    assert state["epoch"] == saved["epoch"] and state["bootstrap_key"] == saved["bootstrap_key"]


def test_resume_known_id_only_polls_without_second_upload(corpus):
    server = Server()
    first, output = execute(corpus, server)
    output.values["state.json"]["cases"]["case-0"]["state"] = "running"
    second, _ = execute(corpus, server, output)
    assert first["counts"]["completed"] == second["counts"]["completed"] == 1
    assert sum(path == "/api/v1/ai/food-analyses" for _, path, _ in server.requests) == 1


@pytest.mark.parametrize("change", ["profile", "epoch", "owner", "capabilities"])
def test_context_changes_stop_without_new_photo(corpus, change):
    server = Server()
    _, output = execute(corpus, server)
    before = len(server.analyses)
    if change == "profile":
        server.profile["prompt_version"] = "changed-v2"
    elif change == "epoch":
        server.epoch = str(uuid4())
    elif change == "owner":
        server.owner = str(uuid4())
    else:
        server.available = False
    result, _ = execute(corpus, server, output)
    assert result["status"] == "WAITING_EXTERNAL" and len(server.analyses) == before


def test_changed_manifest_rejects_rebinding_old_journal(corpus):
    server = Server()
    _, output = execute(corpus, server)
    corpus[1]["o3_evidence_ref"] = "new attestation"
    corpus[0].write_text(json.dumps(corpus[1]), encoding="utf-8")
    before = len(server.requests)
    with pytest.raises(runner.ReferenceError) as error:
        execute(corpus, server, output)
    assert error.value.code == "resume_binding_changed" and len(server.requests) == before


def test_rate_limit_stops_without_retry_or_second_case(corpus):
    server = Server()
    server.create_status = 429
    result, _ = execute(corpus, server, maximum=10)
    assert result["reason"] == "api_rate_limited"
    assert sum(path == "/api/v1/ai/food-analyses" for _, path, _ in server.requests) == 1


def test_full_transport_fixture_never_claims_reference_pass_or_manual_fallback(corpus):
    server = Server()
    output = MemoryOutput()
    for _ in range(3):
        result, output = execute(corpus, server, output, maximum=10)
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["counts"]["completed"] == 30
    assert result["counts"]["identification_successes"] == 26
    assert result["readable_threshold_met"]
    assert result["invalid_structure_ratio"] is None
    assert result["counts"]["manual_fallback_verified"] == 0
    assert "PASS" not in result["status"]


@pytest.mark.parametrize(
    "code", ["provider_result_unknown", "provider_safety_block", "ai_quota_exhausted"]
)
def test_terminal_failure_never_resends_or_continues_without_explicit_command(corpus, code):
    server = Server()
    server.error = code
    result, output = execute(corpus, server, maximum=10)
    assert result["reason"] == "analysis_failed_manual_review"
    assert len(server.analyses) == 1
    original_key = output.values["state.json"]["cases"]["case-0"]["operation_key"]
    server.error = None
    execute(corpus, server, output, maximum=1)
    assert len(server.analyses) == 2
    assert output.values["state.json"]["cases"]["case-0"]["operation_key"] == original_key


def test_poll_deadline_keeps_original_id_for_next_explicit_resume(corpus):
    server = Server()
    server.poll_states = ["queued"]
    now = [0.0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += 420

    manifest = runner.load_manifest(corpus[0])
    output = MemoryOutput()
    api = runner.API(
        "https://backend.reference.test", TOKEN, clock=clock, transport=httpx.MockTransport(server)
    )
    try:
        result = runner.execute(manifest, api, output, clock=clock, sleep=sleep)
    finally:
        api.close()
    assert result["reason"] == "poll_deadline_reached"
    identifier = output.values["state.json"]["cases"]["case-0"]["analysis_id"]
    execute(corpus, server, output)
    assert output.values["state.json"]["cases"]["case-0"]["analysis_id"] == identifier
    assert len(server.analyses) == 1


def test_bounded_response_and_schema_errors_are_not_echoed():
    for payload in (b"x" * (runner.MAX_JSON + 1), b'{"provider":"' + TOKEN.encode() + b'"}'):
        api = runner.API(
            "https://backend.reference.test",
            TOKEN,
            transport=httpx.MockTransport(
                lambda request, raw=payload: httpx.Response(200, content=raw)
            ),
        )
        try:
            with pytest.raises(runner.ReferenceError) as error:
                runner.response(runner.Capabilities, api.request("GET", "/api/v1/ai/capabilities"))
            assert TOKEN not in str(error.value)
        finally:
            api.close()


def test_api_rejects_google_origin_and_mutation_beyond_create():
    with pytest.raises(runner.ReferenceError):
        runner.API("https://generativelanguage.googleapis.com", TOKEN)
    api = runner.API(
        "https://backend.reference.test",
        TOKEN,
        transport=httpx.MockTransport(lambda request: pytest.fail("unexpected request")),
    )
    try:
        for path in ("/api/v1/ai/food-analyses/" + str(uuid4()) + "/confirm", "/api/v1/sync/push"):
            with pytest.raises(runner.ReferenceError) as error:
                api.request("POST", path)
            assert error.value.code == "api_path_invalid"
    finally:
        api.close()


def test_api_total_deadline_cancels_owned_transport_without_retry():
    cancelled, calls = [], []

    async def stalled(request):
        calls.append(request.url.path)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    api = runner.API(
        "https://backend.reference.test",
        TOKEN,
        clock=lambda: 0,
        transport=httpx.MockTransport(stalled),
    )
    with pytest.raises(runner.ReferenceError) as error:
        api.request("GET", "/api/v1/ai/capabilities", deadline=0.02)
    assert error.value.code == "api_transport_unknown"
    assert cancelled == [True] and calls == ["/api/v1/ai/capabilities"]


def test_corrupt_resume_journal_is_controlled_and_never_resets_operation_keys(corpus):
    server = Server()
    _, output = execute(corpus, server)
    original = output.values["state.json"]["cases"]["case-0"]["operation_key"]
    output.values["state.json"]["cases"]["case-0"]["evaluation"] = "corrupt"
    before = len(server.requests)
    with pytest.raises(runner.ReferenceError):
        execute(corpus, server, output)
    assert len(server.requests) == before
    assert output.values["state.json"]["cases"]["case-0"]["operation_key"] == original


def test_cli_invalid_arguments_do_not_echo_accidental_secret(capsys):
    with pytest.raises(SystemExit) as error:
        runner.main(["--token", TOKEN])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "WAITING_EXTERNAL\n"
    assert TOKEN not in captured.out + captured.err


def test_not_passed_threshold_and_structure_ratio_use_actual_denominators(corpus):
    server = Server()
    output = MemoryOutput()
    for _ in range(3):
        result, output = execute(corpus, server, output, maximum=10)
    manifest = runner.load_manifest(corpus[0])
    state = output.values["state.json"]
    for index in range(3):
        entry = state["cases"][f"case-{index}"]
        entry["state"] = "failed"
        entry["error_code"] = "provider_result_invalid"
        entry["evaluation"] = runner.reference_oracle(manifest.cases[index], [])
    result = runner.report(manifest, state)
    assert result["status"] == "NOT_PASSED"
    assert result["counts"]["identification_successes"] == 23
    assert result["counts"]["readable_cases"] == 26
    assert result["invalid_structure_ratio"] == {"numerator": 3, "denominator": 3}
    state["cases"]["case-2"]["state"] = "succeeded"
    state["cases"]["case-2"]["evaluation"] = runner.reference_oracle(
        manifest.cases[2], ["SyntheticProbe"]
    )
    result = runner.report(manifest, state)
    assert result["status"] == "MANUAL_REVIEW_REQUIRED"
    assert result["counts"]["identification_successes"] == 24


@pytest.mark.parametrize(
    "url",
    [
        "http://real.example",
        "https://user:secret@example.test",
        "https://backend.test/?token=secret",
        "https://backend.test/#secret",
        "https://backend.test/path",
    ],
)
def test_url_has_https_and_no_credentials_query_or_redirect_origin(url):
    with pytest.raises(runner.ReferenceError):
        runner.API(url, TOKEN)


def test_redirect_and_untrusted_error_payload_never_expose_credentials(capsys):
    for response in (
        httpx.Response(302, headers={"Location": "https://other.test"}),
        httpx.Response(401, json={"code": TOKEN, "details": [TOKEN]}),
    ):
        api = runner.API(
            "https://backend.reference.test",
            TOKEN,
            transport=httpx.MockTransport(lambda request, reply=response: reply),
        )
        try:
            with pytest.raises(runner.ReferenceError) as error:
                api.request("GET", "/api/v1/ai/capabilities")
            assert TOKEN not in str(error.value)
        finally:
            api.close()
    assert TOKEN not in capsys.readouterr().out


def test_private_output_outside_git_required_and_atomic_real_acl(tmp_path, monkeypatch):
    with pytest.raises(runner.ReferenceError) as error:
        runner.PrivateOutput(ROOT / "backend/var")
    assert error.value.code == "output_must_be_private_outside_git"
    root = tmp_path / "private-output"
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
    # Only the test's own fixture lives under basetemp. Production has no such override.
    monkeypatch.setattr(runner, "inside_git", lambda path: False)
    output = runner.PrivateOutput(root)
    with output.locked():
        output.write("state.json", {"operation_key": str(uuid4())})
        assert output.read("state.json")["operation_key"]
        with pytest.raises(runner.ReferenceError):
            with runner.PrivateOutput(root).locked():
                pass
    with output.locked():
        output.write("state.json", {"resumed": True})
    assert output.read("state.json") == {"resumed": True}
    assert not any(path.name.endswith(".staging") for path in root.iterdir())


def test_main_invalid_manifest_safe_status_and_private_report(corpus, monkeypatch, capsys):
    output = MemoryOutput()

    @contextmanager
    def lock():
        yield output

    output.locked = lock
    monkeypatch.setattr(runner, "PrivateOutput", lambda root: output)
    corpus[0].write_text('{"cases":[]}', encoding="utf-8")
    monkeypatch.setenv("E7_REFERENCE_TOKEN", TOKEN)
    assert runner.main(["--manifest", str(corpus[0]), "--output", str(corpus[0].parent)]) == 2
    assert output.values["report.json"]["status"] == "WAITING_EXTERNAL"
    assert capsys.readouterr().out == "WAITING_EXTERNAL\n"
    assert TOKEN not in json.dumps(output.values)
