import copy
import runpy

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, func, inspect, select, text

from kinlayer_backend.models import (
    Entity, EntityFact, EntityFactEvidence, Episode, MemoryChange, Observation, ObservationEvidence,
)
from kinlayer_backend.services.memory_migration import MemoryDataMigration
from kinlayer_backend.services.structured_facts import normalize_profile_fact


def test_partial_profile_dates_and_typed_text():
    assert normalize_profile_fact("birth_date", "1984-01", {
        "year": 1984, "month": 1, "precision": "month",
    }) == ("1984-01", {"year": 1984, "month": 1, "day": None, "precision": "month"})
    assert normalize_profile_fact("birthday", "--02-29", {
        "month": 2, "day": 29, "precision": "day",
    })[1]["year"] is None
    assert normalize_profile_fact("job", "Teacher", {"text": " Teacher "}) == (
        "Teacher", {"text": "Teacher"},
    )
    for kind, content, value in [
        ("birth_date", "2001-02-29", {"year": 2001, "month": 2, "day": 29, "precision": "day"}),
        ("birth_date", "1984-01", {"year": 1984, "month": 1, "day": 1, "precision": "month"}),
        ("birth_date", "0001", {"year": True, "precision": "year"}),
        ("job", "Teacher", {"text": "Engineer"}),
        ("memo", "Context", {"text": "Context"}),
        ("job", "Teacher", {"text": "Teacher", "schedule": "rotating"}),
    ]:
        with pytest.raises(ValueError):
            normalize_profile_fact(kind, content, value)


def fixture_plan(session):
    person = Entity(entity_type="person", display_name="Synthetic Alex", created_by="user")
    session.add(person)
    session.flush()
    episode = Episode(source_type="agent_conversation", actor="user", body_excerpt="Alex teaches and works nights.", body_hash="sha256:fixture")
    session.add(episode)
    session.flush()
    old = EntityFact(entity_id=person.id, fact_type="job", content="Teacher; night shifts", value={"job": "Teacher", "schedule": "night"}, claim_type="fact", created_by="user")
    session.add(old)
    session.flush()
    session.add(EntityFactEvidence(entity_fact_id=old.id, episode_id=episode.id, excerpt="Alex teaches and works nights."))
    session.commit()
    plan = {
        "schema_version": 1, "plan_id": "synthetic-test",
        "replacements": [{
            "old_record_ref": f"entity_facts:{old.id}",
            "expected": {"status": "active", "content": old.content, "value": old.value},
            "reason": "Split independently correctable profession and working schedule",
            "records": [
                {"record_type": "entity_facts", "payload": {"entity_id": person.id, "fact_type": "job", "content": "Teacher", "value": {"text": "Teacher"}, "claim_basis": "reported", "confidence": 0.9}},
                {"record_type": "observations", "payload": {"subject_entity_id": person.id, "observation_type": "stable_fact", "content": "Works night shifts", "claim_basis": "reported", "confidence": 0.9}},
            ],
        }],
    }
    return old.id, episode.id, plan


def test_data_conversion_rehearsal_preserves_sources_and_is_idempotent(client):
    with client.app.state.session_factory() as session:
        old_id, episode_id, plan = fixture_plan(session)
        original_created = session.get(EntityFact, old_id).created_at
        dry = MemoryDataMigration(session).run(plan)
        assert dry["created"] == 2 and dry["evidence_copied"] == 2
        assert session.get(EntityFact, old_id).status == "active"
        assert session.scalar(select(func.count()).select_from(MemoryChange)) == 0
        applied = MemoryDataMigration(session).run(plan, apply=True)
        assert applied["status"] == "applied"
        old = session.get(EntityFact, old_id)
        assert old.status == "superseded" and old.content == "Teacher; night shifts"
        assert old.value == {"job": "Teacher", "schedule": "night"} and old.valid_to is None
        obs = session.scalar(select(Observation))
        assert obs.created_at == original_created and obs.embedding_status == "pending"
        assert obs.occurred_at is None
        assert session.scalar(select(ObservationEvidence)).episode_id == episode_id
        assert session.scalar(select(func.count()).select_from(Episode)) == 1
        assert MemoryDataMigration(session).run(plan, apply=True)["status"] == "already_applied"
        conflicting = copy.deepcopy(plan)
        conflicting["replacements"][0]["reason"] = "Different manifest"
        with pytest.raises(ValueError, match="different content"):
            MemoryDataMigration(session).run(conflicting, apply=True)


def test_input_drift_rolls_back_entire_conversion(client):
    with client.app.state.session_factory() as session:
        old_id, _, plan = fixture_plan(session)
        plan["replacements"][0]["expected"]["content"] = "Stale text"
        with pytest.raises(ValueError, match="input drift"):
            MemoryDataMigration(session).run(plan, apply=True)
        assert session.scalar(select(func.count()).select_from(MemoryChange)) == 0
        assert session.scalar(select(func.count()).select_from(Observation)) == 0
        assert session.get(EntityFact, old_id).status == "active"


def test_additive_migration_keeps_unknown_basis_and_guards_downgrade(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    migration = runpy.run_path("backend/alembic/versions/20261001_0012_save_first_memories.py")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE episodes (id VARCHAR(36) PRIMARY KEY)"))
        for table in ("entity_facts", "entity_edges", "observations"):
            connection.execute(text(f"CREATE TABLE {table} (id VARCHAR(36) PRIMARY KEY, claim_type TEXT)"))
            connection.execute(text(f"INSERT INTO {table} VALUES ('old-fact', 'fact'), ('old-inference', 'inference')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            assert connection.execute(text("SELECT claim_basis FROM observations ORDER BY id")).scalars().all() == ["unknown", "inferred"]
            assert "memory_changes" in inspect(connection).get_table_names()
            connection.execute(text("INSERT INTO memory_changes (id, request_id, request_sha256, change_kind, actor, created_at) VALUES ('m', 'r', 'sha256:fixture', 'migrate', 'system', CURRENT_TIMESTAMP)"))
            with pytest.raises(RuntimeError, match="pre-migration backup"):
                migration["downgrade"]()


def test_tracked_revisions_cannot_be_overwritten_by_legacy_crud(client):
    with client.app.state.session_factory() as session:
        _, _, plan = fixture_plan(session)
        MemoryDataMigration(session).run(plan, apply=True)
        fact = session.scalar(select(EntityFact).where(EntityFact.status == "active"))
        observation = session.scalar(select(Observation))
        for route, identifier in (("entity-facts", fact.id), ("observations", observation.id)):
            patched = client.patch(f"/api/{route}/{identifier}", json={"content": "Changed"})
            assert patched.status_code == 409
            assert patched.json()["error"]["code"] == "memory_change_required"
            deleted = client.delete(f"/api/{route}/{identifier}")
            assert deleted.status_code == 409
        session.expire_all()
        assert session.get(EntityFact, fact.id).value == {"text": "Teacher"}
        assert session.get(Observation, observation.id).content == "Works night shifts"


def test_migration_inherits_omitted_times_but_respects_explicit_participant_override(client):
    from datetime import UTC, datetime
    from kinlayer_backend.models import ObservationEntity

    with client.app.state.session_factory() as session:
        _, _, base_plan = fixture_plan(session)
        person_id = base_plan["replacements"][0]["records"][0]["payload"]["entity_id"]
        old = Observation(subject_entity_id=person_id, observation_type="user_feeling", content="Old context", claim_type="fact", created_by="user", occurred_at=datetime(2024, 1, 1, tzinfo=UTC), valid_from=datetime(2024, 1, 1, tzinfo=UTC), recency_weight=0.5, embedding="[1,2]", embedding_status="ready")
        session.add(old)
        session.flush()
        session.add(ObservationEntity(observation_id=old.id, entity_id=person_id, role="experiencer"))
        session.commit()
        plan = {"schema_version": 1, "plan_id": "time-role-inheritance", "replacements": [{
            "old_record_ref": f"observations:{old.id}", "expected": {"content": "Old context"},
            "reason": "Explicit role removal; unspecified temporal fields retain their meaning",
            "records": [{"record_type": "observations", "payload": {
                "subject_entity_id": person_id, "observation_type": "stable_fact",
                "content": "Reclassified context", "claim_basis": "unknown", "confidence": 0.5,
                "related_entities": [],
            }}],
        }]}
        MemoryDataMigration(session).run(plan, apply=True)
        new = session.scalar(select(Observation).where(Observation.status == "active"))
        from kinlayer_backend.services.memories import utc
        assert utc(new.occurred_at) == utc(old.occurred_at)
        assert utc(new.valid_from) == utc(old.valid_from)
        assert float(new.recency_weight) == 0.5
        assert session.scalar(select(func.count()).select_from(ObservationEntity).where(ObservationEntity.observation_id == new.id)) == 0
        assert old.embedding == "[1,2]" and old.embedding_status == "ready"
        assert new.embedding is None and new.embedding_status == "pending"


def test_full_snapshot_guard_catches_metadata_drift(client):
    from kinlayer_backend.services.memory_migration import snapshot_digest

    with client.app.state.session_factory() as session:
        old_id, _, plan = fixture_plan(session)
        table = EntityFact.__table__
        rows = [dict(row) for row in session.execute(select(table)).mappings()]
        plan["snapshot"] = {"entity_facts": {"columns": list(rows[0]), "count": len(rows), "sha256": snapshot_digest(rows, table)}}
        session.get(EntityFact, old_id).confidence = 0.25
        session.commit()
        with pytest.raises(ValueError, match="snapshot changed"):
            MemoryDataMigration(session).run(plan, apply=True)
        assert session.scalar(select(func.count()).select_from(MemoryChange)) == 0


def test_observation_to_profile_fact_keeps_validity_without_invalid_event_field(client):
    from datetime import UTC, datetime
    from kinlayer_backend.services.memories import utc

    with client.app.state.session_factory() as session:
        _, _, plan = fixture_plan(session)
        person_id = plan["replacements"][0]["records"][0]["payload"]["entity_id"]
        old = Observation(subject_entity_id=person_id, observation_type="stable_fact",
                          content="Teacher", created_by="user", claim_type="fact",
                          occurred_at=datetime(2024, 1, 1, tzinfo=UTC),
                          valid_from=datetime(2024, 1, 1, tzinfo=UTC))
        session.add(old)
        session.commit()
        conversion = {"schema_version": 1, "plan_id": "observation-to-profile", "replacements": [{
            "old_record_ref": f"observations:{old.id}", "expected": {"content": "Teacher"},
            "reason": "Normalize profile attribute",
            "records": [{"record_type": "entity_facts", "payload": {
                "entity_id": person_id, "fact_type": "job", "content": "Teacher",
                "value": {"text": "Teacher"}, "claim_basis": "reported", "confidence": 0.8,
            }}],
        }]}
        MemoryDataMigration(session).run(conversion, apply=True)
        new = session.scalar(select(EntityFact).where(EntityFact.content == "Teacher"))
        assert utc(new.valid_from) == utc(old.valid_from)
        assert old.status == "superseded" and old.occurred_at is not None
