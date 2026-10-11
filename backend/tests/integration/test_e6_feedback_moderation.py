"""Runtime-role votes, reports, moderation, merge and exact historical reads."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_e6_community_publication import (  # noqa: F401
    boot,
    community_db,
    draft,
    publication,
    publish,
)

from calorie_app.core.config import Settings
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.feedback import (
    change_vote,
    create_report,
    public_feedback,
)
from calorie_app.modules.catalog.community.idempotency import execute_mutation
from calorie_app.modules.catalog.community.models import (
    CommunityAudit,
    CommunityProduct,
    CommunityVote,
)
from calorie_app.modules.catalog.community.repository import lock_catalog
from calorie_app.modules.catalog.community.schemas import ReportRequest
from calorie_app.modules.catalog.community.service import read_community
from calorie_app.modules.catalog.models import ProductVersion
from calorie_app.modules.catalog.moderation.reads import list_reports
from calorie_app.modules.catalog.moderation.router import ReportQuery
from calorie_app.modules.catalog.moderation.schemas import (
    MergeProductRequest,
    ModerateProductRequest,
    ReportResolutionRequest,
)
from calorie_app.modules.catalog.moderation.service import (
    merge_products,
    moderate_product,
    resolve_report,
)
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import require_account

pytestmark = pytest.mark.integration


def mutation(engine, who, epoch, kind, callback, key=None, semantic=None):
    key = key or uuid4()
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_api"))
        outcome = execute_mutation(
            session,
            who,
            kind,
            key,
            epoch,
            semantic or {"op": kind},
            lambda account: callback(session, account, key),
        )
    return outcome


def product(engine, owner, who, epoch, name):
    entity, _ = draft(engine, owner, name=name)
    result = publish(engine, who, epoch, publication(entity, aliases=[]))
    assert result.status == 200 and result.error is None
    return UUID(result.payload["product"]["product_id"])


def actors(engine):
    a = boot(engine)
    b = boot(engine)
    c = boot(engine)
    m, owner, epoch = boot(engine)
    m = Principal(m.issuer, m.subject, frozenset({"user", "catalog_moderator"}))
    return a, b, c, (m, owner, epoch)


def vote(engine, actor, pid, expected, value, key=None):
    return mutation(
        engine,
        actor[0],
        actor[2],
        "vote",
        lambda s, a, k: change_vote(s, a, pid, expected, value, k),
        key,
        {"pid": str(pid), "expected": expected, "value": value},
    )


def feedback(engine, actor, pid):
    with Session(engine) as session, session.begin():
        session.execute(text("SET LOCAL ROLE calorie_app_api"))
        account = require_account(session, actor[0])
        lock_catalog(session, shared=True)
        return public_feedback(session, account, pid)


def merge_body(target, source_revision=1, target_revision=1):
    return MergeProductRequest.model_validate(
        {
            "target": {"product_id": str(target), "revision": 1},
            "expected_source_state_revision": source_revision,
            "expected_target_state_revision": target_revision,
            "identity_confirmed": True,
            "reason": "identity confirmed against synthetic recipe",
        }
    )


def merge(engine, mod, source, target, key=None, source_revision=1, target_revision=1):
    body = merge_body(target, source_revision, target_revision)
    return mutation(
        engine,
        mod[0],
        mod[2],
        "merge",
        lambda s, a, k: merge_products(s, a, source, body, k),
        key,
        {"source": str(source), "body": body.model_dump(mode="json")},
    )


def test_replace_withdraw_tombstone_and_own_vote_revision(request):
    engine = request.getfixturevalue("community_db")
    a, b, c, _ = actors(engine)
    pid = product(engine, a[1], a[0], a[2], "First soup")
    assert vote(engine, a, pid, 0, 1).error.code == "own_product_vote"
    assert vote(engine, b, pid, 0, 1).payload == {"revision": 1, "value": 1}
    assert vote(engine, c, pid, 0, -1).payload["revision"] == 1
    # Another person's vote does not stale my own revision.
    assert vote(engine, b, pid, 1, -1).payload["revision"] == 2
    result = feedback(engine, b, pid)
    assert (result["positive_votes"], result["negative_votes"], result["voters"]) == (0, 2, 2)
    assert vote(engine, b, pid, 1, 1).error.code == "vote_revision_conflict"
    assert vote(engine, b, pid, 2, None).payload == {"revision": 3, "value": None}
    assert feedback(engine, b, pid)["my_revision"] == 3
    assert feedback(engine, b, pid)["my_value"] is None
    assert feedback(engine, b, pid)["voters"] == 1


def test_vote_replay_after_hide_and_epoch_before_resource(request):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    pid = product(engine, a[1], a[0], a[2], "Hidden soup")
    key = uuid4()
    first = vote(engine, b, pid, 0, 1, key)
    body = ModerateProductRequest(
        expected_state_revision=1, reason="synthetic hide", visibility="hidden"
    )
    hidden = mutation(
        engine, mod[0], mod[2], "moderate", lambda s, a, k: moderate_product(s, a, pid, body, k)
    )
    assert hidden.error is None
    assert vote(engine, b, pid, 0, 1, key).payload == first.payload
    assert vote(engine, b, pid, 1, -1).error.code == "not_found"
    assert vote(engine, b, pid, 0, -1, key).error.code == "idempotency_key_reused"
    from calorie_app.core.errors import DomainError

    with pytest.raises(DomainError) as failure:
        mutation(engine, b[0], uuid4(), "vote", lambda s, a, k: change_vote(s, a, uuid4(), 0, 1, k))
    assert failure.value.code == "sync_epoch_changed"


def test_merge_deactivates_source_and_all_authors_self_votes_once(request):
    engine = request.getfixturevalue("community_db")
    a, b, c, mod = actors(engine)
    source = product(engine, a[1], a[0], a[2], "Soup source")
    target = product(engine, b[1], b[0], b[2], "Soup target")
    assert vote(engine, a, target, 0, 1).error is None
    assert vote(engine, c, source, 0, 1).error is None
    assert vote(engine, c, target, 0, -1).error is None
    key = uuid4()
    result = merge(engine, mod, source, target, key)
    assert result.error is None
    summary = feedback(engine, c, target)
    assert (summary["positive_votes"], summary["negative_votes"], summary["voters"]) == (0, 1, 1)
    assert feedback(engine, a, target)["is_mine"] is True
    assert vote(engine, a, target, 1, -1).error.code == "own_product_vote"
    assert vote(engine, c, source, 1, -1).error.code == "product_merged"
    with Session(engine) as session:
        count = session.scalar(select(func.count()).select_from(CommunityAudit))
        source_vote = session.get(CommunityVote, (c[1], source))
        assert source_vote.active is False and source_vote.revision == 2
        old = session.get(ProductVersion, (source, 1))
        assert str(old.energy_kcal) == "200.000000"
    assert merge(engine, mod, source, target, key).payload == result.payload
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CommunityAudit)) == count
        exact = read_community(session, c[0], source, 1)
        assert exact["product_id"] == str(source)
        assert exact["canonical_ref"]["product_id"] == str(target)


def test_merge_flattens_groups_and_conflicting_recipe_is_denied(request):
    engine = request.getfixturevalue("community_db")
    a, b, c, mod = actors(engine)
    ids = [
        product(engine, actor[1], actor[0], actor[2], name)
        for actor, name in zip((a, b, c), ("Soup A", "Soup B", "Soup C"), strict=True)
    ]
    assert merge(engine, mod, ids[0], ids[1]).error is None
    assert merge(engine, mod, ids[1], ids[2], source_revision=2).error is None
    with Session(engine) as session:
        assert all(session.get(CommunityProduct, pid).canonical_id == ids[2] for pid in ids[:2])
        assert read_community(session, a[0], ids[0], 1)["canonical_ref"]["product_id"] == str(
            ids[2]
        )
    entity, _ = draft(engine, a[1], name="Other recipe")
    other = UUID(
        publish(engine, a[0], a[2], publication(entity, recipe="different ingredients")).payload[
            "product"
        ]["product_id"]
    )
    denied = merge(engine, mod, other, ids[2], target_revision=2)
    assert denied.error.code == "identity_conflict"


def test_correction_preserves_exact_values_and_verification_of_current_version(request):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    entity, payload = draft(engine, a[1], name="Incomplete soup", kcal=None)
    pid = UUID(
        publish(engine, a[0], a[2], publication(entity, confirm_new=True)).payload["product"][
            "product_id"
        ]
    )
    correction = {
        "name": payload["name"],
        "aliases": [],
        "identity": publication(entity).identity.model_dump(mode="json"),
        "basis_unit": "g",
        "nutrition_per_100": {"energy_kcal": "222", "protein_g": "2", "fat_g": "1", "carbs_g": "5"},
        "portion": payload["package_quantity"],
        "density": None,
        "source_kind": "recipe",
        "source_description": "confirmed synthetic recipe v2",
    }
    body = ModerateProductRequest.model_validate(
        {
            "expected_state_revision": 1,
            "reason": "confirmed exact v2 source",
            "correction": correction,
            "verification": "verified",
            "source_confirmed": True,
        }
    )
    result = mutation(
        engine, mod[0], mod[2], "moderate", lambda s, a, k: moderate_product(s, a, pid, body, k)
    )
    assert result.error is None and result.payload["product"]["revision"] == 2
    with Session(engine) as session:
        old = read_community(session, b[0], pid, 1)
        current = read_community(session, b[0], pid)
        assert (
            old["nutrition_per_100"]["energy_kcal"] is None and old["verification"] == "unverified"
        )
        assert (
            current["nutrition_per_100"]["energy_kcal"] == "222"
            and current["verification"] == "verified"
        )
        assert session.get(ProductVersion, (pid, 1)).energy_kcal is None


def test_report_queue_resolution_replay_and_revision_changed(request):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    pid = product(engine, a[1], a[0], a[2], "Reported soup")
    body = ReportRequest(
        product={"product_id": str(pid), "revision": 1},
        reason="nutrition",
        description="synthetic problem",
    )
    outcome = mutation(
        engine, b[0], b[2], "report", lambda s, a, k: create_report(s, a, pid, body, k)
    )
    rid = UUID(outcome.payload["report_id"])
    second = mutation(
        engine, b[0], b[2], "report", lambda s, a, k: create_report(s, a, pid, body, k)
    )
    assert second.status == 201
    secret = Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        catalog_page_token_secret="e6" * 32,
    ).catalog_page_token_secret
    with Session(engine) as session:
        first = list_reports(session, mod[0], ReportQuery(limit=1), secret)
    assert first["next_page_token"] is not None
    assert not any(key in str(first) for key in ("owner_id", "issuer", "subject", "draft_id"))
    decision = ReportResolutionRequest(
        expected_revision=1, status="dismissed", reason="synthetic review"
    )
    key = uuid4()
    decided = mutation(
        engine,
        mod[0],
        mod[2],
        "resolve",
        lambda s, a, k: resolve_report(s, a, rid, decision, k),
        key,
    )
    assert decided.payload["revision"] == 2
    assert (
        mutation(
            engine,
            mod[0],
            mod[2],
            "resolve",
            lambda s, a, k: resolve_report(s, a, rid, decision, k),
            key,
        ).payload
        == decided.payload
    )
    from calorie_app.core.errors import DomainError

    with Session(engine) as session, pytest.raises(DomainError) as failure:
        list_reports(
            session, mod[0], ReportQuery(limit=1, page_token=first["next_page_token"]), secret
        )
    assert failure.value.code == "moderation_queue_changed"


@pytest.mark.parametrize(
    "payload,status",
    [
        (b'{"ignored":"' + b"x" * 1048576 + b'"}', 413),
        (b'{"value":1,"value":-1}', 422),
        (b'{"value":' + b"[" * 21 + b"0" + b"]" * 21 + b"}", 422),
        (b'{"value":NaN}', 422),
    ],
    ids=["oversized", "duplicate-keys", "depth21", "nonfinite"],
)
def test_http_e6_early_bounded_errors_no_store(request, payload, status):
    engine = request.getfixturevalue("community_db")
    app = create_app(
        Settings(database_url=engine.url.render_as_string(hide_password=False)), engine=engine
    )
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/products/" + str(uuid4()) + "/vote",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"
    assert set(response.json()) == {"code", "message", "details", "request_id"}


def test_http_role_checked_before_replay_and_public_data_not_private(request):
    engine = request.getfixturevalue("community_db")
    a, _, _, mod = actors(engine)
    pid = product(engine, a[1], a[0], a[2], "Role soup")
    current = [mod[0]]
    app = create_app(
        Settings(database_url=engine.url.render_as_string(hide_password=False)), engine=engine
    )
    app.dependency_overrides[current_principal] = lambda: current[0]
    headers = {"Idempotency-Key": str(uuid4()), "X-Sync-Epoch": str(mod[2])}
    data = {"expected_state_revision": 1, "visibility": "hidden", "reason": "synthetic review"}
    with TestClient(app) as client:
        response = client.patch(
            "/api/v1/moderation/products/" + str(pid), json=data, headers=headers
        )
        assert response.status_code == 200
        current[0] = Principal(mod[0].issuer, mod[0].subject, frozenset({"user"}))
        replay = client.patch("/api/v1/moderation/products/" + str(pid), json=data, headers=headers)
        assert replay.status_code == 403 and replay.headers["Cache-Control"] == "no-store"
