"""Restore a real older PostgreSQL database copy before reopening application traffic."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from test_e4_push import SECRET, operation, request, send
from test_e4_push import synced as _synced_fixture

from calorie_app.modules.identity.service import current_epoch
from calorie_app.modules.sync.errors import SyncFailure
from calorie_app.modules.sync.router import execute_one
from calorie_app.modules.sync.snapshots import pull

pytestmark = pytest.mark.integration
synced = _synced_fixture


def test_restore_older_real_database_retains_receipts_and_requires_conscious_recovery(synced):
    engine, factory, _, owner, boot, cp, url = synced
    first = operation(boot)
    send(synced, [first])
    suffix = uuid4().hex[:12]
    backup_name, restored_name = f"e4_backup_{suffix}_test", f"e4_restore_{suffix}_test"
    source_url = make_url(url)
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    # A template copy is an actual PG physical database snapshot, including the
    # full application graph and receipts. No phones or source DB are reset.
    engine.dispose()
    with admin.connect() as connection:
        connection.exec_driver_sql(
            f'CREATE DATABASE "{backup_name}" TEMPLATE "{source_url.database}"'
        )
    lost = operation(boot)
    send(synced, [lost])
    newer = operation(
        boot, entity_id=first["entity_id"], base=1, payload=first["payload"] | {"weight_kg": "91"}
    )
    send(synced, [newer])
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{restored_name}" TEMPLATE "{backup_name}"')
    restored = create_engine(source_url.set(database=restored_name))
    restored_factory = sessionmaker(restored, expire_on_commit=False)
    try:
        epoch = uuid4()
        # Traffic stays closed until the new epoch is committed.
        with restored.begin() as connection:
            connection.execute(
                text("UPDATE app.installation_state SET sync_epoch=:e WHERE id=1"), {"e": epoch}
            )
        page = pull(
            restored_factory,
            owner,
            {
                "recovery_operation_ids": [
                    first["operation_id"],
                    lost["operation_id"],
                    newer["operation_id"],
                ]
            },
            SECRET,
        )
        assert page["sync_epoch"] == str(epoch)
        assert {r["operation_id"] for r in page["operation_receipts"]} == {first["operation_id"]}
        assert lost["entity_id"] not in {e["entity_id"] for e in page["entities"]}
        stale = request(boot, page["checkpoint"], [lost])
        with pytest.raises(SyncFailure) as caught:
            execute_one(restored_factory, owner, 1, stale, lost, SECRET)
        assert caught.value.code == "sync_epoch_changed"
        current_boot = boot | {"sync_epoch": str(epoch)}
        divergence = operation(
            current_boot,
            entity_id=first["entity_id"],
            base=1,
            payload=first["payload"] | {"weight_kg": "92"},
        )
        data = request(current_boot, page["checkpoint"], [divergence])
        assert execute_one(restored_factory, owner, 1, data, divergence, SECRET)[0]["revision"] == 2
        # Equal revisions across epochs have different contents.
        page2 = pull(restored_factory, owner, {}, SECRET)
        entity = next(e for e in page2["entities"] if e["entity_id"] == first["entity_id"])
        assert (
            entity["revision"] == 2
            and entity["payload"]["weight_kg"] != newer["payload"]["weight_kg"]
        )
        recovery = operation(current_boot, payload=lost["payload"])
        recovery["recovery"] = {
            "source_epoch": boot["sync_epoch"],
            "source_entity_id": lost["entity_id"],
            "source_revision": 1,
            "source_operation_id": lost["operation_id"],
            "decision": "recreate_missing",
        }
        data = request(current_boot, page2["checkpoint"], [recovery])
        result = execute_one(restored_factory, owner, 1, data, recovery, SECRET)[0]
        assert result["status"] == "accepted"
        assert result["recovery_mapping"]["target_entity_id"] != lost["entity_id"]
        with Session(restored) as session:
            assert current_epoch(session) == epoch
    finally:
        restored.dispose()
        with admin.connect() as connection:
            for name in (restored_name, backup_name):
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()
