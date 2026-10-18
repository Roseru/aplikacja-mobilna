"""Real PostgreSQL/storage acceptance boundaries, lost ACK and account purge."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from test_e7_runtime import METADATA, counts, image
from test_e7_runtime import e7 as e7_fixture

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai import repository
from calorie_app.modules.ai.image_preparation import prepare_image
from calorie_app.modules.ai.service import create_analysis
from calorie_app.modules.ai.storage import PhotoStorage

pytestmark = pytest.mark.integration
e7 = e7_fixture


def accept(e7, key):
    return create_analysis(
        e7["api"],
        e7["principals"][0],
        UUID(e7["boots"][0]["sync_epoch"]),
        key,
        METADATA,
        image(),
        e7["settings"],
    )


def purge(e7):
    from tests.support.deletion_regression import purge as delete

    delete(e7["admin"], UUID(e7["boots"][0]["account_id"]))


def test_lost_commit_ack_preserves_one_accepted_file_and_replay(e7):
    key = uuid4()
    original_call, original_commit = repository.call, Session.commit

    def call(session, statement, **params):
        result = original_call(session, statement, **params)
        if "SELECT app.e7_accept(" in statement and "error" not in result:
            session.info["accepted_ack"] = True
        return result

    def commit(session):
        original_commit(session)
        if session.info.pop("accepted_ack", False):
            raise OperationalError(None, None, RuntimeError("synthetic lost COMMIT ACK"))

    with patch.object(repository, "call", call), patch.object(Session, "commit", commit):
        with pytest.raises(OperationalError):
            accept(e7, key)
    assert counts(e7)["ai_jobs"] == counts(e7)["ai_photo_consents"] == 1
    assert len(list(e7["root"].iterdir())) == 1
    with patch(
        "calorie_app.modules.ai.service.prepare_image", side_effect=AssertionError("replay")
    ):
        replay = accept(e7, key)
    assert replay.replayed and counts(e7)["ai_jobs"] == 1
    with e7["admin"].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.ai_cleanup_intents")) == 0


def test_same_operation_serializes_preparation_and_busy_retry_replays(e7):
    entered, release = threading.Event(), threading.Event()
    key = uuid4()
    calls = []

    def prepare(raw):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return prepare_image(raw)

    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        patch("calorie_app.modules.ai.service.prepare_image", prepare),
    ):
        first = pool.submit(accept, e7, key)
        try:
            assert entered.wait(10)
            with pytest.raises(DomainError) as error:
                accept(e7, key)
            assert error.value.code == "ai_operation_busy"
        finally:
            release.set()
        accepted = first.result(10)
    replay = accept(e7, key)
    assert replay.payload == accepted.payload and replay.replayed
    assert len(calls) == counts(e7)["ai_jobs"] == 1
    assert len(list(e7["root"].iterdir())) == 1


def test_distinct_keys_concurrent_admission_has_one_job_and_one_file(e7):
    barrier = threading.Barrier(2)

    def prepare(raw):
        barrier.wait(10)
        return prepare_image(raw)

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        patch("calorie_app.modules.ai.service.prepare_image", prepare),
    ):
        futures = [pool.submit(accept, e7, uuid4()) for _ in range(2)]
        results = [future.result(15) for future in futures]
    assert sum(result.error is None for result in results) == 1
    assert [r.error.code for r in results if r.error] == ["ai_active_job"]
    assert counts(e7)["ai_jobs"] == 1 and len(list(e7["root"].iterdir())) == 1
    with e7["admin"].connect() as connection:
        assert connection.scalar(text("SELECT sum(photos) FROM app.ai_admissions")) == 1


@pytest.mark.parametrize("boundary", ["codec", "staging"])
def test_purge_during_preparation_or_staging_never_resurrects(e7, boundary):
    original = PhotoStorage.activate

    def prepare(raw):
        result = prepare_image(raw)
        purge(e7)
        return result

    def activate(storage, key, raw):
        original(storage, key, raw)
        purge(e7)

    target = "calorie_app.modules.ai.service.prepare_image" if boundary == "codec" else None
    context = patch(target, prepare) if target else patch.object(PhotoStorage, "activate", activate)
    with context:
        with pytest.raises(DomainError):
            accept(e7, uuid4())
    assert not list(e7["root"].iterdir())
    assert counts(e7)["ai_jobs"] == counts(e7)["ai_photo_consents"] == 0
    with e7["admin"].connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM app.ai_cleanup_intents")) == 0


def test_fs_error_after_activation_uses_durable_compensation(e7):
    original = PhotoStorage.activate

    def activate(storage, key, raw):
        original(storage, key, raw)
        with e7["admin"].connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM app.ai_cleanup_intents")) == 1
        raise OSError("synthetic failure after durable rename")

    with patch.object(PhotoStorage, "activate", activate), pytest.raises(OSError):
        accept(e7, uuid4())
    assert not list(e7["root"].iterdir()) and counts(e7)["ai_jobs"] == 0
