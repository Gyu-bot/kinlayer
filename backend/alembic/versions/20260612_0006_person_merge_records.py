"""person merge records

Revision ID: 20260612_0006
Revises: 20260612_0005
Create Date: 2026-06-18
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260612_0006"
down_revision: str | None = "20260612_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entity_merges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_entity_id", sa.String(length=36), nullable=False),
        sa.Column("target_entity_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36)),
        sa.Column("merge_plan", postgresql.JSONB(), nullable=False),
        sa.Column("conflict_decisions", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("canonical_record_ref", sa.String(length=120), nullable=False),
        sa.Column("previous_refs", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["target_entity_id"], ["entities.id"]),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"]),
    )
    op.create_index("ix_entity_merges_source_entity_id", "entity_merges", ["source_entity_id"])
    op.create_index("ix_entity_merges_target_entity_id", "entity_merges", ["target_entity_id"])
    op.create_index("ix_entity_merges_candidate_id", "entity_merges", ["candidate_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_merges_candidate_id", table_name="entity_merges")
    op.drop_index("ix_entity_merges_target_entity_id", table_name="entity_merges")
    op.drop_index("ix_entity_merges_source_entity_id", table_name="entity_merges")
    op.drop_table("entity_merges")
