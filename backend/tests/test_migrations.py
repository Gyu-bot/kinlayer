import runpy
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine


def test_core_entity_migration_defines_required_tables_and_seeds() -> None:
    migration = Path("backend/alembic/versions/20260610_0002_core_entity_bootstrap.py")
    content = migration.read_text()

    for table in [
        "ontology_registry_values",
        "entities",
        "entity_aliases",
        "entity_facts",
    ]:
        assert f'"{table}"' in content

    for seed in ["person", "organization", "fact", "low", "never_surface"]:
        assert f'"{seed}"' in content

    assert "create extension if not exists vector" in content
    assert "create extension if not exists pg_trgm" in content


def test_relationship_observation_migration_defines_required_tables_and_seeds() -> None:
    migration = Path("backend/alembic/versions/20260610_0003_relationships_observations.py")
    content = migration.read_text()

    for table in [
        "allowed_edge_types",
        "allowed_observation_types",
        "entity_edges",
        "observations",
        "observation_entities",
        "episodes",
        "entity_fact_evidence",
        "edge_evidence",
        "observation_evidence",
    ]:
        assert f'"{table}"' in content

    for seed in [
        "edge_type",
        "observation_type",
        "retention_policy",
        "evidence_source_type",
        "allowed_edge_types",
        "allowed_observation_types",
        "client_contact",
        "recent_interaction",
        "excerpt_only",
    ]:
        assert f'"{seed}"' in content

    assert "embedding_status" in content
    assert "vector" in content


def test_candidate_migration_defines_required_tables() -> None:
    migration = Path("backend/alembic/versions/20260610_0004_candidates.py")
    content = migration.read_text()

    for table in ["candidates", "candidate_evidence"]:
        assert f'"{table}"' in content

    for column in [
        "candidate_type",
        "target_entity_id",
        "payload",
        "confidence",
        "sensitivity",
        "suggested_action",
        "status",
        "created_by",
        "resolved_at",
        "resolved_by",
        "resolution_note",
        "canonical_record_ref",
        "supersedes_candidate_id",
        "supersedes_record_ref",
        "episode_id",
        "excerpt",
    ]:
        assert f'"{column}"' in content

    for seed in ["candidate_type", "new_entity", "relationship_edge", "supersede", "pending"]:
        assert f'"{seed}"' in content


def test_agent_write_operation_audit_migration_defines_required_table() -> None:
    migration = Path("backend/alembic/versions/20260612_0005_agent_write_operation_audits.py")
    content = migration.read_text()

    assert '"agent_write_operation_audits"' in content
    for column in [
        "operation_type",
        "source_path",
        "actor",
        "result_status",
        "api_error_code",
        "request_summary",
        "diagnostics",
        "related_refs",
        "candidate_id",
        "correction_id",
        "episode_id",
        "canonical_record_ref",
        "bounded_excerpt",
    ]:
        assert f'"{column}"' in content


def test_person_merge_migration_defines_required_table() -> None:
    migration = Path("backend/alembic/versions/20260612_0006_person_merge_records.py")
    content = migration.read_text()

    assert '"entity_merges"' in content
    for column in [
        "source_entity_id",
        "target_entity_id",
        "candidate_id",
        "merge_plan",
        "conflict_decisions",
        "actor",
        "canonical_record_ref",
        "previous_refs",
    ]:
        assert f'"{column}"' in content


def test_curation_migration_defines_durable_run_and_decision_tables() -> None:
    migration = Path("backend/alembic/versions/20260824_0007_relationship_curation.py")
    content = migration.read_text()

    assert 'down_revision: str | None = "20260612_0006"' in content
    for table in ["curation_runs", "curation_decisions"]:
        assert f'"{table}"' in content
    for column in [
        "mode",
        "status",
        "cursor_started_at",
        "cursor_started_id",
        "cursor_completed_at",
        "cursor_completed_id",
        "policy_version",
        "planner_name",
        "planner_model",
        "planner_version",
        "input_candidate_count",
        "planned_decision_count",
        "executed_decision_count",
        "blocked_decision_count",
        "error_code",
        "diagnostics",
        "started_at",
        "completed_at",
        "run_id",
        "action",
        "risk_level",
        "candidate_ids",
        "target_entity_id",
        "proposed_payload",
        "evidence_episode_ids",
        "reason_codes",
        "idempotency_key",
        "canonical_record_ref",
        "readback_status",
        "readback_summary",
        "api_error_code",
        "executed_at",
    ]:
        assert f'"{column}"' in content
    for constraint in [
        "uq_curation_decisions_idempotency_key",
        "ix_curation_runs_status",
        "ix_curation_decisions_run_id",
        "ix_curation_decisions_status",
    ]:
        assert f'"{constraint}"' in content
    for forbidden in ["raw_prompt", "provider_request", "provider_response", "session_content"]:
        assert forbidden not in content


def test_curation_migration_applies_to_an_empty_database(database_url: str) -> None:
    migration = runpy.run_path(
        "backend/alembic/versions/20260824_0007_relationship_curation.py"
    )
    engine = create_db_engine(Settings(database_url=database_url))

    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration["upgrade"]()

    assert {"curation_runs", "curation_decisions"} <= set(inspect(engine).get_table_names())


def test_candidate_canonicalization_guard_migration_defines_unique_indexes() -> None:
    migration = Path(
        "backend/alembic/versions/20260825_0008_unique_candidate_canonicalization.py"
    )
    content = migration.read_text()

    assert 'down_revision: str | None = "20260824_0007"' in content
    for index in [
        "ux_entity_aliases_source_candidate_id",
        "ux_entity_facts_source_candidate_id",
        "ux_entity_edges_source_candidate_id",
        "ux_observations_source_candidate_id",
        "ux_entity_merges_candidate_id",
    ]:
        assert f'"{index}"' in content
    assert "unique=True" in content
