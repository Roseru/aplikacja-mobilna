"""Narrow SQL calls; all writes are guarded and transaction-owned by the caller."""

from sqlalchemy import text

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.repository import call, encoded

ERROR_STATUS = {
    "not_found": 404,
    "energy_notice_required": 403,
    "energy_notice_provider_mismatch": 403,
    "proposal_expired": 410,
    "ai_unavailable": 503,
    "ai_user_quota_exhausted": 429,
    "energy_analysis_cooldown": 429,
    "energy_apply_cooldown": 429,
}


def checked(value):
    if value is None:
        raise DomainError(404, "not_found")
    if "error" in value:
        code = value["error"]
        raise DomainError(ERROR_STATUS.get(code, 409), code)
    return value


def mutate(session, owner, key, kind, data, profile):
    return checked(
        call(
            session,
            "SELECT app.e9_mutate(:owner,:generation,:epoch,:key,:kind,CAST(:body AS jsonb),"
            "CAST(:profile AS jsonb))",
            owner=owner,
            generation=data.account_generation,
            epoch=data.sync_epoch,
            key=key,
            kind=kind,
            body=encoded(data.model_dump(mode="json")),
            profile=None if profile is None else encoded(profile),
        )
    )


def analysis(session, owner, analysis_id):
    return checked(
        call(session, "SELECT app.e9_analysis_read(:owner,:id)", owner=owner, id=analysis_id)
    )


def analyses(session, owner, limit):
    return list(
        session.scalars(
            text(
                "SELECT app.e9_analysis_read(:owner,id) FROM app.energy_analyses "
                "WHERE owner_id=:owner ORDER BY accepted_at DESC,id DESC LIMIT :limit"
            ),
            {"owner": owner, "limit": limit},
        )
    )


def history(session, owner, limit, after=0):
    return list(
        session.scalars(
            text(
                "SELECT app.e9_entity(id) FROM app.energy_versions WHERE owner_id=:owner "
                "AND revision>:after ORDER BY revision LIMIT :limit"
            ),
            {"owner": owner, "after": after, "limit": limit},
        )
    )


def state(session, owner):
    return checked(call(session, "SELECT app.e9_state(:owner)", owner=owner))
