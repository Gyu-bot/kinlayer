"""unique candidate canonicalization guards

Revision ID: 20260825_0008
Revises: 20260824_0007
Create Date: 2026-08-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

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


def _duplicate_key_classes(connection) -> list[str]:
    affected = []
    for table, column in INDEXES.values():
        duplicate = connection.execute(
            sa.text(
                f"select 1 from {table} "
                f"where {column} is not null "
                f"group by {column} having count(*) > 1 limit 1"
            )
        ).first()
        if duplicate:
            affected.append(f"{table}.{column}")
    return affected


def _assert_no_historical_duplicates(connection) -> None:
    affected = _duplicate_key_classes(connection)
    if affected:
        joined = ", ".join(affected)
        raise RuntimeError(
            "Migration 20260825_0008 blocked: duplicate non-null canonical source keys "
            f"exist in {joined}. Resolve those duplicates manually, then retry. "
            "No rows were changed."
        )


def _offline_postgres_preflight_sql() -> sa.TextClause:
    duplicate_queries = " union all ".join(
        f"select '{table}.{column}' as key_class from {table} "
        f"where {column} is not null group by {column} having count(*) > 1"
        for table, column in INDEXES.values()
    )
    return sa.text(
        "do $$ declare duplicate_keys text; begin "
        "select string_agg(distinct key_class, ', ' order by key_class) into duplicate_keys "
        f"from ({duplicate_queries}) duplicate_keys; "
        "if duplicate_keys is not null then "
        "raise exception 'Migration 20260825_0008 blocked: duplicate non-null canonical "
        "source keys exist in %. Resolve those duplicates manually, then retry. "
        "No rows were changed.', duplicate_keys; "
        "end if; end $$"
    )


def _emit_offline_postgres_preflight() -> None:
    op.execute(_offline_postgres_preflight_sql())


def upgrade() -> None:
    if context.is_offline_mode():
        _emit_offline_postgres_preflight()
    else:
        _assert_no_historical_duplicates(op.get_bind())
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
