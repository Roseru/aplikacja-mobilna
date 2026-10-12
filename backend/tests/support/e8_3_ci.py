"""Owned isolated PostgreSQL services for Nemesis evidence in the real CI job.

Local reviewers supply explicit private clusters. CI uses two labeled containers
so role-topology tests never modify the primary regression server's roles.
"""

import json
import os
import secrets
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from sqlalchemy.engine import make_url

from tests.support.e8_3_postgres import initialize_empty_cluster

IMAGE = (
    "public.ecr.aws/docker/library/postgres:17@sha256:"
    "2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3"
)
LABEL = "calorie.e8-3-evidence"


def docker(*arguments, environment=None):
    result = subprocess.run(
        ["docker", *arguments], env=environment, capture_output=True, text=True, timeout=90
    )
    if result.returncode:
        raise RuntimeError("Isolated Nemesis PostgreSQL container command failed")
    return result.stdout.strip()


@contextmanager
def private_servers(folder):
    owned = []
    run = uuid4().hex
    environment = os.environ.copy()
    try:
        values = {}
        for purpose, revision in (
            ("source", "0020_e8_nemesis_integration"),
            ("audit", "0017_e8_purge_commit"),
        ):
            passwords = {
                key: secrets.token_urlsafe(40) for key in ("admin", "migrator", "api", "worker")
            }
            environment["POSTGRES_PASSWORD"] = passwords["admin"]
            name = "e8-nemesis-" + purpose + "-" + run
            container = docker(
                "run",
                "--detach",
                "--name",
                name,
                "--label",
                LABEL + "=" + run,
                "--publish",
                "127.0.0.1::5432",
                "--env",
                "POSTGRES_PASSWORD",
                "--env",
                "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
                IMAGE,
                environment=environment,
            )
            owned.append(container)
            port = int(docker("port", container, "5432/tcp").rsplit(":", 1)[1])
            deadline = time.monotonic() + 60
            while True:
                try:
                    with psycopg.connect(
                        host="127.0.0.1",
                        port=port,
                        user="postgres",
                        password=passwords["admin"],
                        dbname="postgres",
                        connect_timeout=2,
                    ):
                        break
                except psycopg.OperationalError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Isolated Nemesis PostgreSQL did not become ready"
                        ) from None
                    time.sleep(0.1)
            private = initialize_empty_cluster(
                "127.0.0.1", port, "e8_3_ci_" + purpose + "_test", passwords
            )
            private.migrate(revision)
            target = Path(folder) / (purpose + "-credentials.json")
            target.write_text(
                json.dumps({key: getattr(private, key) for key in private.__dataclass_fields__}),
                encoding="utf-8",
            )
            target.chmod(0o600)
            values[purpose] = str(target)
            if purpose == "source":
                values["operator"] = provision_operator(private, folder)
        yield values
    finally:
        for container in reversed(owned):
            actual_label = docker(
                "inspect", "--format", '{{ index .Config.Labels "' + LABEL + '" }}', container
            )
            if actual_label != run:
                raise RuntimeError(
                    "Refusing to remove a PostgreSQL container not owned by this run"
                )
            docker("rm", "--force", container)


def provision_operator(private, folder):
    """The same hardened real SCRAM provision used by CI and reviewer proofs."""
    admin = make_url(private.admin_url)
    login, password = "e8_3_parent_deletion_login", secrets.token_urlsafe(40)
    environment = os.environ.copy()
    environment.update(
        {
            "PGHOST": admin.host,
            "PGPORT": str(admin.port),
            "PGDATABASE": admin.database,
            "PGUSER": admin.username,
            "PGPASSWORD": admin.password,
            "DELETION_OPERATOR_LOGIN": login,
            "DELETION_OPERATOR_PASSWORD": password,
        }
    )
    script = Path(__file__).resolve().parents[3] / "infra/local/provision_deletion_operator.py"
    result = subprocess.run(
        [sys.executable, str(script)], env=environment, capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError("Isolated Nemesis production deletion LOGIN provision failed")
    operator = Path(folder) / "deletion-credentials.json"
    operator.write_text(
        json.dumps(
            {
                "operator_url": admin.set(username=login, password=password).render_as_string(
                    hide_password=False
                )
            }
        ),
        encoding="utf-8",
    )
    operator.chmod(0o600)
    return str(operator)


CREDENTIAL_KEYS = (
    "E8_3_POSTGRES_CREDENTIALS",
    "E8_3_ROLE_AUDIT_CREDENTIALS",
    "E8_3_PARENT_DELETION_CREDENTIALS",
)


def explicit_credentials_complete(environment):
    present = [bool(environment.get(key)) for key in CREDENTIAL_KEYS]
    if any(present) and not all(present):
        raise ValueError(
            "Nemesis evidence requires source/audit/deletion credential files together"
        )
    if all(present):
        for key in CREDENTIAL_KEYS:
            if not Path(environment[key]).is_file():
                raise ValueError("Nemesis evidence credential file is missing")
        return True
    return False


@contextmanager
def configured_servers(folder):
    keys = (*CREDENTIAL_KEYS, "E8_3_HTTP_PROBE_PORT_BASE")
    previous = {key: os.environ.get(key) for key in keys}
    try:
        with private_servers(folder) as services:
            for key, purpose in zip(CREDENTIAL_KEYS, ("source", "audit", "operator"), strict=True):
                os.environ[key] = services[purpose]
            os.environ[keys[-1]] = "18181"
            yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
