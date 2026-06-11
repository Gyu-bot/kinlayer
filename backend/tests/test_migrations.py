from pathlib import Path


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
