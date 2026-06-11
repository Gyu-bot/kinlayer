"""core entity bootstrap

Revision ID: 20260610_0002
Revises: 20260610_0001
Create Date: 2026-06-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260610_0002"
down_revision: str | None = "20260610_0001"
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


def _seed_rows() -> list[dict]:
    seeds = {
        "entity_type": [
            ("person", "Person", "supported"),
            ("organization", "Organization", "reserved"),
            ("place", "Place", "reserved"),
            ("event", "Event", "reserved"),
            ("topic", "Topic", "reserved"),
            ("account", "Account", "reserved"),
        ],
        "fact_type": [
            ("role", "Role", "supported"),
            ("job", "Job", "supported"),
            ("organization", "Organization", "supported"),
            ("birthday", "Birthday", "supported"),
            ("contact_note", "Contact note", "supported"),
            ("relationship_note", "Relationship note", "supported"),
            ("important_context", "Important context", "supported"),
            ("external_handle", "External handle", "supported"),
            ("location_hint", "Location hint", "supported"),
        ],
        "claim_type": [
            ("fact", "Fact", "supported"),
            ("inference", "Inference", "supported"),
            ("preference", "Preference", "supported"),
            ("pattern", "Pattern", "supported"),
        ],
        "sensitivity": [
            ("low", "Low", "supported"),
            ("medium", "Medium", "supported"),
            ("high", "High", "supported"),
        ],
        "ai_use_policy": [
            ("freely_use", "Freely use", "supported"),
            ("cautious_use", "Cautious use", "supported"),
            ("ask_before_use", "Ask before use", "supported"),
            ("never_surface", "Never surface", "supported"),
        ],
    }
    rows = []
    counter = 1
    for category, values in seeds.items():
        for sort_order, (value, label, support_level) in enumerate(values):
            rows.append(
                {
                    "id": f"seed-{counter:03d}",
                    "category": category,
                    "value": value,
                    "label": label,
                    "description": None,
                    "support_level": support_level,
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
        "ontology_registry_values",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("support_level", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("category", "value", name="uq_registry_category_value"),
    )
    op.create_index("ix_ontology_registry_values_category", "ontology_registry_values", ["category"])

    op.create_table(
        "entities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("canonical_name", sa.String(length=240)),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("confirmation_status", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("ai_use_policy", sa.String(length=60), nullable=False),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("system_role", sa.String(length=60)),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_referenced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index("ix_entities_canonical_name", "entities", ["canonical_name"])
    op.create_index("ix_entities_confirmation_status", "entities", ["confirmation_status"])
    op.create_index(
        "ux_entities_system_role_self",
        "entities",
        ["system_role"],
        unique=True,
        postgresql_where=sa.text("system_role = 'self'"),
    )
    op.execute(
        "create index ix_entities_display_name_trgm "
        "on entities using gin (display_name gin_trgm_ops)"
    )
    op.execute(
        "create index ix_entities_canonical_name_trgm "
        "on entities using gin (canonical_name gin_trgm_ops)"
    )

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("alias", sa.String(length=240), nullable=False),
        sa.Column("normalized_alias", sa.String(length=240)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("source_candidate_id", sa.String(length=36)),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_normalized_alias", "entity_aliases", ["normalized_alias"])
    op.execute(
        "create index ix_entity_aliases_alias_trgm "
        "on entity_aliases using gin (alias gin_trgm_ops)"
    )
    op.execute(
        "create index ix_entity_aliases_normalized_alias_trgm "
        "on entity_aliases using gin (normalized_alias gin_trgm_ops)"
    )

    op.create_table(
        "entity_facts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("entity_id", sa.String(length=36), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("fact_type", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB()),
        sa.Column("claim_type", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("sensitivity", sa.String(length=40), nullable=False),
        sa.Column("ai_use_policy", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("source_candidate_id", sa.String(length=36)),
        sa.Column("created_by", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_entity_facts_entity_id", "entity_facts", ["entity_id"])
    op.create_index("ix_entity_facts_fact_type", "entity_facts", ["fact_type"])
    op.create_index("ix_entity_facts_status", "entity_facts", ["status"])

    op.bulk_insert(registry, _seed_rows())


def downgrade() -> None:
    op.drop_index("ix_entity_facts_status", table_name="entity_facts")
    op.drop_index("ix_entity_facts_fact_type", table_name="entity_facts")
    op.drop_index("ix_entity_facts_entity_id", table_name="entity_facts")
    op.drop_table("entity_facts")

    op.execute("drop index if exists ix_entity_aliases_normalized_alias_trgm")
    op.execute("drop index if exists ix_entity_aliases_alias_trgm")
    op.drop_index("ix_entity_aliases_normalized_alias", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_entity_id", table_name="entity_aliases")
    op.drop_table("entity_aliases")

    op.execute("drop index if exists ix_entities_canonical_name_trgm")
    op.execute("drop index if exists ix_entities_display_name_trgm")
    op.drop_index("ux_entities_system_role_self", table_name="entities")
    op.drop_index("ix_entities_confirmation_status", table_name="entities")
    op.drop_index("ix_entities_canonical_name", table_name="entities")
    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_table("entities")

    op.drop_index("ix_ontology_registry_values_category", table_name="ontology_registry_values")
    op.drop_table("ontology_registry_values")
