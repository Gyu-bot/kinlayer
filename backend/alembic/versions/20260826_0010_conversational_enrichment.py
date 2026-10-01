"""closed conversational enrichment ledgers

Revision ID: 20260826_0010
Revises: 20260825_0009
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0010"
down_revision: str | None = "20260825_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "enrichment_authorizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("authorization_ref", sa.String(120), nullable=False),
        sa.Column("stage_idempotency_key", sa.String(120), nullable=False),
        sa.Column("stage_fingerprint", sa.String(71), nullable=False),
        sa.Column("topic", sa.String(80), nullable=False),
        sa.Column("subject_entity_id", sa.String(36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("entity_snapshots", JSON_TYPE, nullable=False),
        sa.Column("slots", JSON_TYPE, nullable=False),
        sa.Column("slot_states", JSON_TYPE, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('open', 'partially_answered', 'completed', 'expired', 'cancelled')",
            name="ck_enrichment_authorizations_status",
        ),
        sa.UniqueConstraint("authorization_ref", name="uq_enrichment_authorizations_ref"),
        sa.UniqueConstraint("stage_idempotency_key", name="uq_enrichment_authorizations_stage_key"),
    )
    op.create_index("ix_enrichment_authorizations_status", "enrichment_authorizations", ["status"])
    op.create_table(
        "enrichment_answer_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resolution_id", sa.String(120), nullable=False),
        sa.Column(
            "authorization_id",
            sa.String(36),
            sa.ForeignKey("enrichment_authorizations.id"),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.String(71), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("slot_outcomes", JSON_TYPE, nullable=False),
        sa.Column("derived_candidate_ids", JSON_TYPE, nullable=False),
        sa.Column("episode_id", sa.String(36), sa.ForeignKey("episodes.id")),
        sa.Column("canonical_refs", JSON_TYPE, nullable=False),
        sa.Column("source_snapshot", JSON_TYPE),
        sa.Column("readback_summary", JSON_TYPE),
        sa.Column("error_code", sa.String(80)),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending', 'committed_unverified', 'verified', 'verification_failed')",
            name="ck_enrichment_answer_actions_status",
        ),
        sa.UniqueConstraint("resolution_id", name="uq_enrichment_answer_actions_resolution_id"),
    )
    op.create_index("ix_enrichment_answer_actions_status", "enrichment_answer_actions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_enrichment_answer_actions_status", table_name="enrichment_answer_actions")
    op.drop_table("enrichment_answer_actions")
    op.drop_index("ix_enrichment_authorizations_status", table_name="enrichment_authorizations")
    op.drop_table("enrichment_authorizations")
