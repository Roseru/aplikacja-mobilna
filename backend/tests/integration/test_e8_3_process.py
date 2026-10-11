"""Cross-process PostgreSQL admission and bounded live-history evidence."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.integration.test_e8_3_http import TERMS, account, headers
from tests.integration.test_e8_3_http import runtime as runtime

pytestmark = pytest.mark.integration


def test_two_api_processes_share_durable_code_quota(runtime):
    rt = runtime
    owner = account(rt)
    child = Path(__file__).resolve().parents[1] / "support" / "e8_3_process_child.py"
    processes = []
    try:
        for _ in range(2):
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(child), owner[1], str(rt[6]), "3"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=os.environ.copy(),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            )
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            process.stdin.write("go\n")
            process.stdin.flush()
        statuses = []
        for process in processes:
            output, error = process.communicate(timeout=30)
            assert process.returncode == 0, error
            statuses.extend(json.loads(output))
        assert sorted(statuses) == [200, 200, 200, 200, 200, 429]
        with rt[1].connect() as conn:
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=:id "
                        "AND kind='issue'"
                    ),
                    {"id": owner[0]},
                )
                == 5
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def test_metadata_has_no_global_history_cap_and_cursor_pool_bounded(runtime):
    rt = runtime
    a = account(rt)
    b = account(rt)
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    ids = {str(uuid4()) for _ in range(1107)}
    with rt[1].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,"
                "inviter_generation,invitee_generation,sync_epoch,status,terms,"
                "created_at,expires_at) "
                "VALUES(:id,:a,:b,1,1,:epoch,'invited',CAST(:terms AS jsonb),:now,:expires)"
            ),
            [
                {
                    "id": value,
                    "a": a[0],
                    "b": b[0],
                    "epoch": rt[6],
                    "terms": json.dumps(TERMS),
                    "now": now,
                    "expires": now + timedelta(days=7),
                }
                for value in ids
            ],
        )
    seen = []
    cursor = None
    while True:
        params = {"limit": 11}
        if cursor:
            params["cursor"] = cursor
        result = rt[5].get("/api/v1/me/nemesis", headers=headers(rt, a), params=params)
        assert result.status_code == 200, result.text
        page = result.json()
        seen.extend(row["id"] for row in page["items"])
        assert all("inviter_id" not in row and "invitee_id" not in row for row in page["items"])
        cursor = page["next_cursor"]
        with rt[1].connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM app.nemesis_cursors WHERE requester_id=:id"),
                    {"id": a[0]},
                )
                <= 8
            )
        if cursor is None:
            break
    assert len(seen) == 1107 and set(seen) == ids
    first = rt[5].get("/api/v1/me/nemesis?limit=11", headers=headers(rt, a)).json()
    bad = rt[5].get(
        "/api/v1/me/nemesis",
        headers=headers(rt, b),
        params={"limit": 11, "cursor": first["next_cursor"]},
    )
    assert bad.status_code == 409
