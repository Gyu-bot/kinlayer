from datetime import UTC, datetime, timedelta

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import Observation
from kinlayer_backend.services.retrieval import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
    SCORE_WEIGHTS,
    RetrievalService,
)


def create_person(client, name: str, **overrides) -> dict:
    payload = {
        "entity_type": "person",
        "display_name": name,
        "created_by": "user",
        **overrides,
    }
    response = client.post("/api/entities", json=payload)
    assert response.status_code == 201
    return response.json()


def create_alias(client, entity_id: str, alias: str) -> dict:
    response = client.post(
        f"/api/entities/{entity_id}/aliases",
        json={"alias": alias, "created_by": "user"},
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
            "claim_text": "They work together.",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_observation(
    client,
    entity_id: str,
    content: str,
    **overrides,
) -> dict:
    response = client.post(
        "/api/observations",
        json={
            "subject_entity_id": entity_id,
            "observation_type": "recent_interaction",
            "content": content,
            "claim_type": "fact",
            "confidence": 0.9,
            "created_by": "user",
            **overrides,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_retrieval_score_constants_match_prd_values() -> None:
    assert SCORE_WEIGHTS == {
        "entity_hint": 0.25,
        "alias_name": 0.20,
        "semantic_observation": 0.20,
        "recency": 0.15,
        "graph_proximity": 0.10,
        "confirmation_policy": 0.10,
    }
    assert CONFIDENCE_HIGH_THRESHOLD == 0.75
    assert CONFIDENCE_MEDIUM_THRESHOLD == 0.45


def test_confidence_band_boundaries(database_url) -> None:
    with create_session_maker(Settings(database_url=database_url))() as session:
        service = RetrievalService(session)

    assert service.confidence_band_for_score(0.75) == "high"
    assert service.confidence_band_for_score(0.45) == "medium"
    assert service.confidence_band_for_score(0.449) == "low"


def test_exact_normalized_alias_fuzzy_semantic_recency_and_graph_scoring(
    client,
    database_url,
) -> None:
    user = create_person(client, "User", system_role="self", is_system=True)
    alex = create_person(client, "Alex Kim")
    create_alias(client, alex["id"], "AK")
    create_edge(client, user["id"], alex["id"])
    observation = create_observation(
        client,
        alex["id"],
        "Alex prefers concise Korean summaries after investor meetings.",
        occurred_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        recency_weight=0.95,
    )

    settings = Settings(database_url=database_url)
    with create_session_maker(settings)() as session:
        row = session.get(Observation, observation["id"])
        assert row is not None
        row.embedding = "[0.9,0.1,0.0]"
        row.embedding_status = "ready"
        session.commit()

        result = RetrievalService(session).retrieve(
            query="ak concise korean investor summaries",
            entity_hints=[alex["id"]],
            focal_entity_id=user["id"],
            query_embedding=[0.9, 0.1, 0.0],
        )

    match = result.matches[0]
    assert match.entity_id == alex["id"]
    assert match.score_breakdown["entity_hint"] == 0.25
    assert match.score_breakdown["alias_name"] == 0.20
    assert match.score_breakdown["semantic_observation"] == 0.20
    assert match.score_breakdown["recency"] == 0.15
    assert match.score_breakdown["graph_proximity"] == 0.10
    assert match.score_breakdown["confirmation_policy"] == 0.10
    assert match.score == 1.0
    assert match.confidence_band == "high"
    assert "exact_alias" in match.match_reasons
    assert "normalized_alias" in match.match_reasons
    assert "pg_trgm_name_alias" in match.match_reasons
    assert "pgvector_observation" in match.match_reasons
    assert match.observations[0].observation_id == observation["id"]
    assert result.debug["score_weights"] == SCORE_WEIGHTS


def test_policy_penalties_confidence_bands_and_surface_buckets(client, database_url) -> None:
    direct = create_person(client, "Direct Person")
    sensitive = create_person(client, "Sensitive Person", sensitivity="high")
    blocked = create_person(client, "Blocked Person", ai_use_policy="never_surface")
    stale = create_person(client, "Stale Person", confirmation_status="deprecated")
    create_observation(client, direct["id"], "Direct Person likes short updates.")
    create_observation(
        client,
        sensitive["id"],
        "Sensitive Person shared a private concern.",
        sensitivity="high",
        ai_use_policy="ask_before_use",
    )
    create_observation(
        client,
        blocked["id"],
        "Blocked Person said this should never surface.",
        ai_use_policy="never_surface",
    )
    create_observation(
        client,
        stale["id"],
        "Stale Person has old context.",
        status="deprecated",
    )

    with create_session_maker(Settings(database_url=database_url))() as session:
        result = RetrievalService(session).retrieve(
            query="Person short private concern never surface old context",
        )

    buckets = result.surface_buckets
    assert any(item.entity_id == direct["id"] for item in buckets["direct_surface"])
    assert any(item.entity_id == sensitive["id"] for item in buckets["conditional_surface"])
    assert any(item.entity_id == stale["id"] for item in buckets["internal_only"])
    assert any(item.entity_id == blocked["id"] for item in buckets["blocked"])

    blocked_match = next(item for item in result.matches if item.entity_id == blocked["id"])
    stale_match = next(item for item in result.matches if item.entity_id == stale["id"])
    assert blocked_match.penalties["policy_block"] > 0
    assert stale_match.penalties["stale_status"] > 0
    assert blocked_match.confidence_band in {"medium", "low"}


def test_ambiguity_guard_downgrades_implicit_high_confidence(client, database_url) -> None:
    alex = create_person(client, "Alex Kim")
    alexander = create_person(client, "Alexander Kim")
    create_alias(client, alex["id"], "Alex")
    create_alias(client, alexander["id"], "Alex")

    with create_session_maker(Settings(database_url=database_url))() as session:
        result = RetrievalService(session).retrieve(query="Alex")

    assert result.ambiguity_detected is True
    assert len(result.matches) == 2
    assert all(match.confidence_band != "high" for match in result.matches)
    assert all(match.score <= 0.74 for match in result.matches)
