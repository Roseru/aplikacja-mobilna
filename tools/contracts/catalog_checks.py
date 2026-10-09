"""Local fixture invariants; no database, importer or future server simulation."""


def check_catalog(value, definition):
    """Return stable error codes after successful JSON Schema validation."""
    errors = set()
    name = definition.rsplit("/", 1)[-1]
    if name == "Manifest":
        if len(set(value["source_ids"])) != len(value["source_ids"]):
            errors.add("catalog_duplicate")
        if len(value["source_ids"]) != value["counts"]["sources"]:
            errors.add("catalog_counts")
        if value["path"] != f"base-pl.{value['release']}.json.gz":
            errors.add("catalog_manifest")
        return sorted(errors)
    if name != "Package":
        return []
    products = {(p["product_id"], p["revision"]): p for p in value["products"]}
    sources = {s["source_id"]: s for s in value["sources"]}
    rations = {(r["ration_id"], r["revision"]) for r in value["rations"]}
    if (len(products) != len(value["products"]) or len(sources) != len(value["sources"])
            or len(rations) != len(value["rations"])):
        errors.add("catalog_duplicate")
    counts = {"products": len(value["products"]), "rations": len(value["rations"]),
              "sources": len(value["sources"]),
              "components": sum(len(r["components"]) for r in value["rations"])}
    if counts != value["counts"] or counts["components"] > 100000:
        errors.add("catalog_counts")
    for product in value["products"]:
        if product["source_id"] not in sources:
            errors.add("catalog_reference")
        density = product["density_g_per_ml"]
        if density is not None and density["source_id"] not in sources:
            errors.add("catalog_reference")
        if product["package_quantity"]["unit"] != product["basis_unit"] and density is None:
            errors.add("catalog_unit")
    for ration in value["rations"]:
        if ration["source_id"] not in sources:
            errors.add("catalog_reference")
        positions = [c["position"] for c in ration["components"]]
        if positions != list(range(1, len(positions) + 1)):
            errors.add("catalog_order")
        if ration["complete"] and any(e["classification"] != "equipment" for e in ration["excluded_items"]):
            errors.add("catalog_completeness")
        for component in ration["components"]:
            reference = component["product"]
            product = products.get((reference["product_id"], reference["revision"]))
            if product is None:
                errors.add("catalog_reference")
            elif component["quantity"]["unit"] != product["basis_unit"] and product["density_g_per_ml"] is None:
                errors.add("catalog_unit")
            if product is not None and ration["complete"] and any(v is None for v in product["nutrition_per_100"].values()):
                errors.add("catalog_completeness")
    if value["kind"] == "official":
        if any(s["status"] != "verified" or s["missing_data"] or s["basis"] == "assumed_listed_quantity" for s in sources.values()):
            errors.add("catalog_official")
        for product in value["products"]:
            if product["status"] != "verified" or any(v is None for v in product["nutrition_per_100"].values()):
                errors.add("catalog_official")
        if any(r["status"] != "verified" or not r["complete"] or r["manufacturer"] is None for r in value["rations"]):
            errors.add("catalog_official")
    return sorted(errors)
