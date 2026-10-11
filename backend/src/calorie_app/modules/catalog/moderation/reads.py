"""Version-bound, byte-bounded moderator queue without reporter identifiers."""

from sqlalchemy import select

from calorie_app.core.errors import DomainError
from calorie_app.modules.catalog.community.models import CommunityProduct, CommunityReport
from calorie_app.modules.catalog.community.repository import lock_catalog, resolve_community
from calorie_app.modules.catalog.community.tokens import decode_page, encode_page
from calorie_app.modules.catalog.pagination import PAGE_TTL, database_now
from calorie_app.modules.catalog.product_pages import expiry_integer
from calorie_app.modules.catalog.validation import canonical_json
from calorie_app.modules.identity.service import current_epoch, require_account


def report_data(session, report):
    canonical_ref = {"product_id": str(report.product_id), "revision": report.product_revision}
    if session.get(CommunityProduct, report.product_id) is not None:
        canonical = resolve_community(session, report.product_id, require_visible=False)
        canonical_ref = {
            "product_id": str(canonical.product_id),
            "revision": canonical.current_revision,
        }
    return {
        "report_id": str(report.id),
        "product": {"product_id": str(report.product_id), "revision": report.product_revision},
        "canonical_ref": canonical_ref,
        "revision": report.revision,
        "status": report.status,
        "reason": report.reason,
        "description": report.description,
        "resolution_reason": report.resolution_reason,
    }


def list_reports(session, principal, query, secret):
    account = require_account(session, principal)
    epoch = current_epoch(session)
    state = lock_catalog(session, shared=True)
    now = database_now(session)
    after, expiry = None, expiry_integer(now + PAGE_TTL)
    if query.page_token is not None:
        token = decode_page(
            query.page_token,
            secret,
            kind="reports",
            owner=account.id,
            generation=account.generation,
            epoch=epoch,
            query=None,
            filter=query.status,
            limit=query.limit,
            now=now,
        )
        if token["version"] != state.queue_revision:
            raise DomainError(409, "moderation_queue_changed")
        after, expiry = token["after"], token["expiry"]
    statement = select(CommunityReport).order_by(CommunityReport.id).limit(query.limit + 1)
    if query.status is not None:
        statement = statement.where(CommunityReport.status == query.status)
    if after is not None:
        statement = statement.where(CommunityReport.id > after)
    rows = list(session.scalars(statement))
    items, used = [], 50
    more = len(rows) > query.limit
    for row in rows[: query.limit]:
        item = report_data(session, row)
        size = len(canonical_json(item)) + 1
        if size > 1044376:
            raise DomainError(413, "moderation_record_too_large")
        if used + size > 1044376:
            more = True
            break
        items.append(item)
        used += size
    token = None
    if more and items:
        token = encode_page(
            {
                "owner": str(account.id),
                "generation": account.generation,
                "epoch": str(epoch),
                "query": None,
                "filter": query.status,
                "sort": "id",
                "limit": query.limit,
                "after": items[-1]["report_id"],
                "version": state.queue_revision,
                "expiry": expiry,
            },
            secret,
            kind="reports",
        )
    return {"items": items, "next_page_token": token}
