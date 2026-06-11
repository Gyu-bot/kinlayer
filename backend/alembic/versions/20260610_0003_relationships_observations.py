"""relationships observations and evidence

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260610_0003"
down_revision: str | None = "20260610_0002"
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
    seeds = {
        "edge_type": [
            "knows",
            "friend",
            "family",
            "acquaintance",
            "coworker",
            "former_coworker",
            "client_contact",
            "vendor_contact",
            "reports_to",
            "manager_of",
            "introduced_by",
            "referred_by",
            "collaborated_with",
            "dating_interest",
            "dating",
            "former_dating",
            "romantic_partner",
            "former_partner",
            "introduced_for_dating",
            "matched_on_app",
        ],
        "observation_type": [
            "stable_fact",
            "communication_preference",
            "relationship_pattern",
            "care_point",
            "caution",
            "recent_interaction",
            "user_feeling",
            "follow_up_context",
        ],
        "retention_policy": ["excerpt_only", "metadata_only"],
        "evidence_source_type": [
            "agent_conversation",
            "manual_entry",
            "import",
            "connector",
            "correction",
        ],
    }
    rows = []
    counter = 300
    for category, values in seeds.items():
        for sort_order, value in enumerate(values):
            rows.append(
                {
                    "id": f"seed-{counter:03d}",
                    "category": category,
                    "value": value,
                    "label": value.replace("_", " ").title(),
                    "description": None,
                    "support_level": "supported",
                    "is_active": True,
                    "sort_order": sort_order,
                }
            )
            counter += 1
    return rows


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.execute("create extension if not exists pg_trgm")

    op.create_table(
        "allowed_edge_types",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("relation_type", sa.String(length=120), nullable=False),
        sa.Column("from_entity_type", sa.String(length=80), nullable=False),
        sa.Column("to_entity_type", sa.String(length=80), nullable=False),
        sa.Column("directed_default", sa.Boolean(), nullable=False),
        sa.Column("inverse_relation_type", sa.String(length=120)),
        sa.Column("allowed_properties_schema", postgresql.JSONB()),
        sa.Column("description", sa.Text()),
        sa.Column("examples", postgresql.JSONB()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("relation_type", name="uq_allowed_edge_types_relation_type"),
    )

    op.create_table(
        "allowed_observation_types",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("observation_type", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("examples", postgresql.JSONB()),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("observation_type", name="uq_allowed_observation_types_type"),
    )

    op.create_table(
        "episodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("source_ref", sa.String(length=500)),
        sa.Column("source_description", sa.Text()),
        sa.Column("body_excerpt", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.String(length=120), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("retention_policy", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_episodes_source_type", "episodes", ["source_type"])
    op.create_index("ix_episodes_actor", "episodes", ["actor"])

    op.create_table(
        "entity_edges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("from_entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("to_entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("relation_type", sa.String(length=120), nullable=False),
        sa.Column("directed", sa.Boolean(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=60), nullable=False),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("ai_use_policy", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("invalidated_by_edge_id", sa.String(length=36), sa.ForeignKey("entity_edges.id")),
        sa.Column("source_candidate_id", sa.String(length=36)),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_edges_from_entity_id", "entity_edges", ["from_entity_id"])
    op.create_index("ix_entity_edges_to_entity_id", "entity_edges", ["to_entity_id"])
    op.create_index("ix_entity_edges_relation_type", "entity_edges", ["relation_type"])
    op.create_index("ix_entity_edges_status", "entity_edges", ["status"])

    op.create_table(
        "observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject_entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("observation_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("ai_use_policy", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("recency_weight", sa.Numeric(4, 3)),
        sa.Column("embedding", sa.Text()),
        sa.Column("embedding_status", sa.String(length=40), nullable=False),
        sa.Column("embedding_error", sa.Text()),
        sa.Column("embedding_model", sa.String(length=240)),
        sa.Column("embedding_dim", sa.Integer()),
        sa.Column("embedding_created_at", sa.DateTime(timezone=True)),
        sa.Column("source_candidate_id", sa.String(length=36)),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "alter table observations alter column embedding type vector "
        "using embedding::vector"
    )
    op.create_index("ix_observations_subject_entity_id", "observations", ["subject_entity_id"])
    op.create_index("ix_observations_observation_type", "observations", ["observation_type"])
    op.create_index("ix_observations_status", "observations", ["status"])
    op.create_index("ix_observations_claim_type", "observations", ["claim_type"])

    op.create_table(
        "observation_entities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("observation_id", sa.String(length=36), sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_observation_entities_observation_id", "observation_entities", ["observation_id"])
    op.create_index("ix_observation_entities_entity_id", "observation_entities", ["entity_id"])

    op.create_table(
        "entity_fact_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_fact_id", sa.String(length=36), sa.ForeignKey("entity_facts.id"), nullable=False),
        sa.Column("episode_id", sa.String(length=36), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("excerpt", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_fact_evidence_fact_id", "entity_fact_evidence", ["entity_fact_id"])
    op.create_index("ix_entity_fact_evidence_episode_id", "entity_fact_evidence", ["episode_id"])

    op.create_table(
        "edge_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("edge_id", sa.String(length=36), sa.ForeignKey("entity_edges.id"), nullable=False),
        sa.Column("episode_id", sa.String(length=36), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("excerpt", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edge_evidence_edge_id", "edge_evidence", ["edge_id"])
    op.create_index("ix_edge_evidence_episode_id", "edge_evidence", ["episode_id"])

    op.create_table(
        "observation_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("observation_id", sa.String(length=36), sa.ForeignKey("observations.id"), nullable=False),
        sa.Column("episode_id", sa.String(length=36), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("excerpt", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_observation_evidence_observation_id", "observation_evidence", ["observation_id"])
    op.create_index("ix_observation_evidence_episode_id", "observation_evidence", ["episode_id"])

    op.bulk_insert(registry, _registry_rows())
    op.bulk_insert(
        sa.table(
            "allowed_edge_types",
            sa.column("id", sa.String),
            sa.column("relation_type", sa.String),
            sa.column("from_entity_type", sa.String),
            sa.column("to_entity_type", sa.String),
            sa.column("directed_default", sa.Boolean),
            sa.column("inverse_relation_type", sa.String),
            sa.column("allowed_properties_schema", postgresql.JSONB),
            sa.column("description", sa.Text),
            sa.column("examples", postgresql.JSONB),
            sa.column("active", sa.Boolean),
        ),
        [
            {
                "id": f"edge-{index:03d}",
                "relation_type": row["value"],
                "from_entity_type": "person",
                "to_entity_type": "person",
                "directed_default": row["value"]
                in {
                    "reports_to",
                    "manager_of",
                    "introduced_by",
                    "referred_by",
                    "introduced_for_dating",
                },
                "inverse_relation_type": None,
                "allowed_properties_schema": {},
                "description": row["label"],
                "examples": [],
                "active": True,
            }
            for index, row in enumerate(_registry_rows())
            if row["category"] == "edge_type"
        ],
    )
    op.bulk_insert(
        sa.table(
            "allowed_observation_types",
            sa.column("id", sa.String),
            sa.column("observation_type", sa.String),
            sa.column("description", sa.Text),
            sa.column("examples", postgresql.JSONB),
            sa.column("active", sa.Boolean),
        ),
        [
            {
                "id": f"obs-{index:03d}",
                "observation_type": row["value"],
                "description": row["label"],
                "examples": [],
                "active": True,
            }
            for index, row in enumerate(_registry_rows())
            if row["category"] == "observation_type"
        ],
    )


def downgrade() -> None:
    for index, table in [
        ("ix_observation_evidence_episode_id", "observation_evidence"),
        ("ix_observation_evidence_observation_id", "observation_evidence"),
        ("ix_edge_evidence_episode_id", "edge_evidence"),
        ("ix_edge_evidence_edge_id", "edge_evidence"),
        ("ix_entity_fact_evidence_episode_id", "entity_fact_evidence"),
        ("ix_entity_fact_evidence_fact_id", "entity_fact_evidence"),
        ("ix_observation_entities_entity_id", "observation_entities"),
        ("ix_observation_entities_observation_id", "observation_entities"),
        ("ix_observations_claim_type", "observations"),
        ("ix_observations_status", "observations"),
        ("ix_observations_observation_type", "observations"),
        ("ix_observations_subject_entity_id", "observations"),
        ("ix_entity_edges_status", "entity_edges"),
        ("ix_entity_edges_relation_type", "entity_edges"),
        ("ix_entity_edges_to_entity_id", "entity_edges"),
        ("ix_entity_edges_from_entity_id", "entity_edges"),
        ("ix_episodes_actor", "episodes"),
        ("ix_episodes_source_type", "episodes"),
    ]:
        op.drop_index(index, table_name=table)
    for table in [
        "observation_evidence",
        "edge_evidence",
        "entity_fact_evidence",
        "observation_entities",
        "observations",
        "entity_edges",
        "episodes",
        "allowed_observation_types",
        "allowed_edge_types",
    ]:
        op.drop_table(table)
