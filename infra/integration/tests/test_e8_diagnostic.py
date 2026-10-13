import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_e8  # noqa: E402
from run_e8 import diagnostic_services  # noqa: E402


@pytest.mark.parametrize("array", [True, False])
def test_diagnostic_reports_stopped_worker_without_private_compose_fields(array):
    rows = [
        {
            "Service": "motivation",
            "State": "exited",
            "ExitCode": 137,
            "Health": "",
            "Name": "private-name",
            "Command": "private-password",
            "Labels": {"token": "private-token"},
        },
        {"Service": "postgres", "State": "running", "Name": "private-db"},
    ]
    raw = json.dumps(rows) if array else "\n".join(map(json.dumps, rows))
    result = diagnostic_services(raw)
    assert result == [
        {
            "service": "motivation",
            "state": "exited",
            "health": "unknown",
            "exit_code": 137,
        }
    ]
    assert "private" not in json.dumps(result)


def test_diagnostic_does_not_echo_unrecognized_fields_or_convert_bool_to_exit_code():
    result = diagnostic_services(
        json.dumps(
            [
                {
                    "Service": "nemesis-finalizer",
                    "State": "private-token",
                    "Health": "private-password",
                    "ExitCode": True,
                }
            ]
        )
    )
    assert result == [
        {
            "service": "nemesis-finalizer",
            "state": "unknown",
            "health": "unknown",
            "exit_code": None,
        }
    ]


def test_diagnostic_preserves_disabled_finalizer_health_without_inventing_success():
    result = diagnostic_services(
        json.dumps(
            [
                {
                    "Service": "nemesis-finalizer",
                    "State": "running",
                    "Health": "unhealthy",
                    "ExitCode": 0,
                }
            ]
        )
    )
    assert result[0]["health"] == "unhealthy"


def test_cli_failure_stays_failure_and_publishes_only_safe_diagnostic(
    monkeypatch, tmp_path, capsys
):
    class FailedStack:
        def __init__(self, state):
            pass

        def verify(self):
            raise RuntimeError("private-password-and-identity")

        def diagnostic(self):
            return diagnostic_services(
                json.dumps(
                    [
                        {
                            "Service": "motivation",
                            "State": "exited",
                            "ExitCode": 1,
                            "Command": "private-password-and-identity",
                        }
                    ]
                )
            )

    monkeypatch.setattr(run_e8, "E8Stack", FailedStack)
    monkeypatch.setattr(sys, "argv", ["run_e8.py", "verify", "--state", str(tmp_path)])
    assert run_e8.main() == 1
    stderr = capsys.readouterr().err
    receipt = (tmp_path / "e8-operation-error.json").read_text()
    assert "private-password" not in stderr + receipt
    assert json.loads(receipt)["services"][0]["state"] == "exited"
