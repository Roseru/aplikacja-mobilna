"""Real PG regressions for the two independent PR124 acceptance findings."""

import re
import secrets
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from calorie_app.health import EXPECTED_REVISION
from calorie_app.modules.identity import deletion
from tests.integration.test_deletion_ledger import Provider, account, begin, value
from tests.integration.test_e4_operator_login import provision
from tests.support.deletion_regression import harness

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def evidence(engine):
    with engine.connect() as c:
        return {
            "source": c.exec_driver_sql(
                "SELECT to_jsonb(s)-'source_key'-'ack_key',"
                "encode(ledger_crypto.digest(source_key,'sha256'),'hex'),"
                "encode(ledger_crypto.digest(ack_key,'sha256'),'hex') "
                "FROM app.deletion_ledger_source s"
            ).all(),
            "barriers": c.exec_driver_sql(
                "SELECT p.oid::regprocedure::text,pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='app' AND (p.proname ~ '^_ledger_' "
                "OR p.proname IN('begin_account_deletion','confirm_account_deletion',"
                "'purge_deleted_account','ledger_prepare_provider','ledger_provider_result',"
                "'ledger_prepare_purge','ledger_provider_target','ledger_status')) ORDER BY 1"
            ).all(),
            "guard": c.exec_driver_sql(
                "SELECT pg_get_functiondef('app.ledger_downgrade_guard()'::regprocedure)"
            ).scalar_one(),
            "events": c.exec_driver_sql(
                "SELECT to_jsonb(e)::text FROM app.deletion_ledger_events e ORDER BY sequence"
            ).all(),
            "receipts": c.exec_driver_sql(
                "SELECT to_jsonb(r)::text FROM app.deletion_ledger_receipts r ORDER BY received_at"
            ).all(),
        }


def test_neutral_alembic_successor_preserves_evidence_and_atomic_downgrade_guard(
    database, tmp_path
):
    engine, _, _ = database
    h = harness(engine)
    owner = account(engine)
    operation = begin(engine, owner)
    h.deliver()
    before = evidence(engine)
    scripts = tmp_path / "migrations"
    shutil.copytree(ROOT / "backend/migrations", scripts)
    # Deliberately nonnumeric: migration ordering comes from the Alembic graph.
    revision = "ledger_successor_probe"
    (scripts / "versions/review_probe.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        f"revision = {revision!r}\ndown_revision = {EXPECTED_REVISION!r}\n"
        "def upgrade():\n"
        "    op.add_column('user_accounts', sa.Column('ledger_review_probe', "
        "sa.Integer()), schema='app')\n"
        "def downgrade():\n"
        "    op.drop_column('user_accounts', 'ledger_review_probe', schema='app')\n",
        encoding="utf-8",
    )
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(scripts))

    def migrate(action, target):
        with engine.begin() as c:
            c.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = c
            try:
                getattr(command, action)(config, target)
            finally:
                config.attributes.pop("connection", None)

    try:
        migrate("upgrade", revision)
        assert value(engine, "SELECT version_num FROM app.alembic_version") == revision
        assert evidence(engine) == before
        assert (
            value(engine, "SELECT state FROM app.user_accounts WHERE id=:id", id=owner)
            == "deleting"
        )
        with pytest.raises(
            DBAPIError, match="cannot downgrade deletion safety below0024"
        ) as denied:
            migrate("downgrade", "0023_e9_qualification")
        assert denied.value.orig.sqlstate == "23514"
        assert value(engine, "SELECT version_num FROM app.alembic_version") == revision
        assert (
            value(
                engine,
                "SELECT count(*) FROM information_schema.columns WHERE table_schema='app' "
                "AND table_name='user_accounts' AND column_name='ledger_review_probe'",
            )
            == 1
        )
        assert evidence(engine) == before
        with engine.begin() as c:
            c.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
            with pytest.raises(DBAPIError), c.begin_nested():
                c.exec_driver_sql("SELECT * FROM app.account_deletion_jobs")
            assert (
                c.scalar(text("SELECT app.ledger_status(:op)"), {"op": operation})["purged_at"]
                is None
            )
    finally:
        if value(engine, "SELECT version_num FROM app.alembic_version") == revision:
            migrate("downgrade", EXPECTED_REVISION)


@pytest.mark.parametrize(
    "grant_to,signature",
    [
        (target, "app.ledger_configure(text,uuid,bytea,bytea)")
        for target in ("login", "role", "public")
    ]
    + [
        ("login", signature)
        for signature in (
            "app.ledger_ack(uuid,uuid,uuid,uuid,bigint,text,text)",
            "app.ledger_batch(bigint,integer)",
            "app.ledger_export_position()",
            "app._ledger_source_ready()",
        )
    ],
)
def test_operator_provision_refuses_effective_configure_and_rolls_back(
    database, grant_to, signature
):
    engine, _, url = database
    login = "review_operator_" + uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    operator = None
    target = {"login": f'"{login}"', "role": "calorie_app_deletion_operator", "public": "PUBLIC"}[
        grant_to
    ]
    try:
        provision(url, login, password)
        operator = create_engine(
            engine.url.set(username=login, password=password), hide_parameters=True
        )
        before = evidence(engine)
        with engine.begin() as c:
            original_verifier = c.scalar(
                text("SELECT rolpassword FROM pg_authid WHERE rolname=:login"), {"login": login}
            )
            c.exec_driver_sql(f"GRANT EXECUTE ON FUNCTION {signature} TO {target}")
        with operator.connect() as c:
            assert c.exec_driver_sql("SELECT session_user,current_user").one() == (login, login)
            assert c.scalar(
                text("SELECT has_function_privilege(current_user,:f,'EXECUTE')"), {"f": signature}
            )
            assert not c.scalar(
                text("SELECT pg_has_role(current_user,'calorie_app_migrator','MEMBER')")
            )
        provision(url, login, secrets.token_urlsafe(32), expect_success=False)
        assert evidence(engine) == before
        with engine.begin() as c:
            assert (
                c.scalar(
                    text("SELECT rolpassword FROM pg_authid WHERE rolname=:login"), {"login": login}
                )
                == original_verifier
            )
            assert c.scalar(
                text("SELECT has_function_privilege(:login,:f,'EXECUTE')"),
                {"login": login, "f": signature},
            )
            c.exec_driver_sql(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {target}")
        provision(url, login, password)
        with operator.begin() as c:
            with pytest.raises(DBAPIError, match="permission denied"), c.begin_nested():
                c.execute(
                    text("SELECT app.ledger_configure(:issuer,:receiver,:source,:ack)"),
                    {
                        "issuer": "https://review.invalid/realms/synthetic",
                        "receiver": uuid4(),
                        "source": b"s" * 32,
                        "ack": b"a" * 32,
                    },
                )
        assert evidence(engine) == before
    finally:
        if operator is not None:
            operator.dispose()
        with engine.begin() as c:
            c.exec_driver_sql(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {target}")
            if c.scalar(
                text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname=:login)"), {"login": login}
            ):
                c.exec_driver_sql(f'DROP OWNED BY "{login}"')
                c.exec_driver_sql(f'DROP ROLE "{login}"')


def test_guard_denied_revisions_match_actual_unsafe_ancestry(database):
    engine, _, _ = database
    scripts = ScriptDirectory.from_config(Config(str(ROOT / "backend/alembic.ini")))
    unsafe = {r.revision for r in scripts.iterate_revisions("0023_e9_qualification", "base")}
    before = evidence(engine)
    stored = set(re.findall(r"'(\d{4}_[a-z0-9_]+)'", before["guard"]))
    assert stored == unsafe
    marker = value(engine, "SELECT version_num FROM app.alembic_version")
    with engine.begin() as c:
        for revision in unsafe:
            with (
                pytest.raises(
                    DBAPIError, match="cannot downgrade deletion safety below0024"
                ) as denied,
                c.begin_nested(),
            ):
                c.execute(text("UPDATE app.alembic_version SET version_num=:r"), {"r": revision})
            assert denied.value.orig.sqlstate == "23514"
    assert value(engine, "SELECT version_num FROM app.alembic_version") == marker
    assert evidence(engine) == before


def test_populated_0025_upgrade_keeps_identity_evidence_and_corrected_guard(
    historical_database, tmp_path
):
    from tests.support.ledger import LedgerHarness

    engine, _, _ = historical_database
    config = Config(str(ROOT / "backend/alembic.ini"))

    def migrate(action, revision):
        with engine.begin() as c:
            c.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
            config.attributes["connection"] = c
            try:
                getattr(command, action)(config, revision)
            finally:
                config.attributes.pop("connection", None)

    migrate("upgrade", "0025_deletion_ledger")
    assert value(engine, "SELECT version_num FROM app.alembic_version") == "0025_deletion_ledger"
    h = LedgerHarness(engine, tmp_path)
    try:
        owner = account(engine)
        other = account(engine)
        operation = begin(engine, owner)
        h.deliver()
        before = evidence(engine)
        migrate("upgrade", "head")
        after = evidence(engine)
        assert {k: v for k, v in before.items() if k != "guard"} == {
            k: v for k, v in after.items() if k != "guard"
        }
        assert before["guard"] != after["guard"]
        assert value(engine, "SELECT version_num FROM app.alembic_version") == EXPECTED_REVISION
        assert value(engine, "SELECT generation FROM app.user_accounts WHERE id=:id", id=owner) == 2
        assert (
            value(engine, "SELECT state FROM app.user_accounts WHERE id=:id", id=other) == "active"
        )
        for target in ("0025_deletion_ledger", "0024_e9_history_graph"):
            migrate("downgrade", target)
            assert evidence(engine) == after
            with pytest.raises(
                DBAPIError, match="cannot downgrade deletion safety below0024"
            ) as denied:
                migrate("downgrade", "0023_e9_qualification")
            assert denied.value.orig.sqlstate == "23514"
            assert value(engine, "SELECT version_num FROM app.alembic_version") == target
            assert evidence(engine) == after
            migrate("upgrade", "head")
            assert evidence(engine) == after
        assert deletion.resume(engine, operation, Provider(), delivery=h.deliver)["ledger_complete"]
        assert value(engine, "SELECT count(*) FROM app.user_accounts WHERE id=:id", id=owner) == 0
        assert (
            value(engine, "SELECT state FROM app.user_accounts WHERE id=:id", id=other) == "active"
        )
    finally:
        h.close()


@pytest.mark.parametrize(
    "profile,prefix,base",
    [
        ("nemesis_worker", "NEMESIS_WORKER", "calorie_app_nemesis_worker"),
        ("nemesis_finalizer", "NEMESIS_FINALIZER", "calorie_app_nemesis_finalizer"),
    ],
)
def test_existing_0025_e8_provisioners_remain_compatible(
    historical_database, profile, prefix, base
):
    from tests.integration.test_deletion_ledger import assert_real_e8_provisioner_keeps_minimal_acl

    engine, _, _ = historical_database
    config = Config(str(ROOT / "backend/alembic.ini"))
    with engine.begin() as c:
        c.exec_driver_sql("SET LOCAL ROLE calorie_app_migrator")
        config.attributes["connection"] = c
        command.upgrade(config, "0025_deletion_ledger")
    assert value(engine, "SELECT version_num FROM app.alembic_version") == "0025_deletion_ledger"
    assert_real_e8_provisioner_keeps_minimal_acl(engine, profile, prefix, base)
