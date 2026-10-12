"""Actual 0016 -> 0017 repair -> 0018 lifecycle evidence on owned PostgreSQL.

Private helper mounting demonstrates the component deletion seam only. It does
not replace or register a production begin/confirm/purge wrapper in phase C.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from dataclasses import replace
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from calorie_app.integrations.keycloak import Principal
from tests.integration.test_e4_deletion import seed
from tests.integration.test_e8_3_database import accept, execute, invite
from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
PARENT = "0016_e8_motivation"
REPAIR = "0017_e8_purge_commit"
LIFECYCLE = "0018_e8_nemesis_lifecycle"
BODY_SHA256 = "a07b30c41bda409d6aaa734486170d0141939eae729007269d3b46f2da5e473d"


@pytest.fixture
def chain_database():
    # Global role mutations and dynamic operator provision use only the explicitly
    # separate cluster, never the source agent's cluster or database.
    audit_file = os.environ.get("E8_3_ROLE_AUDIT_CREDENTIALS")
    if not audit_file:
        pytest.fail("Actual chain requires the separately owned role-audit cluster")
    base = PrivatePostgres(**json.loads(Path(audit_file).read_text(encoding="utf-8")))
    ordinary = PrivatePostgres.from_environment()
    own, other = make_url(base.admin_url), make_url(ordinary.admin_url)
    assert own.host in {"127.0.0.1", "::1"}
    assert (own.host, own.port) != (other.host, other.port)
    name = "e8_3_chain_" + uuid4().hex[:12] + "_test"
    private = replace(
        base,
        **{
            field: make_url(getattr(base, field))
            .set(database=name)
            .render_as_string(hide_password=False)
            for field in base.__dataclass_fields__
        },
    )
    catalog = base.engine("admin")
    with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
            .format(sql.Identifier(name))
            .as_string(conn.connection.driver_connection)
        )
        conn.exec_driver_sql(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC")
            .format(sql.Identifier(name))
            .as_string(conn.connection.driver_connection)
        )
        conn.exec_driver_sql(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO calorie_app_api, "
                "e8_3_nemesis_worker_login,calorie_app_deletion_operator"
            )
            .format(sql.Identifier(name))
            .as_string(conn.connection.driver_connection)
        )
    migrator = private.engine()
    api = private.engine("api")
    with migrator.begin() as conn:
        conn.execute(text("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator"))
        conn.execute(text("GRANT USAGE ON SCHEMA app TO calorie_app_api,calorie_app_worker"))
        conn.execute(
            text(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA app GRANT "
                "SELECT,INSERT,UPDATE,DELETE ON TABLES TO "
                "calorie_app_api,calorie_app_worker"
            )
        )
    private.migrate(PARENT)
    operators = []
    yield private, migrator, api, operators
    for engine, identity in operators:
        engine.dispose()
        with private.engine("admin").begin() as conn:
            conn.exec_driver_sql(
                sql.SQL("DROP OWNED BY {}")
                .format(sql.Identifier(identity))
                .as_string(conn.connection.driver_connection)
            )
            conn.exec_driver_sql(
                sql.SQL("DROP ROLE {}")
                .format(sql.Identifier(identity))
                .as_string(conn.connection.driver_connection)
            )
    api.dispose()
    migrator.dispose()
    with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            sql.SQL("DROP DATABASE {} WITH (FORCE)")
            .format(sql.Identifier(name))
            .as_string(conn.connection.driver_connection)
        )
    catalog.dispose()


def checker(engine):
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT owner.rolname,p.prosrc,p.proconfig,p.proacl::text,p.prosecdef,"
                "(SELECT jsonb_agg(jsonb_build_array(t.tgrelid::regclass::text,t.tgname,"
                "t.tgtype,t.tgdeferrable,t.tginitdeferred,t.tgenabled) ORDER BY t.tgrelid) "
                "FROM pg_trigger t WHERE t.tgfoid=p.oid) FROM pg_proc p "
                "JOIN pg_roles owner ON owner.oid=p.proowner "
                "WHERE p.oid='app.diary_aggregate_count()'::regprocedure"
            )
        ).one()
    assert row[0] == "calorie_app_migrator"
    assert hashlib.sha256(row[1].encode()).hexdigest() == BODY_SHA256
    assert row[2] == ["search_path=pg_catalog, pg_temp"]
    return row


def snapshot(engine, tables=None):
    with engine.connect() as conn:
        names = tables or [
            name
            for name in inspect(conn).get_table_names(schema="app")
            if name != "alembic_version"
        ]
        return {
            name: list(
                conn.scalars(
                    text(
                        f'SELECT to_jsonb(row)::text FROM app."{name}" row '
                        "ORDER BY to_jsonb(row)::text"
                    )
                )
            )
            for name in names
        }


def people(engine):
    principals = [Principal("e8-test", str(uuid4()), frozenset({"user"})) for _ in range(2)]
    return principals, [seed(engine, person) for person in principals]


def downgrade(engine, target):
    output = StringIO()
    config = Config(str(ROOT / "backend/alembic.ini"), stdout=output)
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, target)
    return output.getvalue()


@pytest.mark.parametrize("populated", [False, True])
def test_actual_chain_preserves_sources_checker_metadata_and_retained_downgrade(
    chain_database, populated
):
    private, migrator, api, _ = chain_database
    if populated:
        people(api)
        with migrator.begin() as conn:
            for owner in conn.scalars(text("SELECT id FROM app.user_accounts")).all():
                conn.execute(text("SELECT app.e8_refresh(:owner,NULL,256)"), {"owner": owner})
    before, original = snapshot(migrator), checker(migrator)
    assert original[4] is False
    private.migrate(REPAIR)
    repaired = checker(migrator)
    assert repaired[:4] == original[:4] and repaired[4] is True and repaired[5] == original[5]
    assert snapshot(migrator, before) == before
    private.migrate(LIFECYCLE)
    assert checker(migrator) == repaired and snapshot(migrator, before) == before
    with migrator.begin() as conn:
        assert conn.scalar(text("SELECT version_num FROM app.alembic_version")) == LIFECYCLE
        assert not conn.scalar(text("SELECT app.e8n_gate()"))
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_releases")) == 0
    downgrade(migrator, REPAIR)
    assert checker(migrator) == repaired and snapshot(migrator) == before
    warning = downgrade(migrator, PARENT)
    assert "SECURITY DEFINER repair is retained" in warning
    assert checker(migrator) == repaired and snapshot(migrator) == before
    private.migrate(LIFECYCLE)
    assert checker(migrator) == repaired and snapshot(migrator, before) == before


def test_actual_chain_public_gate_is_closed_without_private_capability(chain_database):
    private, migrator, api, _ = chain_database
    principals, owners = people(api)
    private.migrate(LIFECYCLE)
    with migrator.begin() as conn:
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    context = (migrator, api, epoch)
    assert execute(context, (owners[0], principals[0].subject), "issue")["http_status"] == 503
    with migrator.begin() as conn:
        for table in (
            "nemesis_share_codes",
            "nemesis_receipts",
            "nemesis_admissions",
            "nemesis_challenges",
            "nemesis_slots",
        ):
            assert conn.scalar(text(f"SELECT count(*) FROM app.{table}")) == 0


def operator(chain):
    private, _, _, operators = chain
    parsed = make_url(private.admin_url)
    identity, password = "e8_3_chain_operator_" + uuid4().hex[:12], secrets.token_urlsafe(32)
    environment = os.environ | {
        "PGHOST": parsed.host,
        "PGPORT": str(parsed.port),
        "PGDATABASE": parsed.database,
        "PGUSER": parsed.username,
        "PGPASSWORD": parsed.password,
        "DELETION_OPERATOR_LOGIN": identity,
        "DELETION_OPERATOR_PASSWORD": password,
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "infra/local/provision_deletion_operator.py")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(parsed.set(username=identity, password=password), hide_parameters=True)
    operators.append((engine, identity))
    return engine


def mount_private_deletion_seam(migrator):
    # An explicitly test-only adapter establishes the confirmed transaction fence
    # before the own helper, then delegates to the unchanged upstream purge chain.
    with migrator.begin() as conn:
        conn.execute(
            text("""
        CREATE FUNCTION app.e8_3_test_purge_with_nemesis(p_operation uuid) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
        DECLARE job app.account_deletion_jobs%ROWTYPE;
        BEGIN
          SELECT * INTO job FROM app.account_deletion_jobs WHERE operation_id=p_operation;
          IF job.operation_id IS NULL THEN
            RAISE EXCEPTION 'exact deletion job required' USING ERRCODE='23514';
          END IF;
          IF job.purged_at IS NOT NULL THEN RETURN; END IF;
          PERFORM 1 FROM app.user_accounts WHERE id=job.account_id FOR UPDATE;
          PERFORM 1 FROM app.sync_counters WHERE owner_id=job.account_id FOR UPDATE;
          INSERT INTO app._deletion_context VALUES(txid_current(),job.account_id,p_operation);
          PERFORM app.e8n_delete_helper(job.account_id,p_operation,true);
          DELETE FROM app._deletion_context WHERE transaction_id=txid_current();
          PERFORM app.purge_deleted_account(p_operation);
        END $$;
        REVOKE ALL ON FUNCTION app.e8_3_test_purge_with_nemesis(uuid) FROM PUBLIC,
          calorie_app_api,calorie_app_worker,calorie_app_ai_worker,
          calorie_app_motivation_worker,calorie_app_nemesis_worker;
        GRANT EXECUTE ON FUNCTION app.e8_3_test_purge_with_nemesis(uuid)
          TO calorie_app_deletion_operator;
        """)
        )


def test_actual_minimal_login_commit_purges_source_and_nemesis_seam_atomically(chain_database):
    private, migrator, api, _ = chain_database
    principals, owners = people(api)
    owner, partner = owners
    private.migrate(LIFECYCLE)
    immutable_checker = checker(migrator)
    with migrator.begin() as conn:
        conn.execute(text("INSERT INTO app.nemesis_releases VALUES('test','test')"))
        conn.execute(
            text(
                "UPDATE app.nemesis_control SET enabled=true,"
                "projector_revision='test',finalizer_revision='test'"
            )
        )
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ "
                "SELECT TIMESTAMPTZ '2026-10-12 12:00:00+00' $$"
            )
        )
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    context = (migrator, api, epoch)
    challenge = invite(context, (owner, principals[0].subject), (partner, principals[1].subject))
    assert accept(context, (partner, principals[1].subject), challenge)["ok"]
    mount_private_deletion_seam(migrator)
    minimal = operator(chain_database)
    with minimal.begin() as conn:
        assert conn.scalar(text("SELECT current_user=session_user"))
        for table in ("meals", "meal_items", "nemesis_challenges", "nemesis_receipts"):
            assert not conn.scalar(
                text(
                    "SELECT has_any_column_privilege(current_user,:table,"
                    "'SELECT,INSERT,UPDATE,REFERENCES')"
                ),
                {"table": "app." + table},
            )
        assert not conn.scalar(
            text(
                "SELECT has_function_privilege(current_user,"
                "'app.diary_aggregate_count()','EXECUTE')"
            )
        )
    operation = uuid4()
    with minimal.begin() as conn:
        conn.execute(
            text("SELECT app.begin_account_deletion(:owner,:op,1)"),
            {"owner": owner, "op": operation},
        )
    with minimal.begin() as conn:
        conn.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
    before = snapshot(migrator)
    with pytest.raises(RuntimeError, match="before actual commit"), minimal.begin() as conn:
        conn.execute(text("SELECT app.e8_3_test_purge_with_nemesis(:op)"), {"op": operation})
        raise RuntimeError("before actual commit")
    assert snapshot(migrator) == before
    with minimal.begin() as conn:
        conn.execute(text("SELECT app.e8_3_test_purge_with_nemesis(:op)"), {"op": operation})
    with migrator.begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meals WHERE owner_id=:owner"), {"owner": owner}
            )
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meal_items WHERE owner_id=:owner"), {"owner": owner}
            )
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meals WHERE owner_id=:owner"), {"owner": partner}
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meal_items WHERE owner_id=:owner"),
                {"owner": partner},
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT purged_at FROM app.account_deletion_jobs WHERE operation_id=:op"),
                {"op": operation},
            )
            is not None
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.deleted_subjects WHERE subject=:subject"),
                {"subject": principals[0].subject},
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_receipts WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_admissions WHERE owner_id=:owner"),
                {"owner": owner},
            )
            == 0
        )
    with api.begin() as conn:
        safe = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:sub,:epoch,:id)"),
            {"sub": principals[1].subject, "epoch": epoch, "id": challenge["id"]},
        )
        assert safe["response"]["cancel_reason"] == "deleted"
        assert safe["response"]["partner_pseudonym"] is None
    with minimal.begin() as conn:
        conn.execute(text("SELECT app.e8_3_test_purge_with_nemesis(:op)"), {"op": operation})
    assert checker(migrator) == immutable_checker
    with pytest.raises(DBAPIError), minimal.begin() as conn:
        conn.execute(text("SELECT app.diary_aggregate_count()"))
