def create_person(client, name: str) -> dict:
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def test_edge_lifecycle_validates_relation_type_and_soft_deletes(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")

    invalid = client.post(
        "/api/edges",
        json={
            "from_entity_id": user["id"],
            "to_entity_id": alex["id"],
            "relation_type": "reply_strategy",
            "claim_text": "This is not a structural edge.",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    created = client.post(
        "/api/edges",
        json={
            "from_entity_id": user["id"],
            "to_entity_id": alex["id"],
            "relation_type": "client_contact",
            "claim_text": "Alex is a client contact.",
            "claim_type": "fact",
            "confidence": 0.95,
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    assert created.status_code == 201
    edge = created.json()
    assert edge["relation_type"] == "client_contact"
    assert edge["directed"] is False

    listed = client.get("/api/edges", params={"entity_id": alex["id"]})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = client.patch(f"/api/edges/{edge['id']}", json={"claim_text": "Updated claim."})
    assert patched.status_code == 200
    assert patched.json()["claim_text"] == "Updated claim."

    deleted = client.delete(f"/api/edges/{edge['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["valid_to"] is not None

    default_list = client.get("/api/edges", params={"entity_id": alex["id"]})
    assert default_list.status_code == 200
    assert default_list.json()["total"] == 0


def test_observation_lifecycle_stores_related_entities_and_soft_deletes(client) -> None:
    subject = create_person(client, "Subject")
    related = create_person(client, "Related")

    created = client.post(
        "/api/observations",
        json={
            "subject_entity_id": subject["id"],
            "related_entities": [
                {"entity_id": related["id"], "role": "related", "confidence": 0.9}
            ],
            "observation_type": "recent_interaction",
            "content": "Related followed up yesterday.",
            "claim_type": "fact",
            "confidence": 0.86,
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    assert created.status_code == 201
    observation = created.json()
    assert observation["embedding_status"] == "pending"
    assert observation["related_entities"][0]["entity_id"] == related["id"]

    listed = client.get("/api/observations", params={"related_entity_id": related["id"]})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    patched = client.patch(
        f"/api/observations/{observation['id']}",
        json={"content": "Related followed up today."},
    )
    assert patched.status_code == 200
    assert patched.json()["content"] == "Related followed up today."
    assert patched.json()["embedding_status"] == "pending"

    deleted = client.delete(f"/api/observations/{observation['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["valid_to"] is not None


def test_episode_create_list_get_exposes_excerpt_and_hash_only(client) -> None:
    created = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": "thread-1",
            "source_description": "Agent conversation excerpt",
            "body_excerpt": "No, Alex is a client contact.",
            "body_hash": "sha256:abc",
            "actor": "user",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert created.status_code == 201
    episode = created.json()
    assert episode["body_excerpt"] == "No, Alex is a client contact."
    assert "body" not in episode

    fetched = client.get(f"/api/episodes/{episode['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["body_hash"] == "sha256:abc"
    assert "body" not in fetched.json()

    listed = client.get("/api/episodes", params={"source_type": "agent_conversation"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
