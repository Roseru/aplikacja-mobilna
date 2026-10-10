"""Check real Android test reports and describe the APK built by CI."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def check_results(directory: Path, lint: Path | None = None) -> dict:
    reports = sorted(directory.rglob("TEST-*.xml"))
    if not reports:
        raise ValueError("Missing JUnit reports; no tests were verified")
    total = 0
    for report in reports:
        root = ET.parse(report).getroot()
        if root.tag not in {"testsuite", "testsuites"}:
            raise ValueError(f"Unsupported JUnit report: {report.name}")
        cases = list(root.iter("testcase"))
        if not cases:
            raise ValueError(f"Empty test report: {report.name}")
        for suite in root.iter("testsuite"):
            for field in ("failures", "errors", "skipped", "disabled"):
                if int(suite.get(field, "0")) != 0:
                    raise ValueError(f"Unsuccessful tests ({field}): {report.name}")
            direct_cases = suite.findall("testcase")
            if "tests" in suite.attrib and not suite.findall("testsuite"):
                if int(suite.attrib["tests"]) != len(direct_cases):
                    raise ValueError(f"Incomplete test report: {report.name}")
        for case in cases:
            if any(case.find(tag) is not None for tag in ("failure", "error", "skipped")):
                raise ValueError(f"Failed or skipped test: {report.name}")
        total += len(cases)
    summary = {"reports": len(reports), "tests": total, "failures": 0, "skipped": 0}
    if lint is not None:
        issues = ET.parse(lint).getroot()
        if issues.tag != "issues":
            raise ValueError("Unsupported lint report")
        severities = [issue.get("severity") for issue in issues.findall("issue")]
        if any(severity in {"Fatal", "Error"} for severity in severities):
            raise ValueError("Lint contains errors")
        summary["lint_warnings"] = severities.count("Warning")
        summary["lint_information"] = severities.count("Information")
    return summary


def package_apk(directory: Path, destination: Path, commit: str, aapt: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("APK must identify the exact tested Git commit")
    metadata = json.loads((directory / "output-metadata.json").read_text("utf-8"))
    elements = metadata["elements"]
    if metadata["variantName"] != "debug" or len(elements) != 1:
        raise ValueError("Expected a single debug APK")
    element = elements[0]
    filename = element["outputFile"]
    if not re.fullmatch(r"[0-9A-Za-z._-]+\.apk", filename):
        raise ValueError("Invalid APK filename")
    apk = directory / filename
    badging = subprocess.check_output([str(aapt), "dump", "badging", str(apk)], text=True)
    package = re.search(
        r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'",
        badging,
        re.MULTILINE,
    )
    if package is None or "application-debuggable" not in badging:
        raise ValueError("APK is not a readable debug application")
    app_id, code, version = package.groups()
    if (app_id, int(code), version) != (
        metadata["applicationId"],
        element["versionCode"],
        element["versionName"],
    ):
        raise ValueError("APK version does not match build metadata")
    if not re.fullmatch(r"[0-9A-Za-z._-]+", version):
        raise ValueError("Version cannot be used as an artifact filename")
    destination.mkdir(parents=True, exist_ok=True)
    name = f"Racje-i-kalorie-{version}-debug.apk"
    shipped = destination / name
    shutil.copyfile(apk, shipped)
    digest = hashlib.sha256(shipped.read_bytes()).hexdigest()
    manifest = {
        "application_id": app_id,
        "version_name": version,
        "version_code": int(code),
        "variant": "debug",
        "commit": commit,
        "apk": name,
        "sha256": digest,
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "SHA256SUMS").write_text(f"{digest}  {name}\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check")
    check.add_argument("--results", type=Path, required=True)
    check.add_argument("--lint", type=Path)
    check.add_argument("--output", type=Path, required=True)
    package = subcommands.add_parser("package")
    package.add_argument("--directory", type=Path, required=True)
    package.add_argument("--destination", type=Path, required=True)
    package.add_argument("--commit", required=True)
    package.add_argument("--aapt", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check":
        result = check_results(args.results, args.lint)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    else:
        result = package_apk(args.directory, args.destination, args.commit, args.aapt)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
