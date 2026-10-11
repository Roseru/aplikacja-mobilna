"""Real PostgreSQL matching agrees with exact rational oracle, beyond preview limits."""

import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from calorie_app.modules.catalog.community.repository import create_version, lock_catalog
from calorie_app.modules.catalog.community.service import high_candidates, manual_candidates
from calorie_app.modules.catalog.matching import MatchingIdentity

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "contracts/test-vectors/e6_matching.json").read_text("utf-8"))[
    "vectors"
]
IDENTITY = {
    "brand": {"state": "not_applicable", "value": None},
    "variant": {"state": "not_applicable", "value": None},
    "composition": {"state": "known", "value": ["water", "carrot"]},
}


def seed(session, energy, unit, density=None, *, product_id=None, identity=IDENTITY):
    item = MatchingIdentity(("rosół",), identity, unit, Decimal(energy), density)
    snapshot = {
        "name": "Rosół",
        "aliases": [],
        "brand": None,
        "variant": None,
        "basis_unit": unit,
        "energy_kcal": energy,
        "protein_g": None,
        "fat_g": None,
        "carbs_g": None,
        "package_amount": "250",
        "package_unit": unit,
        "density_amount": str(density) if density is not None else None,
        "density_source_description": "synthetic same-variant density"
        if density is not None
        else None,
        "source_locator": "synthetic recipe",
        "preparation": None,
    }
    metadata = {
        "source_kind": "recipe",
        "source_description": "synthetic recipe",
        "identity": identity,
        "normalized_names": list(item.names),
        "normalized_identity": item.normalized_identity,
        "identity_key": item.identity_key,
        "search_text": "rosół",
        "ingredients": identity["composition"]["value"],
        "recipe": None,
    }
    create_version(
        session,
        product_id or uuid4(),
        1,
        uuid4(),
        uuid4() if density is not None else None,
        snapshot,
        metadata,
    )


@pytest.mark.integration
@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: v["id"])
def test_sql_energy_matches_independent_fraction_distance(database, vector):
    engine = database[0]
    rho = Decimal(vector["rho"]) if vector["rho"] is not None else None
    left, right = Fraction(vector["left"]), Fraction(vector["right"])
    if vector["left_unit"] != vector["right_unit"] and rho is not None:
        if vector["left_unit"] == "ml":
            left /= Fraction(rho)
        else:
            right /= Fraction(rho)
    known_units = vector["left_unit"] == vector["right_unit"] or rho is not None
    distance = Fraction(0) if left == right == 0 else abs(left - right) / max(left, right)
    expected = known_units and distance <= Fraction(1, 10)
    assert expected is vector["matches"]
    with Session(engine) as session:
        lock_catalog(session)
        seed(session, vector["right"], vector["right_unit"])
        query = MatchingIdentity(
            ("rosół",), IDENTITY, vector["left_unit"], Decimal(vector["left"]), rho
        )
        assert bool(high_candidates(session, query)) is expected
        session.rollback()


@pytest.mark.integration
def test_full_sql_high_predicate_finds_matches_after_twenty_false_preview_candidates(database):
    with Session(database[0]) as session:
        lock_catalog(session)
        different = {**IDENTITY, "composition": {"state": "known", "value": ["different recipe"]}}
        for index in range(1, 26):
            seed(session, "200", "g", product_id=UUID(int=index), identity=different)
        for index in (1000, 1001):
            seed(session, "180", "g", product_id=UUID(int=index))
        query = MatchingIdentity(("rosół",), IDENTITY, "g", Decimal("200"))
        preview, truncated = manual_candidates(session, query)
        assert len(preview) == 20 and truncated
        assert all(not item["high_confidence"] for item in preview)
        matches = high_candidates(session, query)
        assert len(matches) == 2
        assert {row[0].product_id for row in matches} == {UUID(int=1000), UUID(int=1001)}
        session.rollback()


@pytest.mark.integration
def test_sql_density_conflict_is_manual_even_with_same_basis(database):
    with Session(database[0]) as session:
        lock_catalog(session)
        seed(session, "200", "g", Decimal("1.3"))
        query = MatchingIdentity(("rosół",), IDENTITY, "g", Decimal("200"), Decimal("1.2"))
        assert high_candidates(session, query) == []
        candidates, _ = manual_candidates(session, query)
        assert len(candidates) == 1 and candidates[0]["high_confidence"] is False
        session.rollback()
