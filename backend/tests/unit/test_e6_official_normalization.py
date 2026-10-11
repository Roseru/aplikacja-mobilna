"""Runtime and frozen0014 Unicode normalization share the exact standard rule."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from calorie_app.modules.catalog.matching import normalize_text
from calorie_app.modules.catalog.search_metadata import normalized_text, search_metadata


@pytest.mark.parametrize(
    "value",
    [
        "Straße Suppe",
        "STRASSE SUPPE",
        "Ｒｏｓｏｌ",
        "Straße\u00a0\u2003Suppe",
        "\ufdfa" * 2000,
        "İ Σς σ",
        " A\t\n B ",
    ],
)
def test_frozen_migration_runtime_and_matching_normalization_agree(value):
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0014_catalog_search.py"
    spec = importlib.util.spec_from_file_location("migration0014", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    row = SimpleNamespace(
        product_id=uuid4(),
        revision=1,
        name=value,
        aliases=["ＡＬＩＡＳ", value],
        brand="ß",
        variant=" A\u2009B ",
    )
    expected = search_metadata(row.name, row.aliases, row.brand, row.variant)
    assert migration._metadata(row) == expected | {"product_id": row.product_id, "revision": 1}
    assert normalized_text(value) == normalize_text(value) == migration._normalized(value)
