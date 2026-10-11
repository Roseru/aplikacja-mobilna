"""Strict community contracts preserve unknown values and private sync DTOs."""

import json
from copy import deepcopy
from itertools import product
from pathlib import Path

import pytest
from pydantic import ValidationError

from calorie_app.modules.catalog.community.schemas import (
    CommunityProductDTO,
    CompositionDTO,
    FeedbackDTO,
    IdentityFieldDTO,
    MatchProductRequest,
    MatchProductResponse,
    PublishProductRequest,
    ReportRequest,
    VoteRequest,
)
from calorie_app.modules.catalog.moderation.schemas import (
    MergeProductRequest,
    ModerateProductRequest,
    ProductCorrectionDTO,
    ReportResolutionRequest,
)

ROOT = Path(__file__).resolve().parents[3]
REF = {"product_id": "906c8146-aabb-4f83-9616-a764924d56fb", "revision": 1}
IDENTITY = {
    "brand": {"state": "not_applicable", "value": None},
    "variant": {"state": "not_applicable", "value": None},
    "composition": {"state": "known", "value": ["water", "carrot"]},
}


def publish(**updates):
    return {
        "draft_id": "936c8146-aabb-4f83-9616-a764924d56fb",
        "draft_revision": 1,
        "source_kind": "recipe",
        "source_description": "synthetic recipe",
        "identity": IDENTITY,
        **updates,
    }


def correction(**updates):
    return {
        "name": "Rosół",
        "aliases": [],
        "identity": IDENTITY,
        "basis_unit": "ml",
        "nutrition_per_100": {
            "energy_kcal": "20",
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        },
        "portion": {"amount": "250", "unit": "ml"},
        "density": None,
        "source_kind": "recipe",
        "source_description": "synthetic recipe",
        **updates,
    }


def community(**updates):
    return {
        **correction(),
        **REF,
        "canonical_ref": REF,
        "state_revision": 1,
        "brand": None,
        "variant": None,
        "source_id": "b16c8146-aabb-4f83-9616-a764924d56fb",
        "provenance": "community",
        "verification": "unverified",
        "visibility": "visible",
        "complete": False,
        "missing_nutrition_fields": ["protein_g", "fat_g", "carbs_g"],
        "missing_identity_fields": [],
        "positive_votes": 3,
        "negative_votes": 2,
        "voters": 5,
        "is_mine": False,
        **updates,
    }


@pytest.mark.parametrize("state", ["known", "unknown", "not_applicable"])
def test_identity_field_requires_explicit_three_states(state):
    value = "Acme" if state == "known" else None
    dto = IdentityFieldDTO(state=state, value=value)
    assert dto.value == value
    with pytest.raises(ValidationError):
        IdentityFieldDTO(state=state, value=None if state == "known" else "Acme")


@pytest.mark.parametrize("value", [None, " ", [], [" "], ["x"] * 101, "x" * 4001])
def test_invalid_known_composition(value):
    with pytest.raises(ValidationError):
        CompositionDTO(state="known", value=value)


def test_composition_not_applicable_is_forbidden():
    with pytest.raises(ValidationError):
        CompositionDTO(state="not_applicable", value=None)
    assert CompositionDTO(state="unknown", value=None)


@pytest.mark.parametrize("kind", ["label", "recipe", "estimate", "ai"])
def test_source_classes_and_unknown_nutrition_do_not_grant_verification(kind):
    assert PublishProductRequest.model_validate(publish(source_kind=kind)).source_kind == kind
    item = CommunityProductDTO.model_validate(community(source_kind=kind))
    assert item.complete is False and item.nutrition_per_100.protein_g is None
    assert item.missing_identity_fields == []


@pytest.mark.parametrize(
    "field", ["owner_id", "role", "verified", "official", "status", "account_id"]
)
def test_client_cannot_set_privilege_or_ownership(field):
    with pytest.raises(ValidationError):
        PublishProductRequest.model_validate(publish(**{field: "spoof"}))


@pytest.mark.parametrize(
    "value", [True, 1, 1.2, "NaN", "Infinity", "-1", "1000000", "1e2", "0.1234567"]
)
def test_exact_bounded_decimal_contract_rejects_invalid_portions(value):
    with pytest.raises(ValidationError):
        PublishProductRequest.model_validate(publish(portion={"amount": value, "unit": "g"}))


def test_portion_positive_and_ml_does_not_require_density():
    with pytest.raises(ValidationError):
        PublishProductRequest.model_validate(publish(portion={"amount": "0", "unit": "ml"}))
    assert ProductCorrectionDTO.model_validate(correction()).density is None
    with pytest.raises(ValidationError):
        ProductCorrectionDTO.model_validate(correction(portion={"amount": "250", "unit": "g"}))
    assert ProductCorrectionDTO.model_validate(
        correction(
            portion={"amount": "250", "unit": "g"},
            density={"amount": "1.2", "source_description": "same variant label"},
        )
    )


def test_alias_and_text_bounds_and_strict_revision():
    for changes in (
        {"aliases": ["x"] * 51},
        {"source_description": "x" * 2001},
        {"draft_revision": True},
    ):
        with pytest.raises(ValidationError):
            PublishProductRequest.model_validate(publish(**changes))
    assert PublishProductRequest.model_validate(publish(aliases=["x"] * 50))


@pytest.mark.parametrize("changes", [{"source_description": " \t"}, {"aliases": [" \n"]}])
def test_public_text_requires_more_than_whitespace(changes):
    with pytest.raises(ValidationError):
        PublishProductRequest.model_validate(publish(**changes))


def test_community_completeness_and_vote_count_invariants():
    for changes in (
        {"complete": True},
        {"missing_nutrition_fields": []},
        {"verification": "verified"},
        {"voters": 6},
        {"brand": "spoof"},
        {"missing_identity_fields": ["composition"]},
    ):
        with pytest.raises(ValidationError):
            CommunityProductDTO.model_validate(community(**changes))
    identity = deepcopy(IDENTITY)
    identity["composition"] = {"state": "unknown", "value": None}
    nutrition = {"energy_kcal": "0", "protein_g": "0", "fat_g": "0", "carbs_g": "0"}
    dto = CommunityProductDTO.model_validate(
        community(
            identity=identity,
            nutrition_per_100=nutrition,
            complete=True,
            missing_nutrition_fields=[],
            missing_identity_fields=["composition"],
        )
    )
    assert dto.complete and dto.missing_identity_fields == ["composition"]


def test_publish_selection_excludes_new_confirmation_and_matches_excludes_selection():
    with pytest.raises(ValidationError):
        PublishProductRequest.model_validate(publish(selected_product=REF, confirm_new=True))
    with pytest.raises(ValidationError):
        MatchProductRequest.model_validate(publish(selected_product=REF))


@pytest.mark.parametrize("value", [0, True, "1", 2, -2, 1.0])
def test_votes_are_strict_plus_or_minus_one(value):
    with pytest.raises(ValidationError):
        VoteRequest(value=value)


def test_feedback_initial_revision_is_distinct_from_product_revision():
    dto = FeedbackDTO(
        product=REF,
        positive_votes=0,
        negative_votes=0,
        voters=0,
        my_value=None,
        my_revision=0,
        is_mine=False,
    )
    assert dto.my_revision == 0
    assert VoteRequest(value=1) and VoteRequest(value=-1)
    assert ReportRequest(product=REF, reason="wrong energy", description="synthetic report")


def test_moderation_demands_explicit_change_and_source_confirmation():
    for value in (
        {"expected_state_revision": 1, "reason": "empty"},
        {"expected_state_revision": 1, "reason": "verify", "verification": "verified"},
    ):
        with pytest.raises(ValidationError):
            ModerateProductRequest.model_validate(value)
    assert ModerateProductRequest(
        expected_state_revision=1,
        reason="check label",
        verification="verified",
        source_confirmed=True,
    )
    assert ModerateProductRequest(expected_state_revision=1, reason="hide", visibility="hidden")
    with pytest.raises(ValidationError):
        MergeProductRequest(
            target=REF,
            expected_source_state_revision=1,
            expected_target_state_revision=1,
            identity_confirmed=False,
            reason="merge",
        )


@pytest.mark.parametrize("status", ["resolved", "dismissed", "referred_to_admin"])
def test_report_resolution_states(status):
    assert ReportResolutionRequest(expected_revision=1, status=status, reason="decision")
    with pytest.raises(ValidationError):
        ReportResolutionRequest(expected_revision=1, status="open", reason="decision")


def test_shared_publish_example_matches_runtime():
    example = json.loads((ROOT / "contracts/examples/e6-publish.json").read_text("utf-8"))
    assert PublishProductRequest.model_validate(example).model_dump(mode="json") == example


@pytest.mark.parametrize("known", list(product((False, True), repeat=4)))
def test_every_nullable_nutrition_combination_keeps_exact_missing_fields(known):
    names = ("energy_kcal", "protein_g", "fat_g", "carbs_g")
    nutrition = {key: "0" if present else None for key, present in zip(names, known, strict=True)}
    missing = [key for key in names if nutrition[key] is None]
    item = CommunityProductDTO.model_validate(
        community(
            nutrition_per_100=nutrition,
            complete=not missing,
            missing_nutrition_fields=missing,
            missing_identity_fields=[] if known[0] else ["energy_kcal"],
        )
    )
    assert item.missing_nutrition_fields == missing
    assert item.complete is all(known)


@pytest.mark.parametrize("decision", ["existing_variant", "manual_candidates", "new_product"])
def test_match_decision_references_are_explicit(decision):
    values = {
        "decision": decision,
        "existing_product": REF if decision == "existing_variant" else None,
        "candidates": [],
        "missing_identity_fields": [],
        "truncated": False,
    }
    assert MatchProductResponse.model_validate(values)
    values["existing_product"] = None if decision == "existing_variant" else REF
    with pytest.raises(ValidationError):
        MatchProductResponse.model_validate(values)


def test_empty_manual_candidates_preserve_identity_uncertainty():
    values = {
        "decision": "manual_candidates",
        "existing_product": None,
        "candidates": [],
        "missing_identity_fields": ["composition", "energy_kcal"],
        "truncated": False,
    }
    assert MatchProductResponse.model_validate(values).missing_identity_fields
    for decision in ("existing_variant", "new_product"):
        with pytest.raises(ValidationError):
            MatchProductResponse.model_validate({**values, "decision": decision})
