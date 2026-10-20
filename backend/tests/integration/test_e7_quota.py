"""Real PG/SCRAM limiter proofs. No provider, storage, or E9 endpoint is invoked."""

import hashlib
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from psycopg import sql
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from calorie_app.core.config import Settings
from calorie_app.modules.ai.configuration import configuration
from tests.support.deletion_regression import begin as begin_deletion

pytestmark = pytest.mark.integration
SCOPE = "mock:local:mock-food-v1:local"
BUDGET = 10240
RESERVE = text("SELECT app.e7_reserve(:scope,:purpose,:kind,NULL,0,:attempt,:worker)")
FINISH = text("SELECT app.e7_io_finished(:attempt,:worker,:status,:input,:output,:thoughts)")
ADMIT = text("SELECT app.e7_admit(:owner,:kind)")


def scalar(engine, statement, parameters=None):
    with engine.begin() as connection:
        return connection.scalar(
            text(statement) if isinstance(statement, str) else statement, parameters or {}
        )


def login_engine(database, role):
    admin, _, url = database
    login, password = "e7_quota_" + secrets.token_hex(6), secrets.token_urlsafe(32)
    with admin.begin() as connection:
        pg = connection.connection.driver_connection
        hashed = pg.pgconn.encrypt_password(
            password.encode(), login.encode(), b"scram-sha-256"
        ).decode()
        for statement in (
            sql.SQL("CREATE ROLE {} LOGIN INHERIT PASSWORD {}").format(
                sql.Identifier(login), sql.Literal(hashed)
            ),
            sql.SQL("GRANT {} TO {}").format(sql.Identifier(role), sql.Identifier(login)),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(make_url(url).database), sql.Identifier(login)
            ),
        ):
            connection.exec_driver_sql(statement.as_string(pg))
    runtime = create_engine(
        make_url(url).set(username=login, password=password),
        hide_parameters=True,
        pool_size=4,
        max_overflow=2,
    )
    return runtime, login


@pytest.fixture(scope="module")
def quota_roles(database):
    api, api_login = login_engine(database, "calorie_app_api")
    worker, worker_login = login_engine(database, "calorie_app_ai_worker")
    legacy, legacy_login = login_engine(database, "calorie_app_worker")
    yield api, worker, legacy
    api.dispose()
    worker.dispose()
    legacy.dispose()
    with database[0].begin() as connection:
        pg = connection.connection.driver_connection
        for login in (api_login, worker_login, legacy_login):
            connection.exec_driver_sql(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
            )
            connection.exec_driver_sql(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
            )


@pytest.fixture
def quota(database, quota_roles):
    admin, _, url = database
    api, worker, legacy = quota_roles

    def clear():
        with admin.begin() as connection:
            connection.execute(text("TRUNCATE app.user_accounts CASCADE"))
            connection.execute(
                text("TRUNCATE app.ai_attempts,app.ai_transport_permits,app.ai_cleanup_intents")
            )
            connection.execute(
                text("DELETE FROM app.ai_pools WHERE scope<>:scope"), {"scope": SCOPE}
            )
            connection.execute(
                text(
                    "INSERT INTO app.ai_transport_permits(environment,slot) "
                    "VALUES('local',1),('local',2)"
                )
            )
            connection.execute(
                text(
                    "UPDATE app.ai_controls SET sync_epoch=(SELECT "
                    "sync_epoch FROM app.installation_state WHERE "
                    "id=1),dispatch_open=true,closed_at=NULL"
                )
            )
            connection.execute(
                text(
                    "UPDATE app.ai_pools SET "
                    "rpm=100,tpm=1000000,rpd=10000,enabled=true WHERE "
                    "scope=:scope"
                ),
                {"scope": SCOPE},
            )

    clear()
    owner = uuid4()
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.user_accounts(id,issuer,subject) "
                "VALUES(:id,'https://quota.e7.test',:subject)"
            ),
            {"id": owner, "subject": str(uuid4())},
        )
    yield {
        "admin": admin,
        "api": api,
        "worker": worker,
        "legacy": legacy,
        "owner": owner,
        "url": url,
    }
    clear()


def reserve(quota, *, purpose="food_photo", kind="generate", scope=SCOPE, connection=None):
    parameters = {
        "scope": scope,
        "purpose": purpose,
        "kind": kind,
        "attempt": uuid4(),
        "worker": uuid4(),
    }
    outcome = (
        connection.scalar(RESERVE, parameters)
        if connection is not None
        else scalar(quota["admin"], RESERVE, parameters)
    )
    return outcome, parameters


def finish(quota, parameters, *, status="unknown", usage=(None, None, None), worker=None):
    return scalar(
        quota["worker"],
        FINISH,
        {
            "attempt": parameters["attempt"],
            "worker": worker or parameters["worker"],
            "status": status,
            "input": usage[0],
            "output": usage[1],
            "thoughts": usage[2],
        },
    )


def ledger(quota, attempt):
    with quota["admin"].connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM app.ai_attempts WHERE id=:id"), {"id": attempt})
            .mappings()
            .one()
        )


def limits(quota, *, rpm=100, tpm=1000000, rpd=10000):
    scalar(
        quota["admin"],
        "UPDATE app.ai_pools SET rpm=:rpm,tpm=:tpm,rpd=:rpd WHERE scope=:scope RETURNING scope",
        {"rpm": rpm, "tpm": tpm, "rpd": rpd, "scope": SCOPE},
    )


@pytest.mark.parametrize("kind", ["count_tokens", "generate"])
def test_both_purposes_share_one_pool_and_every_kind_reserves_full_budget(quota, kind):
    before = scalar(quota["admin"], "SELECT clock_timestamp()")
    first, food = reserve(quota, kind=kind)
    second, energy = reserve(quota, purpose="energy_adjustment", kind=kind)
    after = scalar(quota["admin"], "SELECT clock_timestamp()")
    assert "attempt_id" in first and "attempt_id" in second
    rows = [ledger(quota, parameters["attempt"]) for parameters in (food, energy)]
    assert {row["purpose"] for row in rows} == {"food_photo", "energy_adjustment"}
    assert all(
        row["job_id"] is None and row["pool_scope"] == SCOPE and row["reserved_tokens"] == BUDGET
        for row in rows
    )
    assert all(before <= row["dispatched_at"] <= after for row in rows)
    assert all(
        row["pacific_day"]
        == row["dispatched_at"].astimezone(ZoneInfo("America/Los_Angeles")).date()
        for row in rows
    )
    assert sorted((first["slot"], second["slot"])) == [1, 2]


@pytest.mark.parametrize(
    "first_purpose,second_purpose",
    [("food_photo", "energy_adjustment"), ("energy_adjustment", "food_photo")],
)
def test_one_purpose_cannot_bypass_the_other_purpose_request_quota(
    quota, first_purpose, second_purpose
):
    limits(quota, rpm=1)
    first, parameters = reserve(quota, purpose=first_purpose, kind="count_tokens")
    assert "attempt_id" in first and finish(quota, parameters)
    second, _ = reserve(quota, purpose=second_purpose)
    assert second == {"error": "ai_rate_limited"}
    assert scalar(quota["admin"], "SELECT count(*) FROM app.ai_attempts") == 1


@pytest.mark.parametrize(
    "dimension,error",
    [("rpm", "ai_rate_limited"), ("tpm", "ai_rate_limited"), ("rpd", "ai_quota_exhausted")],
)
def test_concurrent_last_request_token_or_day_slot_is_consumed_once(quota, dimension, error):
    limits(quota, **{dimension: 2 * BUDGET if dimension == "tpm" else 2})
    seeded, parameters = reserve(quota, kind="count_tokens")
    assert "attempt_id" in seeded and finish(quota, parameters)
    if dimension == "rpd":
        scalar(
            quota["admin"],
            "UPDATE app.ai_attempts SET "
            "dispatched_at=clock_timestamp()-interval '61 seconds' WHERE "
            "id=:id RETURNING id",
            {"id": parameters["attempt"]},
        )
    barrier = threading.Barrier(2)

    def compete(purpose):
        with quota["admin"].begin() as connection:
            connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
            barrier.wait(timeout=10)
            return reserve(quota, purpose=purpose, connection=connection)[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(compete, purpose) for purpose in ("food_photo", "energy_adjustment")
        ]
        outcomes = [future.result(timeout=20) for future in futures]
    assert sum("attempt_id" in outcome for outcome in outcomes) == 1
    assert [outcome["error"] for outcome in outcomes if "error" in outcome] == [error]
    assert scalar(quota["admin"], "SELECT count(*) FROM app.ai_attempts") == 2
    assert scalar(quota["admin"], "SELECT sum(reserved_tokens) FROM app.ai_attempts") == 2 * BUDGET


def test_window_includes_recent_request_but_excludes_exactly_sixty_seconds_old(quota):
    limits(quota, rpm=1)
    first, parameters = reserve(quota)
    assert "attempt_id" in first and finish(quota, parameters)
    scalar(
        quota["admin"],
        "UPDATE app.ai_attempts SET dispatched_at=clock_timestamp()-interval"
        " '50 seconds' WHERE id=:id RETURNING id",
        {"id": parameters["attempt"]},
    )
    assert reserve(quota, purpose="energy_adjustment")[0] == {"error": "ai_rate_limited"}
    scalar(
        quota["admin"],
        "UPDATE app.ai_attempts SET dispatched_at=clock_timestamp()-interval"
        " '60 seconds' WHERE id=:id RETURNING id",
        {"id": parameters["attempt"]},
    )
    second, new_parameters = reserve(quota, purpose="energy_adjustment")
    assert "attempt_id" in second
    assert ledger(quota, new_parameters["attempt"])["dispatched_at"] - ledger(
        quota, parameters["attempt"]
    )["dispatched_at"] >= timedelta(seconds=60)


def test_crossing_calendar_minute_does_not_reset_moving_window(quota):
    limits(quota, rpm=1)
    _, parameters = reserve(quota)
    assert finish(quota, parameters)
    # An unlucky call across midnight of a minute may age this deliberately
    # staged row beyond 60 s. Re-stage with a savepoint, never fixed sleeps.
    with quota["admin"].begin() as connection:
        for _ in range(3):
            savepoint = connection.begin_nested()
            staged = connection.scalar(
                text(
                    "UPDATE app.ai_attempts SET "
                    "dispatched_at=date_trunc('minute',clock_timestamp())-interval"
                    " '1 microsecond' WHERE id=:id RETURNING dispatched_at"
                ),
                {"id": parameters["attempt"]},
            )
            outcome, _ = reserve(quota, purpose="energy_adjustment", connection=connection)
            after = connection.scalar(text("SELECT clock_timestamp()"))
            if after - staged < timedelta(seconds=60):
                assert staged.minute != after.minute or staged.hour != after.hour
                assert outcome == {"error": "ai_rate_limited"}
                savepoint.commit()
                break
            savepoint.rollback()
        else:
            pytest.fail(
                "Database could not complete a bounded call within the chosen moving window"
            )


@pytest.mark.parametrize(
    "status,usage",
    [
        ("ok", (None, None, None)),
        ("ok", (512, None, 0)),
        ("ok", (512, 256, None)),
        ("unknown", (512, 256, 0)),
        ("denied", (512, 256, 0)),
        ("invalid", (512, 256, 0)),
    ],
)
def test_missing_or_untrusted_usage_keeps_the_full_budget_after_physical_finish(
    quota, status, usage
):
    _, parameters = reserve(quota, kind="count_tokens")
    assert finish(quota, parameters, status=status, usage=usage)
    saved = ledger(quota, parameters["attempt"])
    assert saved["reserved_tokens"] == BUDGET and saved["io_finished_at"] is not None
    assert (
        scalar(
            quota["admin"],
            "SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id IS NOT NULL",
        )
        == 0
    )


def test_valid_usage_reconciles_thinking_once_but_request_count_stays_used(quota):
    limits(quota, rpm=1)
    _, parameters = reserve(quota)
    assert finish(quota, parameters, status="ok", usage=(512, 768, 256))
    saved = ledger(quota, parameters["attempt"])
    assert (
        saved["reserved_tokens"],
        saved["input_tokens"],
        saved["output_tokens"],
        saved["thoughts_tokens"],
    ) == (1536, 512, 768, 256)
    assert reserve(quota, purpose="energy_adjustment")[0] == {"error": "ai_rate_limited"}


@pytest.mark.parametrize("usage", [(-1, 0, 0), (8193, 0, 0), (1, -1, 0), (1, 2048, 1)])
def test_invalid_raw_usage_cannot_refund_or_release_any_permit(quota, usage):
    _, parameters = reserve(quota)
    with pytest.raises(DBAPIError) as failed:
        finish(quota, parameters, status="ok", usage=usage)
    assert failed.value.orig.sqlstate == "23514"
    saved = ledger(quota, parameters["attempt"])
    assert saved["reserved_tokens"] == BUDGET and saved["io_finished_at"] is None
    assert (
        scalar(
            quota["admin"],
            "SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id=:id",
            {"id": parameters["attempt"]},
        )
        == 1
    )


def test_physical_finish_requires_exact_worker_token_and_is_not_reconciled_twice(quota):
    _, parameters = reserve(quota)
    saved = ledger(quota, parameters["attempt"])
    assert "worker_token" not in saved
    assert (
        saved["worker_token_hash"] == hashlib.sha256(str(parameters["worker"]).encode()).hexdigest()
    )
    assert len(saved["worker_token_hash"]) == 64 and saved["worker_token_hash"] != str(
        parameters["worker"]
    )
    assert finish(quota, parameters, worker=uuid4()) is False
    assert ledger(quota, parameters["attempt"])["io_finished_at"] is None
    assert finish(quota, parameters, status="unknown") is True
    assert finish(quota, parameters, status="ok", usage=(1, 1, 0)) is False
    assert ledger(quota, parameters["attempt"])["reserved_tokens"] == BUDGET


def test_ai_worker_has_minimal_read_capabilities_and_cannot_read_claim_fence(quota):
    assert scalar(
        quota["worker"], "SELECT pg_has_role(current_user,'calorie_app_ai_worker','MEMBER')"
    )
    assert not scalar(
        quota["worker"], "SELECT pg_has_role(current_user,'calorie_app_worker','MEMBER')"
    )
    assert scalar(
        quota["worker"],
        "SELECT NOT(rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
        "OR rolbypassrls) FROM pg_roles WHERE rolname=current_user",
    )
    scalar(
        quota["worker"],
        "SELECT id,purpose,state,next_attempt_at,lease_until FROM app.ai_jobs LIMIT 0",
    )
    with pytest.raises(DBAPIError) as failed:
        scalar(quota["worker"], "SELECT fence FROM app.ai_jobs LIMIT 0")
    assert failed.value.orig.sqlstate == "42501"


@pytest.mark.parametrize(
    "table,column",
    [
        ("meals", "id"),
        ("product_drafts", "id"),
        ("products", "id"),
        ("product_versions", "revision"),
    ],
)
@pytest.mark.parametrize("action", ["INSERT", "UPDATE", "DELETE"])
def test_ai_worker_cannot_execute_raw_dml_on_private_diary_drafts_or_catalog(
    quota, table, column, action
):
    assert not scalar(
        quota["worker"],
        "SELECT has_table_privilege(current_user,:table,:action)",
        {"table": "app." + table, "action": action},
    )
    if action != "DELETE":
        assert not scalar(
            quota["worker"],
            "SELECT has_column_privilege(current_user,:table,:column,:action)",
            {"table": "app." + table, "column": column, "action": action},
        )
    statement = {
        "INSERT": f"INSERT INTO app.{table} DEFAULT VALUES",
        "UPDATE": f"UPDATE app.{table} SET {column}=:value WHERE false",
        "DELETE": f"DELETE FROM app.{table} WHERE false",
    }[action]
    with pytest.raises(DBAPIError) as failed:
        scalar(quota["worker"], statement, {"value": 1 if column == "revision" else uuid4()})
    assert failed.value.orig.sqlstate == "42501"


def test_legacy_worker_retains_its_previous_role_but_cannot_dispatch_e7(quota):
    assert scalar(quota["legacy"], "SELECT pg_has_role(current_user,'calorie_app_worker','MEMBER')")
    assert not scalar(
        quota["legacy"], "SELECT pg_has_role(current_user,'calorie_app_ai_worker','MEMBER')"
    )
    assert scalar(quota["legacy"], "SELECT has_table_privilege(current_user,'app.meals','INSERT')")
    with pytest.raises(DBAPIError) as failed:
        scalar(
            quota["legacy"],
            "SELECT app.e7_dispatch(:job,:fence,'count_tokens',:attempt,:worker)",
            {"job": uuid4(), "fence": uuid4(), "attempt": uuid4(), "worker": uuid4()},
        )
    assert failed.value.orig.sqlstate == "42501"


def test_api_cannot_finish_transport_and_worker_cannot_call_internal_reserve(quota):
    _, parameters = reserve(quota)
    for engine, statement, args in (
        (
            quota["api"],
            FINISH,
            {
                "attempt": parameters["attempt"],
                "worker": parameters["worker"],
                "status": "ok",
                "input": 1,
                "output": 1,
                "thoughts": 0,
            },
        ),
        (quota["worker"], RESERVE, parameters),
        (quota["api"], RESERVE, parameters),
        (quota["worker"], ADMIT, {"owner": quota["owner"], "kind": "food_photo"}),
    ):
        with pytest.raises(DBAPIError) as failed:
            scalar(engine, statement, args)
        assert failed.value.orig.sqlstate == "42501"
    assert ledger(quota, parameters["attempt"])["reserved_tokens"] == BUDGET


def test_photo_and_receipt_admissions_have_separate_exact_utc_limits(quota):
    with quota["api"].begin() as connection:
        photos = list(
            connection.scalars(
                text("SELECT app.e7_admit(:owner,'food_photo') FROM generate_series(1,11)"),
                {"owner": quota["owner"]},
            )
        )
        receipts = list(
            connection.scalars(
                text("SELECT app.e7_admit(:owner,'receipts') FROM generate_series(1,1001)"),
                {"owner": quota["owner"]},
            )
        )
    assert photos == [True] * 10 + [False]
    assert receipts == [True] * 1000 + [False]
    with quota["admin"].connect() as connection:
        row = connection.execute(
            text(
                "SELECT photos,receipts,day,(clock_timestamp() AT TIME ZONE "
                "'UTC')::date AS today FROM app.ai_admissions WHERE "
                "owner_id=:owner"
            ),
            {"owner": quota["owner"]},
        ).one()
    assert (row.photos, row.receipts, row.day) == (10, 1000, row.today)


def test_utc_admission_day_ignores_session_timezone_and_keeps_yesterdays_limits(quota):
    with quota["admin"].begin() as connection:
        connection.execute(
            text(
                "INSERT INTO app.ai_admissions(owner_id,day,photos,receipts)"
                " VALUES(:owner,(clock_timestamp() AT TIME ZONE "
                "'UTC')::date-1,10,1000)"
            ),
            {"owner": quota["owner"]},
        )
        now = connection.scalar(text("SELECT clock_timestamp()"))
    zone = "Pacific/Kiritimati" if now.astimezone(UTC).hour >= 10 else "Etc/GMT+12"
    with quota["api"].begin() as connection:
        connection.scalar(text("SELECT set_config('TimeZone',:zone,true)"), {"zone": zone})
        assert connection.scalar(
            text("SELECT clock_timestamp()::date<>(clock_timestamp() AT TIME ZONE 'UTC')::date")
        )
        assert connection.scalar(ADMIT, {"owner": quota["owner"], "kind": "food_photo"})
        assert connection.scalar(ADMIT, {"owner": quota["owner"], "kind": "receipts"})
    with quota["admin"].connect() as connection:
        rows = connection.execute(
            text(
                "SELECT photos,receipts FROM app.ai_admissions WHERE owner_id=:owner ORDER BY day"
            ),
            {"owner": quota["owner"]},
        ).all()
    assert [tuple(row) for row in rows] == [(10, 1000), (1, 1)]


@pytest.mark.parametrize(
    "kind,maximum", [("food_photo", 10), ("receipts", 1000), ("energy_adjustment", 1)]
)
def test_last_user_admission_is_atomic_between_two_scram_api_connections(quota, kind, maximum):
    with quota["admin"].begin() as connection:
        if kind == "energy_adjustment":
            connection.execute(
                text(
                    "INSERT INTO app.ai_energy_admissions "
                    "VALUES(:owner,clock_timestamp()-interval '337 hours')"
                ),
                {"owner": quota["owner"]},
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO "
                    "app.ai_admissions(owner_id,day,photos,receipts) "
                    "VALUES(:owner,(clock_timestamp() AT TIME ZONE "
                    "'UTC')::date,:photos,:receipts)"
                ),
                {
                    "owner": quota["owner"],
                    "photos": maximum - 1 if kind == "food_photo" else 0,
                    "receipts": maximum - 1 if kind == "receipts" else 0,
                },
            )
    barrier = threading.Barrier(2)

    def compete():
        with quota["api"].begin() as connection:
            connection.exec_driver_sql("SET LOCAL statement_timeout='15s'")
            barrier.wait(timeout=10)
            return connection.scalar(ADMIT, {"owner": quota["owner"], "kind": kind})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(compete) for _ in range(2)]
        assert sorted(future.result(timeout=20) for future in futures) == [False, True]
    if kind != "energy_adjustment":
        field = "photos" if kind == "food_photo" else "receipts"
        assert (
            scalar(
                quota["admin"],
                f"SELECT {field} FROM app.ai_admissions WHERE owner_id=:owner",
                {"owner": quota["owner"]},
            )
            == maximum
        )


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Pacific/Chatham"])
def test_energy_admission_is_a_moving_336_hour_window_in_every_session_timezone(quota, zone):
    assert scalar(quota["api"], ADMIT, {"owner": quota["owner"], "kind": "energy_adjustment"})
    with quota["api"].begin() as connection:
        connection.scalar(text("SELECT set_config('TimeZone',:zone,true)"), {"zone": zone})
        assert (
            connection.scalar(ADMIT, {"owner": quota["owner"], "kind": "energy_adjustment"})
            is False
        )
    scalar(
        quota["admin"],
        "UPDATE app.ai_energy_admissions SET "
        "accepted_at=clock_timestamp()-interval '335 hours' WHERE "
        "owner_id=:owner RETURNING owner_id",
        {"owner": quota["owner"]},
    )
    assert (
        scalar(quota["api"], ADMIT, {"owner": quota["owner"], "kind": "energy_adjustment"}) is False
    )
    old = scalar(
        quota["admin"],
        "UPDATE app.ai_energy_admissions SET "
        "accepted_at=clock_timestamp()-interval '336 hours' WHERE "
        "owner_id=:owner RETURNING accepted_at",
        {"owner": quota["owner"]},
    )
    with quota["api"].begin() as connection:
        connection.scalar(text("SELECT set_config('TimeZone',:zone,true)"), {"zone": zone})
        assert (
            connection.scalar(ADMIT, {"owner": quota["owner"], "kind": "energy_adjustment"}) is True
        )
    current = scalar(
        quota["admin"],
        "SELECT accepted_at FROM app.ai_energy_admissions WHERE owner_id=:owner",
        {"owner": quota["owner"]},
    )
    assert current - old >= timedelta(hours=336)


@pytest.mark.parametrize("context", ["missing", "deleting", "unknown_kind"])
def test_user_admission_requires_active_account_and_known_purpose(quota, context):
    owner = uuid4() if context == "missing" else quota["owner"]
    if context == "deleting":
        with quota["admin"].begin() as connection:
            begin_deletion(connection, owner, uuid4(), 1)
    with pytest.raises(DBAPIError) as failed:
        scalar(
            quota["api"],
            ADMIT,
            {"owner": owner, "kind": "not_e7" if context == "unknown_kind" else "food_photo"},
        )
    assert failed.value.orig.sqlstate == ("22023" if context == "unknown_kind" else "23514")
    assert scalar(quota["admin"], "SELECT count(*) FROM app.ai_admissions") == 0


@pytest.mark.parametrize(
    "instant,expected",
    [
        ("2026-01-01T07:59:59.999999+00:00", "2025-12-31"),
        ("2026-01-01T08:00:00+00:00", "2026-01-01"),
        ("2026-07-01T06:59:59.999999+00:00", "2026-06-30"),
        ("2026-07-01T07:00:00+00:00", "2026-07-01"),
        ("2026-03-08T09:59:59.999999+00:00", "2026-03-08"),
        ("2026-03-08T10:00:00+00:00", "2026-03-08"),
        ("2026-11-01T08:59:59.999999+00:00", "2026-11-01"),
        ("2026-11-01T09:00:00+00:00", "2026-11-01"),
    ],
)
def test_pacific_provider_day_exact_pst_pdt_dst_oracle(database, instant, expected):
    stamp = datetime.fromisoformat(instant)
    oracle = stamp.astimezone(ZoneInfo("America/Los_Angeles")).date()
    assert oracle == date.fromisoformat(expected)
    actual = scalar(database[0], "SELECT app.e7_provider_day(:instant)", {"instant": stamp})
    assert actual == oracle


@pytest.mark.parametrize(
    "zone,instant",
    [
        ("America/Los_Angeles", "2026-03-09T12:00:00+00:00"),
        ("America/Los_Angeles", "2026-11-02T12:00:00+00:00"),
        ("Europe/Warsaw", "2026-03-30T12:00:00+00:00"),
        ("Europe/Warsaw", "2026-10-26T12:00:00+00:00"),
        ("Pacific/Chatham", "2026-04-06T12:00:00+00:00"),
        ("Pacific/Chatham", "2026-09-28T12:00:00+00:00"),
        ("Australia/Sydney", "2026-04-06T12:00:00+00:00"),
        ("Australia/Sydney", "2026-10-05T12:00:00+00:00"),
        ("America/Santiago", "2026-04-06T12:00:00+00:00"),
        ("America/Santiago", "2026-09-07T12:00:00+00:00"),
        ("Pacific/Auckland", "2026-04-06T12:00:00+00:00"),
        ("Pacific/Auckland", "2026-09-28T12:00:00+00:00"),
    ],
)
def test_336_hours_has_fixed_elapsed_time_across_twelve_dst_transitions(database, zone, instant):
    # Historical arithmetic probe, not a claim that clock_timestamp was shifted.
    # Runtime admission is separately exercised against the real current DB clock.
    end = datetime.fromisoformat(instant)
    oracle = end - timedelta(hours=336)
    calendar_oracle = (end.astimezone(ZoneInfo(zone)) - timedelta(days=14)).astimezone(UTC)
    assert oracle != calendar_oracle, "fixture must straddle an actual offset transition"
    with database[0].begin() as connection:
        connection.scalar(text("SELECT set_config('TimeZone',:zone,true)"), {"zone": zone})
        actual = connection.execute(
            text(
                "SELECT CAST(:instant AS timestamptz)-interval '336 hours' "
                "AS fixed,CAST(:instant AS timestamptz)-interval '14 days' "
                "AS calendar"
            ),
            {"instant": end},
        ).one()
    assert actual.fixed == oracle and end - actual.fixed == timedelta(hours=336)
    assert actual.calendar == calendar_oracle


def test_key_rotation_keeps_stable_namespace_and_existing_request_token_day_consumption(
    quota, tmp_path
):
    confirmation = tmp_path / "synthetic-only-confirmation.json"
    confirmation.write_text(
        json.dumps(
            {
                "provider": "gemini",
                "project_id": "quota-fixture",
                "environment_id": "quota-fixture",
                "model": "gemini-3.5-flash-lite",
                "confirmed_at": "1970-01-01T00:00:00+00:00",
                "free_only": True,
                "billing_disabled": True,
                "development_only": True,
                "model_verified": True,
                "rpm": 1,
                "tpm": BUDGET,
                "rpd": 1,
                "quota_windows": {},
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        database_url=quota["url"],
        environment="development",
        ai_provider="gemini",
        ai_project_id="quota-fixture",
        ai_environment_id="quota-fixture",
        ai_live_confirmation=confirmation,
        gemini_api_key=SecretStr("synthetic-key-before"),
    )
    first_profile = configuration(settings)
    rotated_profile = configuration(
        settings.model_copy(update={"gemini_api_key": SecretStr("synthetic-key-after")})
    )
    assert first_profile.reason is None and rotated_profile.reason is None
    assert first_profile.profile == rotated_profile.profile
    scope = first_profile.profile["pool_scope"]
    with quota["admin"].begin() as connection:
        connection.execute(
            text(
                "INSERT INTO "
                "app.ai_pools(scope,provider,project,model,environment,rpm,tpm,rpd,confirmed_at,free_only)"
                " "
                "VALUES(:scope,'gemini','quota-fixture','gemini-3.5-flash-lite','quota-fixture',1,10240,1,clock_timestamp(),true)"
            ),
            {"scope": scope},
        )
        connection.execute(
            text(
                "INSERT INTO app.ai_transport_permits(environment,slot) "
                "VALUES('quota-fixture',1),('quota-fixture',2)"
            )
        )
    before, parameters = reserve(quota, scope=scope, kind="count_tokens")
    assert "attempt_id" in before and finish(quota, parameters)
    assert reserve(quota, scope=rotated_profile.profile["pool_scope"], purpose="energy_adjustment")[
        0
    ] == {"error": "ai_rate_limited"}
    scalar(
        quota["admin"],
        "UPDATE app.ai_attempts SET dispatched_at=clock_timestamp()-interval"
        " '61 seconds' WHERE id=:id RETURNING id",
        {"id": parameters["attempt"]},
    )
    assert reserve(quota, scope=scope, purpose="energy_adjustment")[0] == {
        "error": "ai_quota_exhausted"
    }
    assert ledger(quota, parameters["attempt"])["reserved_tokens"] == BUDGET
    assert (
        scalar(
            quota["admin"],
            "SELECT count(*) FROM app.ai_attempts WHERE pool_scope=:scope",
            {"scope": scope},
        )
        == 1
    )
