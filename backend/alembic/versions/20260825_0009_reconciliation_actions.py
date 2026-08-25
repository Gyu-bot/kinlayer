"""durable reconciliation action ledger

Revision ID: 20260825_0009
Revises: 20260825_0008
Create Date: 2026-08-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0009"
down_revision: str | None = "20260825_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.add_column(
        "curation_decisions",
        sa.Column(
            "expected_candidates",
            JSON_TYPE,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.create_table(
        "reconciliation_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resolution_id", sa.String(120), nullable=False),
        sa.Column("action_type", sa.String(60), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("request_fingerprint", sa.String(71), nullable=False),
        sa.Column("candidate_ids", JSON_TYPE, nullable=False),
        sa.Column("expected_candidates", JSON_TYPE, nullable=False),
        sa.Column("expected_entities", JSON_TYPE, nullable=False),
        sa.Column("source_entity_id", sa.String(36), sa.ForeignKey("entities.id")),
        sa.Column("target_entity_id", sa.String(36), sa.ForeignKey("entities.id")),
        sa.Column("primary_entity_id", sa.String(36), sa.ForeignKey("entities.id")),
        sa.Column("derived_candidate_ids", JSON_TYPE, nullable=False),
        sa.Column("confirmation_episode_id", sa.String(36), sa.ForeignKey("episodes.id")),
        sa.Column("outcome_canonical_refs", JSON_TYPE, nullable=False),
        sa.Column("readback_summary", JSON_TYPE),
        sa.Column("error_code", sa.String(80)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'committed_unverified', 'verified', 'verification_failed')",
            name="ck_reconciliation_actions_status",
        ),
        sa.UniqueConstraint("resolution_id", name="uq_reconciliation_actions_resolution_id"),
    )
    op.create_index("ix_reconciliation_actions_status", "reconciliation_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_reconciliation_actions_status", table_name="reconciliation_actions")
    op.drop_table("reconciliation_actions")
    op.drop_column("curation_decisions", "expected_candidates")
