"""Maintenance fairness, transactional recheck and immutable 0018 -> 0019 repair."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import StringIO
from pathlib import Path
from queue import Queue
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
PARENT = "0018_e8_nemesis_lifecycle"
REPAIR = "0019_e8_nemesis_maintenance"
ORIGINAL_BODY = "d34581def320c114e3e1e2325eccc5533f4c82d392268bc41afe81a22667ccc0"
REPAIRED_BODY = "8dcd70d6869792f297df482285b683393cd7a9eb6c273c4c8e2d235ed4a56a61"
CLOCK = "2026-01-20 12:00:00+00"
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 90,
    "time_zone": "UTC",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}


@pytest.fixture
def maintenance_database():
    private_file = os.environ.get("E8_3_ROLE_AUDIT_CREDENTIALS")
    if not private_file:
        pytest.fail("Maintenance evidence requires owned PostgreSQL credentials")
    base = PrivatePostgres(**json.loads(Path(private_file).read_text(encoding="utf-8")))
    parsed = make_url(base.admin_url)
    assert parsed.host in {"127.0.0.1", "::1"} and parsed.database.endswith("_test")
    name = "e8_3_maintenance_" + uuid4().hex[:12] + "_test"
    private = replace(
        base,
        **{
            key: make_url(getattr(base, key))
            .set(database=name)
            .render_as_string(hide_password=False)
            for key in base.__dataclass_fields__
        },
    )
    catalog, migrator, worker, api = (
        base.engine("admin"),
        private.engine(),
        private.engine("worker"),
        private.engine("api"),
    )
    with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        driver = conn.connection.driver_connection
        conn.exec_driver_sql(
            sql.SQL("CREATE DATABASE {} OWNER calorie_app_migrator")
            .format(sql.Identifier(name))
            .as_string(driver)
        )
        conn.exec_driver_sql(
            sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC")
            .format(sql.Identifier(name))
            .as_string(driver)
        )
        conn.exec_driver_sql(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO calorie_app_api,e8_3_nemesis_worker_login")
            .format(sql.Identifier(name))
            .as_string(driver)
        )
    with migrator.begin() as conn:
        conn.execute(text("CREATE SCHEMA app AUTHORIZATION calorie_app_migrator"))
        conn.execute(text("GRANT USAGE ON SCHEMA app TO calorie_app_api,calorie_app_worker"))
    private.migrate(PARENT)
    state = {"pg": private, "migrator": migrator, "worker": worker, "api": api}
    set_clock(state, CLOCK)
    yield state
    for engine in (api, worker, migrator):
        engine.dispose()
    with catalog.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(
            sql.SQL("DROP DATABASE {} WITH (FORCE)")
            .format(sql.Identifier(name))
            .as_string(conn.connection.driver_connection)
        )
    catalog.dispose()


def set_clock(state, instant, connection=None):
    # Updating a private clock row makes time observable inside an already
    # running function. Replacing a constant function body mid-call can retain
    # the caller's cached body and is not a faithful clock-advancement probe.
    def apply(conn):
        if conn.scalar(text("SELECT to_regclass('app.e8_3_maintenance_test_clock')")) is None:
            conn.execute(
                text(
                    "CREATE TABLE app.e8_3_maintenance_test_clock "
                    "(id integer PRIMARY KEY CHECK(id=1),instant timestamptz NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "REVOKE ALL ON app.e8_3_maintenance_test_clock FROM PUBLIC,"
                    "calorie_app_api,calorie_app_worker,calorie_app_ai_worker,"
                    "calorie_app_motivation_worker,calorie_app_nemesis_worker,"
                    "calorie_app_deletion_operator"
                )
            )
            conn.execute(
                text(
                    "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                    "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ "
                    "SELECT instant FROM app.e8_3_maintenance_test_clock WHERE id=1 $$"
                )
            )
        conn.execute(
            text(
                "INSERT INTO app.e8_3_maintenance_test_clock VALUES(1,"
                "CAST(:instant AS timestamptz)) ON CONFLICT(id) "
                "DO UPDATE SET instant=EXCLUDED.instant"
            ),
            {"instant": instant},
        )

    if connection is not None:
        apply(connection)
    else:
        with state["migrator"].begin() as conn:
            apply(conn)


def upgrade(state):
    # The same permanent progress oracle can reproduce RED on published 0018.
    revision = os.environ.get("E8_3_MAINTENANCE_REVISION", REPAIR)
    assert revision in {PARENT, REPAIR}
    state["pg"].migrate(revision)


def seed_graph(state, prefix=1, due_invite=True, due_active=True):
    records = [(UUID(int=n + 1), "active", 90) for n in range(prefix)]
    if due_invite:
        records.append((UUID(int=10001), "invited", 90))
    if due_active:
        records.append((UUID(int=10002), "active", 7))
    with state["migrator"].begin() as conn:
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
        for index, (identity, status, duration) in enumerate(records):
            owners = (UUID(int=100000 + index * 2), UUID(int=100001 + index * 2))
            for owner in owners:
                conn.execute(
                    text(
                        "INSERT INTO app.user_accounts(id,issuer,subject) "
                        "VALUES(:id,'maintenance-test',:subject)"
                    ),
                    {"id": owner, "subject": str(owner)},
                )
                conn.execute(
                    text("INSERT INTO app.sync_counters(owner_id) VALUES(:id)"), {"id": owner}
                )
                conn.execute(
                    text(
                        "INSERT INTO app.user_profiles(id,owner_id,revision,"
                        "pseudonym,activity_class,time_zone) "
                        "VALUES(:profile,:id,1,'Participant','stationary','UTC')"
                    ),
                    {"profile": uuid4(), "id": owner},
                )
            parameters = {
                "id": identity,
                "a": owners[0],
                "b": owners[1],
                "epoch": epoch,
                "terms": json.dumps({**TERMS, "duration_days": duration}),
            }
            if status == "invited":
                conn.execute(
                    text(
                        "INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,"
                        "inviter_generation,invitee_generation,sync_epoch,status,terms,"
                        "created_at,expires_at) VALUES(:id,:a,:b,1,1,:epoch,'invited',"
                        "CAST(:terms AS jsonb),'2026-01-01 10:00Z','2026-01-08 10:00Z')"
                    ),
                    parameters,
                )
            else:
                conn.execute(
                    text(
                        "INSERT INTO app.nemesis_challenges(id,inviter_id,invitee_id,"
                        "inviter_generation,invitee_generation,sync_epoch,status,terms,"
                        "created_at,expires_at,accepted_at,start_date,end_date,start_at,"
                        "end_at,deadline_at,result_status) VALUES(:id,:a,:b,1,1,:epoch,"
                        "'active',CAST(:terms AS jsonb),'2026-01-01 10:00Z',"
                        "'2026-01-08 10:00Z','2026-01-02 12:00Z','2026-01-03',"
                        "DATE '2026-01-03'+CAST(:days AS integer),'2026-01-03 00:00Z',"
                        "TIMESTAMPTZ '2026-01-03 00:00Z'+CAST(:days AS integer)"
                        "*interval '24 hours',"
                        "TIMESTAMPTZ '2026-01-03 00:00Z'+(CAST(:days AS integer)+30)"
                        "*interval '24 hours',"
                        "'provisional')"
                    ),
                    parameters | {"days": duration},
                )
                for owner in owners:
                    conn.execute(
                        text("INSERT INTO app.nemesis_slots VALUES(:owner,:challenge)"),
                        {"owner": owner, "challenge": identity},
                    )
    return {
        "stale": [row[0] for row in records if row[1:] == ("active", 90)],
        "invite": UUID(int=10001) if due_invite else None,
        "ended": UUID(int=10002) if due_active else None,
    }


def maintain(state, batch=None, engine=None):
    selected = engine or state["worker"]
    with selected.begin() as conn:
        assert conn.scalar(text("SELECT current_user=session_user"))
        assert conn.scalar(text("SELECT current_user")) == "e8_3_nemesis_worker_login"
        statement = (
            "SELECT app.e8n_maintain()" if batch is None else "SELECT app.e8n_maintain(:batch)"
        )
        return conn.scalar(text(statement), {} if batch is None else {"batch": batch})


def states(state):
    with state["migrator"].connect() as conn:
        return {
            row.id: (row.status, row.revision)
            for row in conn.execute(
                text("SELECT id,status,revision FROM app.nemesis_challenges ORDER BY id")
            )
        }


def test_batch_one_progress_survives_worker_connection_restart(maintenance_database):
    state = maintenance_database
    graph = seed_graph(state)
    upgrade(state)
    results = [maintain(state, 1)]
    restarted = create_engine(state["pg"].worker_url, hide_parameters=True)
    try:
        results.extend(maintain(state, 1, restarted) for _ in range(3))
    finally:
        restarted.dispose()
    assert [result["transitioned"] for result in results] == [1, 1, 0, 0]
    current = states(state)
    assert current[graph["invite"]] == ("cancelled", 2)
    assert current[graph["ended"]] == ("finished", 2)
    assert current[graph["stale"][0]] == ("active", 1)


def test_default_batch_hundred_cannot_starve_due_rows_behind_active_prefix(maintenance_database):
    state = maintenance_database
    graph = seed_graph(state, prefix=100)
    upgrade(state)
    results = [maintain(state) for _ in range(3)]
    assert [result["transitioned"] for result in results] == [2, 0, 0]
    current = states(state)
    assert current[graph["invite"]] == ("cancelled", 2)
    assert current[graph["ended"]] == ("finished", 2)
    assert all(current[identity] == ("active", 1) for identity in graph["stale"])
    with state["migrator"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_slots")) == 200


def metadata(state):
    with state["migrator"].connect() as conn:
        return conn.execute(
            text(
                "SELECT p.oid,p.proowner::regrole::text,p.proconfig,"
                "p.proacl::text,p.prosecdef,p.proargtypes::text,p.prorettype::regtype::text,"
                "encode(sha256(convert_to(p.prosrc,'UTF8')),'hex') FROM pg_proc p "
                "WHERE p.oid='app.e8n_maintain(integer)'::regprocedure"
            )
        ).one()


def rows(state):
    with state["migrator"].connect() as conn:
        return {
            name: list(
                conn.scalars(
                    text(
                        f'SELECT to_jsonb(row)::text FROM app."{name}" row '
                        "ORDER BY to_jsonb(row)::text"
                    )
                )
            )
            for name in inspect(conn).get_table_names(schema="app")
            if name != "alembic_version"
        }


@pytest.mark.parametrize("populated", [False, True])
def test_real_empty_filled_migration_preserves_rows_owner_path_acl_and_retains_downgrade(
    maintenance_database, populated
):
    state = maintenance_database
    if populated:
        seed_graph(state)
    before_rows, before_meta = rows(state), metadata(state)
    assert before_meta[-1] == ORIGINAL_BODY
    state["pg"].migrate(REPAIR)
    repaired_meta = metadata(state)
    assert repaired_meta[:-1] == before_meta[:-1] and repaired_meta[-1] == REPAIRED_BODY
    assert rows(state) == before_rows
    if populated:
        assert maintain(state, 1)["transitioned"] == 1
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"), stdout=output)
    after = rows(state)
    with state["migrator"].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, PARENT)
    assert "starvation repair is retained" in output.getvalue()
    assert metadata(state) == repaired_meta and rows(state) == after
    state["pg"].migrate(REPAIR)
    assert metadata(state) == repaired_meta and rows(state) == after
    if populated:
        assert maintain(state, 1)["transitioned"] == 1
        assert maintain(state, 1)["transitioned"] == 0


def test_worker_gc_is_bounded_and_keeps_minimal_receipts_and_young_admissions(maintenance_database):
    state = maintenance_database
    seed_graph(state, prefix=0, due_invite=False, due_active=False)
    upgrade(state)
    owner = uuid4()
    keys = [uuid4() for _ in range(3)]
    young_key = uuid4()
    with state["migrator"].begin() as conn:
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
        conn.execute(
            text(
                "INSERT INTO app.user_accounts(id,issuer,subject) VALUES(:id,"
                "'maintenance-test',:subject)"
            ),
            {"id": owner, "subject": str(owner)},
        )
        conn.execute(text("INSERT INTO app.sync_counters(owner_id) VALUES(:id)"), {"id": owner})
        for key in keys:
            conn.execute(
                text(
                    "INSERT INTO app.nemesis_receipts(owner_id,operation,key,"
                    "request_hash,generation,sync_epoch,http_status,code,response,"
                    "created_at,response_expires_at) VALUES(:owner,'revoke',:key,"
                    "encode(sha256(convert_to(jsonb_build_object('operation','revoke',"
                    "'epoch',CAST(:epoch AS uuid),'payload','{}'::jsonb)::text,'UTF8')),'hex'),"
                    "1,:epoch,200,'accepted',jsonb_build_object('revoked',true),"
                    "'2025-10-01 12:00Z','2025-11-30 12:00Z')"
                ),
                {"owner": owner, "key": key, "epoch": epoch},
            )
            conn.execute(
                text(
                    "INSERT INTO app.nemesis_admissions VALUES(:owner,'attempt',"
                    ":key,'2026-01-19 12:00Z')"
                ),
                {"owner": owner, "key": key},
            )
        conn.execute(
            text(
                "INSERT INTO app.nemesis_receipts(owner_id,operation,key,request_hash,"
                "generation,sync_epoch,http_status,code,response,created_at,response_expires_at) "
                "VALUES(:owner,'revoke',:key,repeat('a',64),1,:epoch,200,'accepted',"
                "jsonb_build_object('revoked',true),'2026-01-19 12:00Z','2026-03-20 12:00Z')"
            ),
            {"owner": owner, "key": young_key, "epoch": epoch},
        )
        conn.execute(
            text(
                "INSERT INTO app.nemesis_admissions VALUES(:owner,'attempt',:key,"
                "'2026-01-20 11:59Z')"
            ),
            {"owner": owner, "key": young_key},
        )
        for index in range(4):
            code_owner = uuid4()
            conn.execute(
                text(
                    "INSERT INTO app.user_accounts(id,issuer,subject) "
                    "VALUES(:id,'maintenance-gc',:subject)"
                ),
                {"id": code_owner, "subject": str(code_owner)},
            )
            issued = "2026-01-01 12:00Z" if index < 3 else "2026-01-20 11:00Z"
            expires = "2026-01-02 12:00Z" if index < 3 else "2026-01-21 11:00Z"
            cursor_expiry = "2026-01-01 12:15Z" if index < 3 else "2026-01-20 12:10Z"
            conn.execute(
                text(
                    "INSERT INTO app.nemesis_share_codes(owner_id,digest,generation,sync_epoch,"
                    "issued_at,expires_at) VALUES(:owner,encode(sha256("
                    "convert_to(:identity,'UTF8')),"
                    "'hex'),1,:epoch,CAST(:issued AS timestamptz),CAST(:expires AS timestamptz))"
                ),
                {
                    "owner": code_owner,
                    "identity": str(code_owner),
                    "epoch": epoch,
                    "issued": issued,
                    "expires": expires,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO app.nemesis_cursors(requester_id,generation,sync_epoch,"
                    "anchor_created_at,anchor_id,expires_at) VALUES(:owner,1,:epoch,"
                    "'2026-01-01 12:00Z',:anchor,CAST(:expires AS timestamptz))"
                ),
                {"owner": owner, "epoch": epoch, "anchor": uuid4(), "expires": cursor_expiry},
            )
    counts, code_counts, cursor_counts = [], [], []
    for _ in range(4):
        counts.append(maintain(state, 1))
        with state["migrator"].connect() as conn:
            code_counts.append(conn.scalar(text("SELECT count(*) FROM app.nemesis_share_codes")))
            cursor_counts.append(conn.scalar(text("SELECT count(*) FROM app.nemesis_cursors")))
    assert code_counts == [3, 2, 1, 1]
    assert cursor_counts == [3, 2, 1, 1]
    assert [item["responses_pruned"] for item in counts] == [1, 1, 1, 0]
    assert [item["admissions_pruned"] for item in counts] == [1, 1, 1, 0]
    with state["migrator"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_receipts")) == 4
        assert (
            conn.scalar(text("SELECT count(*) FROM app.nemesis_receipts WHERE response IS NULL"))
            == 3
        )
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_admissions")) == 1
    with state["api"].begin() as conn:
        result = conn.scalar(
            text(
                "SELECT app.e8n_execute('maintenance-test',:subject,:epoch,"
                "'revoke',:key,repeat('0',64),'{}'::jsonb)"
            ),
            {"subject": str(owner), "epoch": epoch, "key": keys[0]},
        )
        assert result["code"] == "idempotency_result_expired"
    with state["migrator"].connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM app.nemesis_receipts")) == 4


def test_worker_raw_denials_and_public_gate_stay_closed(maintenance_database):
    state = maintenance_database
    graph = seed_graph(state)
    upgrade(state)
    with state["worker"].connect() as conn:
        for table in (
            "nemesis_control",
            "nemesis_releases",
            "nemesis_challenges",
            "nemesis_receipts",
        ):
            assert not conn.scalar(
                text(
                    "SELECT has_any_column_privilege(current_user,:table,"
                    "'SELECT,INSERT,UPDATE,REFERENCES')"
                ),
                {"table": "app." + table},
            )
    for statement in (
        "UPDATE app.nemesis_control SET enabled=true",
        "INSERT INTO app.nemesis_releases VALUES('bad','bad')",
        "SELECT app.e8n_restore_cancel(1)",
        "SET LOCAL ROLE calorie_app_migrator",
    ):
        with pytest.raises(DBAPIError), state["worker"].begin() as conn:
            conn.execute(text(statement))
    with state["migrator"].connect() as conn:
        assert not conn.scalar(text("SELECT app.e8n_gate()"))
        owner = conn.execute(
            text("SELECT inviter_id FROM app.nemesis_challenges WHERE id=:id"),
            {"id": graph["stale"][0]},
        ).scalar_one()
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    with state["api"].begin() as conn:
        result = conn.scalar(
            text(
                "SELECT app.e8n_execute('maintenance-test',:subject,:epoch,"
                "'issue',:key,repeat('0',64),'{}'::jsonb)"
            ),
            {"subject": str(owner), "epoch": epoch, "key": uuid4()},
        )
        assert result["code"] == "nemesis_activation_unavailable"


def wait_for_blocker(state, worker_pid, holder_pid):
    deadline = time.monotonic() + 10
    with state["pg"].engine("admin").connect() as conn:
        while time.monotonic() < deadline:
            if holder_pid in conn.scalar(
                text("SELECT pg_blocking_pids(:pid)"), {"pid": worker_pid}
            ):
                return
    pytest.fail("worker did not reach the real challenge row-lock barrier")


@pytest.mark.parametrize("change", ["clock", "status"])
def test_after_lock_recheck_uses_new_clock_and_terminal_status(maintenance_database, change):
    state = maintenance_database
    graph = seed_graph(state, prefix=0, due_active=False)
    upgrade(state)
    pids = Queue()
    with state["migrator"].connect() as holder, holder.begin() as transaction:
        holder_pid = holder.scalar(text("SELECT pg_backend_pid()"))
        holder.execute(
            text("SELECT 1 FROM app.nemesis_challenges WHERE id=:id FOR UPDATE"),
            {"id": graph["invite"]},
        )

        def invoke():
            with state["worker"].begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout='15s'"))
                pids.put(conn.scalar(text("SELECT pg_backend_pid()")))
                return conn.scalar(text("SELECT app.e8n_maintain(1)"))

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(invoke)
            wait_for_blocker(state, pids.get(timeout=10), holder_pid)
            if change == "clock":
                set_clock(state, "2026-01-07 12:00:00+00")
                expected = ("invited", 1)
            else:
                holder.execute(
                    text(
                        "UPDATE app.nemesis_challenges SET status='cancelled',"
                        "cancel_reason='withdrawn',revision=revision+1 WHERE id=:id"
                    ),
                    {"id": graph["invite"]},
                )
                expected = ("cancelled", 2)
            transaction.commit()
            assert pending.result(timeout=15)["transitioned"] == 0
    assert states(state)[graph["invite"]] == expected


@pytest.mark.parametrize("tamper", ["body", "owner", "path", "public", "api", "invoker"])
def test_migration_rejects_tampered_maintenance_atomically(maintenance_database, tamper):
    state = maintenance_database
    with state["pg"].engine("admin").begin() as conn:
        if tamper == "body":
            conn.execute(
                text(
                    "CREATE OR REPLACE FUNCTION app.e8n_maintain(p_batch integer "
                    "DEFAULT 100) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER "
                    "SET search_path=pg_catalog,pg_temp AS $$ BEGIN RETURN '{}'::jsonb; END $$"
                )
            )
        elif tamper == "owner":
            conn.execute(text("ALTER FUNCTION app.e8n_maintain(integer) OWNER TO calorie_app_api"))
        elif tamper == "path":
            conn.execute(
                text("ALTER FUNCTION app.e8n_maintain(integer) SET search_path=public,pg_temp")
            )
        elif tamper in {"public", "api"}:
            role = "PUBLIC" if tamper == "public" else "calorie_app_api"
            conn.execute(text("GRANT EXECUTE ON FUNCTION app.e8n_maintain(integer) TO " + role))
        else:
            conn.execute(text("ALTER FUNCTION app.e8n_maintain(integer) SECURITY INVOKER"))
    before, before_rows = metadata(state), rows(state)
    with pytest.raises(DBAPIError) as error:
        state["pg"].migrate(REPAIR)
    assert error.value.orig.sqlstate == "23514"
    assert metadata(state) == before and rows(state) == before_rows
    with state["migrator"].connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM app.alembic_version")) == PARENT
