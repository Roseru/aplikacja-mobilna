"""Independent numerical and all-history witnesses for regularity_v1."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from calorie_app.modules.analytics.motivation.rules import (
    BADGE_CODES,
    BadgeDay,
    day_candidate_points,
    evaluate_day,
    rank_for_points,
    ration_meal_qualifies,
    reduce_badges,
)
from calorie_app.modules.catalog.nutrition import FIELDS


def meals(energy, *, amount="100", marker=None, ration=None):
    return [
        {
            "ration": ration,
            "items": [
                {
                    "quantity": {"amount": amount, "unit": "g"},
                    "basis_unit": "g",
                    "density_g_per_ml": None,
                    "nutrition_per_100": {
                        field: energy if field == "energy_kcal" else None for field in FIELDS
                    },
                    "ration_component_position": marker,
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    "energy,points,in_goal",
    [
        ("1799.999999", 1, False),
        ("1800", 2, True),
        ("2000", 2, True),
        ("2200", 2, True),
        ("2200.000001", 1, False),
        ("4000", 1, False),
        (None, 0, None),
        ("0", 0, None),
    ],
)
def test_exact_closed_band_and_missing_macro(energy, points, in_goal):
    result = evaluate_day(True, meals(energy), Decimal("2000"))
    assert result.candidate_points == points
    assert result.in_goal is in_goal
    assert result.effective_complete is (points > 0)


@pytest.mark.parametrize(
    "declared,entries,goal,points,complete",
    [
        (False, meals("2000"), "2000", 0, False),
        (True, [], "2000", 0, False),
        (True, [{"items": []}], "2000", 0, False),
        (True, meals("2000"), None, 1, True),
        (True, meals("2000"), "0", 1, True),
        (True, meals("2000") + meals(None), "2000", 0, False),
    ],
)
def test_declaration_energy_and_goal_are_independent(declared, entries, goal, points, complete):
    result = evaluate_day(declared, entries, goal)
    assert result.candidate_points == points
    assert result.effective_complete is complete
    assert result.in_goal is None


def test_exact_density_and_micro_energy_not_display_rounding():
    tiny = evaluate_day(True, meals("0.000001", amount="0.000001"), "0.00000000000001")
    assert tiny.candidate_points == 2
    density_meals = meals("200", amount="50")
    density_meals[0]["items"][0].update(
        quantity={"amount": "50", "unit": "ml"}, density_g_per_ml="1.2"
    )
    assert evaluate_day(True, density_meals, "120").candidate_points == 2


@pytest.mark.parametrize(
    "points,rank",
    [
        (0, "Rekrut"),
        (19, "Rekrut"),
        (20, "Szeregowy"),
        (59, "Szeregowy"),
        (60, "Kapral"),
        (119, "Kapral"),
        (120, "Sier\u017cant"),
        (1000000, "Sier\u017cant"),
    ],
)
def test_rank_boundaries(points, rank):
    assert rank_for_points(points) == rank


@pytest.mark.parametrize("points", [-1, True, 1.0, "20"])
def test_rank_rejects_non_authoritative_value(points):
    with pytest.raises(ValueError, match="invalid_points"):
        rank_for_points(points)


def test_points_always_bounded_and_badges_do_not_enter_score():
    assert [
        day_candidate_points(complete, goal)
        for complete in (False, True)
        for goal in (None, False, True)
    ] == [0, 0, 0, 1, 1, 2]
    assert evaluate_day(True, meals("1000") * 2, "2000").candidate_points == 2


def streak(count, *, start=date(2000, 1, 1), **qualifiers):
    return [BadgeDay(start + timedelta(days=i), **qualifiers) for i in range(count)]


@pytest.mark.parametrize("count,active,progress", [(9, False, 9), (10, True, 10), (11, True, 10)])
def test_streak_minimal_witness(count, active, progress):
    result = reduce_badges(streak(count, complete=True, in_goal=True))
    for code in ("complete_streak_10", "in_goal_streak_10"):
        assert result[code].active is active
        assert result[code].progress == progress
        assert len(result[code].witness) == (10 if active else 0)


def test_sparse_date_and_incomplete_break_streak():
    source = streak(10, complete=True, in_goal=True)
    assert not reduce_badges(source[:4] + source[5:])["complete_streak_10"].active
    source[4] = BadgeDay(source[4].local_date, complete=True)
    result = reduce_badges(source)
    assert result["complete_streak_10"].active
    assert not result["in_goal_streak_10"].active


def test_unclosed_day_only_progress_and_independent_mature_weight_ration():
    facts = streak(10, complete=True, in_goal=True, weight=True, ration=True)
    facts[-1] = BadgeDay(facts[-1].local_date, True, True, True, True, closed=False)
    result = reduce_badges(facts)
    assert result["complete_streak_10"].progress == 10
    assert not result["complete_streak_10"].active
    assert not result["in_goal_streak_10"].active
    assert result["weight_days_4_14"].active
    assert result["ration_days_5"].active


@pytest.mark.parametrize("last,active", [(13, True), (14, False)])
def test_four_distinct_weight_dates_inclusive_span(last, active):
    start = date(2026, 1, 1)
    result = reduce_badges(
        BadgeDay(start + timedelta(days=i), weight=True) for i in (0, 5, 10, last)
    )
    assert result["weight_days_4_14"].active is active


def test_weight_window_moves_to_alternative_witness():
    start = date(2026, 1, 1)
    facts = [BadgeDay(start + timedelta(days=i), weight=True) for i in (0, 15, 17, 20, 28)]
    witness = reduce_badges(facts)["weight_days_4_14"].witness
    assert witness == tuple(point.local_date for point in facts[1:])


def test_ration_five_distinct_nonconsecutive_dates_and_legacy_provenance():
    start = date(2000, 1, 1)
    source = [BadgeDay(start + timedelta(days=i), ration=True) for i in (0, 15, 200, 400, 1000)]
    assert reduce_badges(source)["ration_days_5"].active
    assert not reduce_badges(source[:4])["ration_days_5"].active
    assert not ration_meal_qualifies(meals("100", ration={"name": "saved"})[0])
    assert not ration_meal_qualifies(meals("100", marker=1)[0])
    assert ration_meal_qualifies(meals(None, marker=1, ration={"name": "saved"})[0])
    removed = meals("100", marker=1, ration={"name": "saved"})[0] | {"deleted_at": "now"}
    assert not ration_meal_qualifies(removed)
    zero = meals("100", amount="0", marker=1, ration={"name": "saved"})[0]
    assert not ration_meal_qualifies(zero)


def test_all_history_alternative_witness_revoke_and_reactivate():
    first = streak(10, complete=True)
    second = streak(10, start=date(2020, 1, 1), complete=True)
    full = reduce_badges(first + second)["complete_streak_10"]
    alternate = reduce_badges(first[:-1] + second)["complete_streak_10"]
    revoked = reduce_badges(first[:-1] + second[:-1])["complete_streak_10"]
    assert full.active and alternate.active and not revoked.active
    assert full.witness == tuple(point.local_date for point in first)
    assert alternate.witness == tuple(point.local_date for point in second)
    assert reduce_badges(first + second)["complete_streak_10"] == full


@pytest.mark.parametrize("offsets", [(0, 0), (1, 0)])
def test_duplicate_or_unordered_dates_rejected(offsets):
    with pytest.raises(ValueError, match="distinct_and_ordered"):
        reduce_badges(BadgeDay(date(2000, 1, 1) + timedelta(days=i), weight=True) for i in offsets)


def test_single_pass_large_history_is_not_window_truncated():
    def history():
        for i in range(100000):
            yield BadgeDay(date.fromordinal(730120 + i), complete=i < 10)

    result = reduce_badges(history())
    assert result["complete_streak_10"].active
    assert result["complete_streak_10"].witness[0] == date(2000, 1, 1)
    assert set(result) == set(BADGE_CODES)


def test_streaming_witness_memory_does_not_scale_with_history():
    import tracemalloc

    tracemalloc.start()
    try:
        result = reduce_badges(
            BadgeDay(
                date.fromordinal(730120 + i), complete=True, in_goal=True, weight=True, ration=True
            )
            for i in range(100000)
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert all(badge.active for badge in result.values())
    assert peak < 100000, peak
