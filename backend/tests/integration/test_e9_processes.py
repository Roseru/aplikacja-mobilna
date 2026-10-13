"""Actual separate worker processes and committed dispatch/fence crash boundaries."""

import json
import os
import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Thread
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.integration.test_e7_runtime import e7 as e7_fixture
from tests.integration.test_e9_energy import body, create, owner, post, read, seed

e7 = e7_fixture
pytestmark = pytest.mark.integration
HELPER = Path(__file__).resolve().parents[1] / "support/e9_worker_child.py"


def spawn(rt, job, pause=None):
    process = subprocess.Popen(
        [sys.executable, str(HELPER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    request = {
        "database_url": rt["worker"].url.render_as_string(hide_password=False),
        "photo_root": str(rt["root"]),
        "job_id": str(job),
        "pause": pause,
    }
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    assert event(process)["event"] == "ready"
    return process


def event(process):
    result = Queue()
    Thread(target=lambda: result.put(process.stdout.readline()), daemon=True).start()
    line = result.get(timeout=30)
    assert line, "owned worker exited before its boundary"
    return json.loads(line)


def job(rt):
    with rt["admin"].connect() as c:
        return c.scalar(text("SELECT id FROM app.ai_jobs WHERE purpose='energy_adjustment'"))


def finish(process):
    output, error = process.communicate("continue\n", timeout=45)
    assert process.returncode == 0, error
    return output


def test_two_real_processes_cannot_claim_or_publish_twice(e7):
    seed(e7)
    a = create(e7)
    first = spawn(e7, job(e7), "after_claim")
    try:
        assert event(first)["boundary"] == "after_claim"
        second = spawn(e7, job(e7))
        try:
            assert event(second) == {"event": "done", "handled": False}
            assert second.wait(timeout=10) == 0
        finally:
            if second.poll() is None:
                second.kill()
        finish(first)
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=10)
    ready = read(e7, a["id"]).json()
    assert ready["state"] == "ready", ready
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 2


def test_real_kill_after_dispatch_restart_never_sends_again(e7):
    seed(e7)
    a = create(e7)
    first = spawn(e7, job(e7), "after_dispatch")
    assert event(first)["boundary"] == "after_dispatch"
    first.kill()
    first.communicate(timeout=10)
    with e7["admin"].begin() as c:
        c.execute(text("UPDATE app.ai_jobs SET lease_until=clock_timestamp()-interval '1 second'"))
    second = spawn(e7, job(e7))
    assert event(second) == {"event": "done", "handled": False}
    assert second.wait(timeout=10) == 0
    result = read(e7, a["id"]).json()
    assert result["state"] == "failed" and result["error_code"] == "provider_result_unknown"
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 1
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL")
            )
            == 1
        )


@pytest.mark.parametrize("change", ["source", "epoch", "delete", "revert"])
def test_real_late_worker_is_fenced_by_competing_source_or_account_change(e7, change):
    original, _, _ = seed(e7)
    create(e7)
    first = spawn(e7, job(e7), "before_result_commit")
    try:
        assert event(first)["boundary"] == "before_result_commit"
        with e7["admin"].begin() as c:
            if change == "source":
                c.execute(
                    text("UPDATE app.weights SET revision=revision+1 WHERE owner_id=:owner"),
                    {"owner": owner(e7)},
                )
            elif change == "epoch":
                c.execute(
                    text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
                    {"epoch": uuid4()},
                )
            elif change == "delete":
                c.execute(
                    text("SELECT app.begin_account_deletion(:owner,:operation,1)"),
                    {"owner": owner(e7), "operation": uuid4()},
                )
        if change == "revert":
            response = post(e7, "revert", body(e7) | {"id": str(original), "replace_id": None})
            assert response.status_code == 200, response.text
        finish(first)
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate(timeout=10)
    with e7["admin"].connect() as c:
        assert c.scalar(text("SELECT count(*) FROM app.energy_versions WHERE source='manual'")) == 0
        assert (
            c.scalar(text("SELECT count(*) FROM app.energy_versions WHERE source='automatic'")) == 0
        )
        assert c.scalar(text("SELECT count(*) FROM app.ai_attempts")) == 2
        assert (
            c.scalar(
                text("SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL")
            )
            == 0
        )
