"""Actual PG/storage/worker processes plus separate loopback HTTP, never E7-R."""

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_e7_runtime import METADATA, image
from test_e7_runtime import e7 as _runtime_e7

from calorie_app.integrations.gemini.mock import generate_envelope, sample_food
from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.ai.service import create_analysis
from calorie_app.modules.identity.service import bootstrap

pytestmark = pytest.mark.integration
e7 = _runtime_e7
HELPER = Path(__file__).resolve().parents[1] / "support" / "e7_worker_child.py"


class OwnedProcess:
    """An exact owned process object, including after its parent is killed."""

    def __init__(self, pid):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.TerminateProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x00100000 | 0x0001, False, pid)
            assert handle, "owned child handle must be opened before send"
            self.wait = lambda timeout: (
                kernel.WaitForSingleObject(handle, max(0, int(timeout * 1000))) == 0
            )
            self.terminate = lambda: kernel.TerminateProcess(handle, 125)
            self.close_handle = lambda: kernel.CloseHandle(handle)
        else:
            import select
            import signal

            descriptor = os.pidfd_open(pid)
            self.wait = lambda timeout: bool(
                select.select([descriptor], [], [], max(0, timeout))[0]
            )
            self.terminate = lambda: signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            self.close_handle = lambda: os.close(descriptor)

    def close(self, deadline):
        if not self.wait(max(0, deadline - time.monotonic()) + 1.5):
            self.terminate()
            assert self.wait(5)
        self.close_handle()


class WorkerProcess:
    def __init__(self, state, fake, job, *, pause=(), transport_seconds=20):
        self.events, self.children = [], []
        self.condition, self.write_lock = threading.Condition(), threading.Lock()
        self.reader_error = None
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH"}
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        self.process = subprocess.Popen(
            [sys.executable, str(HELPER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        request = {
            "database_url": state["worker"].url.render_as_string(hide_password=False),
            "photo_root": str(state["root"]),
            "job_id": str(job),
            "fake_url": fake.url,
            "pause": [
                {"boundary": boundary, "occurrence": occurrence} for boundary, occurrence in pause
            ],
            "transport_seconds": transport_seconds,
        }
        self.process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for raw in iter(lambda: self.process.stdout.readline(8193), b""):
                if len(raw) > 8192:
                    raise ValueError("unbounded test child event")
                event = json.loads(raw)
                if event["event"] == "transport_child":
                    self.children.append((OwnedProcess(event["pid"]), event["deadline"]))
                    self.send()
                with self.condition:
                    self.events.append(event)
                    self.condition.notify_all()
        except Exception as error:
            with self.condition:
                self.reader_error = type(error).__name__
                self.condition.notify_all()
        finally:
            with self.condition:
                self.condition.notify_all()

    def send(self):
        with self.write_lock:
            self.process.stdin.write(b"continue\n")
            self.process.stdin.flush()

    def event(self, kind, *, boundary=None, occurrence=None, timeout=20):
        def find():
            return next(
                (
                    event
                    for event in self.events
                    if event["event"] == kind
                    and (boundary is None or event.get("boundary") == boundary)
                    and (occurrence is None or event.get("occurrence") == occurrence)
                ),
                None,
            )

        with self.condition:
            ready = self.condition.wait_for(
                lambda: find() is not None or self.reader_error is not None, timeout=timeout
            )
            assert ready and self.reader_error is None, (
                f"worker barrier failed: {kind}/{boundary}; {self.reader_error}"
            )
            return find()

    def start(self):
        self.event("ready")
        self.send()

    def finish(self):
        done = self.event("done")
        self.process.wait(timeout=5)
        assert self.process.returncode == 0
        return done

    def kill(self):
        self.process.kill()
        self.process.wait(timeout=5)
        assert self.process.returncode is not None

    def close(self):
        if self.process.poll() is None:
            self.kill()
        self.reader.join(timeout=5)
        assert not self.reader.is_alive()
        for child, deadline in self.children:
            child.close(deadline)
        self.process.stdin.close()
        self.process.stdout.close()


@contextmanager
def workers(state, fake):
    owned = []

    def spawn(job, **kwargs):
        worker = WorkerProcess(state, fake, job, **kwargs)
        owned.append(worker)
        return worker

    try:
        yield spawn
    finally:
        for worker in owned:
            worker.close()


class FakeProvider:
    def __init__(self, hold_count=False, hold_generate=False):
        self.records, self.holds = [], {}
        self.condition = threading.Condition()
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                size = int(self.headers["Content-Length"])
                assert 0 < size <= 8 * 1024 * 1024
                body = json.loads(self.rfile.read(size))
                kind = self.path.rsplit(":", 1)[-1]
                with fixture.condition:
                    index = len(fixture.records) + 1
                    fixture.records.append({"kind": kind, "body": body, "index": index})
                    gate = threading.Event()
                    fixture.holds[index] = gate
                    fixture.condition.notify_all()
                if (hold_count and kind == "countTokens") or (
                    hold_generate and kind == "generateContent"
                ):
                    gate.wait(timeout=30)
                raw = (
                    b'{"totalTokens":512}'
                    if kind == "countTokens"
                    else generate_envelope(sample_food())
                )
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def accepted(self, count, timeout=20):
        with self.condition:
            assert self.condition.wait_for(lambda: len(self.records) >= count, timeout=timeout)
            return list(self.records)

    def release(self, index):
        self.holds[index].set()

    def counts(self):
        with self.condition:
            return {
                kind: sum(row["kind"] == kind for row in self.records)
                for kind in ("countTokens", "generateContent")
            }

    def close(self):
        for gate in self.holds.values():
            gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def create_job(state, who=0):
    if who >= len(state["principals"]):
        principal = Principal("https://process.e7.test", str(uuid4()), frozenset({"user"}))
        with Session(state["api"]) as session, session.begin():
            state["boots"].append(bootstrap(session, principal, uuid4()))
        state["principals"].append(principal)
    result = create_analysis(
        state["api"],
        state["principals"][who],
        UUID(state["boots"][who]["sync_epoch"]),
        uuid4(),
        METADATA,
        image(),
        state["settings"],
    )
    assert result.status == 202
    analysis = UUID(result.payload["analysis_id"])
    with state["admin"].connect() as connection:
        job = connection.scalar(
            text("SELECT id FROM app.ai_jobs WHERE analysis_id=:id"), {"id": analysis}
        )
    assert job is not None and len(list(state["root"].iterdir())) >= 1
    return job, analysis


def row(state, analysis):
    with state["admin"].connect() as connection:
        return dict(
            connection.execute(
                text(
                    "SELECT "
                    "a.state,j.state AS job_state,a.error_code,a.proposal,j.phase,j.fence,"
                    "j.input_tokens,j.generate_attempts"
                    " FROM app.ai_analyses a JOIN app.ai_jobs j ON "
                    "j.analysis_id=a.id WHERE a.id=:id"
                ),
                {"id": analysis},
            )
            .mappings()
            .one()
        )


def sql_value(state, statement, **parameters):
    with state["admin"].begin() as connection:
        return connection.scalar(text(statement), parameters)


def attempts(state, job):
    with state["admin"].connect() as connection:
        return [
            dict(item)
            for item in connection.execute(
                text("SELECT * FROM app.ai_attempts WHERE job_id=:id ORDER BY dispatched_at,id"),
                {"id": job},
            ).mappings()
        ]


def permits(state):
    return sql_value(
        state, "SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL"
    )


def expire_lease(state, job):
    sql_value(
        state,
        "UPDATE app.ai_jobs SET lease_until=clock_timestamp()-interval '1 "
        "second' WHERE id=:id RETURNING id",
        id=job,
    )


def ready_retry(state, job):
    sql_value(
        state,
        "UPDATE app.ai_jobs SET next_attempt_at=clock_timestamp()-interval "
        "'1 second' WHERE id=:id RETURNING id",
        id=job,
    )


def fence_proven_dead(state, job):
    for attempt in attempts(state, job):
        if attempt["io_finished_at"] is None:
            evidence = hashlib.sha256(
                ("owned-process-termination:" + str(attempt["id"])).encode()
            ).hexdigest()
            sql_value(
                state,
                "SELECT app.e7_fence_permit(:id,:evidence,true)",
                id=attempt["id"],
                evidence=evidence,
            )
            saved = next(item for item in attempts(state, job) if item["id"] == attempt["id"])
            assert saved["fenced_at"] is not None and saved["fencing_evidence_hash"] == evidence


@pytest.mark.parametrize("number", [2, 3])
def test_actual_workers_claim_the_same_job_once(e7, number):
    job, analysis = create_job(e7)
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        contenders = [spawn(job, pause=[("after_claim", 1)]) for _ in range(number)]
        for contender in contenders:
            contender.event("ready")
        for contender in contenders:
            contender.send()
        winner = None
        for contender in contenders:
            with contender.condition:
                assert contender.condition.wait_for(
                    lambda contender=contender: (
                        any(
                            event["event"] == "done"
                            or (event["event"] == "hook" and event["boundary"] == "after_claim")
                            for event in contender.events
                        )
                        or contender.reader_error
                    ),
                    timeout=20,
                )
                claimed = any(
                    event["event"] == "hook" and event["boundary"] == "after_claim"
                    for event in contender.events
                )
            if claimed:
                assert winner is None
                winner = contender
            else:
                assert contender.finish()["handled"] is False
        assert winner is not None and row(e7, analysis)["phase"] == "claimed"
        assert attempts(e7, job) == [] and fake.counts() == {"countTokens": 0, "generateContent": 0}
        winner.send()
        assert winner.finish()["handled"] is True
        assert row(e7, analysis)["state"] == "succeeded"
        assert fake.counts() == {"countTokens": 1, "generateContent": 1}
        assert len(attempts(e7, job)) == 2 and permits(e7) == 0


def test_two_physical_outbound_calls_block_a_third_actual_worker_until_io_ends(e7):
    jobs = [create_job(e7, who) for who in range(3)]
    with FakeProvider(hold_count=True) as fake, workers(e7, fake) as spawn:
        first, second = spawn(jobs[0][0]), spawn(jobs[1][0])
        first.start()
        fake.accepted(1)
        second.start()
        fake.accepted(2)
        assert permits(e7) == 2
        assert not first.children[0][0].wait(0) and not second.children[0][0].wait(0)
        third = spawn(jobs[2][0])
        third.start()
        assert third.finish()["handled"] is True
        assert fake.counts() == {"countTokens": 2, "generateContent": 0}
        assert row(e7, jobs[2][1])["job_state"] == "queued" and attempts(e7, jobs[2][0]) == []
        fake.release(1)
        fake.release(2)
        first.finish()
        second.finish()
        assert permits(e7) == 0
        ready_retry(e7, jobs[2][0])
        retried = spawn(jobs[2][0])
        retried.start()
        third_count = fake.accepted(5)[-1]
        assert third_count["kind"] == "countTokens"
        fake.release(third_count["index"])
        retried.finish()
        assert fake.counts() == {"countTokens": 3, "generateContent": 3}
        assert all(row(e7, analysis)["state"] == "succeeded" for _, analysis in jobs)


def test_expired_lease_cannot_free_alive_io_or_allow_stale_result_and_next_send(e7):
    jobs = [create_job(e7, who) for who in range(3)]
    with FakeProvider(hold_count=True) as fake, workers(e7, fake) as spawn:
        stale = spawn(jobs[0][0])
        stale.start()
        fake.accepted(1)
        expire_lease(e7, jobs[0][0])
        recovery = spawn(jobs[0][0])
        recovery.start()
        assert recovery.finish()["handled"] is False
        assert row(e7, jobs[0][1])["error_code"] == "provider_result_unknown"
        assert permits(e7) == 1 and not stale.children[0][0].wait(0)
        second = spawn(jobs[1][0])
        second.start()
        fake.accepted(2)
        third = spawn(jobs[2][0])
        third.start()
        third.finish()
        assert permits(e7) == 2 and attempts(e7, jobs[2][0]) == []
        fake.release(1)
        stale.finish()
        assert fake.counts() == {"countTokens": 2, "generateContent": 0}
        assert row(e7, jobs[0][1])["proposal"] is None
        fake.release(2)
        second.finish()
        assert fake.counts() == {"countTokens": 2, "generateContent": 1}
        assert row(e7, jobs[0][1])["state"] == "failed" and permits(e7) == 0


@pytest.mark.parametrize(
    "boundary,occurrence", [("after_claim", 1), ("before_dispatch", 1), ("before_dispatch", 2)]
)
def test_kill_before_durable_marker_is_safely_reclaimed_without_prior_send(
    e7, boundary, occurrence
):
    job, analysis = create_job(e7)
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        original = spawn(job, pause=[(boundary, occurrence)])
        original.start()
        original.event("hook", boundary=boundary, occurrence=occurrence)
        old_fence = row(e7, analysis)["fence"]
        original.kill()
        assert permits(e7) == 0 and len(attempts(e7, job)) == occurrence - 1
        assert fake.counts() == {"countTokens": occurrence - 1, "generateContent": 0}
        expire_lease(e7, job)
        replacement = spawn(job)
        replacement.start()
        replacement.finish()
        assert row(e7, analysis)["state"] == "succeeded" and row(e7, analysis)["fence"] != old_fence
        assert fake.counts() == {"countTokens": 1, "generateContent": 1}
        assert len(attempts(e7, job)) == 2 and permits(e7) == 0


@pytest.mark.parametrize("occurrence", [1, 2])
def test_kill_after_marker_before_send_is_unknown_without_new_connection_and_keeps_permit(
    e7, occurrence
):
    job, analysis = create_job(e7)
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        original = spawn(job, pause=[("after_dispatch", occurrence)])
        original.start()
        original.event("hook", boundary="after_dispatch", occurrence=occurrence)
        assert row(e7, analysis)["phase"] == "dispatch_started" and permits(e7) == 1
        original.kill()
        expire_lease(e7, job)
        replacement = spawn(job)
        replacement.start()
        assert replacement.finish()["handled"] is False
        assert row(e7, analysis)["error_code"] == "provider_result_unknown"
        assert fake.counts() == {"countTokens": occurrence - 1, "generateContent": 0}
        assert len(attempts(e7, job)) == occurrence and permits(e7) == 1
        assert len(original.children) == occurrence - 1
        assert all(child.wait(0) for child, _ in original.children)
        assert original.process.poll() is not None
        fence_proven_dead(e7, job)
        assert permits(e7) == 0 and attempts(e7, job)[0]["reserved_tokens"] == 10240


@pytest.mark.parametrize("accepted_kind", ["countTokens", "generateContent"])
def test_kill_after_http_acceptance_never_resends_and_orphan_permit_needs_physical_fencing(
    e7, accepted_kind
):
    job, analysis = create_job(e7)
    calls = 1 if accepted_kind == "countTokens" else 2
    with (
        FakeProvider(hold_count=calls == 1, hold_generate=calls == 2) as fake,
        workers(e7, fake) as spawn,
    ):
        original = spawn(job, transport_seconds=10)
        original.start()
        fake.accepted(calls)
        child, deadline = original.children[-1]
        assert not child.wait(0) and permits(e7) == 1
        original.kill()
        expire_lease(e7, job)
        replacement = spawn(job)
        replacement.start()
        assert replacement.finish()["handled"] is False
        assert row(e7, analysis)["error_code"] == "provider_result_unknown" and permits(e7) == 1
        assert child.wait(max(0, deadline - time.monotonic()) + 1.5)
        assert permits(e7) == 1
        fake.release(calls)
        fence_proven_dead(e7, job)
        assert permits(e7) == 0 and fake.counts() == {
            "countTokens": 1,
            "generateContent": calls - 1,
        }
        assert len(attempts(e7, job)) == calls and row(e7, analysis)["proposal"] is None


@pytest.mark.parametrize(
    "boundary,occurrence,active_permits", [("after_response", 2, 1), ("before_result_commit", 1, 0)]
)
def test_kill_after_generation_response_before_result_commit_is_unknown_without_resend(
    e7, boundary, occurrence, active_permits
):
    job, analysis = create_job(e7)
    with FakeProvider() as fake, workers(e7, fake) as spawn:
        original = spawn(job, pause=[(boundary, occurrence)])
        original.start()
        original.event("hook", boundary=boundary, occurrence=occurrence)
        assert fake.counts() == {"countTokens": 1, "generateContent": 1}
        assert permits(e7) == active_permits and all(
            child.wait(0) for child, _ in original.children
        )
        original.kill()
        expire_lease(e7, job)
        replacement = spawn(job)
        replacement.start()
        assert replacement.finish()["handled"] is False
        assert row(e7, analysis)["state"] == "failed"
        assert row(e7, analysis)["error_code"] == "provider_result_unknown"
        assert row(e7, analysis)["proposal"] is None and len(attempts(e7, job)) == 2
        assert fake.counts() == {"countTokens": 1, "generateContent": 1}
        fence_proven_dead(e7, job)
        assert permits(e7) == 0
