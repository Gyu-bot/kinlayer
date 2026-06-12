"""agent write operation audits

Revision ID: 20260612_0005
Revises: 20260610_0004
Create Date: 2026-06-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260612_0005"
down_revision: str | None = "20260610_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_write_operation_audits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("source_path", sa.String(length=240), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("result_status", sa.String(length=40), nullable=False),
        sa.Column("api_error_code", sa.String(length=80)),
        sa.Column("request_summary", postgresql.JSONB(), nullable=False),
        sa.Column("diagnostics", postgresql.JSONB(), nullable=False),
        sa.Column("related_refs", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_id", sa.String(length=36)),
        sa.Column("correction_id", sa.String(length=36)),
        sa.Column("episode_id", sa.String(length=36)),
        sa.Column("canonical_record_ref", sa.String(length=120)),
        sa.Column("bounded_excerpt", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_write_operation_actor", "agent_write_operation_audits", ["actor"])
    op.create_index(
        "ix_agent_write_operation_operation_type",
        "agent_write_operation_audits",
        ["operation_type"],
    )
    op.create_index(
        "ix_agent_write_operation_result_status",
        "agent_write_operation_audits",
        ["result_status"],
    )
    op.create_index(
        "ix_agent_write_operation_candidate_id",
        "agent_write_operation_audits",
        ["candidate_id"],
    )
    op.create_index(
        "ix_agent_write_operation_created_at",
        "agent_write_operation_audits",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_write_operation_created_at", table_name="agent_write_operation_audits")
    op.drop_index("ix_agent_write_operation_candidate_id", table_name="agent_write_operation_audits")
    op.drop_index("ix_agent_write_operation_result_status", table_name="agent_write_operation_audits")
    op.drop_index("ix_agent_write_operation_operation_type", table_name="agent_write_operation_audits")
    op.drop_index("ix_agent_write_operation_actor", table_name="agent_write_operation_audits")
    op.drop_table("agent_write_operation_audits")
