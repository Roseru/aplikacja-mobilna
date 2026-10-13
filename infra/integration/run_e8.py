"""Explicit local E8 worker rollout; activation is a separate owner-only action."""

import argparse
import json
import re
import secrets
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from run import DEFAULT_STATE, HERE, Stack, env_file

SERVICES = {
    "motivation": "motivation",
    "lifecycle": "nemesis-lifecycle",
    "finalizer": "nemesis-finalizer",
}
LOGINS = {
    "motivation": "integration_motivation",
    "lifecycle": "integration_nemesis",
    "finalizer": "integration_finalizer",
}
PREFIXES = {
    "motivation": "MOTIVATION_WORKER",
    "lifecycle": "NEMESIS_WORKER",
    "finalizer": "NEMESIS_FINALIZER",
}


def prepare(state):
    original = dict(
        line.split("=", 1) for line in (state / "postgres.env").read_text().splitlines()
    )
    admin = {
        "PGHOST": "postgres",
        "PGDATABASE": "calorie_app",
        "PGUSER": "postgres",
        "PGPASSWORD": original["POSTGRES_PASSWORD"],
    }
    for task, login in LOGINS.items():
        target = state / f"e8-{task}.env"
        if not target.exists():
            password = secrets.token_hex(32)
            env_file(
                state,
                target.name,
                {"DATABASE_URL": f"postgresql+psycopg://{login}:{password}@postgres/calorie_app"},
            )
        data = dict(line.split("=", 1) for line in target.read_text().splitlines())
        match = re.fullmatch(
            rf"postgresql\+psycopg://{login}:([0-9a-f]{{64}})@postgres/calorie_app",
            data["DATABASE_URL"],
        )
        if not match:
            raise ValueError("Preserve unexpected existing E8 credentials")
        admin[PREFIXES[task] + "_LOGIN"] = login
        admin[PREFIXES[task] + "_PASSWORD"] = match[1]
    env_file(state, "e8-admin.env", admin)


class E8Stack(Stack):
    def e8(self, *arguments):
        return self.compose("-f", str(HERE / "compose.e8.yaml"), *arguments)

    def provision(self):
        for name in ("motivation_worker", "nemesis_worker", "nemesis_finalizer"):
            self.e8(
                "run",
                "--rm",
                "--no-deps",
                "e8-provision",
                ".venv/bin/python",
                f"/opt/provision/provision_{name}.py",
            )

    def up_workers(self):
        self.provision()
        self.e8("run", "--rm", "--no-deps", "e8-storage-init")
        # Finalizer deliberately unhealthy while capability is disabled. Do not wait
        # for a false ready result, or automatically activate to make Compose green.
        self.e8("up", "--detach", "--no-deps", *SERVICES.values())

    def status(self):
        results = {}
        for task, service in SERVICES.items():
            # status exits nonzero when unhealthy; read persisted aggregates directly.
            value = self.e8(
                "exec",
                "-T",
                service,
                ".venv/bin/python",
                "-I",
                "-c",
                "from pathlib import Path; print(Path('/worker/status.json').read_text())",
            )
            results[task] = json.loads(value)
        return results

    def verify(self):
        if self.sql("calorie_app", "SELECT enabled FROM app.nemesis_control;") != "f":
            raise ValueError("Verification requires the default closed gate")
        checks = []

        def valid(status):
            return (
                status["finalizer"]["state"] == "disabled"
                and status["finalizer"]["metrics"]["ready"] is False
                and all(
                    status[k]["state"] in {"ok", "pending"} for k in ("motivation", "lifecycle")
                )
            )

        def wait_changed(previous=None):
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                try:
                    status = self.status()
                except (RuntimeError, ValueError):
                    # Container startup may precede the first persisted status.
                    time.sleep(2)
                    continue
                if valid(status) and (
                    previous is None
                    or all(status[k]["last_attempt"] != previous[k]["last_attempt"] for k in status)
                ):
                    return status
                time.sleep(2)
            raise RuntimeError("No completed E8 cycle observed")

        first = wait_changed()
        checks.append("Installed CLI startup; motivation/lifecycle ready; finalizer disabled")
        second = wait_changed(first)
        for task in first:
            spacing = (
                datetime.fromisoformat(second[task]["last_attempt"])
                - datetime.fromisoformat(first[task]["last_attempt"])
            ).total_seconds()
            if not 55 <= spacing <= 120:
                raise RuntimeError("Minute cadence not observed")
        checks.append("Second natural minute cycle observed for all three services")
        query = (
            "SELECT current_user, has_schema_privilege(current_user,'app','CREATE'),"
            "has_database_privilege(current_user,'keycloak','CONNECT'),"
            "has_table_privilege(current_user,'app.meals','SELECT'),"
            "(SELECT bool_or(set_option OR admin_option) FROM pg_auth_members "
            "WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))"
        )
        for task, service in SERVICES.items():
            code = (
                "import json,os; from sqlalchemy import create_engine,text; "
                "from calorie_app.core.config import Settings; "
                "e=create_engine(Settings().database_url.get_secret_value()); "
                "c=e.connect(); "
                f"r=c.execute(text({query!r})).one(); "
                "print(json.dumps([os.getuid(),*r])); c.close(); e.dispose()"
            )
            values = json.loads(
                self.e8("exec", "-T", service, ".venv/bin/python", "-I", "-c", code)
            )
            if values != [10001, LOGINS[task], False, False, False, False]:
                raise RuntimeError("Effective E8 LOGIN boundary failed")
        checks.append("UID10001 and three actual LOGINs; no DDL/raw source/identity/SET ROLE")
        epoch = self.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;")
        self.e8("stop", *SERVICES.values())
        self.e8("up", "--detach", "--no-deps", *SERVICES.values())
        wait_changed(second)
        if self.sql("calorie_app", "SELECT sync_epoch FROM app.installation_state;") != epoch:
            raise RuntimeError("Restart changed epoch")
        checks.append("Service restart catches up immediately; epoch and closed gate preserved")
        env_file_path = self.state / "e8-verification.json"
        # Receipt has aggregates and test scope only; no identifiers, credentials or output buffers.
        from run import private_write

        private_write(
            env_file_path,
            json.dumps(
                {
                    "result": "PASS",
                    "verified_at": datetime.now(UTC).isoformat(),
                    "checks": checks,
                    "scope": "Local E8 processes/ACL/cadence/restart; "
                    "excludes production/restore/APK",
                },
                indent=2,
            ),
        )
        for check in checks:
            print("PASS " + check, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "up", "status", "stop", "activate", "verify"))
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args()
    try:
        state = args.state.resolve()
        stack = E8Stack(state)
        if args.action in {"prepare", "up"}:
            prepare(state)
        if args.action == "up":
            stack.up_workers()
        elif args.action == "activate":
            # Real manifest/ACL/head/epoch guards are in this owner entrypoint.
            stack.sql(
                "calorie_app",
                "SELECT app.e8n_activate(sync_epoch) FROM app.installation_state;",
                user="calorie_app_migrator",
            )
        elif args.action == "stop":
            stack.e8("stop", *SERVICES.values())
        elif args.action == "status":
            print(json.dumps(stack.status(), sort_keys=True))
        elif args.action == "verify":
            stack.verify()
        print(f"E8 {args.action}: OK")
        return 0
    except Exception:
        print("E8 local operation failed; inspect private state/compose.log", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
