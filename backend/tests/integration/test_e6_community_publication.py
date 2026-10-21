"""Real PG publication ownership, exact replay, races and bounded reads."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.core.errors import DomainError
from calorie_app.integrations.keycloak import Principal
from calorie_app.main import create_app
from calorie_app.modules.catalog.community.idempotency import execute_mutation
from calorie_app.modules.catalog.community.models import (
    CommunityAuthor,
    CommunityProduct,
    CommunityQuota,
    CommunityReceipt,
    PublicationBinding,
)
from calorie_app.modules.catalog.community.repository import bump_catalog, lock_catalog
from calorie_app.modules.catalog.community.router import CommunityQuery, router
from calorie_app.modules.catalog.community.schemas import PublishProductRequest
from calorie_app.modules.catalog.community.service import (
    list_community,
    match_draft,
    publish_draft,
    read_community,
)
from calorie_app.modules.catalog.community.tokens import decode_page
from calorie_app.modules.catalog.pagination import database_now
from calorie_app.modules.diary.models import ProductDraft
from calorie_app.modules.identity.dependencies import current_principal
from calorie_app.modules.identity.service import bootstrap
from tests.support.deletion_regression import begin as begin_deletion

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]
SECRET = SecretStr("e6" * 32)


def principal():
    return Principal("https://identity.example.test/e6", str(uuid4()), frozenset({"user"}))


@pytest.fixture
def community_db(database):
    engine, _, _ = database
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE app.user_accounts,app.products,app.product_sources,"
                "app.offline_packages,app.rations CASCADE"
            )
        )
    yield engine
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE app.user_accounts,app.products,app.product_sources,"
                "app.offline_packages,app.rations CASCADE"
            )
        )


def boot(engine):
    who = principal()
    with Session(engine) as session, session.begin():
        result = bootstrap(session, who, uuid4())
    return who, UUID(result["account_id"]), UUID(result["sync_epoch"])


def draft(engine, owner, *, name="Rosół", kcal="200", portion="100", unit="g", density=None):
    value = json.loads((ROOT / "contracts/examples/valid/product-draft.json").read_text())
    value.update(
        name=name,
        basis_unit=unit,
        package_quantity={"amount": portion, "unit": unit},
        density_g_per_ml=density,
        density_source="synthetic density" if density else None,
    )
    value["nutrition_per_100"] = {
        "energy_kcal": kcal,
        "protein_g": "2",
        "fat_g": "1",
        "carbs_g": "5",
    }
    entity = uuid4()
    with Session(engine) as session, session.begin():
        session.add(ProductDraft(id=entity, owner_id=owner, revision=1, payload=value))
    return entity, value


def publication(entity, *, recipe="woda i marchew", **changes):
    value = {
        "draft_id": str(entity),
        "draft_revision": 1,
        "source_kind": "recipe",
        "source_description": "synthetic recipe approved for publication",
        "identity": {
            "brand": {"state": "not_applicable", "value": None},
            "variant": {"state": "not_applicable", "value": None},
            "composition": {"state": "known", "value": recipe},
        },
        "aliases": ["Domowy rosół"],
    }
    return PublishProductRequest.model_validate(value | changes)


def publish(engine, who, epoch, data, key=None):
    key = key or uuid4()
    with Session(engine) as session, session.begin():
        return execute_mutation(
            session,
            who,
            "publish_product",
            key,
            epoch,
            {"method": "POST", "path": "/api/v1/products", "body": data.model_dump(mode="json")},
            lambda account: publish_draft(session, account, data, key),
        )


def test_publication_binding_replay_and_unchanged_private_payload(community_db):
    who, owner, epoch = boot(community_db)
    entity, original = draft(community_db, owner)
    data, key = publication(entity), uuid4()
    first = publish(community_db, who, epoch, data, key)
    assert first.status == 200 and first.payload["decision"] == "new_product"
    assert publish(community_db, who, epoch, data, key).payload == first.payload
    assert publish(community_db, who, epoch, data).payload == first.payload
    changed = publication(entity, source_description="changed metadata")
    assert publish(community_db, who, epoch, changed).error.code == "draft_already_published"
    assert publish(community_db, who, epoch, changed, key).error.code == "idempotency_key_reused"
    with Session(community_db) as session:
        assert session.get(ProductDraft, entity).payload == original
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == 1
        assert session.scalar(select(func.count()).select_from(PublicationBinding)) == 1
        assert session.scalar(select(func.count()).select_from(CommunityAuthor)) == 1
        quota = session.scalar(select(CommunityQuota).where(CommunityQuota.owner_id == owner))
        assert (quota.products, quota.receipts) == (1, 3)
    product = UUID(first.payload["product"]["product_id"])
    with Session(community_db) as session, session.begin():
        public = read_community(session, who, product)
        assert public["complete"] is True and public["is_mine"] is True
        assert not any("owner" in key or "draft" in key for key in public)
        assert public["nutrition_per_100"]["energy_kcal"] == "200"


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("foreign", "not_found"),
        ("missing", "not_found"),
        ("deleted", "not_found"),
        ("stale", "draft_revision_conflict"),
    ],
)
def test_owned_live_revision_errors_are_durable(community_db, scenario, code):
    who, owner, epoch = boot(community_db)
    _, other, _ = boot(community_db)
    entity, _ = draft(community_db, other if scenario == "foreign" else owner)
    if scenario == "missing":
        entity = uuid4()
    elif scenario in {"deleted", "stale"}:
        with Session(community_db) as session, session.begin():
            row = session.get(ProductDraft, entity)
            if scenario == "deleted":
                row.deleted_at = database_now(session)
            else:
                row.revision = 2
    key, data = uuid4(), publication(entity)
    outcome = publish(community_db, who, epoch, data, key)
    assert outcome.error.code == code
    assert publish(community_db, who, epoch, data, key).replayed
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(CommunityReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == 0


def test_unknown_energy_and_composition_require_conscious_new(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner, kcal=None)
    data = publication(entity)
    with Session(community_db) as session, session.begin():
        result = match_draft(session, who, data, epoch)
    assert result["decision"] == "manual_candidates" and result["candidates"] == []
    assert result["missing_identity_fields"] == ["energy_kcal"]
    assert publish(community_db, who, epoch, data).error.code == "publication_confirmation_required"
    data = PublishProductRequest.model_validate(
        data.model_dump(mode="json") | {"confirm_new": True}
    )
    first = publish(community_db, who, epoch, data)
    with Session(community_db) as session, session.begin():
        public = read_community(session, who, UUID(first.payload["product"]["product_id"]))
    assert public["complete"] is False and public["missing_nutrition_fields"] == ["energy_kcal"]


def test_fuzzy_simultaneous_publications_one_product_different_portions(community_db):
    a, owner_a, epoch = boot(community_db)
    b, owner_b, _ = boot(community_db)
    da, _ = draft(community_db, owner_a, kcal="200", portion="100")
    db, _ = draft(community_db, owner_b, kcal="190", portion="300")
    gate = Barrier(2)

    def write(who, data):
        gate.wait(timeout=10)
        return publish(community_db, who, epoch, data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(write, a, publication(da)), pool.submit(write, b, publication(db))
        results = [fa.result(timeout=15), fb.result(timeout=15)]
    assert {outcome.payload["decision"] for outcome in results} == {
        "new_product",
        "existing_variant",
    }
    assert results[0].payload["product"] == results[1].payload["product"]
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == 1
        assert session.scalar(select(func.count()).select_from(PublicationBinding)) == 2
        assert session.scalar(select(func.count()).select_from(CommunityAuthor)) == 1
        assert session.get(ProductDraft, da).payload["package_quantity"]["amount"] == "100"
        assert session.get(ProductDraft, db).payload["package_quantity"]["amount"] == "300"


def test_two_retries_identical_key_and_changed_body(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    key, gate = uuid4(), Barrier(2)

    def write(data):
        gate.wait(timeout=10)
        return publish(community_db, who, epoch, data, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(write, publication(entity)), pool.submit(write, publication(entity))
        first, second = fa.result(timeout=15), fb.result(timeout=15)
    assert first.payload == second.payload and sum((first.replayed, second.replayed)) == 1
    key, gate = uuid4(), Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(write, publication(entity))
        fb = pool.submit(write, publication(entity, source_description="changed body"))
        outcomes = [fa.result(timeout=15), fb.result(timeout=15)]
    assert sum(outcome.error is not None for outcome in outcomes) >= 1
    assert any(
        outcome.error and outcome.error.code == "idempotency_key_reused" for outcome in outcomes
    )


@pytest.mark.parametrize("kcal,expected", [("180", "existing_variant"), ("179", "new_product")])
def test_full_sql_density_boundary_matches_independent_known_values(community_db, kcal, expected):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner, kcal="240", unit="ml", density="1.2")
    first = publish(community_db, who, epoch, publication(entity))
    other, _ = draft(community_db, owner, kcal=kcal)
    second = publish(community_db, who, epoch, publication(other))
    assert second.payload["decision"] == expected
    assert (first.payload["product"] == second.payload["product"]) == (
        expected == "existing_variant"
    )


def test_replay_after_hide_and_cleanup_never_republishes(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    data, key = publication(entity), uuid4()
    first = publish(community_db, who, epoch, data, key)
    product = UUID(first.payload["product"]["product_id"])
    with Session(community_db) as session, session.begin():
        lock_catalog(session)
        state = session.get(CommunityProduct, product)
        state.visibility = "hidden"
        state.state_revision += 1
        bump_catalog(session)
    assert publish(community_db, who, epoch, data, key).payload == first.payload
    with Session(community_db) as session, session.begin():
        with pytest.raises(DomainError) as failure:
            read_community(session, who, product)
        assert failure.value.status == 404
        receipt = session.get(CommunityReceipt, (owner, "publish_product", key))
        receipt.created_at = database_now(session) - timedelta(days=61)
    with community_db.begin() as connection:
        connection.execute(
            text("SELECT app.prune_community_receipts(:owner,100)"), {"owner": owner}
        )
    expired = publish(community_db, who, epoch, data, key)
    assert expired.error.code == "idempotency_result_expired"
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == 1


def test_epoch_precedence_and_deleting_replay_without_effects(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    data, key = publication(entity), uuid4()
    publish(community_db, who, epoch, data, key)
    with Session(community_db) as session, session.begin():
        session.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": uuid4()}
        )
    try:
        with pytest.raises(DomainError) as failure:
            publish(community_db, who, epoch, data, uuid4())
        assert failure.value.code == "sync_epoch_changed"
        with Session(community_db) as session, session.begin():
            # Restore the source epoch after independently checking epoch denial;
            # a fenced source must not authorize a new lifecycle transition.
            session.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": epoch}
            )
            begin_deletion(session.connection(), owner, uuid4(), 1)
        with pytest.raises(DomainError) as failure:
            publish(community_db, who, epoch, data, key)
        assert failure.value.code == "account_deleting"
    finally:
        with community_db.begin() as connection:
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:epoch"), {"epoch": epoch}
            )


def test_savepoint_denial_rolls_back_effect_and_records_one_denial(community_db):
    who, owner, epoch = boot(community_db)
    key = uuid4()

    def denied(account):
        session.add(
            ProductDraft(
                id=uuid4(),
                owner_id=account.id,
                revision=1,
                payload=json.loads(
                    (ROOT / "contracts/examples/valid/product-draft.json").read_text()
                ),
            )
        )
        session.flush()
        raise DomainError(409, "synthetic_denial")

    with Session(community_db) as session, session.begin():
        outcome = execute_mutation(session, who, "probe", key, epoch, {"path": "probe"}, denied)
    assert outcome.error.code == "synthetic_denial"
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(ProductDraft)) == 0
        assert session.scalar(select(func.count()).select_from(CommunityReceipt)) == 1


def test_catalog_tokens_bind_version_owner_filter_and_byte_budget(community_db, monkeypatch):
    who, owner, epoch = boot(community_db)
    other, _, _ = boot(community_db)
    for i in range(3):
        entity, _ = draft(community_db, owner, name=f"Produkt {i}")
        publish(community_db, who, epoch, publication(entity, recipe=f"przepis {i}"))
    query = CommunityQuery(limit=1)
    with Session(community_db) as session, session.begin():
        first = list_community(session, who, query, SECRET)
        now = database_now(session)
        token = first["next_page_token"]
        claims = decode_page(
            token, SECRET, owner=owner, generation=1, epoch=epoch, query=None, limit=1, now=now
        )
    assert len(first["items"]) == 1 and token
    second_query = CommunityQuery(limit=1, page_token=token)
    with Session(community_db) as session, session.begin():
        second = list_community(session, who, second_query, SECRET)
        next_claims = decode_page(
            second["next_page_token"],
            SECRET,
            owner=owner,
            generation=1,
            epoch=epoch,
            query=None,
            limit=1,
            now=now,
        )
        assert next_claims["expiry"] == claims["expiry"]
        with pytest.raises(DomainError):
            list_community(session, other, second_query, SECRET)
        lock_catalog(session)
        bump_catalog(session)
    with Session(community_db) as session, session.begin():
        with pytest.raises(DomainError) as failure:
            list_community(session, who, second_query, SECRET)
        assert failure.value.code == "catalog_changed"
    monkeypatch.setattr("calorie_app.modules.catalog.community.service.PAGE_BYTES", 4300)
    with Session(community_db) as session, session.begin():
        with pytest.raises(DomainError) as failure:
            list_community(session, who, query, SECRET)
        assert failure.value.code == "community_record_too_large"


def test_receipt_admission_race_at_cap_and_replay_free(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    data, key = publication(entity), uuid4()
    first = publish(community_db, who, epoch, data, key)
    with community_db.begin() as connection:
        connection.execute(
            text("UPDATE app.community_quotas SET receipts=999 WHERE owner_id=:owner"),
            {"owner": owner},
        )
    gate = Barrier(2)

    def write():
        gate.wait(timeout=10)
        try:
            return publish(community_db, who, epoch, data)
        except DomainError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa, fb = pool.submit(write), pool.submit(write)
        results = [fa.result(timeout=15), fb.result(timeout=15)]
    assert sum(isinstance(result, DomainError) and result.status == 429 for result in results) == 1
    assert publish(community_db, who, epoch, data, key).payload == first.payload
    with Session(community_db) as session:
        assert (
            session.scalar(select(CommunityQuota.receipts).where(CommunityQuota.owner_id == owner))
            == 1000
        )
        assert session.scalar(select(func.count()).select_from(CommunityReceipt)) == 2


def test_http_ownership_spoof_missing_auth_epoch_and_strict_queries(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    settings = Settings(
        database_url=SecretStr(str(community_db.url)),
        environment="test",
        catalog_page_token_secret=SECRET,
    )
    app = create_app(settings, engine=community_db)
    if "/api/v1/community/products" not in app.openapi()["paths"]:
        app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/v1/community/products").status_code == 401
        app.dependency_overrides[current_principal] = lambda: who
        payload = publication(entity).model_dump(mode="json")
        headers = {"Idempotency-Key": str(uuid4()), "X-Sync-Epoch": str(epoch)}
        assert (
            client.post(
                "/api/v1/products", json=payload | {"owner_id": str(uuid4())}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/products", json=payload, headers={"Idempotency-Key": str(uuid4())}
            ).status_code
            == 422
        )
        result = client.post("/api/v1/products", json=payload, headers=headers)
        assert result.status_code == 200
        product = result.json()["product"]["product_id"]
        exact = client.get(f"/api/v1/community/products/{product}?revision=1")
        assert exact.status_code == 200 and exact.headers["Cache-Control"] == "no-store"
        assert client.get("/api/v1/community/products?owner_id=spoof").status_code == 422
        assert client.get("/api/v1/community/products?limit=501").status_code == 422
        with community_db.begin() as connection:
            connection.execute(
                text("UPDATE app.community_quotas SET receipts=1000 WHERE owner_id=:owner"),
                {"owner": owner},
            )
        throttled = client.post(
            "/api/v1/products", json=payload, headers=headers | {"Idempotency-Key": str(uuid4())}
        )
        assert throttled.status_code == 429
        assert int(throttled.headers["Retry-After"]) > 0
        assert throttled.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("action", ["edit", "delete", "deleting"])
@pytest.mark.parametrize("publish_first", [True, False])
def test_actual_account_barriers_publish_vs_draft_or_deletion(community_db, action, publish_first):
    from threading import Event

    from calorie_app.modules.identity.service import require_account
    from tests.support.deletion_regression import begin_deleting

    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    data, key = publication(entity), uuid4()
    acquired, release = Event(), Event()

    def publish_with_barrier():
        def effect(account):
            result = publish_draft(session, account, data, key)
            if publish_first:
                acquired.set()
                assert release.wait(timeout=10)
            return result

        with Session(community_db) as session, session.begin():
            return execute_mutation(
                session,
                who,
                "publish_product",
                key,
                epoch,
                {
                    "method": "POST",
                    "path": "/api/v1/products",
                    "body": data.model_dump(mode="json"),
                },
                effect,
            )

    def edit_with_barrier():
        with Session(community_db) as session, session.begin():
            require_account(session, who)
            if action == "deleting":
                begin_deleting(session, owner)
            else:
                row = session.get(ProductDraft, entity)
                row.revision += 1
                if action == "delete":
                    row.deleted_at = database_now(session)
                else:
                    row.payload = row.payload | {"name": "Edited later"}
            session.flush()
            if not publish_first:
                acquired.set()
                assert release.wait(timeout=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(publish_with_barrier if publish_first else edit_with_barrier)
        assert acquired.wait(timeout=10)
        second = pool.submit(edit_with_barrier if publish_first else publish_with_barrier)
        try:
            assert not second.done()
        finally:
            release.set()
        if publish_first:
            outcome = first.result(timeout=15)
            second.result(timeout=15)
            assert outcome.payload["decision"] == "new_product"
        else:
            first.result(timeout=15)
            if action == "deleting":
                with pytest.raises(DomainError) as failure:
                    second.result(timeout=15)
                assert failure.value.code == "account_deleting"
            else:
                outcome = second.result(timeout=15)
                assert outcome.error.code == (
                    "not_found" if action == "delete" else "draft_revision_conflict"
                )
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == int(
            publish_first
        )
        if publish_first:
            from calorie_app.modules.catalog.models import ProductVersion

            version = session.scalar(select(ProductVersion))
            assert version.name == "Rosół"


def test_multiple_full_high_matches_need_explicit_choice_and_no_silent_new(community_db):
    from calorie_app.modules.catalog.community.repository import create_version
    from calorie_app.modules.catalog.community.service import publication_metadata
    from calorie_app.modules.catalog.matching import build_matching_identity

    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    data = publication(entity)
    first = publish(community_db, who, epoch, data)
    # Synthetic deliberately duplicate seed models a moderator correction/release race.
    with Session(community_db) as session, session.begin():
        lock_catalog(session)
        private = session.get(ProductDraft, entity)
        identity = build_matching_identity(private.payload, data)
        snapshot, metadata = publication_metadata(private, data, identity)
        create_version(session, uuid4(), 1, uuid4(), None, snapshot, metadata)
        bump_catalog(session)
    newer, _ = draft(community_db, owner)
    request = publication(newer, confirm_new=True)
    ambiguous = publish(community_db, who, epoch, request)
    assert ambiguous.error.code == "ambiguous_product_match"
    selected = publication(newer, selected_product=first.payload["product"])
    accepted = publish(community_db, who, epoch, selected)
    assert accepted.payload == {
        "decision": "selected_existing",
        "product": first.payload["product"],
    }
    with Session(community_db) as session:
        assert session.scalar(select(func.count()).select_from(CommunityProduct)) == 2


def test_large_unicode_alias_hash_index_and_original_text_preserved(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    # UTF8 index key >8KiB; NFKC expands this single character into18 characters.
    alias = "\ufdfa" * 1800
    data = publication(entity, aliases=[alias])
    first = publish(community_db, who, epoch, data)
    assert first.error is None
    newer, _ = draft(community_db, owner, name="Other name")
    second = publish(community_db, who, epoch, publication(newer, aliases=[alias]))
    assert second.payload["decision"] == "existing_variant"
    with Session(community_db) as session, session.begin():
        product = read_community(session, who, UUID(first.payload["product"]["product_id"]))
    assert product["aliases"] == [alias]


def test_large_valid_composition_and_internal_normalization_budget(community_db):
    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    composition = ["marchew " + "ą" * 1990 for _ in range(100)]
    data = publication(
        entity,
        identity={
            "brand": {"state": "not_applicable", "value": None},
            "variant": {"state": "not_applicable", "value": None},
            "composition": {"state": "known", "value": composition},
        },
    )
    assert publish(community_db, who, epoch, data).error is None
    oversized = ["\ufdfa" * 2000 for _ in range(100)]
    newer, _ = draft(community_db, owner)
    data = publication(
        newer,
        identity={
            "brand": {"state": "not_applicable", "value": None},
            "variant": {"state": "not_applicable", "value": None},
            "composition": {"state": "known", "value": oversized},
        },
    )
    assert publish(community_db, who, epoch, data).error.code == "publication_metadata_too_large"


def test_exact_old_incomplete_version_survives_corrected_verified_current(community_db):
    from types import SimpleNamespace

    from calorie_app.modules.catalog.community.repository import create_version
    from calorie_app.modules.catalog.community.schemas import CommunityProductDTO
    from calorie_app.modules.catalog.community.service import publication_metadata
    from calorie_app.modules.catalog.matching import build_matching_identity

    who, owner, epoch = boot(community_db)
    entity, original = draft(community_db, owner, kcal=None)
    request = publication(entity, confirm_new=True)
    first = publish(community_db, who, epoch, request)
    product = UUID(first.payload["product"]["product_id"])
    complete = original | {
        "nutrition_per_100": original["nutrition_per_100"] | {"energy_kcal": "100"}
    }
    with Session(community_db) as session, session.begin():
        lock_catalog(session)
        identity = build_matching_identity(complete, request)
        snapshot, metadata = publication_metadata(
            SimpleNamespace(payload=complete), request, identity
        )
        create_version(session, product, 2, uuid4(), None, snapshot, metadata)
        state = session.get(CommunityProduct, product)
        state.current_revision = 2
        state.state_revision += 1
        state.verification = "verified"
        session.flush()
        bump_catalog(session)
    with Session(community_db) as session, session.begin():
        old = CommunityProductDTO.model_validate(read_community(session, who, product, 1))
        current = CommunityProductDTO.model_validate(read_community(session, who, product))
    assert old.nutrition_per_100.energy_kcal is None and old.complete is False
    assert old.verification == "unverified" and old.canonical_ref.revision == 2
    assert current.complete and current.verification == "verified"
    assert publish(community_db, who, epoch, request).payload == first.payload


def test_large_catalog_small_batch_keyset_byte_pages_no_scan_python(community_db, monkeypatch):
    from sqlalchemy import event

    from calorie_app.modules.catalog.community.repository import create_version
    from calorie_app.modules.catalog.community.service import publication_metadata
    from calorie_app.modules.catalog.matching import build_matching_identity
    from calorie_app.modules.catalog.validation import canonical_json

    who, owner, epoch = boot(community_db)
    entity, _ = draft(community_db, owner)
    request = publication(entity)
    with Session(community_db) as session, session.begin():
        lock_catalog(session)
        private = session.get(ProductDraft, entity)
        identity = build_matching_identity(private.payload, request)
        snapshot, metadata = publication_metadata(private, request, identity)
        for index in range(65):
            create_version(
                session, uuid4(), 1, uuid4(), None, snapshot | {"name": f"Seed {index}"}, metadata
            )
        bump_catalog(session)
    limits = []

    def bounded_select(connection, cursor, statement, parameters, context, executemany):
        if "community_versions" in statement and context.compiled is not None:
            limit = getattr(context.compiled.statement, "_limit_clause", None)
            if limit is not None:
                limits.append(limit.value)

    event.listen(community_db, "before_cursor_execute", bounded_select)
    monkeypatch.setattr("calorie_app.modules.catalog.community.service.PAGE_BYTES", 8000)
    products, token = [], None
    try:
        for _ in range(100):
            with Session(community_db) as session, session.begin():
                page = list_community(
                    session, who, CommunityQuery(limit=500, page_token=token), SECRET
                )
            assert len(canonical_json(page)) <= 8000
            products.extend(item["product_id"] for item in page["items"])
            token = page["next_page_token"]
            if token is None:
                break
        else:
            pytest.fail("keyset did not terminate")
    finally:
        event.remove(community_db, "before_cursor_execute", bounded_select)
    assert len(products) == len(set(products)) == 65 and products == sorted(products)
    assert limits and max(limits) <= 16


def test_chosen_hidden_stale_reference_refuses_new_binding(community_db):
    who, owner, epoch = boot(community_db)
    first_draft, _ = draft(community_db, owner)
    second_draft, _ = draft(community_db, owner)
    first = publish(community_db, who, epoch, publication(first_draft))
    product = UUID(first.payload["product"]["product_id"])
    wrong_ref = first.payload["product"] | {"revision": 2}
    assert (
        publish(
            community_db, who, epoch, publication(second_draft, selected_product=wrong_ref)
        ).error.code
        == "selected_product_changed"
    )
    with Session(community_db) as session, session.begin():
        lock_catalog(session)
        state = session.get(CommunityProduct, product)
        state.visibility = "hidden"
        state.state_revision += 1
        session.flush()
        bump_catalog(session)
    assert (
        publish(
            community_db,
            who,
            epoch,
            publication(second_draft, selected_product=first.payload["product"]),
        ).error.code
        == "not_found"
    )
    with Session(community_db) as session:
        assert session.get(PublicationBinding, (owner, second_draft, 1)) is None
