"""Add nullable structured relationship assessments without interpreting old prose.

Revision ID: 20261001_0013
Revises: 20261001_0012
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0013"
down_revision = "20261001_0012"
branch_labels = None
depends_on = None

PROFILE_CHECK = (
    "(observation_type <> 'relationship_assessment' AND perspective_entity_id IS NULL AND relationship_axis IS NULL AND relationship_value IS NULL) OR "
    "(observation_type = 'relationship_assessment' AND perspective_entity_id IS NOT NULL AND perspective_entity_id <> subject_entity_id AND relationship_axis IS NOT NULL AND relationship_value IS NOT NULL AND claim_basis = 'reported' AND "
    "((relationship_axis = 'closeness' AND relationship_value IN ('recognize','acquainted','comfortable','close','very_close')) OR "
    "(relationship_axis = 'importance' AND relationship_value IN ('normal','important','very_important')) OR "
    "(relationship_axis = 'interaction_frequency' AND relationship_value IN ('frequent','occasional','rare','none')) OR "
    "(relationship_axis = 'connection_state' AND relationship_value IN ('maintained','distant','disconnected'))))"
)


def upgrade():
    with op.batch_alter_table("observations") as batch:
        batch.add_column(sa.Column("perspective_entity_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("relationship_axis", sa.String(40), nullable=True))
        batch.add_column(sa.Column("relationship_value", sa.String(40), nullable=True))
        batch.create_foreign_key(
            "fk_observations_perspective_entity", "entities", ["perspective_entity_id"], ["id"]
        )
        batch.create_check_constraint("ck_observations_relationship_profile", PROFILE_CHECK)
    op.create_index(
        "ux_observations_current_relationship_axis",
        "observations",
        ["perspective_entity_id", "subject_entity_id", "relationship_axis"],
        unique=True,
        sqlite_where=sa.text("relationship_axis IS NOT NULL AND status IN ('active', 'disputed')"),
        postgresql_where=sa.text(
            "relationship_axis IS NOT NULL AND status IN ('active', 'disputed')"
        ),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM observations WHERE relationship_axis IS NOT NULL"))
        .scalar()
    ):
        raise RuntimeError(
            "Restore the pre-migration backup to preserve relationship assessment history."
        )
    op.drop_index("ux_observations_current_relationship_axis", table_name="observations")
    with op.batch_alter_table("observations") as batch:
        batch.drop_constraint("ck_observations_relationship_profile", type_="check")
        batch.drop_constraint("fk_observations_perspective_entity", type_="foreignkey")
        for name in ("relationship_value", "relationship_axis", "perspective_entity_id"):
            batch.drop_column(name)
