"""Inspect one pinned four-APK delivery offline; never install or accept Android/live E4."""

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import tempfile
import threading
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from cryptography import x509

ROLES = ("debug", "validation-configured", "test-default", "test-liveReplay-optin")
APP_ROLES = ROLES[:2]
DRIVER = b"Lpl/roseru/kalorie/LiveMealReplayTest"
OTHER_DRIVER = b"Lpl/roseru/kalorie/LiveApiLateReceiptTest"
MAX_JSON = 1024**2
MAX_APK = 256 * 1024**2
MAX_DEX = 64 * 1024**2
MAX_OUTPUT = 16 * 1024**2


class Unchecked(ValueError):
    """Inspection is incomplete; its input/diagnostic text must not leak to the report."""


def require(condition, reason):
    if not condition:
        raise Unchecked(reason)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def no_redirects(path):
    require(
        all(part in {".", ".."} or not part.endswith((".", " ")) for part in Path(path).parts),
        "ambiguous Windows path spelling",
    )
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), "redirected path refused")
    return path


def regular(path, limit=None):
    path = no_redirects(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode), "input must be a regular file")
    if limit is not None:
        require(0 < info.st_size <= limit, "input size outside inspection limit")
    return path.resolve(strict=True)


def output_path(path):
    path = no_redirects(path)
    require(not path.exists(), "report already exists; no existing file overwritten")
    require(path.parent.is_dir(), "report parent must already exist")
    require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json", path.name)),
        "report requires a plain JSON filename",
    )
    require(not reserved_name(path.name), "reserved output filename")
    return path


def write_report(output, report):
    """Publish a complete, fsynced report exclusively; no partial PASS file on I/O failure."""
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor, name = tempfile.mkstemp(prefix=".apk-static-", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        output_path(output)
        os.link(
            temporary, output
        )  # Exclusive publication on NTFS/POSIX; never replace a link/file.
    finally:
        temporary.unlink()


def reserved_name(name):
    return bool(re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", name.split(".")[0], re.I))


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def reject_constant(_):
    raise Unchecked("nonfinite JSON value")


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


def bounded_read(path, limit):
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "input exceeds inspection limit")
    return raw


def keys(value, expected):
    require(
        type(value) is dict and set(value) == set(expected.split()), "incomplete/unknown fields"
    )


def hex_value(value, length):
    require(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value),
        "expected a full lowercase hexadecimal identity",
    )


def positive(value):
    require(type(value) is int and value > 0, "expected a positive integer")


def identifier(value):
    require(
        isinstance(value, str) and re.fullmatch(r"[A-Za-z]\w*(?:\.[A-Za-z]\w*)+", value),
        "invalid application/runner identity",
    )


def entry_path(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]*", value)
        and not PurePosixPath(value).is_absolute()
        and all(part not in {"", ".", ".."} for part in value.split("/")),
        "invalid APK entry path",
    )


def endpoints(value, *, empty=False):
    keys(value, "api_base_url oidc_issuer")
    if empty and value == {"api_base_url": "", "oidc_issuer": ""}:
        return set()
    hosts = set()
    for name, url in value.items():
        require(isinstance(url, str) and len(url) <= 2048, "invalid expected HTTPS endpoint")
        parsed = urlsplit(url)
        require(
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and "?" not in url
            and "#" not in url
            and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in url),
            "expected HTTPS without credentials/query/fragment",
        )
        require(parsed.port is None or 1 <= parsed.port <= 65535, "invalid endpoint port")
        if name == "api_base_url":
            require(parsed.path in {"/api/v1", "/api/v1/"}, "API endpoint requires /api/v1")
        hosts.add(parsed.hostname)
    return hosts


def manifest_contract(value, source_commit, android_tree):
    keys(value, "schema_version source configuration artifacts")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "unknown schema")
    source = value["source"]
    keys(source, "commit android_tree room")
    for candidate in (source["commit"], source["android_tree"], source_commit, android_tree):
        hex_value(candidate, 40)
    positive(source["room"])
    require(
        source["commit"] == source_commit and source["android_tree"] == android_tree,
        "delivery differs from independently pinned source/tree",
    )
    config = value["configuration"]
    keys(config, "api_base_url oidc_issuer ca_sha256 ca_entry network_xml_entry")
    endpoints({key: config[key] for key in ("api_base_url", "oidc_issuer")})
    hex_value(config["ca_sha256"], 64)
    for key in ("ca_entry", "network_xml_entry"):
        entry_path(config[key])
    require(config["ca_entry"] != config["network_xml_entry"], "CA and policy must differ")
    records = value["artifacts"]
    require(type(records) is list and len(records) == 4, "exactly four APK roles required")
    by_role = {}
    for record in records:
        keys(
            record,
            "role filename bytes sha256 signer_sha256 application_id version_code version_name "
            "endpoints instrumentation",
        )
        role = record["role"]
        require(
            isinstance(role, str) and role in ROLES and role not in by_role, "ambiguous APK roles"
        )
        by_role[role] = record
        filename = record["filename"]
        require(
            isinstance(filename, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.apk", filename),
            "APK requires a plain filename",
        )
        require(not reserved_name(filename), "reserved APK filename")
        positive(record["bytes"])
        require(record["bytes"] <= MAX_APK, "APK size exceeds inspection limit")
        for field in ("sha256", "signer_sha256"):
            hex_value(record[field], 64)
        identifier(record["application_id"])
        if record["version_code"] is not None:
            positive(record["version_code"])
        if record["version_name"] is not None:
            require(
                isinstance(record["version_name"], str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", record["version_name"]),
                "invalid expected version name",
            )
        if role in APP_ROLES:
            positive(record["version_code"])
            require(record["version_name"] is not None, "app version name is required")
            endpoints(record["endpoints"], empty=role == "debug")
            require(record["instrumentation"] is None, "application cannot be instrumentation")
        else:
            require(record["endpoints"] is None, "test APK config belongs to its explicit target")
            instrumentation = record["instrumentation"]
            keys(instrumentation, "target_role target_package runner")
            require(
                instrumentation["target_role"] in APP_ROLES, "unknown instrumentation target role"
            )
            identifier(instrumentation["target_package"])
            identifier(instrumentation["runner"])
    for field in ("filename", "sha256"):
        require(len({r[field].casefold() for r in records}) == 4, "aliased/identical APK roles")
    require(
        by_role["validation-configured"]["endpoints"]
        == {key: config[key] for key in ("api_base_url", "oidc_issuer")},
        "validation endpoints differ from delivery configuration",
    )
    require(
        by_role["debug"]["endpoints"]
        in (
            {"api_base_url": "", "oidc_issuer": ""},
            by_role["validation-configured"]["endpoints"],
        ),
        "regular debug must be unconfigured or use the same delivery endpoints",
    )
    application_ids = {by_role[role]["application_id"] for role in APP_ROLES}
    require(len(application_ids) == 2, "regular and validation application must differ")
    for role in ROLES[2:]:
        test = by_role[role]
        pair = test["instrumentation"]
        if role == "test-liveReplay-optin":
            require(
                pair["target_role"] == "validation-configured",
                "liveReplay must target the configured validation application",
            )
        target = by_role[pair["target_role"]]
        require(pair["target_package"] == target["application_id"], "target pair identity mismatch")
        require(test["application_id"] not in application_ids, "test and application must differ")
        require(test["signer_sha256"] == target["signer_sha256"], "test/target signer mismatch")
    return by_role


def command(arguments, cwd, *, limit=MAX_OUTPUT, timeout=30):
    """Drain both pipes with hard bounds; never print/persist raw tool diagnostics."""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    env = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH"):
        env.pop(key, None)
    with subprocess.Popen(
        arguments,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **options,
    ) as process:
        chunks = []
        exceeded = threading.Event()

        def drain(pipe, bound, keep):
            total = 0
            while block := pipe.read(65536):
                total += len(block)
                if total > bound:
                    exceeded.set()
                    process.kill()
                    break
                if keep:
                    chunks.append(block)

        threads = [
            threading.Thread(target=drain, args=(process.stdout, limit, True), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, MAX_JSON, False), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            for thread in threads:
                thread.join(timeout=2)
        require(not any(t.is_alive() for t in threads), "inspection pipe did not close")
        require(not exceeded.is_set(), "inspection output exceeds limit")
        require(process.returncode == 0, "inspection tool failed; raw output discarded")
    return b"".join(chunks).decode("utf-8", errors="strict").replace("\r\n", "\n")


class Inspector:
    def __init__(self, aapt, java, apksigner_jar, git):
        self.paths = [regular(p) for p in (aapt, java, apksigner_jar, git)]
        if os.name == "nt":
            require(
                all(p.suffix.lower() == ".exe" for p in self.paths[:2] + self.paths[3:]),
                "native inspection executables required",
            )

    def aapt(self, apk, *args):
        # Legacy aapt on Windows cannot open Polish absolute APK paths. Never copy the APK.
        return command([str(self.paths[0]), "dump", *args, apk.name], apk.parent)

    def xml(self, apk, entry):
        return xml_nodes(
            command(
                [str(self.paths[0]), "dump", "xmltree", apk.name, entry],
                apk.parent,
            )
        )

    def signers(self, apk):
        output = command(
            [
                str(self.paths[1]),
                "-jar",
                str(self.paths[2]),
                "verify",
                "--verbose",
                "--print-certs",
                apk.name,
            ],
            apk.parent,
        )
        return re.findall(
            r"^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$",
            output,
            re.M,
        )

    def source(self, checkout, source):
        git = str(self.paths[3])

        def read(spec):
            return command([git, "--no-pager", "show", spec], checkout, limit=MAX_JSON)

        tree = command(
            [git, "rev-parse", source["commit"] + ":android"],
            checkout,
            limit=MAX_JSON,
        ).strip()
        require(tree == source["android_tree"], "Git android tree differs from source pin")
        gradle = read(source["commit"] + ":android/app/build.gradle.kts")
        database = read(
            source["commit"] + ":android/app/src/main/java/pl/roseru/kalorie/data/Database.kt"
        )
        schema = parse_json(
            read(
                source["commit"]
                + ":android/app/schemas/pl.roseru.kalorie.data.CalorieDatabase/"
                + str(source["room"])
                + ".json",
            )
        )
        return source_declarations(gradle, database, schema, source["room"])


def source_declarations(gradle, database, schema, room):
    """Known repository profile only, not an evaluator of arbitrary Gradle/Kotlin code."""
    gradle = re.sub(r"(?m)^\s*//.*$", "", gradle)

    def one(pattern):
        matches = re.findall(pattern, gradle)
        require(len(matches) == 1, "unsupported/ambiguous source variant declaration")
        return matches[0]

    app = one(r'\bapplicationId\s*=\s*"([\w.]+)"')
    version = one(r'\bversionName\s*=\s*"([\w.-]+)"')
    code = int(one(r"\bversionCode\s*=\s*([0-9]+)"))
    suffix = one(r'\bapplicationIdSuffix\s*=\s*"([\w.]+)"')
    target_sdk = int(one(r"\btargetSdk\s*=\s*([0-9]+)"))
    default_test_type = one(r'\btestBuildType\s*=\s*"(debug|validation)"')
    runner = one(r'\btestInstrumentationRunner\s*=\s*"([\w.]+)"')
    offset = int(one(r"output\.versionCode\.set\(([0-9]+)\s*\+\s*checkNotNull"))
    version_suffix = one(r'output\.versionName\.set\(checkNotNull\([^)]*\)\s*\+\s*"([\w.-]+)"')
    require('create("validation")' in gradle, "validation build type missing")
    flag = re.sub(r"\s+", "", gradle)
    require(
        'if(providers.gradleProperty("O1_LIVE_E4_REPLAY_TEST").orElse("false").get()=="true")'
        '{sourceSets.getByName("androidTest").java.srcDir("src/liveReplay/java")}' in flag,
        "known opt-in liveReplay source gate missing",
    )
    rooms = re.findall(r"\bversion\s*=\s*([0-9]+)\s*,\s*exportSchema\s*=\s*true", database)
    require(rooms == [str(room)] and schema["database"]["version"] == room, "source Room mismatch")
    return {
        "debug": {"application_id": app, "version_code": code, "version_name": version},
        "validation-configured": {
            "application_id": app + suffix,
            "version_code": code + offset,
            "version_name": version + version_suffix,
        },
        "target_sdk": target_sdk,
        "default_test_build_type": default_test_type,
        "runner": runner,
        "room": room,
    }


# These compiled-resource/XML/trust checks preserve the private O3 preflight profile.
def resource(table, name):
    pattern = re.compile(r"(?m)^\s*resource (0x[0-9a-fA-F]+) [^:\s]+:" + re.escape(name) + r":.*$")
    records = []
    for match in pattern.finditer(table):
        following = table[match.end() :].lstrip("\n").splitlines()[0]
        value = re.fullmatch(r'\s*\((?:string8|string16)\) (".*")\s*', following)
        require(value is not None, "unsupported compiled resource representation")
        parsed = json.loads(value[1])
        require(isinstance(parsed, str), "resource is not a compiled string")
        records.append((match[1].lower(), parsed))
    require(len({r[0] for r in records}) <= 1, "ambiguous compiled resource identity")
    return records


def xml_nodes(dump):
    roots, stack = [], []
    for line in dump.splitlines():
        element = re.match(r"^(\s*)E: ([^\s]+)", line)
        if element:
            depth = len(element[1])
            node = {"name": element[2], "attrs": {}, "children": [], "text": []}
            while stack and stack[-1][0] >= depth:
                stack.pop()
            (stack[-1][1]["children"] if stack else roots).append(node)
            stack.append((depth, node))
        elif line.lstrip().startswith("A:"):
            attr = re.match(r"\s*A: ([\w:.-]+)(?:\(0x[0-9a-fA-F]+\))?=(.*)$", line)
            require(bool(stack) and attr is not None, "unsupported XML attribute")
            require(attr[1] not in stack[-1][1]["attrs"], "duplicate XML attribute")
            stack[-1][1]["attrs"][attr[1]] = attr[2]
        elif line.lstrip().startswith("C:"):
            require(bool(stack), "XML text without element")
            stack[-1][1]["text"].append(json.loads(line.split("C:", 1)[1].strip()))
    require(len(roots) == 1, "ambiguous XML root")
    return roots[0]


def false_value(value):
    return bool(re.fullmatch(r"\(type 0x12\)0x0", value or ""))


def string_value(value):
    try:
        result, _ = json.JSONDecoder().raw_decode(value or "")
        return result if isinstance(result, str) else None
    except ValueError:
        return None


def integer_value(value):
    match = re.fullmatch(r"\(type 0x1[01]\)0x([0-9a-fA-F]+)", value or "")
    require(match is not None, "unsupported compiled integer")
    return int(match[1], 16)


def strict_trust(root, ca_id, hosts):
    require(root["name"] == "network-security-config", "unknown network policy root")
    if root["attrs"] or root["text"]:
        return False
    bases = [n for n in root["children"] if n["name"] == "base-config"]
    domains = [n for n in root["children"] if n["name"] == "domain-config"]
    if len(bases) != 1 or len(bases) + len(domains) != len(root["children"]):
        return False

    def anchors(node, expected):
        children = [c for c in node["children"] if c["name"] == "trust-anchors"]
        if len(children) != 1 or children[0]["attrs"] or children[0]["text"]:
            return False
        certs = children[0]["children"]
        return (
            len(certs) == 1
            and certs[0]["name"] == "certificates"
            and set(certs[0]["attrs"]) == {"src"}
            and not certs[0]["children"]
            and not certs[0]["text"]
            and expected(certs[0]["attrs"]["src"])
        )

    def denies_cleartext(node):
        return (
            set(node["attrs"]) == {"cleartextTrafficPermitted"}
            and false_value(node["attrs"]["cleartextTrafficPermitted"])
            and not node["text"]
        )

    base = bases[0]
    if (
        not denies_cleartext(base)
        or [n["name"] for n in base["children"]] != ["trust-anchors"]
        or not anchors(base, lambda v: string_value(v) == "system")
    ):
        return False
    found = []
    for domain in domains:
        if (
            not denies_cleartext(domain)
            or ca_id is None
            or not anchors(domain, lambda v: v.lower() == "@" + ca_id)
            or any(n["name"] not in {"domain", "trust-anchors"} for n in domain["children"])
        ):
            return False
        items = [n for n in domain["children"] if n["name"] == "domain"]
        if not items:
            return False
        for item in items:
            if (
                set(item["attrs"]) != {"includeSubdomains"}
                or not false_value(item["attrs"]["includeSubdomains"])
                or item["children"]
                or len(item["text"]) != 1
            ):
                return False
            found.append(item["text"][0])
    return len(found) == len(set(found)) and set(found) == hosts


def dex_classes(raw):
    """Read class_defs -> type_ids -> string_ids, not arbitrary DEX string occurrences.

    Profile: little endian standard DEX 035/037/038/039/040, 112-byte header.
    This is a bounded definition-index reader, not a bytecode verifier/interpreter.
    """
    require(112 <= len(raw) <= MAX_DEX, "DEX size outside limit")
    require(re.fullmatch(rb"dex\n0(?:35|37|38|39|40)\x00", raw[:8]), "unsupported DEX version")
    require(
        struct.unpack_from("<III", raw, 32) == (len(raw), 112, 0x12345678), "invalid DEX header"
    )

    def table(offset, width):
        count, start = struct.unpack_from("<II", raw, offset)
        require(
            count <= 1_000_000 and (start == 0 if count == 0 else start >= 112), "invalid DEX table"
        )
        require(start + count * width <= len(raw), "DEX table out of bounds")
        return count, start

    strings, string_start = table(56, 4)
    types, type_start = table(64, 4)
    count, class_start = table(96, 32)
    result = set()
    for index in range(count):
        type_index = struct.unpack_from("<I", raw, class_start + index * 32)[0]
        require(type_index < types, "DEX class type out of bounds")
        string_index = struct.unpack_from("<I", raw, type_start + type_index * 4)[0]
        require(string_index < strings, "DEX descriptor index out of bounds")
        offset = struct.unpack_from("<I", raw, string_start + string_index * 4)[0]
        require(112 <= offset < len(raw), "DEX string out of bounds")
        for _byte in range(5):
            require(offset < len(raw), "truncated DEX string length")
            value = raw[offset]
            offset += 1
            if value < 128:
                break
        else:
            raise Unchecked("invalid DEX string length")
        end = raw.find(b"\0", offset, offset + 4096)
        require(end >= 0, "unterminated/oversize DEX class descriptor")
        descriptor = raw[offset:end]
        require(
            descriptor.startswith(b"L") and descriptor.endswith(b";"),
            "invalid DEX class descriptor",
        )
        require(descriptor not in result, "duplicate DEX class definition")
        result.add(descriptor)
    return result


def archive_evidence(apk, config, ca):
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        require(
            len(names) <= 100_000 and len(names) == len(set(names)), "ambiguous/oversize APK ZIP"
        )
        dex = [n for n in names if re.fullmatch(r"classes(?:[2-9]|[1-9][0-9]+)?\.dex", n)]
        require("classes.dex" in dex, "APK contains no primary DEX")
        require(
            not any(n.endswith(".dex") and n not in dex for n in names), "unsupported embedded DEX"
        )
        require(
            sum(archive.getinfo(n).file_size for n in dex) <= MAX_APK, "DEX total exceeds limit"
        )
        definitions = set()
        for name in dex:
            info = archive.getinfo(name)
            require(
                info.file_size <= MAX_DEX
                and not info.flag_bits & 1
                and info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                "unreadable/oversize DEX",
            )
            with archive.open(info) as stream:
                raw = stream.read(MAX_DEX + 1)
            found = dex_classes(raw)
            require(not definitions.intersection(found), "duplicate multidex class definition")
            definitions.update(found)
        embedded_ca = False
        if config["ca_entry"] in names:
            require(
                archive.getinfo(config["ca_entry"]).file_size <= MAX_JSON, "CA entry exceeds limit"
            )
            with archive.open(config["ca_entry"]) as stream:
                embedded_ca = stream.read(MAX_JSON + 1) == ca
        return definitions, embedded_ca


def compiled_package(root):
    require(root["name"] == "manifest", "compiled manifest root missing")
    attrs = root["attrs"]
    require(
        "android:versionCodeMajor" not in attrs
        or integer_value(attrs["android:versionCodeMajor"]) == 0,
        "extended version code is outside this delivery profile",
    )
    app_id = string_value(attrs.get("package"))
    identifier(app_id)
    code = integer_value(attrs["android:versionCode"]) if "android:versionCode" in attrs else None
    version = string_value(attrs["android:versionName"]) if "android:versionName" in attrs else None
    require(
        "android:versionName" not in attrs or version is not None,
        "unsupported compiled version name",
    )
    return {"application_id": app_id, "version_code": code, "version_name": version}


def check(report, role, name, passed):
    report["checks"].append({"role": role, "name": name, "status": "PASS" if passed else "FAIL"})


def inspect_apk(report, role, record, apk, inspector, config, ca, source):
    check(report, role, "apk_bytes", apk.stat().st_size == record["bytes"])
    check(report, role, "apk_sha256", digest(apk) == record["sha256"])
    signers = [s.lower() for s in inspector.signers(apk)]
    check(report, role, "verified_single_signer", signers == [record["signer_sha256"]])
    root = inspector.xml(apk, "AndroidManifest.xml")
    observed = compiled_package(root)
    check(report, role, "compiled_package_version", observed == {k: record[k] for k in observed})
    instruments = [n for n in root["children"] if n["name"] == "instrumentation"]
    if role in APP_ROLES:
        check(report, role, "no_instrumentation", not instruments)
    else:
        expected = record["instrumentation"]
        check(
            report,
            role,
            "instrumentation_pair",
            len(instruments) == 1
            and string_value(instruments[0]["attrs"].get("android:targetPackage"))
            == expected["target_package"]
            and string_value(instruments[0]["attrs"].get("android:name")) == expected["runner"],
        )
    definitions, embedded_ca = archive_evidence(apk, config, ca)
    replay = {d for d in definitions if d.startswith((DRIVER + b";", DRIVER + b"$"))}
    other = {d for d in definitions if d.startswith((OTHER_DRIVER + b";", OTHER_DRIVER + b"$"))}
    check(
        report,
        role,
        "driver_definitions",
        (DRIVER + b";" in replay if role == ROLES[3] else not replay) and not other,
    )
    report["artifacts"].append(
        {
            "role": role,
            "sha256": digest(apk),
            "bytes": apk.stat().st_size,
            "replay_driver_defined": DRIVER + b";" in replay,
        }
    )
    if role not in APP_ROLES:
        return
    apps = [n for n in root["children"] if n["name"] == "application"]
    sdk = [n for n in root["children"] if n["name"] == "uses-sdk"]
    require(len(apps) == len(sdk) == 1, "ambiguous application/SDK manifest")
    app = apps[0]
    target = integer_value(sdk[0]["attrs"].get("android:targetSdkVersion"))
    check(report, role, "source_target_sdk", target == source["target_sdk"] and target >= 24)
    check(
        report,
        role,
        "debuggable_variant",
        app["attrs"].get("android:debuggable") == "(type 0x12)0xffffffff",
    )
    check(
        report,
        role,
        "manifest_cleartext",
        false_value(app["attrs"].get("android:usesCleartextTraffic")),
    )
    table = inspector.aapt(apk, "--values", "resources")
    for name, expected in record["endpoints"].items():
        values = resource(table, "string/" + name)
        check(
            report, role, "compiled_" + name, bool(values) and all(v == expected for _, v in values)
        )
    network = resource(table, "xml/o3_network_security")
    raw_ca = resource(table, "raw/o3_local_ca")
    binding = app["attrs"].get("android:networkSecurityConfig")
    if role == "debug":
        # Android >=24 defaults to system CAs only; reject any uninspected override.
        check(report, role, "system_trust_only", binding is None and not network and not raw_ca)
        check(report, role, "no_validation_ca", not embedded_ca)
        return
    network_ok = bool(network) and all(v == config["network_xml_entry"] for _, v in network)
    ca_ok = bool(raw_ca) and all(v == config["ca_entry"] for _, v in raw_ca)
    check(report, role, "network_resource", network_ok)
    check(report, role, "ca_resource", ca_ok)
    check(report, role, "embedded_ca_bytes", embedded_ca)
    bound = network_ok and binding is not None and binding.lower() == "@" + network[0][0]
    check(report, role, "manifest_network_binding", bound)
    trust = False
    if bound and ca_ok:
        policy = inspector.xml(apk, config["network_xml_entry"])
        trust = strict_trust(policy, raw_ca[0][0], endpoints(record["endpoints"]))
    check(report, role, "strict_network_trust", trust)


def inspect_delivery(
    manifest,
    *,
    expected_manifest_sha256,
    source_commit,
    android_tree,
    checkout,
    ca,
    inspector,
    report_path=None,
):
    report = {
        "scope": "STATIC_FOUR_APK_ONLY",
        "result": "STATIC_BLOCKED",
        "checks": [],
        "artifacts": [],
        "observed_at": datetime.now(UTC).isoformat(),
        "android_acceptance": "NOT_CREATED",
        "live_trial": "NOT_RUN",
        "room_runtime": "NOT_CHECKED",
        "driver_execution": "NOT_RUN",
        "runtime_tls_chain": "NOT_CHECKED",
        "deployment_authorized": False,
        "apk_source_provenance": "DECLARED_NOT_REPRODUCED",
    }
    try:
        output = output_path(report_path) if report_path is not None else None
        manifest = regular(manifest, MAX_JSON)
        ca = regular(ca, MAX_JSON)
        hex_value(expected_manifest_sha256, 64)
        manifest_bytes = bounded_read(manifest, MAX_JSON)
        require(
            hashlib.sha256(manifest_bytes).hexdigest() == expected_manifest_sha256,
            "expected manifest hash mismatch",
        )
        spec = parse_json(manifest_bytes.decode("utf-8", errors="strict"))
        records = manifest_contract(spec, source_commit, android_tree)
        config = spec["configuration"]
        paths = {
            role: regular(manifest.parent / r["filename"], MAX_APK) for role, r in records.items()
        }
        inputs = [manifest, ca, *paths.values(), *inspector.paths]
        require(
            len({(p.stat().st_dev, p.stat().st_ino) for p in inputs}) == len(inputs),
            "aliased input roles",
        )
        before = {p: digest(p) for p in inputs}
        require(before[manifest] == expected_manifest_sha256, "manifest changed during preparation")
        ca_bytes = bounded_read(ca, MAX_JSON)
        require(
            re.fullmatch(
                rb"\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+"
                rb"-----END CERTIFICATE-----\s*",
                ca_bytes,
            ),
            "expected one public CA certificate without private keys",
        )
        certificate = x509.load_pem_x509_certificate(ca_bytes)
        require(
            certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca,
            "provided certificate is not a CA",
        )
        check(report, "delivery", "provided_ca_sha256", digest(ca) == config["ca_sha256"])
        source = inspector.source(no_redirects(checkout), spec["source"])
        report["manifest_sha256"] = expected_manifest_sha256
        report["inspection_tools_sha256"] = [before[p] for p in inspector.paths]
        report["source_declarations"] = spec["source"] | {
            "default_test_build_type": source["default_test_build_type"]
        }
        for role in APP_ROLES:
            check(
                report,
                role,
                "source_variant_metadata",
                source[role] == {k: records[role][k] for k in source[role]},
            )
        for role in ROLES[2:]:
            check(
                report,
                role,
                "source_runner",
                records[role]["instrumentation"]["runner"] == source["runner"],
            )
        for role in ROLES:
            inspect_apk(
                report, role, records[role], paths[role], inspector, config, ca_bytes, source
            )
        check(
            report, "delivery", "inputs_unchanged", all(digest(p) == h for p, h in before.items())
        )
        report["result"] = (
            "STATIC_PASS" if all(c["status"] == "PASS" for c in report["checks"]) else "STATIC_FAIL"
        )
        if output is not None:
            write_report(output, report)
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        RecursionError,
        struct.error,
        subprocess.TimeoutExpired,
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        x509.ExtensionNotFound,
    ) as error:
        report["result"] = "STATIC_BLOCKED"
        reason = (
            str(error)
            if isinstance(error, Unchecked)
            else "inspection incomplete; tool details omitted"
        )
        report["checks"].append(
            {
                "role": "delivery",
                "name": "inspection_completeness",
                "status": "NOT_CHECKED",
                "reason": reason,
            }
        )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "ca", "checkout", "aapt", "java", "apksigner-jar", "git"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("expected-manifest-sha256", "source-commit", "source-android-tree"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument(
        "--report", type=Path, help="Create a NEW report only, after complete inspection"
    )
    args = parser.parse_args(argv)
    try:
        inspector = Inspector(args.aapt, args.java, args.apksigner_jar, args.git)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "scope": "STATIC_FOUR_APK_ONLY",
                    "result": "STATIC_BLOCKED",
                    "reason": "inspection tools unavailable",
                    "android_acceptance": "NOT_CREATED",
                    "deployment_authorized": False,
                }
            )
        )
        return 2
    result = inspect_delivery(
        args.manifest,
        expected_manifest_sha256=args.expected_manifest_sha256,
        source_commit=args.source_commit,
        android_tree=args.source_android_tree,
        checkout=args.checkout,
        ca=args.ca,
        inspector=inspector,
        report_path=args.report,
    )
    print(json.dumps(result, ensure_ascii=False))
    return {"STATIC_PASS": 0, "STATIC_FAIL": 1, "STATIC_BLOCKED": 2}[result["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
