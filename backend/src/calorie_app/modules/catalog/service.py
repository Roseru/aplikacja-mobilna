"""Controlled atomic import and reusable product reads; no public mutations."""

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageProduct,
    OfflinePackageRation,
    OfflinePackageSource,
    Product,
    ProductSource,
    ProductVersion,
    Ration,
    RationComponent,
    RationVersion,
)
from calorie_app.modules.catalog.repository import (
    components_for,
    product_data,
    ration_data,
    read_package,
    source_data,
)
from calorie_app.modules.catalog.timestamps import normalize_timestamp
from calorie_app.modules.catalog.validation import (
    CatalogValidationError,
    canonical_json,
    validate_package,
)

# Imports are rare operator jobs. One transaction lock serializes identity
# checks across packages as well as within a channel, without destructive UPSERT.
IMPORT_LOCK = 64324940002


@dataclass(frozen=True)
class ImportResult:
    package_id: UUID
    release: int
    created: bool


def content_hash(value: dict) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def ordered_package(value: dict) -> dict:
    return value | {
        "sources": sorted(value["sources"], key=lambda s: s["source_id"]),
        "products": sorted(value["products"], key=lambda p: (p["product_id"], p["revision"])),
        "rations": sorted(value["rations"], key=lambda r: (r["ration_id"], r["revision"])),
    }


def _same(existing, value, adapter) -> None:
    if existing.content_hash is None:
        raise CatalogValidationError("catalog_legacy_metadata")
    if existing.content_hash != content_hash(value) or adapter(existing) != value:
        raise CatalogValidationError("catalog_version_conflict")


def import_catalog(engine, value: dict) -> ImportResult:
    """Validate first, then import dependencies and seal in one DB transaction."""
    validate_package(value)
    value = normalize_timestamp(ordered_package(value))
    package_id, release = UUID(value["package_id"]), value["release"]
    if package_id == OFFICIAL_PACKAGE_ID and value["kind"] != "official":
        raise CatalogValidationError("catalog_channel")
    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
        channel = session.get(OfflineChannel, package_id)
        if channel is None:
            channel = OfflineChannel(package_id=package_id, kind=value["kind"], active_release=None)
            session.add(channel)
            session.flush()
        elif channel.kind != value["kind"]:
            raise CatalogValidationError("catalog_channel")
        existing = session.get(OfflinePackage, (package_id, release))
        if existing is not None:
            stored_value = read_package(session, package_id, release)
            if (
                existing.content_hash != content_hash(stored_value)
                or normalize_timestamp(stored_value) != value
            ):
                raise CatalogValidationError("catalog_release_conflict")
            return ImportResult(package_id, release, False)
        for source in value["sources"]:
            source_id = UUID(source["source_id"])
            stored = session.get(ProductSource, source_id)
            if stored is not None:
                _same(stored, source, source_data)
                continue
            session.add(
                ProductSource(
                    id=source_id,
                    description=source["document_id"],
                    **{k: v for k, v in source.items() if k not in {"source_id", "checked_on"}},
                    checked_on=date.fromisoformat(source["checked_on"]),
                    content_hash=content_hash(source),
                )
            )
        session.flush()
        for product in value["products"]:
            product_id = UUID(product["product_id"])
            stored = session.get(ProductVersion, (product_id, product["revision"]))
            if stored is not None:
                _same(stored, product, product_data)
                continue
            if session.get(Product, product_id) is None:
                session.add(Product(id=product_id))
                session.flush()
            density = product["density_g_per_ml"]
            session.add(
                ProductVersion(
                    product_id=product_id,
                    revision=product["revision"],
                    source_id=UUID(product["source_id"]),
                    **{
                        k: product[k]
                        for k in (
                            "name",
                            "aliases",
                            "brand",
                            "variant",
                            "basis_unit",
                            "source_locator",
                            "status",
                            "preparation",
                        )
                    },
                    **{
                        k: None if v is None else Decimal(v)
                        for k, v in product["nutrition_per_100"].items()
                    },
                    package_amount=Decimal(product["package_quantity"]["amount"]),
                    package_unit=product["package_quantity"]["unit"],
                    density_amount=None if density is None else Decimal(density["amount"]),
                    density_source_id=None if density is None else UUID(density["source_id"]),
                    content_hash=content_hash(product),
                )
            )
        session.flush()
        for ration in value["rations"]:
            ration_id = UUID(ration["ration_id"])
            stored = session.get(RationVersion, (ration_id, ration["revision"]))
            if stored is not None:
                _same(
                    stored,
                    ration,
                    lambda row: ration_data(
                        row, components_for(session, row.ration_id, row.revision)
                    ),
                )
                continue
            if session.get(Ration, ration_id) is None:
                session.add(Ration(id=ration_id))
                session.flush()
            row = RationVersion(
                ration_id=ration_id,
                revision=ration["revision"],
                source_id=UUID(ration["source_id"]),
                **{
                    k: ration[k]
                    for k in (
                        "name",
                        "manufacturer",
                        "variant",
                        "status",
                        "complete",
                        "excluded_items",
                    )
                },
                content_hash=None,
            )
            session.add(row)
            session.flush()
            for component in ration["components"]:
                session.add(
                    RationComponent(
                        ration_id=ration_id,
                        ration_revision=ration["revision"],
                        position=component["position"],
                        group_name=component["group"],
                        product_id=UUID(component["product"]["product_id"]),
                        product_revision=component["product"]["revision"],
                        amount=Decimal(component["quantity"]["amount"]),
                        unit=component["quantity"]["unit"],
                        optional=component["optional"],
                    )
                )
            session.flush()
            row.content_hash = content_hash(ration)
            session.flush()
        counts = value["counts"]
        package = OfflinePackage(
            package_id=package_id,
            release=release,
            schema_version=value["schema_version"],
            min_reader_version=value["min_reader_version"],
            published_at=datetime.fromisoformat(value["published_at"]),
            state="draft",
            sealed=False,
            content_hash=content_hash(value),
            product_count=counts["products"],
            ration_count=counts["rations"],
            source_count=counts["sources"],
            component_count=counts["components"],
        )
        session.add(package)
        session.flush()
        session.add_all(
            OfflinePackageProduct(
                package_id=package_id,
                release=release,
                product_id=UUID(p["product_id"]),
                product_revision=p["revision"],
            )
            for p in value["products"]
        )
        session.add_all(
            OfflinePackageRation(
                package_id=package_id,
                release=release,
                ration_id=UUID(r["ration_id"]),
                ration_revision=r["revision"],
            )
            for r in value["rations"]
        )
        session.add_all(
            OfflinePackageSource(
                package_id=package_id, release=release, source_id=UUID(s["source_id"])
            )
            for s in value["sources"]
        )
        session.flush()
        package.sealed = True
        session.flush()
    return ImportResult(package_id, release, True)


def recover_timestamp(engine, original: dict) -> ImportResult:
    """Restore only the proven original spelling of a sealed, unpublished draft.

    The relational graph, original package hash and membership stay immutable.
    Every child snapshot must also have a valid hash. The canonical original
    evidence and authenticated DB operator are recorded atomically in the audit.
    """
    validate_package(original)
    original = ordered_package(original)
    package_id, release = UUID(original["package_id"]), original["release"]
    with Session(engine) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
        row = session.get(OfflinePackage, (package_id, release), with_for_update=True)
        if row is None or not row.sealed or row.state != "draft":
            raise CatalogValidationError("catalog_recovery_requires_draft")
        if row.content_hash != content_hash(original):
            raise CatalogValidationError("catalog_recovery_input_conflict")
        restored = read_package(session, package_id, release) | {
            "published_at": original["published_at"]
        }
        if (
            normalize_timestamp(restored) != normalize_timestamp(original)
            or content_hash(restored) != row.content_hash
            or normalize_timestamp(original)["published_at"]
            != normalize_timestamp({"published_at": row.published_at.isoformat()})["published_at"]
        ):
            raise CatalogValidationError("catalog_recovery_graph_conflict")
        for source in original["sources"]:
            _same(session.get(ProductSource, UUID(source["source_id"])), source, source_data)
        for product in original["products"]:
            _same(
                session.get(ProductVersion, (UUID(product["product_id"]), product["revision"])),
                product,
                product_data,
            )
        for ration in original["rations"]:
            _same(
                session.get(RationVersion, (UUID(ration["ration_id"]), ration["revision"])),
                ration,
                lambda item: ration_data(
                    item, components_for(session, item.ration_id, item.revision)
                ),
            )
        existing = session.scalar(
            text(
                "SELECT original_input FROM app.catalog_timestamp_recoveries "
                "WHERE package_id=:package_id AND release=:release"
            ),
            {"package_id": package_id, "release": release},
        )
        evidence = canonical_json(original).decode("utf-8")
        if existing is not None:
            if existing != evidence:
                raise CatalogValidationError("catalog_recovery_input_conflict")
            return ImportResult(package_id, release, False)
        if restored == read_package(session, package_id, release):
            raise CatalogValidationError("catalog_recovery_not_required")
        session.execute(
            text(
                "INSERT INTO app.catalog_timestamp_recoveries "
                "(package_id,release,published_at_text,original_content_hash,original_input) "
                "VALUES (:package_id,:release,:timestamp,:content_hash,:evidence)"
            ),
            {
                "package_id": package_id,
                "release": release,
                "timestamp": original["published_at"],
                "content_hash": row.content_hash,
                "evidence": evidence,
            },
        )
    return ImportResult(package_id, release, True)


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def search_products(engine, package_id: UUID, release: int, query: str | None = None) -> list[dict]:
    """Internal service ready for E3 auth, including aliases/brand/variant.

    A match never merges identities or treats similar kcal as product identity.
    Only exact versions belonging to the requested immutable package are read.
    """
    if query is not None and not 1 <= len(query) <= 100:
        raise CatalogValidationError("catalog_query")
    with Session(engine) as session:
        products = read_package(session, package_id, release)["products"]
    latest = {}
    for product in products:
        latest[product["product_id"]] = product
    needle = None if query is None else _normalized(query)
    return [
        product
        for product in latest.values()
        if needle is None
        or any(
            needle in _normalized(value)
            for value in [
                product["name"],
                *product["aliases"],
                product["brand"],
                product["variant"],
            ]
            if value is not None
        )
    ]


def read_product(
    engine, package_id: UUID, release: int, product_id: UUID, revision: int | None = None
):
    with Session(engine) as session:
        matches = [
            p
            for p in read_package(session, package_id, release)["products"]
            if p["product_id"] == str(product_id)
            and (revision is None or p["revision"] == revision)
        ]
    return matches[-1] if matches else None
