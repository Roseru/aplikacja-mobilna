"""Derive the offline MRE reference release without changing the collected sources.

The independent MRE reference package coexists with the immutable base DEMO. It is not the official
ARPOL/FDC seed required by WYMAGANIA_PROJEKTOWE.md 11.4. DLA alternatives,
unconfirmed matches and COMRAD's older accessory average remain explicit.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import uuid
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal, localcontext
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = uuid.UUID("df877ff1-c740-57df-93f8-eab4f6ab44d1")
PUBLISHED = "2026-10-26T00:00:00Z"
CONFIRMED = {
    "source_profile",
    "source_generic_profile",
    "source_profile_other_menu",
    "variant_profiles",
    "source_packet_average",
}


def stable(text: str) -> str:
    return str(uuid.uuid5(NAMESPACE, text))


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def build(output: Path) -> dict:
    source_path = ROOT / "Random Data/MRE/mre_2026.json"
    # Only the generated copy normalizes line endings. The collected source stays untouched.
    # This binds APK assets consistently on Windows checkouts and Linux CI.
    source_bytes = source_path.read_bytes().replace(b"\r\n", b"\n")
    source = json.loads(source_bytes, parse_float=Decimal)
    if len(source["menus"]) != 24:
        raise ValueError("Unexpected reference inputs; a new source requires an explicit release")
    payload = {
        "schema_version": 1,
        "min_reader_version": 1,
        "package_id": stable("package:US-MRE-2026"),
        "kind": "demo",
        "release": 1,
        "published_at": PUBLISHED,
        "products": [],
        "rations": [],
        "sources": [],
    }
    profiles = source["nutrition_profiles"]
    products = {p["product_id"]: p for p in payload["products"]}
    sources = {s["source_id"]: s for s in payload["sources"]}
    dla_id = stable("DLA:MRE46:2026")
    sources[dla_id] = {
        "source_id": dla_id,
        "document_id": "DLA MRE XLVI 2026; collected indexed text",
        "url": source["source_url"],
        "checked_on": source["retrieved_date"],
        "market": "US",
        "manufacturer": None,
        "variant": "XLVI / 2026",
        "basis": "mixed_labels",
        "status": "unverified",
        "missing_data": [
            "Lista DLA pochodzi z indeksowanego tekstu; PDF zwracał HTTP403.",
            "Nie wszystkie składniki mają potwierdzone masy i wartości odżywcze.",
        ],
        "notes": [
            "Nie jest to specyfikacja konkretnej partii ani oficjalny seed ARPOL/FDC.",
            "Smaki alternatywne nie są jednocześnie zawartością jednej paczki.",
            "Masa porcji COMRAD nie określa liczby sztuk. Proszki: masa przed dodaniem wody.",
        ],
    }
    metadata = {
        "format": 1,
        "input_sha256": digest(source_bytes),
        "package_id": payload["package_id"],
        "release": 1,
        "kind": "demo",
        "menus": [],
    }

    def product(profile_id: str) -> dict | None:
        profile = profiles[profile_id]
        values = profile["values"]
        mass = values.get("weight_g")
        if mass is None or Decimal(mass) <= 0:
            return None
        mass = Decimal(mass)
        pid = stable("COMRAD:2026:" + profile_id)
        if pid in products:
            return products[pid]
        nutrition = {}
        for target, origin in [
            ("energy_kcal", "energy_kcal"),
            ("protein_g", "protein_g"),
            ("fat_g", "fat_g"),
            ("carbs_g", "carbohydrate_g"),
        ]:
            value = values.get(origin)
            if value is None:
                nutrition[target] = None
            else:
                with localcontext() as ctx:
                    ctx.prec = 40
                    per_100 = (Decimal(value) * 100 / mass).quantize(
                        Decimal("0.000001"), rounding=ROUND_HALF_UP
                    )
                if per_100 < 0:
                    raise ValueError("Negative primary nutrient in " + profile_id)
                nutrition[target] = decimal_text(per_100)
        sid = stable("COMRAD:source:2026:" + profile_id)
        missing = [name for name, value in values.items() if value is None]
        notes = list(profile.get("quality_notes_pl", [])) + [
            "Profil źródłowy "
            + profile_id
            + "; COMRAD, strona "
            + str(profile["source_page"])
            + ".",
            "Wartości na porcję "
            + decimal_text(mass)
            + " g przeliczono na100g z ROUND_HALF_UP do6miejsc.",
            "Oryginalne wartości, jednostki i uwagi są w lokalnym zbiorze źródłowym MRE2026.",
        ]
        sources[sid] = {
            "source_id": sid,
            "document_id": "HPRC COMRAD MRE46 2026 / " + profile_id,
            "url": profile["source_url"],
            "checked_on": source["retrieved_date"],
            "market": "US",
            "manufacturer": None,
            "variant": "2026 / XLVI",
            "basis": "label_serving",
            "status": "unverified",
            "missing_data": missing,
            "notes": notes,
        }
        result = {
            "product_id": pid,
            "revision": 1,
            "name": profile["name_source"],
            "aliases": ["MRE2026 " + profile["name_source"]],
            "brand": None,
            "variant": "COMRAD2026 " + profile_id,
            "basis_unit": "g",
            "nutrition_per_100": nutrition,
            "package_quantity": {"amount": decimal_text(mass), "unit": "g"},
            "density_g_per_ml": None,
            "source_id": sid,
            "source_locator": "COMRAD2026/page="
            + str(profile["source_page"])
            + "/profile="
            + profile_id,
            "status": "unverified",
            "preparation": "Porcja źródłowa, nie liczba sztuk. Proszek waż przed dodaniem wody.",
        }
        products[pid] = result
        return result

    for menu in source["menus"]:
        parts, excluded, bindings, choices, packets = [], [], [], [], []
        warnings = [
            "Sprawdź skład swojej paczki: DLA dopuszcza zamienniki.",
            "Warianty wybieraj osobno; brak danych nie oznacza zera.",
        ]

        def add(
            row: dict,
            locator: str,
            group: str,
            *,
            parts=parts,
            excluded=excluded,
            bindings=bindings,
            choices=choices,
        ) -> list[int]:
            nutrition = row["nutrition"]
            ids = nutrition.get("profile_ids", []) if nutrition["status"] in CONFIRMED else []
            usable = [(profile_id, product(profile_id)) for profile_id in ids]
            usable = [(profile_id, item) for profile_id, item in usable if item is not None]
            if not usable:
                equipment = nutrition["status"] == "not_applicable"
                reasons = list(nutrition.get("notes_pl", []))
                if not equipment:
                    reasons.append(
                        "Brak potwierdzonego profilu i masy; "
                        "nie użyto profilu porównawczego ani zera."
                    )
                else:
                    reasons.append("Element niejadalny — nie jest produktem dziennika.")
                excluded.append(
                    {
                        "source_locator": locator,
                        "name": row.get("name_pl") or row["name_en"],
                        "classification": "equipment"
                        if equipment
                        else "seasoning"
                        if row["name_en"] == "Salt"
                        else "food",
                        "source_amount": None,
                        "source_unit": None,
                        "reasons": reasons,
                    }
                )
                return []
            positions = []
            for profile_id, item in usable:
                position = len(parts) + 1
                parts.append(
                    {
                        "position": position,
                        "group": group,
                        "product": {"product_id": item["product_id"], "revision": 1},
                        "quantity": deepcopy(item["package_quantity"]),
                        "optional": bool(row.get("conditional", False)),
                    }
                )
                bindings.append(
                    {
                        "position": position,
                        "product_id": item["product_id"],
                        "revision": 1,
                        "profile_id": profile_id,
                        "source_locator": locator,
                        "nutrition_status": nutrition["status"],
                        "notes": list(nutrition.get("notes_pl", [])),
                        "flavours": row.get("variant_options_en", []),
                    }
                )
                positions.append(position)
            if len(positions) > 1:
                choices.append(
                    {"name": row.get("name_pl") or row["name_en"], "positions": positions}
                )
            return positions

        for component in menu["components"]:
            locator = menu["source_section"] + "/position=" + str(component["position"])
            packet = component.get("accessory_packet_id")
            group = component["name_en"]
            if packet:
                aggregate = (
                    add(component, locator, group)
                    if component["nutrition"]["status"] == "source_packet_average"
                    else []
                )
                children = []
                for index, child in enumerate(
                    source["accessory_packets"][packet]["components"], start=1
                ):
                    children += add(
                        child, locator + "/packet=" + packet + "/item=" + str(index), group
                    )
                packets.append({"name": group, "aggregate": aggregate, "details": children})
                if aggregate:
                    warnings.append(
                        "Pakiet " + packet + ": średnia COMRAD z MRE42; "
                        "nie dodawaj jej do osobno zapisanych składników."
                    )
            else:
                add(component, locator, group)
        if not parts:
            raise ValueError("No usable food in " + menu["id"])
        rid = stable("DLA:" + menu["id"])
        ration = {
            "ration_id": rid,
            "revision": 1,
            "name": "MRE2026 · "
            + menu["case"]
            + str(menu["menu_number"]).zfill(2)
            + " · "
            + menu["name_pl"],
            "manufacturer": None,
            "variant": menu["name_en"] + " / XLVI",
            "status": "unverified",
            "source_id": dla_id,
            "complete": False,
            "components": parts,
            "excluded_items": excluded,
        }
        payload["rations"].append(ration)
        metadata["menus"].append(
            {
                "ration_id": rid,
                "revision": 1,
                "source_menu_id": menu["id"],
                "case": menu["case"],
                "number": menu["menu_number"],
                "ration_sha256": digest(canonical(ration)),
                "bindings": bindings,
                "choices": choices,
                "packets": packets,
                "warnings": warnings,
            }
        )
    payload["products"] = sorted(
        products.values(), key=lambda item: (item["product_id"], item["revision"])
    )
    payload["rations"] = sorted(
        payload["rations"], key=lambda item: (item["ration_id"], item["revision"])
    )
    payload["sources"] = sorted(sources.values(), key=lambda item: item["source_id"])
    counts = {
        "products": len(payload["products"]),
        "rations": len(payload["rations"]),
        "components": sum(len(r["components"]) for r in payload["rations"]),
        "sources": len(payload["sources"]),
    }
    payload["counts"] = counts
    # Match the PostgreSQL export transport, including ordering, LF and gzip metadata.
    # Per-ration hashes above deliberately use canonical JSON without a terminal LF.
    raw = canonical(payload) + b"\n"
    buffer = BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as archive:
        archive.write(raw)
    compressed = buffer.getvalue()
    metadata["payload_sha256"] = digest(raw)
    metadata["gzip_sha256"] = digest(compressed)
    manifest = {
        "schema_version": 1,
        "package_id": payload["package_id"],
        "kind": "demo",
        "release": 1,
        "min_reader_version": 1,
        "published_at": PUBLISHED,
        "path": "base-pl.1.json.gz",
        "compressed_bytes": len(compressed),
        "uncompressed_bytes": len(raw),
        "sha256": digest(compressed),
        "counts": counts,
        "source_ids": sorted(sources),
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, content in {
        "manifest.json": canonical(manifest) + b"\n",
        "base-pl.1.json.gz.bin": compressed,
        "selection-rules.json": canonical(metadata),
        "source.json": source_bytes,
    }.items():
        (output / name).write_bytes(content)
    return {
        "menus": len(metadata["menus"]),
        **counts,
        "source_sha256": digest(source_bytes),
        "payload_sha256": digest(raw),
        "gzip_sha256": digest(compressed),
        "kind": "demo",
        "official_seed": "NOT_CREATED",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "android/app/src/main/assets/catalog/mre2026"
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
