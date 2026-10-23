"""Conservative Git scope and strict Project CI gate; no API or third-party dependencies."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Audited prose only: contracts/validate.py checks local links, not executable inputs.
# No globs: specifications, agent instructions, configs and new paths stay FULL.
PROSE_PATHS = frozenset(
    {"docs/KOMUNIKACJA_AGENTOW.md", "docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md"}
)
HEAVY_JOBS = (
    "quality",
    "postgres",
    "keycloak-pkce",
    "android-build",
    "android-device",
    "local-integration",
)
JOBS = frozenset(("contracts", *HEAVY_JOBS))
SHA = re.compile(r"[0-9a-f]{40}")
REASONS = {
    "allowlisted prose only",
    "empty diff requires full checks",
    "non-allowlisted path or file metadata",
    "invalid event or unavailable Git comparison; full required",
}
PLAN_KEYS = {"mode", "reason", "base", "after", "changed_count"}


def valid_sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None and value != "0" * 40


def git(repo, *args):
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def commit(repo, value):
    if not valid_sha(value):
        raise ValueError("invalid commit SHA")
    resolved = git(repo, "rev-parse", "--verify", value + "^{commit}").decode().strip()
    if resolved != value:
        raise ValueError("commit does not resolve exactly")
    return value


def comparison(repo, event_name, event, tested_sha):
    """PR: actual tested merge vs its base, with event parents checked; push: before..after."""
    after = commit(repo, tested_sha)
    if git(repo, "rev-parse", "HEAD").decode().strip() != after:
        raise ValueError("checkout differs from tested SHA")
    if event_name == "pull_request":
        parents = git(repo, "show", "-s", "--format=%P", after).decode().split()
        pr = event["pull_request"]
        if len(parents) != 2 or parents != [pr["base"]["sha"], pr["head"]["sha"]]:
            raise ValueError("PR event does not match tested merge parents")
        return commit(repo, parents[0]), after
    if event_name == "push":
        if event["after"] != after:
            raise ValueError("push after differs from tested SHA")
        return commit(repo, event["before"]), after
    raise ValueError("unsupported event")


def changes(repo, base, after):
    """NUL-delimited raw records include modes; no rename/copy hiding either changed name."""
    raw = git(
        repo,
        "diff",
        "--raw",
        "-z",
        "--no-renames",
        "--no-ext-diff",
        "--no-textconv",
        "--abbrev=40",
        base,
        after,
        "--",
    )
    if not raw:
        return []
    parts = raw.split(b"\0")
    if parts.pop() != b"" or len(parts) % 2:
        raise ValueError("invalid raw Git records")
    records = []
    for header, path in zip(parts[::2], parts[1::2], strict=True):
        fields = header.decode("ascii").split()
        if len(fields) != 5 or not fields[0].startswith(":") or not path:
            raise ValueError("invalid raw Git record")
        old, new, old_id, new_id, status = fields
        if not all(SHA.fullmatch(oid) for oid in (old_id, new_id)):
            raise ValueError("invalid raw Git object")
        records.append((old[1:], new, status, path.decode("utf-8", errors="strict")))
    return records


def classify(repo, event_name, event, tested_sha):
    plan = {
        "mode": "full",
        "reason": "unverified comparison",
        "base": "",
        "after": "",
        "changed_count": 0,
    }
    try:
        base, after = comparison(repo, event_name, event, tested_sha)
        plan.update(base=base, after=after)
        records = changes(repo, base, after)
        plan["changed_count"] = len(records)
        if not records:
            plan["reason"] = "empty diff requires full checks"
            return plan
        normal = {("100644", "100644", "M"), ("000000", "100644", "A"), ("100644", "000000", "D")}
        if all(
            (old, new, status) in normal and path in PROSE_PATHS
            for old, new, status, path in records
        ):
            plan.update(mode="docs", reason="allowlisted prose only")
        else:
            plan["reason"] = "non-allowlisted path or file metadata"
    except (ValueError, KeyError, TypeError, UnicodeError, OSError, subprocess.SubprocessError):
        # Unknown/zero before, shallow/missing commits and malformed events are never DOCS.
        plan["reason"] = "invalid event or unavailable Git comparison; full required"
    return plan


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS or plan["mode"] not in {"docs", "full"}:
        raise ValueError("missing or invalid scope plan")
    if not isinstance(plan["reason"], str) or plan["reason"] not in REASONS:
        raise ValueError("invalid scope reason")
    if type(plan["changed_count"]) is not int or plan["changed_count"] < 0:
        raise ValueError("invalid change count")
    for key in ("base", "after"):
        if plan[key] != "" and not valid_sha(plan[key]):
            raise ValueError("invalid scope range")
    if plan["mode"] == "docs" and (
        plan["reason"] != "allowlisted prose only"
        or plan["changed_count"] == 0
        or not valid_sha(plan["base"])
        or not valid_sha(plan["after"])
        or plan["base"] == plan["after"]
    ):
        raise ValueError("unverified docs plan")
    return plan


def decide(needs):
    if not isinstance(needs, dict) or set(needs) != JOBS:
        raise ValueError("missing or unexpected jobs")
    for job in needs.values():
        if not isinstance(job, dict) or not isinstance(job.get("result"), str):
            raise ValueError("invalid job result")
    contracts = needs["contracts"]
    if contracts["result"] != "success" or set(contracts["outputs"]) != {"plan"}:
        raise ValueError("contracts or qualification failed")
    plan = validate_plan(json.loads(contracts["outputs"]["plan"]))
    expected = "skipped" if plan["mode"] == "docs" else "success"
    for name in HEAVY_JOBS:
        if needs[name]["result"] != expected:
            raise ValueError(f"{name}: expected {expected}")
    return plan


def summary(plan, needs=None):
    lines = [
        f"Project CI mode: {plan['mode'].upper()}",
        f"Reason: {plan['reason']}",
        f"Git range: {plan['base'] or 'unavailable'} -> {plan['after'] or 'unavailable'}",
        f"Changed paths: {plan['changed_count']}",
    ]
    if needs is None:
        lines += [
            "Required: contracts (including scope/gate/wiring tests)",
            ("Planned skips: " if plan["mode"] == "docs" else "Required: ") + ", ".join(HEAVY_JOBS),
        ]
    else:
        lines += [f"{name}: {needs[name]['result']}" for name in ("contracts", *HEAVY_JOBS)]
        if plan["mode"] == "docs":
            lines += ["DOCS PASS: no application, PostgreSQL, Android or live E4 tests were run."]
    return "\n".join(lines) + "\n"


def report(text):
    print(text, end="")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write("```text\n" + text + "```\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("classify", "gate"))
    args = parser.parse_args()
    if args.action == "classify":
        try:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        except (KeyError, OSError, ValueError):
            event = {}
        plan = classify(
            Path.cwd(),
            os.environ.get("GITHUB_EVENT_NAME", ""),
            event,
            os.environ.get("GITHUB_SHA", ""),
        )
        validate_plan(plan)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write("plan=" + json.dumps(plan, separators=(",", ":")) + "\n")
        report(summary(plan))
    else:
        needs = {}
        try:
            needs = json.loads(os.environ["RESULTS"])
            plan = decide(needs)
        except (KeyError, TypeError, ValueError) as error:
            text = f"Project CI BLOCKED: {error}\nMode/range: unverified; no success granted\n"
            if isinstance(needs, dict):
                for name in ("contracts", *HEAVY_JOBS):
                    row = needs.get(name)
                    actual = row.get("result", "missing") if isinstance(row, dict) else "missing"
                    text += f"{name}: {actual}\n"
            report(text)
            return 1
        report(summary(plan, needs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
