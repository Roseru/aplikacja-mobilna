"""Derived exact-version selectors; original catalogue bytes remain immutable."""

import hashlib

from sqlalchemy import text

from calorie_app.modules.catalog.matching import normalize_text as normalized_text
from calorie_app.modules.catalog.models import ProductSearchMetadata


def search_metadata(name, aliases, brand=None, variant=None):
    names = sorted({normalized_text(name), *map(normalized_text, aliases or [])})
    return {
        "normalized_names": names,
        "normalized_name_hashes": [hashlib.sha256(value.encode()).hexdigest() for value in names],
        "search_text": " ".join(
            names + [normalized_text(value) for value in (brand, variant) if value is not None]
        ),
    }


def metadata_installed(session):
    # Historical operator fixtures import before 0014. Upgrade backfills them;
    # production API readiness requires 0014, and its DB guard fences old tools.
    return session.scalar(text("SELECT to_regclass('app.product_search_metadata') IS NOT NULL"))


def add_search_metadata(session, row):
    """Migrator import transaction owns flush/commit; copies never edit a snapshot."""
    if session.get(ProductSearchMetadata, (row.product_id, row.revision)) is None:
        session.add(
            ProductSearchMetadata(
                product_id=row.product_id,
                revision=row.revision,
                **search_metadata(row.name, row.aliases, row.brand, row.variant),
            )
        )
