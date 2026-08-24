"""unique candidate canonicalization guards

Revision ID: 20260825_0008
Revises: 20260824_0007
Create Date: 2026-08-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0008"
down_revision: str | None = "20260824_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXES = {
    "ux_entity_aliases_source_candidate_id": ("entity_aliases", "source_candidate_id"),
    "ux_entity_facts_source_candidate_id": ("entity_facts", "source_candidate_id"),
    "ux_entity_edges_source_candidate_id": ("entity_edges", "source_candidate_id"),
    "ux_observations_source_candidate_id": ("observations", "source_candidate_id"),
    "ux_entity_merges_candidate_id": ("entity_merges", "candidate_id"),
}


def upgrade() -> None:
    for name, (table, column) in INDEXES.items():
        op.create_index(
            name,
            table,
            [column],
            unique=True,
            postgresql_where=sa.text(f"{column} is not null"),
            sqlite_where=sa.text(f"{column} is not null"),
        )


def downgrade() -> None:
    for name, (table, _column) in reversed(INDEXES.items()):
        op.drop_index(name, table_name=table)
