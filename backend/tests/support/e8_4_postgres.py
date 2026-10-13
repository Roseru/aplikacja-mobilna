"""Private E8.4 producer fixtures using the production factory and real SCRAM.

No capability, seed or caller-qualified timestamp is forged by this module.
The migrator controls a private database clock solely for boundary oracles.
JWT/JWKS are synthetic signed inputs; these tests do not claim Keycloak/TLS.
"""

import json
import os
import secrets
import time as clock_time
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, time
from decimal import Decimal
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from tests.support.e8_3_ci import IMAGE, docker
from tests.support.e8_3_jwt import ISSUER, SignedTokens
from tests.support.e8_3_postgres import PrivatePostgres, initialize_empty_cluster

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "contracts/examples/valid"
SECRET = "e4" * 32


def example(name):
    return json.loads((EXAMPLES / (name + ".json")).read_text(encoding="utf-8"))


def private_database():
    credential_file = os.environ.get("E8_4_POSTGRES_CREDENTIALS")
    if credential_file:
        values = json.loads(Path(credential_file).read_text(encoding="utf-8"))
        return PrivatePostgres(**{key: values[key] for key in PrivatePostgres.__dataclass_fields__})
    raise ValueError("E8.4 requires its own credential file or owned producer fixture")


@pytest.fixture(scope="session", autouse=True)
def e8_4_services(tmp_path_factory):
    """One pinned owned PG17 container when no explicit private service is supplied."""
    previous = os.environ.get("E8_4_POSTGRES_CREDENTIALS")
    if previous:
        assert Path(previous).is_file(), "private E8.4 credential file missing"
        yield
        return
    run = uuid4().hex
    label = "calorie.e8-4-evidence"
    passwords = {key: secrets.token_urlsafe(40) for key in ("admin", "migrator", "api", "worker")}
    environment = os.environ | {"POSTGRES_PASSWORD": passwords["admin"]}
    container = docker(
        "run",
        "--detach",
        "--name",
        "e8-4-author-" + run,
        "--label",
        label + "=" + run,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_PASSWORD",
        "--env",
        "POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256",
        IMAGE,
        environment=environment,
    )
    try:
        port = int(docker("port", container, "5432/tcp").rsplit(":", 1)[1])
        deadline = monotonic() + 60
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
                if monotonic() >= deadline:
                    raise RuntimeError("owned E8.4 PG17 container did not become ready") from None
                clock_time.sleep(0.1)
        private = initialize_empty_cluster("127.0.0.1", port, "e8_4_author_test", passwords)
        admin = private.engine("admin")
        try:
            with admin.begin() as connection:
                connection.execute(
                    text(
                        "CREATE ROLE calorie_app_nemesis_finalizer NOLOGIN NOINHERIT "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE"
                    )
                )
        finally:
            admin.dispose()
        private.migrate("0021_e8_nemesis_results")
        target = tmp_path_factory.mktemp("e8-4-private") / "credentials.json"
        target.write_text(
            json.dumps({key: getattr(private, key) for key in private.__dataclass_fields__}),
            encoding="utf-8",
        )
        target.chmod(0o600)
        os.environ["E8_4_POSTGRES_CREDENTIALS"] = str(target)
        yield
    finally:
        os.environ.pop("E8_4_POSTGRES_CREDENTIALS", None)
        actual = docker(
            "inspect", "--format", '{{ index .Config.Labels "' + label + '" }}', container
        )
        if actual != run:
            raise RuntimeError("refusing to remove a PG17 container not owned by this E8.4 fixture")
        docker("rm", "--force", container)


@contextmanager
def fresh_database(revision="0020_e8_nemesis_integration", *, initialize=True):
    """A separate owned DB, reusing only role definitions of the owned PG service."""
    base = private_database()
    name = "e8_4_migration_" + uuid4().hex[:12] + "_test"
    private = replace(
        base,
        **{
            field: make_url(getattr(base, field))
            .set(database=name)
            .render_as_string(hide_password=False)
            for field in base.__dataclass_fields__
        },
    )
    admin = base.engine("admin")
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in (
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator").format(sql.Identifier(name)),
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)),
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO calorie_app_api,"
                "calorie_app_worker,calorie_app_nemesis_worker,calorie_app_nemesis_finalizer,"
                "calorie_app_deletion_operator"
            ).format(sql.Identifier(name)),
        ):
            connection.exec_driver_sql(statement.as_string(connection.connection.driver_connection))
    migrator = private.engine()
    try:
        with migrator.begin() as connection:
            if not initialize:
                yield private
                return
            connection.execute(text("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator"))
            connection.execute(
                text("GRANT USAGE ON SCHEMA app TO calorie_app_api,calorie_app_worker")
            )
            connection.execute(
                text(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
                    "SELECT,INSERT,UPDATE,DELETE ON TABLES TO calorie_app_api,calorie_app_worker"
                )
            )
        private.migrate(revision)
        yield private
    finally:
        migrator.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.exec_driver_sql(
                sql.SQL("DROP DATABASE {} WITH (FORCE)")
                .format(sql.Identifier(name))
                .as_string(connection.connection.driver_connection)
            )
        admin.dispose()


def clock(rt, instant):
    """Replace only the private DB clock; production requests have no time authority."""
    if instant.tzinfo is None:
        raise ValueError("aware private test instant required")
    value = instant.astimezone(UTC).isoformat()
    with rt["migrator"].begin() as connection:
        for name in ("e8_clock", "e8n_clock"):
            connection.exec_driver_sql(
                f"CREATE OR REPLACE FUNCTION app.{name}() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
                f"AS $$ SELECT TIMESTAMPTZ '{value}' $$"
            )


def reset_clock(migrator):
    with migrator.begin() as connection:
        for name in ("e8_clock", "e8n_clock"):
            connection.exec_driver_sql(
                f"CREATE OR REPLACE FUNCTION app.{name}() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp "
                "AS $$ SELECT clock_timestamp() $$"
            )


@contextmanager
def finalizer_login(private):
    """A real random SCRAM LOGIN inheriting only the dedicated finalizer base."""
    name, password = "e8_4_finalizer_" + uuid4().hex[:12], secrets.token_urlsafe(40)
    admin = private.engine("admin")
    parsed = make_url(private.admin_url)
    with admin.begin() as connection:
        raw = connection.connection.driver_connection
        for statement in (
            sql.SQL(
                "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
            ).format(sql.Identifier(name), sql.Literal(password)),
            sql.SQL("GRANT calorie_app_nemesis_finalizer TO {}").format(sql.Identifier(name)),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(parsed.database), sql.Identifier(name)
            ),
        ):
            connection.exec_driver_sql(statement.as_string(raw))
    engine = create_engine(parsed.set(username=name, password=password), hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            raw = connection.connection.driver_connection
            for statement in (
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)),
                sql.SQL("DROP ROLE {}").format(sql.Identifier(name)),
            ):
                connection.exec_driver_sql(statement.as_string(raw))
        admin.dispose()


@contextmanager
def runtime(*, now=datetime(2026, 10, 12, 12, tzinfo=UTC), zone="UTC"):
    with fresh_database("0023_e9_qualification") as private:
        with _runtime(private, now=now, zone=zone) as rt:
            yield rt


@contextmanager
def _runtime(private, *, now, zone):
    engines = {name: private.engine(name) for name in ("admin", "migrator", "api", "worker")}
    with engines["admin"].connect() as connection:
        assert 170000 <= int(connection.scalar(text("SHOW server_version_num"))) < 180000
        assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) in {
            "0021_e8_nemesis_results",
            "0022_e9_energy",
            "0023_e9_qualification",
        }
    for name in ("api", "migrator", "worker"):
        with engines[name].connect() as connection:
            assert connection.scalar(text("SELECT current_user=session_user"))
            assert not connection.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            )
    signed = SignedTokens()
    app = create_app(
        Settings(
            database_url=private.api_url,
            environment="test",
            catalog_page_token_secret=SecretStr(SECRET),
            oidc_issuer=ISSUER,
            oidc_jwks_url=ISSUER + "/certs",
            _env_file=None,
        ),
        engine=engines["api"],
    )
    app.state.oidc_verifier = signed.verifier
    with engines["admin"].begin() as connection:
        connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
        # The synthetic reset cascades through ai_jobs/attempts into physical
        # permits. Restore the original two configured slots, never the limits.
        connection.execute(
            text(
                "INSERT INTO app.ai_transport_permits(environment,slot) "
                "SELECT DISTINCT p.environment,s FROM app.ai_pools p "
                "CROSS JOIN generate_series(1,2) s ON CONFLICT DO NOTHING"
            )
        )
        connection.execute(text("UPDATE app.nemesis_control SET enabled=false"))
        epoch = connection.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    rt = engines | {"private": private, "signed": signed, "epoch": epoch, "actors": {}, "now": now}
    clock(rt, now)
    try:
        with (
            finalizer_login(private) as finalizer,
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            rt["client"] = client
            rt["finalizer"] = finalizer
            for name in ("a", "b", "c"):
                subject = str(uuid4())
                headers = {"Authorization": "Bearer " + signed.token(subject)}
                response = client.post(
                    "/api/v1/me/bootstrap", headers=headers | {"Idempotency-Key": str(uuid4())}
                )
                assert response.status_code == 200, response.text
                pull = client.get("/api/v1/sync/pull", headers=headers)
                assert pull.status_code == 200, pull.text
                actor = {
                    "owner": UUID(response.json()["account_id"]),
                    "subject": subject,
                    "headers": headers,
                    "checkpoint": pull.json()["checkpoint"],
                    "profile": uuid4(),
                }
                rt["actors"][name] = actor
                profile = operation(
                    rt,
                    "profile",
                    entity=actor["profile"],
                    payload=example("profile") | {"time_zone": zone},
                )
                assert push(rt, name, profile)["status"] == "accepted"
            yield rt
    finally:
        with engines["admin"].begin() as connection:
            connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
            connection.execute(text("UPDATE app.nemesis_control SET enabled=false"))
        reset_clock(engines["migrator"])
        for engine in engines.values():
            engine.dispose()


def headers(rt, actor="a", *, key=None, revision=None):
    values = rt["actors"][actor]["headers"] | {
        "X-Sync-Epoch": str(rt["epoch"]),
        "Idempotency-Key": str(key or uuid4()),
    }
    if revision is not None:
        values["If-Match"] = f'"{revision}"'
    return values


def operation(rt, kind, *, entity=None, base=None, payload=None, action="upsert"):
    return {
        "operation_id": str(uuid4()),
        "entity_type": kind,
        "entity_id": str(entity or uuid4()),
        "base_revision": base,
        "sync_epoch": str(rt["epoch"]),
        "action": action,
        "payload": (payload if payload is not None else example(kind.replace("_", "-")))
        if action == "upsert"
        else None,
    }


def push_response(rt, actor, operations):
    response = rt["client"].post(
        "/api/v1/sync/push",
        headers=rt["actors"][actor]["headers"],
        json={
            "protocol_version": 1,
            "sync_epoch": str(rt["epoch"]),
            "checkpoint": rt["actors"][actor]["checkpoint"],
            "operations": operations,
        },
    )
    assert response.headers["cache-control"] == "no-store"
    return response


def push(rt, actor, op):
    response = push_response(rt, actor, [op])
    assert response.status_code == 200, response.text
    return response.json()["results"][0]


def meal_payload(day, energy, zone="UTC", *, item_id=None):
    payload = example("meal") | {
        "local_date": day.isoformat(),
        "occurred_at": datetime.combine(day, time(12), UTC).isoformat().replace("+00:00", "Z"),
        "time_zone": zone,
    }
    payload["items"][0] |= {
        "item_id": str(item_id or uuid4()),
        "quantity": {"amount": "100", "unit": "g"},
        "nutrition_per_100": {
            "energy_kcal": energy,
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        },
    }
    return payload


def complete_day(rt, actor, day, energy, zone="UTC"):
    meal = operation(rt, "meal", payload=meal_payload(day, energy, zone))
    assert push(rt, actor, meal)["status"] == "accepted"
    with rt["admin"].connect() as connection:
        identifier, revision = connection.execute(
            text(
                "SELECT id,revision FROM app.diary_days WHERE owner_id=:owner AND local_date=:day"
            ),
            {"owner": rt["actors"][actor]["owner"], "day": day},
        ).one()
    declared = operation(
        rt,
        "diary_day",
        entity=identifier,
        base=revision,
        payload={"local_date": day.isoformat(), "time_zone": zone, "declared_complete": True},
    )
    assert push(rt, actor, declared)["status"] == "accepted"
    return meal, declared


def goal_payload(day, energy, *, timeline_revision=0, maintenance=None, zone="UTC"):
    payload = example("goal") | {
        "effective_from": day.isoformat(),
        "decided_at": datetime.combine(day, time(0), UTC).isoformat().replace("+00:00", "Z"),
        "time_zone": zone,
        "energy_kcal": energy,
        "timeline_base_revision": timeline_revision,
    }
    if maintenance is not None:
        resting = Decimal(maintenance) / Decimal("1.5")
        weight = (resting - Decimal(980)) / Decimal(10)

        def canonical(value):
            return format(value, "f").rstrip("0").rstrip(".") if value % 1 else str(int(value))

        payload["estimate"] = {
            "method": "mifflin_pal_v1",
            "input": {
                "age_years": 30,
                "height_cm": "180",
                "weight_kg": canonical(weight),
                "equation_variant": "plus_5",
                "activity_class": "stationary",
            },
            "resting_kcal": canonical(resting),
            "pal": "1.5",
            "maintenance_kcal": maintenance,
            "estimated_at": payload["decided_at"],
        }
    return payload


def statistics(rt, challenge, actor="a", *, extra_headers=None):
    response = rt["client"].get(
        f"/api/v1/nemesis/{challenge}/statistics",
        headers=headers(rt, actor) | (extra_headers or {}),
    )
    assert response.headers["cache-control"] == "no-store"
    return response


def activate(rt):
    with rt["migrator"].begin() as connection:
        connection.execute(text("SELECT app.e8n_activate(:epoch)"), {"epoch": rt["epoch"]})
        assert connection.scalar(text("SELECT app.e8n_gate()"))


def invite(rt, *, sender="a", receiver="b", days=7, zone="UTC", metrics=False):
    terms = {
        "rule_version": "regularity_v1",
        "duration_days": days,
        "time_zone": zone,
        "scope": {"regularity": True, "weight_change": metrics, "mean_deficit": metrics},
    }
    code = rt["client"].post("/api/v1/me/nemesis/share-code", headers=headers(rt, receiver))
    assert code.status_code == 200, code.text
    response = rt["client"].post(
        "/api/v1/nemesis",
        headers=headers(rt, sender),
        json={"destination_code": code.json()["destination_code"], "terms": terms},
    )
    assert response.status_code == 201, response.text
    return response.json(), terms


def accept(rt, invitation, terms, *, actor="b", key=None):
    return rt["client"].post(
        "/api/v1/nemesis/" + invitation["id"] + "/accept",
        headers=headers(rt, actor, key=key, revision=invitation["revision"]),
        json={"terms": terms},
    )


def challenge(rt, **options):
    invitation, terms = invite(rt, **options)
    response = accept(rt, invitation, terms, actor=options.get("receiver", "b"))
    assert response.status_code == 200, response.text
    return response.json()


def finalize(rt, challenge):
    with rt["finalizer"].begin() as connection:
        return connection.scalar(text("SELECT app.e8n_finalize(:id)"), {"id": challenge})


def projection_rows(rt, identifier):
    with rt["admin"].connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT * FROM app.nemesis_day_projections WHERE challenge_id=:id "
                    "ORDER BY participant_role,local_date"
                ),
                {"id": identifier},
            ).mappings()
        ]


def wait_for_blocker(rt, blocker_pid, timeout=8):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        with rt["admin"].connect() as connection:
            if connection.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity "
                    "WHERE datname=current_database() AND pid<>:pid "
                    "AND :pid=ANY(pg_blocking_pids(pid)))"
                ),
                {"pid": blocker_pid},
            ):
                return
        Event().wait(0.01)
    raise AssertionError("competitor did not enter an observed PostgreSQL lock wait")
