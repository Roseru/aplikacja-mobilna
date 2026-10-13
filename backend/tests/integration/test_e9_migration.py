"""Populated 0021->0022, drift, legacy snapshot source and empty downgrade."""

import json
import subprocess
import types
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.integrations.keycloak import Principal
from calorie_app.modules.identity.service import bootstrap
from tests.integration.test_e9_energy import owner, seed
from tests.support.e8_4_postgres import e8_4_services as e8_4_services
from tests.support.e8_4_postgres import fresh_database

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
BASE = "a522471140150271d853d66aa06f11d868699e49"


def row_snapshot(engine, names):
    with engine.connect() as c:
        return {
            name: list(
                c.scalars(
                    text("SELECT to_jsonb(t) FROM app." + name + " t ORDER BY to_jsonb(t)::text")
                )
            )
            for name in names
        }


def test_populated_upgrade_preserves_sources_epoch_and_bootstraps_without_affirmation():
    with fresh_database("0021_e8_nemesis_results") as private:
        admin, api, migrator = (private.engine(name) for name in ("admin", "api", "migrator"))
        try:
            who = Principal("https://e9-migration.test", str(uuid4()), frozenset({"user"}))
            with Session(api) as s, s.begin():
                boot = bootstrap(s, who, uuid4())
            rt = {"admin": admin, "api": api, "boots": [boot]}
            goal, original, today = seed(rt)
            names = (
                "user_accounts",
                "user_profiles",
                "user_consents",
                "goal_versions",
                "goal_timelines",
                "diary_days",
                "meals",
                "meal_items",
                "weights",
                "installation_state",
                "sync_counters",
                "sync_changes",
            )
            before = row_snapshot(admin, names)
            private.migrate("head")
            assert row_snapshot(admin, names) == before
            imported = row_snapshot(admin, ["energy_versions"])
            with migrator.begin() as c:
                assert (
                    c.scalar(
                        text("SELECT (app.e9_resolve(:owner,:today)).maintenance_kcal"),
                        {"owner": owner(rt), "today": today},
                    )
                    == 2595
                )
                assert c.scalar(text("SELECT baseline_id IS NULL FROM app.energy_axes")) is True
                assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 1
                c.execute(
                    text("SELECT app.e9_legacy_import(:owner,:id)"),
                    {"owner": owner(rt), "id": goal},
                )
            assert row_snapshot(admin, ["energy_versions"]) == imported
            with admin.connect() as c:
                assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 1
            cfg = Config(str(ROOT / "backend/alembic.ini"))
            with migrator.begin() as c:
                cfg.attributes["connection"] = c
                command.check(cfg)
        finally:
            for engine in (admin, api, migrator):
                engine.dispose()


def test_real_published_legacy_snapshot_source_skips_new_marker():
    with fresh_database("0024_e9_history_graph") as private:
        admin, api = (private.engine(name) for name in ("admin", "api"))
        try:
            who = Principal("https://e9-legacy.test", str(uuid4()), frozenset({"user"}))
            with Session(api) as s, s.begin():
                boot = bootstrap(s, who, uuid4())
            rt = {"admin": admin, "api": api, "boots": [boot]}
            goal, _, _ = seed(rt)
            raw = subprocess.run(
                ["git", "show", BASE + ":backend/src/calorie_app/modules/sync/snapshots.py"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            ).stdout
            legacy = types.ModuleType("published_legacy_snapshot")
            exec(compile(raw, "published-a522-snapshots.py", "exec"), legacy.__dict__)
            secret = "e4" * 32
            old = legacy.pull(sessionmaker(api), owner(rt), {}, secret)
            with Session(api) as s, s.begin():
                data = {"axis_revision": 1, "id": str(goal), "replace_id": None}
                result = s.scalar(
                    text(
                        "SELECT app.e9_mutate(:owner,1,:epoch,:key,'revert',CAST(:bod"
                        "y AS jsonb),NULL)"
                    ),
                    {
                        "owner": owner(rt),
                        "epoch": boot["sync_epoch"],
                        "key": uuid4(),
                        "body": json.dumps(data),
                    },
                )
                assert "error" not in result, result
            page = legacy.pull(
                sessionmaker(api),
                owner(rt),
                {"checkpoint": old["checkpoint"], "sync_epoch": boot["sync_epoch"]},
                secret,
            )
            assert page["entities"] == [] and page["checkpoint"] != old["checkpoint"]
            with admin.connect() as c:
                assert (
                    c.scalar(
                        text(
                            "SELECT entity IS NULL FROM app.sync_changes ORDER BY positio"
                            "n DESC LIMIT 1"
                        )
                    )
                    is True
                )
                assert c.scalar(text("SELECT count(*) FROM app.energy_changes")) == 1
        finally:
            admin.dispose()
            api.dispose()


def test_empty_e9_downgrade_reupgrade_preserves_legacy_contract():
    with fresh_database("0024_e9_history_graph") as private:
        engine = private.engine()
        cfg = Config(str(ROOT / "backend/alembic.ini"))
        try:
            with engine.begin() as c:
                cfg.attributes["connection"] = c
                command.downgrade(cfg, "0021_e8_nemesis_results")
                assert c.scalar(text("SELECT to_regclass('app.energy_versions')")) is None
                assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is True
            cfg.attributes.pop("connection", None)
            private.migrate("head")
            with engine.connect() as c:
                assert (
                    c.scalar(text("SELECT version_num FROM app.alembic_version"))
                    == "0024_e9_history_graph"
                )
                assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is True
        finally:
            engine.dispose()


def test_queued_photo_survives_upgrade_and_new_typed_runner(tmp_path):
    from psycopg import sql

    from calorie_app.core.config import Settings
    from calorie_app.modules.jobs.runner import Runner
    from tests.integration.test_e7_runtime import create, private_root, role_engine

    with fresh_database("0021_e8_nemesis_results") as private:
        admin, api = (private.engine(name) for name in ("admin", "api"))
        worker = None
        login = None
        try:
            who = Principal("https://e9-photo-upgrade.test", str(uuid4()), frozenset({"user"}))
            with Session(api) as s, s.begin():
                boot = bootstrap(s, who, uuid4())
            folder = private_root(tmp_path / "photo-private")
            settings = Settings(
                database_url=private.api_url, environment="test", ai_photo_root=folder
            )
            rt = {
                "admin": admin,
                "api": api,
                "boots": [boot],
                "principals": [who],
                "root": folder,
                "settings": settings,
            }
            queued = create(rt)
            names = ("ai_analyses", "ai_photo_consents", "ai_jobs")
            before = row_snapshot(admin, names)
            private.migrate("head")
            after = row_snapshot(admin, names)
            for table, rows in before.items():
                assert len(after[table]) == len(rows)
                for old, new in zip(rows, after[table], strict=True):
                    assert all(new.get(key) == value for key, value in old.items())
            worker, login = role_engine((admin, None, private.admin_url), "calorie_app_ai_worker")
            with admin.connect() as c:
                job = c.scalar(
                    text("SELECT id FROM app.ai_jobs WHERE analysis_id=:id"),
                    {"id": queued["analysis_id"]},
                )
            assert Runner(worker, lambda: Session(worker), settings).process(job)
            with admin.connect() as c:
                assert (
                    c.scalar(
                        text("SELECT state FROM app.ai_analyses WHERE id=:id"),
                        {"id": queued["analysis_id"]},
                    )
                    == "succeeded"
                )
                assert c.scalar(text("SELECT count(*) FROM app.energy_analyses")) == 0
        finally:
            if worker is not None:
                worker.dispose()
                with admin.begin() as c:
                    pg = c.connection.driver_connection
                    c.exec_driver_sql(
                        sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
                    )
                    c.exec_driver_sql(
                        sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
                    )
            admin.dispose()
            api.dispose()


def test_0023_qualifies_existing_duplicate_artifact_without_rewriting_history(tmp_path):
    from datetime import timedelta

    from calorie_app.core.config import Settings
    from calorie_app.modules.jobs.runner import Runner
    from calorie_app.modules.profiles.schemas import GoalPayload
    from calorie_app.modules.profiles.service import create_goal
    from tests.integration.test_e7_runtime import private_root, role_engine
    from tests.integration.test_e9_energy import create, decision, post, read

    with fresh_database("0022_e9_energy") as private:
        admin, api = (private.engine(name) for name in ("admin", "api"))
        worker, login = role_engine((admin, None, private.admin_url), "calorie_app_ai_worker")
        try:
            principal = Principal("https://e9-artifact.test", str(uuid4()), frozenset({"user"}))
            with Session(api) as session, session.begin():
                boot = bootstrap(session, principal, uuid4())
            folder = private_root(tmp_path / "private-artifact")
            settings = Settings(
                database_url=private.api_url, environment="test", ai_photo_root=folder
            )
            rt = {
                "admin": admin,
                "api": api,
                "boots": [boot],
                "principals": [principal],
                "root": folder,
                "settings": settings,
            }
            _, goal, today = seed(rt)
            with admin.begin() as c:
                c.execute(
                    text(
                        "UPDATE app.ai_controls SET dispatch_open=true,sync_epoch="
                        "(SELECT sync_epoch FROM app.installation_state WHERE id=1)"
                    )
                )
                c.execute(
                    text(
                        "UPDATE app.ai_pools SET enabled=true,rpm=100,tpm=1000000,rpd=10000 "
                        "WHERE provider='mock'"
                    )
                )
                c.execute(
                    text(
                        "INSERT INTO app.ai_transport_permits(environment,slot) "
                        "VALUES('local',1),('local',2) ON CONFLICT DO NOTHING"
                    )
                )
            analysis = create(rt)
            assert Runner(worker, lambda: Session(worker), settings).cycle() == 1
            accepted = post(rt, "analyses/accept", decision(rt, read(rt, analysis["id"]).json()))
            assert accepted.status_code == 200, accepted.text
            clone = goal | {
                "energy_kcal": "2300",
                "timeline_base_revision": 1,
                "effective_from": (today + timedelta(days=1)).isoformat(),
                "decided_at": today.isoformat() + "T12:00:00Z",
            }
            with Session(api) as session, session.begin():
                create_goal(session, owner(rt), uuid4(), GoalPayload.model_validate(clone))
            with admin.connect() as c:
                assert (
                    c.scalar(
                        text("SELECT (app.e9_resolve(:o,:d)).maintenance_kcal"),
                        {"o": owner(rt), "d": today + timedelta(days=1)},
                    )
                    == 2595
                )
            names = (
                "goal_versions",
                "goal_timelines",
                "energy_versions",
                "energy_axes",
                "energy_analyses",
            )
            before = row_snapshot(admin, names)
            private.migrate("head")
            assert row_snapshot(admin, names) == before
            with admin.connect() as c:
                assert (
                    c.scalar(
                        text("SELECT (app.e9_resolve(:o,:d)).maintenance_kcal"),
                        {"o": owner(rt), "d": today + timedelta(days=1)},
                    )
                    == 2700
                )
                assert (
                    c.scalar(
                        text(
                            "SELECT has_function_privilege('calorie_app_motivation_worker',"
                            "'app.e8n_delete_helper(uuid,uuid,boolean)','EXECUTE')"
                        )
                    )
                    is False
                )
            fresh = clone | {
                "timeline_base_revision": 2,
                "effective_from": (today + timedelta(days=2)).isoformat(),
                "estimate": goal["estimate"] | {"estimated_at": today.isoformat() + "T12:00:00Z"},
            }
            with Session(api) as session, session.begin():
                create_goal(session, owner(rt), uuid4(), GoalPayload.model_validate(fresh))
            with admin.connect() as c:
                assert c.scalar(text("SELECT count(*) FROM app.energy_versions")) == 4
                assert (
                    c.scalar(
                        text("SELECT (app.e9_resolve(:o,:d)).maintenance_kcal"),
                        {"o": owner(rt), "d": today + timedelta(days=2)},
                    )
                    == 2595
                )
        finally:
            worker.dispose()
            with admin.begin() as c:
                pg = c.connection.driver_connection
                from psycopg import sql

                c.exec_driver_sql(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)).as_string(pg)
                )
                c.exec_driver_sql(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(login)).as_string(pg)
                )
            admin.dispose()
            api.dispose()


def test_forward_0024_refuses_drifted_parent_even_if_0023_rehashed_it():
    from sqlalchemy.exc import DBAPIError

    with fresh_database("0022_e9_energy") as private:
        engine = private.engine("migrator")
        try:
            with engine.begin() as c:
                c.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION app.e8n_source_in_transaction(p_xmin xid) "
                        "RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER "
                        "SET search_path=pg_catalog,pg_temp AS 'SELECT true'"
                    )
                )
                assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is False
            with pytest.raises(DBAPIError, match="parent Nemesis contract drift"):
                private.migrate("head")
            with engine.connect() as c:
                assert (
                    c.scalar(text("SELECT version_num FROM app.alembic_version"))
                    == "0022_e9_energy"
                )
                assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is False
        finally:
            engine.dispose()
