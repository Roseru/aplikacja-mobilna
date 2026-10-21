"""Restartable operator protocol: begin commit → provider → confirm commit → purge.

The DB functions own authorization and lock order. Network calls never run
inside a database transaction. The retained job permits retry after any crash.
"""

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import create_engine, text

from calorie_app.integrations.keycloak.admin import (
    AdminFailure,
    KeycloakAdmin,
    RealmAdminConfig,
)


def status(connection, operation_id: UUID) -> dict:
    from datetime import datetime

    result = connection.scalar(
        text("SELECT app.ledger_status(:operation)"), {"operation": operation_id}
    )
    if result is None:
        raise ValueError("Unknown deletion operation")
    for key in ("created_at", "identity_confirmed_at", "block_until", "purged_at"):
        if result[key] is not None:
            result[key] = datetime.fromisoformat(result[key])
    for key in ("operation_id", "account_id"):
        result[key] = UUID(result[key])
    return result


def begin(connection, account_id: UUID, operation_id: UUID, expected_generation: int) -> dict:
    connection.execute(
        text("SELECT app.begin_account_deletion(:owner,:operation,:generation)"),
        {"owner": account_id, "operation": operation_id, "generation": expected_generation},
    )
    return status(connection, operation_id)


def resume(engine, operation_id: UUID, adapter, *, barrier=None, delivery=None) -> dict:
    def emit(stage):
        if barrier:
            barrier(stage)

    def deliver():
        if delivery is not None:
            delivery()

    deliver()
    with engine.begin() as connection:
        job = status(connection, operation_id)
    if job["legacy_unknown"]:
        raise ValueError("Legacy deletion requires reconciliation")
    if job["ledger_complete"]:
        return job
    if job["identity_confirmed_at"] is None:
        if job["provider_result"] != "confirmed":
            with engine.begin() as connection:
                token = connection.scalar(
                    text("SELECT app.ledger_prepare_provider(:operation)"),
                    {"operation": operation_id},
                )
            emit("provider_intent_committed")
            deliver()
            with engine.begin() as connection:
                target = connection.scalar(
                    text("SELECT app.ledger_provider_target(:operation,:token)"),
                    {"operation": operation_id, "token": token},
                )
            # Target and authorization commit precede network. No transaction is open.
            try:
                adapter.delete_and_confirm(target["issuer"], target["subject"])
            except Exception:
                with engine.begin() as connection:
                    connection.execute(
                        text("SELECT app.ledger_provider_result(:operation,:token,'uncertain')"),
                        {"operation": operation_id, "token": token},
                    )
                deliver()
                raise
            emit("provider_confirmed")
            with engine.begin() as connection:
                connection.execute(
                    text("SELECT app.ledger_provider_result(:operation,:token,'confirmed')"),
                    {"operation": operation_id, "token": token},
                )
            emit("provider_result_committed")
            deliver()
        with engine.begin() as connection:
            connection.execute(
                text("SELECT app.confirm_account_deletion(:operation)"), {"operation": operation_id}
            )
        emit("confirmation_committed")
    deliver()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT app.ledger_prepare_purge(:operation)"), {"operation": operation_id}
        )
    emit("purge_intent_committed")
    deliver()
    with engine.begin() as connection:
        connection.execute(
            text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation_id}
        )
    emit("purge_committed")
    deliver()
    with engine.begin() as connection:
        job = status(connection, operation_id)
    if not job["ledger_complete"]:
        raise ValueError("Purge committed locally; durable external ACK pending")
    return job


def public_status(job):
    return {
        key: job[key]
        if key in {"ledger_version", "legacy_unknown", "ledger_complete"}
        else str(job[key])
        if job[key] is not None
        else None
        for key in (
            "operation_id",
            "account_id",
            "expected_generation",
            "deleting_generation",
            "created_at",
            "identity_confirmed_at",
            "block_until",
            "purged_at",
            "ledger_version",
            "legacy_unknown",
            "ledger_complete",
            "provider_result",
        )
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Operator account deletion; no self-service HTTP")
    parser.add_argument("action", choices=("begin", "resume", "status"))
    parser.add_argument("--operation-id", required=True, type=UUID)
    parser.add_argument("--account-id", type=UUID)
    parser.add_argument("--expected-generation", type=int)
    args = parser.parse_args(argv)
    if args.action == "begin" and (args.account_id is None or args.expected_generation is None):
        parser.error("begin requires --account-id and --expected-generation")
    engine = create_engine(os.environ["DELETION_DATABASE_URL"], hide_parameters=True)
    try:
        if args.action == "begin":
            with engine.begin() as connection:
                job = begin(
                    connection, args.account_id, args.operation_id, args.expected_generation
                )
        elif args.action == "status":
            with engine.begin() as connection:
                job = status(connection, args.operation_id)
        else:
            raw = json.loads(Path(os.environ["KEYCLOAK_ADMIN_CONFIG"]).read_text(encoding="utf-8"))
            configurations = [
                RealmAdminConfig(**(entry | {"client_secret": SecretStr(entry["client_secret"])}))
                for entry in raw
            ]
            adapter = KeycloakAdmin(configurations)
            try:
                job = resume(engine, args.operation_id, adapter)
            finally:
                adapter.close()
        print(json.dumps(public_status(job)))
    except AdminFailure as error:
        parser.exit(2, error.code + "\n")
    except Exception:
        # DB diagnostics can contain identity or private row values.
        parser.exit(2, "Deletion failed; inspect privileged diagnostics without exposing data\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
