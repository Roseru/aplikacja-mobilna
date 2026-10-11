"""Actual catalogue-lock ordering and unchanged private exact meal snapshots."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_catalog_delivery import synthetic_official
from test_e6_community_publication import (  # noqa: F401
    boot,
    community_db,
    draft,
    publication,
    publish,
)
from test_e6_feedback_moderation import actors, feedback, merge, mutation, product, vote

from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.community.feedback import create_report
from calorie_app.modules.catalog.community.models import CommunityProduct, PublicationBinding
from calorie_app.modules.catalog.community.schemas import ReportRequest
from calorie_app.modules.catalog.community.service import publish_draft
from calorie_app.modules.catalog.export import publish_package
from calorie_app.modules.catalog.moderation.schemas import (
    ModerateProductRequest,
    ReportResolutionRequest,
)
from calorie_app.modules.catalog.moderation.service import moderate_product, resolve_report
from calorie_app.modules.catalog.service import import_catalog
from calorie_app.modules.diary.models import Meal, MealItem
from calorie_app.modules.diary.service import save_meal

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def seeded_official(engine):
    value = synthetic_official(count=1)
    imported = import_catalog(engine, value)
    return imported, UUID(value["products"][0]["product_id"])


def test_official_commit_before_waiting_selection_records_exact_release(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    actor, owner, epoch = boot(engine)
    entity, _ = draft(engine, owner)
    imported, official = seeded_official(engine)
    data = publication(entity, selected_product={"product_id": str(official), "revision": 1})
    held, release = Event(), Event()

    def hook(stage):
        if stage == "before_commit":
            held.set()
            assert release.wait(10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            publish_package, engine, imported.package_id, 1, tmp_path, fault_hook=hook
        )
        assert held.wait(10)
        waiting = pool.submit(publish, engine, actor, epoch, data)
        # PostgreSQL observes the waiting E6 transaction: it cannot read old
        # channel state through the catalogue decision lock.
        from time import monotonic, sleep

        deadline = monotonic() + 5
        blocked = False
        while monotonic() < deadline:
            with engine.connect() as conn:
                blocked = bool(
                    conn.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND query LIKE '%lock_community_catalog%'"
                        )
                    )
                )
            if blocked:
                break
            sleep(0.02)
        release.set()
        first.result(timeout=10)
        result = waiting.result(timeout=10)
    assert blocked and result.error is None
    assert result.payload == {
        "decision": "selected_existing",
        "product": {"product_id": str(official), "revision": 1},
    }
    with Session(engine) as session:
        binding = session.get(PublicationBinding, (owner, entity, 1))
        assert binding.result_minimal["official_release"] == 1
        assert session.get(CommunityProduct, official) is None


def test_official_commit_after_community_never_merges_or_adopts_votes(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    actor, owner, epoch = boot(engine)
    other = boot(engine)
    entity, _ = draft(engine, owner, name="Late official soup")
    data = publication(entity, aliases=[])
    imported, official = seeded_official(engine)
    held, release = Event(), Event()

    def blocked_publish(session, account, operation):
        result = publish_draft(session, account, data, operation)
        held.set()
        assert release.wait(10)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(mutation, engine, actor, epoch, "publish", blocked_publish)
        assert held.wait(10)
        waiting = pool.submit(publish_package, engine, imported.package_id, 1, tmp_path)
        from time import monotonic, sleep

        deadline, blocked = monotonic() + 5, False
        while monotonic() < deadline:
            with engine.connect() as conn:
                blocked = bool(
                    conn.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND wait_event_type='Lock' AND query LIKE '%lock_community_catalog%'"
                        )
                    )
                )
            if blocked:
                break
            sleep(0.02)
        release.set()
        result = first.result(timeout=10)
        waiting.result(timeout=10)
    assert blocked and result.error is None
    community = UUID(result.payload["product"]["product_id"])
    assert community != official
    assert vote(engine, other, community, 0, 1).error is None
    with Session(engine) as session:
        assert session.get(CommunityProduct, community).canonical_id is None
    assert feedback(engine, other, community)["voters"] == 1
    assert feedback(engine, other, official)["voters"] == 0


def test_official_votes_reports_referral_do_not_assign_moderator_authorship(request, tmp_path):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    imported, pid = seeded_official(engine)
    publish_package(engine, OFFICIAL_PACKAGE_ID, imported.release, tmp_path)
    assert feedback(engine, mod, pid)["is_mine"] is False
    assert vote(engine, mod, pid, 0, 1).error is None
    assert vote(engine, b, pid, 0, -1).error is None
    before = feedback(engine, a, pid)
    assert (before["positive_votes"], before["negative_votes"], before["voters"]) == (1, 1, 2)
    report = ReportRequest(
        product={"product_id": str(pid), "revision": 1},
        reason="label",
        description="synthetic official error",
    )
    created = mutation(
        engine, a[0], a[2], "report", lambda s, a, k: create_report(s, a, pid, report, k)
    )
    rid = UUID(created.payload["report_id"])
    decision = ReportResolutionRequest(
        expected_revision=1, status="resolved", reason="requires official source correction"
    )
    denied = mutation(
        engine, mod[0], mod[2], "resolve", lambda s, a, k: resolve_report(s, a, rid, decision, k)
    )
    assert denied.error.code == "official_report_requires_admin_release"
    referred = decision.model_copy(update={"status": "referred_to_admin"})
    result = mutation(
        engine, mod[0], mod[2], "resolve", lambda s, a, k: resolve_report(s, a, rid, referred, k)
    )
    assert result.payload["status"] == "referred_to_admin"
    patch = ModerateProductRequest(
        expected_state_revision=1, visibility="hidden", reason="not community"
    )
    assert (
        mutation(
            engine,
            mod[0],
            mod[2],
            "moderate",
            lambda s, a, k: moderate_product(s, a, pid, patch, k),
        ).error.code
        == "not_found"
    )


def test_old_meal_and_later_offline_exact_input_survive_merge_hide(request):
    engine = request.getfixturevalue("community_db")
    a, b, c, mod = actors(engine)
    source = product(engine, a[1], a[0], a[2], "History source")
    target = product(engine, b[1], b[0], b[2], "History target")
    payload = json.loads((ROOT / "contracts/examples/valid/meal.json").read_text(encoding="utf-8"))
    item = payload["items"][0]
    item.update(
        name="Historical source",
        product={"product_id": str(source), "revision": 1},
        nutrition_origin="catalog_snapshot",
        nutrition_per_100={
            "energy_kcal": "200",
            "protein_g": "2",
            "fat_g": "1",
            "carbs_g": "5",
        },
    )
    first = uuid4()
    with Session(engine) as session, session.begin():
        save_meal(session, c[1], first, payload)
    with engine.connect() as connection:
        before = connection.scalar(
            text("SELECT to_jsonb(t)::text FROM app.meal_items t WHERE meal_id=:m"), {"m": first}
        )
    assert merge(engine, mod, source, target).error is None
    hide = ModerateProductRequest(
        expected_state_revision=2, visibility="hidden", reason="synthetic moderation"
    )
    assert (
        mutation(
            engine,
            mod[0],
            mod[2],
            "moderate",
            lambda s, a, k: moderate_product(s, a, target, hide, k),
        ).error
        is None
    )
    # Old offline exact input is validated by immutable FK, not public visibility.
    payload["items"][0]["item_id"] = str(uuid4())
    second = uuid4()
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_api"))
        save_meal(session, c[1], second, payload)
    with engine.connect() as connection:
        after = connection.scalar(
            text("SELECT to_jsonb(t)::text FROM app.meal_items t WHERE meal_id=:m"), {"m": first}
        )
    assert before == after
    with Session(engine) as session:
        rows = list(session.scalars(select(MealItem).where(MealItem.meal_id.in_((first, second)))))
        assert len(rows) == 2
        assert all(row.product_id == source and row.product_revision == 1 for row in rows)
        assert all(str(row.energy_kcal) == "200.000000" for row in rows)
        assert session.get(Meal, first).revision == 1
