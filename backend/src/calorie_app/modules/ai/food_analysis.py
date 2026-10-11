"""Validated transient matching shares E6 identity and response semantics."""

import hashlib
from uuid import uuid4

from calorie_app.modules.ai import repository as repo
from calorie_app.modules.catalog.matching import (
    MatchingIdentity,
    high_match,
    match_reasons,
    matching_from_snapshot,
    matching_response,
    missing_identity_fields,
    normalize_text,
)
from calorie_app.modules.catalog.nutrition import calculate


def transient_matches(session, item):
    identity = MatchingIdentity(
        names=(normalize_text(item.name),),
        identity=item.identity.model_dump(mode="json"),
        basis_unit=item.basis_unit,
        energy_kcal=item.nutrition_per_100.energy_kcal,
    )
    rows = repo.call(
        session,
        "SELECT app.e7_match_candidates(:names,:hashes,:key,CAST(:identity AS jsonb),"
        ":basis,:energy,:density)",
        names=list(identity.names),
        hashes=[hashlib.sha256(name.encode()).hexdigest() for name in identity.names],
        key=identity.identity_key if not missing_identity_fields(identity) else None,
        identity=repo.encoded(identity.normalized_identity),
        basis=identity.basis_unit,
        energy=identity.energy_kcal,
        density=identity.density_g_per_ml,
    )
    candidates = {}
    high = []
    counts = {"community": 0, "official": 0}
    for row in rows:
        other = matching_from_snapshot(row, row["identity"])
        candidate = {
            "product": row["product"],
            "provenance": row["provenance"],
            "reasons": match_reasons(identity, other),
            "high_confidence": high_match(identity, other),
        }
        if row["high_selector"] and candidate["high_confidence"]:
            high.append(candidate)
        elif not row["high_selector"]:
            counts[row["provenance"]] += 1
            key = row["product"]["product_id"]
            if key not in candidates or row["provenance"] == "community":
                candidates[key] = candidate
    values = [candidates[key] for key in sorted(candidates)]
    return matching_response(identity, high, values, len(values) > 20 or max(counts.values()) > 20)


def proposal(session, result, model_version):
    items = []
    for item in result.items:
        items.append(
            {
                **item.model_dump(mode="json"),
                "component_id": str(uuid4()),
                "matches": transient_matches(session, item),
            }
        )
    totals = calculate(
        {
            **item.model_dump(mode="json"),
            "amount": item.quantity.model_dump(mode="json")["amount"],
            "unit": item.quantity.unit,
            "density_g_per_ml": None,
        }
        for item in result.items
    )
    value = {
        "items": items,
        "notes": result.notes,
        "totals": totals,
        "model_version": model_version,
        "formula_version": "nutrition_v1",
    }
    if len(repo.encoded(value).encode()) > 1024 * 1024:
        raise ValueError("provider_result_invalid")
    return value
