"""Durable operation evidence and per-account commit ordering after E3."""

from alembic import op

revision = "0009_e4_sync"
down_revision = "0008_diary_delete"
branch_labels = None
depends_on = None


def upgrade():
    from calorie_app.modules.sync.models import (
        RecoveryMapping,
        SyncChange,
        SyncCounter,
        SyncReceipt,
        SyncReservation,
    )

    for model in (SyncCounter, SyncReceipt, SyncChange, SyncReservation, RecoveryMapping):
        model.__table__.create(op.get_bind(), checkfirst=True)
        table = model.__tablename__
        op.execute(f"REVOKE ALL ON app.{table} FROM PUBLIC, calorie_app_api, calorie_app_worker")
        op.execute(f"GRANT SELECT, INSERT ON app.{table} TO calorie_app_api, calorie_app_worker")
    op.execute("GRANT UPDATE ON app.sync_counters TO calorie_app_api, calorie_app_worker")
    op.execute(
        "INSERT INTO app.sync_counters(owner_id) SELECT id FROM app.user_accounts "
        "ON CONFLICT DO NOTHING"
    )


def downgrade():
    # Published evidence cannot be removed to run an old image.
    op.get_context().config.print_stdout(
        "WARNING: E4 synchronization tables and evidence retained on downgrade."
    )
