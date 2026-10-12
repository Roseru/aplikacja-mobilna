"""Owned isolated PostgreSQL services for Nemesis evidence in the real CI job.

Local reviewers supply explicit private clusters. CI uses two labeled containers
so role-topology tests never modify the primary regression server's roles.
"""

import json
import os
import secrets
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg

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
