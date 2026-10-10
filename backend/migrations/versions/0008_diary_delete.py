"""Keep diary parents as tombstones and serialize item DELETE with account blocking."""

from alembic import op

revision = "0008_diary_delete"
down_revision = "0007_e3_diary"
branch_labels = None
depends_on = None


def upgrade():
    # These aggregates are removed by UPDATE/tombstones. Physical deletion is
    # reserved for a future, explicitly controlled account-removal protocol.
    for table in ("diary_days", "meals", "weights", "product_drafts"):
        op.execute(f"REVOKE DELETE ON app.{table} FROM PUBLIC, calorie_app_api, calorie_app_worker")

    # Only the item replacement path needs DELETE. The parent/account locks are
    # held until the caller's transaction ends; OLD is the sole row for DELETE.
    op.execute("""
    CREATE OR REPLACE FUNCTION app.diary_item_delete_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
    DECLARE account_state text; parent_deleted_at timestamptz;
    BEGIN
        SELECT state INTO account_state FROM app.user_accounts
            WHERE id=OLD.owner_id FOR UPDATE;
        IF NOT FOUND OR account_state <> 'active' THEN
            RAISE EXCEPTION 'item delete requires an active account' USING ERRCODE='23514';
        END IF;
        SELECT deleted_at INTO parent_deleted_at FROM app.meals
            WHERE owner_id=OLD.owner_id AND id=OLD.meal_id FOR UPDATE;
        IF NOT FOUND OR parent_deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'item delete requires a live meal snapshot' USING ERRCODE='23514';
        END IF;
        RETURN OLD;
    END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION app.diary_item_delete_guard() FROM PUBLIC")
    # PostgreSQL runs BEFORE triggers alphabetically. The account lock therefore
    # precedes diary_item_lock's aggregate lock, including direct runtime SQL.
    # IF EXISTS also permits re-upgrade after the security-preserving downgrade.
    op.execute("DROP TRIGGER IF EXISTS diary_delete_account ON app.meal_items")
    op.execute(
        "CREATE TRIGGER diary_delete_account BEFORE DELETE ON app.meal_items "
        "FOR EACH ROW EXECUTE FUNCTION app.diary_item_delete_guard()"
    )


def downgrade():
    # No schema/data rewrite is required to run the previous compatible image.
    # Keep both the ACL and DELETE trigger even when Alembic records revision 7.
    # Older diary-schema removal drops the trigger with its table; re-upgrade
    # replaces the helper safely. Do not silently reopen the vulnerable grants.
    op.get_context().config.print_stdout(
        "WARNING: Diary DELETE security protection is retained on downgrade; "
        "runtime privileges are not widened."
    )
