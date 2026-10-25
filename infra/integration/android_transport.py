"""Owned, rooted AVD tunnel to the existing loopback gateway, preserving HTTPS identity."""

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
from pathlib import Path


class Transport:
    def __init__(self, adb: str, serial: str, avd: str, host: str, port: int, server_port=5037):
        if not re.fullmatch(r"emulator-[0-9]+", serial):
            raise ValueError("Only an explicitly selected emulator is supported")
        address = ipaddress.IPv4Address(host)
        if (
            not any(
                address in ipaddress.ip_network(n)
                for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
            )
            or not 1024 <= port <= 65535
        ):
            raise ValueError("Expected existing private IPv4 origin and nonprivileged HTTPS port")
        self.adb, self.serial, self.avd = adb, serial, avd
        if not 1024 <= server_port <= 65535:
            raise ValueError("Invalid ADB server port")
        self.server_port = server_port
        self.host, self.port = str(address), port
        self.chain = f"O3_APK_{port}"

    def call(self, *args):
        result = subprocess.run(
            [self.adb, "-P", str(self.server_port), "-s", self.serial, *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode:
            # adb output can contain unrelated device data. Do not publish it.
            raise RuntimeError("ADB command failed: " + " ".join(args[:3]))
        return result.stdout.strip().replace("\r", "")

    def guard(self):
        name = self.call("emu", "avd", "name").splitlines()[0]
        if name != self.avd or self.call("shell", "getprop", "sys.boot_completed") != "1":
            raise RuntimeError("Selected owned AVD must match and be fully booted")
        if self.call("shell", "id", "-u") != "0":
            raise RuntimeError("Requires adb root on the owned Google APIs test AVD")
        return self.call("shell", "cat", "/proc/sys/kernel/random/boot_id")

    def rules(self):
        return self.call("shell", "iptables", "-t", "nat", "-S").splitlines()

    def reverse(self):
        return [line.split() for line in self.call("reverse", "--list").splitlines()]

    def ipt(self, *args):
        self.call("shell", "iptables", "-t", "nat", *args)

    def specification(self, boot):
        return dict(
            serial=self.serial,
            avd=self.avd,
            host=self.host,
            port=self.port,
            chain=self.chain,
            boot=boot,
            adb_server_port=self.server_port,
        )

    def connect(self, lease: Path):
        boot = self.guard()
        if any(self.chain in rule.split() for rule in self.rules()):
            raise RuntimeError("Existing chain is not overwritten; disconnect its owner first")
        if any(f"tcp:{self.port}" == row[1] for row in self.reverse()):
            raise RuntimeError("Existing reverse mapping is not overwritten")
        lease.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive ownership record before mutation. No silent reuse of another tunnel.
        with lease.open("x", encoding="utf-8") as stream:
            json.dump(self.specification(boot), stream, indent=2)
        chain = reverse = output = False
        try:
            self.ipt("-N", self.chain)
            chain = True
            self.call("reverse", "--no-rebind", f"tcp:{self.port}", f"tcp:{self.port}")
            reverse = True
            self.ipt(
                "-A",
                self.chain,
                "-p",
                "tcp",
                "-d",
                self.host,
                "--dport",
                str(self.port),
                "-j",
                "DNAT",
                "--to-destination",
                f"127.0.0.1:{self.port}",
            )
            self.ipt("-I", "OUTPUT", "1", "-j", self.chain)
            output = True
            self.check(lease)
        except Exception:
            if output:
                self.ipt("-D", "OUTPUT", "-j", self.chain)
            if chain:
                self.ipt("-F", self.chain)
                self.ipt("-X", self.chain)
            if reverse:
                self.call("reverse", "--remove", f"tcp:{self.port}")
            lease.unlink()
            raise

    def check(self, lease: Path):
        if json.loads(lease.read_text(encoding="utf-8")) != self.specification(self.guard()):
            raise RuntimeError("Lease belongs to another origin, AVD or boot; no mutation")
        expected = {
            f"-N {self.chain}",
            f"-A OUTPUT -j {self.chain}",
            f"-A {self.chain} -d {self.host}/32 -p tcp -m tcp --dport {self.port} "
            f"-j DNAT --to-destination 127.0.0.1:{self.port}",
        }
        observed = [rule for rule in self.rules() if self.chain in rule.split()]
        if len(observed) != 3 or set(observed) != expected:
            raise RuntimeError("Tunnel rules changed; refusing to flush unrelated rules")
        mapping = [row for row in self.reverse() if row[1] == f"tcp:{self.port}"]
        if len(mapping) != 1 or mapping[0][2] != f"tcp:{self.port}":
            raise RuntimeError("Reverse mapping changed; refusing to remove it")

    def ensure(self, lease: Path):
        """Reuse a checked tunnel, or preserve an expired boot's absent tunnel record."""
        if lease.exists():
            raw = lease.read_bytes()
            recorded = json.loads(raw)
            current = self.specification(self.guard())
            if recorded == current:
                self.check(lease)
                return
            if (
                not isinstance(recorded, dict)
                or not isinstance(recorded.get("boot"), str)
                or not recorded["boot"]
                or recorded != self.specification(recorded["boot"])
                or recorded["boot"] == current["boot"]
            ):
                raise RuntimeError("Lease belongs to another transport; no mutation")
            if any(self.chain in rule.split() for rule in self.rules()) or any(
                row[1] == f"tcp:{self.port}" for row in self.reverse()
            ):
                raise RuntimeError("Previous boot lease has an existing route; no mutation")
            archive = lease.with_name(
                lease.name + ".stale-" + hashlib.sha256(raw).hexdigest() + ".json"
            )
            with archive.open("xb") as stream:
                stream.write(raw)
            if lease.read_bytes() != raw:
                raise RuntimeError("Lease changed while preserving it; no route mutation")
            lease.unlink()
        self.connect(lease)

    def disconnect(self, lease: Path):
        self.check(lease)
        self.ipt("-D", "OUTPUT", "-j", self.chain)
        self.ipt("-F", self.chain)
        self.ipt("-X", self.chain)
        self.call("reverse", "--remove", f"tcp:{self.port}")
        lease.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("connect", "ensure", "status", "disconnect"))
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb-server-port", type=int, default=5037)
    parser.add_argument("--avd", required=True, help="Explicitly owned test AVD, never a phone")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--lease", type=Path, required=True, help="Private ownership receipt")
    args = parser.parse_args()
    config = json.loads((args.state / "config.json").read_text(encoding="utf-8"))
    tunnel = Transport(
        args.adb, args.serial, args.avd, config["host"], int(config["port"]), args.adb_server_port
    )
    if args.action == "status":
        tunnel.check(args.lease)
    else:
        getattr(tunnel, args.action)(args.lease)
    print(
        json.dumps(
            {
                "action": args.action,
                "routing": "PASS",
                "avd": args.avd,
                "origin": f"https://{tunnel.host}:{tunnel.port}",
                "ca_sha256": hashlib.sha256((args.state / "tls/ca.pem").read_bytes()).hexdigest(),
                "tls_acceptance": "NOT_TESTED_BY_ROUTING_SCRIPT",
            }
        )
    )


if __name__ == "__main__":
    main()
