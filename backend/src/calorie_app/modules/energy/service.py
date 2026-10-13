"""Online owner context, then the common account/counter SQL transaction."""

from calorie_app.core.errors import DomainError
from calorie_app.modules.ai.configuration import AIConfiguration, configuration
from calorie_app.modules.energy import repository
from calorie_app.modules.identity.service import current_epoch, require_account


def energy_configuration(settings):
    cfg = configuration(settings)
    profile = cfg.profile | {"purpose": "energy_adjustment"}
    profile.update(
        prompt_version="energy-explanation-v1",
        schema_version="energy-explanation-v1",
        preparation_version="energy-aggregates-v1",
    )
    return AIConfiguration(profile, cfg.transport | profile, cfg.reason, cfg.limits)


def mutate(session, principal, settings, key, kind, data):
    account = require_account(session, principal)
    if account.generation != data.account_generation:
        raise DomainError(409, "account_generation_changed")
    if current_epoch(session) != data.sync_epoch:
        raise DomainError(409, "sync_epoch_changed")
    try:
        cfg = energy_configuration(settings)
    except DomainError:
        cfg = None
    # Missing configuration is passed fail-closed; insufficient inputs still
    # return an honest deterministic status without dispatch or quota admission.
    profile = cfg.profile if cfg is not None and cfg.reason is None else None
    return repository.mutate(session, account.id, key, kind, data, profile)
