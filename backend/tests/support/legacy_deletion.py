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
    result = (
        connection.execute(
            text("SELECT * FROM app.account_deletion_jobs WHERE operation_id=:operation"),
            {"operation": operation_id},
        )
        .mappings()
        .one_or_none()
    )
    if result is None:
        raise ValueError("Unknown deletion operation")
    return dict(result)


def begin(connection, account_id: UUID, operation_id: UUID, expected_generation: int) -> dict:
    connection.execute(
        text("SELECT app.begin_account_deletion(:owner,:operation,:generation)"),
        {"owner": account_id, "operation": operation_id, "generation": expected_generation},
    )
    return status(connection, operation_id)


def resume(engine, operation_id: UUID, adapter, *, barrier=None) -> dict:
    # Reading/committing the target is separate from its provider call; the
    # subject and realm are durable, immutable job attributes, not CLI input.
    with engine.begin() as connection:
        job = status(connection, operation_id)
    if job["purged_at"] is not None:
        return job
    if job["identity_confirmed_at"] is None:
        adapter.delete_and_confirm(job["issuer"], job["subject"])
        if barrier:
            barrier("provider_confirmed")
        with engine.begin() as connection:
            connection.execute(
                text("SELECT app.confirm_account_deletion(:operation)"),
                {"operation": operation_id},
            )
        if barrier:
            barrier("confirmation_committed")
    with engine.begin() as connection:
        connection.execute(
            text("SELECT app.purge_deleted_account(:operation)"), {"operation": operation_id}
        )
    if barrier:
        barrier("purge_committed")
    with engine.begin() as connection:
        return status(connection, operation_id)


def public_status(job):
    return {
        key: str(job[key]) if job[key] is not None else None
        for key in (
            "operation_id",
            "account_id",
            "expected_generation",
            "deleting_generation",
            "created_at",
            "identity_confirmed_at",
            "block_until",
            "purged_at",
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
