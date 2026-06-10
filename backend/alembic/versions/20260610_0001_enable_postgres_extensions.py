"""enable postgres extensions

Revision ID: 20260610_0001
Revises:
Create Date: 2026-06-10
"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260610_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists vector")
    op.execute("create extension if not exists pg_trgm")


def downgrade() -> None:
    op.execute("drop extension if exists pg_trgm")
    op.execute("drop extension if exists vector")
