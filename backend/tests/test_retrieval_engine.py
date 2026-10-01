from datetime import UTC, datetime, timedelta

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_session_maker
from kinlayer_backend.models import Entity, Observation
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
            "relation_type": "collaborated_with",
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
    assert "confirmation_policy" not in match.score_breakdown
    assert match.score == 0.9
    assert match.confidence_band == "high"
    assert "exact_alias" in match.match_reasons
    assert "normalized_alias" in match.match_reasons
    assert "pg_trgm_name_alias" in match.match_reasons
    assert "pgvector_observation" in match.match_reasons
    assert match.observations[0].observation_id == observation["id"]
    assert result.debug["score_weights"] == SCORE_WEIGHTS


def test_retired_policy_and_confirmation_do_not_change_retrieval(client, database_url) -> None:
    person = create_person(client, "Policy Fixture")
    record = create_observation(client, person["id"], "policy fixture context", recency_weight=1.0)
    create_person(client, "Unrelated Name")
    with create_session_maker(Settings(database_url=database_url))() as session:
        entity = session.get(Entity, person["id"])
        observation = session.get(Observation, record["id"])
        service = RetrievalService(session)
        baseline = service.retrieve(query="policy fixture context", entity_hints=[person["id"]])
        baseline_match = baseline.matches[0]
        for policy in ("freely_use", "cautious_use", "ask_before_use", "never_surface"):
            for confirmation in ("confirmed", "candidate", "rejected", "deprecated", "disputed"):
                entity.ai_use_policy = policy
                entity.confirmation_status = confirmation
                observation.ai_use_policy = policy
                session.commit()
                current = service.retrieve(query="policy fixture context", entity_hints=[person["id"]])
                assert current.matches == baseline.matches
                assert current.surface_buckets["blocked"] == []
                assert current.surface_buckets["internal_only"] == []
        assert baseline_match.score == 0.8
        assert baseline_match.confidence_band == "high"
        assert baseline_match.penalties == {}
        assert [match.entity_id for match in baseline.matches] == [person["id"]]
        assert service.retrieve(query="unmatched zzqx tokens").matches == []


def test_inactive_observations_do_not_poison_current_person_and_disputed_is_labeled(
    client, database_url,
) -> None:
    person = create_person(client, "State Fixture")
    active = create_observation(client, person["id"], "current context", recency_weight=1.0)
    old_records = [
        create_observation(client, person["id"], "old context", status=status)
        for status in ("superseded", "deleted", "deprecated")
    ]
    disputed = create_observation(client, person["id"], "disputed context", status="disputed")
    with create_session_maker(Settings(database_url=database_url))() as session:
        for record in old_records:
            row = session.get(Observation, record["id"])
            row.ai_use_policy = "never_surface"
        session.commit()
        current = RetrievalService(session).retrieve(query="current context", entity_hints=[person["id"]])
        ids = {item.observation_id for item in current.matches[0].observations}
        assert active["id"] in ids
        assert not ids.intersection(record["id"] for record in old_records)
        assert "policy_block" not in current.matches[0].penalties
        disputed_result = RetrievalService(session).retrieve(query="disputed context")
        disputed_item = next(
            item for item in disputed_result.matches[0].observations
            if item.observation_id == disputed["id"]
        )
        assert disputed_item.status == "disputed"
        assert disputed_result.matches[0].surface_bucket == "conditional_surface"


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
