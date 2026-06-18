from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import Candidate, EntityEdge, OntologyRegistryValue


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
            "source_ref": "thread-agent-write-filter",
            "source_description": "Agent write filter evidence",
            "body_excerpt": "Alex used to work with Dana.",
            "body_hash": "sha256:agent-write-filter",
            "actor": "ai_agent",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert response.status_code == 201
    return response.json()


def relationship_candidate(user_id: str, alex_id: str, episode_id: str, relation_type: str) -> dict:
    return {
        "candidate_type": "relationship_edge",
        "target_entity_id": alex_id,
        "payload": {
            "from_entity_id": user_id,
            "to_entity_id": alex_id,
            "relation_type": relation_type,
            "claim_text": "Alex used to work with Dana.",
            "claim_type": "fact",
        },
        "evidence": [
            {
                "episode_id": episode_id,
                "excerpt": "Alex used to work with Dana.",
                "confidence": 0.9,
            }
        ],
        "confidence": 0.86,
        "sensitivity": "medium",
        "suggested_action": "review",
        "created_by": "ai_agent",
    }


def observation_candidate(person_id: str, episode_id: str, content: str) -> dict:
    return {
        "candidate_type": "observation",
        "target_entity_id": person_id,
        "payload": {
            "subject_entity_id": person_id,
            "observation_type": "relationship_pattern",
            "content": content,
            "claim_type": "pattern",
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
        },
        "evidence": [{"episode_id": episode_id, "excerpt": content, "confidence": 0.9}],
        "confidence": 0.72,
        "sensitivity": "medium",
        "suggested_action": "review",
        "created_by": "ai_agent",
    }


def test_agent_write_validate_warns_about_observation_content_quality(client) -> None:
    alex = create_person(client, "Alex")
    episode = create_episode(client)
    content = "그 사람은 전 연인이고 8년 만났고 중학교 영어교사이며 치아바타를 좋아함. 그러니 연락 끊어."

    response = client.post(
        "/api/agent-writes/validate",
        json={"write_type": "candidate", "payload": observation_candidate(alex["id"], episode["id"], content)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    warning_codes = {warning["code"] for warning in body["warnings"]}
    assert "observation_content_dangling_reference" in warning_codes
    assert "observation_content_missing_temporal_scope" in warning_codes
    assert "observation_typed_record_boundary_review" in warning_codes
    assert body["diagnostics"]["observation_content_contract"]["typed_record_boundary"] == [
        "relationship edges",
        "entity facts",
        "relationship properties",
    ]


def test_agent_write_validate_normalizes_candidate_without_persisting(client, database_url) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    response = client.post(
        "/api/agent-writes/validate",
        json={
            "write_type": "candidate",
            "payload": relationship_candidate(
                user["id"],
                alex["id"],
                episode["id"],
                "Former coworker",
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["validated_payload"]["payload"]["relation_type"] == "former_coworker"
    assert body["normalizations_applied"] == [
        {
            "field": "payload.relation_type",
            "original": "Former coworker",
            "normalized": "former_coworker",
            "category": "edge_type",
        }
    ]
    assert "payload.relation_type" in body["controlled_values_checked"]

    with create_session_maker(Settings(database_url=database_url))() as session:
        assert session.query(Candidate).count() == 0


def test_agent_write_validate_rejects_unknown_edge_type_without_guessing(client) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    response = client.post(
        "/api/agent-writes/validate",
        json={
            "write_type": "candidate",
            "payload": relationship_candidate(
                user["id"],
                alex["id"],
                episode["id"],
                "worked together",
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert body["validated_payload"]["payload"]["relation_type"] == "worked together"
    assert body["normalizations_applied"] == []
    assert body["errors"][0]["code"] == "relation_type_not_allowed"
    assert "former_coworker" in body["diagnostics"]["allowed_edge_types"]


def test_agent_write_validate_rejects_ambiguous_controlled_value(client, database_url) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    episode = create_episode(client)
    with create_session_maker(Settings(database_url=database_url))() as session:
        session.add(
            OntologyRegistryValue(
                category="edge_type",
                value="former_coworker_shadow",
                label="Former coworker",
                support_level="supported",
                sort_order=999,
                is_active=True,
            )
        )
        session.commit()

    response = client.post(
        "/api/agent-writes/validate",
        json={
            "write_type": "candidate",
            "payload": relationship_candidate(
                user["id"],
                alex["id"],
                episode["id"],
                "Former coworker",
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is False
    assert any(error["code"] == "ambiguous_controlled_value" for error in body["errors"])


def test_agent_candidate_submit_uses_filter_normalization(client, database_url) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    response = client.post(
        "/api/candidates",
        json=relationship_candidate(user["id"], alex["id"], episode["id"], "Former-coworker"),
    )

    assert response.status_code == 201
    assert response.json()["payload"]["relation_type"] == "former_coworker"
    operations = client.get("/api/agent-operations", params={"operation_type": "candidate_submit"})
    filter_details = operations.json()["items"][0]["related_refs"]["agent_write_filter"]
    assert filter_details["accepted"] is True
    assert filter_details["normalizations_applied"][0]["normalized"] == "former_coworker"
    with create_session_maker(Settings(database_url=database_url))() as session:
        candidate = session.query(Candidate).one()
        assert candidate.payload["relation_type"] == "former_coworker"


def test_agent_candidate_submit_rejects_unknown_edge_type_before_persistence(
    client,
    database_url,
) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    episode = create_episode(client)

    response = client.post(
        "/api/candidates",
        json=relationship_candidate(user["id"], alex["id"], episode["id"], "worked together"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["errors"][0]["code"] == "relation_type_not_allowed"
    with create_session_maker(Settings(database_url=database_url))() as session:
        assert session.query(Candidate).count() == 0


def test_agent_correction_apply_uses_filter_normalization(client, database_url) -> None:
    user = create_person(client, "Dana")
    alex = create_person(client, "Alex")
    old_edge = client.post(
        "/api/edges",
        json={
            "from_entity_id": user["id"],
            "to_entity_id": alex["id"],
            "relation_type": "coworker",
            "claim_text": "Alex works with Dana.",
            "claim_type": "fact",
            "created_by": "user",
        },
    ).json()

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_edges:{old_edge['id']}",
            "new_record": {
                "record_type": "entity_edges",
                "payload": {
                    "from_entity_id": user["id"],
                    "to_entity_id": alex["id"],
                    "relation_type": "Client contact",
                    "claim_text": "Alex is a client contact.",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "source_actor": "user",
                "user_explicit": True,
                "excerpt": "No, Alex is a client contact.",
                "source_ref": "thread-correction-filter",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 200
    new_edge_id = response.json()["new_record_ref"].split(":", 1)[1]
    with create_session_maker(Settings(database_url=database_url))() as session:
        assert session.get(EntityEdge, new_edge_id).relation_type == "client_contact"
