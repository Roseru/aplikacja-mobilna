"""Privileged, fail-closed restore entry point; never opens traffic or purges data."""

import json
from uuid import UUID

from sqlalchemy import text

from calorie_app.modules.identity.ledger_contract import digest, require, validate_restore


def reconcile_restore(engine, trust, envelopes, *, backup_point, cutoff, fence_pin=None):
    result = validate_restore(
        trust, envelopes, backup_point=backup_point, cutoff=cutoff, fence_pin=fence_pin
    )
    with engine.begin() as connection:
        # Keep account locks before the source mutex, matching live producers.
        # O3 still must physically fence processes/provider credentials first.
        owners = sorted({entry["account_id"] for entry in result["targets"]})
        connection.execute(
            text("SELECT id FROM app.user_accounts WHERE id=ANY(:owners) ORDER BY id FOR UPDATE"),
            {"owners": [UUID(owner) for owner in owners]},
        )
        # Only the trusted restore controller/migrator can access these tables.
        pin = connection.execute(
            text(
                "SELECT installation_id,stream_id,anchor_id,next_sequence-1,head_hash "
                "FROM app.deletion_ledger_source WHERE id=1 FOR UPDATE"
            )
        ).one()
        expected_pin = (trust.installation_id, trust.stream_id, trust.anchor_id)
        require(tuple(str(v) for v in pin[:3]) == expected_pin, "restored_source_mismatch")
        require(
            (pin[3], pin[4]) == (backup_point["sequence"], backup_point["chain_hash"]),
            "backup_snapshot_prefix_conflict",
        )
        connection.execute(text("UPDATE app.deletion_ledger_source SET enabled=false WHERE id=1"))
        for entry in sorted(result["targets"], key=lambda e: e["account_id"]):
            values = {
                k: entry[k]
                for k in (
                    "operation_id",
                    "account_id",
                    "issuer",
                    "subject",
                    "expected_generation",
                    "deleting_generation",
                )
            }
            for key in ("operation_id", "account_id"):
                values[key] = UUID(values[key])
            account = (
                connection.execute(
                    text(
                        "SELECT issuer,subject,generation,state FROM app.user_accounts "
                        "WHERE id=:account_id FOR UPDATE"
                    ),
                    values,
                )
                .mappings()
                .one_or_none()
            )
            if account is not None:
                require(
                    (account["issuer"], account["subject"]) == (entry["issuer"], entry["subject"]),
                    "restore_account_identity_conflict",
                )
                require(
                    (account["generation"], account["state"])
                    in {
                        (entry["expected_generation"], "active"),
                        (entry["deleting_generation"], "deleting"),
                    },
                    "restore_generation_conflict",
                )
            job = (
                connection.execute(
                    text(
                        "SELECT account_id,issuer,subject,expected_generation,deleting_generation "
                        "FROM app.account_deletion_jobs WHERE operation_id=:operation_id FOR UPDATE"
                    ),
                    values,
                )
                .mappings()
                .one_or_none()
            )
            if job is not None:
                require(all(job[k] == values[k] for k in job), "restore_job_conflict")
            connection.execute(
                text(
                    "INSERT INTO app._ledger_account_context "
                    "VALUES(txid_current(),:account_id,:operation_id)"
                ),
                values,
            )
            if job is None:
                connection.execute(
                    text(
                        "INSERT INTO app.account_deletion_jobs(operation_id,account_id,issuer,"
                        "subject,expected_generation,deleting_generation) VALUES(:operation_id,"
                        ":account_id,:issuer,:subject,:expected_generation,:deleting_generation)"
                    ),
                    values,
                )
            connection.execute(
                text(
                    "INSERT INTO app.deleted_subjects(issuer,subject,operation_id) "
                    "VALUES(:issuer,:subject,:operation_id) ON CONFLICT(issuer,subject) DO NOTHING"
                ),
                values,
            )
            block = connection.scalar(
                text(
                    "SELECT operation_id FROM app.deleted_subjects "
                    "WHERE issuer=:issuer AND subject=:subject"
                ),
                values,
            )
            require(block == values["operation_id"], "restore_subject_fence_conflict")
            if account is not None and account["state"] == "active":
                connection.execute(
                    text(
                        "UPDATE app.user_accounts SET state='deleting',"
                        "generation=:deleting_generation "
                        "WHERE id=:account_id"
                    ),
                    values,
                )
            connection.execute(
                text("DELETE FROM app._ledger_account_context WHERE transaction_id=txid_current()")
            )
        receipt = json.dumps(
            {"backup_point": backup_point, "cutoff": cutoff, "fence_pin": fence_pin.fields()},
            sort_keys=True,
        )
        connection.execute(
            text(
                "INSERT INTO app.deletion_ledger_restore_receipts(receipt_hash,receipt) "
                "VALUES(:hash,CAST(:receipt AS jsonb)) ON CONFLICT(receipt_hash) DO NOTHING"
            ),
            {"hash": digest(receipt.encode()), "receipt": receipt},
        )
    return result
