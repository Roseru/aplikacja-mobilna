"""Reject special nutrition values while preserving existing data and NULLs."""

from alembic import op

revision = "0002_finite_nutrition"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade():
    # Validate all existing rows before replacing the old CHECK. A validation
    # failure rolls back the migration, including its schema and revision changes.
    op.create_check_constraint(
        op.f("ck_product_versions_finite_nutrition"),
        "product_versions",
        "(energy_kcal IS NULL OR (energy_kcal >= 0 AND energy_kcal <= 999999.999999)) "
        "AND (protein_g IS NULL OR (protein_g >= 0 AND protein_g <= 999999.999999)) "
        "AND (fat_g IS NULL OR (fat_g >= 0 AND fat_g <= 999999.999999)) "
        "AND (carbs_g IS NULL OR (carbs_g >= 0 AND carbs_g <= 999999.999999))",
        schema="app",
    )
    op.drop_constraint(
        op.f("ck_product_versions_nonnegative_nutrition"),
        "product_versions",
        schema="app",
        type_="check",
    )


def downgrade():
    op.create_check_constraint(
        op.f("ck_product_versions_nonnegative_nutrition"),
        "product_versions",
        "energy_kcal >= 0 AND protein_g >= 0 AND fat_g >= 0 AND carbs_g >= 0",
        schema="app",
    )
    op.drop_constraint(
        op.f("ck_product_versions_finite_nutrition"),
        "product_versions",
        schema="app",
        type_="check",
    )
