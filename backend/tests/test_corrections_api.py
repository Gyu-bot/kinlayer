from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import (
    Candidate,
    EdgeEvidence,
    EntityFactEvidence,
    Episode,
    ObservationEvidence,
)


def create_person(client, name: str) -> dict:
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def create_edge(client, from_entity_id: str, to_entity_id: str, relation_type: str) -> dict:
    response = client.post(
        "/api/edges",
        json={
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "relation_type": relation_type,
            "claim_text": f"Alex is a {relation_type}.",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_correction_apply_requires_explicit_user_source(client) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    old_edge = create_edge(client, user["id"], alex["id"], "former_coworker")

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_edges:{old_edge['id']}",
            "new_record": {
                "record_type": "entity_edges",
                "payload": {
                    "from_entity_id": user["id"],
                    "to_entity_id": alex["id"],
                    "relation_type": "client_contact",
                    "claim_text": "Alex is a client contact.",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": False,
                "excerpt": "I think Alex may be a client contact instead.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_explicit_edge_correction_supersedes_old_record_and_links_evidence(
    client,
    database_url,
) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    old_edge = create_edge(client, user["id"], alex["id"], "former_coworker")

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_edges:{old_edge['id']}",
            "new_record": {
                "record_type": "entity_edges",
                "payload": {
                    "from_entity_id": user["id"],
                    "to_entity_id": alex["id"],
                    "relation_type": "client_contact",
                    "claim_text": "Alex is a client contact, not a former coworker.",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "No, Alex is not a former coworker; Alex is a client contact.",
                "source_ref": "thread-correction-1",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_record_ref"] == f"entity_edges:{old_edge['id']}"
    assert body["new_record_ref"].startswith("entity_edges:")
    assert body["episode_id"]

    old_after = client.get(f"/api/edges/{old_edge['id']}")
    assert old_after.status_code == 200
    assert old_after.json()["status"] == "superseded"
    assert old_after.json()["valid_to"] is not None

    new_edge_id = body["new_record_ref"].split(":", 1)[1]
    new_edge = client.get(f"/api/edges/{new_edge_id}")
    assert new_edge.status_code == 200
    assert new_edge.json()["status"] == "active"
    assert new_edge.json()["relation_type"] == "client_contact"
    assert new_edge.json()["claim_text"] == "Alex is a client contact, not a former coworker."
    assert old_after.json()["invalidated_by_edge_id"] == new_edge_id

    visible_edges = client.get("/api/edges", params={"entity_id": alex["id"]})
    assert visible_edges.status_code == 200
    assert visible_edges.json()["total"] == 1
    assert visible_edges.json()["items"][0]["id"] == new_edge_id

    with create_session_maker(Settings(database_url=database_url))() as session:
        episode = session.get(Episode, body["episode_id"])
        assert episode is not None
        assert episode.source_type == "correction"
        assert episode.body_excerpt == (
            "No, Alex is not a former coworker; Alex is a client contact."
        )
        assert episode.body_hash.startswith("sha256:")
        evidence_rows = (
            session.query(EdgeEvidence)
            .filter(EdgeEvidence.edge_id == new_edge_id, EdgeEvidence.episode_id == episode.id)
            .all()
        )
        assert len(evidence_rows) == 1
        assert evidence_rows[0].excerpt == episode.body_excerpt
        assert session.query(Candidate).count() == 0


def test_explicit_observation_correction_replaces_visible_observation_and_links_evidence(
    client,
    database_url,
) -> None:
    alex = create_person(client, "Alex")
    old = client.post(
        "/api/observations",
        json={
            "subject_entity_id": alex["id"],
            "observation_type": "communication_preference",
            "content": "Alex prefers long casual check-ins.",
            "claim_type": "pattern",
            "created_by": "user",
        },
    ).json()

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"observations:{old['id']}",
            "new_record": {
                "record_type": "observations",
                "payload": {
                    "subject_entity_id": alex["id"],
                    "observation_type": "communication_preference",
                    "content": "Alex prefers concise follow-ups.",
                    "claim_type": "pattern",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "Actually, Alex prefers concise follow-ups.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 200
    new_observation_id = response.json()["new_record_ref"].split(":", 1)[1]
    assert client.get(f"/api/observations/{old['id']}").json()["status"] == "superseded"
    visible = client.get("/api/observations", params={"subject_entity_id": alex["id"]}).json()
    assert visible["total"] == 1
    assert visible["items"][0]["id"] == new_observation_id
    assert visible["items"][0]["content"] == "Alex prefers concise follow-ups."

    with create_session_maker(Settings(database_url=database_url))() as session:
        assert (
            session.query(ObservationEvidence)
            .filter(
                ObservationEvidence.observation_id == new_observation_id,
                ObservationEvidence.episode_id == response.json()["episode_id"],
            )
            .count()
            == 1
        )


def test_explicit_fact_correction_replaces_visible_fact_and_links_evidence(
    client,
    database_url,
) -> None:
    alex = create_person(client, "Alex")
    old = client.post(
        "/api/entity-facts",
        json={
            "entity_id": alex["id"],
            "fact_type": "organization",
            "content": "Old Corp",
            "claim_type": "fact",
            "created_by": "user",
        },
    ).json()

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_facts:{old['id']}",
            "new_record": {
                "record_type": "entity_facts",
                "payload": {
                    "entity_id": alex["id"],
                    "fact_type": "organization",
                    "content": "New Corp",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "No, Alex works with New Corp.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 200
    new_fact_id = response.json()["new_record_ref"].split(":", 1)[1]
    assert client.get(f"/api/entity-facts/{old['id']}").json()["status"] == "superseded"
    visible = client.get(
        "/api/entity-facts",
        params={"entity_id": alex["id"], "status": "active"},
    ).json()
    assert visible["total"] == 1
    assert visible["items"][0]["id"] == new_fact_id
    assert visible["items"][0]["content"] == "New Corp"

    with create_session_maker(Settings(database_url=database_url))() as session:
        assert (
            session.query(EntityFactEvidence)
            .filter(
                EntityFactEvidence.entity_fact_id == new_fact_id,
                EntityFactEvidence.episode_id == response.json()["episode_id"],
            )
            .count()
            == 1
        )


def test_correction_apply_rejects_records_without_canonical_evidence_table(client) -> None:
    alex = create_person(client, "Alex")
    alias = client.post(
        f"/api/entities/{alex['id']}/aliases",
        json={"alias": "알렉스", "created_by": "user"},
    ).json()

    response = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_aliases:{alias['id']}",
            "new_record": {
                "record_type": "entity_aliases",
                "payload": {"entity_id": alex["id"], "alias": "Alex K"},
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "Use Alex K as the alias instead.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
