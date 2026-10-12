"""Real loopback TCP HTTP, commit/lost-ACK, restart and two API replicas."""

import json
import os
import socket
import subprocess
import sys
import sysconfig
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import text

from tests.integration.test_e8_3_http import account, headers
from tests.integration.test_e8_3_http import runtime as runtime

pytestmark = pytest.mark.integration


@pytest.fixture
def servers(runtime, tmp_path):
    rt = runtime
    private = tmp_path / "private-server.json"
    public = json.loads(RSAAlgorithm.to_jwk(rt[4].private.public_key()))
    public.update(kid="e8-component", use="sig", alg="RS256")
    private.write_text(
        json.dumps({"api_url": rt[0].api_url, "jwks": {"keys": [public]}}), encoding="utf-8"
    )
    child = Path(__file__).resolve().parents[1] / "support" / "e8_3_http_server.py"
    base = int(os.environ.get("E8_3_HTTP_PROBE_PORT_BASE", "18181"))
    processes = []
    logs = []

    def start(index):
        port = base + index
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("refusing to reuse an active listener")
        log_path = tmp_path / f"server-{index}-{len(processes)}.log"
        log = log_path.open("w", encoding="utf-8")
        logs.append(log)
        child_env = os.environ.copy()
        site_packages = sysconfig.get_path("purelib")
        child_env["PYTHONPATH"] = site_packages + os.pathsep + child_env.get("PYTHONPATH", "")
        process = subprocess.Popen(
            [getattr(sys, "_base_executable", sys.executable), str(child), str(private), str(port)],
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            env=child_env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        processes.append(process)
        # stdout readiness is emitted only after uvicorn has bound the listener.
        with ThreadPoolExecutor(max_workers=1) as executor:
            ready = executor.submit(process.stdout.readline)
            try:
                assert ready.result(timeout=20).strip() == "ready"
            except BaseException:
                process.terminate()
                process.wait(timeout=10)
                raise
        return process, f"http://127.0.0.1:{port}"

    try:
        first, url1 = start(0)
        second, url2 = start(1)
        yield rt, (first, url1), (second, url2), start, tmp_path
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for log in logs:
            log.close()


def test_tcp_commit_lost_ack_restart_and_no_store(servers):
    rt, first, second, start, logs = servers
    owner = account(rt)
    key = uuid4()
    h = headers(rt, owner, key)
    port = int(first[1].rsplit(":", 1)[1])
    raw = (
        "POST /api/v1/me/nemesis/share-code HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        + "".join(name + ": " + value + "\r\n" for name, value in h.items())
        + "Content-Length: 0\r\nConnection: close\r\n\r\n"
    ).encode("ascii")
    client = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        client.sendall(raw)
        deadline = monotonic() + 15
        with rt[1].connect() as conn:
            while not conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM app.nemesis_receipts "
                    "WHERE owner_id=:owner AND operation='issue' AND key=:key)"
                ),
                {"owner": owner[0], "key": key},
            ):
                if monotonic() > deadline:
                    pytest.fail("server commit barrier was not reached")
        # No recv: the client deliberately loses the ACK after DB commit.
    finally:
        client.close()
    first[0].terminate()
    first[0].wait(timeout=10)
    _, restarted = start(0)
    with httpx.Client(timeout=15, trust_env=False) as http:
        replay = http.post(restarted + "/api/v1/me/nemesis/share-code", headers=h)
        again = http.post(second[1] + "/api/v1/me/nemesis/share-code", headers=h)
        assert replay.status_code == again.status_code == 200
        assert replay.json() == again.json()
        assert replay.headers["cache-control"] == "no-store"
        raw_code = replay.json()["destination_code"]
        bad = http.post(restarted + "/api/v1/me/nemesis/share-code")
        assert bad.status_code == 401 and bad.headers["cache-control"] == "no-store"
    with rt[1].connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=:owner "
                    "AND kind='issue'"
                ),
                {"owner": owner[0]},
            )
            == 1
        )
    for log in logs.glob("server-*.log"):
        content = log.read_text(encoding="utf-8")
        assert raw_code not in content and h["Authorization"] not in content


def test_two_tcp_api_replicas_share_rolling_quota(servers):
    rt, first, second, _, _ = servers
    owner = account(rt)
    barrier = Barrier(2)

    def run(url):
        with httpx.Client(timeout=15, trust_env=False) as client:
            barrier.wait(timeout=15)
            statuses = []
            for _ in range(3):
                result = client.post(
                    url + "/api/v1/me/nemesis/share-code", headers=headers(rt, owner)
                )
                assert result.headers["cache-control"] == "no-store"
                if result.status_code == 429:
                    assert int(result.headers["retry-after"]) > 0
                statuses.append(result.status_code)
            return statuses

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = [
            status for result in executor.map(run, [first[1], second[1]]) for status in result
        ]
    assert sorted(statuses) == [200, 200, 200, 200, 200, 429]
