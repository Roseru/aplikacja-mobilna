"""Bounded catalog queries and narrow SQL writes; caller owns transaction."""

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import load_only

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.community.models import (
    CommunityAuthor,
    CommunityProduct,
    CommunityVersion,
    CommunityVote,
)
from calorie_app.modules.catalog.models import (
    OfflineChannel,
    OfflinePackage,
    OfflinePackageProduct,
    ProductSource,
    ProductVersion,
)
from calorie_app.modules.catalog.validation import canonical, canonical_json


@dataclass(frozen=True)
class PublicProduct:
    version: ProductVersion
    community: CommunityProduct | None
    canonical_ref: dict
    release: int | None = None


def lock_catalog(session, *, shared=False):
    row = session.execute(
        text("SELECT * FROM app.lock_community_catalog(:shared)"), {"shared": shared}
    ).one_or_none()
    if row is None:
        raise DomainError(503, "service_unavailable")
    return row


def bump_catalog(session, *, queue=False):
    return session.scalar(text("SELECT app.bump_community_catalog(:queue)"), {"queue": queue})


def admit(session, owner, kind):
    if not session.scalar(
        text("SELECT app.admit_community_operation(:owner,:kind)"), {"owner": owner, "kind": kind}
    ):
        raise DomainError(429, "community_quota_exhausted", [{"field": "quota", "reason": kind}])


def append_audit(session, event):
    return session.scalar(
        text("SELECT app.append_community_audit(CAST(:event AS jsonb))"),
        {"event": canonical_json(event).decode()},
    )


def exact_ref(row):
    return {"product_id": str(row.product_id), "revision": row.revision}


def resolve_community(session, product_id, *, require_visible=True):
    """Bounded traversal validates visibility of source and every canonical target."""
    current = product_id
    visited = set()
    for _ in range(16):
        if current in visited:
            raise DomainError(409, "canonical_cycle")
        visited.add(current)
        state = session.get(CommunityProduct, current)
        if state is None:
            raise DomainError(404, "not_found")
        if require_visible and state.visibility != "visible":
            raise DomainError(404, "not_found")
        if state.canonical_id is None or state.canonical_id == current:
            return state
        current = state.canonical_id
    raise DomainError(409, "canonical_depth_exceeded")


def official_statement(product_id=None, revision=None, *, active=True):
    statement = (
        select(ProductVersion, OfflinePackage.release)
        .join(
            OfflinePackageProduct,
            and_(
                OfflinePackageProduct.product_id == ProductVersion.product_id,
                OfflinePackageProduct.product_revision == ProductVersion.revision,
            ),
        )
        .join(
            OfflinePackage,
            and_(
                OfflinePackage.package_id == OfflinePackageProduct.package_id,
                OfflinePackage.release == OfflinePackageProduct.release,
            ),
        )
        .join(OfflineChannel, OfflineChannel.package_id == OfflinePackage.package_id)
        .where(
            OfflineChannel.package_id == OFFICIAL_PACKAGE_ID,
            OfflineChannel.kind == "official",
            OfflinePackage.state == "published",
        )
    )
    if active:
        statement = statement.where(OfflinePackage.release == OfflineChannel.active_release)
    if product_id is not None:
        statement = statement.where(ProductVersion.product_id == product_id)
    if revision is not None:
        statement = statement.where(ProductVersion.revision == revision)
    return statement


def require_public_product(session, product_id, revision=None, *, mutation=False):
    state = session.get(CommunityProduct, product_id)
    if state is not None:
        canonical = resolve_community(session, product_id)
        canonical_ref = {
            "product_id": str(canonical.product_id),
            "revision": canonical.current_revision,
        }
        if mutation and canonical.product_id != product_id:
            raise DomainError(
                409,
                "product_merged",
                [
                    {
                        "field": "canonical_product",
                        "reason": json.dumps(canonical_ref, separators=(",", ":")),
                    }
                ],
            )
        wanted = state.current_revision if revision is None else revision
        version = session.get(ProductVersion, (product_id, wanted))
        if version is None:
            raise DomainError(404, "not_found")
        return PublicProduct(version, state, canonical_ref)
    found = session.execute(
        official_statement(product_id, revision, active=revision is None)
        .order_by(ProductVersion.revision.desc(), OfflinePackage.release.desc())
        .limit(1)
    ).first()
    if found is None:
        raise DomainError(404, "not_found")
    row, release = found
    return PublicProduct(row, None, exact_ref(row), release)


def is_author(session, owner, product_id):
    return bool(
        session.scalar(
            select(CommunityAuthor.product_id)
            .join(CommunityProduct, CommunityProduct.product_id == CommunityAuthor.product_id)
            .where(
                CommunityAuthor.owner_id == owner,
                or_(
                    CommunityProduct.product_id == product_id,
                    CommunityProduct.canonical_id == product_id,
                ),
            )
            .limit(1)
        )
    )


def vote_counts(session, product_id):
    result = session.execute(
        select(
            func.count().filter(CommunityVote.value == 1),
            func.count().filter(CommunityVote.value == -1),
        ).where(
            CommunityVote.product_id == product_id,
            CommunityVote.active.is_(True),
            CommunityVote.value.is_not(None),
        )
    ).one()
    return {
        "positive_votes": result[0],
        "negative_votes": result[1],
        "voters": result[0] + result[1],
    }


def dto(session, public, owner):

    version, state = public.version, public.community
    metadata = session.get(CommunityVersion, (version.product_id, version.revision))
    if state is None or metadata is None:
        raise DomainError(404, "not_found")
    nutrition = {
        name: None if getattr(version, name) is None else canonical(getattr(version, name))
        for name in ("energy_kcal", "protein_g", "fat_g", "carbs_g")
    }
    missing = [name for name, value in nutrition.items() if value is None]
    density = None
    if version.density_amount is not None:
        density_source = session.get(ProductSource, version.density_source_id)
        density = {
            "amount": canonical(version.density_amount),
            "source_description": density_source.description,
        }
    identity_missing = [
        name
        for name in ("brand", "variant", "composition")
        if metadata.identity[name]["state"] == "unknown"
    ]
    if version.energy_kcal is None:
        identity_missing.append("energy_kcal")
    return {
        "product_id": str(version.product_id),
        "revision": version.revision,
        "canonical_ref": public.canonical_ref,
        "state_revision": state.state_revision,
        "name": version.name,
        "aliases": version.aliases or [],
        "brand": version.brand,
        "variant": version.variant,
        "basis_unit": version.basis_unit,
        "nutrition_per_100": nutrition,
        "portion": {"amount": canonical(version.package_amount), "unit": version.package_unit},
        "density": density,
        "source_id": str(version.source_id),
        "source_kind": metadata.source_kind,
        "source_description": metadata.source_description,
        "identity": metadata.identity,
        "provenance": "community",
        "verification": state.verification
        if version.revision == state.current_revision
        else "unverified",
        "visibility": state.visibility,
        "complete": not missing,
        "missing_nutrition_fields": missing,
        "missing_identity_fields": identity_missing,
        "is_mine": is_author(session, owner, UUID(public.canonical_ref["product_id"])),
        **vote_counts(session, UUID(public.canonical_ref["product_id"])),
    }


def community_statement():
    return (
        select(ProductVersion, CommunityProduct, CommunityVersion)
        .options(
            load_only(
                CommunityVersion.source_kind,
                CommunityVersion.source_description,
                CommunityVersion.identity,
            )
        )
        .join(
            CommunityProduct,
            and_(
                CommunityProduct.product_id == ProductVersion.product_id,
                CommunityProduct.current_revision == ProductVersion.revision,
            ),
        )
        .join(
            CommunityVersion,
            and_(
                CommunityVersion.product_id == ProductVersion.product_id,
                CommunityVersion.revision == ProductVersion.revision,
            ),
        )
        .where(
            CommunityProduct.visibility == "visible",
            or_(
                CommunityProduct.canonical_id.is_(None),
                CommunityProduct.canonical_id == CommunityProduct.product_id,
            ),
        )
    )


def escaped_search(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def community_page(session, *, query=None, after=None, limit=100):
    statement = community_statement()
    if query is not None:
        from calorie_app.modules.catalog.matching import normalize_text

        statement = statement.where(
            CommunityVersion.search_text.ilike(escaped_search(normalize_text(query)), escape="\\")
        )
    if after is not None:
        statement = statement.where(ProductVersion.product_id > UUID(after))
    return session.execute(statement.order_by(ProductVersion.product_id).limit(limit)).all()


def create_version(session, product_id, revision, source_id, density_source_id, snapshot, metadata):
    session.execute(
        text(
            "SELECT app.create_community_version(:product,:revision,:source,:density_source,"
            "CAST(:snapshot AS jsonb),CAST(:metadata AS jsonb))"
        ),
        {
            "product": product_id,
            "revision": revision,
            "source": source_id,
            "density_source": density_source_id,
            "snapshot": canonical_json(snapshot).decode(),
            "metadata": canonical_json(metadata).decode(),
        },
    )
