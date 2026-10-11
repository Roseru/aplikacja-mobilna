"""Generate an external, validation-only Android TLS overlay without editing O1 sources."""

import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization


def prepare(state: Path, output: Path):
    config = json.loads((state / "config.json").read_text(encoding="utf-8"))
    host = str(ipaddress.IPv4Address(config["host"]))
    address = ipaddress.IPv4Address(host)
    if not (
        address.is_loopback
        or any(
            address in ipaddress.ip_network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
    ):
        raise ValueError("Only the existing local integration IPv4 address is supported")
    port = int(config["port"])
    if not 1 <= port <= 65535:
        raise ValueError("Invalid HTTPS port")
    issuer = f"https://{host}:{port}/realms/calorie-dev"
    pem = (state / "tls" / "ca.pem").read_bytes()
    if not re.fullmatch(
        rb"\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*",
        pem,
    ):
        raise ValueError("Expected exactly one public certificate, without private keys")
    certificate = x509.load_pem_x509_certificate(pem)
    if not certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError("Expected a CA certificate")
    pem = certificate.public_bytes(serialization.Encoding.PEM)
    output.mkdir(parents=True, exist_ok=False)
    resources = output / "res"
    (resources / "raw").mkdir(parents=True)
    (resources / "xml").mkdir()
    (resources / "raw" / "o3_local_ca.pem").write_bytes(pem)
    (resources / "xml" / "o3_network_security.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<network-security-config>\n"
        '  <base-config cleartextTrafficPermitted="false">\n'
        '    <trust-anchors><certificates src="system"/></trust-anchors>\n'
        "  </base-config>\n"
        '  <domain-config cleartextTrafficPermitted="false">\n'
        f'    <domain includeSubdomains="false">{host}</domain>\n'
        '    <trust-anchors><certificates src="@raw/o3_local_ca"/></trust-anchors>\n'
        "  </domain-config>\n"
        "</network-security-config>\n",
        encoding="utf-8",
    )
    (output / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <application android:networkSecurityConfig="@xml/o3_network_security"/>\n'
        "</manifest>\n",
        encoding="utf-8",
    )
    # Inject source locations before Android evaluates its variants. Only validation uses them.
    # Use a Groovy literal: a double-quoted GString would interpret $ in a path.
    path = "'" + output.resolve().as_posix().replace("\\", "\\\\").replace("'", "\\'") + "'"
    (output / "init.gradle").write_text(
        "gradle.beforeProject { project ->\n"
        '  project.pluginManager.withPlugin("com.android.application") {\n'
        '    if (project.path != ":app") throw new GradleException("Expected :app only")\n'
        f"    def overlay = new File({path})\n"
        '    project.android.sourceSets.maybeCreate("validation").with {\n'
        '      res.srcDir(new File(overlay, "res"))\n'
        '      manifest.srcFile(new File(overlay, "AndroidManifest.xml"))\n'
        "    }\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    receipt = {
        "issuer": issuer,
        "application_id": "pl.roseru.kalorie.validation",
        "variant": "validation",
        "ca_sha256": hashlib.sha256(pem).hexdigest(),
        "host": host,
        "port": port,
        "cleartext": False,
        "include_subdomains": False,
        "trust_user_ca": False,
    }
    (output / "overlay.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.state.resolve(), args.output.resolve())))


if __name__ == "__main__":
    main()
