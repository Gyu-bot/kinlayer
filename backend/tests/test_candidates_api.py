import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import (
    Candidate,
    EdgeEvidence,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.schemas.candidates import CandidateCreate
from kinlayer_backend.services.candidates import CandidateService


def create_person(client, name: str) -> dict:
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def create_episode(client) -> dict:
    response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": "thread-candidate",
            "source_description": "Candidate evidence",
            "body_excerpt": "Alex prefers concise follow-ups.",
            "body_hash": "sha256:candidate",
            "actor": "ai_agent",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_candidate_payload_schemas_cover_supported_types() -> None:
    common = {"confidence": 0.72, "created_by": "ai_agent"}
    payloads = {
        "new_entity": {"entity_type": "person", "display_name": "Alex"},
        "alias": {"entity_id": "entity-1", "alias": "알렉스"},
        "profile_field": {
            "entity_id": "entity-1",
            "field_path": "properties.role_note",
            "value": "Former coworker",
            "claim_type": "fact",
        },
        "relationship_edge": {
            "from_entity_id": "entity-1",
            "to_entity_id": "entity-2",
            "relation_type": "former_coworker",
            "claim_text": "Alex is a former coworker.",
            "claim_type": "fact",
        },
        "observation": {
            "subject_entity_id": "entity-1",
            "observation_type": "communication_preference",
            "content": "Alex prefers concise follow-ups.",
            "claim_type": "pattern",
            "occurred_at": "2026-06-16T00:00:00Z",
            "valid_from": "2026-06-16T00:00:00Z",
            "valid_to": "2026-06-30T00:00:00Z",
        },
        "merge": {
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
            "reason": "Alias and references suggest a duplicate.",
        },
        "conflict": {
            "record_refs": ["observations:old", "observations:new"],
            "conflict_type": "contradiction",
            "description": "Two observations disagree.",
        },
        "supersede": {
            "old_record_ref": "observations:old",
            "new_payload": {
                "content": "Alex now prefers direct scheduling.",
                "claim_type": "pattern",
                "observation_type": "communication_preference",
            },
            "reason": "More recent interaction changed the pattern.",
        },
    }

    for candidate_type, payload in payloads.items():
        candidate = CandidateCreate.model_validate(
            {"candidate_type": candidate_type, "payload": payload, **common}
        )
        assert candidate.candidate_type == candidate_type

    with pytest.raises(ValidationError):
        CandidateCreate.model_validate(
            {
                "candidate_type": "relationship_edge",
                "payload": {"from_entity_id": "entity-1"},
                **common,
            }
        )


def test_candidate_create_validates_payload_and_stores_evidence(client) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)

    created = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person["id"],
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "communication_preference",
                "content": "Alex prefers concise follow-ups.",
                "claim_type": "pattern",
                "sensitivity": "medium",
                "ai_use_policy": "cautious_use",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex prefers concise follow-ups.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.72,
            "sensitivity": "medium",
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["candidate_type"] == "observation"
    assert body["status"] == "pending"
    assert body["payload"]["content"] == "Alex prefers concise follow-ups."
    assert body["evidence"][0]["episode_id"] == episode["id"]
    assert body["evidence"][0]["excerpt"] == "Alex prefers concise follow-ups."
    assert body["evidence"][0]["source_type"] == "agent_conversation"
    assert body["evidence"][0]["source_ref"] == "thread-candidate"
    assert body["evidence"][0]["source_description"] == "Candidate evidence"
    assert body["evidence"][0]["body_hash"] == "sha256:candidate"
    assert body["evidence"][0]["actor"] == "ai_agent"
    assert body["evidence"][0]["created_at"] is not None
    assert client.get("/api/observations", params={"subject_entity_id": person["id"]}).json()[
        "total"
    ] == 0

    invalid = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "payload": {"from_entity_id": person["id"]},
            "confidence": 0.5,
            "created_by": "ai_agent",
        },
    )

    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_agent_candidate_requires_traceable_non_empty_evidence(client) -> None:
    person = create_person(client, "Alex")

    missing_evidence = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person["id"],
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "communication_preference",
                "content": "Alex prefers concise follow-ups.",
                "claim_type": "pattern",
            },
            "confidence": 0.72,
            "created_by": "ai_agent",
        },
    )
    assert missing_evidence.status_code == 422
    assert missing_evidence.json()["error"]["code"] == "validation_error"

    weak_episode = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": None,
            "source_description": "Missing source ref",
            "body_excerpt": "Alex prefers concise follow-ups.",
            "body_hash": "sha256:weak",
            "actor": "ai_agent",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    ).json()
    weak_evidence = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person["id"],
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "communication_preference",
                "content": "Alex prefers concise follow-ups.",
                "claim_type": "pattern",
            },
            "evidence": [{"episode_id": weak_episode["id"], "excerpt": " ", "confidence": 0.8}],
            "confidence": 0.72,
            "created_by": "ai_agent",
        },
    )
    assert weak_evidence.status_code == 422
    assert weak_evidence.json()["error"]["code"] == "validation_error"

    manual = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person["id"],
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "communication_preference",
                "content": "Alex prefers concise follow-ups.",
                "claim_type": "pattern",
            },
            "confidence": 0.72,
            "created_by": "user",
        },
    )
    assert manual.status_code == 201


def test_candidate_submit_rejects_semantically_invalid_payloads(client) -> None:
    person = create_person(client, "Alex")
    organization = client.post(
        "/api/entities",
        json={"entity_type": "organization", "display_name": "Acme", "created_by": "user"},
    ).json()

    invalid_relation_type = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "payload": {
                "from_entity_id": person["id"],
                "to_entity_id": person["id"],
                "relation_type": "reply_strategy",
                "claim_text": "This should be an observation.",
                "claim_type": "fact",
            },
            "confidence": 0.5,
            "created_by": "ai_agent",
        },
    )
    assert invalid_relation_type.status_code == 422
    assert invalid_relation_type.json()["error"]["code"] == "validation_error"

    invalid_endpoint_type = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "payload": {
                "from_entity_id": person["id"],
                "to_entity_id": organization["id"],
                "relation_type": "client_contact",
                "claim_text": "Alex is a client contact.",
                "claim_type": "fact",
            },
            "confidence": 0.5,
            "created_by": "ai_agent",
        },
    )
    assert invalid_endpoint_type.status_code == 422
    assert invalid_endpoint_type.json()["error"]["code"] == "validation_error"

    invalid_observation_type = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "reply_strategy",
                "content": "Should use a supported observation type.",
                "claim_type": "pattern",
            },
            "confidence": 0.5,
            "created_by": "ai_agent",
        },
    )
    assert invalid_observation_type.status_code == 422
    assert invalid_observation_type.json()["error"]["code"] == "validation_error"

    invalid_confidence = client.post(
        "/api/candidates",
        json={
            "candidate_type": "new_entity",
            "payload": {"entity_type": "person", "display_name": "Jordan"},
            "confidence": 1.5,
            "created_by": "ai_agent",
        },
    )
    assert invalid_confidence.status_code == 422
    assert invalid_confidence.json()["error"]["code"] == "validation_error"


def test_relationship_edge_edit_accept_rejects_invalid_relation_type_and_audits(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    episode = create_episode(client)
    created = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "payload": {
                "from_entity_id": user["id"],
                "to_entity_id": alex["id"],
                "relation_type": "client_contact",
                "claim_text": "Alex is a client contact.",
                "claim_type": "fact",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex is a client contact.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.7,
            "created_by": "ai_agent",
        },
    )
    assert created.status_code == 201
    candidate = created.json()

    edited = client.post(
        f"/api/candidates/{candidate['id']}/edit-accept",
        json={
            "payload": {
                "from_entity_id": user["id"],
                "to_entity_id": alex["id"],
                "relation_type": "reply_strategy",
                "claim_text": "This should not become an edge.",
                "claim_type": "fact",
            }
        },
    )

    assert edited.status_code == 422
    listed = client.get(
        "/api/agent-operations",
        params={"operation_type": "candidate_edit_accept", "result_status": "rejected"},
    )
    assert listed.status_code == 200
    operation = listed.json()["items"][0]
    assert operation["candidate_id"] == candidate["id"]
    assert operation["request_summary"]["relation_type"] == "reply_strategy"
    assert operation["diagnostics"]["message"] == "Invalid relation_type."
    assert client.get("/api/edges", params={"entity_id": alex["id"]}).json()["total"] == 0


def test_relationship_edge_accept_rejects_legacy_invalid_relation_type(client, database_url) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    with create_session_maker(Settings(database_url=database_url))() as session:
        candidate = Candidate(
            candidate_type="relationship_edge",
            target_entity_id=alex["id"],
            payload={
                "from_entity_id": user["id"],
                "to_entity_id": alex["id"],
                "relation_type": "reply_strategy",
                "claim_text": "This should not become an edge.",
                "claim_type": "fact",
            },
            confidence=0.5,
            sensitivity="medium",
            suggested_action="review",
            created_by="ai_agent",
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    accepted = client.post(f"/api/candidates/{candidate_id}/accept")

    assert accepted.status_code == 422
    listed = client.get(
        "/api/agent-operations",
        params={"operation_type": "candidate_accept", "result_status": "rejected"},
    )
    assert listed.status_code == 200
    operation = listed.json()["items"][0]
    assert operation["candidate_id"] == candidate_id
    assert operation["request_summary"]["relation_type"] == "reply_strategy"
    assert operation["diagnostics"]["message"] == "Invalid relation_type."
    assert client.get("/api/edges", params={"entity_id": alex["id"]}).json()["total"] == 0


def submit_observation_candidate(client, person_id: str, episode_id: str, content: str) -> dict:
    response = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person_id,
            "payload": {
                "subject_entity_id": person_id,
                "observation_type": "communication_preference",
                "content": content,
                "claim_type": "pattern",
            },
            "evidence": [
                {
                    "episode_id": episode_id,
                    "excerpt": content,
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.72,
            "sensitivity": "medium",
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_candidate_list_get_patch_and_delete_archive(client) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)
    candidate = submit_observation_candidate(
        client,
        person["id"],
        episode["id"],
        "Alex prefers concise follow-ups.",
    )

    listed = client.get("/api/candidates", params={"status": "pending"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    fetched = client.get(f"/api/candidates/{candidate['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == candidate["id"]

    patched = client.patch(
        f"/api/candidates/{candidate['id']}",
        json={"suggested_action": "clarify", "sensitivity": "high"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "pending"
    assert patched.json()["suggested_action"] == "clarify"
    assert patched.json()["canonical_record_ref"] is None
    assert patched.json()["resolved_at"] is None

    deleted = client.delete(f"/api/candidates/{candidate['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "archived"

    archived = client.get(f"/api/candidates/{candidate['id']}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_candidate_review_actions_set_resolution_statuses(client) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)
    rejected = submit_observation_candidate(client, person["id"], episode["id"], "Reject me.")
    archived = submit_observation_candidate(client, person["id"], episode["id"], "Archive me.")
    unclear = submit_observation_candidate(client, person["id"], episode["id"], "Clarify me.")
    old = submit_observation_candidate(client, person["id"], episode["id"], "Old candidate.")
    newer = submit_observation_candidate(client, person["id"], episode["id"], "New candidate.")

    reject_response = client.post(
        f"/api/candidates/{rejected['id']}/reject",
        json={"resolution_note": "Incorrect person."},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "rejected"
    assert reject_response.json()["resolved_at"] is not None

    archive_response = client.post(f"/api/candidates/{archived['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"

    clarify_response = client.post(
        f"/api/candidates/{unclear['id']}/needs-clarification",
        json={"resolution_note": "Need to ask who this refers to."},
    )
    assert clarify_response.status_code == 200
    assert clarify_response.json()["status"] == "needs_clarification"

    supersede_response = client.post(
        f"/api/candidates/{old['id']}/supersede",
        json={
            "supersedes_candidate_id": newer["id"],
            "resolution_note": "Replaced by clearer candidate.",
        },
    )
    assert supersede_response.status_code == 200
    assert supersede_response.json()["status"] == "superseded"
    assert supersede_response.json()["supersedes_candidate_id"] == newer["id"]


def test_accept_observation_candidate_writes_canonical_record_and_evidence(
    client,
    database_url,
) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)
    candidate = submit_observation_candidate(
        client,
        person["id"],
        episode["id"],
        "Alex prefers concise follow-ups.",
    )

    accepted = client.post(
        f"/api/candidates/{candidate['id']}/accept",
        json={
            "resolved_by": "ai_agent",
            "resolution_note": "User explicitly confirmed this merge in the current turn.",
        },
    )

    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["canonical_record_ref"].startswith("observations:")
    observation_id = body["canonical_record_ref"].split(":", 1)[1]
    observation = client.get(f"/api/observations/{observation_id}").json()
    assert observation["content"] == "Alex prefers concise follow-ups."
    assert observation["source_candidate_id"] == candidate["id"]

    with create_session_maker(Settings(database_url=database_url))() as session:
        stored = session.get(Observation, observation_id)
        assert stored is not None
        evidence_rows = (
            session.query(ObservationEvidence)
            .filter(ObservationEvidence.observation_id == observation_id)
            .all()
        )
        assert len(evidence_rows) == 1
        assert evidence_rows[0].episode_id == episode["id"]


def test_accept_observation_candidate_preserves_temporal_payload_fields(client) -> None:
    person = create_person(client, "Alex")
    content = (
        "During the week of 2026-06-17 to 2026-06-23 (Asia/Seoul), Alex reports "
        "that abrupt schedule changes feel stressful."
    )
    episode_response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": "thread-temporal-candidate",
            "source_description": "Temporal candidate evidence",
            "body_excerpt": content,
            "body_hash": "sha256:temporal-candidate",
            "actor": "ai_agent",
            "occurred_at": "2026-06-18T00:00:00+09:00",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert episode_response.status_code == 201
    episode = episode_response.json()
    created = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person["id"],
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": content,
                "claim_type": "pattern",
                "occurred_at": "2026-06-17T00:00:00+09:00",
                "valid_from": "2026-06-17T00:00:00+09:00",
                "valid_to": "2026-06-24T00:00:00+09:00",
            },
            "evidence": [{"episode_id": episode["id"], "excerpt": content, "confidence": 0.8}],
            "confidence": 0.72,
            "sensitivity": "medium",
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )
    assert created.status_code == 201
    assert created.json()["payload"]["occurred_at"] == "2026-06-17T00:00:00+09:00"

    accepted = client.post(f"/api/candidates/{created.json()['id']}/accept")

    assert accepted.status_code == 200
    observation_id = accepted.json()["canonical_record_ref"].split(":", 1)[1]
    observation = client.get(f"/api/observations/{observation_id}").json()
    assert observation["occurred_at"].startswith("2026-06-17T00:00:00")
    assert observation["valid_from"].startswith("2026-06-17T00:00:00")
    assert observation["valid_to"].startswith("2026-06-24T00:00:00")


def test_accept_observation_candidate_rejects_invalid_legacy_temporal_payload(
    client,
    database_url,
) -> None:
    person = create_person(client, "Alex")
    with create_session_maker(Settings(database_url=database_url))() as session:
        candidate = Candidate(
            candidate_type="observation",
            target_entity_id=person["id"],
            payload={
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": "Alex followed up recently.",
                "claim_type": "pattern",
                "occurred_at": "not-a-date",
            },
            confidence=0.72,
            sensitivity="medium",
            suggested_action="review",
            created_by="ai_agent",
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    accepted = client.post(f"/api/candidates/{candidate_id}/accept")

    assert accepted.status_code == 422
    assert accepted.json()["error"]["code"] == "validation_error"
    assert accepted.json()["error"]["message"] == "Invalid occurred_at."


def test_edit_accept_validates_edited_payload_and_writes_edited_record(client) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)
    candidate = submit_observation_candidate(client, person["id"], episode["id"], "Draft content.")

    invalid = client.post(
        f"/api/candidates/{candidate['id']}/edit-accept",
        json={"payload": {"subject_entity_id": person["id"]}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    accepted = client.post(
        f"/api/candidates/{candidate['id']}/edit-accept",
        json={
            "payload": {
                "subject_entity_id": person["id"],
                "observation_type": "communication_preference",
                "content": "Edited concise follow-up preference.",
                "claim_type": "pattern",
            },
            "resolution_note": "Edited wording before accepting.",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "edited_accepted"
    observation_id = accepted.json()["canonical_record_ref"].split(":", 1)[1]
    observation = client.get(f"/api/observations/{observation_id}").json()
    assert observation["content"] == "Edited concise follow-up preference."


def test_profile_field_candidate_accept_writes_structured_fact_and_context_card(client) -> None:
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "profile_field",
            "target_entity_id": alex["id"],
            "payload": {
                "entity_id": alex["id"],
                "field_path": "profile.email",
                "fact_type": "email",
                "content": "alex@example.com",
                "value": {"kind": "work", "email": "alex@example.com"},
                "claim_type": "fact",
                "sensitivity": "high",
                "ai_use_policy": "ask_before_use",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex said alex@example.com is the best work email.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.8,
            "sensitivity": "high",
            "created_by": "ai_agent",
        },
    )
    assert candidate.status_code == 201

    accepted = client.post(f"/api/candidates/{candidate.json()['id']}/accept")

    assert accepted.status_code == 200
    assert accepted.json()["canonical_record_ref"].startswith("entity_facts:")
    fact_id = accepted.json()["canonical_record_ref"].split(":", 1)[1]
    fact = client.get(f"/api/entity-facts/{fact_id}").json()
    assert fact["fact_type"] == "email"
    assert fact["content"] == "alex@example.com"
    assert fact["value"] == {
        "field_path": "profile.email",
        "value": {"kind": "work", "email": "alex@example.com"},
    }
    assert fact["claim_type"] == "fact"
    assert fact["confidence"] == 0.8
    assert fact["sensitivity"] == "high"
    assert fact["ai_use_policy"] == "ask_before_use"
    assert fact["source_candidate_id"] == candidate.json()["id"]

    context_card = client.get(f"/api/entities/{alex['id']}/context-card").json()
    assert [item["id"] for item in context_card["profile_facts"]] == [fact_id]


def test_accept_supported_candidate_types_write_matching_canonical_records(
    client,
    database_url,
) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    new_entity = client.post(
        "/api/candidates",
        json={
            "candidate_type": "new_entity",
            "payload": {"entity_type": "person", "display_name": "Jordan"},
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Jordan should be added as a person.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.8,
            "created_by": "ai_agent",
        },
    ).json()
    accepted_entity = client.post(f"/api/candidates/{new_entity['id']}/accept").json()
    assert accepted_entity["canonical_record_ref"].startswith("entities:")

    alias = client.post(
        "/api/candidates",
        json={
            "candidate_type": "alias",
            "target_entity_id": alex["id"],
            "payload": {"entity_id": alex["id"], "alias": "알렉스"},
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex also goes by 알렉스.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.8,
            "created_by": "ai_agent",
        },
    ).json()
    accepted_alias = client.post(f"/api/candidates/{alias['id']}/accept").json()
    alias_id = accepted_alias["canonical_record_ref"].split(":", 1)[1]
    aliases = client.get(f"/api/entities/{alex['id']}/aliases").json()["items"]
    assert any(item["id"] == alias_id and item["source_candidate_id"] == alias["id"] for item in aliases)

    edge = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "target_entity_id": alex["id"],
            "payload": {
                "from_entity_id": user["id"],
                "to_entity_id": alex["id"],
                "relation_type": "client_contact",
                "claim_text": "Alex is a client contact.",
                "claim_type": "fact",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex is a client contact.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.8,
            "created_by": "ai_agent",
        },
    ).json()
    accepted_edge = client.post(f"/api/candidates/{edge['id']}/accept").json()
    edge_id = accepted_edge["canonical_record_ref"].split(":", 1)[1]
    fetched_edge = client.get(f"/api/edges/{edge_id}").json()
    assert fetched_edge["source_candidate_id"] == edge["id"]

    profile = client.post(
        "/api/candidates",
        json={
            "candidate_type": "profile_field",
            "target_entity_id": alex["id"],
            "payload": {
                "entity_id": alex["id"],
                "field_path": "properties.role_note",
                "value": "Former coworker from Acme",
                "claim_type": "fact",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Former coworker from Acme",
                    "confidence": 0.7,
                }
            ],
            "confidence": 0.7,
            "created_by": "ai_agent",
        },
    ).json()
    accepted_profile = client.post(f"/api/candidates/{profile['id']}/accept").json()
    fact_id = accepted_profile["canonical_record_ref"].split(":", 1)[1]
    fact = client.get(f"/api/entity-facts/{fact_id}").json()
    assert fact["source_candidate_id"] == profile["id"]
    assert fact["fact_type"] == "important_context"

    with create_session_maker(Settings(database_url=database_url))() as session:
        assert (
            session.query(EdgeEvidence)
            .filter(EdgeEvidence.edge_id == edge_id, EdgeEvidence.episode_id == episode["id"])
            .count()
            == 1
        )
        assert (
            session.query(EntityFactEvidence)
            .filter(
                EntityFactEvidence.entity_fact_id == fact_id,
                EntityFactEvidence.episode_id == episode["id"],
            )
            .count()
            == 1
        )


def test_candidate_accept_rolls_back_canonical_write_when_evidence_copy_fails(
    client,
    database_url,
    monkeypatch,
) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    episode = create_episode(client)
    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "relationship_edge",
            "target_entity_id": alex["id"],
            "payload": {
                "from_entity_id": user["id"],
                "to_entity_id": alex["id"],
                "relation_type": "client_contact",
                "claim_text": "Alex is a client contact.",
                "claim_type": "fact",
            },
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "Alex is a client contact.",
                    "confidence": 0.8,
                }
            ],
            "confidence": 0.8,
            "created_by": "ai_agent",
        },
    ).json()

    def fail_copy(self, candidate, edge_id):
        raise RuntimeError("simulated evidence failure")

    monkeypatch.setattr(CandidateService, "_copy_edge_evidence", fail_copy)

    with create_session_maker(Settings(database_url=database_url))() as session:
        service = CandidateService(session)
        row = session.get(Candidate, candidate["id"])
        with pytest.raises(RuntimeError, match="simulated evidence failure"):
            service.accept_candidate(row)
        session.rollback()
        persisted_candidate = session.get(Candidate, candidate["id"])
        assert persisted_candidate.status == "pending"
        assert persisted_candidate.canonical_record_ref is None
        orphan_count = (
            session.query(EntityEdge)
            .filter(EntityEdge.source_candidate_id == candidate["id"])
            .count()
        )
        assert orphan_count == 0


def test_accept_merge_candidate_repoints_person_records_and_creates_audit(
    client,
    database_url,
) -> None:
    target = create_person(client, "Alex Kim")
    source = create_person(client, "Alex K.")
    colleague = create_person(client, "Jordan Lee")
    assert client.post(
        f"/api/entities/{source['id']}/aliases",
        json={"alias": "알렉스", "created_by": "user"},
    ).status_code == 201
    source_fact = client.post(
        "/api/entity-facts",
        json={
            "entity_id": source["id"],
            "fact_type": "organization",
            "content": "Example Corp",
            "claim_type": "fact",
            "confidence": 0.9,
            "created_by": "user",
            "source_candidate_id": "candidate-source-fact",
        },
    ).json()
    source_edge = client.post(
        "/api/edges",
        json={
            "from_entity_id": source["id"],
            "to_entity_id": colleague["id"],
            "relation_type": "former_coworker",
            "directed": True,
            "claim_text": "Alex worked with Jordan.",
            "claim_type": "fact",
            "created_by": "user",
        },
    ).json()
    source_observation = client.post(
        "/api/observations",
        json={
            "subject_entity_id": source["id"],
            "related_entities": [{"entity_id": colleague["id"], "role": "related"}],
            "observation_type": "communication_preference",
            "content": "Alex prefers concise follow-ups.",
            "claim_type": "pattern",
            "created_by": "user",
        },
    ).json()
    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "target_entity_id": target["id"],
            "payload": {
                "source_entity_id": source["id"],
                "target_entity_id": target["id"],
                "reason": "Alias and relationship context indicate a duplicate.",
                "fields_to_merge": ["aliases", "profile_facts", "edges", "observations"],
                "risk_notes": ["Reviewed by user."],
            },
            "confidence": 0.91,
            "created_by": "user",
            "suggested_action": "review",
        },
    ).json()

    accepted = client.post(
        f"/api/candidates/{candidate['id']}/accept",
        json={
            "resolved_by": "ai_agent",
            "resolution_note": "User explicitly confirmed this merge in the current turn.",
        },
    )

    assert accepted.status_code == 200
    body = accepted.json()
    assert body["status"] == "accepted"
    assert body["resolved_by"] == "ai_agent"
    assert body["resolution_note"] == "User explicitly confirmed this merge in the current turn."
    assert body["canonical_record_ref"] == f"entities:{target['id']}"
    merged_source = client.get(f"/api/entities/{source['id']}").json()
    assert merged_source["status"] == "merged"
    assert merged_source["confirmation_status"] == "merged"
    assert merged_source["properties"]["merged_entity_ref"] == f"entities:{target['id']}"

    default_people = client.get("/api/entities", params={"entity_type": "person"}).json()
    assert {item["id"] for item in default_people["items"]} == {target["id"], colleague["id"]}
    aliases = client.get(f"/api/entities/{target['id']}/aliases").json()["items"]
    assert any(item["alias"] == "알렉스" for item in aliases)
    target_card = client.get(f"/api/entities/{target['id']}/context-card").json()
    assert [fact["id"] for fact in target_card["profile_facts"]] == [source_fact["id"]]
    assert [edge["id"] for edge in target_card["relationship_edges"]] == [source_edge["id"]]
    assert [item["id"] for item in target_card["communication_context"]] == [
        source_observation["id"]
    ]

    with create_session_maker(Settings(database_url=database_url))() as session:
        fact = session.get(EntityFact, source_fact["id"])
        edge = session.get(EntityEdge, source_edge["id"])
        observation = session.get(Observation, source_observation["id"])
        merge = (
            session.execute(
                text(
                    "select source_entity_id, target_entity_id, canonical_record_ref, "
                    "merge_plan, actor from entity_merges where candidate_id = :candidate_id"
                ),
                {"candidate_id": candidate["id"]},
            )
            .mappings()
            .one()
        )
        assert fact.entity_id == target["id"]
        assert fact.source_candidate_id == "candidate-source-fact"
        assert edge.from_entity_id == target["id"]
        assert observation.subject_entity_id == target["id"]
        assert merge["source_entity_id"] == source["id"]
        assert merge["target_entity_id"] == target["id"]
        assert merge["canonical_record_ref"] == f"entities:{target['id']}"
        assert merge["actor"] == "ai_agent"
        merge_plan = merge["merge_plan"]
        if isinstance(merge_plan, str):
            merge_plan = json.loads(merge_plan)
        assert merge_plan["fields_to_merge"] == [
            "aliases",
            "profile_facts",
            "edges",
            "observations",
        ]


def test_merge_candidate_rejects_self_and_same_entity(client) -> None:
    self_entity = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": "Me",
            "created_by": "system",
            "system_role": "self",
            "is_system": True,
        },
    ).json()
    alex = create_person(client, "Alex")

    same_entity = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "target_entity_id": alex["id"],
            "payload": {
                "source_entity_id": alex["id"],
                "target_entity_id": alex["id"],
                "reason": "No-op merge should be rejected.",
            },
            "confidence": 0.8,
            "created_by": "user",
        },
    )
    assert same_entity.status_code == 422
    assert same_entity.json()["error"]["code"] == "validation_error"

    protected = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "target_entity_id": alex["id"],
            "payload": {
                "source_entity_id": self_entity["id"],
                "target_entity_id": alex["id"],
                "reason": "Protected self cannot be merged.",
            },
            "confidence": 0.8,
            "created_by": "user",
        },
    )
    assert protected.status_code == 403
    assert protected.json()["error"]["code"] == "forbidden"


def test_merge_candidate_accept_deprecates_duplicate_aliases_and_self_edges(client) -> None:
    target = create_person(client, "Alex Kim")
    source = create_person(client, "Alex K.")
    assert client.post(
        f"/api/entities/{target['id']}/aliases",
        json={"alias": "AK", "created_by": "user"},
    ).status_code == 201
    client.post(
        f"/api/entities/{source['id']}/aliases",
        json={"alias": "AK", "created_by": "user"},
    ).json()
    self_edge = client.post(
        "/api/edges",
        json={
            "from_entity_id": source["id"],
            "to_entity_id": target["id"],
            "relation_type": "client_contact",
            "directed": True,
            "claim_text": "Duplicate edge would become a self-edge.",
            "claim_type": "fact",
            "created_by": "user",
        },
    ).json()
    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "target_entity_id": target["id"],
            "payload": {
                "source_entity_id": source["id"],
                "target_entity_id": target["id"],
                "reason": "Alias indicates a duplicate.",
                "fields_to_merge": ["aliases", "edges"],
            },
            "confidence": 0.9,
            "created_by": "user",
        },
    ).json()

    accepted = client.post(f"/api/candidates/{candidate['id']}/accept")

    assert accepted.status_code == 200
    aliases = client.get(f"/api/entities/{target['id']}/aliases").json()["items"]
    assert [alias["alias"] for alias in aliases] == ["AK"]
    deprecated_alias = client.get(f"/api/entities/{source['id']}/aliases")
    assert deprecated_alias.status_code == 200
    assert deprecated_alias.json()["items"] == []
    edge = client.get(f"/api/edges/{self_edge['id']}").json()
    assert edge["status"] == "deprecated"
    assert client.get("/api/edges", params={"entity_id": target["id"]}).json()["items"] == []


def test_merge_candidate_accept_rolls_back_partial_rewrites(
    client,
    database_url,
    monkeypatch,
) -> None:
    target = create_person(client, "Alex Kim")
    source = create_person(client, "Alex K.")
    client.post(
        f"/api/entities/{source['id']}/aliases",
        json={"alias": "알렉스", "created_by": "user"},
    ).json()
    observation = client.post(
        "/api/observations",
        json={
            "subject_entity_id": source["id"],
            "related_entities": [{"entity_id": source["id"], "role": "mentioned"}],
            "observation_type": "communication_preference",
            "content": "Alex prefers concise follow-ups.",
            "claim_type": "pattern",
            "created_by": "user",
        },
    ).json()
    candidate = client.post(
        "/api/candidates",
        json={
            "candidate_type": "merge",
            "target_entity_id": target["id"],
            "payload": {
                "source_entity_id": source["id"],
                "target_entity_id": target["id"],
                "reason": "Alias indicates a duplicate.",
                "fields_to_merge": ["aliases", "observations"],
            },
            "confidence": 0.9,
            "created_by": "user",
        },
    ).json()

    def fail_observation_repoint(self, source_id, target_id):
        raise RuntimeError("simulated merge observation failure")

    monkeypatch.setattr(
        CandidateService,
        "_repoint_merge_observations",
        fail_observation_repoint,
        raising=False,
    )

    with create_session_maker(Settings(database_url=database_url))() as session:
        service = CandidateService(session)
        row = session.get(Candidate, candidate["id"])
        with pytest.raises(RuntimeError, match="simulated merge observation failure"):
            service.accept_candidate(row)
        session.rollback()
        persisted_candidate = session.get(Candidate, candidate["id"])
        assert persisted_candidate.status == "pending"
        assert persisted_candidate.canonical_record_ref is None
        assert session.get(Observation, observation["id"]).subject_entity_id == source["id"]
        related_entity_ids = {
            row.entity_id
            for row in session.query(ObservationEntity)
            .filter(ObservationEntity.observation_id == observation["id"])
            .all()
        }
        assert related_entity_ids == {source["id"]}
        assert client.get(f"/api/entities/{source['id']}").json()["status"] == "active"
        assert (
            session.execute(
                text("select count(*) from entity_merges where candidate_id = :candidate_id"),
                {"candidate_id": candidate["id"]},
            ).scalar_one()
            == 0
        )
        assert client.get(f"/api/entities/{target['id']}/aliases").json()["items"] == []
