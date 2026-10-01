"""Bound explicit material imports to episodes; preserve historical data.

Revision ID: 20260930_0011
Revises: 20260826_0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260930_0011"
down_revision = "20260826_0010"
branch_labels = None
depends_on = None


def upgrade():
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "material_imports",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("request_sha256", sa.String(71), nullable=False, unique=True),
        sa.Column("manifest", json_type, nullable=False),
        sa.Column("candidate_links", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("episodes") as batch:
        batch.add_column(sa.Column("material_import_id", sa.String(120), nullable=True))
        batch.create_foreign_key(
            "fk_episodes_material_import_id", "material_imports", ["material_import_id"], ["id"]
        )


def downgrade():
    # Do not silently strip provenance from imported canonical/candidate evidence.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM material_imports")).scalar():
        raise RuntimeError("Export and explicitly retire imported evidence before downgrade.")
    with op.batch_alter_table("episodes") as batch:
        batch.drop_constraint("fk_episodes_material_import_id", type_="foreignkey")
        batch.drop_column("material_import_id")
    op.drop_table("material_imports")
