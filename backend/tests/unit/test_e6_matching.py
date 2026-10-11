"""KO-09 vectors and an independent Fraction oracle for energy equivalence."""

import json
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from pathlib import Path

import pytest

from calorie_app.modules.catalog.community.schemas import MatchProductRequest
from calorie_app.modules.catalog.matching import (
    MatchingIdentity,
    build_matching_identity,
    energy_matches,
    high_match,
    identity_conflicts,
    match_reasons,
    matching_from_snapshot,
    missing_identity_fields,
    normalize_text,
)

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "contracts/test-vectors/e6_matching.json").read_text("utf-8"))[
    "vectors"
]
IDENTITY = {
    "brand": {"state": "not_applicable", "value": None},
    "variant": {"state": "not_applicable", "value": None},
    "composition": {"state": "known", "value": ["water", "chicken", "carrot"]},
}


def broth(**kwargs):
    return MatchingIdentity(("rosół",), IDENTITY, "g", Decimal("200"), **kwargs)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_shared_energy_vectors(vector):
    rho = Decimal(vector["rho"]) if vector["rho"] is not None else None
    assert (
        energy_matches(
            Decimal(vector["left"]),
            Decimal(vector["right"]),
            vector["left_unit"],
            vector["right_unit"],
            rho,
        )
        is vector["matches"]
    )


def oracle(a, b, unit_a, unit_b, density_a, density_b):
    # This oracle uses exact rational division and relative distance, whereas
    # runtime compares integer cross-products and never divides energy.
    if density_a is not None and density_b is not None and density_a != density_b:
        return False
    left, right = Fraction(a), Fraction(b)
    if unit_a != unit_b:
        rho = density_a if density_a is not None else density_b
        if rho is None:
            return False
        if unit_a == "ml":
            left /= Fraction(rho)
        else:
            right /= Fraction(rho)
    if left == right == 0:
        return True
    return abs(left - right) / max(left, right) <= Fraction(1, 10)


def test_independent_fraction_oracle_across_boundaries_units_and_contexts():
    energies = [Decimal(v) for v in ("0", "0.000001", "179", "180", "200", "240", "999999.999999")]
    densities = [None, Decimal("0.3"), Decimal("1.2"), Decimal("999999.999999")]
    for a, b, ua, ub, da, db in product(
        energies, energies, ("g", "ml"), ("g", "ml"), densities, densities
    ):
        expected = oracle(a, b, ua, ub, da, db)
        with localcontext() as context:
            context.prec = 2
            assert energy_matches(a, b, ua, ub, da, db) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  RＯSÓŁ\t domowy\u00a0", "rosół domowy"),
        ("Straße", "strasse"),
        ("Kelvin", "kelvin"),
        ("Cafe\u0301\n soup", "café soup"),
    ],
)
def test_unicode_normalization(raw, expected):
    assert normalize_text(raw) == expected


def test_small_large_portion_is_not_identity_and_alias_can_match():
    left = broth()
    right = replace(left, names=("zupa", "rosół"), energy_kcal=Decimal("180"))
    assert high_match(left, right)
    assert match_reasons(left, right) == [
        "shared_name",
        "identity_equal",
        "energy_within_10_percent",
    ]


@pytest.mark.parametrize("field", ["brand", "variant", "composition"])
def test_unknown_does_not_act_as_wildcard(field):
    identity = {**IDENTITY, field: {"state": "unknown", "value": None}}
    candidate = replace(broth(), identity=identity)
    assert not high_match(broth(), candidate)
    assert not high_match(candidate, candidate)
    assert missing_identity_fields(candidate) == [field]


def test_missing_energy_is_manual_even_identical_macros_identity():
    item = replace(broth(), energy_kcal=None)
    assert not high_match(item, item)
    assert missing_identity_fields(item) == ["energy_kcal"]


@pytest.mark.parametrize("field", ["brand", "variant", "composition"])
def test_distinct_known_identity_cannot_be_merged_by_similar_energy(field):
    identity = {**IDENTITY, field: {"state": "known", "value": "different"}}
    right = replace(broth(), identity=identity)
    assert not high_match(broth(), right)
    assert field in identity_conflicts(broth(), right)


def test_recipe_and_ordered_ingredient_list_are_distinct():
    recipe = {**IDENTITY, "composition": {"state": "known", "value": "water chicken carrot"}}
    assert not high_match(broth(), replace(broth(), identity=recipe))
    reordered = {
        **IDENTITY,
        "composition": {"state": "known", "value": ["carrot", "chicken", "water"]},
    }
    assert not high_match(broth(), replace(broth(), identity=reordered))


def test_density_conflict_for_same_and_different_basis_is_manual():
    a = broth(density_g_per_ml=Decimal("1.2"))
    b = broth(density_g_per_ml=Decimal("1.3"))
    assert not high_match(a, b)
    assert "density_g_per_ml" in identity_conflicts(a, b)
    assert not high_match(a, replace(b, basis_unit="ml"))


def test_identity_key_is_bounded_and_exact_normalized_identity_preserved():
    recipe = {**IDENTITY, "composition": {"state": "known", "value": "x" * 4000}}
    item = replace(broth(), identity=recipe)
    assert len(item.identity_key) == 64
    assert item.normalized_identity["composition"]["value"] == "recipe:" + "x" * 4000


def request(**updates):
    return MatchProductRequest.model_validate(
        {
            "draft_id": "936c8146-aabb-4f83-9616-a764924d56fb",
            "draft_revision": 1,
            "source_kind": "recipe",
            "source_description": "Synthetic recipe",
            "identity": IDENTITY,
            **updates,
        }
    )


def draft(**updates):
    return {
        "name": "ROSÓŁ",
        "brand": None,
        "variant": None,
        "basis_unit": "ml",
        "nutrition_per_100": {
            "energy_kcal": "200",
            "protein_g": None,
            "fat_g": None,
            "carbs_g": None,
        },
        "package_quantity": {"amount": "250", "unit": "ml"},
        "density_g_per_ml": None,
        "density_source": None,
        "source_description": "draft",
        **updates,
    }


def test_metadata_derives_only_authorized_fields_and_requires_portion():
    assert build_matching_identity(draft(), request()).names == ("rosół",)
    with pytest.raises(ValueError, match="portion_required"):
        build_matching_identity(draft(package_quantity=None), request())
    assert build_matching_identity(
        draft(package_quantity=None), request(portion={"amount": "100", "unit": "ml"})
    )


def test_known_draft_identity_and_density_cannot_be_overridden():
    with pytest.raises(ValueError, match="draft_identity_conflict"):
        build_matching_identity(draft(brand="Known brand"), request())
    with pytest.raises(ValueError, match="draft_density_conflict"):
        build_matching_identity(
            draft(density_g_per_ml="1.2", density_source="label"),
            request(density={"amount": "1.3", "source_description": "other label"}),
        )
    with pytest.raises(ValueError, match="density_required"):
        build_matching_identity(
            draft(package_quantity=None), request(portion={"amount": "250", "unit": "g"})
        )


def test_known_portion_is_preserved_and_empty_draft_name_rejected():
    with pytest.raises(ValueError, match="draft_portion_conflict"):
        build_matching_identity(draft(), request(portion={"amount": "500", "unit": "ml"}))
    with pytest.raises(ValueError, match="product_name_required"):
        build_matching_identity(draft(name=" \t"), request())


def test_official_without_explicit_composition_is_conservative_manual():
    snapshot = {**draft(), "aliases": []}
    assert matching_from_snapshot(snapshot).identity["composition"]["state"] == "unknown"
    assert not high_match(matching_from_snapshot(snapshot), matching_from_snapshot(snapshot))


def test_legacy_blank_brand_or_variant_remains_readable_as_unknown_identity():
    snapshot = {**draft(brand=" ", variant="\t"), "aliases": [" "]}
    item = matching_from_snapshot(snapshot)
    assert item.names == ("rosół",)
    assert item.identity["brand"] == {"state": "unknown", "value": None}
    assert item.identity["variant"] == {"state": "unknown", "value": None}
