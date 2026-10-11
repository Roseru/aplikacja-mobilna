"""Explicit correction creates only a binding/template, never diary/domain rows."""

import hashlib
from uuid import UUID

from sqlalchemy import select

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai import repository as repo
from calorie_app.modules.ai.idempotency import execute_mutation, semantic_hash
from calorie_app.modules.ai.service import public_profile, rejection
from calorie_app.modules.catalog.community.repository import require_public_product
from calorie_app.modules.catalog.nutrition import FIELDS
from calorie_app.modules.catalog.validation import canonical, canonical_json
from calorie_app.modules.profiles.models import GoalVersion


def validate_choices(session, owner, request):
    meal = request.meal.payload
    if (
        meal["goal_id"] is not None
        and session.scalar(
            select(GoalVersion.id).where(
                GoalVersion.id == UUID(meal["goal_id"]), GoalVersion.owner_id == owner
            )
        )
        is None
    ):
        raise DomainError(404, "not_found")
    for item in meal["items"]:
        if item["nutrition_origin"] not in {"ai_estimate", "catalog_snapshot"}:
            raise DomainError(422, "photo_nutrition_origin_required")
        ref = item["product"]
        if ref is None:
            if item["nutrition_origin"] == "catalog_snapshot":
                raise DomainError(422, "catalog_snapshot_requires_reference")
            continue
        try:
            public = require_public_product(
                session, UUID(ref["product_id"]), ref["revision"], mutation=True
            )
            current = require_public_product(session, UUID(ref["product_id"]), mutation=True)
        except DomainError as error:
            raise DomainError(409, "photo_catalog_choice_changed", error.details) from None
        if current.version.revision != ref["revision"]:
            raise DomainError(409, "photo_catalog_choice_changed")
        if item["nutrition_origin"] == "catalog_snapshot":
            nutrition = {
                name: canonical(getattr(public.version, name))
                if getattr(public.version, name) is not None
                else None
                for name in FIELDS
            }
            if (
                item["nutrition_per_100"] != nutrition
                or item["basis_unit"] != public.version.basis_unit
            ):
                raise DomainError(422, "catalog_snapshot_mismatch")
    for draft in request.drafts:
        if not any(
            all(
                draft.payload[key] == item[key]
                for key in (
                    "name",
                    "basis_unit",
                    "nutrition_per_100",
                    "density_g_per_ml",
                    "density_source",
                )
            )
            for item in meal["items"]
        ):
            raise DomainError(422, "draft_not_in_confirmed_meal")


def confirm(factory, principal, epoch, key, analysis_id, request):
    semantic = request.model_dump(mode="json")
    request_hash = semantic_hash(
        "POST", f"/api/v1/ai/food-analyses/{analysis_id}/confirm", semantic
    )
    decision_hash = hashlib.sha256(
        canonical_json({k: v for k, v in semantic.items() if k != "expected_revision"})
    ).hexdigest()
    with factory() as session:

        def action(account):
            value = repo.analysis(session, account.id, analysis_id)
            existing = repo.row(
                session,
                "SELECT * FROM app.ai_decisions WHERE owner_id=:owner AND analysis_id=:id",
                owner=account.id,
                id=analysis_id,
            )
            # The identical immutable decision remains stable under a new key,
            # including after a later catalog change.
            if existing is not None:
                if value["sync_epoch"] != epoch or value["generation"] != account.generation:
                    raise DomainError(409, "analysis_context_changed")
                if existing["decision_hash"] != decision_hash:
                    raise DomainError(409, "analysis_already_confirmed")
                return 200, existing["response"]
            validate_choices(session, account.id, request)
            provenance = {
                "analysis_id": str(analysis_id),
                **public_profile(value["profile"]),
                "model_version": value["proposal"].get("model_version")
                if value["proposal"]
                else None,
                "uncertainty": [
                    {"component_id": item["component_id"], "uncertainty": item["uncertainty"]}
                    for item in (value["proposal"] or {}).get("items", [])
                ],
            }
            result = {
                "analysis_id": str(analysis_id),
                "meal": request.meal.model_dump(mode="json"),
                "drafts": [draft.model_dump(mode="json") for draft in request.drafts],
                "provenance": provenance,
            }
            result = repo.call(
                session,
                "SELECT app.e7_confirm(:owner,:generation,:epoch,:id,:revision,:hash,:meal,"
                "CAST(:response AS jsonb))",
                owner=account.id,
                generation=account.generation,
                epoch=epoch,
                id=analysis_id,
                revision=request.expected_revision,
                hash=decision_hash,
                meal=request.meal.meal_id,
                response=repo.encoded(result),
            )
            return 200, rejection(result)

        outcome = execute_mutation(session, principal, key, epoch, "confirm", request_hash, action)
        session.commit()
        return outcome


def cancel(factory, principal, epoch, key, analysis_id, request):
    digest = semantic_hash(
        "POST", f"/api/v1/ai/food-analyses/{analysis_id}/cancel", request.model_dump(mode="json")
    )
    with factory() as session:

        def action(account):
            result = repo.call(
                session,
                "SELECT app.e7_cancel(:owner,:generation,:epoch,:id,:revision)",
                owner=account.id,
                generation=account.generation,
                epoch=epoch,
                id=analysis_id,
                revision=request.expected_revision,
            )
            return 200, rejection(result)

        outcome = execute_mutation(session, principal, key, epoch, "cancel", digest, action)
        session.commit()
        return outcome
