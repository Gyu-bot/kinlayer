import pytest

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import (
    Candidate,
    EdgeEvidence,
    EntityEdge,
    EntityFactEvidence,
    Episode,
    ObservationEvidence,
)
from kinlayer_backend.services.corrections import CorrectionService


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
    assert old_after.json()["valid_to"] is None

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


def test_explicit_correction_records_user_source_and_agent_submitter(client, database_url) -> None:
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
                "source_actor": "user",
                "user_explicit": True,
                "excerpt": "No, Alex is a client contact.",
                "source_ref": "thread-correction-source",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_actor"] == "user"
    assert body["submitted_by"] == "ai_agent"
    with create_session_maker(Settings(database_url=database_url))() as session:
        episode = session.get(Episode, body["episode_id"])
        assert episode.actor == "user"
        assert episode.source_ref == "thread-correction-source"
        assert "submitted_by=ai_agent" in episode.source_description


def test_correction_apply_rolls_back_new_record_when_evidence_link_fails(
    client,
    database_url,
    monkeypatch,
) -> None:
    user = create_person(client, "User")
    alex = create_person(client, "Alex")
    old_edge = create_edge(client, user["id"], alex["id"], "former_coworker")

    def fail_link(self, record_ref, episode_id, excerpt):
        raise RuntimeError("simulated correction evidence failure")

    monkeypatch.setattr(CorrectionService, "_link_evidence", fail_link)

    payload = {
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
            "user_explicit": True,
            "excerpt": "No, Alex is a client contact.",
            "source_ref": "thread-correction-atomic",
        },
        "created_by": "ai_agent",
    }

    with create_session_maker(Settings(database_url=database_url))() as session:
        with pytest.raises(RuntimeError, match="simulated correction evidence failure"):
            CorrectionService(session).apply_correction(payload)
        session.rollback()
        old_after = session.get(EntityEdge, old_edge["id"])
        assert old_after.status == "active"
        assert old_after.invalidated_by_edge_id is None
        assert (
            session.query(EntityEdge)
            .filter(
                EntityEdge.source_candidate_id.is_(None),
                EntityEdge.relation_type == "client_contact",
            )
            .count()
            == 0
        )


def test_invalid_edge_correction_apply_records_submitted_relation_type(client) -> None:
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
                    "relation_type": "reply_strategy",
                    "claim_text": "This should not become an edge.",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "source_ref": "turn-1",
                "user_explicit": True,
                "excerpt": "No, this is about reply strategy.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 422
    listed = client.get("/api/agent-operations", params={"operation_type": "correction_apply"})
    assert listed.status_code == 200
    operation = listed.json()["items"][0]
    assert operation["result_status"] == "rejected"
    assert operation["api_error_code"] == "validation_error"
    assert operation["request_summary"]["old_record_ref"] == f"entity_edges:{old_edge['id']}"
    assert operation["request_summary"]["new_record_type"] == "entity_edges"
    assert operation["request_summary"]["relation_type"] == "reply_strategy"


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


def test_correction_structured_profile_fact_validation_rejects_invalid_new_fact(
    client,
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
                    "fact_type": "email",
                    "content": "alex.example.com",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "No, Alex's email is alex.example.com.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get(f"/api/entity-facts/{old['id']}").json()["status"] == "active"


def test_agent_correction_apply_rejects_non_string_structured_fact_content(client) -> None:
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
                    "fact_type": "email",
                    "content": {"email": "alex@example.com"},
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "Alex email is alex@example.com.",
            },
            "created_by": "ai_agent",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get(f"/api/entity-facts/{old['id']}").json()["status"] == "active"


def test_fact_correction_rejects_entity_mismatch_or_stale_old_record(client) -> None:
    alex = create_person(client, "Alex")
    jordan = create_person(client, "Jordan")
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

    mismatch = client.post(
        "/api/corrections/apply",
        json={
            "old_record_ref": f"entity_facts:{old['id']}",
            "new_record": {
                "record_type": "entity_facts",
                "payload": {
                    "entity_id": jordan["id"],
                    "fact_type": "organization",
                    "content": "New Corp",
                    "claim_type": "fact",
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "user_explicit": True,
                "excerpt": "Alex works with New Corp.",
            },
            "created_by": "ai_agent",
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "validation_error"

    assert client.delete(f"/api/entity-facts/{old['id']}").status_code == 200
    stale = client.post(
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
                "excerpt": "Alex works with New Corp.",
            },
            "created_by": "ai_agent",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "conflict"
    stale_error_codes = {
        error["code"] for error in stale.json()["error"]["details"]["errors"]
    }
    assert stale_error_codes == {"stale_record_ref"}


def test_fact_correction_rejects_wrong_entity_replacement(client) -> None:
    alex = create_person(client, "Alex")
    jordan = create_person(client, "Jordan")
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
                    "entity_id": jordan["id"],
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

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get(f"/api/entity-facts/{old['id']}").json()["status"] == "active"
    visible = client.get(
        "/api/entity-facts",
        params={"entity_id": jordan["id"], "status": "active"},
    ).json()
    assert visible["total"] == 0


def test_fact_correction_rejects_deleted_old_fact(client) -> None:
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
    deleted = client.delete(f"/api/entity-facts/{old['id']}")
    assert deleted.status_code == 200

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

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    response_error_codes = {
        error["code"] for error in response.json()["error"]["details"]["errors"]
    }
    assert response_error_codes == {"stale_record_ref"}
    assert client.get(f"/api/entity-facts/{old['id']}").json()["status"] == "deleted"


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


def test_legacy_correction_replay_and_new_actions_share_change_history(client, database_url):
    from kinlayer_backend.models import EntityFact, MemoryChange

    alex = create_person(client, "Alex")
    blair = create_person(client, "Blair")
    old = client.post("/api/entity-facts", json={
        "entity_id": alex["id"], "fact_type": "organization", "content": "Old Corp",
        "claim_type": "fact", "created_by": "user",
    }).json()
    payload = {
        "old_record_ref": f"entity_facts:{old['id']}",
        "new_record": {"record_type": "entity_facts", "payload": {
            "entity_id": alex["id"], "fact_type": "organization", "content": "New Corp", "claim_type": "fact",
        }},
        "correction_source": {"source_type": "agent_conversation", "user_explicit": True, "excerpt": "Alex works with New Corp."},
    }
    response = client.post("/api/corrections/apply", json=payload)
    assert response.status_code == 200, response.text
    first = response.json()
    replay = client.post("/api/corrections/apply", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first
    payload.update(request_id="legacy-move", action="reattribute", old_record_ref=first["new_record_ref"])
    payload["new_record"]["payload"]["entity_id"] = blair["id"]
    payload["correction_source"]["excerpt"] = "That was Blair's company, not Alex's."
    moved_response = client.post("/api/corrections/apply", json=payload)
    assert moved_response.status_code == 200, moved_response.text
    moved = moved_response.json()
    payload.update(request_id="legacy-retract", action="retract", old_record_ref=moved["new_record_ref"])
    payload.pop("new_record")
    payload["correction_source"]["excerpt"] = "Remove that claim entirely."
    retracted_response = client.post("/api/corrections/apply", json=payload)
    assert retracted_response.status_code == 200, retracted_response.text
    assert retracted_response.json()["new_record_ref"] is None
    assert client.post("/api/corrections/apply", json=payload).json() == retracted_response.json()
    with create_session_maker(Settings(database_url=database_url))() as session:
        row = session.get(EntityFact, moved["new_record_ref"].split(":", 1)[1])
        assert row.entity_id == blair["id"]
        assert row.status == "deleted"
        assert row.valid_to is None
        assert session.query(MemoryChange).count() == 3
        assert session.query(Episode).count() == 3


def test_legacy_correction_request_id_conflict_does_not_mutate(client):
    user, alex = create_person(client, "User"), create_person(client, "Alex")
    old = create_edge(client, user["id"], alex["id"], "coworker")
    payload = {
        "request_id": "legacy-reused", "action": "retract", "old_record_ref": f"entity_edges:{old['id']}",
        "correction_source": {"source_type": "agent_conversation", "user_explicit": True, "excerpt": "Remove that claim."},
    }
    assert client.post("/api/corrections/apply", json=payload).status_code == 200
    payload["correction_source"]["excerpt"] = "Different source under reused id."
    response = client.post("/api/corrections/apply", json=payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"
