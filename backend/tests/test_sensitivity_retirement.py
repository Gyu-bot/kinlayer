"""The retired label is neither a public contract nor a decision input.

Historical rows deliberately use ORM writes, not the now-inert legacy API input.
All data below is synthetic and uses the isolated TestClient database.
"""
import json
from copy import deepcopy
from dataclasses import asdict

import pytest

from kinlayer_backend.models import (
    AgentWriteOperationAudit, Candidate, CandidateEvidence, Entity, Episode, Observation,
)
from kinlayer_backend.services.candidate_snapshots import (
    candidate_snapshot,
    digest,
    entity_digest,
)
from kinlayer_backend.services.curation import CurationService
from kinlayer_backend.services.retrieval import RetrievalService


RETIRED_KEYS = {"sensitivity", "effective_sensitivity", "sensitivity_levels"}


def assert_public(value):
    if isinstance(value, dict):
        assert not RETIRED_KEYS.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


def historical_candidate(client, *, candidate_type="observation"):
    with client.app.state.session_factory() as session:
        entity = Entity(entity_type="person", display_name="Synthetic Casey", sensitivity="high", created_by="user")
        episode = Episode(
            source_type="agent_conversation", source_ref="test:sensitivity-retirement",
            body_excerpt="As of 2026-09-28, Synthetic Casey prefers concise scheduling.", body_hash="sha256:fixture",
            actor="user", sensitivity="high", retention_policy="excerpt_only",
        )
        session.add_all([entity, episode])
        session.flush()
        payload = {
            "subject_entity_id": entity.id, "related_entity_ids": [],
            "observation_type": "communication_preference",
            "content": episode.body_excerpt, "claim_type": "preference",
            "ai_use_policy": "cautious_use", "sensitivity": "high",
        }
        if candidate_type == "new_entity":
            payload = {
                "entity_type": "person", "display_name": "Synthetic Casey",
                "canonical_name": "Synthetic Casey", "properties": {},
                "ai_use_policy": "cautious_use", "sensitivity": "high",
            }
        candidate = Candidate(
            candidate_type=candidate_type,
            target_entity_id=entity.id if candidate_type == "observation" else None,
            payload=payload, confidence=0.95, sensitivity="high", created_by="ai_agent",
        )
        session.add(candidate)
        session.flush()
        session.add(CandidateEvidence(
            candidate_id=candidate.id, episode_id=episode.id,
            excerpt=episode.body_excerpt, confidence=1.0,
        ))
        session.commit()
        return entity.id, candidate.id, episode.id


def test_legacy_inputs_are_inert_and_historical_labels_are_preserved(client):
    entity_id, candidate_id, episode_id = historical_candidate(client)
    with client.app.state.session_factory() as session:
        snapshot = candidate_snapshot(session, session.get(Candidate, candidate_id))
        old_payload = deepcopy(session.get(Candidate, candidate_id).payload)
        old_entity_digest = entity_digest(session.get(Entity, entity_id))

    for path in [f"/api/entities/{entity_id}", f"/api/candidates/{candidate_id}"]:
        response = client.patch(path, json={"sensitivity": "not-a-level"})
        assert response.status_code == 200
        assert_public(response.json())
    created = client.post("/api/entities", json={
        "display_name": "Another synthetic person", "sensitivity": {"ignored": True},
    })
    assert created.status_code == 201
    assert_public(created.json())
    for path in [
        "/api/entities?sensitivity=impossible",
        "/api/candidates?sensitivity=impossible",
        f"/api/episodes/{episode_id}",
        f"/api/entities/{entity_id}/context-card",
        "/api/ontology",
    ]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert_public(response.json())
        if path.startswith("/api/entities?") or path.startswith("/api/candidates?"):
            assert response.json()["total"] > 0
    with client.app.state.session_factory() as session:
        candidate = session.get(Candidate, candidate_id)
        assert candidate.payload == old_payload
        assert candidate.sensitivity == "high"
        assert session.get(Entity, entity_id).sensitivity == "high"
        assert session.get(Episode, episode_id).sensitivity == "high"
        assert candidate_snapshot(session, candidate) == snapshot
        assert entity_digest(session.get(Entity, entity_id)) == old_entity_digest
        assert session.get(Entity, created.json()["id"]).sensitivity == "medium"


def test_source_pack_omits_retired_keys_but_preserves_opaque_snapshot_digests(client):
    client.app.state.settings.curation_mode = "shadow"
    _, candidate_id, _ = historical_candidate(client)
    with client.app.state.session_factory() as session:
        candidate = session.get(Candidate, candidate_id)
        before = candidate_snapshot(session, candidate)
        payload = deepcopy(candidate.payload)
        evidence = candidate.evidence[0]
        episode = evidence.episode
        expected_evidence_digest = digest([{
            "id": evidence.id, "episode_id": evidence.episode_id,
            "excerpt": evidence.excerpt, "confidence": str(evidence.confidence),
            "source_type": episode.source_type, "source_ref": episode.source_ref,
            "body_hash": episode.body_hash, "actor": episode.actor,
            "sensitivity": "high",
        }])
    response = client.post("/api/curation/source-packs", json={"limit": 10})
    assert response.status_code == 200
    pack = response.json()
    assert_public(pack)
    assert pack["input_candidate_count"] == 1
    candidate = pack["groups"][0]["candidates"][0]
    assert candidate["payload_digest"] == digest(payload) == before["payload_digest"]
    assert candidate["evidence_digest"] == expected_evidence_digest == before["evidence_digest"]
    assert set(candidate["evidence"][0]) == {
        "candidate_evidence_id", "episode_id", "excerpt", "confidence", "source_type",
        "source_ref", "body_hash", "actor", "occurred_at", "ingested_at", "created_at",
    }
    assert candidate["validation_errors"] == []
    with client.app.state.session_factory() as session:
        assert candidate_snapshot(session, session.get(Candidate, candidate_id)) == before
        assert session.get(Candidate, candidate_id).payload == payload


def test_historical_sensitivity_does_not_change_retrieval_or_provisional_eligibility(client):
    entity_id, candidate_id, _ = historical_candidate(client)
    with client.app.state.session_factory() as session:
        entity = session.get(Entity, entity_id)
        candidate = session.get(Candidate, candidate_id)
        observation = Observation(
            subject_entity_id=entity_id, observation_type="communication_preference",
            content="As of 2026-09-28, Synthetic Casey prefers concise scheduling.", claim_type="preference",
            sensitivity="high", ai_use_policy="cautious_use", created_by="user",
        )
        session.add(observation)
        session.commit()
        def retrieve():
            return asdict(RetrievalService(session).retrieve(
                "Casey concise scheduling", entity_hints=[entity_id],
            ))
        high = retrieve()
        assert high["matches"][0]["surface_bucket"] == "direct_surface"
        assert CurationService(session).is_provisional_candidate(candidate, entity_id)
        entity.sensitivity = observation.sensitivity = "low"
        session.flush()
        assert retrieve() == high
        entity.ai_use_policy = "ask_before_use"
        assert retrieve()["matches"][0]["surface_bucket"] == "conditional_surface"
        entity.ai_use_policy = "never_surface"
        assert retrieve()["matches"][0]["surface_bucket"] == "blocked"
        candidate.payload = {**candidate.payload, "ai_use_policy": "never_surface"}
        assert not CurationService(session).is_provisional_candidate(candidate, entity_id)


@pytest.mark.parametrize("candidate_type", ["observation", "new_entity"])
def test_historical_auto_plan_ignores_retired_label(client, candidate_type):
    client.app.state.settings.curation_mode = "shadow"
    _, candidate_id, _ = historical_candidate(client, candidate_type=candidate_type)
    # A separate person with the same name is an unrelated identity gate; remove
    # that synthetic fixture entity from active identity matching, not real data.
    with client.app.state.session_factory() as session:
        for entity in session.query(Entity).filter(Entity.display_name == "Synthetic Casey"):
            entity.display_name = "Unrelated Synthetic"
            entity.canonical_name = "Unrelated Synthetic"
        session.commit()
    pack = client.post("/api/curation/source-packs", json={}).json()
    candidate = pack["groups"][0]["candidates"][0]
    cursor = pack["cursor_completed"]
    response = client.post("/api/curation/runs", json={
        "mode": "shadow", "policy_version": "curation-policy-v1",
        "input_candidate_count": 1,
        "cursor_started_at": "2000-01-01T00:00:00Z", "cursor_started_id": "",
        "cursor_completed_at": cursor["created_at"],
        "cursor_completed_id": cursor["candidate_id"],
        "decisions": [{
            "action": "accept_existing", "risk_level": "low",
            "candidate_ids": [candidate_id],
            "expected_candidates": [{key: candidate[key] for key in (
                "id", "status", "updated_at", "payload_digest", "evidence_digest",
            )}],
            "target_entity_id": candidate["target_entity_id"],
            "proposed_payload": candidate["payload"],
            "evidence_episode_ids": [candidate["evidence"][0]["episode_id"]],
            "policy_version": "curation-policy-v1", "idempotency_key": "retired:person",
            "planner": {"name": "test", "version": "1"},
        }],
    })
    assert response.status_code == 201, response.text
    assert_public(response.json())
    assert response.json()["decisions"][0]["status"] == "allowed", response.text
    reasons = response.json()["decisions"][0]["reason_codes"]
    assert "new_entity_payload_inference_not_allowed" not in reasons
    assert "high_sensitivity" not in reasons
    # Planning in shadow must never accept the synthetic candidate.
    assert client.get(f"/api/candidates/{candidate_id}").json()["status"] == "pending"


def test_openapi_response_contract_has_no_sensitivity(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in [
        "EntityRead", "CandidateRead", "EpisodeRead", "EdgeRead", "ObservationRead",
        "CurationSourceEvidenceRead", "CurationSourceCandidateRead", "PoliciesRead",
        "ReconciliationCandidateEvidenceRead",
    ]:
        assert not RETIRED_KEYS.intersection(schemas[name].get("properties", {})), name


def test_historical_audit_projection_does_not_rewrite_evidence_or_policy(client):
    historical = {"sensitivity": "high", "ai_use_policy": "ask_before_use"}
    with client.app.state.session_factory() as session:
        audit = AgentWriteOperationAudit(
            operation_type="candidate_submit", source_path="/api/candidates",
            actor="ai_agent", result_status="success", request_summary=historical,
            diagnostics={"historical_payload": {"sensitivity": "low", "claim_type": "fact"}},
            related_refs={}, bounded_excerpt="Synthetic audit excerpt.",
        )
        session.add(audit)
        session.commit()
        audit_id = audit.id
    response = client.get("/api/agent-operations")
    assert response.status_code == 200
    assert_public(response.json())
    assert response.json()["items"][0]["request_summary"] == {"ai_use_policy": "ask_before_use"}
    exported = client.get("/api/agent-operations/export")
    assert exported.status_code == 200
    records = [json.loads(line) for line in exported.text.splitlines()]
    assert_public(records)
    assert records[1]["audit_id"] == audit_id
    assert records[1]["bounded_excerpt"] == "Synthetic audit excerpt."
    with client.app.state.session_factory() as session:
        audit = session.get(AgentWriteOperationAudit, audit_id)
        assert audit.request_summary == historical
        assert audit.diagnostics["historical_payload"]["sensitivity"] == "low"
