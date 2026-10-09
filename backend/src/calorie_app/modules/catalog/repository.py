"""SQL reads and wire adapters. The caller owns every transaction."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageProduct,
    OfflinePackageRation,
    OfflinePackageSource,
    ProductSource,
    ProductVersion,
    RationComponent,
    RationVersion,
)
from calorie_app.modules.catalog.validation import CatalogValidationError, canonical

NUTRITION_FIELDS = ("energy_kcal", "protein_g", "fat_g", "carbs_g")


def utc_text(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def source_data(row: ProductSource) -> dict:
    if row.content_hash is None or row.checked_on is None:
        raise CatalogValidationError("catalog_legacy_metadata")
    return {
        "source_id": str(row.id),
        "document_id": row.document_id,
        "url": row.url,
        "checked_on": row.checked_on.isoformat(),
        "market": row.market,
        "manufacturer": row.manufacturer,
        "variant": row.variant,
        "basis": row.basis,
        "status": row.status,
        "missing_data": row.missing_data,
        "notes": row.notes,
    }


def product_data(row: ProductVersion) -> dict:
    if row.content_hash is None:
        raise CatalogValidationError("catalog_legacy_metadata")
    return {
        "product_id": str(row.product_id),
        "revision": row.revision,
        "name": row.name,
        "aliases": row.aliases,
        "brand": row.brand,
        "variant": row.variant,
        "basis_unit": row.basis_unit,
        "nutrition_per_100": {
            field: None if getattr(row, field) is None else canonical(getattr(row, field))
            for field in NUTRITION_FIELDS
        },
        "package_quantity": {"amount": canonical(row.package_amount), "unit": row.package_unit},
        "density_g_per_ml": None
        if row.density_amount is None
        else {"amount": canonical(row.density_amount), "source_id": str(row.density_source_id)},
        "source_id": str(row.source_id),
        "source_locator": row.source_locator,
        "status": row.status,
        "preparation": row.preparation,
    }


def ration_data(row: RationVersion, components: list[RationComponent]) -> dict:
    if row.content_hash is None:
        raise CatalogValidationError("catalog_legacy_metadata")
    return {
        "ration_id": str(row.ration_id),
        "revision": row.revision,
        "name": row.name,
        "manufacturer": row.manufacturer,
        "variant": row.variant,
        "status": row.status,
        "source_id": str(row.source_id),
        "complete": row.complete,
        "components": [
            {
                "position": c.position,
                "group": c.group_name,
                "product": {"product_id": str(c.product_id), "revision": c.product_revision},
                "quantity": {"amount": canonical(c.amount), "unit": c.unit},
                "optional": c.optional,
            }
            for c in components
        ],
        "excluded_items": row.excluded_items,
    }


def components_for(session: Session, ration_id: UUID, revision: int):
    return list(
        session.scalars(
            select(RationComponent)
            .where(
                RationComponent.ration_id == ration_id,
                RationComponent.ration_revision == revision,
            )
            .order_by(RationComponent.position)
        )
    )


def package_header(row: OfflinePackage, kind: str) -> dict:
    return {
        "package_id": str(row.package_id),
        "release": row.release,
        "schema_version": row.schema_version,
        "min_reader_version": row.min_reader_version,
        "published_at": utc_text(row.published_at),
        "kind": kind,
        "counts": {
            "products": row.product_count,
            "rations": row.ration_count,
            "components": row.component_count,
            "sources": row.source_count,
        },
    }


def read_package(session: Session, package_id: UUID, release: int) -> dict:
    """Reconstruct a graph from relational PostgreSQL data, never an input blob."""
    row = session.get(OfflinePackage, (package_id, release))
    channel = session.get(OfflineChannel, package_id)
    if row is None or channel is None or not row.sealed:
        raise CatalogValidationError("catalog_package_not_found")
    products = session.scalars(
        select(ProductVersion)
        .join(
            OfflinePackageProduct,
            and_(
                OfflinePackageProduct.product_id == ProductVersion.product_id,
                OfflinePackageProduct.product_revision == ProductVersion.revision,
            ),
        )
        .where(
            OfflinePackageProduct.package_id == package_id,
            OfflinePackageProduct.release == release,
        )
        .order_by(ProductVersion.product_id, ProductVersion.revision)
    )
    sources = session.scalars(
        select(ProductSource)
        .join(OfflinePackageSource, OfflinePackageSource.source_id == ProductSource.id)
        .where(
            OfflinePackageSource.package_id == package_id,
            OfflinePackageSource.release == release,
        )
        .order_by(ProductSource.id)
    )
    rations = session.scalars(
        select(RationVersion)
        .join(
            OfflinePackageRation,
            and_(
                OfflinePackageRation.ration_id == RationVersion.ration_id,
                OfflinePackageRation.ration_revision == RationVersion.revision,
            ),
        )
        .where(
            OfflinePackageRation.package_id == package_id,
            OfflinePackageRation.release == release,
        )
        .order_by(RationVersion.ration_id, RationVersion.revision)
    )
    components = session.scalars(
        select(RationComponent)
        .join(
            OfflinePackageRation,
            and_(
                OfflinePackageRation.ration_id == RationComponent.ration_id,
                OfflinePackageRation.ration_revision == RationComponent.ration_revision,
            ),
        )
        .where(
            OfflinePackageRation.package_id == package_id,
            OfflinePackageRation.release == release,
        )
        .order_by(
            RationComponent.ration_id, RationComponent.ration_revision, RationComponent.position
        )
    )
    grouped = {}
    for component in components:
        grouped.setdefault((component.ration_id, component.ration_revision), []).append(component)
    return package_header(row, channel.kind) | {
        "sources": [source_data(s) for s in sources],
        "products": [product_data(p) for p in products],
        "rations": [ration_data(r, grouped.get((r.ration_id, r.revision), [])) for r in rations],
    }


def active_package(session: Session, package_id: UUID) -> OfflinePackage | None:
    return session.scalar(
        select(OfflinePackage)
        .join(
            OfflineChannel,
            and_(
                OfflineChannel.package_id == OfflinePackage.package_id,
                OfflineChannel.active_release == OfflinePackage.release,
            ),
        )
        .where(
            OfflineChannel.package_id == package_id,
            OfflineChannel.kind == "official",
            OfflinePackage.state == "published",
        )
    )


def manifest_data(session: Session, row: OfflinePackage, kind: str) -> dict:
    return package_header(row, kind) | {
        "path": f"base-pl.{row.release}.json.gz",
        "compressed_bytes": row.compressed_bytes,
        "uncompressed_bytes": row.uncompressed_bytes,
        "sha256": row.sha256,
        "source_ids": [
            str(source_id)
            for source_id in session.scalars(
                select(OfflinePackageSource.source_id)
                .where(
                    OfflinePackageSource.package_id == row.package_id,
                    OfflinePackageSource.release == row.release,
                )
                .order_by(OfflinePackageSource.source_id)
            )
        ],
    }
