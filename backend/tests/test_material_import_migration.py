import io
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_postgresql_material_import_upgrade_ddl_is_additive():
    migration = runpy.run_path(
        "backend/alembic/versions/20260930_0011_authorized_material_imports.py"
    )
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration["upgrade"]()
    ddl = output.getvalue()
    assert "CREATE TABLE material_imports" in ddl
    assert "manifest JSONB" in ddl
    assert "ALTER TABLE episodes ADD COLUMN material_import_id" in ddl
    assert "REFERENCES material_imports (id)" in ddl
    assert "DROP" not in ddl


def test_material_import_migration_roundtrip_and_populated_guard(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    migration = runpy.run_path(
        str(Path("backend/alembic/versions/20260930_0011_authorized_material_imports.py"))
    )
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE episodes (id VARCHAR(36) PRIMARY KEY, actor VARCHAR(80))")
        )
        connection.execute(text("INSERT INTO episodes VALUES ('historical', 'user')"))
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()
            assert "material_imports" in inspect(connection).get_table_names()
            assert "material_import_id" in {
                c["name"] for c in inspect(connection).get_columns("episodes")
            }
            assert connection.execute(
                text("SELECT actor, material_import_id FROM episodes")
            ).one() == ("user", None)
            migration["downgrade"]()
            assert "material_imports" not in inspect(connection).get_table_names()
            assert connection.execute(text("SELECT actor FROM episodes")).scalar() == "user"
            migration["upgrade"]()
            connection.execute(
                text(
                    "INSERT INTO material_imports VALUES ('test', 'sha256:test', '{}', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            with pytest.raises(RuntimeError, match="retire imported evidence"):
                migration["downgrade"]()
            assert "material_imports" in inspect(connection).get_table_names()
