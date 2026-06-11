"""candidate schema and evidence

Revision ID: 20260610_0004
Revises: 20260610_0003
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260610_0004"
down_revision: str | None = "20260610_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

registry = sa.table(
    "ontology_registry_values",
    sa.column("id", sa.String),
    sa.column("category", sa.String),
    sa.column("value", sa.String),
    sa.column("label", sa.String),
    sa.column("description", sa.Text),
    sa.column("support_level", sa.String),
    sa.column("is_active", sa.Boolean),
    sa.column("sort_order", sa.Integer),
)


def _registry_rows() -> list[dict]:
    values = [
        "new_entity",
        "alias",
        "profile_field",
        "relationship_edge",
        "observation",
        "merge",
        "conflict",
        "supersede",
    ]
    return [
        {
            "id": f"seed-500-{sort_order:02d}",
            "category": "candidate_type",
            "value": value,
            "label": value.replace("_", " ").title(),
            "description": None,
            "support_level": "supported",
            "is_active": True,
            "sort_order": sort_order,
        }
        for sort_order, value in enumerate(values)
    ]


def upgrade() -> None:
    op.create_table(
        "candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("candidate_type", sa.String(length=80), nullable=False),
        sa.Column("target_entity_id", sa.String(length=36), sa.ForeignKey("entities.id")),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("sensitivity", sa.String(length=40), nullable=False, server_default="medium"),
        sa.Column("suggested_action", sa.String(length=80)),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(length=60)),
        sa.Column("resolution_note", sa.Text()),
        sa.Column("canonical_record_ref", sa.String(length=120)),
        sa.Column(
            "supersedes_candidate_id",
            sa.String(length=36),
            sa.ForeignKey("candidates.id"),
        ),
        sa.Column("supersedes_record_ref", sa.String(length=120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_candidates_candidate_type", "candidates", ["candidate_type"])
    op.create_index("ix_candidates_status", "candidates", ["status"])
    op.create_index("ix_candidates_target_entity_id", "candidates", ["target_entity_id"])

    op.create_table(
        "candidate_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(length=36),
            sa.ForeignKey("candidates.id"),
            nullable=False,
        ),
        sa.Column("episode_id", sa.String(length=36), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("excerpt", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_candidate_evidence_candidate_id", "candidate_evidence", ["candidate_id"])
    op.create_index("ix_candidate_evidence_episode_id", "candidate_evidence", ["episode_id"])
    op.bulk_insert(registry, _registry_rows())


def downgrade() -> None:
    op.execute("delete from ontology_registry_values where category = 'candidate_type'")
    op.drop_index("ix_candidate_evidence_episode_id", table_name="candidate_evidence")
    op.drop_index("ix_candidate_evidence_candidate_id", table_name="candidate_evidence")
    op.drop_table("candidate_evidence")
    op.drop_index("ix_candidates_target_entity_id", table_name="candidates")
    op.drop_index("ix_candidates_status", table_name="candidates")
    op.drop_index("ix_candidates_candidate_type", table_name="candidates")
    op.drop_table("candidates")
