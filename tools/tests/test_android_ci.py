"""Regression checks for missing/skipped evidence and incorrectly labelled APKs."""

import json
import tempfile
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
                    {"outputFile": "app-debug.apk", "versionCode": 8, "versionName": "0.7.1"}
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


if __name__ == "__main__":
    unittest.main()
