"""Publishing and matching live own drafts, with bounded public reads."""

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, literal, or_, select

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.community.models import (
    CommunityAuthor,
    CommunityVersion,
    PublicationBinding,
)
from calorie_app.modules.catalog.community.repository import (
    PublicProduct,
    admit,
    append_audit,
    bump_catalog,
    community_page,
    community_statement,
    create_version,
    dto,
    escaped_search,
    exact_ref,
    lock_catalog,
    official_statement,
    require_public_product,
)
from calorie_app.modules.catalog.community.tokens import decode_page, encode_page
from calorie_app.modules.catalog.matching import (
    build_matching_identity,
    high_match,
    match_reasons,
    matching_from_snapshot,
    missing_identity_fields,
    normalize_text,
)
from calorie_app.modules.catalog.models import ProductSearchMetadata, ProductVersion
from calorie_app.modules.catalog.pagination import PAGE_TTL, database_now
from calorie_app.modules.catalog.product_pages import expiry_integer
from calorie_app.modules.catalog.validation import canonical, canonical_json
from calorie_app.modules.diary.models import ProductDraft
from calorie_app.modules.identity.service import current_epoch, require_account

PAGE_BYTES = 1024 * 1024


def own_draft(session, owner, request):
    draft = session.scalar(
        select(ProductDraft)
        .where(ProductDraft.owner_id == owner, ProductDraft.id == request.draft_id)
        .with_for_update()
    )
    if draft is None or draft.deleted_at is not None:
        raise DomainError(404, "not_found")
    if draft.revision != request.draft_revision:
        raise DomainError(409, "draft_revision_conflict")
    try:
        identity = build_matching_identity(draft.payload, request)
    except ValueError as error:
        raise DomainError(422, str(error)) from None
    return draft, identity


def high_candidates(session, identity):
    """Full exact relational predicate, LIMIT2 distinguishes unique from ambiguous."""
    if missing_identity_fields(identity):
        return []
    energy = literal(identity.energy_kcal)
    rho = func.coalesce(literal(identity.density_g_per_ml), ProductVersion.density_amount)
    left = case(
        (
            and_(ProductVersion.basis_unit != identity.basis_unit, identity.basis_unit == "g"),
            energy * rho,
        ),
        else_=energy,
    )
    right = case(
        (
            and_(ProductVersion.basis_unit != identity.basis_unit, identity.basis_unit == "ml"),
            ProductVersion.energy_kcal * rho,
        ),
        else_=ProductVersion.energy_kcal,
    )
    density_consistent = (
        True
        if identity.density_g_per_ml is None
        else or_(
            ProductVersion.density_amount.is_(None),
            ProductVersion.density_amount == identity.density_g_per_ml,
        )
    )
    statement = (
        community_statement()
        .where(
            CommunityVersion.identity_key == identity.identity_key,
            CommunityVersion.normalized_identity == identity.normalized_identity,
            CommunityVersion.normalized_name_hashes.overlap(
                [hashlib.sha256(name.encode("utf-8")).hexdigest() for name in identity.names]
            ),
            CommunityVersion.normalized_names.overlap(list(identity.names)),
            ProductVersion.energy_kcal.is_not(None),
            density_consistent,
            or_(ProductVersion.basis_unit == identity.basis_unit, rho.is_not(None)),
            func.abs(left - right) * 10 <= func.greatest(left, right),
        )
        .order_by(ProductVersion.product_id)
        .limit(2)
    )
    return session.execute(statement).all()


def manual_candidates(session, identity):
    """SQL selects at most21 per source; Python evaluates only those candidates."""
    predicates = [
        and_(
            CommunityVersion.normalized_name_hashes.overlap(
                [hashlib.sha256(name.encode("utf-8")).hexdigest() for name in identity.names]
            ),
            CommunityVersion.normalized_names.overlap(list(identity.names)),
        )
    ]
    predicates.extend(
        CommunityVersion.search_text.ilike(escaped_search(name), escape="\\")
        for name in identity.names
        if name
    )
    predicates.extend(CommunityVersion.search_text.op("%")(name) for name in identity.names if name)
    community = session.execute(
        community_statement().where(or_(*predicates)).order_by(ProductVersion.product_id).limit(21)
    ).all()
    official_predicates = [
        and_(
            ProductSearchMetadata.normalized_name_hashes.overlap(
                [hashlib.sha256(name.encode("utf-8")).hexdigest() for name in identity.names]
            ),
            ProductSearchMetadata.normalized_names.overlap(list(identity.names)),
        )
    ]
    official_predicates.extend(
        ProductSearchMetadata.search_text.ilike(escaped_search(name), escape="\\")
        for name in identity.names
        if name
    )
    official_predicates.extend(
        ProductSearchMetadata.search_text.op("%")(name) for name in identity.names if name
    )
    official = session.execute(
        official_statement()
        .join(
            ProductSearchMetadata,
            and_(
                ProductSearchMetadata.product_id == ProductVersion.product_id,
                ProductSearchMetadata.revision == ProductVersion.revision,
            ),
        )
        .where(or_(*official_predicates))
        .order_by(ProductVersion.product_id, ProductVersion.revision.desc())
        .limit(21)
    ).all()
    candidates = {}
    for version, _, metadata in community:
        other = matching_from_snapshot(version, metadata.identity)
        candidates[str(version.product_id)] = {
            "product": exact_ref(version),
            "provenance": "community",
            "reasons": match_reasons(identity, other),
            "high_confidence": high_match(identity, other),
        }
    for version, _ in official:
        key = str(version.product_id)
        if key not in candidates:
            other = matching_from_snapshot(version)
            candidates[key] = {
                "product": exact_ref(version),
                "provenance": "official",
                "reasons": match_reasons(identity, other),
                "high_confidence": False,
            }
    values = [candidates[key] for key in sorted(candidates)]
    return values[:20], len(values) > 20 or len(community) > 20 or len(official) > 20


def match_draft(session, principal, request, epoch):
    account = require_account(session, principal)
    if current_epoch(session) != epoch:
        raise DomainError(409, "sync_epoch_changed")
    lock_catalog(session, shared=True)
    _, identity = own_draft(session, account.id, request)
    high = high_candidates(session, identity)
    candidates, truncated = manual_candidates(session, identity)
    # Exact high matches must remain visible even if similarity candidates filled the page.
    for version, _, metadata in reversed(high):
        key = exact_ref(version)
        if not any(item["product"] == key for item in candidates):
            candidates.insert(
                0,
                {
                    "product": key,
                    "provenance": "community",
                    "reasons": match_reasons(
                        identity, matching_from_snapshot(version, metadata.identity)
                    ),
                    "high_confidence": True,
                },
            )
    truncated = truncated or len(candidates) > 20
    candidates = candidates[:20]
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
        "existing_product": exact_ref(high[0][0]) if len(high) == 1 else None,
        "candidates": candidates,
        "missing_identity_fields": missing,
        "truncated": truncated,
    }


def publication_metadata(draft, request, identity):
    portion = (
        request.portion.model_dump(mode="json")
        if request.portion is not None
        else draft.payload["package_quantity"]
    )
    density_description = (
        request.density.source_description
        if request.density is not None
        else draft.payload["density_source"]
    )
    raw_identity = request.identity.model_dump(mode="json")
    composition = raw_identity["composition"]["value"]
    snapshot = {
        "name": draft.payload["name"],
        "aliases": request.aliases,
        "brand": raw_identity["brand"]["value"],
        "variant": raw_identity["variant"]["value"],
        "basis_unit": draft.payload["basis_unit"],
        **draft.payload["nutrition_per_100"],
        "package_amount": portion["amount"],
        "package_unit": portion["unit"],
        "density_amount": None
        if identity.density_g_per_ml is None
        else canonical(identity.density_g_per_ml),
        "density_source_description": density_description,
        "source_locator": request.source_description,
        "status": "unverified",
        "preparation": None,
    }
    searchable = [draft.payload["name"], *request.aliases]
    searchable.extend(
        value["value"]
        for key, value in raw_identity.items()
        if key != "composition" and value["value"] is not None
    )
    searchable.extend(
        composition
        if isinstance(composition, list)
        else [composition]
        if composition is not None
        else []
    )
    metadata = {
        "source_kind": request.source_kind,
        "source_description": request.source_description,
        "identity": raw_identity,
        "normalized_identity": identity.normalized_identity,
        "ingredients": composition if isinstance(composition, list) else None,
        "recipe": composition if isinstance(composition, str) else None,
        "normalized_names": list(identity.names),
        "identity_key": identity.identity_key,
        "search_text": normalize_text(" ".join(searchable)),
    }
    validate_public_metadata(snapshot, metadata, identity)
    return snapshot, metadata


def validate_public_metadata(snapshot, metadata, identity):
    """Bound derived storage for publications and audited community corrections."""
    # The derived normalization may expand Unicode far beyond original wire size.
    # Reject before SQL rather than letting an internal storage cap surface as503.
    limits = (
        (snapshot, 1048576 - 4096),
        (metadata, 4194304 - 16384),
        (metadata["identity"], 1048576 - 4096),
        (identity.normalized_identity, 1048576 - 4096),
    )
    if any(len(canonical_json(value)) > limit for value, limit in limits):
        raise DomainError(422, "publication_metadata_too_large")
    if (
        any(len(name) > 36000 for name in identity.names)
        or len(metadata["search_text"].encode("utf-8")) > 1048576 - 4096
    ):
        raise DomainError(422, "publication_metadata_too_large")


def publish_draft(session, account, request, operation_id):
    """Called within execute_mutation after actor and catalog locks."""
    draft, identity = own_draft(session, account.id, request)
    metadata_hash = hashlib.sha256(canonical_json(request.model_dump(mode="json"))).hexdigest()
    binding = session.get(
        PublicationBinding, (account.id, request.draft_id, request.draft_revision)
    )
    if binding is not None:
        if binding.metadata_hash != metadata_hash:
            raise DomainError(409, "draft_already_published")
        return {key: binding.result_minimal[key] for key in ("decision", "product")}
    release = None
    if request.selected_product is not None:
        selected = require_public_product(
            session, request.selected_product.product_id, mutation=True
        )
        if selected.version.revision != request.selected_product.revision:
            raise DomainError(409, "selected_product_changed")
        result = {"decision": "selected_existing", "product": exact_ref(selected.version)}
        release = selected.release
    else:
        high = high_candidates(session, identity)
        if len(high) > 1:
            raise DomainError(409, "ambiguous_product_match")
        if high:
            result = {"decision": "existing_variant", "product": exact_ref(high[0][0])}
        else:
            if missing_identity_fields(identity) and not request.confirm_new:
                raise DomainError(409, "publication_confirmation_required")
            admit(session, account.id, "products")
            product_id, source_id = uuid4(), uuid4()
            snapshot, metadata = publication_metadata(draft, request, identity)
            density_source_id = uuid4() if identity.density_g_per_ml is not None else None
            create_version(session, product_id, 1, source_id, density_source_id, snapshot, metadata)
            session.add(CommunityAuthor(product_id=product_id, owner_id=account.id))
            result = {
                "decision": "new_product",
                "product": {"product_id": str(product_id), "revision": 1},
            }
            append_audit(
                session,
                {
                    "actor_id": str(account.id),
                    "operation_id": str(operation_id),
                    "action": "publish",
                    "reason": "user_confirmed_publication",
                    "new_ref": result["product"],
                    "new_state": 1,
                    "target_id": str(product_id),
                },
            )
            bump_catalog(session)
    session.add(
        PublicationBinding(
            owner_id=account.id,
            draft_id=request.draft_id,
            draft_revision=request.draft_revision,
            metadata_hash=metadata_hash,
            product_id=UUID(result["product"]["product_id"]),
            product_revision=result["product"]["revision"],
            result_minimal=result | {"official_release": release},
        )
    )
    session.flush()
    return result


def read_community(session, principal, product_id, revision=None):
    account = require_account(session, principal)
    current_epoch(session)
    lock_catalog(session, shared=True)
    public = require_public_product(session, product_id, revision)
    return dto(session, public, account.id)


def list_community(session, principal, query, secret):
    account = require_account(session, principal)
    epoch = current_epoch(session)
    state = lock_catalog(session, shared=True)
    now = database_now(session)
    after, expiry = None, expiry_integer(now + PAGE_TTL)
    if query.page_token is not None:
        token = decode_page(
            query.page_token,
            secret,
            owner=account.id,
            generation=account.generation,
            epoch=epoch,
            query=query.query,
            limit=query.limit,
            now=now,
        )
        if token["version"] != state.revision:
            raise DomainError(409, "catalog_changed")
        after, expiry = token["after"], token["expiry"]
    items = []
    more = False
    # At most16 candidate records remain in memory; max500 is a response limit,
    # not permission to materialize500 large identities before applying byte cap.
    budget = PAGE_BYTES - 4200
    used = len(canonical_json({"items": [], "next_page_token": None}))
    scan_after = after
    exhausted = False
    while not exhausted:
        batch = min(16, query.limit - len(items) + 1)
        rows = community_page(session, query=query.query, after=scan_after, limit=batch)
        exhausted = len(rows) < batch
        for version, community, _ in rows:
            if len(items) == query.limit:
                more = True
                exhausted = True
                break
            value = dto(session, PublicProduct(version, community, exact_ref(version)), account.id)
            size = len(canonical_json(value)) + 1
            if size > budget:
                raise DomainError(413, "community_record_too_large")
            if used + size > budget:
                more = True
                exhausted = True
                break
            items.append(value)
            scan_after = str(version.product_id)
            used += size
    next_token = None
    if more and items:
        next_token = encode_page(
            {
                "owner": str(account.id),
                "generation": account.generation,
                "epoch": str(epoch),
                "query": query.query,
                "filter": None,
                "sort": "id",
                "limit": query.limit,
                "after": items[-1]["product_id"],
                "version": state.revision,
                "expiry": expiry,
            },
            secret,
        )
    return {"items": items, "next_page_token": next_token}
