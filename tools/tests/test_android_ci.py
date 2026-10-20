"""Regression checks for missing/skipped evidence and incorrectly labelled APKs."""

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.android_ci import check_results, package_apk


class AndroidCiTest(unittest.TestCase):
    def test_real_cases_are_required_and_skips_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with self.assertRaises(ValueError):
                check_results(directory)
            report = directory / "TEST-suite.xml"
            invalid_reports = [
                '<testsuite tests="0"/>',
                '<testsuite tests="2"><testcase name="one"/></testsuite>',
                '<testsuite tests="1" skipped="1"><testcase/></testsuite>',
                '<testsuite tests="1"><testcase><skipped/></testcase></testsuite>',
                '<testsuite tests="1"><testcase><failure/></testcase></testsuite>',
                '<testsuite tests="1"><testcase><error/></testcase></testsuite>',
            ]
            for xml in invalid_reports:
                with self.subTest(xml=xml):
                    report.write_text(xml, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        check_results(directory)
            report.write_text('<testsuite tests="1"><testcase/></testsuite>', "utf-8")
            lint = directory / "lint.xml"
            lint.write_text('<issues><issue severity="Warning"/></issues>', "utf-8")
            self.assertEqual(check_results(directory, lint)["tests"], 1)
            lint.write_text('<issues><issue severity="Error"/></issues>', "utf-8")
            with self.assertRaises(ValueError):
                check_results(directory, lint)

    def test_artifact_identifies_actual_apk_and_rejects_wrong_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            metadata = {
                "variantName": "debug",
                "applicationId": "pl.roseru.kalorie",
                "elements": [
                    {
                        "outputFile": "app-debug.apk",
                        "versionCode": 8,
                        "versionName": "0.7.1",
                    }
                ],
            }
            (directory / "output-metadata.json").write_text(json.dumps(metadata), "utf-8")
            (directory / "app-debug.apk").write_bytes(b"built APK fixture")
            badging = (
                "package: name='pl.roseru.kalorie' versionCode='8' versionName='0.7.1'\n"
                "application-debuggable\n"
            )
            with patch("tools.android_ci.subprocess.check_output", return_value=badging):
                destination = directory / "delivery"
                manifest = package_apk(directory, destination, "a" * 40, Path("aapt"))
                self.assertEqual(manifest["version_code"], 8)
                self.assertEqual(manifest["commit"], "a" * 40)
                self.assertEqual((destination / manifest["apk"]).read_bytes(), b"built APK fixture")
                self.assertIn(manifest["sha256"], (destination / "SHA256SUMS").read_text())
                metadata["elements"][0]["versionName"] = "0.7.2"
                (directory / "output-metadata.json").write_text(json.dumps(metadata), "utf-8")
                with self.assertRaises(ValueError):
                    package_apk(directory, destination, "a" * 40, Path("aapt"))
                with self.assertRaises(ValueError):
                    package_apk(directory, destination, "main", Path("aapt"))


@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "Linux CI shell regression")
class AndroidBuildDiagnosticsTest(unittest.TestCase):
    def test_validation_failure_blocks_build_even_when_debug_report_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "gradlew"
            wrapper.write_text(
                "#!/bin/sh\n"
                "mkdir -p app/build/test-results/testDebugUnitTest\n"
                'echo \'<testsuite tests="1"><testcase name="debug"/></testsuite>\' '
                "> app/build/test-results/testDebugUnitTest/TEST-debug.xml\n"
                'for task in "$@"; do\n'
                '  if [ "$task" = ":app:testValidationUnitTest" ]; then\n'
                "    echo fixture-validation-failure >&2\n"
                "    exit 29\n"
                "  fi\n"
                "done\n"
                "exit 0\n"
            )
            wrapper.chmod(0o755)
            script = Path(__file__).resolve().parents[1] / "android_build.sh"
            result = subprocess.run(
                ["bash", script.as_posix()],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 29, result.stdout + result.stderr)
            self.assertEqual(
                check_results(root / "app/build/test-results/testDebugUnitTest")["tests"],
                1,
            )
            log = (root / "app/build/ci/gradle-build.log").read_text()
            self.assertIn("fixture-validation-failure", log)

    def test_configuration_failure_keeps_log_and_nonzero_status_without_xml(self):
        self.run_build_script(23)

    def test_success_keeps_both_output_streams_without_creating_test_evidence(self):
        self.run_build_script(0)

    def run_build_script(self, status):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "gradlew"
            wrapper.write_text(
                "#!/bin/sh\necho fixture-stdout\necho fixture-stderr >&2\n"
                "echo call >> calls\nexit " + str(status) + "\n"
            )
            wrapper.chmod(0o755)
            script = Path(__file__).resolve().parents[1] / "android_build.sh"
            result = subprocess.run(
                ["bash", str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, status, result.stderr)
            log = (root / "app/build/ci/gradle-build.log").read_text()
            self.assertIn("fixture-stdout", log)
            self.assertIn("fixture-stderr", log)
            self.assertEqual((root / "calls").read_text().splitlines(), ["call"])
            self.assertFalse(list(root.rglob("TEST-*.xml")))


@unittest.skipUnless(os.name != "nt" and shutil.which("bash"), "Linux CI shell regression")
class AndroidDeviceStartupTest(unittest.TestCase):
    def run_device_script(
        self, ready_after, command_failure="none", gradle_status=0, offline_glitch="none"
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            device = root / "android"
            device.mkdir()
            binaries = root / "bin"
            binaries.mkdir()
            stub = textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, os, sys
                from pathlib import Path
                state = Path(os.environ["DEVICE_STUB_STATE"])
                args = sys.argv[1:]
                with (state / "commands.jsonl").open("a") as output:
                    output.write(json.dumps(args) + "\\n")
                if args[:3] == ["shell", "service", "check"]:
                    service = args[3]
                    count_file = state / "phone-attempts"
                    count = int(count_file.read_text()) if count_file.exists() else 0
                    if service == "phone":
                        count += 1
                        count_file.write_text(str(count))
                    found = service != "phone" or count >= int(os.environ["DEVICE_READY_AFTER"])
                    print("Service " + service + (": found" if found else ": not found"))
                elif args == ["shell", "getprop", "sys.boot_completed"]:
                    print("1")
                elif args == ["shell", "cmd", "connectivity", "airplane-mode", "disable"]:
                    count = int((state / "phone-attempts").read_text())
                    if count < int(os.environ["DEVICE_READY_AFTER"]):
                        print("cmd: Can't find service: phone", file=sys.stderr)
                        raise SystemExit(20)
                elif args == ["shell", "svc", "data", "disable"]:
                    counter = state / "data-attempts"
                    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
                    counter.write_text(str(attempt))
                    mode = os.environ["DEVICE_COMMAND_FAILURE"]
                    if mode == "permanent" or (mode == "once" and attempt == 1):
                        raise SystemExit(1)
                elif args[:4] == ["shell", "settings", "get", "global"]:
                    print("1" if args[-1] == "airplane_mode_on" else "0")
                elif args == ["shell", "cmd", "wifi", "status"]:
                    print("Wifi is disabled")
                elif args == ["shell", "dumpsys", "connectivity"]:
                    counter = state / "connectivity-probes"
                    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
                    counter.write_text(str(attempt))
                    mode = os.environ["DEVICE_OFFLINE_GLITCH"]
                    glitch = ((mode == "once" and attempt == 2)
                              or (mode == "permanent" and attempt % 2 == 0)
                              or (mode == "after" and (state / "android/test-executed").exists()))
                    print("Active default network: " + ("123" if glitch else "none"))
                """)
            (binaries / "adb").write_text(stub)
            (binaries / "adb").chmod(0o755)
            (binaries / "sleep").write_text("#!/bin/sh\nexit 0\n")
            (binaries / "sleep").chmod(0o755)
            (device / "gradlew").write_text(
                "#!/bin/sh\ntouch test-executed\necho fixture-gradle-diagnostic >&2\n"
                'printf \'["gradle"]\\n\' >> "$DEVICE_STUB_STATE/commands.jsonl"\n'
                "exit " + str(gradle_status) + "\n"
            )
            (device / "gradlew").chmod(0o755)
            script = Path(__file__).resolve().parents[1] / "android_device_test.sh"
            result = subprocess.run(
                ["bash", str(script)],
                check=False,
                cwd=device,
                capture_output=True,
                text=True,
                env=os.environ
                | {
                    "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                    "ANDROID_SERIAL": "emulator-5554",
                    "DEVICE_STUB_STATE": str(root),
                    "DEVICE_READY_AFTER": str(ready_after),
                    "DEVICE_COMMAND_FAILURE": command_failure,
                    "DEVICE_OFFLINE_GLITCH": offline_glitch,
                },
                timeout=30,
            )
            return (
                result,
                (device / "test-executed").exists(),
                (device / "app/build/ci/startup-services.txt").read_text()
                + (device / "app/build/ci/setup-status.txt").read_text()
                + (
                    (device / "app/build/ci/setup-attempts.txt").read_text()
                    if (device / "app/build/ci/setup-attempts.txt").exists()
                    else ""
                )
                + (
                    (device / "app/build/ci/gradle-device.log").read_text()
                    if (device / "app/build/ci/gradle-device.log").exists()
                    else ""
                ),
                [json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()],
            )

    def test_boot_completed_before_phone_waits_then_runs_real_script(self):
        result, executed, diagnostics, commands = self.run_device_script(3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(executed)
        self.assertIn("Service phone: found", diagnostics)
        policy_index = commands.index(["shell", "cmd", "connectivity", "airplane-mode", "disable"])
        phone_probes = [
            c for c in commands[:policy_index] if c == ["shell", "service", "check", "phone"]
        ]
        self.assertGreaterEqual(len(phone_probes), 3)

    def test_missing_phone_fails_without_running_tests_and_keeps_diagnostics(self):
        result, executed, diagnostics, commands = self.run_device_script(100000)
        self.assertEqual(result.returncode, 20, result.stderr)
        self.assertFalse(executed)
        self.assertIn("Service phone: not found", diagnostics)
        self.assertNotIn(["shell", "cmd", "connectivity", "airplane-mode", "disable"], commands)

    def test_registered_service_with_transient_command_failure_waits_before_tests(self):
        result, executed, diagnostics, commands = self.run_device_script(1, "once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(executed)
        self.assertEqual(commands.count(["shell", "svc", "data", "disable"]), 2)
        self.assertIn("stage=complete", diagnostics)

    def test_permanent_offline_setup_failure_never_runs_application_tests(self):
        result, executed, diagnostics, commands = self.run_device_script(1, "permanent")
        self.assertEqual(result.returncode, 21, result.stderr)
        self.assertFalse(executed)
        self.assertEqual(commands.count(["shell", "svc", "data", "disable"]), 30)
        self.assertIn("stage=data_disable", diagnostics)

    def test_gradle_failure_keeps_dependency_error_and_is_not_a_pass(self):
        result, executed, diagnostics, _ = self.run_device_script(1, gradle_status=23)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertTrue(executed)
        self.assertIn("fixture-gradle-diagnostic", diagnostics)
        self.assertIn("stage=application_tests", diagnostics)
        self.assertIn("exit_code=23", diagnostics)
        self.assertNotIn("stage=complete", diagnostics)

    def test_connectivity_change_after_first_pass_retries_setup_before_one_test_run(self):
        result, executed, diagnostics, commands = self.run_device_script(1, offline_glitch="once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(executed)
        self.assertIn("stage=offline_settling result=not_ready", diagnostics)
        self.assertEqual(commands.count(["shell", "svc", "data", "disable"]), 2)
        self.assertEqual(commands.count(["gradle"]), 1)
        self.assertIn("stage=complete", diagnostics)

    def test_permanently_unstable_offline_state_never_runs_gradle(self):
        result, executed, diagnostics, commands = self.run_device_script(
            1, offline_glitch="permanent"
        )
        self.assertEqual(result.returncode, 21, result.stderr)
        self.assertFalse(executed)
        self.assertEqual(commands.count(["shell", "svc", "data", "disable"]), 30)
        self.assertEqual(commands.count(["gradle"]), 0)
        self.assertIn("stage=offline_settling", diagnostics)

    def test_network_restored_by_tests_fails_immediately_without_repeating_them(self):
        result, executed, diagnostics, commands = self.run_device_script(1, offline_glitch="after")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertTrue(executed)
        self.assertEqual(commands.count(["gradle"]), 1)
        self.assertEqual(commands.count(["shell", "svc", "data", "disable"]), 1)
        self.assertIn("stage=offline_after_tests", diagnostics)


if __name__ == "__main__":
    unittest.main()
