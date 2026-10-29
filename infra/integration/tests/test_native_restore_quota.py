"""Neutral durable mock witness boundaries; no database, provider or clock fixture."""

import hashlib
import json

import httpx
import pytest

from infra.local.integration import restore_quota_oracle as quota


def test_counter_reopens_without_reset_and_preserves_exact_http_byte_hashes(tmp_path):
    path = tmp_path / "counter.jsonl"
    counter = quota.DurableCounter(path, create=True)
    counter.append("created-before-capture", fixture="synthetic-only")
    with (
        quota._observed_provider(counter, "unit-loopback") as fake,
        httpx.Client(trust_env=False) as client,
    ):
        for kind in ("countTokens", "generateContent"):
            raw = b'{ "synthetic": true, "spaces": "preserved" }'
            response = client.post(fake.url + "/v1beta/models/mock:" + kind, content=raw)
            assert response.status_code == 200
            dispatch, outcome = counter.read()[-2:]
            assert dispatch["request_bytes"] == len(raw)
            assert dispatch["request_sha256"] == hashlib.sha256(raw).hexdigest()
            assert outcome["response_bytes"] == len(response.content)
            assert outcome["response_sha256"] == hashlib.sha256(response.content).hexdigest()
    reopened = quota.DurableCounter(path)
    assert reopened.counts() == {"countTokens": 1, "generateContent": 1}
    assert len(reopened.read()) == 5
    with pytest.raises(FileExistsError):
        quota.DurableCounter(path, create=True)


def test_counter_rejects_modified_content_gap_partial_record_and_tail_rollback(
    tmp_path,
):
    path = tmp_path / "counter.jsonl"
    counter = quota.DurableCounter(path, create=True)
    counter.append("created-before-capture", fixture="synthetic-only")
    counter.append("dispatch", kind="countTokens", request_bytes=2, request_sha256="a" * 64)
    original = path.read_bytes()
    changed = [json.loads(line) for line in original.splitlines()]
    changed[1]["request_bytes"] = 3
    path.write_bytes(b"\n".join(json.dumps(row).encode() for row in changed) + b"\n")
    with pytest.raises(ValueError, match="prefix changed"):
        quota.DurableCounter(path)
    path.write_bytes(original.splitlines()[1] + b"\n")
    with pytest.raises(ValueError, match="prefix changed"):
        quota.DurableCounter(path)
    path.write_bytes(original[:-1])
    with pytest.raises(ValueError, match="Incomplete"):
        quota.DurableCounter(path)
    path.write_bytes(original.splitlines()[0] + b"\n")
    with pytest.raises(ValueError, match="outside its observer"):
        counter.append("dispatch", kind="generateContent")


def test_failed_durability_flush_cannot_silently_continue(tmp_path, monkeypatch):
    path = tmp_path / "counter.jsonl"
    counter = quota.DurableCounter(path, create=True)
    counter.append("created-before-capture", fixture="synthetic-only")

    def failed_flush(_descriptor):
        raise OSError("synthetic disk flush failure")

    monkeypatch.setattr(quota.os, "fsync", failed_flush)
    with pytest.raises(OSError, match="flush failure"):
        counter.append("dispatch", kind="countTokens")
    with pytest.raises(ValueError, match="outside its observer"):
        counter.append("dispatch", kind="generateContent")
