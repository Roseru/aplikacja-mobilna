"""Populated 0021->0022, drift, legacy snapshot source and empty downgrade."""

import json
import subprocess
import types
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from calorie_app.health import EXPECTED_REVISION
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
                    == EXPECTED_REVISION
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


def test_o2_populated_0021_to_current_graph_and_legacy_replay(tmp_path):
    """Migration release predecessor: E8 main a522471 / actual schema0021.

    Two real API LOGIN owners, local guest-shaped payload (no server guest),
    g/ml/null meals, history/goals, sync ACK/tombstone, catalogue and queued AI.
    Whole old row/column values plus independent semantic oracles are checked.
    """
    from pydantic import SecretStr
    from sqlalchemy import inspect

    from calorie_app.core.config import Settings
    from calorie_app.modules.catalog.service import import_catalog
    from calorie_app.modules.sync.router import execute_one, preflight
    from calorie_app.modules.sync.schemas import preflight_structure
    from calorie_app.modules.sync.snapshots import pull
    from tests.integration.test_e4_push import operation, request
    from tests.integration.test_e7_runtime import create, private_root, role_engine
    from tests.integration.test_e9_energy import sample

    with fresh_database("0021_e8_nemesis_results") as private:
        admin, api, migrator = (private.engine(name) for name in ("admin", "api", "migrator"))
        ai_worker = None
        ai_login = None
        try:
            principals = [Principal("e8-test", str(uuid4()), frozenset({"user"})) for _ in range(2)]
            boots = []
            for principal in principals:
                with Session(api) as s, s.begin():
                    boots.append(bootstrap(s, principal, uuid4()))
            rt = {"admin": admin, "api": api, "boots": boots, "principals": principals}
            goal, _, today = seed(rt)
            folder = private_root(tmp_path / "photos")
            rt.update(
                root=folder,
                settings=Settings(
                    database_url=private.api_url, environment="test", ai_photo_root=folder
                ),
            )
            photo = create(rt)
            ai_worker, ai_login = role_engine(
                (admin, None, private.admin_url), "calorie_app_ai_worker"
            )
            with admin.connect() as connection:
                job = connection.scalar(
                    text("SELECT id FROM app.ai_jobs WHERE analysis_id=:id"),
                    {"id": photo["analysis_id"]},
                )
            fence, attempt, transport = uuid4(), uuid4(), uuid4()
            with ai_worker.begin() as connection:
                assert (
                    connection.scalar(
                        text("SELECT app.e7_claim(:job,:fence)"), {"job": job, "fence": fence}
                    )
                    is not None
                )
                reservation = connection.scalar(
                    text("SELECT app.e7_dispatch(:job,:fence,'count_tokens',:attempt,:transport)"),
                    {"job": job, "fence": fence, "attempt": attempt, "transport": transport},
                )
                assert reservation["attempt_id"] == str(attempt)
            # No provider IO: preserve an uncertain reserved mock call across upgrade.
            catalog = json.loads((ROOT / "backend/data/demo/seed.json").read_text(encoding="utf-8"))
            import_catalog(migrator, catalog)
            secret = SecretStr("e4" * 32)
            factory = sessionmaker(api, expire_on_commit=False)
            account = owner(rt)
            from calorie_app.modules.profiles.schemas import ProfilePayload
            from calorie_app.modules.profiles.service import save_profile
            from tests.integration.test_e8_3_database import TERMS, accept, invite

            with Session(api) as session, session.begin():
                save_profile(
                    session,
                    UUID(boots[1]["account_id"]),
                    uuid4(),
                    ProfilePayload(
                        pseudonym="Synthetic B",
                        height_cm="180",
                        activity_class="stationary",
                        time_zone="UTC",
                    ),
                )
            with migrator.begin() as connection:
                connection.execute(
                    text("SELECT app.e8n_activate(:epoch)"), {"epoch": boots[0]["sync_epoch"]}
                )
            context = (migrator, api, boots[0]["sync_epoch"])
            participant_a = (account, principals[0].subject)
            participant_b = (UUID(boots[1]["account_id"]), principals[1].subject)
            invitation = invite(context, participant_a, participant_b, TERMS | {"time_zone": "UTC"})
            accepted_challenge = accept(context, participant_b, invitation)
            assert accepted_challenge["ok"], accepted_challenge
            cp = pull(factory, account, {}, secret)["checkpoint"]
            payload = sample("meal")
            payload["time_zone"] = "UTC"
            payload["items"] = [
                payload["items"][0] | {"item_id": str(uuid4())},
                payload["items"][0]
                | {
                    "item_id": str(uuid4()),
                    "basis_unit": "ml",
                    "quantity": {"amount": "250", "unit": "ml"},
                    "nutrition_per_100": {
                        "energy_kcal": "42",
                        "protein_g": None,
                        "fat_g": None,
                        "carbs_g": None,
                    },
                },
            ]
            payload["local_date"] = accepted_challenge["response"]["start_date"]
            payload["occurred_at"] = accepted_challenge["response"]["start_date"] + "T06:00:00Z"
            op = operation(boots[0], "meal", payload=payload)
            ration = catalog["rations"][0]
            op["payload"]["ration"] = {
                "ration_id": ration["ration_id"],
                "revision": ration["revision"],
                "name": ration["name"],
            }
            op["payload"]["items"][0]["product"] = ration["components"][0]["product"]
            op["payload"]["items"][0]["ration_component_position"] = 1

            def push(value):
                body = request(boots[0], cp, [value])
                preflight_structure(body)
                authorized, generation = preflight(factory, principals[0], body, secret)
                assert authorized == account
                return execute_one(factory, account, generation, body, value, secret)[0]

            assert push(op)["status"] == "accepted"
            dead = operation(boots[0])
            assert push(dead)["status"] == "accepted"
            removed = operation(boots[0], entity_id=dead["entity_id"], base=1, action="delete")
            assert push(removed)["status"] == "accepted"
            names = [
                name
                for name in inspect(admin).get_table_names(schema="app")
                if name
                not in {
                    "alembic_version",
                    "nemesis_releases",
                    "nemesis_runtime_contract",
                    "nemesis_control",
                }
            ]
            before = row_snapshot(admin, names)
            controls = row_snapshot(admin, ["nemesis_control"])["nemesis_control"]
            assert before["ai_attempts"] and before["ai_transport_permits"]
            assert before["nemesis_day_projections"]
            assert before["nemesis_projection_seeds"]
            private.migrate("head")
            after = row_snapshot(admin, names)
            assert row_snapshot(admin, ["nemesis_control"])["nemesis_control"] == [
                row | {"enabled": False} for row in controls
            ]
            for table, rows in before.items():
                assert len(after[table]) == len(rows), table
                # E9 adds columns to AI jobs; compare every existing column, keyed by
                # canonical old column projection so new columns cannot reorder rows.
                keys = set(rows[0]) if rows else set()

                def project(row, keys=keys):
                    return json.dumps({key: row[key] for key in keys}, sort_keys=True)

                assert sorted(map(project, after[table])) == sorted(map(project, rows)), table
            with admin.connect() as c:
                assert (
                    c.scalar(
                        text("SELECT reserved_tokens FROM app.ai_attempts WHERE id=:id"),
                        {"id": attempt},
                    )
                    == 10240
                )
                assert (
                    c.scalar(
                        text("SELECT count(*) FROM app.ai_transport_permits WHERE attempt_id=:id"),
                        {"id": attempt},
                    )
                    == 1
                )
                assert c.scalar(text("SELECT count(*) FROM app.nemesis_releases")) == 4
                assert c.scalar(text("SELECT app.e8n_runtime_ready()")) is True
                assert c.scalar(text("SELECT enabled FROM app.nemesis_control")) is False
                assert (
                    c.scalar(
                        text("SELECT ration FROM app.meals WHERE id=:id"), {"id": op["entity_id"]}
                    )
                    == op["payload"]["ration"]
                )
                assert c.scalar(
                    text("SELECT product_id FROM app.meal_items WHERE meal_id=:id AND position=1"),
                    {"id": op["entity_id"]},
                ) == UUID(ration["components"][0]["product"]["product_id"])
                assert c.scalar(text("SELECT count(*) FROM app.user_accounts")) == 2
                assert c.scalar(text("SELECT count(*) FROM app.meals")) == 15
                assert (
                    c.scalar(text("SELECT count(*) FROM app.weights WHERE deleted_at IS NULL")) == 4
                )
                assert (
                    c.scalar(text("SELECT count(*) FROM app.meal_items WHERE basis_unit='ml'")) == 1
                )
                assert (
                    c.scalar(
                        text(
                            "SELECT sum(quantity_amount*energy_kcal/100) FROM app.meal_items "
                            "WHERE meal_id=:id"
                        ),
                        {"id": op["entity_id"]},
                    )
                    == 235.5
                )
                assert (
                    c.scalar(
                        text("SELECT count(*) FROM app.ai_jobs WHERE analysis_id=:id"),
                        {"id": photo["analysis_id"]},
                    )
                    == 1
                )
                assert (
                    c.scalar(
                        text("SELECT (app.e9_resolve(:owner,:today)).maintenance_kcal"),
                        {"owner": account, "today": today},
                    )
                    == 2595
                )
                assert (
                    c.scalar(
                        text(
                            "SELECT baseline_id IS NULL FROM app.energy_axes WHERE owner_id=:owner"
                        ),
                        {"owner": account},
                    )
                    is True
                )
                assert (
                    c.scalar(text("SELECT id FROM app.goal_versions WHERE id=:id"), {"id": goal})
                    == goal
                )
            assert push(op)["status"] == "already_applied"
            assert push(removed)["status"] == "already_applied"
            other = pull(factory, UUID(boots[1]["account_id"]), {}, secret)
            assert all(item["entity_type"] == "profile" for item in other["entities"])
        finally:
            if ai_worker is not None:
                ai_worker.dispose()
                with admin.begin() as connection:
                    connection.exec_driver_sql(f'DROP OWNED BY "{ai_login}"')
                    connection.exec_driver_sql(f'DROP ROLE "{ai_login}"')
            for engine in (admin, api, migrator):
                engine.dispose()
