from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.models import (
    Base,
    Candidate,
    CandidateEvidence,
    Entity,
    Episode,
    Observation,
)
from kinlayer_backend.schemas.curation import (
    CurationRunCreate,
    CurationSourcePackRequest,
)
from kinlayer_backend.services.curation import CurationService
from kinlayer_backend.services.ontology import seed_ontology_values

AS_OF = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)


@pytest.fixture
def session(database_url: str):
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        seed_ontology_values(db_session)
        yield db_session


def add_person(session: Session, name: str = "Casey Lane") -> Entity:
    entity = Entity(
        entity_type="person",
        display_name=name,
        canonical_name=name,
        created_by="user",
        status="active",
        confirmation_status="confirmed",
        sensitivity="medium",
        ai_use_policy="cautious_use",
    )
    session.add(entity)
    session.commit()
    return entity


def add_episode(
    session: Session,
    *,
    actor: str = "user",
    excerpt: str = "As of 2026-08-24, Casey prefers concise scheduling.",
    source_ref: str = "thread-synthetic",
) -> Episode:
    episode = Episode(
        source_type="agent_conversation",
        source_ref=source_ref,
        source_description="must not leave Kinlayer",
        body_excerpt=f"private prefix {excerpt} private suffix",
        body_hash=f"sha256:{actor}:{source_ref}",
        actor=actor,
        occurred_at=AS_OF - timedelta(hours=1),
        sensitivity="medium",
        retention_policy="excerpt_only",
    )
    session.add(episode)
    session.commit()
    return episode


def observation_payload(entity_id: str, **overrides) -> dict:
    payload = {
        "subject_entity_id": entity_id,
        "related_entity_ids": [],
        "observation_type": "communication_preference",
        "content": "As of 2026-08-24, Casey prefers concise scheduling.",
        "claim_type": "preference",
        "ai_use_policy": "cautious_use",
        "sensitivity": "low",
        "occurred_at": "2026-08-24T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def add_observation_candidate(
    session: Session,
    entity: Entity,
    episodes: list[Episode],
    **overrides,
) -> Candidate:
    payload = overrides.pop("payload", observation_payload(entity.id))
    candidate = Candidate(
        candidate_type="observation",
        target_entity_id=entity.id,
        payload=payload,
        confidence=overrides.pop("confidence", 0.9),
        sensitivity=overrides.pop("sensitivity", payload.get("sensitivity", "low")),
        suggested_action="accept",
        status="pending",
        created_by="ai_agent",
        created_at=AS_OF - timedelta(minutes=10),
        updated_at=AS_OF - timedelta(minutes=10),
        **overrides,
    )
    session.add(candidate)
    session.flush()
    for episode in episodes:
        session.add(
            CandidateEvidence(
                candidate_id=candidate.id,
                episode_id=episode.id,
                excerpt=payload["content"],
                confidence=0.9,
            )
        )
    session.commit()
    session.refresh(candidate)
    return candidate


def decision_payload(candidate: Candidate, key: str, **overrides) -> dict:
    payload = {
        "action": "accept_existing",
        "risk_level": "low",
        "candidate_ids": [candidate.id],
        "target_entity_id": candidate.target_entity_id,
        "proposed_payload": candidate.payload,
        "evidence_episode_ids": [item.episode_id for item in candidate.evidence],
        "reason_codes": ["planner_advisory"],
        "policy_version": "curation-policy-v1",
        "idempotency_key": key,
        "planner": {"name": "external-curator", "model": None, "version": "adapter-v1"},
    }
    payload.update(overrides)
    return payload


def test_source_pack_is_bounded_incremental_and_excludes_non_user_bodies(session: Session) -> None:
    entity = add_person(session)
    user_episode = add_episode(session)
    agent_episode = add_episode(session, actor="ai_agent", source_ref="thread-agent")
    candidate = add_observation_candidate(session, entity, [user_episode, agent_episode])
    session.add(
        Observation(
            subject_entity_id=entity.id,
            observation_type="communication_preference",
            content="  AS OF 2026-08-24, Casey   prefers concise scheduling. ",
            claim_type="preference",
            sensitivity="low",
            ai_use_policy="cautious_use",
            status="active",
            created_by="user",
            occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        )
    )
    for name in ["Casey Park", " casey   park ", "Casey Parks"]:
        session.add(
            Candidate(
                candidate_type="new_entity",
                payload={"entity_type": "person", "display_name": name},
                confidence=0.7,
                sensitivity="low",
                status="pending",
                created_by="ai_agent",
                created_at=AS_OF - timedelta(minutes=5),
                updated_at=AS_OF - timedelta(minutes=5),
            )
        )
    session.commit()

    request = CurationSourcePackRequest(
        as_of=AS_OF,
        limit=20,
        max_age_days=30,
        max_evidence_per_candidate=2,
        max_excerpt_chars=80,
    )
    first = CurationService(session).build_source_pack(request)
    retry = CurationService(session).build_source_pack(request)

    assert first == retry
    assert first["input_candidate_count"] == 4
    assert first["cursor_completed"]["candidate_id"] is not None
    entity_group = next(group for group in first["groups"] if group["target_entity_id"] == entity.id)
    packed_candidate = entity_group["candidates"][0]
    assert packed_candidate["id"] == candidate.id
    assert [item["actor"] for item in packed_candidate["evidence"]] == ["user"]
    assert len(packed_candidate["evidence"][0]["excerpt"]) <= 80
    assert entity_group["signals"]["exact_canonical_duplicate_refs"]
    unresolved = next(group for group in first["groups"] if group["group_key"] == "unresolved:casey park")
    assert len(unresolved["candidates"]) == 2
    assert "ambiguous_identity" in unresolved["reason_codes"]
    spelling_variant = next(
        group for group in first["groups"] if group["group_key"] == "unresolved:casey parks"
    )
    assert len(spelling_variant["candidates"]) == 1
    assert "ambiguous_identity" in spelling_variant["reason_codes"]
    serialized = str(first)
    assert "private prefix" not in serialized
    assert "must not leave Kinlayer" not in serialized

    after = CurationSourcePackRequest(
        as_of=AS_OF,
        cursor=first["cursor_completed"],
        limit=20,
    )
    assert CurationService(session).build_source_pack(after)["input_candidate_count"] == 0


def test_policy_allows_only_safe_user_grounded_observations_and_persists_reasons(
    session: Session,
) -> None:
    entity = add_person(session)
    other_entity = add_person(session, "Jordan Synthetic")
    user_episode = add_episode(session)
    grounded_content = "As of 2026-08-24, Casey repeatedly prefers concise scheduling."
    grounded_episodes = [
        add_episode(session, excerpt=grounded_content, source_ref=f"thread-pattern-{index}")
        for index in (1, 2)
    ]
    agent_episode = add_episode(session, actor="ai_agent", source_ref="thread-agent")

    safe = add_observation_candidate(session, entity, [user_episode])
    pattern = add_observation_candidate(
        session,
        entity,
        [user_episode],
        payload=observation_payload(entity.id, claim_type="pattern"),
    )
    grounded_pattern = add_observation_candidate(
        session,
        entity,
        grounded_episodes,
        payload=observation_payload(
            entity.id,
            claim_type="pattern",
            content=grounded_content,
        ),
    )
    non_user = add_observation_candidate(
        session,
        entity,
        [agent_episode],
        payload=observation_payload(
            entity.id,
            content="As of 2026-08-24, Casey prefers voice notes.",
        ),
    )
    sensitive = add_observation_candidate(
        session,
        entity,
        [user_episode],
        sensitivity="high",
        payload=observation_payload(
            entity.id,
            content="As of 2026-08-24, Casey prefers detailed planning.",
        ),
    )
    transient = add_observation_candidate(
        session,
        entity,
        [user_episode],
        payload=observation_payload(
            entity.id,
            observation_type="follow_up_context",
            content="Casey needs a follow-up soon.",
            occurred_at=None,
        ),
    )
    mixed_subject = add_observation_candidate(
        session,
        entity,
        [user_episode],
        payload=observation_payload(
            other_entity.id,
            content="As of 2026-08-24, Jordan prefers concise scheduling.",
        ),
    )
    structural = Candidate(
        candidate_type="new_entity",
        payload={"entity_type": "person", "display_name": "Director"},
        confidence=0.95,
        sensitivity="low",
        status="pending",
        created_by="ai_agent",
    )
    session.add(structural)
    session.commit()

    decisions = [
        decision_payload(safe, "policy:safe"),
        decision_payload(pattern, "policy:pattern"),
        decision_payload(grounded_pattern, "policy:grounded-pattern"),
        decision_payload(non_user, "policy:non-user"),
        decision_payload(sensitive, "policy:sensitive"),
        decision_payload(transient, "policy:transient"),
        decision_payload(mixed_subject, "policy:mixed-subject"),
        decision_payload(
            structural,
            "policy:structural",
            target_entity_id=None,
            proposed_payload=structural.payload,
            evidence_episode_ids=[],
        ),
    ]
    run = CurationService(session).create_run(
        CurationRunCreate.model_validate(
            {
                "mode": "shadow",
                "policy_version": "curation-policy-v1",
                "input_candidate_count": len(decisions),
                "decisions": decisions,
            }
        )
    )
    evaluated = CurationService(session).evaluate_run(run)
    by_key = {decision.idempotency_key: decision for decision in evaluated.decisions}

    assert by_key["policy:safe"].status == "allowed"
    assert by_key["policy:grounded-pattern"].status == "allowed"
    assert "policy_allowed" in by_key["policy:safe"].reason_codes
    assert "pattern_requires_multiple_episodes" in by_key["policy:pattern"].reason_codes
    assert "non_user_evidence" in by_key["policy:non-user"].reason_codes
    assert "high_sensitivity" in by_key["policy:sensitive"].reason_codes
    assert "missing_temporal_scope" in by_key["policy:transient"].reason_codes
    assert "target_entity_mismatch" in by_key["policy:mixed-subject"].reason_codes
    assert "unsupported_candidate_type" in by_key["policy:structural"].reason_codes
    assert all(
        decision.status == "blocked"
        for key, decision in by_key.items()
        if key not in {"policy:safe", "policy:grounded-pattern"}
    )


@pytest.mark.parametrize(
    "content",
    [
        "As of 2026-08-24, Casey's email is casey@example.test.",
        "As of 2026-08-24, Casey's phone is 010-1234-5678.",
        "As of 2026-08-24, Casey's address is 10 Synthetic Road.",
        "As of 2026-08-24, Casey shared updated contact details.",
    ],
)
def test_low_sensitivity_contact_content_is_never_auto_promoted(
    session: Session,
    content: str,
) -> None:
    entity = add_person(session)
    episode = add_episode(session, excerpt=content, source_ref=f"contact-{len(content)}")
    candidate = add_observation_candidate(
        session,
        entity,
        [episode],
        payload=observation_payload(entity.id, content=content),
    )
    run = CurationService(session).create_run(
        CurationRunCreate.model_validate(
            {
                "mode": "shadow",
                "policy_version": "curation-policy-v1",
                "input_candidate_count": 1,
                "decisions": [decision_payload(candidate, f"contact:{len(content)}")],
            }
        )
    )
    decision = CurationService(session).evaluate_run(run).decisions[0]
    assert decision.status == "blocked"
    assert "high_impact_content" in decision.reason_codes


def test_source_pack_redacts_unsafe_and_bounds_legacy_candidate_payload(session: Session) -> None:
    entity = add_person(session)
    unsafe = Candidate(
        candidate_type="observation",
        target_entity_id=entity.id,
        payload={
            **observation_payload(entity.id),
            "raw_transcript": {"provider_response": "RAW_TRANSCRIPT secret"},
        },
        confidence=0.8,
        sensitivity="low",
        status="pending",
        created_by="user",
        created_at=AS_OF - timedelta(minutes=2),
    )
    long = Candidate(
        candidate_type="observation",
        target_entity_id=entity.id,
        payload=observation_payload(entity.id, content="x" * 10000),
        confidence=0.8,
        sensitivity="low",
        status="pending",
        created_by="user",
        created_at=AS_OF - timedelta(minutes=1),
    )
    session.add_all([unsafe, long])
    session.commit()

    packed = CurationService(session).build_source_pack(
        CurationSourcePackRequest(as_of=AS_OF, limit=10)
    )
    serialized = str(packed)
    assert "RAW_TRANSCRIPT" not in serialized
    assert "secret" not in serialized
    items = {
        item["id"]: item
        for group in packed["groups"]
        for item in group["candidates"]
    }
    assert items[unsafe.id]["payload"] == {}
    assert items[unsafe.id]["validation_errors"][0]["code"] == "unsafe_candidate_payload"
    assert len(items[long.id]["payload"]["content"]) <= 500
