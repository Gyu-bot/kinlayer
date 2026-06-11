from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


def create_person(client, name: str, **overrides) -> dict:
    response = client.post(
        "/api/entities",
        json={
            "entity_type": "person",
            "display_name": name,
            "created_by": "user",
            **overrides,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_alias(client, entity_id: str, alias: str) -> dict:
    response = client.post(
        f"/api/entities/{entity_id}/aliases",
        json={"alias": alias, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def create_fact(client, entity_id: str, fact_type: str, content: str) -> dict:
    response = client.post(
        "/api/entity-facts",
        json={
            "entity_id": entity_id,
            "fact_type": fact_type,
            "content": content,
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_edge(client, from_entity_id: str, to_entity_id: str) -> dict:
    response = client.post(
        "/api/edges",
        json={
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "relation_type": "client_contact",
            "claim_text": "Alex is a client contact.",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_observation(client, entity_id: str, content: str, **overrides) -> dict:
    response = client.post(
        "/api/observations",
        json={
            "subject_entity_id": entity_id,
            "observation_type": "recent_interaction",
            "content": content,
            "claim_type": "fact",
            "created_by": "user",
            **overrides,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_context_retrieve_returns_matches_scores_observations_and_debug(client) -> None:
    alex = create_person(client, "Alex Kim")
    create_alias(client, alex["id"], "AK")
    observation = create_observation(
        client,
        alex["id"],
        "Alex prefers concise Korean summaries after investor meetings.",
        recency_weight=1.0,
    )

    response = client.post(
        "/api/context/retrieve",
        json={
            "query": "AK Korean summaries",
            "entity_hints": [alex["id"]],
            "include_debug": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched_entities"][0]["entity_id"] == alex["id"]
    assert body["matched_entities"][0]["score"] > 0
    assert "exact_alias" in body["matched_entities"][0]["match_reasons"]
    assert "alias_name" in body["matched_entities"][0]["score_breakdown"]
    assert body["observations"][0]["observation_id"] == observation["id"]
    assert "score_weights" in body["debug"]


def test_context_pack_policy_buckets_and_no_final_advice_or_drafts(client) -> None:
    alex = create_person(client, "Alex Kim")
    blocked = create_person(client, "Blocked Kim", ai_use_policy="never_surface")
    create_observation(client, alex["id"], "Alex likes concise status updates.")
    create_observation(
        client,
        blocked["id"],
        "Blocked Kim shared context that should never surface.",
        ai_use_policy="never_surface",
    )

    response = client.post(
        "/api/context/pack",
        json={"query": "Kim concise never surface", "include_debug": True},
    )

    assert response.status_code == 200
    pack = response.json()["context_pack"]
    assert pack["confidence"] in {"high", "medium", "low"}
    assert pack["suggested_response_policy"] in {
        "natural_use",
        "ask_clarifying_question",
        "conditional_use",
        "blocked_by_policy",
    }
    direct_ids = {item["entity_id"] for item in pack["buckets"]["direct_surface"]}
    blocked_ids = {item["entity_id"] for item in pack["buckets"]["blocked"]}
    assert blocked["id"] not in direct_ids
    assert blocked["id"] in blocked_ids
    assert "final_relationship_advice" not in pack
    assert "message_draft" not in pack
    assert response.json()["debug"]["score_weights"]


def test_context_pack_medium_direct_surface_uses_conditional_policy(client) -> None:
    alex = create_person(client, "Alex Kim")
    create_observation(client, alex["id"], "Alex likes concise status updates.")

    response = client.post("/api/context/pack", json={"query": "Alex concise"})

    assert response.status_code == 200
    pack = response.json()["context_pack"]
    assert pack["confidence"] == "medium"
    assert pack["buckets"]["direct_surface"]
    assert pack["suggested_response_policy"] == "conditional_use"


def test_context_pack_excludes_superseded_observations_by_default(client) -> None:
    alex = create_person(client, "Alex Kim")
    active = create_observation(
        client,
        alex["id"],
        "Alex prefers concise async written updates before calls.",
        observation_type="communication_preference",
    )
    superseded = create_observation(
        client,
        alex["id"],
        "Alex prefers long phone calls for all updates.",
        observation_type="communication_preference",
    )
    patched = client.patch(f"/api/observations/{superseded['id']}", json={"status": "superseded"})
    assert patched.status_code == 200

    response = client.post(
        "/api/context/pack",
        json={"query": "Alex updates calls", "entity_hints": [alex["id"]]},
    )

    assert response.status_code == 200
    pack_text = response.text
    assert active["content"] in pack_text
    assert superseded["content"] not in pack_text


def test_context_pack_low_confidence_or_ambiguity_asks_clarifying_question(client) -> None:
    alex = create_person(client, "Alex Kim")
    alexander = create_person(client, "Alexander Kim")
    create_alias(client, alex["id"], "Alex")
    create_alias(client, alexander["id"], "Alex")

    ambiguous = client.post("/api/context/pack", json={"query": "Alex"}).json()
    assert ambiguous["context_pack"]["suggested_response_policy"] == "ask_clarifying_question"
    assert ambiguous["context_pack"]["ambiguity_detected"] is True

    create_person(client, "Nobody")
    low = client.post("/api/context/pack", json={"query": "Nobody"}).json()
    assert low["context_pack"]["suggested_response_policy"] == "ask_clarifying_question"
    assert low["context_pack"]["confidence"] == "low"


def test_context_card_returns_entity_relationship_context_and_provenance(client) -> None:
    user = create_person(client, "User", system_role="self", is_system=True)
    alex = create_person(client, "Alex Kim")
    create_alias(client, alex["id"], "AK")
    fact = create_fact(client, alex["id"], "organization", "Acme")
    edge = create_edge(client, user["id"], alex["id"])
    stable = create_observation(
        client,
        alex["id"],
        "Alex prefers concise updates.",
        observation_type="communication_preference",
    )
    recent = create_observation(
        client,
        alex["id"],
        "Alex followed up yesterday.",
        observation_type="recent_interaction",
    )

    response = client.get(f"/api/entities/{alex['id']}/context-card")

    assert response.status_code == 200
    card = response.json()
    assert card["entity"]["id"] == alex["id"]
    assert card["aliases"][0]["alias"] == "AK"
    assert card["profile_facts"][0]["id"] == fact["id"]
    assert card["relationship_edges"][0]["id"] == edge["id"]
    assert any(item["id"] == stable["id"] for item in card["communication_context"])
    assert any(item["id"] == recent["id"] for item in card["recent_context"])
    assert card["provenance_summary"]["fact_count"] == 1
    assert card["retrieval_hints"]["entity_id"] == alex["id"]
    assert "AK" in card["retrieval_hints"]["aliases"]


def test_context_endpoints_obey_optional_api_token(database_url) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    with TestClient(
        create_app({"database_url": database_url, "api_token": "secret-token"})
    ) as authed_client:
        created = authed_client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Token User", "created_by": "user"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert created.status_code == 201

        assert authed_client.post("/api/context/retrieve", json={"query": "Token"}).status_code == 401
        assert authed_client.post("/api/context/pack", json={"query": "Token"}).status_code == 401
        assert authed_client.get(
            f"/api/entities/{created.json()['id']}/context-card"
        ).status_code == 401

        headers = {"Authorization": "Bearer secret-token"}
        assert authed_client.post(
            "/api/context/retrieve",
            json={"query": "Token"},
            headers=headers,
        ).status_code == 200
        assert authed_client.post(
            "/api/context/pack",
            json={"query": "Token"},
            headers=headers,
        ).status_code == 200
        assert authed_client.get(
            f"/api/entities/{created.json()['id']}/context-card",
            headers=headers,
        ).status_code == 200
