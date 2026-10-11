"""Consented reference runs through the application API; never calls Google directly."""

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import stat
import sys
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from pydantic import ValidationError

from calorie_app.modules.ai.schemas import (
    AnalysisProfile,
    AnalysisResponse,
    Capabilities,
    CreateResponse,
)
from calorie_app.modules.ai.storage import PhotoStorage, _not_link, _private_file, _Windows
from calorie_app.modules.profiles.schemas import Bootstrap

MAX_IMAGE = 5 * 1024 * 1024
MAX_JSON = 1024 * 1024
GROUPS = {"products": 8, "mixed": 8, "rations": 10, "unreadable": 4}
SAFE_CODES = {
    "unauthorized",
    "forbidden",
    "not_found",
    "account_deleting",
    "account_bootstrap_required",
    "sync_epoch_changed",
    "account_generation_changed",
    "analysis_context_changed",
    "idempotency_key_reused",
    "ai_operation_busy",
    "ai_user_quota_exhausted",
    "ai_active_job",
    "ai_receipt_quota_exhausted",
    "ai_quota_exhausted",
    "ai_restore_pending",
    "ai_unavailable",
    "ai_storage_unavailable",
    "photo_consent_required",
    "photo_provider_changed",
    "invalid_image",
    "request_too_large",
    "invalid_request",
    "service_unavailable",
    "provider_result_unknown",
    "provider_no_food",
    "provider_result_invalid",
    "provider_json_invalid",
    "provider_json_depth",
    "provider_json_duplicate",
    "provider_response_size",
    "provider_safety_blocked",
    "provider_safety_block",
    "provider_max_tokens",
    "provider_no_candidates",
    "provider_result_truncated",
    "provider_parts_invalid",
    "provider_input_too_large",
    "provider_input_budget_exceeded",
    "provider_minute_quota",
    "provider_usage_invalid",
    "provider_before_send",
    "provider_unavailable",
    "image_expired",
    "image_unavailable",
    "queue_expired",
    "analysis_queue_expired",
    "analysis_cancelled",
    "ai_profile_unavailable",
    "provider_budget_exceeded",
}
STRUCTURE_CODES = {
    "provider_result_invalid",
    "provider_json_invalid",
    "provider_json_depth",
    "provider_json_duplicate",
    "provider_response_size",
    "provider_parts_invalid",
    "provider_result_truncated",
}


class ReferenceError(ValueError):
    """A controlled code, without paths, credentials, response bodies or image bytes."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code="manifest_invalid"):
    if not condition:
        raise ReferenceError(code)


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def strict_json(raw, maximum=MAX_JSON):
    require(isinstance(raw, bytes) and 0 < len(raw) <= maximum, "json_size_invalid")
    try:
        source = raw.decode("utf-8", errors="strict")
        quoted = escaped = False
        depth = 0
        for char in source:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                require(depth <= 20, "json_invalid")
            elif char in "]}":
                depth -= 1

        def pairs(items):
            value = {}
            for key, item in items:
                require(key not in value, "json_invalid")
                value[key] = item
            return value

        def constant(_):
            raise ReferenceError("json_invalid")

        value = json.loads(source, object_pairs_hook=pairs, parse_constant=constant)

        def text(item):
            if isinstance(item, str):
                require(
                    "\x00" not in item and not any(0xD800 <= ord(c) <= 0xDFFF for c in item),
                    "json_invalid",
                )
            elif isinstance(item, float):
                require(math.isfinite(item), "json_invalid")
            elif isinstance(item, dict):
                for key, child in item.items():
                    text(key)
                    text(child)
            elif isinstance(item, list):
                for child in item:
                    text(child)

        text(value)
        require(isinstance(value, dict), "json_invalid")
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise ReferenceError("json_invalid") from None


def object_fields(value, fields):
    require(isinstance(value, dict) and set(value) == set(fields))


def text_field(value, maximum=2000):
    require(isinstance(value, str) and 0 < len(value) <= maximum and bool(value.strip()))
    return value


def timestamp(value):
    try:
        require(isinstance(value, str) and value.endswith("Z"))
        date = datetime.fromisoformat(value)
        require(date.tzinfo is not None and date <= datetime.now(UTC))
        return date
    except ValueError:
        raise ReferenceError("manifest_invalid") from None


def no_links(path):
    """Check each component, including Windows junctions, without resolving links."""
    require(path.is_absolute() and ".." not in path.parts, "unsafe_path")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        info = current.lstat()
        require(
            not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "unsafe_path",
        )


def read_file(path, maximum):
    """Pin directories and refuse links at open time as well as during preflight."""
    require(path.is_absolute() and ".." not in path.parts, "unsafe_path")
    handles, descriptor, windows = [], None, None
    try:
        if os.name == "nt":
            import msvcrt

            windows = _Windows()
            current = Path(path.anchor)
            for component in path.parts[1:-1]:
                current /= component
                handles.append(windows.open(current, directory=True))
                info = current.lstat()
                _not_link(info)
                require(stat.S_ISDIR(info.st_mode), "unsafe_path")
            handle = windows.open(path)
            try:
                descriptor = msvcrt.open_osfhandle(handle, os.O_BINARY)
            except BaseException:
                windows.kernel.CloseHandle(handle)
                raise
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            directory = os.open(path.anchor, flags)
            handles.append(directory)
            for component in path.parts[1:-1]:
                directory = os.open(component, flags, dir_fd=directory)
                handles.append(directory)
            descriptor = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
        before = os.fstat(descriptor)
        _not_link(before)
        require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum, "input_size_invalid"
        )
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(maximum + 1)
        after = os.fstat(descriptor)
        require(
            0 < len(raw) <= maximum
            and before.st_size == after.st_size == len(raw)
            and before.st_mtime_ns == after.st_mtime_ns,
            "input_changed",
        )
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        for handle in reversed(handles):
            if windows:
                windows.kernel.CloseHandle(handle)
            else:
                os.close(handle)


def image_media(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    raise ReferenceError("image_format_invalid")


@dataclass(frozen=True)
class Case:
    case_id: str
    group: str
    sha256: str
    notice_version: str
    reference: dict = field(repr=False)
    image_path: Path = field(repr=False)


@dataclass(frozen=True)
class Manifest:
    sha256: str
    profile: dict
    cases: tuple[Case, ...]


def load_manifest(path):
    path = Path(path).absolute()
    raw = read_file(path, 256 * 1024)
    value = strict_json(raw, 256 * 1024)
    object_fields(
        value,
        {
            "format_version",
            "created_at",
            "o3_confirmation",
            "o3_evidence_ref",
            "expected_profile",
            "cases",
        },
    )
    require(value["format_version"] == "e7-reference-manifest-v1")
    timestamp(value["created_at"])
    text_field(value["o3_evidence_ref"])
    confirmation = value["o3_confirmation"]
    object_fields(
        confirmation,
        {
            "provider",
            "project_id",
            "environment_id",
            "model",
            "confirmed_at",
            "free_only",
            "billing_disabled",
            "development_only",
            "rpm",
            "tpm",
            "rpd",
            "model_verified",
            "quota_windows",
        },
    )
    timestamp(confirmation["confirmed_at"])
    require(confirmation["provider"] == "gemini")
    for key in ("free_only", "billing_disabled", "development_only", "model_verified"):
        require(confirmation[key] is True, "o3_confirmation_required")
    for key in ("project_id", "environment_id", "model"):
        require(
            isinstance(confirmation[key], str)
            and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", confirmation[key]) is not None
        )
    for key, low, high in (("rpm", 1, 100000), ("tpm", 10240, 1000000000), ("rpd", 1, 1000000)):
        require(
            type(confirmation[key]) is int and low <= confirmation[key] <= high,
            "o3_confirmation_required",
        )
    require(
        isinstance(confirmation["quota_windows"], dict) and len(confirmation["quota_windows"]) <= 20
    )
    try:
        profile = AnalysisProfile.model_validate(value["expected_profile"]).model_dump(mode="json")
    except ValidationError:
        raise ReferenceError("profile_invalid") from None
    require(
        profile["provider"] == "gemini"
        and profile["mock_scenario"] is None
        and profile["model"] == confirmation["model"],
        "profile_invalid",
    )
    for key in ("prompt_version", "schema_version", "preparation_version", "rest_profile_version"):
        require(
            isinstance(profile[key], str) and re.fullmatch(r"[A-Za-z0-9._-]{1,100}", profile[key]),
            "profile_invalid",
        )
    require(isinstance(value["cases"], list) and 30 <= len(value["cases"]) <= 100)
    cases, ids, hashes = [], set(), set()
    for item in value["cases"]:
        object_fields(
            item,
            {"case_id", "group", "image", "image_sha256", "legal_source", "consent", "reference"},
        )
        case_id, group = item["case_id"], item["group"]
        require(
            isinstance(case_id, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", case_id)
            and case_id not in ids
            and isinstance(group, str)
            and group in GROUPS
        )
        digest = item["image_sha256"]
        require(
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
            and digest not in hashes,
            "corpus_duplicate_or_invalid_hash",
        )
        text_field(item["legal_source"])
        consent = item["consent"]
        object_fields(
            consent,
            {
                "accepted",
                "reference_use_accepted",
                "nonsensitive",
                "provider",
                "scope",
                "notice_version",
                "approved_at",
                "evidence_ref",
            },
        )
        require(
            all(
                consent[key] is True
                for key in ("accepted", "reference_use_accepted", "nonsensitive")
            )
            and consent["provider"] == "gemini"
            and consent["scope"] == "this_photo",
            "photo_consent_required",
        )
        text_field(consent["notice_version"], 100)
        text_field(consent["evidence_ref"])
        timestamp(consent["approved_at"])
        reference = item["reference"]
        object_fields(
            reference,
            {"readable", "criterion", "source", "reviewed_at", "reviewer", "main_components"},
        )
        require(reference["readable"] is (group != "unreadable"))
        for key in ("criterion", "source", "reviewer"):
            text_field(reference[key])
        timestamp(reference["reviewed_at"])
        components = reference["main_components"]
        require(
            isinstance(components, list)
            and len(components) <= 30
            and (bool(components) if reference["readable"] else not components)
        )
        aliases, labels = set(), set()
        for component in components:
            object_fields(component, {"label", "accepted_aliases"})
            label = normalize(text_field(component["label"], 200))
            require(label not in labels, "reference_label_ambiguous")
            labels.add(label)
            require(
                isinstance(component["accepted_aliases"], list)
                and 1 <= len(component["accepted_aliases"]) <= 20
            )
            for alias in component["accepted_aliases"]:
                name = normalize(text_field(alias, 200))
                require(name not in aliases, "reference_alias_ambiguous")
                aliases.add(name)
        relative = item["image"]
        require(
            isinstance(relative, str)
            and 0 < len(relative) <= 500
            and not relative.startswith(("/", "\\"))
            and "\\" not in relative
            and ":" not in relative
            and not Path(relative).is_absolute()
            and not re.match(r"^[A-Za-z]:", relative)
            and ".." not in relative.replace("\\", "/").split("/"),
            "unsafe_path",
        )
        image_path = path.parent / relative
        image = read_file(image_path, MAX_IMAGE)
        image_media(image)
        require(hashlib.sha256(image).hexdigest() == digest, "image_hash_mismatch")
        ids.add(case_id)
        hashes.add(digest)
        cases.append(Case(case_id, group, digest, consent["notice_version"], reference, image_path))
    counts = Counter(case.group for case in cases)
    require(all(counts[group] >= minimum for group, minimum in GROUPS.items()), "corpus_incomplete")
    return Manifest(hashlib.sha256(raw).hexdigest(), profile, tuple(cases))


def reference_oracle(case, proposed_names):
    """Exact human-approved aliases only; never derive references from model text."""
    names = {normalize(name) for name in proposed_names}
    matched, missing = [], []
    for component in case.reference["main_components"]:
        found = any(normalize(alias) in names for alias in component["accepted_aliases"])
        (matched if found else missing).append(component["label"])
    return {
        "readable": case.reference["readable"],
        "matched_components": matched,
        "missing_components": missing,
        "identification_success": not missing if case.reference["readable"] else None,
        "manual_review": "required",
    }


def inside_git(path):
    return any((ancestor / ".git").exists() for ancestor in (path, *path.parents))


class PrivateOutput:
    """Private JSON journal/report with OS locking and atomic, fsynced writes."""

    def __init__(self, root):
        self.root = Path(root)
        require(
            self.root.is_absolute() and not inside_git(self.root),
            "output_must_be_private_outside_git",
        )
        self.storage = PhotoStorage(self.root)
        require(self.storage.availability(), "private_output_permissions_required")

    @contextmanager
    def locked(self):
        try:
            with self.storage._access() as (directory, windows):
                fresh = self.storage._stat("run.lock", directory) is None
                descriptor = self.storage._open_file("run.lock", directory, windows, create=fresh)
                try:
                    if fresh:
                        os.write(descriptor, b"1")
                        os.fsync(descriptor)
                    if windows is None:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    yield self
                finally:
                    os.close(descriptor)
        except OSError:
            raise ReferenceError("reference_run_busy_or_storage_unavailable") from None

    def read(self, name):
        require(name in {"state.json", "report.json"}, "output_name_invalid")
        with self.storage._access() as (directory, windows):
            try:
                descriptor = self.storage._open_file(name, directory, windows)
            except FileNotFoundError:
                return None
            with os.fdopen(descriptor, "rb") as source:
                raw = source.read(MAX_JSON + 1)
        return strict_json(raw)

    def write(self, name, value):
        require(name in {"state.json", "report.json"}, "output_name_invalid")
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        require(len(raw) <= MAX_JSON, "output_size_invalid")
        stage = ".reference-" + uuid4().hex + ".staging"
        with self.storage._access() as (directory, windows):
            existing = self.storage._stat(name, directory)
            if existing is not None:
                _private_file(existing)
                if windows:
                    windows.private_acl(self.root / name, False)
            descriptor = self.storage._open_file(stage, directory, windows, create=True)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                if windows:
                    require(
                        windows.kernel.MoveFileExW(
                            str(self.root / stage), str(self.root / name), 9
                        ),
                        "output_activation_failed",
                    )
                else:
                    os.replace(stage, name, src_dir_fd=directory, dst_dir_fd=directory)
                    os.fsync(directory)
            finally:
                if self.storage._stat(stage, directory) is not None:
                    self.storage._unlink(stage, directory)


def api_url(value, transport=None):
    require(isinstance(value, str), "api_url_invalid")
    try:
        parsed = urlsplit(value)
        require(
            parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path in {"", "/"}
            and bool(parsed.hostname),
            "api_url_invalid",
        )
        require(
            parsed.scheme == "https"
            or (
                isinstance(transport, httpx.MockTransport)
                and parsed.scheme == "http"
                and parsed.hostname == "127.0.0.1"
            ),
            "https_required",
        )
        require(
            not parsed.hostname.rstrip(".").endswith(".googleapis.com")
            and parsed.hostname.rstrip(".")
            not in {"googleapis.com", "ai.google.dev", "aistudio.google.com"},
            "application_api_required",
        )
        require(parsed.port is None or 1 <= parsed.port <= 65535, "api_url_invalid")
        return value.rstrip("/")
    except ValueError:
        raise ReferenceError("api_url_invalid") from None


def safe_code(value, fallback="api_request_failed"):
    return value if isinstance(value, str) and value in SAFE_CODES else fallback


class API:
    def __init__(self, url, token, *, ca=None, transport=None, clock=time.monotonic):
        self.url = api_url(url, transport)
        require(
            isinstance(token, str)
            and 0 < len(token) <= 16384
            and not any(char.isspace() for char in token),
            "api_token_required",
        )
        verify = True
        if ca is not None:
            path = Path(ca).absolute()
            no_links(path)
            require(path.is_file(), "ca_bundle_invalid")
            verify = ssl.create_default_context(cafile=str(path))
        self._token, self.clock = token, clock
        self._verify, self._transport = verify, transport

    def close(self):
        # Each request already awaits closure of its owned AsyncClient.
        pass

    def request(self, method, path, *, deadline=None, **kwargs):
        allowed = (method, path) in {
            ("GET", "/api/v1/ai/capabilities"),
            ("POST", "/api/v1/me/bootstrap"),
            ("POST", "/api/v1/ai/food-analyses"),
        } or (
            method == "GET"
            and re.fullmatch(
                r"/api/v1/ai/food-analyses/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", path
            )
        )
        require(allowed, "api_path_invalid")
        remaining = 15 if deadline is None else min(15, deadline - self.clock())
        require(remaining > 0, "poll_deadline_reached")

        async def bounded():
            # The total timeout cancels an owned response/transport; socket
            # read timeout alone would reset on each chunk and permit trickle.
            async with (
                asyncio.timeout(remaining),
                httpx.AsyncClient(
                    verify=self._verify,
                    trust_env=False,
                    follow_redirects=False,
                    transport=self._transport,
                    headers={"Authorization": "Bearer " + self._token},
                ) as client,
                client.stream(method, self.url + path, timeout=remaining, **kwargs) as response,
            ):
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    require(deadline is None or self.clock() <= deadline, "poll_deadline_reached")
                    require(len(chunk) <= MAX_JSON - len(body), "api_response_too_large")
                    body.extend(chunk)
                require(not 300 <= response.status_code < 400, "api_redirect_rejected")
                value = strict_json(bytes(body))
                if response.status_code >= 400:
                    raise ReferenceError(
                        "api_rate_limited"
                        if response.status_code == 429
                        else safe_code(value.get("code"))
                    )
                expected = 202 if path == "/api/v1/ai/food-analyses" else 200
                require(response.status_code == expected, "api_status_invalid")
                return value

        try:
            return asyncio.run(bounded())
        except (httpx.HTTPError, TimeoutError):
            # A create may have committed. Its persisted key remains pending
            # and is reused only on the next explicit CLI invocation.
            raise ReferenceError("api_transport_unknown") from None


def response(model, value):
    try:
        return model.model_validate(value).model_dump(mode="json")
    except (ValidationError, ValueError):
        raise ReferenceError("api_response_schema_invalid") from None


def canonical_uuid(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, "journal_invalid")
    except ValueError:
        raise ReferenceError("journal_invalid") from None


def journal(manifest, url, saved):
    if saved is None:
        return {
            "format_version": "e7-reference-state-v1",
            "manifest_sha256": manifest.sha256,
            "api_url": url,
            "run_id": str(uuid4()),
            "bootstrap_key": str(uuid4()),
            "profile": manifest.profile,
            "account_id": None,
            "generation": None,
            "epoch": None,
            "cases": {},
        }
    object_fields(
        saved,
        {
            "format_version",
            "manifest_sha256",
            "api_url",
            "run_id",
            "bootstrap_key",
            "profile",
            "account_id",
            "generation",
            "epoch",
            "cases",
        },
    )
    require(
        saved.get("format_version") == "e7-reference-state-v1"
        and saved.get("manifest_sha256") == manifest.sha256
        and saved.get("api_url") == url
        and saved.get("profile") == manifest.profile,
        "resume_binding_changed",
    )
    canonical_uuid(saved.get("run_id"))
    canonical_uuid(saved.get("bootstrap_key"))
    if saved["account_id"] is not None:
        canonical_uuid(saved["account_id"])
        canonical_uuid(saved["epoch"])
        require(
            type(saved["generation"]) is int and 1 <= saved["generation"] <= 2147483647,
            "journal_invalid",
        )
    else:
        require(saved["epoch"] is None and saved["generation"] is None, "journal_invalid")
    require(isinstance(saved.get("cases"), dict), "journal_invalid")
    cases = {case.case_id: case for case in manifest.cases}
    for key, item in saved["cases"].items():
        require(
            key in cases and isinstance(item, dict) and item.get("sha256") == cases[key].sha256,
            "resume_binding_changed",
        )
        canonical_uuid(item.get("operation_key"))
        mandatory = {"sha256", "operation_key", "analysis_id", "state", "profile", "error_code"}
        require(
            mandatory <= item.keys()
            and not item.keys() - mandatory - {"evaluation", "model_version"},
            "journal_invalid",
        )
        require(
            item.get("state") in {"create_pending", "queued", "running", "succeeded", "failed"},
            "journal_invalid",
        )
        require(
            item["error_code"] is None
            or (
                isinstance(item["error_code"], str)
                and item["error_code"] in SAFE_CODES | {"analysis_failed"}
            ),
            "journal_invalid",
        )
        if item.get("analysis_id") is not None:
            canonical_uuid(item["analysis_id"])
        if item.get("profile") is not None:
            require(item["profile"] == manifest.profile, "resume_profile_changed")
        if item["state"] != "create_pending":
            require(
                item["analysis_id"] is not None and item["profile"] == manifest.profile,
                "journal_invalid",
            )
        evaluation = item.get("evaluation")
        if evaluation is not None:
            object_fields(
                evaluation,
                {
                    "readable",
                    "matched_components",
                    "missing_components",
                    "identification_success",
                    "manual_review",
                },
            )
            require(
                evaluation["readable"] is cases[key].reference["readable"]
                and evaluation["manual_review"] == "required",
                "journal_invalid",
            )
            labels = {component["label"] for component in cases[key].reference["main_components"]}
            matched, missing = evaluation["matched_components"], evaluation["missing_components"]
            require(
                isinstance(matched, list)
                and isinstance(missing, list)
                and all(isinstance(value, str) for value in matched + missing),
                "journal_invalid",
            )
            require(
                len(set(matched + missing)) == len(matched + missing)
                and set(matched + missing) == labels,
                "journal_invalid",
            )
            expected = not missing if cases[key].reference["readable"] else None
            require(evaluation["identification_success"] is expected, "journal_invalid")
        if item["state"] in {"succeeded", "failed"}:
            require(
                item["analysis_id"] is not None
                and item["profile"] == manifest.profile
                and evaluation is not None,
                "journal_invalid",
            )
    return saved


def report(manifest, state, reason=None):
    results = []
    successes = completed = invalid = blocked = 0
    readable = sum(case.reference["readable"] for case in manifest.cases)
    for case in manifest.cases:
        item = state["cases"].get(case.case_id, {})
        evaluation = item.get("evaluation")
        terminal = item.get("state") in {"succeeded", "failed"}
        completed += terminal
        successes += bool(terminal and evaluation and evaluation["identification_success"] is True)
        structural = item.get("error_code") in STRUCTURE_CODES
        invalid += structural
        blocked += bool(structural and item.get("state") == "failed")
        results.append(
            {
                "case_id": case.case_id,
                "image_sha256": case.sha256,
                "analysis_id": item.get("analysis_id"),
                "state": item.get("state", "not_run"),
                "error_code": item.get("error_code"),
                "model_version": item.get("model_version"),
                "evaluation": evaluation,
                "manual_review": "required",
            }
        )
    complete = completed == len(manifest.cases)
    accuracy = successes * 10 >= readable * 9
    external_reason = reason and not (complete and reason == "analysis_failed_manual_review")
    status = (
        "WAITING_EXTERNAL"
        if external_reason or not complete
        else "MANUAL_REVIEW_REQUIRED"
        if accuracy
        else "NOT_PASSED"
    )
    return {
        "format_version": "e7-reference-report-v1",
        "status": status,
        "reason": reason or (None if complete else "corpus_incomplete"),
        "run_id": state["run_id"],
        "manifest_sha256": manifest.sha256,
        "profile": manifest.profile,
        "counts": {
            "planned": len(manifest.cases),
            "completed": completed,
            "identification_successes": successes,
            "readable_cases": readable,
            "unreadable_cases": len(manifest.cases) - readable,
            "invalid_structures_observed": invalid,
            "invalid_structures_blocked": blocked,
            "manual_fallback_verified": 0,
            "manual_fallback_required": len(manifest.cases),
        },
        "readable_threshold_met": complete and accuracy,
        "invalid_structure_ratio": None
        if invalid == 0
        else {"numerator": blocked, "denominator": invalid},
        "manual_review": "required_external_evidence",
        "cases": results,
    }


def execute(manifest, api, output, *, maximum=1, clock=time.monotonic, sleep=time.sleep):
    require(type(maximum) is int and 1 <= maximum <= 10, "max_cases_invalid")
    state = journal(manifest, api.url, output.read("state.json"))

    def save(name, value):
        require(api._token not in json.dumps(value, ensure_ascii=False), "secret_output_rejected")
        output.write(name, value)

    save("state.json", state)
    reason = None
    try:
        caps = response(Capabilities, api.request("GET", "/api/v1/ai/capabilities"))
        require(
            caps["provider"] == "gemini" and caps["available"] is True, "live_capabilities_required"
        )
        require(caps.get("profile") == manifest.profile, "capability_profile_changed")
        require(
            all(case.notice_version == caps["notice_version"] for case in manifest.cases),
            "notice_changed",
        )
        boot = response(
            Bootstrap,
            api.request(
                "POST", "/api/v1/me/bootstrap", headers={"Idempotency-Key": state["bootstrap_key"]}
            ),
        )
        context = (boot["account_id"], boot["account_generation"], boot["sync_epoch"])
        previous = (state["account_id"], state["generation"], state["epoch"])
        require(
            previous == (None, None, None) or previous == context, "resume_account_or_epoch_changed"
        )
        state.update(account_id=context[0], generation=context[1], epoch=context[2])
        save("state.json", state)
        processed = 0
        for case in manifest.cases:
            entry = state["cases"].get(case.case_id)
            if entry and entry.get("state") in {"succeeded", "failed"}:
                continue
            if processed == maximum:
                break
            processed += 1
            if entry is None:
                entry = {
                    "sha256": case.sha256,
                    "operation_key": str(uuid4()),
                    "analysis_id": None,
                    "state": "create_pending",
                    "profile": None,
                    "error_code": None,
                }
                state["cases"][case.case_id] = entry
                save("state.json", state)
            deadline = clock() + 420
            if entry["analysis_id"] is None:
                image = read_file(case.image_path, MAX_IMAGE)
                require(hashlib.sha256(image).hexdigest() == case.sha256, "image_hash_mismatch")
                metadata = {
                    "consent": {
                        "accepted": True,
                        "notice_version": case.notice_version,
                        "provider": "gemini",
                        "scope": "this_photo",
                    }
                }
                created = response(
                    CreateResponse,
                    api.request(
                        "POST",
                        "/api/v1/ai/food-analyses",
                        deadline=deadline,
                        headers={
                            "Idempotency-Key": entry["operation_key"],
                            "X-Sync-Epoch": state["epoch"],
                        },
                        files={
                            "metadata": (None, json.dumps(metadata), "application/json"),
                            "image": ("photo", image, image_media(image)),
                        },
                    ),
                )
                entry.update(
                    analysis_id=created["analysis_id"],
                    profile=created["profile"],
                    state=created["state"],
                )
                save("state.json", state)
                require(created["profile"] == manifest.profile, "accepted_profile_changed")
            while True:
                analysis = response(
                    AnalysisResponse,
                    api.request(
                        "GET", "/api/v1/ai/food-analyses/" + entry["analysis_id"], deadline=deadline
                    ),
                )
                require(
                    analysis["analysis_id"] == entry["analysis_id"]
                    and analysis["profile"] == manifest.profile,
                    "analysis_binding_changed",
                )
                entry["state"] = analysis["state"]
                if analysis["state"] in {"succeeded", "failed"}:
                    require(analysis["decision_state"] == "pending", "analysis_decision_changed")
                    proposal = analysis["proposal"]
                    require(
                        (analysis["state"] == "succeeded") == (proposal is not None),
                        "api_response_schema_invalid",
                    )
                    entry["evaluation"] = reference_oracle(
                        case, [item["name"] for item in (proposal or {}).get("items", [])]
                    )
                    entry["error_code"] = (
                        safe_code(analysis["error_code"], "analysis_failed")
                        if (analysis["state"] == "failed")
                        else None
                    )
                    entry["model_version"] = (proposal or {}).get("model_version")
                    save("state.json", state)
                    if analysis["state"] == "failed":
                        raise ReferenceError("analysis_failed_manual_review")
                    break
                save("state.json", state)
                require(clock() + 2 <= deadline, "poll_deadline_reached")
                sleep(2)
    except ReferenceError as error:
        reason = error.code
    except OSError:
        reason = "private_input_or_output_unavailable"
    result = report(manifest, state, reason)
    save("report.json", result)
    return result


def main(argv=None):
    class QuietParser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, "WAITING_EXTERNAL\n")

    parser = QuietParser(description="Consented E7-R through the application API only")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--output", required=True, type=Path, help="existing private directory outside Git"
    )
    parser.add_argument("--max-cases", type=int, default=1, choices=range(1, 11))
    arguments = parser.parse_args(argv)
    api = None
    try:
        output = PrivateOutput(arguments.output)
        with output.locked():
            try:
                manifest = load_manifest(arguments.manifest)
                api = API(
                    os.environ.get("E7_REFERENCE_API_URL", ""),
                    os.environ.get("E7_REFERENCE_TOKEN", ""),
                    ca=os.environ.get("E7_REFERENCE_CA_BUNDLE"),
                )
                result = execute(manifest, api, output, maximum=arguments.max_cases)
            except (ReferenceError, OSError, KeyboardInterrupt) as error:
                result = {
                    "status": "WAITING_EXTERNAL",
                    "reason": error.code
                    if isinstance(error, ReferenceError)
                    else "interrupted"
                    if isinstance(error, KeyboardInterrupt)
                    else "private_input_or_output_unavailable",
                }
                output.write("report.json", result)
        print(result["status"])
        return 2 if result["status"] == "WAITING_EXTERNAL" else 3
    except (ReferenceError, OSError, KeyboardInterrupt):
        print("WAITING_EXTERNAL")
        return 2
    finally:
        if api:
            api.close()


if __name__ == "__main__":
    sys.exit(main())
