"""AI availability is separate from diary readiness; live is explicitly fail-closed."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.result import parse_bounded_json

NOTICE_VERSION = "food-photo-notice-v1"
PREPARATION_VERSION = "food-photo-preparation-v1"
PROMPT_VERSION = "food-photo-prompt-v1"
SCHEMA_VERSION = "food-photo-schema-v1"
REST_PROFILE_VERSION = "gemini-rest-v1beta-2026-10-11"


@dataclass(frozen=True)
class AIConfiguration:
    profile: dict
    transport: dict
    reason: str | None = None
    limits: dict | None = None


def configuration(settings):
    provider = settings.ai_provider
    if provider not in {"mock", "gemini"}:
        raise DomainError(503, "ai_configuration_invalid")
    model = settings.ai_model or ("mock-food-v1" if provider == "mock" else "gemini-3.5-flash-lite")
    names = (provider, settings.ai_project_id, model, settings.ai_environment_id)
    if any(re.fullmatch(r"[a-zA-Z0-9._-]{1,100}", value) is None for value in names):
        raise DomainError(503, "ai_configuration_invalid")
    profile = {
        "provider": provider,
        "model": model,
        "pool_scope": ":".join(names),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "preparation_version": PREPARATION_VERSION,
        "rest_profile_version": REST_PROFILE_VERSION,
        "mock_scenario": settings.ai_mock_scenario if provider == "mock" else None,
    }
    transport = {**profile, "environment": settings.environment}
    if provider == "mock":
        return AIConfiguration(profile, transport)
    reason = "ai_live_confirmation_required"
    try:
        path = settings.ai_live_confirmation
        if path is None or path.stat().st_size > 16384 or settings.environment != "development":
            return AIConfiguration(profile, transport, reason)
        with path.open("rb") as source:
            raw = parse_bounded_json(source.read(16385), max_bytes=16384)
        required = {
            "provider",
            "project_id",
            "environment_id",
            "model",
            "confirmed_at",
            "free_only",
            "billing_disabled",
            "development_only",
            "rpm",
            "tpm",
            "rpd",
            "model_verified",
            "quota_windows",
        }
        if (
            set(raw) != required
            or any(
                raw[key] is not True
                for key in ("free_only", "billing_disabled", "development_only", "model_verified")
            )
            or (raw["provider"], raw["project_id"], raw["model"], raw["environment_id"]) != names
        ):
            return AIConfiguration(profile, transport, reason)
        date = datetime.fromisoformat(raw["confirmed_at"])
        if (
            date.tzinfo is None
            or date > datetime.now(UTC)
            or raw["model"] != "gemini-3.5-flash-lite"
        ):
            return AIConfiguration(profile, transport, reason)
        for key, minimum, maximum in (
            ("rpm", 1, 100000),
            ("tpm", 10240, 1000000000),
            ("rpd", 1, 1000000),
        ):
            if type(raw[key]) is not int or not minimum <= raw[key] <= maximum:
                return AIConfiguration(profile, transport, reason)
        if not isinstance(raw["quota_windows"], dict) or len(raw["quota_windows"]) > 20:
            return AIConfiguration(profile, transport, reason)
        if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value():
            return AIConfiguration(profile, transport, "ai_credentials_unavailable")
        transport.update(
            api_key=settings.gemini_api_key.get_secret_value(),
            live_authorized=True,
            quota_windows=raw["quota_windows"],
        )
        return AIConfiguration(
            profile, transport, limits={key: raw[key] for key in ("rpm", "tpm", "rpd")}
        )
    except (OSError, ValueError, TypeError, KeyError):
        return AIConfiguration(profile, transport, reason)
