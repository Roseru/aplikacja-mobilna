"""Repeat the PG17 deletion contract rehearsal in a fresh owned output directory."""

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    state = args.state.resolve()
    if state.exists() or not os.environ.get("TEST_DATABASE_URL"):
        parser.error("new scratch state and dedicated PG17 TEST_DATABASE_URL required")
    state.mkdir(parents=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    )
    report = state / "tests.xml"
    with (state / "private-test.log").open("wb") as output:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/tests/integration/test_deletion_ledger.py",
                "backend/tests/unit/test_deletion_ledger_contract.py",
                "--tb=short",
                "-q",
                "--basetemp",
                str(state / "pytest"),
                "--junitxml",
                str(report),
            ],
            cwd=ROOT,
            stdout=output,
            stderr=output,
            timeout=300,
        )
    suites = ET.parse(report).getroot().findall("testsuite") if report.exists() else []
    tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(
        int(s.attrib.get("failures", 0)) + int(s.attrib.get("errors", 0)) for s in suites
    )
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    passed = result.returncode == 0 and tests >= 40 and failures == skipped == 0
    receipt = {
        "version": 1,
        "scope": "isolated-PG17-deletion-ledger-contract",
        "result": "PASS" if passed else "FAIL",
        "commit": head,
        "dirty_source": dirty,
        "migration": "0025_deletion_ledger",
        "tests": tests,
        "failures": failures,
        "skipped": skipped,
        "production_stream": False,
        "reopen_authorized": False,
        "full_ko32": "WAITING_EXTERNAL O3/O1",
        "google_calls": 0,
    }
    (state / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
