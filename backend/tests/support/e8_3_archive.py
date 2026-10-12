"""Real PG17 archive clients; host-independent and bound to the trusted source."""

import os
import shutil
import subprocess
from pathlib import Path

from tests.support.e8_3_ci import IMAGE


def archive_environment(admin):
    if admin.host not in {"127.0.0.1", "::1"} or not admin.database.endswith("_test"):
        raise ValueError("Archive proof requires an owned loopback test database")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update(
        PGHOST=admin.host,
        PGPORT=str(admin.port),
        PGUSER=admin.username,
        PGPASSWORD=admin.password,
        PGDATABASE=admin.database,
    )
    return environment


def pg_command(name, arguments, environment, *, interactive=False):
    if name not in {"pg_dump", "pg_restore"}:
        raise ValueError("Only archive clients are permitted")
    directory = next(
        (
            environment[key]
            for key in ("E8_3_POSTGRES_BIN", "E7_TEST_PG_BIN", "E4_SECRET_PG_BIN")
            if environment.get(key)
        ),
        None,
    )
    path = (
        str(Path(directory) / (name + (".exe" if os.name == "nt" else "")))
        if directory
        else shutil.which(name)
    )
    if path and Path(path).is_file():
        version = subprocess.run(
            [path, "--version"], env=environment, capture_output=True, text=True, timeout=10
        )
        if version.returncode == 0 and " 17." in version.stdout:
            return [path, *arguments]
    if directory or os.name == "nt":
        raise RuntimeError("Archive proof requires an explicit PostgreSQL17 client directory")
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Archive proof requires PostgreSQL17 clients or pinned Docker")
    docker_version = subprocess.run(
        [docker, "run", "--rm", IMAGE, name, "--version"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if docker_version.returncode != 0 or " 17." not in docker_version.stdout:
        raise RuntimeError("Pinned archive client must be PostgreSQL17")
    return [
        docker,
        "run",
        "--rm",
        "--network",
        "host",
        *(["--interactive"] if interactive else []),
        "--env",
        "PGHOST",
        "--env",
        "PGPORT",
        "--env",
        "PGUSER",
        "--env",
        "PGPASSWORD",
        "--env",
        "PGDATABASE",
        IMAGE,
        name,
        *arguments,
    ]
