"""E8.3 database evidence uses real PostgreSQL 17 and real runtime LOGINs."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.support.e8_3_postgres import PrivatePostgres

pytestmark = pytest.mark.integration
TERMS = {
    "rule_version": "regularity_v1",
    "duration_days": 7,
    "time_zone": "Europe/Warsaw",
    "scope": {"regularity": True, "weight_change": False, "mean_deficit": False},
}


@pytest.fixture
def pg():
    private = PrivatePostgres.from_environment()
    admin, api = private.engine("migrator"), private.engine("api")
    with admin.begin() as conn:
        assert 170000 <= int(conn.scalar(text("SHOW server_version_num"))) < 180000
        conn.execute(
            text(
                "INSERT INTO app.nemesis_releases VALUES "
                "('test-projector','test-finalizer') ON CONFLICT DO NOTHING "
            )
        )
        conn.execute(
            text(
                "UPDATE app.nemesis_control SET sync_epoch=(SELECT sync_epoch FROM "
                "app.installation_state WHERE "
                "id=1),enabled=true,projector_revision='test-projector',"
                "finalizer_revision='test-finalizer' "
            )
        )
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ SELECT "
                "TIMESTAMPTZ '2026-10-12 12:00:00+00' $$ "
            )
        )
        epoch = conn.scalar(text("SELECT sync_epoch FROM app.installation_state WHERE id=1"))
    yield admin, api, epoch
    with admin.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ SELECT "
                "clock_timestamp() $$ "
            )
        )
        conn.execute(text("UPDATE app.nemesis_control SET enabled=false"))
    api.dispose()
    admin.dispose()


def account(pg, zone="Europe/Warsaw"):
    owner, subject = uuid4(), str(uuid4())
    with pg[0].begin() as conn:
        conn.execute(
            text("INSERT INTO app.user_accounts(id,issuer,subject) VALUES (:id,'e8-test',:sub)"),
            {"id": owner, "sub": subject},
        )
        conn.execute(text("INSERT INTO app.sync_counters(owner_id) VALUES (:id)"), {"id": owner})
        conn.execute(
            text(
                "INSERT INTO "
                "app.user_profiles(id,owner_id,revision,pseudonym,activity_class,time_zone) "
                "VALUES (:profile,:id,1,'Partner','stationary',:zone) "
            ),
            {"profile": uuid4(), "id": owner, "zone": zone},
        )
    return owner, subject


def execute(pg, who, operation, payload=None, key=None, conn=None):
    params = {
        "issuer": "e8-test",
        "subject": who[1],
        "epoch": pg[2],
        "op": operation,
        "key": key or uuid4(),
        "hash": "0" * 64,
        "payload": json.dumps(payload or {}),
    }
    stmt = text(
        "SELECT app.e8n_execute(:issuer,:subject,:epoch,:op,:key,:hash,CAST(:payload AS jsonb))"
    )
    if conn is not None:
        return conn.scalar(stmt, params)
    with pg[1].begin() as connection:
        return connection.scalar(stmt, params)


def invite(pg, sender, receiver, terms=None):
    issued = execute(pg, receiver, "issue")
    assert issued["ok"], issued
    digest = hashlib.sha256(issued["response"]["destination_code"].encode()).hexdigest()
    result = execute(pg, sender, "create", {"destination_digest": digest, "terms": terms or TERMS})
    assert result["ok"], result
    return result["response"]


def accept(pg, receiver, metadata, key=None):
    return execute(
        pg,
        receiver,
        "accept",
        {
            "challenge_id": metadata["id"],
            "revision": metadata["revision"],
            "terms": metadata["terms"],
        },
        key,
    )


def clock(pg, instant):
    # Migrator-controlled private fixture only; production has no clock argument.
    with pg[0].begin() as conn:
        conn.execute(
            text(
                (
                    "CREATE OR REPLACE FUNCTION app.e8n_clock() RETURNS timestamptz "
                    "LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$ SELECT "
                    "CAST(' "
                )
                + instant
                + "' AS timestamptz) $$"
            )
        )


def test_database_gate_raw_execute_and_safe_cancel(pg):
    a, b = account(pg), account(pg)
    challenge = invite(pg, a, b)
    with pg[0].begin() as conn:
        conn.execute(text("UPDATE app.nemesis_control SET enabled=false"))
    assert execute(pg, b, "issue")["code"] == "nemesis_activation_unavailable"
    assert accept(pg, b, challenge)["http_status"] == 503
    result = execute(
        pg, a, "cancel", {"challenge_id": challenge["id"], "revision": 1, "reason": "withdrawn"}
    )
    assert result["ok"] and result["response"]["status"] == "cancelled"
    assert execute(pg, b, "revoke")["ok"]


def test_issue_server_entropy_digest_rotation_and_replay(pg):
    b = account(pg)
    key = uuid4()
    first = execute(pg, b, "issue", key=key)
    token = first["response"]["destination_code"]
    assert len(token) == 43 and set(token) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert first["response"]["issued_at"].endswith("Z")
    assert execute(pg, b, "issue", key=key)["response"] == first["response"]
    with pg[0].begin() as conn:
        digest = conn.scalar(
            text("SELECT digest FROM app.nemesis_share_codes WHERE owner_id=:id"), {"id": b[0]}
        )
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    second = execute(pg, b, "issue")
    assert second["response"]["destination_code"] != token
    assert execute(pg, b, "issue", key=key)["code"] == "idempotency_result_expired"
    assert execute(pg, b, "issue", {"raw_code": "a" * 43})["http_status"] == 422


def test_invalid_create_attempts_durable_limit_and_replay(pg):
    a = account(pg)
    for _ in range(20):
        assert (
            execute(pg, a, "create", {"destination_digest": "f" * 64, "terms": TERMS})["code"]
            == "destination_unavailable"
        )
    key = uuid4()
    payload = {"destination_digest": "f" * 64, "terms": TERMS}
    assert execute(pg, a, "create", payload, key)["http_status"] == 429
    assert execute(pg, a, "create", payload, key)["replayed"]
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_admissions "
                    "WHERE owner_id=:id AND kind='attempt'"
                ),
                {"id": a[0]},
            )
            == 21
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=:id"),
                {"id": a[0]},
            )
            == 0
        )


def test_single_consumption_rollback_lost_ack_and_semantic_key(pg):
    a, b = account(pg), account(pg)
    code = execute(pg, b, "issue")["response"]["destination_code"]
    payload = {"destination_digest": hashlib.sha256(code.encode()).hexdigest(), "terms": TERMS}
    key = uuid4()
    with pg[1].connect() as conn:
        tx = conn.begin()
        assert execute(pg, a, "create", payload, key, conn)["ok"]
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        tx.rollback()
    committed = execute(pg, a, "create", payload, key)
    assert committed["ok"] and committed["http_status"] == 201
    assert execute(pg, a, "create", payload, key)["response"] == committed["response"]
    changed = {**payload, "terms": {**TERMS, "duration_days": 30}}
    assert execute(pg, a, "create", changed, key)["code"] == "idempotency_key_reused"
    assert execute(pg, a, "create", payload)["code"] == "destination_unavailable"


def test_shared_participant_racing_accept_unique_slots(pg):
    a, b, c = account(pg), account(pg), account(pg)
    first, second = invite(pg, a, b), invite(pg, c, b)
    barrier = Barrier(2)

    def attempt(metadata):
        barrier.wait()
        return accept(pg, b, metadata)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (first, second)))
    assert sorted(r["http_status"] for r in results) == [200, 409]
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE owner_id=:id"), {"id": b[0]}
            )
            == 1
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE owner_id IN (:a,:b,:c)"),
                {"a": a[0], "b": b[0], "c": c[0]},
            )
            == 2
        )


def test_accept_expiry_exact_boundary_and_end_without_worker(pg):
    a, b, c = account(pg), account(pg), account(pg)
    first = invite(pg, a, b)
    clock(pg, "2026-10-19 12:00:00+00")
    assert accept(pg, b, first)["code"] == "nemesis_accept_unavailable"
    clock(pg, "2026-10-12 12:00:00+00")
    active = accept(pg, b, invite(pg, a, b))["response"]
    assert active["start_date"] == "2026-10-13" and active["end_date"] == "2026-10-20"
    assert active["result_status"] == "provisional"
    clock(pg, "2026-10-19 12:00:00+00")
    next_invite = invite(pg, c, b)
    clock(pg, "2026-10-19 22:00:00+00")
    assert accept(pg, b, next_invite)["ok"]
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM app.nemesis_challenges WHERE id=:id"), {"id": active["id"]}
            )
            == "finished"
        )


@pytest.mark.parametrize(
    "instant,days,hours", [("2026-03-27 12:00:00+00", 7, 167), ("2026-10-23 12:00:00+00", 7, 169)]
)
def test_warsaw_calendar_dst_and_deadline(pg, instant, days, hours):
    clock(pg, instant)
    a, b = account(pg), account(pg)
    active = accept(pg, b, invite(pg, a, b))["response"]
    with pg[0].begin() as conn:
        row = conn.execute(
            text(
                "SELECT extract(epoch FROM end_at-start_at)/3600,extract(epoch FROM "
                "deadline_at-end_at)/3600,end_date-start_date FROM "
                "app.nemesis_challenges WHERE id=:id "
            ),
            {"id": active["id"]},
        ).one()
    assert row == (hours, 720, days)


def test_public_and_runtime_table_privileges_and_raw_mutation(pg):
    with pg[1].begin() as conn:
        assert conn.scalar(text("SELECT current_user")) == "calorie_app_api"
        for table in (
            "nemesis_control",
            "nemesis_releases",
            "nemesis_challenges",
            "nemesis_receipts",
            "nemesis_share_codes",
        ):
            assert not conn.scalar(
                text(
                    "SELECT has_table_privilege(current_user,:table,'SELECT,INSERT,UPDATE,DELETE')"
                ),
                {"table": "app." + table},
            )
        assert not conn.scalar(
            text("SELECT has_function_privilege('public','app.e8n_gate()','EXECUTE')")
        )
    with pytest.raises(DBAPIError), pg[1].begin() as conn:
        conn.execute(text("UPDATE app.nemesis_control SET enabled=true"))


def test_unknown_terms_rejected_raw_sql_and_immutable_bindings(pg):
    a, b = account(pg), account(pg)
    meta = invite(pg, a, b)
    with pytest.raises(DBAPIError), pg[0].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.nemesis_challenges SET terms=CAST(:terms AS "
                "jsonb),revision=revision+1 WHERE id=:id "
            ),
            {"terms": json.dumps({}), "id": meta["id"]},
        )
    with pytest.raises(DBAPIError), pg[0].begin() as conn:
        conn.execute(
            text(
                "UPDATE app.nemesis_challenges SET invitee_id=:other,"
                "revision=revision+1 WHERE id=:id"
            ),
            {"other": a[0], "id": meta["id"]},
        )
    key = uuid4()
    assert accept(pg, b, meta, key)["ok"]
    cancelled = execute(
        pg, b, "cancel", {"challenge_id": meta["id"], "revision": 2, "reason": "sharing_revoked"}
    )
    assert cancelled["ok"]
    replay = accept(pg, b, meta, key)
    assert replay["ok"] and replay["response"]["status"] == "cancelled"


def test_metadata_cursor_owner_context_and_bounded_history(pg):
    a, b, c = account(pg), account(pg), account(pg)
    for _ in range(3):
        meta = invite(pg, a, b)
        assert execute(
            pg, a, "cancel", {"challenge_id": meta["id"], "revision": 1, "reason": "withdrawn"}
        )["ok"]
    with pg[1].begin() as conn:
        page = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:sub,:epoch,NULL,1,NULL)"),
            {"sub": a[1], "epoch": pg[2]},
        )
        assert len(page["response"]["items"]) == 1
        token = page["response"]["next_cursor"]
        assert token
        other = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:sub,:epoch,NULL,1,:cursor)"),
            {"sub": c[1], "epoch": pg[2], "cursor": token},
        )
        assert other["code"] == "nemesis_cursor_unavailable"
        second = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:sub,:epoch,NULL,1,:cursor)"),
            {"sub": a[1], "epoch": pg[2], "cursor": token},
        )
        assert second["response"]["items"][0]["id"] != page["response"]["items"][0]["id"]


def test_old_epoch_immediately_gates_and_nonempty_downgrade_atomic(pg):
    a, b = account(pg), account(pg)
    meta = invite(pg, a, b)
    with pg[0].begin() as conn:
        conn.execute(text("UPDATE app.nemesis_control SET sync_epoch=:epoch"), {"epoch": uuid4()})
    assert execute(pg, b, "issue")["http_status"] == 503
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with pytest.raises(DBAPIError), pg[0].begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0016_e8_motivation")
    with pg[0].begin() as conn:
        assert (
            conn.scalar(text("SELECT version_num FROM app.alembic_version"))
            == "0017_e8_nemesis_lifecycle"
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE id=:id"), {"id": meta["id"]}
            )
            == 1
        )


def test_bounded_cursor_pool_does_not_cap_history(pg):
    a, b = account(pg), account(pg)
    for _ in range(3):
        meta = invite(pg, a, b)
        assert execute(
            pg, a, "cancel", {"challenge_id": meta["id"], "revision": 1, "reason": "withdrawn"}
        )["ok"]
    with pg[1].begin() as conn:
        for _ in range(20):
            result = conn.scalar(
                text("SELECT app.e8n_read('e8-test',:sub,:epoch,NULL,1,NULL)"),
                {"sub": a[1], "epoch": pg[2]},
            )
            assert result["response"]["next_cursor"]
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_cursors WHERE requester_id=:id"),
                {"id": a[0]},
            )
            == 8
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=:id"),
                {"id": a[0]},
            )
            == 3
        )


def test_issue_rolling_cap_and_cancel_does_not_refund(pg):
    a, b = account(pg), account(pg)
    for _ in range(5):
        assert execute(pg, b, "issue")["ok"]
        assert execute(pg, b, "revoke")["ok"]
    assert execute(pg, b, "issue")["http_status"] == 429
    clock(pg, "2026-10-13 12:00:00+00")
    assert execute(pg, b, "issue")["ok"]
    for _ in range(5):
        meta = invite(pg, a, account(pg))
        assert execute(
            pg, a, "cancel", {"challenge_id": meta["id"], "revision": 1, "reason": "withdrawn"}
        )["ok"]
    issued = execute(pg, account(pg), "issue")["response"]
    payload = {
        "destination_digest": hashlib.sha256(issued["destination_code"].encode()).hexdigest(),
        "terms": TERMS,
    }
    assert execute(pg, a, "create", payload)["http_status"] == 429


def test_minimal_receipt_retention_replay_no_mutation(pg):
    a, b = account(pg), account(pg)
    code = execute(pg, b, "issue")["response"]["destination_code"]
    payload = {"destination_digest": hashlib.sha256(code.encode()).hexdigest(), "terms": TERMS}
    key = uuid4()
    assert execute(pg, a, "create", payload, key)["ok"]
    clock(pg, "2026-12-12 12:00:00+00")
    with pg[0].begin() as conn:
        conn.execute(text("SELECT app.e8n_maintain(1000)"))
        assert (
            conn.scalar(
                text(
                    "SELECT response FROM app.nemesis_receipts "
                    "WHERE owner_id=:id AND operation='create' AND key=:key"
                ),
                {"id": a[0], "key": key},
            )
            is None
        )
    replay = execute(pg, a, "create", payload, key)
    assert replay["http_status"] == 409 and replay["code"] == "idempotency_result_expired"
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE inviter_id=:id"),
                {"id": a[0]},
            )
            == 1
        )
        assert (
            conn.scalar(
                text(
                    "SELECT count(*) FROM app.nemesis_admissions "
                    "WHERE owner_id=:id AND kind='attempt'"
                ),
                {"id": a[0]},
            )
            == 1
        )


@pytest.mark.parametrize(
    "instant,zone,expected_start,expected_end,status",
    [
        ("2011-12-29 12:00:00+00", "Pacific/Apia", "2011-12-31", "2012-01-07", 200),
        ("2011-12-27 12:00:00+00", "Pacific/Apia", None, None, 409),
        ("2011-12-22 12:00:00+00", "Pacific/Apia", "2011-12-23", "2011-12-30", 200),
        ("2018-11-03 12:00:00+00", "America/Sao_Paulo", "2018-11-04", "2018-11-11", 200),
    ],
)
def test_skipped_dates_and_midnight_gap(pg, instant, zone, expected_start, expected_end, status):
    clock(pg, instant)
    a, b = account(pg, zone), account(pg, zone)
    terms = {**TERMS, "time_zone": zone}
    result = accept(pg, b, invite(pg, a, b, terms))
    assert result["http_status"] == status
    if status == 200:
        assert result["response"]["start_date"] == expected_start
        assert result["response"]["end_date"] == expected_end
    else:
        assert result["code"] == "period_calendar_date_unavailable"


def test_slot_constraint_immediate_and_accept_rollback(pg):
    a, b = account(pg), account(pg)
    meta = invite(pg, a, b)
    with pg[1].connect() as conn:
        tx = conn.begin()
        assert execute(
            pg, b, "accept", {"challenge_id": meta["id"], "revision": 1, "terms": TERMS}, conn=conn
        )["ok"]
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        tx.rollback()
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT status FROM app.nemesis_challenges WHERE id=:id"), {"id": meta["id"]}
            )
            == "invited"
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_slots WHERE challenge_id=:id"),
                {"id": meta["id"]},
            )
            == 0
        )


def test_deleting_before_purge_denies_partner_then_safe_marker_and_both_purge(pg):
    a, b = account(pg), account(pg)
    metadata = invite(pg, a, b)
    assert accept(pg, b, metadata)["ok"]
    operation_a = uuid4()
    with pg[0].begin() as conn:
        conn.execute(
            text("SELECT app.begin_account_deletion(:id,:op,1)"), {"id": a[0], "op": operation_a}
        )
        conn.execute(
            text("SELECT app.e8n_delete_helper(:id,:op,false)"), {"id": a[0], "op": operation_a}
        )
    with pg[1].begin() as conn:
        result = conn.scalar(
            text("SELECT app.e8n_read('e8-test',:sub,:epoch,:id)"),
            {"sub": b[1], "epoch": pg[2], "id": metadata["id"]},
        )
        assert result["code"] == "nemesis_not_found"
    for participant, operation in ((a, operation_a), (b, uuid4())):
        with pg[0].begin() as conn:
            if participant == b:
                conn.execute(
                    text("SELECT app.begin_account_deletion(:id,:op,1)"),
                    {"id": participant[0], "op": operation},
                )
            conn.execute(text("SELECT app.confirm_account_deletion(:op)"), {"op": operation})
            # Private seam fixture, not a production wrapper installation.
            conn.execute(
                text("INSERT INTO app._deletion_context VALUES(txid_current(),:id,:op)"),
                {"id": participant[0], "op": operation},
            )
            conn.execute(
                text("SELECT app.e8n_delete_helper(:id,:op,true)"),
                {"id": participant[0], "op": operation},
            )
        if participant == a:
            with pg[1].begin() as conn:
                safe = conn.scalar(
                    text("SELECT app.e8n_read('e8-test',:sub,:epoch,:id)"),
                    {"sub": b[1], "epoch": pg[2], "id": metadata["id"]},
                )
                assert safe["response"]["cancel_reason"] == "deleted"
                assert safe["response"]["partner_pseudonym"] is None
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_challenges WHERE id=:id"),
                {"id": metadata["id"]},
            )
            == 0
        )
        assert (
            conn.scalar(
                text("SELECT count(*) FROM app.nemesis_receipts WHERE owner_id IN(:a,:b)"),
                {"a": a[0], "b": b[0]},
            )
            == 0
        )


def test_raw_invalid_scope_shapes_fail_closed_without_exception(pg):
    a, b = account(pg), account(pg)
    code = execute(pg, b, "issue")["response"]["destination_code"]
    digest = hashlib.sha256(code.encode()).hexdigest()
    for scope in (
        None,
        [],
        "all",
        {"regularity": True},
        {"regularity": True, "weight_change": False, "raw_weight": False},
    ):
        result = execute(
            pg, a, "create", {"destination_digest": digest, "terms": {**TERMS, "scope": scope}}
        )
        assert result["http_status"] == 422 and result["code"] == "invalid_terms"
    with pg[0].begin() as conn:
        assert (
            conn.scalar(
                text("SELECT consumed_at FROM app.nemesis_share_codes WHERE owner_id=:id"),
                {"id": b[0]},
            )
            is None
        )
