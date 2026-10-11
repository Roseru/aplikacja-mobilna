"""Physical disposable processes and real HTTP; these are transport, not E7-R."""

import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from calorie_app.integrations.gemini import transport
from calorie_app.integrations.gemini.adapter import _endpoint
from calorie_app.integrations.gemini.mock import generate_envelope, sample_food
from calorie_app.integrations.gemini.transport import execute
from calorie_app.modules.ai.prompts import MODEL
from calorie_app.modules.ai.result import MAX_PROVIDER_BYTES, ProviderResultError

IMAGE = b"\xff\xd8\xffsynthetic-prepared-image"


@contextmanager
def fake_provider(*, mode="ok", status=200, response=None, headers=None):
    records = []
    accepted, disconnected, stop = threading.Event(), threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            records.append(
                {
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            accepted.set()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            if mode == "trickle":
                self.send_header("Content-Length", "100000")
                self.end_headers()
                try:
                    while not stop.wait(0.03):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    disconnected.set()
                return
            raw = response
            if raw is None:
                raw = (
                    b'{"totalTokens":512}'
                    if self.path.endswith(":countTokens")
                    else generate_envelope(sample_food())
                )
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = {
        "_test_base_url": f"http://127.0.0.1:{server.server_port}",
        "environment": "test",
        "test_fixture_adapter": True,
        "api_key": "fixture-secret-only",
    }
    try:
        yield cfg, records, accepted, disconnected
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("valid", "ok"),
        ("null", "ok"),
        ("invalid", "provider_result_invalid"),
        ("safety", "provider_safety_block"),
        ("429_minute", "provider_rate_limited"),
        ("429_daily", "ai_quota_exhausted"),
        ("429_unknown", "ai_quota_exhausted"),
        ("unknown", "provider_result_unknown"),
        ("injection", "provider_result_invalid"),
        ("no_food", "provider_no_food"),
    ],
)
def test_mock_scenarios_are_server_selected_and_use_strict_process_envelope(scenario, code):
    outcome = execute("mock", "generateContent", IMAGE, {"mock_scenario": scenario}, 10)
    assert outcome.code == code
    if scenario == "null":
        assert outcome.result.items[0].nutrition_per_100.protein_g is None
    if code == "ok":
        assert outcome.model_version == "mock-food-photo-v1"


def test_mock_preflight_is_explicit_synthetic_token_count():
    outcome = execute("mock", "countTokens", IMAGE, {"mock_scenario": "valid"}, 10)
    assert outcome.code == "ok" and outcome.token_count == 512
    assert outcome.result is None and outcome.total_tokens is None


def test_real_loopback_count_and_generate_send_same_immutable_content_and_one_call_each():
    with fake_provider() as (config, records, _, _):
        count = execute("gemini", "countTokens", IMAGE, config, 10)
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert count.code == outcome.code == "ok"
        assert count.token_count == 512 and len(records) == 2
        assert records[0]["path"] == f"/v1beta/models/{MODEL}:countTokens"
        assert records[1]["path"] == f"/v1beta/models/{MODEL}:generateContent"
        assert records[0]["body"]["generateContentRequest"] == records[1]["body"]
        assert records[1]["headers"]["x-goog-api-key"] == "fixture-secret-only"
        assert "fixture-secret-only" not in records[1]["path"]


def test_500_possible_send_is_unknown_without_transport_retry():
    with fake_provider(status=503) as (config, records, accepted, _):
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert accepted.is_set() and len(records) == 1
        assert outcome.code == "provider_result_unknown" and outcome.sent


def test_redirect_is_not_followed():
    with fake_provider(status=307, headers={"Location": "http://127.0.0.1:1/redirect"}) as (
        config,
        records,
        _,
        _,
    ):
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert len(records) == 1 and outcome.code == "provider_unavailable"


def test_unknown_429_free_text_is_terminal_with_one_connection():
    payload = json.dumps(
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "minute limit; retry now",
                "details": [],
            }
        }
    ).encode()
    with fake_provider(status=429, response=payload, headers={"Retry-After": "1"}) as (
        config,
        records,
        _,
        _,
    ):
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert len(records) == 1 and outcome.code == "ai_quota_exhausted"
        assert outcome.retry_kind == "unknown"


def test_response_bytes_are_bounded_before_json_parser():
    with fake_provider(response=b" " * (MAX_PROVIDER_BYTES + 1)) as (config, records, _, _):
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert len(records) == 1 and outcome.code == "provider_response_size"


def test_trickling_http_cannot_reset_total_timeout_and_process_is_dead_before_return(monkeypatch):
    spawned = []
    real_popen = subprocess.Popen

    def record_process(args, **kwargs):
        assert "fixture-secret-only" not in repr(args)
        assert kwargs["stderr"] == subprocess.DEVNULL
        process = real_popen(args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", record_process)
    with fake_provider(mode="trickle") as (config, records, accepted, disconnected):
        started = time.monotonic()
        # Allow process/import startup under the concurrent full backend suite;
        # the server event still proves the timed-out call reached actual IO.
        outcome = execute("gemini", "generateContent", IMAGE, config, 5)
        elapsed = time.monotonic() - started
        assert accepted.is_set() and len(records) == 1
        assert outcome.code == "provider_result_unknown" and 4 <= elapsed < 8
        assert len(spawned) == 1 and spawned[0].poll() is not None
        assert disconnected.wait(5)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:123",
        "http://127.0.0.2:123",
        "https://127.0.0.1:123",
        "http://127.0.0.1:123/",
        "http://127.0.0.1:123?q=secret",
        "http://user@127.0.0.1:123",
        "http://127.0.0.1:123#f",
    ],
)
def test_fixture_url_has_exact_loopback_allowlist(url):
    with pytest.raises(ProviderResultError):
        _endpoint(
            {"environment": "test", "test_fixture_adapter": True, "_test_base_url": url},
            "generateContent",
        )


def test_fixture_cannot_run_in_non_test_environment_and_live_requires_authorization():
    for config in (
        {},
        {
            "_test_base_url": "http://127.0.0.1:123",
            "environment": "dev",
            "test_fixture_adapter": True,
        },
    ):
        with pytest.raises(ProviderResultError):
            _endpoint(config, "generateContent")
    endpoint, fixture = _endpoint({"live_authorized": True}, "generateContent")
    assert (
        endpoint
        == f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    )
    assert fixture is False


def test_unapproved_model_and_version_cannot_silently_fallback():
    for config in (
        {"live_authorized": True, "model": "latest"},
        {"live_authorized": True, "schema_version": "v999"},
    ):
        with pytest.raises(ProviderResultError):
            _endpoint(config, "generateContent")


def test_mock_timeout_is_physically_terminated(monkeypatch):
    processes = []
    original = subprocess.Popen

    def record_process(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(transport.subprocess, "Popen", record_process)
    outcome = execute("mock", "generateContent", IMAGE, {"mock_scenario": "timeout"}, 0.8)
    assert outcome.code == "provider_result_unknown"
    assert len(processes) == 1 and processes[0].poll() is not None


def test_secret_and_prepared_image_never_enter_captured_logs_or_stdout(caplog, capfd):
    with fake_provider() as (config, _, _, _):
        outcome = execute("gemini", "generateContent", IMAGE, config, 10)
        assert outcome.code == "ok"
    captured = capfd.readouterr()
    combined = captured.out + captured.err + caplog.text
    assert "fixture-secret-only" not in combined
    assert "synthetic-prepared-image" not in combined


@contextmanager
def owned_process_witness(pid):
    """Wait on the exact owned process object, including after its parent dies."""
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
        assert handle, f"cannot observe owned child {pid}"

        def wait_dead(timeout):
            status = kernel.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
            assert status in (0, 0x102), f"unexpected process wait status {status}"
            return status == 0

        def terminate():
            assert kernel.TerminateProcess(handle, 125)

        def close():
            assert kernel.CloseHandle(handle)
    else:
        import select
        import signal

        descriptor = os.pidfd_open(pid)

        def wait_dead(timeout):
            return bool(select.select([descriptor], [], [], max(0, timeout))[0])

        def terminate():
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)

        def close():
            os.close(descriptor)

    try:
        yield wait_dead
    finally:
        if not wait_dead(0):
            terminate()
            assert wait_dead(5)
        close()


def test_killed_parent_cannot_leave_trickling_transport_alive_past_its_absolute_deadline():
    # Only the small PID/deadline witness crosses this helper's stdout. The
    # config/image still travel over stdin, exactly as they do in the worker.
    helper = """
import json
import sys
from calorie_app.integrations.gemini import transport

config = json.load(sys.stdin)
original = transport.subprocess.Popen
def record_process(*args, **kwargs):
    process = original(*args, **kwargs)
    communicate = process.communicate
    def record_dispatch(input=None, timeout=None):
        request = json.loads(input)
        print(json.dumps({"pid": process.pid,
                          "deadline": request["deadline_monotonic"]}), flush=True)
        return communicate(input, timeout=timeout)
    process.communicate = record_dispatch
    return process
transport.subprocess.Popen = record_process
outcome = transport.execute("gemini", "generateContent",
                            b"\\xff\\xd8\\xffsynthetic-prepared-image", config, 8)
print(outcome.code, flush=True)
"""
    with fake_provider(mode="trickle") as (config, records, accepted, disconnected):
        parent = subprocess.Popen(
            [sys.executable, "-c", helper],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        mailbox = queue.Queue()
        reader = threading.Thread(target=lambda: mailbox.put(parent.stdout.readline()), daemon=True)
        try:
            parent.stdin.write(json.dumps(config).encode("utf-8"))
            parent.stdin.close()
            reader.start()
            witness = json.loads(mailbox.get(timeout=10))
            with owned_process_witness(witness["pid"]) as wait_dead:
                assert accepted.wait(5), (
                    "the child must reach actual HTTP before killing its parent"
                )
                assert len(records) == 1 and not wait_dead(0)
                parent.kill()
                parent.wait(timeout=5)
                assert parent.returncode is not None
                remaining = witness["deadline"] - time.monotonic()
                assert remaining > 0, "the parent must die before the child's deadline"
                assert wait_dead(remaining + 1.5), "the orphan must enforce its own deadline"
                assert time.monotonic() <= witness["deadline"] + 1.5
                assert disconnected.wait(2), "process termination must close physical HTTP IO"
                assert len(records) == 1, "parent death must not send or retry another call"
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=5)
            reader.join(timeout=1)
            parent.stdout.close()


def test_expired_absolute_deadline_refuses_provider_io_before_heavy_import():
    with fake_provider() as (config, records, accepted, _):
        request = {
            "provider": "gemini",
            "call_kind": "generateContent",
            "image": base64.b64encode(IMAGE).decode("ascii"),
            "config": config,
            "timeout_seconds": 8,
            "deadline_monotonic": time.monotonic() - 1,
        }
        child = subprocess.Popen(
            [sys.executable, "-m", "calorie_app.integrations.gemini.process"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            output, _ = child.communicate(json.dumps(request).encode(), timeout=5)
            assert child.returncode == 124 and output == b""
            assert not accepted.is_set() and records == []
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
