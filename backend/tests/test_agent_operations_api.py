from __future__ import annotations

import json


def create_person(client, name: str) -> dict:
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def create_episode(client, excerpt: str = "Alex prefers concise follow-ups.") -> dict:
    response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": "thread-agent-write",
            "source_description": "Agent write evidence",
            "body_excerpt": excerpt,
            "body_hash": "sha256:agent-write",
            "actor": "ai_agent",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert response.status_code == 201
    return response.json()


def submit_observation_candidate(client, person_id: str, episode_id: str) -> dict:
    response = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": person_id,
            "payload": {
                "subject_entity_id": person_id,
                "observation_type": "communication_preference",
                "content": "Alex prefers concise follow-ups.",
                "claim_type": "pattern",
                "sensitivity": "medium",
                "ai_use_policy": "cautious_use",
            },
            "evidence": [
                {
                    "episode_id": episode_id,
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
    assert response.status_code == 201
    return response.json()


def test_agent_write_operations_list_and_export_success_and_rejection(client) -> None:
    person = create_person(client, "Alex")
    episode = create_episode(client)
    candidate = submit_observation_candidate(client, person["id"], episode["id"])

    accepted = client.post(f"/api/candidates/{candidate['id']}/accept")
    assert accepted.status_code == 200
    canonical_record_ref = accepted.json()["canonical_record_ref"]

    invalid = client.post(
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
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": "This should be an observation.",
                    "confidence": 0.5,
                }
            ],
            "confidence": 0.5,
            "created_by": "ai_agent",
        },
    )
    assert invalid.status_code == 422

    listed = client.get("/api/agent-operations", params={"limit": 20})
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 3

    operations = body["items"]
    accepted_operation = next(
        item for item in operations if item["operation_type"] == "candidate_accept"
    )
    rejected_operation = next(
        item
        for item in operations
        if item["operation_type"] == "candidate_submit" and item["result_status"] == "rejected"
    )

    assert accepted_operation["actor"] == "ai_agent"
    assert accepted_operation["candidate_id"] == candidate["id"]
    assert accepted_operation["episode_id"] == episode["id"]
    assert accepted_operation["canonical_record_ref"] == canonical_record_ref
    assert accepted_operation["result_status"] == "success"
    assert accepted_operation["request_summary"]["candidate_type"] == "observation"
    assert accepted_operation["bounded_excerpt"] == "Alex prefers concise follow-ups."

    assert rejected_operation["actor"] == "ai_agent"
    assert rejected_operation["api_error_code"] == "validation_error"
    assert rejected_operation["diagnostics"]["message"] == "Agent write validation failed."
    assert any(
        error["code"] == "relation_type_not_allowed"
        for error in rejected_operation["diagnostics"]["details"]["errors"]
    )
    assert rejected_operation["request_summary"]["relation_type"] == "reply_strategy"
    assert "body_excerpt" not in rejected_operation["request_summary"]

    exported = client.get("/api/agent-operations/export", params={"format": "jsonl"})
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in exported.text.splitlines()]

    manifest = lines[0]
    assert manifest["record_type"] == "manifest"
    assert manifest["schema_version"] == "agent_write_operations.v1"
    assert manifest["scope"] == "agent_write_operations_only"

    records = [line for line in lines[1:] if line["record_type"] == "agent_write_operation"]
    assert any(record["candidate_id"] == candidate["id"] for record in records)
    assert any(record["result_status"] == "rejected" for record in records)
    assert all("retrieval" not in record["operation_type"] for record in records)
