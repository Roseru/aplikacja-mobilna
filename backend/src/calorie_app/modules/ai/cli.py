"""Offline migrator-only maintenance; quota history is never reset."""

import argparse
import hashlib
import json
from datetime import UTC
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from calorie_app.core.config import Settings
from calorie_app.db.session import make_engine
from calorie_app.modules.ai.configuration import configuration
from calorie_app.modules.ai.result import parse_bounded_json


def evidence(path):
    raw = Path(path).read_bytes()
    data = parse_bounded_json(raw, max_bytes=16384)
    if data.get("previous_io_fenced") is not True or not isinstance(data.get("observed_at"), str):
        raise ValueError("physical fencing evidence required")
    from datetime import datetime

    observed = datetime.fromisoformat(data["observed_at"])
    if observed.tzinfo is None or observed > datetime.now(UTC):
        raise ValueError("dated fencing evidence required")
    return hashlib.sha256(raw).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description="E7 operator maintenance with preserved quotas")
    parser.add_argument(
        "action", choices=("configure-pool", "fence-permit", "resume-after-restore")
    )
    parser.add_argument("--epoch", type=UUID, required=True)
    parser.add_argument("--attempt", type=UUID)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    engine = make_engine(settings)
    try:
        with engine.begin() as connection:
            member = connection.scalar(
                text("SELECT pg_has_role(current_user,'calorie_app_migrator','MEMBER')")
            )
            if (
                not member
                or connection.scalar(
                    text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
                )
                != args.epoch
            ):
                raise ValueError("exact migrator context required")
            if args.action == "configure-pool":
                connection.execute(text("SELECT id FROM app.ai_controls WHERE id=1 FOR UPDATE"))
                cfg = configuration(settings)
                if cfg.reason not in (None, "ai_credentials_unavailable"):
                    raise ValueError("verified configuration required")
                if cfg.profile["provider"] == "mock":
                    limits = {"rpm": 100, "tpm": 1000000, "rpd": 10000, "confirmed_at": None}
                else:
                    limits = parse_bounded_json(
                        settings.ai_live_confirmation.read_bytes(), max_bytes=16384
                    )
                    other = connection.scalar(
                        text(
                            "SELECT EXISTS(SELECT 1 FROM app.ai_pools WHERE provider='gemini' "
                            "AND project=:project AND environment<>:environment)"
                        ),
                        {
                            "project": settings.ai_project_id,
                            "environment": settings.ai_environment_id,
                        },
                    )
                    if other:
                        raise ValueError("one live environment per project")
                connection.execute(
                    text(
                        "INSERT INTO app.ai_pools(scope,provider,project,model,environment,"
                        "rpm,tpm,rpd,confirmed_at,free_only,enabled) "
                        "VALUES(:scope,:provider,:project,:model,:environment,:rpm,:tpm,:rpd,"
                        "coalesce(CAST(:confirmed AS timestamptz),clock_timestamp()),true,true) "
                        "ON CONFLICT(scope) DO UPDATE SET rpm=excluded.rpm,tpm=excluded.tpm,"
                        "rpd=excluded.rpd,confirmed_at=excluded.confirmed_at,enabled=true"
                    ),
                    {
                        "scope": cfg.profile["pool_scope"],
                        "provider": cfg.profile["provider"],
                        "model": cfg.profile["model"],
                        "project": settings.ai_project_id,
                        "environment": settings.ai_environment_id,
                        "rpm": limits["rpm"],
                        "tpm": limits["tpm"],
                        "rpd": limits["rpd"],
                        "confirmed": limits["confirmed_at"],
                    },
                )
                connection.execute(
                    text(
                        "INSERT INTO app.ai_transport_permits(environment,slot) "
                        "VALUES(:environment,1),(:environment,2) ON CONFLICT DO NOTHING"
                    ),
                    {"environment": settings.ai_environment_id},
                )
            else:
                if args.evidence is None or (
                    args.action == "fence-permit" and args.attempt is None
                ):
                    raise ValueError("evidence and exact target required")
                proof = evidence(args.evidence)
                if args.action == "fence-permit":
                    connection.execute(
                        text("SELECT app.e7_fence_permit(:attempt,:proof,true)"),
                        {"attempt": args.attempt, "proof": proof},
                    )
                else:
                    connection.execute(
                        text("SELECT app.e7_reconcile(:epoch,:proof,true)"),
                        {"epoch": args.epoch, "proof": proof},
                    )
        print(json.dumps({"status": "ok", "action": args.action}))
        return 0
    except Exception:
        print(json.dumps({"status": "unavailable", "code": "e7_operator_action_refused"}))
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
