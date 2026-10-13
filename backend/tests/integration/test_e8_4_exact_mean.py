"""Real HTTP sources near a HALF_UP tie; the oracle uses exact fractions."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from math import comb
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.support.e8_4_postgres import (
    activate,
    challenge,
    clock,
    complete_day,
    goal_payload,
    meal_payload,
    operation,
    push,
    runtime,
    statistics,
)
from tests.support.e8_4_postgres import e8_4_services as e8_4_services


def wire(value):
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


@pytest.mark.parametrize("order", [6, 8])
@pytest.mark.parametrize("sign", [1, -1])
def test_half_up_mean_near_exact_tie_matches_rational_oracle(order, sign):
    with runtime() as rt:
        activate(rt)
        metadata = challenge(rt, days=30, metrics=True)
        first = date.fromisoformat(metadata["start_date"])
        count = order + 2
        pairs = []
        for index in range(order + 1):
            maintenance = Decimal("2700") + Decimal(index) * Decimal("0.000015")
            intake = maintenance + Decimal(sign * (-1) ** index * comb(order, index)) / 100
            pairs.append((intake, maintenance))
        # The aggregate is strictly inside the half-way interval. HTTP inputs
        # use at most six decimal places; the final day's computed intake has
        # twelve places because it sums two exact nutrition*quantity products.
        pairs.append(
            (
                Decimal("2700")
                - sign * Decimal("2700") * Decimal(count) * Decimal("0.000000000000005"),
                Decimal("2700"),
            )
        )
        for index, (intake, maintenance) in enumerate(pairs):
            day = first + timedelta(days=index)
            outcome = push(
                rt,
                "a",
                operation(
                    rt,
                    "goal",
                    payload=goal_payload(
                        day, "9999", maintenance=wire(maintenance), timeline_revision=index
                    ),
                ),
            )
            assert outcome["status"] == "accepted", outcome
            if index < count - 1:
                complete_day(rt, "a", day, wire(intake))
            else:
                a, b = Decimal("0.000009"), Decimal(count) * Decimal("0.0000015")
                base = Decimal("2699") - (b - sign * a)
                payload = meal_payload(day, wire(base))
                extra = deepcopy(payload["items"][0])
                extra["item_id"] = str(uuid4())
                extra["quantity"]["amount"] = wire(1 - sign * a)
                extra["nutrition_per_100"]["energy_kcal"] = wire(100 * (1 + b))
                payload["items"].append(extra)
                assert base + (1 - sign * a) * (1 + b) == intake
                assert push(rt, "a", operation(rt, "meal", payload=payload))["status"] == "accepted"
                with rt["admin"].connect() as c:
                    row = c.execute(
                        text(
                            "SELECT id,revision FROM app.diary_days "
                            "WHERE owner_id=:owner AND local_date=:day"
                        ),
                        {"owner": rt["actors"]["a"]["owner"], "day": day},
                    ).one()
                assert (
                    push(
                        rt,
                        "a",
                        operation(
                            rt,
                            "diary_day",
                            entity=row.id,
                            base=row.revision,
                            payload={
                                "local_date": day.isoformat(),
                                "time_zone": "UTC",
                                "declared_complete": True,
                            },
                        ),
                    )["status"]
                    == "accepted"
                )
        exact_fraction = (
            sum(
                (
                    100 * (Fraction(maintenance) - Fraction(intake)) / Fraction(maintenance)
                    for intake, maintenance in pairs
                ),
                Fraction(0),
            )
            / count
        )
        assert 0 < sign * exact_fraction < Fraction(1, 2000000000000)
        clock(rt, datetime.combine(first + timedelta(days=count), datetime.min.time(), UTC))
        response = statistics(rt, metadata["id"])
        assert response.status_code == 200, response.text
        assert response.json()["self"]["mean_deficit"] == {
            "state": "available",
            "value": "0",
            "eligible_days": count,
        }
