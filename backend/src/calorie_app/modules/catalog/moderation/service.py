"""Versioned community corrections, explicit report decisions and atomic merges."""

from uuid import uuid4

from sqlalchemy import select, update

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.community.models import (
    CommunityAuthor,
    CommunityProduct,
    CommunityReport,
    CommunityVersion,
    CommunityVote,
)
from calorie_app.modules.catalog.community.repository import (
    append_audit,
    bump_catalog,
    create_version,
    exact_ref,
    resolve_community,
)
from calorie_app.modules.catalog.community.service import validate_public_metadata
from calorie_app.modules.catalog.matching import (
    identity_conflicts,
    matching_from_snapshot,
    normalize_text,
)
from calorie_app.modules.catalog.models import ProductVersion
from calorie_app.modules.catalog.validation import canonical


def require_moderator(principal):
    if "user" not in principal.roles or not ({"catalog_moderator", "admin"} & principal.roles):
        raise DomainError(403, "forbidden")


def state_row(session, product_id):
    row = session.scalar(
        select(CommunityProduct)
        .where(CommunityProduct.product_id == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        # Official and absent IDs reveal no mutable community resource.
        raise DomainError(404, "not_found")
    return row


def require_root(session, state, *, visible=True):
    canonical = resolve_community(session, state.product_id, require_visible=False)
    if state.canonical_id is not None:
        raise DomainError(
            409,
            "product_merged",
            [
                {
                    "field": "canonical_product",
                    "reason": str(canonical.product_id),
                }
            ],
        )
    if visible and state.visibility != "visible":
        raise DomainError(404, "not_found")


def next_revision(value):
    if value >= 2147483647:
        raise DomainError(409, "revision_exhausted")
    return value + 1


def moderate_product(session, account, product_id, body, operation_id):
    state = state_row(session, product_id)
    require_root(session, state, visible=False)
    if state.state_revision != body.expected_state_revision:
        raise DomainError(409, "product_state_conflict")
    old_version = session.get(ProductVersion, (product_id, state.current_revision))
    old_ref, old_state = exact_ref(old_version), state.state_revision
    version = old_version
    if body.correction is not None:
        correction = body.correction
        revision = next_revision(state.current_revision)
        public = correction.model_dump(mode="json")
        snapshot = {
            "name": correction.name,
            "aliases": correction.aliases,
            "brand": correction.identity.brand.value,
            "variant": correction.identity.variant.value,
            "basis_unit": correction.basis_unit,
            **public["nutrition_per_100"],
            "package_amount": canonical(correction.portion.amount),
            "package_unit": correction.portion.unit,
            "density_amount": canonical(correction.density.amount) if correction.density else None,
            "density_source_description": correction.density.source_description
            if correction.density
            else None,
            "source_locator": correction.source_description,
            "preparation": None,
        }
        identity = matching_from_snapshot(snapshot, correction.identity)
        composition = correction.identity.composition.value
        searchable = [correction.name, *correction.aliases]
        searchable.extend(
            value
            for value in (
                correction.identity.brand.value,
                correction.identity.variant.value,
            )
            if value is not None
        )
        searchable.extend(
            composition
            if isinstance(composition, list)
            else [composition]
            if composition is not None
            else []
        )
        metadata = {
            "source_kind": correction.source_kind,
            "source_description": correction.source_description,
            "identity": public["identity"],
            "normalized_names": list(identity.names),
            "normalized_identity": identity.normalized_identity,
            "identity_key": identity.identity_key,
            "ingredients": composition if isinstance(composition, list) else None,
            "recipe": composition if isinstance(composition, str) else None,
            "search_text": normalize_text(" ".join(searchable)),
        }
        validate_public_metadata(snapshot, metadata, identity)
        create_version(
            session,
            product_id,
            revision,
            uuid4(),
            uuid4() if correction.density else None,
            snapshot,
            metadata,
        )
        session.expire_all()
        state = state_row(session, product_id)
        state.current_revision = revision
        state.verification = "unverified"
        state.state_revision = next_revision(old_state)
        with session.no_autoflush:
            version = session.get(ProductVersion, (product_id, revision))
    if body.verification == "verified":
        if not body.source_confirmed or any(
            getattr(version, field) is None
            for field in ("energy_kcal", "protein_g", "fat_g", "carbs_g")
        ):
            raise DomainError(409, "verification_requires_complete_source")
    if body.verification is not None:
        state.verification = body.verification
    if body.visibility is not None:
        state.visibility = body.visibility
    state.state_revision = next_revision(old_state)
    session.flush()
    new_ref = exact_ref(version)
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "product_moderate",
            "reason": body.reason,
            "old_ref": old_ref,
            "new_ref": new_ref,
            "old_state": old_state,
            "new_state": state.state_revision,
            "source_id": str(product_id),
        },
    )
    bump_catalog(session)
    return {"product": new_ref, "canonical_ref": new_ref, "state_revision": state.state_revision}


def merge_products(session, account, source_id, body, operation_id):
    target_id = body.target.product_id
    if source_id == target_id:
        raise DomainError(409, "self_merge")
    states = {value: state_row(session, value) for value in sorted((source_id, target_id))}
    source, target = states[source_id], states[target_id]
    require_root(session, source)
    require_root(session, target)
    if (
        source.state_revision != body.expected_source_state_revision
        or target.state_revision != body.expected_target_state_revision
        or target.current_revision != body.target.revision
    ):
        raise DomainError(409, "product_state_conflict")
    source_version = session.get(ProductVersion, (source_id, source.current_revision))
    target_version = session.get(ProductVersion, (target_id, target.current_revision))
    source_metadata = session.get(CommunityVersion, (source_id, source.current_revision))
    target_metadata = session.get(CommunityVersion, (target_id, target.current_revision))
    conflicts = identity_conflicts(
        matching_from_snapshot(source_version, source_metadata.identity),
        matching_from_snapshot(target_version, target_metadata.identity),
    )
    if conflicts or not body.identity_confirmed:
        raise DomainError(
            409,
            "identity_conflict",
            [{"field": key, "reason": "known_identity_conflict"} for key in conflicts],
        )
    # Entire source group becomes a direct link to target; every descendant
    # keeps its own snapshot, visibility and authorship. No new chain is built.
    source_group = select(CommunityProduct.product_id).where(
        (CommunityProduct.product_id == source_id) | (CommunityProduct.canonical_id == source_id)
    )
    if (
        session.scalar(
            select(CommunityVote.owner_id)
            .where(
                (
                    CommunityVote.product_id.in_(source_group)
                    | (CommunityVote.product_id == target_id)
                ),
                CommunityVote.active.is_(True),
                CommunityVote.revision == 2147483647,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(409, "revision_exhausted")
    author_ids = (
        select(CommunityAuthor.owner_id)
        .join(CommunityProduct, CommunityProduct.product_id == CommunityAuthor.product_id)
        .where(
            CommunityProduct.product_id.in_(source_group)
            | (CommunityProduct.product_id == target_id)
            | (CommunityProduct.canonical_id == target_id)
        )
    )
    # Opinion policy v1: source opinions are withdrawn; target self-votes too.
    source_votes = session.execute(
        update(CommunityVote)
        .where(CommunityVote.product_id.in_(source_group), CommunityVote.active.is_(True))
        .values(active=False, revision=CommunityVote.revision + 1)
    ).rowcount
    target_votes = session.execute(
        update(CommunityVote)
        .where(
            CommunityVote.product_id == target_id,
            CommunityVote.owner_id.in_(author_ids),
            CommunityVote.active.is_(True),
        )
        .values(active=False, revision=CommunityVote.revision + 1)
    ).rowcount
    old_state = source.state_revision
    # Protect against exhaustion before either group update can overflow.
    if (
        session.scalar(
            select(CommunityProduct.product_id)
            .where(
                CommunityProduct.product_id.in_(source_group),
                CommunityProduct.state_revision == 2147483647,
            )
            .limit(1)
        )
        is not None
    ):
        raise DomainError(409, "revision_exhausted")
    target.state_revision = next_revision(target.state_revision)
    source.canonical_id = target_id
    source.state_revision = next_revision(old_state)
    session.flush()
    # The DB guard permits only this direct compression through the source
    # whose canonical link was just committed in this same transaction.
    session.execute(
        update(CommunityProduct)
        .where(CommunityProduct.canonical_id == source_id)
        .values(canonical_id=target_id, state_revision=CommunityProduct.state_revision + 1)
    )
    session.flush()
    session.refresh(source)
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "product_merge",
            "reason": body.reason,
            "old_ref": exact_ref(source_version),
            "new_ref": exact_ref(target_version),
            "old_state": old_state,
            "new_state": source.state_revision,
            "source_id": str(source_id),
            "target_id": str(target_id),
        },
    )
    # Separate nonpersonal audit events record the opinion policy/counts.
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "merge_votes_deactivated",
            "reason": f"source={source_votes}; target_self={target_votes}",
            "source_id": str(source_id),
            "target_id": str(target_id),
        },
    )
    bump_catalog(session, queue=True)
    return {
        "source": exact_ref(source_version),
        "target": exact_ref(target_version),
        "source_state_revision": source.state_revision,
        "target_state_revision": target.state_revision,
    }


def resolve_report(session, account, report_id, body, operation_id):
    report = session.scalar(
        select(CommunityReport).where(CommunityReport.id == report_id).with_for_update()
    )
    if report is None:
        raise DomainError(404, "not_found")
    if report.revision != body.expected_revision:
        raise DomainError(409, "report_revision_conflict")
    if report.status != "open":
        raise DomainError(409, "report_already_decided")
    # An official discrepancy cannot be patched by this moderator endpoint.
    # `resolved` means actual correction, so official is referred or dismissed.
    if session.get(CommunityProduct, report.product_id) is None and body.status == "resolved":
        raise DomainError(409, "official_report_requires_admin_release")
    old_revision = report.revision
    report.revision = next_revision(report.revision)
    report.status = body.status
    report.resolution_reason = body.reason
    session.flush()
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "report_" + body.status,
            "reason": body.reason,
            "old_ref": {"product_id": str(report.product_id), "revision": report.product_revision},
            "old_state": old_revision,
            "new_state": report.revision,
        },
    )
    bump_catalog(session, queue=True)
    return {"report_id": str(report.id), "revision": report.revision, "status": report.status}
