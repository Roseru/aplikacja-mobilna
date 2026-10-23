"""Real Git fixtures plus the exact CLI/gate and Project CI wiring (PyYAML from contracts)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_scope as scope  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/ci_scope.py"
JOURNAL = "docs/KOMUNIKACJA_AGENTOW.md"
REPORT = "docs/integracja/PRZYGOTOWANIE_REPLAY_E4_O3.md"


def plan(mode="full"):
    return {
        "mode": mode,
        "reason": "allowlisted prose only"
        if mode == "docs"
        else "non-allowlisted path or file metadata",
        "base": "a" * 40,
        "after": "b" * 40,
        "changed_count": 1,
    }


def needs(mode="full"):
    return {
        "contracts": {"result": "success", "outputs": {"plan": json.dumps(plan(mode))}},
        **{
            name: {"result": "skipped" if mode == "docs" else "success", "outputs": {}}
            for name in scope.HEAVY_JOBS
        },
    }


class GitScopeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q", "-b", "main")
        for key, value in [
            ("user.name", "CI fixture"),
            ("user.email", "ci@example.invalid"),
            ("commit.gpgsign", "false"),
            ("core.autocrlf", "false"),
            ("core.hooksPath", str(self.repo / "no-hooks")),
        ]:
            self.git("config", key, value)
        for path in [JOURNAL, REPORT, "app.py"]:
            self.write(path, path + "\n")
        self.base = self.save()

    def git(self, *args, data=None):
        return (
            subprocess.run(
                ["git", "-C", str(self.repo), *args], input=data, capture_output=True, check=True
            )
            .stdout.decode()
            .strip()
        )

    def write(self, path, value):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value, encoding="utf-8")

    def save(self, stage=True):
        if stage:
            self.git("add", "-A")
        self.git("commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def classify(self, base=None):
        after = self.git("rev-parse", "HEAD")
        return scope.classify(
            self.repo, "push", {"before": base or self.base, "after": after}, after
        )

    def test_journal_report_and_deleted_prose(self):
        self.write(JOURNAL, "updated\n")
        self.write(REPORT, "reported\n")
        self.save()
        self.assertEqual(self.classify()["mode"], "docs")
        before = self.git("rev-parse", "HEAD")
        (self.repo / REPORT).unlink()
        self.save()
        self.assertEqual(self.classify(before)["mode"], "docs")

    def test_every_unknown_or_normative_input_requires_full(self):
        for i, path in enumerate(
            [
                "AGENTS.md",
                "WYMAGANIA_PROJEKTOWE.md",
                "docs/WORKFLOW.md",
                "docs/new-report.md",
                "contracts/schema.json",
                "data/menu.json",
                "Random Data/source.md",
                "android/app/asset.md",
                "app.py",
                ".github/workflows/backend.yml",
                "uv.lock",
                "config.yml",
            ]
        ):
            with self.subTest(path=path):
                before = self.git("rev-parse", "HEAD")
                self.write(path, f"input {i}\n")
                self.save()
                self.assertEqual(self.classify(before)["mode"], "full")

    def test_mixed_diff_and_code_deletion(self):
        self.write(JOURNAL, "prose\n")
        self.write("app.py", "new code\n")
        self.save()
        self.assertEqual(self.classify()["mode"], "full")
        before = self.git("rev-parse", "HEAD")
        (self.repo / "app.py").unlink()
        self.save()
        self.assertEqual(self.classify(before)["mode"], "full")

    def test_rename_code_to_allowlisted_md_cannot_hide_code(self):
        self.git("rm", REPORT)
        (self.repo / REPORT).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", "app.py", REPORT)
        self.save()
        self.assertEqual(self.classify()["mode"], "full")

    def test_rename_md_to_code_and_copy_to_unknown_md(self):
        self.git("rm", "app.py")
        self.git("mv", REPORT, "app.py")
        self.save()
        self.assertEqual(self.classify()["mode"], "full")
        before = self.git("rev-parse", "HEAD")
        self.write("docs/copied.md", (self.repo / "app.py").read_text())
        self.save()
        self.assertEqual(self.classify(before)["mode"], "full")

    def test_spaces_unicode_and_no_300_file_limit(self):
        for path in ["docs/raport ze spacjami.md", "docs/raport-zażółć.md"]:
            self.write(path, "unknown\n")
        for i in range(350):
            self.write(f"docs/unknown-{i}.md", "text\n")
        self.write("zz-code.py", "code\n")
        self.save()
        result = self.classify()
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["changed_count"], 353)
        records = scope.changes(self.repo, self.base, result["after"])
        self.assertIn("docs/raport-zażółć.md", [r[3] for r in records])
        self.assertIn("docs/raport ze spacjami.md", [r[3] for r in records])

    def test_push_whole_multi_commit_and_merge_range(self):
        self.git("switch", "-qc", "feature")
        self.write("app.py", "code in earlier commit\n")
        self.save()
        self.write(JOURNAL, "last commit only prose\n")
        head = self.save()
        self.assertEqual(self.classify()["mode"], "full")
        self.assertEqual(self.classify(self.git("rev-parse", "HEAD^"))["mode"], "docs")
        self.git("switch", "-q", "main")
        self.git("merge", "--no-ff", "-qm", "merge fixture", head)
        self.assertEqual(self.classify()["mode"], "full")

    def test_pr_uses_actual_test_merge_base_after_base_update(self):
        self.git("switch", "-qc", "feature")
        self.write(JOURNAL, "PR prose\n")
        head = self.save()
        self.git("switch", "-q", "main")
        self.write("app.py", "already accepted newer base code\n")
        new_base = self.save()
        self.git("merge", "--no-ff", "-qm", "merge fixture", head)
        merged = self.git("rev-parse", "HEAD")
        event = {"pull_request": {"base": {"sha": new_base}, "head": {"sha": head}}}
        result = scope.classify(self.repo, "pull_request", event, merged)
        self.assertEqual(
            (result["mode"], result["base"], result["after"]), ("docs", new_base, merged)
        )
        self.assertEqual(self.classify()["mode"], "full")  # Old base includes unrelated code.
        event["pull_request"]["base"]["sha"] = self.base
        self.assertEqual(scope.classify(self.repo, "pull_request", event, merged)["mode"], "full")
        self.assertEqual(scope.classify(self.repo, "pull_request", event, head)["mode"], "full")

    def test_modes_symlinks_and_submodules_are_not_prose(self):
        for mode in ["100755", "120000", "160000"]:
            with self.subTest(mode=mode):
                before = self.git("rev-parse", "HEAD")
                oid = (
                    before
                    if mode == "160000"
                    else self.git("hash-object", "-w", "--stdin", data=b"target\n")
                )
                self.git("update-index", "--cacheinfo", mode, oid, JOURNAL)
                self.save(stage=False)
                self.assertEqual(self.classify(before)["mode"], "full")

    def test_invalid_missing_zero_sha_empty_event_and_git_errors(self):
        after = self.git("rev-parse", "HEAD")
        self.assertEqual(self.classify()["mode"], "full")  # Empty diff.
        cases = [
            ("push", {}, after),
            ("push", {"before": "0" * 40, "after": after}, after),
            ("push", {"before": "f" * 40, "after": after}, after),
            ("push", {"before": self.base, "after": "x"}, after),
            ("pull_request", {}, after),
            ("schedule", {}, after),
            ("push", {}, ""),
            ("push", [], after),
            ("push", {}, "HEAD; unsafe"),
        ]
        for name, event, tested in cases:
            with self.subTest(name=name, event=event, tested=tested):
                self.assertEqual(scope.classify(self.repo, name, event, tested)["mode"], "full")
        with patch.object(scope, "git", side_effect=OSError("unavailable")):
            self.assertEqual(self.classify_with_known_sha(after)["mode"], "full")
        with patch.object(scope, "changes", side_effect=ValueError("bad raw record")):
            self.assertEqual(self.classify()["mode"], "full")

    def classify_with_known_sha(self, after):
        return scope.classify(self.repo, "push", {"before": self.base, "after": after}, after)

    def test_cli_classify_emits_plan_and_summary(self):
        self.write(JOURNAL, "prose\n")
        after = self.save()
        event = self.repo / "event.json"
        event.write_text(json.dumps({"before": self.base, "after": after}))
        output, summary = self.repo / "output", self.repo / "summary"
        env = dict(
            os.environ,
            GITHUB_EVENT_PATH=str(event),
            GITHUB_EVENT_NAME="push",
            GITHUB_SHA=after,
            GITHUB_OUTPUT=str(output),
            GITHUB_STEP_SUMMARY=str(summary),
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "classify"],
            cwd=self.repo,
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        emitted = json.loads(output.read_text().removeprefix("plan="))
        self.assertEqual(emitted["mode"], "docs")
        self.assertIn("Planned skips: quality", summary.read_text())
        env["GITHUB_EVENT_PATH"] = str(self.repo / "missing")
        subprocess.run(
            [sys.executable, str(SCRIPT), "classify"],
            cwd=self.repo,
            env=env,
            check=True,
            capture_output=True,
        )
        self.assertEqual(json.loads(output.read_text().splitlines()[-1][5:])["mode"], "full")


class GateTest(unittest.TestCase):
    def test_valid_docs_and_full(self):
        for mode in ["docs", "full"]:
            self.assertEqual(scope.decide(needs(mode))["mode"], mode)

    def test_every_wrong_heavy_result_or_missing_job_blocks(self):
        for mode in ["docs", "full"]:
            good = "skipped" if mode == "docs" else "success"
            for name in scope.HEAVY_JOBS:
                for result in {"success", "skipped", "failure", "cancelled", "", "unknown"} - {
                    good
                }:
                    with self.subTest(mode=mode, name=name, result=result):
                        data = needs(mode)
                        data[name]["result"] = result
                        with self.assertRaises(ValueError):
                            scope.decide(data)
                data = needs(mode)
                del data[name]
                with self.assertRaises(ValueError):
                    scope.decide(data)

    def test_contracts_failure_cancel_skip_and_missing_outputs_block(self):
        for result in ["failure", "cancelled", "skipped", "", "unknown"]:
            data = needs("docs")
            data["contracts"]["result"] = result
            with self.assertRaises(ValueError):
                scope.decide(data)
        for outputs in [
            {},
            {"plan": ""},
            {"plan": "null"},
            {"plan": "{}"},
            {"plan": json.dumps(plan("docs")), "unexpected": "x"},
        ]:
            data = needs("docs")
            data["contracts"]["outputs"] = outputs
            with self.assertRaises((ValueError, TypeError)):
                scope.decide(data)

    def test_bad_plans_modes_results_and_extra_jobs_block(self):
        for change in [
            {"mode": ""},
            {"mode": "other"},
            {"changed_count": 0},
            {"changed_count": True},
            {"base": "0" * 40},
            {"after": ""},
            {"reason": "unverified comparison"},
            {"unexpected": "value"},
        ]:
            data = needs("docs")
            value = plan("docs")
            value.update(change)
            data["contracts"]["outputs"]["plan"] = json.dumps(value)
            with self.assertRaises(ValueError):
                scope.decide(data)
        for data in [{}, None, {**needs(), "unexpected": {"result": "success"}}]:
            with self.assertRaises(ValueError):
                scope.decide(data)
        data = needs()
        data["quality"] = None
        with self.assertRaises(ValueError):
            scope.decide(data)

    def test_cli_gate_is_the_gate_used_by_workflow(self):
        for mode in ["docs", "full"]:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "gate"],
                env=dict(os.environ, RESULTS=json.dumps(needs(mode)), GITHUB_STEP_SUMMARY=""),
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"mode: {mode.upper()}", result.stdout)
        data = needs()
        data["postgres"]["result"] = "skipped"
        for value in [json.dumps(data), "{}", "invalid"]:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "gate"],
                env=dict(os.environ, RESULTS=value, GITHUB_STEP_SUMMARY=""),
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCKED", result.stdout)


class WorkflowWiringTest(unittest.TestCase):
    def test_exact_graph_conditions_and_shared_cli(self):
        workflow = yaml.load(
            (ROOT / ".github/workflows/backend.yml").read_text(), Loader=yaml.BaseLoader
        )
        self.assertEqual(
            workflow["on"], {"pull_request": {"branches": ["main"]}, "push": {"branches": ["main"]}}
        )
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), scope.JOBS | {"ci-required"})
        contracts = jobs["contracts"]
        self.assertNotIn("if", contracts)
        self.assertNotIn("needs", contracts)
        self.assertEqual(contracts["outputs"], {"plan": "${{ steps.scope.outputs.plan }}"})
        steps = contracts["steps"]
        self.assertEqual(steps[0]["with"], {"fetch-depth": "0"})
        runs = [step.get("run", "") for step in steps]
        self.assertIn("python backend/sync_catalog_schemas.py --check", runs)
        self.assertIn(
            "uv run --project tools/contracts --locked --offline "
            "python tools/contracts/validate.py",
            runs,
        )
        test_run = (
            "uv run --project tools/contracts --locked --offline "
            "python -m unittest discover -s tools/tests -p test_ci_scope.py -v"
        )
        self.assertIn(test_run, runs)
        self.assertEqual(steps[-1]["id"], "scope")
        self.assertEqual(steps[-1]["run"], "python tools/ci_scope.py classify")
        for step in steps:
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)
        for name in scope.HEAVY_JOBS:
            job = jobs[name]
            self.assertEqual(job["needs"], ["contracts"])
            self.assertEqual(
                job["if"],
                "${{ needs.contracts.result == 'success' && "
                "fromJSON(needs.contracts.outputs.plan).mode == 'full' }}",
            )
            self.assertNotIn("continue-on-error", job)
        gate = jobs["ci-required"]
        self.assertEqual(gate["if"], "always()")
        self.assertEqual(set(gate["needs"]), scope.JOBS)
        step = gate["steps"][-1]
        self.assertEqual(step["env"], {"RESULTS": "${{ toJSON(needs) }}"})
        self.assertEqual(step["run"], "python tools/ci_scope.py gate")
        self.assertNotIn("continue-on-error", step)
        # Exercise the same planned results the graph produces: no blanket accept-skipped.
        for mode in ["docs", "full"]:
            self.assertEqual(scope.decide(needs(mode))["mode"], mode)
        broken = needs("docs")
        broken["postgres"]["result"] = "cancelled"
        with self.assertRaises(ValueError):
            scope.decide(broken)


if __name__ == "__main__":
    unittest.main()
