"""Account-owned votes and reports share the catalogue transaction and history."""

from uuid import uuid4

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.community.models import (
    CommunityReport,
    CommunityVote,
)
from calorie_app.modules.catalog.community.repository import (
    admit,
    append_audit,
    bump_catalog,
    is_author,
    require_public_product,
    vote_counts,
)


def public_feedback(session, account, product_id):
    public = require_public_product(session, product_id)
    canonical_id = public.canonical_ref["product_id"]
    # The resolver emits UUID refs internally; tolerate JSON-compatible refs too.
    from uuid import UUID

    canonical_id = UUID(str(canonical_id))
    counts = vote_counts(session, canonical_id)
    vote = session.get(CommunityVote, (account.id, canonical_id))
    return {
        "product": public.canonical_ref,
        **counts,
        "my_value": vote.value if vote is not None and vote.active else None,
        "my_revision": vote.revision if vote is not None else 0,
        "is_mine": is_author(session, account.id, canonical_id),
    }


def change_vote(session, account, product_id, expected_revision, value, operation_id):
    public = require_public_product(session, product_id, mutation=True)
    if is_author(session, account.id, product_id):
        raise DomainError(403, "own_product_vote")
    row = session.get(CommunityVote, (account.id, product_id))
    current = row.revision if row is not None else 0
    if current != expected_revision:
        raise DomainError(409, "vote_revision_conflict")
    if current == 2147483647:
        raise DomainError(409, "revision_exhausted")
    admit(session, account.id, "votes")
    if row is None:
        row = CommunityVote(
            owner_id=account.id,
            product_id=product_id,
            revision=1,
            value=value,
            active=value is not None,
        )
        session.add(row)
    else:
        row.revision += 1
        row.value = value
        row.active = value is not None
    session.flush()
    bump_catalog(session)
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "vote_withdraw" if value is None else "vote_change",
            "old_ref": public.canonical_ref,
            "new_ref": public.canonical_ref,
        },
    )
    return {"revision": row.revision, "value": row.value}


def create_report(session, account, product_id, body, operation_id):
    if body.product.product_id != product_id:
        raise DomainError(422, "product_reference_mismatch")
    public = require_public_product(session, product_id, body.product.revision, mutation=True)
    admit(session, account.id, "reports")
    row = CommunityReport(
        id=uuid4(),
        owner_id=account.id,
        product_id=product_id,
        product_revision=body.product.revision,
        canonical_id=product_id,
        reason=body.reason,
        description=body.description,
        status="open",
        revision=1,
    )
    session.add(row)
    session.flush()
    bump_catalog(session, queue=True)
    # Personal report text is kept only in the report, never copied to audit.
    append_audit(
        session,
        {
            "actor_id": str(account.id),
            "operation_id": str(operation_id),
            "action": "report_create",
            "old_ref": public.canonical_ref,
            "new_ref": {"product_id": str(product_id), "revision": body.product.revision},
        },
    )
    return 201, {"report_id": str(row.id), "revision": row.revision, "status": row.status}
