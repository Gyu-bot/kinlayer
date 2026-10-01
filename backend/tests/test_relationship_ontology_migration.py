"""An operator-reviewed conversion must preserve evidence and historical meaning."""
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from kinlayer_backend.models import EdgeEvidence, Entity, EntityEdge, Episode, MemoryChange
from kinlayer_backend.services.memories import utc
from kinlayer_backend.services.memory_migration import MemoryDataMigration
from kinlayer_backend.services.ontology import seed_ontology_values


def relationship_plan(session):
    people = [Entity(display_name=name, entity_type="person", created_by="user")
              for name in ("Synthetic A", "Synthetic B")]
    session.add_all(people)
    session.flush()
    source = Episode(source_type="manual_entry", actor="user",
                     body_excerpt="I describe B as my early dating partner.",
                     body_hash="sha256:synthetic-relationship")
    session.add(source)
    session.flush()
    # Direct fixture represents a historical row, not permission to create this type now.
    edge = EntityEdge(from_entity_id=people[0].id, to_entity_id=people[1].id,
                      relation_type="dating_interest", directed=False,
                      claim_text=source.body_excerpt, claim_type="inference",
                      claim_basis="unknown", confidence=0.7, created_by="user",
                      properties={"relationship_label": "early dating partner"})
    session.add(edge)
    session.flush()
    session.add(EdgeEvidence(edge_id=edge.id, episode_id=source.id,
                             excerpt=source.body_excerpt, confidence=0.7))
    session.commit()
    manifest = {
        "schema_version": 1, "plan_id": "reviewed-relationship-example",
        "replacements": [{
            "old_record_ref": f"entity_edges:{edge.id}",
            "expected": {"relation_type": edge.relation_type, "status": "active",
                         "updated_at": utc(edge.updated_at).isoformat(),
                         "claim_text": edge.claim_text, "properties": edge.properties},
            "reason": "Reviewed wording describes an early dating relationship, not a feeling.",
            "records": [{"record_type": "entity_edges", "payload": {
                "from_entity_id": edge.from_entity_id, "to_entity_id": edge.to_entity_id,
                "relation_type": "situationship", "directed": False,
                "claim_text": edge.claim_text, "claim_basis": "unknown", "confidence": 0.7,
                "properties": {"relationship_detail": "early dating partner"},
            }}],
        }],
    }
    return edge.id, source.id, manifest


def test_reviewed_relationship_migration_preserves_original_and_evidence(client):
    with client.app.state.session_factory() as session:
        old_id, source_id, plan = relationship_plan(session)
        old = session.get(EntityEdge, old_id)
        original_created = old.created_at
        original_updated = old.updated_at
        # Seeding definitions must never silently reinterpret historical records.
        seed_ontology_values(session)
        assert old.relation_type == "dating_interest"
        assert old.updated_at == original_updated
        dry = MemoryDataMigration(session).run(plan)
        assert dry["replaced"] == dry["created"] == dry["evidence_copied"] == 1
        assert session.get(EntityEdge, old_id).status == "active"
        assert session.scalar(select(func.count()).select_from(MemoryChange)) == 0
        applied = MemoryDataMigration(session).run(plan, apply=True)
        assert applied["status"] == "applied"
        old = session.get(EntityEdge, old_id)
        assert old.status == "superseded" and old.relation_type == "dating_interest"
        assert old.properties == {"relationship_label": "early dating partner"}
        new = session.scalar(select(EntityEdge).where(EntityEdge.id != old_id))
        assert new.relation_type == "situationship" and new.directed is False
        assert new.claim_basis == "unknown" and float(new.confidence) == 0.7
        assert new.claim_text == old.claim_text and new.created_at == original_created
        evidence = session.scalar(select(EdgeEvidence).where(EdgeEvidence.edge_id == new.id))
        assert evidence.episode_id == source_id and evidence.excerpt == old.claim_text
        change = session.scalar(select(MemoryChange).where(
            MemoryChange.old_record_ref == f"entity_edges:{old_id}"))
        assert change.new_record_ref == f"entity_edges:{new.id}"
        assert MemoryDataMigration(session).run(plan, apply=True)["status"] == "already_applied"


def test_relationship_conversion_refuses_stale_plan(client):
    with client.app.state.session_factory() as session:
        old_id, _, plan = relationship_plan(session)
        stale = deepcopy(plan)
        stale["replacements"][0]["expected"]["updated_at"] = "2000-01-01T00:00:00+00:00"
        with pytest.raises(ValueError, match="Migration input drift"):
            MemoryDataMigration(session).run(stale, apply=True)
        assert session.get(EntityEdge, old_id).status == "active"
        assert session.scalar(select(func.count()).select_from(MemoryChange)) == 0
