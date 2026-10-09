"""Initial account and catalog skeleton; later stages extend this schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("issuer", sa.String(2048), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("issuer", "subject", name="uq_user_accounts_issuer"),
        sa.CheckConstraint("generation >= 1", name="positive_generation"),
        sa.CheckConstraint("state IN ('active', 'deleting')", name="account_state"),
        schema="app",
    )
    op.create_table(
        "product_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint("status IN ('unverified', 'verified')", name="source_status"),
        schema="app",
    )
    op.create_table("products", sa.Column("id", sa.Uuid(), primary_key=True), schema="app")
    op.create_table(
        "product_versions",
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("app.products.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("app.product_sources.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("basis_unit", sa.String(2), nullable=False),
        *[
            sa.Column(name, sa.Numeric(12, 6), nullable=True)
            for name in ("energy_kcal", "protein_g", "fat_g", "carbs_g")
        ],
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint("basis_unit IN ('g', 'ml')", name="basis_unit"),
        sa.CheckConstraint(
            "energy_kcal >= 0 AND protein_g >= 0 AND fat_g >= 0 AND carbs_g >= 0",
            name="nonnegative_nutrition",
        ),
        schema="app",
    )


def downgrade():
    # For a disposable test DB only. Production rollback requires a backup plan.
    for name in ("product_versions", "products", "product_sources", "user_accounts"):
        op.drop_table(name, schema="app")
