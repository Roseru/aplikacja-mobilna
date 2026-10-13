"""Fresh/populated additive0021 and effective privileges on real PG17/SCRAM."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from calorie_app.integrations.keycloak import Principal
from tests.integration.test_e4_deletion import seed
from tests.integration.test_e8_3_database import accept as legacy_accept
from tests.integration.test_e8_3_database import invite as legacy_invite
from tests.support.e8_4_postgres import activate, fresh_database, headers, runtime
from tests.support.e8_4_postgres import e8_4_services as e8_4_services

pytestmark = pytest.mark.integration
HEAD = "0021_e8_nemesis_results"
PRIVATE_TABLES = (
    "nemesis_projection_seeds",
    "nemesis_day_projections",
    "nemesis_final_results",
    "nemesis_runtime_contract",
)


def snapshot(engine, names=None):
    with engine.connect() as connection:
        names = names or [
            name
            for name in inspect(connection).get_table_names(schema="app")
            if name != "alembic_version"
        ]
        return {
            name: list(
                connection.scalars(
                    text(f'SELECT to_jsonb(t)::text FROM app."{name}" t ORDER BY to_jsonb(t)::text')
                )
            )
            for name in names
        }


@pytest.mark.parametrize("populated", [False, True])
def test_additive20_to21_preserves_sources_and_default_gate_closed(populated):
    with fresh_database() as private:
        migrator, api = private.engine(), private.engine("api")
        try:
            legacy = None
            if populated:
                participants = [
                    Principal("e8-test", str(uuid4()), frozenset({"user"})) for _ in range(2)
                ]
                owners = [seed(api, principal) for principal in participants]
                with migrator.begin() as connection:
                    epoch = connection.scalar(
                        text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
                    )
                    connection.execute(
                        text("INSERT INTO app.nemesis_releases VALUES('legacy-test','legacy-test')")
                    )
                    connection.execute(
                        text(
                            "UPDATE app.nemesis_control SET enabled=true,"
                            "projector_revision='legacy-test',finalizer_revision='legacy-test'"
                        )
                    )
                context = (migrator, api, epoch)
                legacy = legacy_invite(
                    context,
                    (owners[0], participants[0].subject),
                    (owners[1], participants[1].subject),
                )
                assert legacy_accept(context, (owners[1], participants[1].subject), legacy)["ok"]
            before = snapshot(migrator)
            private.migrate(HEAD)
            # Control acquires additive columns; all preexisting columns/rows
            # retain their values. Newly installed manifest/release are separate.
            retained = {
                name: rows
                for name, rows in before.items()
                if name not in {"nemesis_control", "nemesis_releases"}
            }
            assert snapshot(migrator, retained) == retained
            releases_after = [
                json.loads(row)
                for row in snapshot(migrator, ["nemesis_releases"])["nemesis_releases"]
            ]
            for old in map(json.loads, before["nemesis_releases"]):
                assert any(
                    all(row.get(key) == value for key, value in old.items())
                    for row in releases_after
                )
            with migrator.connect() as connection:
                assert (
                    connection.scalar(text("SELECT version_num FROM app.alembic_version")) == HEAD
                )
                assert not connection.scalar(text("SELECT app.e8n_gate()"))
                assert all(
                    connection.scalar(text(f"SELECT count(*) FROM app.{table}")) == 0
                    for table in PRIVATE_TABLES[:3]
                )
                assert (
                    connection.scalar(text("SELECT count(*) FROM app.nemesis_runtime_contract")) > 0
                )
                assert not connection.scalar(text("SELECT enabled FROM app.nemesis_control"))
                if legacy:
                    connection.execute(text("SELECT app.e8n_activate(:epoch)"), {"epoch": epoch})
                    connection.commit()
            if legacy:
                with api.begin() as connection:
                    result = connection.scalar(
                        text("SELECT app.e8n_statistics('e8-test',:subject,:epoch,:id)"),
                        {"subject": participants[0].subject, "epoch": epoch, "id": legacy["id"]},
                    )
                    assert (
                        result["http_status"] == 503
                        and result["code"] == "nemesis_statistics_unavailable"
                    )
                    metadata = connection.scalar(
                        text("SELECT app.e8n_read('e8-test',:subject,:epoch,:id)"),
                        {"subject": participants[0].subject, "epoch": epoch, "id": legacy["id"]},
                    )
                    assert metadata["ok"] and metadata["response"]["accepted_at"] is not None
        finally:
            api.dispose()
            migrator.dispose()


def test_new_private_facts_close_inherited_api_and_worker_default_table_grants():
    with fresh_database(HEAD) as private:
        for login in ("api", "worker"):
            engine = private.engine(login)
            try:
                with engine.connect() as connection:
                    assert connection.scalar(text("SELECT current_user=session_user"))
                    for table in PRIVATE_TABLES:
                        assert not connection.scalar(
                            text(
                                "SELECT has_any_column_privilege(current_user,:table,"
                                "'SELECT,INSERT,UPDATE,REFERENCES')"
                            ),
                            {"table": "app." + table},
                        )
                    assert not connection.scalar(
                        text(
                            "SELECT has_function_privilege(current_user,"
                            "'app.e8n_write_projection(uuid,uuid,text,timestamptz)','EXECUTE')"
                        )
                    )
                with pytest.raises(DBAPIError) as denied, engine.begin() as connection:
                    connection.execute(text("SELECT * FROM app.nemesis_day_projections"))
                assert denied.value.orig.sqlstate == "42501"
                with pytest.raises(DBAPIError) as denied, engine.begin() as connection:
                    connection.execute(
                        text(
                            "SELECT app.e8n_write_projection("
                            ":id,:owner,'inviter',clock_timestamp())"
                        ),
                        {"id": uuid4(), "owner": uuid4()},
                    )
                assert denied.value.orig.sqlstate == "42501"
            finally:
                engine.dispose()


def test_default_closed_and_fake_revision_pair_never_open_public_or_raw_api_gate():
    with runtime() as rt:
        for engine in (rt["api"], rt["worker"], rt["finalizer"]):
            with pytest.raises(DBAPIError) as denied, engine.begin() as connection:
                connection.execute(text("SELECT app.e8n_activate(:epoch)"), {"epoch": rt["epoch"]})
            assert denied.value.orig.sqlstate == "42501"
        for fake in (False, True):
            if fake:
                with rt["migrator"].begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO app.nemesis_releases("
                            "projector_revision,finalizer_revision,"
                            "schema_revision,initializer_revision) VALUES('fake-projector',"
                            "'fake-finalizer','fake-schema','fake-initializer')"
                        )
                    )
                    connection.execute(
                        text(
                            "UPDATE app.nemesis_control SET enabled=true,"
                            "projector_revision='fake-projector',finalizer_revision='fake-finalizer',"
                            "schema_revision='fake-schema',initializer_revision='fake-initializer'"
                        )
                    )
            response = rt["client"].post("/api/v1/me/nemesis/share-code", headers=headers(rt))
            assert response.status_code == 503 and response.headers["cache-control"] == "no-store"
            with rt["api"].begin() as connection:
                raw = connection.scalar(
                    text("SELECT app.e8n_execute(:issuer,:subject,:epoch,'issue',:key,:hash,'{}')"),
                    {
                        "issuer": "https://nemesis-identity.example.test/realm",
                        "subject": rt["actors"]["a"]["subject"],
                        "epoch": rt["epoch"],
                        "key": uuid4(),
                        "hash": "4" * 64,
                    },
                )
                assert raw["http_status"] == 503
        activate(rt)
        assert (
            rt["client"].post("/api/v1/me/nemesis/share-code", headers=headers(rt)).status_code
            == 200
        )


def test_real_finalizer_login_has_only_finalizer_functions_and_no_source_or_identity_access():
    with runtime() as rt:
        with rt["finalizer"].connect() as connection:
            assert connection.scalar(text("SELECT current_user=session_user"))
            for role in (
                "calorie_app_api",
                "calorie_app_migrator",
                "calorie_app_deletion_operator",
                "calorie_app_nemesis_worker",
            ):
                assert not connection.scalar(
                    text("SELECT pg_has_role(current_user,:role,'MEMBER')"), {"role": role}
                )
            for signature in (
                "app.e8n_source_refresh(uuid,integer,uuid,jsonb,uuid[])",
                "app.e8n_statistics(text,text,uuid,uuid)",
                "app.e8n_execute(text,text,uuid,text,uuid,text,jsonb)",
                "app.begin_account_deletion(uuid,uuid,integer)",
            ):
                assert not connection.scalar(
                    text("SELECT has_function_privilege(current_user,:signature,'EXECUTE')"),
                    {"signature": signature},
                )
            for table in (
                "meals",
                "diary_days",
                "weights",
                "goal_versions",
                "user_profiles",
                "user_accounts",
                "sync_counters",
                "nemesis_day_projections",
            ):
                assert not connection.scalar(
                    text(
                        "SELECT has_any_column_privilege(current_user,:table,"
                        "'SELECT,INSERT,UPDATE,REFERENCES')"
                    ),
                    {"table": "app." + table},
                )
