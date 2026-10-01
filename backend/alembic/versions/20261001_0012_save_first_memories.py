"""Add independent evidence basis and atomic memory change receipts.

Revision ID: 20261001_0012
Revises: 20260930_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0012"
down_revision = "20260930_0011"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("entity_facts", "entity_edges", "observations"):
        op.add_column(
            table,
            sa.Column("claim_basis", sa.String(40), nullable=False, server_default="unknown"),
        )
        # Only the unambiguous old inference label maps automatically. 'Fact'
        # does not establish who reported it, nor whether it was verified.
        op.execute(sa.text(f"UPDATE {table} SET claim_basis='inferred' WHERE claim_type='inference'"))
    op.create_table(
        "memory_changes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(160), nullable=False),
        sa.Column("request_sha256", sa.String(71), nullable=False),
        sa.Column("change_kind", sa.String(40), nullable=False),
        sa.Column("old_record_ref", sa.String(120)),
        sa.Column("new_record_ref", sa.String(120)),
        sa.Column("source_episode_id", sa.String(36), sa.ForeignKey("episodes.id")),
        sa.Column("actor", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_memory_changes_request_id"),
        sa.CheckConstraint(
            "change_kind IN ('create', 'correct', 'retract', 'reattribute', 'migrate')",
            name="ck_memory_changes_kind",
        ),
    )
    op.create_index("ix_memory_changes_old_record_ref", "memory_changes", ["old_record_ref"])
    op.create_index("ix_memory_changes_new_record_ref", "memory_changes", ["new_record_ref"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT count(*) FROM memory_changes")).scalar():
        raise RuntimeError("Restore the pre-migration backup to preserve memory change history.")
    op.drop_table("memory_changes")
    for table in ("observations", "entity_edges", "entity_facts"):
        op.drop_column(table, "claim_basis")
