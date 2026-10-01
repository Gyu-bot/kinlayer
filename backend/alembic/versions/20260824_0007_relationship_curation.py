"""durable relationship curation runs and decisions

Revision ID: 20260824_0007
Revises: 20260612_0006
Create Date: 2026-08-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0007"
down_revision: str | None = "20260612_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "curation_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mode", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("cursor_started_at", sa.DateTime(timezone=True)),
        sa.Column("cursor_started_id", sa.String(length=36)),
        sa.Column("cursor_completed_at", sa.DateTime(timezone=True)),
        sa.Column("cursor_completed_id", sa.String(length=36)),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("planner_name", sa.String(length=160)),
        sa.Column("planner_model", sa.String(length=240)),
        sa.Column("planner_version", sa.String(length=120)),
        sa.Column("input_candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_decision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_decision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_decision_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80)),
        sa.Column("diagnostics", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "mode in ('disabled', 'shadow', 'apply')",
            name="ck_curation_runs_mode",
        ),
        sa.CheckConstraint(
            "status in ('pending', 'planning', 'ready', 'executing', "
            "'completed', 'partial', 'failed')",
            name="ck_curation_runs_status",
        ),
        sa.CheckConstraint(
            "(cursor_started_at is null) = (cursor_started_id is null)",
            name="ck_curation_runs_started_cursor_pair",
        ),
        sa.CheckConstraint(
            "(cursor_completed_at is null) = (cursor_completed_id is null)",
            name="ck_curation_runs_completed_cursor_pair",
        ),
        sa.CheckConstraint(
            "cursor_completed_at is null or cursor_started_at is not null",
            name="ck_curation_runs_completed_cursor_requires_started",
        ),
        sa.CheckConstraint(
            "cursor_completed_at is null or cursor_completed_at > cursor_started_at or "
            "(cursor_completed_at = cursor_started_at and cursor_completed_id >= cursor_started_id)",
            name="ck_curation_runs_cursor_order",
        ),
        sa.CheckConstraint(
            "input_candidate_count >= 0 and planned_decision_count >= 0 and "
            "executed_decision_count >= 0 and blocked_decision_count >= 0",
            name="ck_curation_runs_nonnegative_counts",
        ),
    )
    op.create_index("ix_curation_runs_status", "curation_runs", ["status"])

    op.create_table(
        "curation_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("curation_runs.id"), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="proposed"),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("candidate_ids", JSON_TYPE, nullable=False, server_default="[]"),
        sa.Column("target_entity_id", sa.String(length=36), sa.ForeignKey("entities.id")),
        sa.Column("proposed_payload", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("evidence_episode_ids", JSON_TYPE, nullable=False, server_default="[]"),
        sa.Column("reason_codes", JSON_TYPE, nullable=False, server_default="[]"),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("canonical_record_ref", sa.String(length=120)),
        sa.Column("readback_status", sa.String(length=60)),
        sa.Column("readback_summary", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("api_error_code", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "action in ('accept_existing', 'edit_accept_existing', 'consolidate_accept', "
            "'archive_exact_duplicate', 'mark_needs_clarification', 'defer', "
            "'recommend_merge_review', 'recommend_conflict_review')",
            name="ck_curation_decisions_action",
        ),
        sa.CheckConstraint(
            "status in ('proposed', 'allowed', 'blocked', 'executing', 'executed', 'failed')",
            name="ck_curation_decisions_status",
        ),
        sa.CheckConstraint(
            "risk_level in ('low', 'medium', 'high')",
            name="ck_curation_decisions_risk_level",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_curation_decisions_idempotency_key"),
    )
    op.create_index("ix_curation_decisions_run_id", "curation_decisions", ["run_id"])
    op.create_index("ix_curation_decisions_status", "curation_decisions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_curation_decisions_status", table_name="curation_decisions")
    op.drop_index("ix_curation_decisions_run_id", table_name="curation_decisions")
    op.drop_table("curation_decisions")
    op.drop_index("ix_curation_runs_status", table_name="curation_runs")
    op.drop_table("curation_runs")
