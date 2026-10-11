"""Conservative identity matching and exact rational energy comparisons."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from calorie_app.modules.catalog.community.schemas import IdentityDTO, MatchProductRequest
from calorie_app.modules.catalog.schemas import NutritionDTO, QuantityDTO


def normalize_text(value: str) -> str:
    """NFKC, Unicode casefold and collapse all Unicode whitespace, retaining originals."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def normalize_composition(value: str | list[str] | None) -> str | None:
    """Preserve recipe versus ordered ingredient-list semantics without guessing."""
    if value is None:
        return None
    if isinstance(value, str):
        return "recipe:" + normalize_text(value)
    return "ingredients:" + json.dumps(
        [normalize_text(item) for item in value], ensure_ascii=False, separators=(",", ":")
    )


def normalized_identity(identity: IdentityDTO | dict) -> dict:
    identity = IdentityDTO.model_validate(identity)
    result = {}
    for key in ("brand", "variant", "composition"):
        part = getattr(identity, key)
        value = (
            normalize_composition(part.value)
            if key == "composition"
            else normalize_text(part.value)
            if part.value is not None
            else None
        )
        result[key] = {"state": part.state, "value": value}
    return result


@dataclass(frozen=True)
class MatchingIdentity:
    names: tuple[str, ...]
    identity: dict
    basis_unit: str
    energy_kcal: Decimal | None
    density_g_per_ml: Decimal | None = None

    @property
    def normalized_identity(self) -> dict:
        return normalized_identity(self.identity)

    @property
    def identity_key(self) -> str:
        encoded = json.dumps(
            self.normalized_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def missing_identity_fields(value: MatchingIdentity) -> list[str]:
    result = [
        key
        for key in ("brand", "variant", "composition")
        if value.identity[key]["state"] == "unknown"
    ]
    if value.energy_kcal is None:
        result.append("energy_kcal")
    return result


def matching_response(identity, high, candidates, truncated):
    """One response rule for private drafts and validated transient photo items."""
    candidates = list(candidates)
    for item in reversed(high):
        if not any(candidate["product"] == item["product"] for candidate in candidates):
            candidates.insert(0, item)
    truncated = truncated or len(candidates) > 20
    missing = missing_identity_fields(identity)
    decision = (
        "existing_variant"
        if len(high) == 1
        else "manual_candidates"
        if missing or candidates or len(high) > 1
        else "new_product"
    )
    return {
        "decision": decision,
        "existing_product": high[0]["product"] if len(high) == 1 else None,
        "candidates": candidates[:20],
        "missing_identity_fields": missing,
        "truncated": truncated,
    }


def energy_matches(
    left: Decimal,
    right: Decimal,
    left_unit: str = "g",
    right_unit: str = "g",
    left_density: Decimal | None = None,
    right_density: Decimal | None = None,
) -> bool:
    """Compare by integer cross-products; Decimal context cannot round the threshold."""
    if left_unit not in ("g", "ml") or right_unit not in ("g", "ml"):
        return False
    if not left.is_finite() or not right.is_finite() or min(left, right) < 0:
        return False
    for density in (left_density, right_density):
        if density is not None and (not density.is_finite() or density <= 0):
            return False
    if left_density is not None and right_density is not None and left_density != right_density:
        return False
    a_num, a_den = left.as_integer_ratio()
    b_num, b_den = right.as_integer_ratio()
    if left_unit != right_unit:
        density = left_density if left_density is not None else right_density
        if density is None:
            return False
        rho_num, rho_den = density.as_integer_ratio()
        # Convert the ml side to g by dividing by rho, without Decimal division.
        if left_unit == "ml":
            a_num *= rho_den
            a_den *= rho_num
        else:
            b_num *= rho_den
            b_den *= rho_num
    a = a_num * b_den
    b = b_num * a_den
    return abs(a - b) * 10 <= max(a, b)


def high_match(left: MatchingIdentity, right: MatchingIdentity) -> bool:
    if missing_identity_fields(left) or missing_identity_fields(right):
        return False
    return (
        bool(set(left.names) & set(right.names))
        and left.normalized_identity == right.normalized_identity
        and energy_matches(
            left.energy_kcal,
            right.energy_kcal,
            left.basis_unit,
            right.basis_unit,
            left.density_g_per_ml,
            right.density_g_per_ml,
        )
    )


def identity_conflicts(left: MatchingIdentity, right: MatchingIdentity) -> list[str]:
    """Known contradictions block moderation merge; unknown never proves equality."""
    result = []
    a, b = left.normalized_identity, right.normalized_identity
    for key in ("brand", "variant", "composition"):
        if a[key]["state"] != "unknown" and b[key]["state"] != "unknown" and a[key] != b[key]:
            result.append(key)
    if left.basis_unit != right.basis_unit:
        # Different bases require the same documented variant density.
        density = left.density_g_per_ml or right.density_g_per_ml
        if density is None:
            result.append("basis_unit")
    if (
        left.density_g_per_ml is not None
        and right.density_g_per_ml is not None
        and left.density_g_per_ml != right.density_g_per_ml
    ):
        result.append("density_g_per_ml")
    return result


def match_reasons(left: MatchingIdentity, right: MatchingIdentity) -> list[str]:
    if high_match(left, right):
        return ["shared_name", "identity_equal", "energy_within_10_percent"]
    reasons = []
    if set(left.names) & set(right.names):
        reasons.append("shared_name")
    reasons.extend("identity_conflict_" + key for key in identity_conflicts(left, right))
    missing = sorted(set(missing_identity_fields(left) + missing_identity_fields(right)))
    reasons.extend("missing_" + key for key in missing)
    if left.basis_unit != right.basis_unit and not (
        left.density_g_per_ml or right.density_g_per_ml
    ):
        reasons.append("density_required")
    return reasons or ["similar_name_manual_review"]


def build_matching_identity(draft: dict, metadata: MatchProductRequest) -> MatchingIdentity:
    """Validate public metadata against known private draft identity and quantities."""
    if not normalize_text(draft["name"]):
        raise ValueError("product_name_required")
    identity = metadata.identity.model_dump(mode="json")
    for key in ("brand", "variant"):
        known = draft[key]
        field = identity[key]
        if known is not None and (
            field["state"] != "known" or normalize_text(known) != normalize_text(field["value"])
        ):
            raise ValueError("draft_identity_conflict")
    density = draft["density_g_per_ml"]
    if density is not None:
        density = Decimal(density)
    if metadata.density is not None:
        if density is not None and density != metadata.density.amount:
            raise ValueError("draft_density_conflict")
        density = metadata.density.amount
    draft_portion = (
        QuantityDTO.model_validate(draft["package_quantity"])
        if draft["package_quantity"] is not None
        else None
    )
    if (
        metadata.portion is not None
        and draft_portion is not None
        and metadata.portion != draft_portion
    ):
        raise ValueError("draft_portion_conflict")
    portion = metadata.portion or draft_portion
    if portion is None:
        raise ValueError("portion_required")
    if portion.unit != draft["basis_unit"] and density is None:
        raise ValueError("density_required")
    nutrition = NutritionDTO.model_validate(draft["nutrition_per_100"])
    return MatchingIdentity(
        names=tuple(
            sorted({normalize_text(draft["name"]), *map(normalize_text, metadata.aliases)})
        ),
        identity=identity,
        basis_unit=draft["basis_unit"],
        energy_kcal=nutrition.energy_kcal,
        density_g_per_ml=density,
    )


def matching_from_snapshot(
    snapshot: Any, identity: IdentityDTO | dict | None = None
) -> MatchingIdentity:
    """Adapt exact ProductDTO/dict or ProductVersion; absent official composition stays unknown."""
    if hasattr(snapshot, "model_dump"):
        snapshot = snapshot.model_dump()
    if not isinstance(snapshot, dict):
        snapshot = {
            key: getattr(snapshot, key)
            for key in (
                "name",
                "aliases",
                "brand",
                "variant",
                "basis_unit",
                "energy_kcal",
                "density_amount",
            )
        }
    if identity is None:
        identity = {
            key: {
                "state": "known" if snapshot[key] and normalize_text(snapshot[key]) else "unknown",
                "value": snapshot[key] if snapshot[key] and normalize_text(snapshot[key]) else None,
            }
            for key in ("brand", "variant")
        }
        identity["composition"] = {"state": "unknown", "value": None}
    energy = snapshot.get("nutrition_per_100", {}).get("energy_kcal", snapshot.get("energy_kcal"))
    density = snapshot.get(
        "density", snapshot.get("density_g_per_ml", snapshot.get("density_amount"))
    )
    if isinstance(density, dict):
        density = density["amount"]
    return MatchingIdentity(
        names=tuple(
            sorted(
                {
                    name
                    for name in (
                        normalize_text(snapshot["name"]),
                        *map(normalize_text, snapshot["aliases"] or []),
                    )
                    if name
                }
            )
        ),
        identity=IdentityDTO.model_validate(identity).model_dump(mode="json"),
        basis_unit=snapshot["basis_unit"],
        energy_kcal=Decimal(energy) if energy is not None else None,
        density_g_per_ml=Decimal(density) if density is not None else None,
    )
