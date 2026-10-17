"""Actual production deletion wrappers and fenced restore in additive0020."""

import hashlib
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak.admin import AdminFailure
from calorie_app.modules.ai.service import create_analysis
from tests.integration.test_e7_runtime import METADATA, image, private_root
from tests.integration.test_e8_3_chain import (
    ROOT,
    checker,
    operator,
    people,
    snapshot,
)
from tests.integration.test_e8_3_chain import (
    chain_database as chain_database,
)
from tests.integration.test_e8_3_database import accept, execute, invite
from tests.support.deletion_regression import begin, resume
from tests.support.e8_3_archive import archive_environment, pg_command

pytestmark = pytest.mark.integration
PARENT = "0019_e8_nemesis_maintenance"
INTEGRATION = "0020_e8_nemesis_integration"


def migrate(chain, action, revision):
    private, migrator, _, _ = chain
    if action == "upgrade":
        private.migrate(revision)
        return
    config = Config(str(ROOT / "backend/alembic.ini"))
    with migrator.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, revision)


def procedures(engine, names):
    with engine.connect() as conn:
        return {
            name: conn.execute(
                text(
                    "SELECT prosrc,proowner::regrole::text,proconfig,proacl::text,prosecdef "
                    "FROM pg_proc WHERE oid=CAST(:signature AS regprocedure)"
                ),
                {"signature": "app." + name},
            ).one()
            for name in names
        }


@pytest.mark.parametrize("filled", [False, True])
def test_actual19_to20_preserves_source_rows_parent_chain_checker_and_empty_reverse(
    chain_database, filled
):
    private, migrator, api, _ = chain_database
    migrate(chain_database, "upgrade", PARENT)
    if filled:
        people(api)
    before = snapshot(migrator)
    names = [
        "begin_account_deletion(uuid,uuid,integer)",
        "purge_deleted_account(uuid)",
        "confirm_account_deletion(uuid)",
        "purge_deleted_account_e7(uuid)",
        "purge_deleted_account_e6(uuid)",
        "purge_deleted_account_e5(uuid)",
    ]
    original = procedures(migrator, names)
    checker_before = checker(migrator)
    migrate(chain_database, "upgrade", INTEGRATION)
    assert snapshot(migrator) == before
    inner = procedures(migrator, names[2:])
    assert inner == {name: original[name] for name in names[2:]}
    aliases = procedures(
        migrator,
        ["begin_account_deletion_e8_19(uuid,uuid,integer)", "purge_deleted_account_e8_19(uuid)"],
    )
    for old, internal in zip(names[:2], aliases.values(), strict=True):
        assert internal[:3] == original[old][:3] and internal[4] == original[old][4]
        assert "calorie_app_deletion_operator" not in internal[3]
    assert checker(migrator) == checker_before
    migrate(chain_database, "downgrade", PARENT)
    assert procedures(migrator, names) == original and snapshot(migrator) == before
    assert checker(migrator) == checker_before
    migrate(chain_database, "upgrade", INTEGRATION)
    assert snapshot(migrator) == before
    assert checker(migrator) == checker_before


@pytest.fixture
def production(chain_database):
    private, migrator, api, _ = chain_database
    migrate(chain_database, "upgrade", PARENT)
    principals, owners = people(api)
    migrate(chain_database, "upgrade", INTEGRATION)
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
    challenge = invite(
        context, (owners[0], principals[0].subject), (owners[1], principals[1].subject)
    )
    accepted = accept(context, (owners[1], principals[1].subject), challenge)
    assert accepted["ok"]
    minimal = operator(chain_database)
    return {
        "chain": chain_database,
        "migrator": migrator,
        "api": api,
        "context": context,
        "principals": principals,
        "owners": owners,
        "challenge": challenge,
        "operator": minimal,
        "epoch": epoch,
    }


def metadata_for_partner(state):
    with state["api"].begin() as conn:
        return conn.scalar(
            text("SELECT app.e8n_read('e8-test',:subject,:epoch,:id)"),
            {
                "subject": state["principals"][1].subject,
                "epoch": state["epoch"],
                "id": state["challenge"]["id"],
            },
        )


def test_production_begin_cuts_sharing_before_provider_and_rollbacks_confirmation(production):
    state = production
    owner, partner = state["owners"]
    operation = uuid4()
    with state["operator"].begin() as conn:
        assert conn.scalar(text("SELECT current_user=session_user"))
        job = begin(conn, owner, operation, 1)
        assert job["deleting_generation"] == 2 and job["identity_confirmed_at"] is None
    assert metadata_for_partner(state)["code"] == "nemesis_not_found"
    with state["migrator"].connect() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                {"id": state["challenge"]["id"]},
            )
            == "cancelled"
        )
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_slots")) == 0
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meals WHERE owner_id=:owner"), {"owner": owner}
            )
            == 1
        )

    class FailedProvider:
        def delete_and_confirm(self, *_):
            raise AdminFailure()

    with pytest.raises(AdminFailure):
        resume(state["operator"], operation, FailedProvider())
    with pytest.raises(RuntimeError), state["operator"].begin() as conn:
        conn.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
        raise RuntimeError("confirmation before commit")
    with state["migrator"].connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT identity_confirmed_at FROM app.account_deletion_jobs "
                    "WHERE operation_id=:op"
                ),
                {"op": operation},
            )
            is None
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meals WHERE owner_id=:owner"), {"owner": owner}
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meals WHERE owner_id=:owner"), {"owner": partner}
            )
            == 1
        )
    with pytest.raises(DBAPIError), state["operator"].begin() as conn:
        conn.execute(text("SELECT app.purge_deleted_account(:op)"), {"op": operation})


def test_production_resume_commits_full_graph_nm_cleanup_intents_and_anonymous_budget(
    production, tmp_path
):
    state = production
    owner, partner = state["owners"]
    settings = Settings(
        database_url=state["api"].url.render_as_string(hide_password=False),
        environment="test",
        ai_photo_root=private_root(tmp_path / "photos"),
    )
    analysis = create_analysis(
        state["api"], state["principals"][0], state["epoch"], uuid4(), METADATA, image(), settings
    )
    assert analysis.status == 202
    attempt = uuid4()
    with state["migrator"].begin() as conn:
        job_id = conn.scalar(
            text("SELECT id FROM app.ai_jobs WHERE owner_id=:owner"), {"owner": owner}
        )
        reserved = conn.scalar(
            text(
                "SELECT app.e7_reserve('mock:local:mock-food-v1:local',"
                "'food_photo','count_tokens',:job,0,:attempt,:worker)"
            ),
            {"job": job_id, "attempt": attempt, "worker": uuid4()},
        )
        assert "error" not in reserved
        anonymous_before = conn.scalar(
            text("SELECT (to_jsonb(row)-'job_id')::text FROM app.ai_attempts row WHERE id=:id"),
            {"id": attempt},
        )
    operation = uuid4()
    with state["operator"].begin() as conn:
        begin(conn, owner, operation, 1)

    class Confirmed:
        def delete_and_confirm(self, issuer, subject):
            assert (issuer, subject) == (
                state["principals"][0].issuer,
                state["principals"][0].subject,
            )

    with pytest.raises(RuntimeError, match="purge_committed"):
        resume(
            state["operator"],
            operation,
            Confirmed(),
            barrier=lambda stage: (
                (_ for _ in ()).throw(RuntimeError(stage)) if stage == "purge_committed" else None
            ),
        )

    class NoProvider:
        def delete_and_confirm(self, *_):
            raise AssertionError("confirmed protocol must not contact provider again")

    completed = resume(state["operator"], operation, NoProvider())
    assert completed["purged_at"] is not None
    assert resume(state["operator"], operation, NoProvider()) == completed
    with state["migrator"].connect() as conn:
        for table in (
            "meals",
            "meal_items",
            "weights",
            "user_profiles",
            "nemesis_receipts",
            "nemesis_admissions",
            "nemesis_share_codes",
            "nemesis_cursors",
        ):
            column = "requester_id" if table == "nemesis_cursors" else "owner_id"
            assert (
                conn.scalar(
                    text(f"SELECT count(*) FROM app.{table} WHERE {column}=:owner"),
                    {"owner": owner},
                )
                == 0
            )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.meal_items WHERE owner_id=:owner"),
                {"owner": partner},
            )
            == 1
        )
        assert conn.scalar(text("SELECT count(*) FROM app._deletion_context")) == 0
        assert conn.scalar(text("SELECT count(*) FROM app.ai_cleanup_intents")) == 1
        assert (
            conn.scalar(text("SELECT job_id FROM app.ai_attempts WHERE id=:id"), {"id": attempt})
            is None
        )
        assert conn.scalar(
            text("SELECT (to_jsonb(row)-'job_id')::text FROM app.ai_attempts row WHERE id=:id"),
            {"id": attempt},
        ) == (anonymous_before)
    safe = metadata_for_partner(state)["response"]
    assert safe["status"] == "cancelled" and safe["cancel_reason"] == "deleted"
    assert safe["partner_pseudonym"] is None
    with state["operator"].begin() as conn:
        assert begin(conn, owner, operation, 1)["purged_at"] == completed["purged_at"]


def test_production_raw_operator_cannot_bypass_fences_parents_context_or_restore(production):
    state = production
    for statement in (
        "SELECT app.begin_account_deletion_e8_19(NULL,NULL,1)",
        "SELECT app.purge_deleted_account_e8_19(NULL)",
        "SELECT app.e8n_delete_helper(NULL,NULL,false)",
        "SELECT app.e8n_restore_maintain(1)",
        "INSERT INTO app._deletion_context VALUES"
        "(txid_current(),gen_random_uuid(),gen_random_uuid())",
        "DELETE FROM app.meals",
        "UPDATE app.nemesis_control SET enabled=true",
    ):
        with pytest.raises(DBAPIError) as denied, state["operator"].begin() as conn:
            conn.execute(text(statement))
        assert denied.value.orig.sqlstate == "42501"
    owner = state["owners"][0]
    with pytest.raises(DBAPIError) as invalid, state["operator"].begin() as conn:
        begin(conn, owner, uuid4(), 2)
    assert invalid.value.orig.sqlstate == "23514"
    assert metadata_for_partner(state)["response"]["status"] == "active"


def test_historical_operator_cli_uses_actual_parent_and_durable_retry(production, tmp_path):
    state = production
    operation = uuid4()
    config = tmp_path / "no-provider.json"
    config.write_text("[]", encoding="utf-8")
    environment = os.environ | {
        "DELETION_DATABASE_URL": state["operator"].url.render_as_string(hide_password=False),
        "KEYCLOAK_ADMIN_CONFIG": str(config),
        "PYTHONPATH": os.pathsep.join([str(ROOT / "backend"), str(ROOT / "backend/src")]),
    }

    # The current CLI deliberately refuses this pre-ledger schema.
    unsupported = subprocess.run(
        [
            sys.executable,
            "-m",
            "calorie_app.modules.identity.deletion",
            "status",
            "--operation-id",
            str(operation),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert unsupported.returncode != 0 and not unsupported.stdout

    # Frozen pre-ledger CLI for this historical migration scope.
    def cli(action, *arguments):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.support.legacy_deletion",
                action,
                "--operation-id",
                str(operation),
                *arguments,
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    cli("begin", "--account-id", str(state["owners"][0]), "--expected-generation", "1")
    assert metadata_for_partner(state)["code"] == "nemesis_not_found"
    with state["operator"].begin() as conn:
        conn.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
    completed = cli("resume")
    assert completed["purged_at"] is not None
    assert cli("resume") == cli("status") == completed


def test_nonempty_downgrade_refuses_before_any_wrapper_or_source_ddl(production):
    state = production
    signatures = [
        "begin_account_deletion(uuid,uuid,integer)",
        "purge_deleted_account(uuid)",
        "e8n_restore_maintain(integer)",
        "e8n_source_lock(uuid,integer,uuid,text,date[],date[],boolean)",
    ]
    before_procs, before_rows = (
        procedures(state["migrator"], signatures),
        snapshot(state["migrator"]),
    )
    with pytest.raises(DBAPIError) as refusal:
        migrate(state["chain"], "downgrade", PARENT)
    assert refusal.value.orig.sqlstate == "23514"
    assert procedures(state["migrator"], signatures) == before_procs
    assert snapshot(state["migrator"]) == before_rows


def test_restore_new_epoch_bounded_cancellation_clears_old_payloads_without_reopen(production):
    state = production
    owner, partner = state["owners"]
    second_code = execute(state["context"], (owner, state["principals"][0].subject), "issue")
    assert second_code["ok"]
    with state["api"].begin() as conn:
        # Mint a genuine bounded metadata cursor with another synthetic invitation.
        recipient = execute(state["context"], (partner, state["principals"][1].subject), "issue")
    digest = hashlib.sha256(recipient["response"]["destination_code"].encode()).hexdigest()
    another = execute(
        state["context"],
        (owner, state["principals"][0].subject),
        "create",
        {"destination_digest": digest, "terms": state["challenge"]["terms"]},
    )
    assert another["ok"]
    with state["api"].begin() as conn:
        page = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:subject,:epoch,NULL,1,NULL)"),
            {"subject": state["principals"][0].subject, "epoch": state["epoch"]},
        )
        assert page["response"]["next_cursor"]
    with pytest.raises(DBAPIError), state["migrator"].begin() as conn:
        conn.execute(text("SELECT app.e8n_restore_maintain(1)"))
    original_rows = snapshot(state["migrator"])
    original_receipts = [
        (
            row["owner_id"],
            row["operation"],
            row["key"],
            row["request_hash"],
            row["generation"],
            row["sync_epoch"],
            row["entity_id"],
            row["accepted_revision"],
            row["http_status"],
            row["code"],
        )
        for text_row in original_rows["nemesis_receipts"]
        for row in [json.loads(text_row)]
    ]
    new_epoch = uuid4()
    with state["migrator"].begin() as conn:
        conn.execute(text("UPDATE app.nemesis_control SET enabled=false"))
        conn.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": new_epoch}
        )
    with state["api"].begin() as conn:
        denied = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:subject,:epoch,:id)"),
            {
                "subject": state["principals"][1].subject,
                "epoch": new_epoch,
                "id": state["challenge"]["id"],
            },
        )
        assert denied["code"] == "nemesis_not_found"
    batches = []
    while True:
        with state["migrator"].begin() as conn:
            result = conn.scalar(text("SELECT app.e8n_restore_maintain(1)"))
        assert all(
            result[name] <= 1
            for name in ("cancelled", "responses_pruned", "codes_pruned", "cursors_pruned")
        )
        batches.append(result)
        if result["pending"] == 0:
            break
        assert len(batches) < 20
    with state["migrator"].connect() as conn:
        assert not conn.scalar(text("SELECT app.e8n_gate()"))
        assert (
            conn.scalar(text("SELECT sync_epoch FROM app.nemesis_control WHERE id=1"))
            == state["epoch"]
        )
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_slots")) == 0
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_share_codes")) == 0
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_cursors")) == 0
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_receipts WHERE response IS NOT NULL")
            )
            == 0
        )
        current = list(
            conn.execute(
                text(
                    "SELECT owner_id,operation,key,request_hash,generation,"
                    "sync_epoch,entity_id,accepted_revision,http_status,code "
                    "FROM app.nemesis_receipts"
                )
            )
        )
        assert sorted(tuple(map(str, row)) for row in current) == (
            sorted(tuple(map(str, row)) for row in original_receipts)
        )
        assert all(
            row.status == "cancelled" and row.cancel_reason == "restore"
            for row in conn.execute(text("SELECT status,cancel_reason FROM app.nemesis_challenges"))
        )
    with state["migrator"].begin() as conn:
        assert conn.scalar(text("SELECT app.e8n_restore_maintain(1)"))["pending"] == 0


def test_purge_takes_shared_globals_before_challenge_phase(production):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue

    state = production
    operation = uuid4()
    with state["operator"].begin() as conn:
        begin(conn, state["owners"][0], operation, 1)
    with state["operator"].begin() as conn:
        conn.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
    pids = Queue()
    with state["migrator"].connect() as holder, holder.begin() as transaction:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        holder.execute(text("SELECT 1 FROM app.community_catalog_state WHERE id=1 FOR UPDATE"))

        def purge():
            with state["operator"].begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout='15s'"))
                pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
                conn.execute(text("SELECT app.purge_deleted_account(:op)"), {"op": operation})

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(purge)
            worker_pid = pids.get(timeout=10)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                blockers = holder.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid})
                if holder_pid in blockers:
                    break
            else:
                pytest.fail("production purge did not reach observed global-row barrier")
            # If the helper ran before the global lock, this NOWAIT would fail.
            with state["migrator"].begin() as checker_connection:
                checker_connection.execute(
                    text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": state["challenge"]["id"]},
                )
            transaction.commit()
            pending.result(timeout=15)
    with state["migrator"].connect() as conn:
        assert (
            conn.scalar(
                text("SELECT purged_at FROM app.account_deletion_jobs WHERE operation_id=:op"),
                {"op": operation},
            )
            is not None
        )


@pytest.mark.parametrize("tamper", ["body", "owner", "path", "public_acl"])
def test0020_rejects_tampered_parent_before_any_alias_or_ddl(chain_database, tamper):
    private, migrator, _, _ = chain_database
    migrate(chain_database, "upgrade", PARENT)
    admin = private.engine("admin")
    try:
        with admin.begin() as conn:
            if tamper == "body":
                conn.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION app.begin_account_deletion("
                        "p_owner uuid,p_operation uuid,p_generation integer) RETURNS uuid "
                        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp "
                        "AS $$ BEGIN RETURN p_operation; END $$"
                    )
                )
            elif tamper == "owner":
                conn.execute(
                    text(
                        "ALTER FUNCTION app.begin_account_deletion(uuid,uuid,integer) "
                        "OWNER TO calorie_app_api"
                    )
                )
            elif tamper == "path":
                conn.execute(
                    text(
                        "ALTER FUNCTION app.begin_account_deletion(uuid,uuid,integer) "
                        "SET search_path=public,pg_temp"
                    )
                )
            else:
                conn.execute(
                    text(
                        "GRANT EXECUTE ON FUNCTION "
                        "app.begin_account_deletion(uuid,uuid,integer) TO PUBLIC"
                    )
                )
        names = ["begin_account_deletion(uuid,uuid,integer)", "purge_deleted_account(uuid)"]
        before = procedures(migrator, names)
        before_rows = snapshot(migrator)
        with pytest.raises(DBAPIError) as refusal:
            migrate(chain_database, "upgrade", INTEGRATION)
        assert refusal.value.orig.sqlstate == "23514"
        assert procedures(migrator, names) == before and snapshot(migrator) == before_rows
        with migrator.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM app.alembic_version")) == PARENT
            assert (
                conn.scalar(
                    text(
                        "SELECT to_regprocedure("
                        "'app.begin_account_deletion_e8_19(uuid,uuid,integer)')"
                    )
                )
                is None
            )
    finally:
        admin.dispose()


def test_actual_archive_cannot_resurrect_withdrawn_sharing_after_new_epoch(production, tmp_path):
    from psycopg import sql
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    state = production
    private = state["chain"][0]
    parsed = make_url(private.migrator_url)
    root = private_root(tmp_path / "archive")
    archive = root / "before-withdrawal.dump"
    environment = archive_environment(parsed)
    with archive.open("wb") as output:
        dump = subprocess.run(
            pg_command("pg_dump", ["--format=custom", "--dbname", parsed.database], environment),
            stdout=output,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=30,
        )
    assert dump.returncode == 0 and archive.stat().st_size > 0, "PG17 archive creation failed"
    withdrawn = execute(
        state["context"],
        (state["owners"][0], state["principals"][0].subject),
        "cancel",
        {"challenge_id": state["challenge"]["id"], "revision": 2, "reason": "sharing_revoked"},
    )
    assert withdrawn["ok"] and withdrawn["response"]["status"] == "cancelled"
    restore_name = "e8_3_archive_" + uuid4().hex[:12] + "_test"
    admin = private.engine("admin")
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
            .format(sql.Identifier(restore_name))
            .as_string(conn.connection.driver_connection)
        )
        conn.exec_driver_sql(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC")
            .format(sql.Identifier(restore_name))
            .as_string(conn.connection.driver_connection)
        )
        conn.exec_driver_sql(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO calorie_app_api")
            .format(sql.Identifier(restore_name))
            .as_string(conn.connection.driver_connection)
        )
    restored = create_engine(parsed.set(database=restore_name), hide_parameters=True)
    restored_api = create_engine(
        make_url(private.api_url).set(database=restore_name), hide_parameters=True
    )
    try:
        with archive.open("rb") as input_archive:
            restore = subprocess.run(
                pg_command(
                    "pg_restore",
                    ["--exit-on-error", "--dbname", restore_name],
                    environment,
                    interactive=True,
                ),
                stdin=input_archive,
                capture_output=True,
                env=environment,
                timeout=30,
            )
        assert restore.returncode == 0, "PG17 archive restoration failed"
        with restored.begin() as conn:
            assert (
                conn.scalar(
                    text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                    {"id": state["challenge"]["id"]},
                )
                == "active"
            )
            # Restored copied consent is not permitted to escape the new epoch.
            conn.execute(text("UPDATE app.nemesis_control SET enabled=false"))
            new_epoch = uuid4()
            conn.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": new_epoch}
            )
        with restored_api.begin() as conn:
            read = conn.scalar(
                text("SELECT app.e8n_read('e8-test',:subject,:epoch,:id)"),
                {
                    "subject": state["principals"][1].subject,
                    "epoch": new_epoch,
                    "id": state["challenge"]["id"],
                },
            )
            assert read["code"] == "nemesis_not_found"
        while True:
            with restored.begin() as conn:
                result = conn.scalar(text("SELECT app.e8n_restore_maintain(1)"))
            if result["pending"] == 0:
                break
        with restored.connect() as conn:
            assert (
                conn.scalar(
                    text("SELECT status FROM app.nemesis_challenges WHERE id=:id"),
                    {"id": state["challenge"]["id"]},
                )
                == "cancelled"
            )
            assert conn.scalar(text("SELECT count(*) FROM app.nemesis_slots")) == 0
            assert not conn.scalar(text("SELECT app.e8n_gate()"))
            assert (
                conn.scalar(
                    text("SELECT count(*) FROM app.nemesis_receipts WHERE response IS NOT NULL")
                )
                == 0
            )
    finally:
        restored_api.dispose()
        restored.dispose()
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(
                sql.SQL("DROP DATABASE {} WITH (FORCE)")
                .format(sql.Identifier(restore_name))
                .as_string(conn.connection.driver_connection)
            )
        admin.dispose()
