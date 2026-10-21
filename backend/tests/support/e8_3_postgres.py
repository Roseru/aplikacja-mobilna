"""Private E8.3 PostgreSQL bootstrap; never imported by the runtime package.

Every reviewer supplies its own cluster and credentials through a private JSON
file or E8_3_*_DATABASE_URL environment variables. No URL is printed by this
module. Bootstrap creates roles only on an empty private cluster and refuses
preexisting application roles; it does not alter shared services.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

BASE_ROLES = (
    "calorie_app_api",
    "calorie_app_worker",
    "calorie_app_migrator",
    "calorie_app_ai_worker",
    "calorie_app_motivation_worker",
    "calorie_app_deletion_operator",
    "calorie_app_deletion_exporter",
    "calorie_app_nemesis_worker",
    "keycloak",
    "e8_3_nemesis_worker_login",
)


@dataclass(frozen=True)
class PrivatePostgres:
    admin_url: str = field(repr=False)
    migrator_url: str = field(repr=False)
    api_url: str = field(repr=False)
    worker_url: str = field(repr=False)

    @classmethod
    def from_environment(cls):
        private_file = os.environ.get("E8_3_POSTGRES_CREDENTIALS")
        values = json.loads(Path(private_file).read_text(encoding="utf-8")) if private_file else {}
        for name in ("admin", "migrator", "api", "worker"):
            override = os.environ.get(f"E8_3_{name.upper()}_DATABASE_URL")
            if override:
                values[f"{name}_url"] = override
        result = cls(**{name: values[name] for name in cls.__dataclass_fields__})
        for url in (result.admin_url, result.migrator_url, result.api_url, result.worker_url):
            parsed = make_url(url)
            if parsed.drivername != "postgresql+psycopg" or not parsed.database.endswith("_test"):
                raise ValueError("private E8.3 PostgreSQL *_test database required")
        return result

    def engine(self, role="migrator"):
        if role not in {"admin", "migrator", "api", "worker"}:
            raise ValueError("unsupported private E8.3 role")
        return create_engine(getattr(self, f"{role}_url"), hide_parameters=True)

    def migrate(self, revision="0016_e8_motivation"):
        engine = self.engine()
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = self.migrator_url
        try:
            with engine.begin() as connection:
                assert 170000 <= int(connection.scalar(text("SHOW server_version_num"))) < 180000
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
        finally:
            config.attributes.pop("connection", None)
            engine.dispose()
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous


def initialize_empty_cluster(host, port, database, passwords):
    """Explicit private bootstrap on a freshly initialized loopback cluster.

    passwords contains random fixture credentials held outside tracked files.
    Application base workers stay NOLOGIN; the private lifecycle login inherits
    only its worker base. Runtime permission evidence must use actual LOGINs.
    """
    if host not in {"127.0.0.1", "::1"} or not database.endswith("_test"):
        raise ValueError("private loopback *_test cluster required")
    admin = URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=passwords["admin"],
        host=host,
        port=port,
        database="postgres",
    )
    with psycopg.connect(
        admin.render_as_string(hide_password=False).replace(
            "postgresql+psycopg://", "postgresql://", 1
        ),
        autocommit=True,
    ) as conn:
        present = conn.execute(
            "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(BASE_ROLES),)
        ).fetchall()
        if present:
            raise ValueError("refusing to change preexisting application roles")
        for role in BASE_ROLES:
            if role in {"calorie_app_migrator", "calorie_app_api", "calorie_app_worker"}:
                key = role.removeprefix("calorie_app_")
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(passwords[key]))
                )
            elif role == "e8_3_nemesis_worker_login":
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(passwords["worker"]))
                )
                conn.execute(
                    sql.SQL("GRANT calorie_app_nemesis_worker TO {}").format(sql.Identifier(role))
                )
            else:
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    ).format(sql.Identifier(role))
                )
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator").format(
                sql.Identifier(database)
            )
        )
        conn.execute(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database))
        )
        conn.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO calorie_app_api, "
                "calorie_app_worker, calorie_app_deletion_operator, "
                "e8_3_nemesis_worker_login"
            ).format(sql.Identifier(database))
        )
    urls = {}
    for role in ("admin", "migrator", "api", "worker"):
        username = (
            "postgres"
            if role == "admin"
            else "e8_3_nemesis_worker_login"
            if role == "worker"
            else f"calorie_app_{role}"
        )
        urls[f"{role}_url"] = URL.create(
            "postgresql+psycopg",
            username=username,
            password=passwords[role],
            host=host,
            port=port,
            database=database,
        ).render_as_string(hide_password=False)
    private = PrivatePostgres(**urls)
    engine = private.engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator"))
            conn.execute(text("GRANT USAGE ON SCHEMA app TO calorie_app_api, calorie_app_worker"))
            conn.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
                    "SELECT, INSERT, UPDATE, DELETE ON TABLES "
                    "TO calorie_app_api, calorie_app_worker"
                )
            )
            conn.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
                    "USAGE, SELECT ON SEQUENCES TO calorie_app_api, calorie_app_worker"
                )
            )
    finally:
        engine.dispose()
    return private
