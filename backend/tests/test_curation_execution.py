from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
    ObservationEvidence,
)
from kinlayer_backend.schemas.curation import CurationRunCreate
from kinlayer_backend.services.curation import CurationService
from kinlayer_backend.services.ontology import seed_ontology_values

NOW = datetime(2026, 8, 25, tzinfo=UTC)


@pytest.fixture
def session(database_url: str):
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        seed_ontology_values(db_session)
        yield db_session


def setup_person(session: Session) -> Entity:
    entity = Entity(
        entity_type="person",
        display_name="Casey Morgan",
        canonical_name="Casey Morgan",
        created_by="user",
        status="active",
        confirmation_status="confirmed",
        sensitivity="medium",
        ai_use_policy="cautious_use",
    )
    session.add(entity)
    session.commit()
    return entity


def add_candidate(session: Session, entity: Entity, content: str, source_ref: str) -> Candidate:
    episode = Episode(
        source_type="agent_conversation",
        source_ref=source_ref,
        body_excerpt=f"prefix {content} suffix",
        body_hash=f"sha256:{source_ref}",
        actor="user",
        occurred_at=NOW - timedelta(hours=1),
        sensitivity="low",
        retention_policy="excerpt_only",
    )
    candidate = Candidate(
        candidate_type="observation",
        target_entity_id=entity.id,
        payload={
            "subject_entity_id": entity.id,
            "related_entity_ids": [],
            "observation_type": "communication_preference",
            "content": content,
            "claim_type": "preference",
            "ai_use_policy": "cautious_use",
            "sensitivity": "low",
            "occurred_at": "2026-08-24T00:00:00Z",
        },
        confidence=0.9,
        sensitivity="low",
        suggested_action="accept",
        status="pending",
        created_by="ai_agent",
    )
    session.add_all([episode, candidate])
    session.flush()
    session.add(
        CandidateEvidence(
            candidate_id=candidate.id,
            episode_id=episode.id,
            excerpt=content,
            confidence=0.9,
        )
    )
    session.commit()
    session.refresh(candidate)
    return candidate


def create_run(
    session: Session,
    candidates: list[Candidate],
    *,
    action: str,
    proposed_payload: dict,
    key: str,
) -> tuple[CurationService, object]:
    service = CurationService(session)
    run = service.create_run(
        CurationRunCreate.model_validate(
            {
                "mode": "apply",
                "policy_version": "curation-policy-v1",
                "input_candidate_count": len(candidates),
                "decisions": [
                    {
                        "action": action,
                        "risk_level": "low",
                        "candidate_ids": [candidate.id for candidate in candidates],
                        "target_entity_id": candidates[0].target_entity_id,
                        "proposed_payload": proposed_payload,
                        "evidence_episode_ids": sorted(
                            {
                                evidence.episode_id
                                for candidate in candidates
                                for evidence in candidate.evidence
                            }
                        ),
                        "reason_codes": [],
                        "policy_version": "curation-policy-v1",
                        "idempotency_key": key,
                        "planner": {
                            "name": "external-curator",
                            "model": None,
                            "version": "adapter-v1",
                        },
                    }
                ],
            }
        )
    )
    return service, service.evaluate_run(run)


def test_accept_existing_executes_once_and_resume_only_reads_back(session: Session) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-accept",
    )
    service, run = create_run(
        session,
        [candidate],
        action="accept_existing",
        proposed_payload=candidate.payload,
        key="execute:accept",
    )

    executed = service.execute_run(run)
    decision = executed.decisions[0]
    observation_count = session.scalar(select(func.count()).select_from(Observation))

    assert executed.status == "completed"
    assert decision.status == "executed"
    assert decision.readback_status == "verified"
    assert decision.canonical_record_ref.startswith("observations:")
    assert decision.readback_summary["target_entity_id"] == entity.id
    assert session.get(Candidate, candidate.id).status == "accepted"
    assert session.scalar(select(func.count()).select_from(ObservationEvidence)) == 1

    resumed = service.resume_run(executed)
    assert resumed.decisions[0].canonical_record_ref == decision.canonical_record_ref
    assert session.scalar(select(func.count()).select_from(Observation)) == observation_count


def test_database_rejects_duplicate_canonical_source_candidate(session: Session) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-unique-source",
    )
    rows = [
        Observation(
            subject_entity_id=entity.id,
            observation_type="communication_preference",
            content=f"Synthetic canonical {index}",
            claim_type="preference",
            sensitivity="low",
            ai_use_policy="cautious_use",
            status="active",
            source_candidate_id=candidate.id,
            created_by="system",
        )
        for index in (1, 2)
    ]
    session.add(rows[0])
    session.commit()
    session.add(rows[1])
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_edit_accept_existing_reuses_candidate_writer(session: Session) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-edit-accept",
    )
    proposed = {
        **candidate.payload,
        "content": "As of 2026-08-24, Casey prefers concise calendar messages.",
    }
    service, run = create_run(
        session,
        [candidate],
        action="edit_accept_existing",
        proposed_payload=proposed,
        key="execute:edit-accept",
    )

    executed = service.execute_run(run)
    decision = executed.decisions[0]
    observation = session.get(Observation, decision.canonical_record_ref.split(":", 1)[1])

    assert decision.status == "executed"
    assert observation.content == proposed["content"]
    assert session.get(Candidate, candidate.id).status == "edited_accepted"


def test_consolidate_accept_preserves_evidence_and_supersedes_sources(session: Session) -> None:
    entity = setup_person(session)
    first = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-consolidate-1",
    )
    second = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers short calendar messages.",
        "thread-consolidate-2",
    )
    proposed = {
        **first.payload,
        "content": "As of 2026-08-24, Casey prefers concise scheduling messages.",
    }
    service, run = create_run(
        session,
        [first, second],
        action="consolidate_accept",
        proposed_payload=proposed,
        key="execute:consolidate",
    )

    executed = service.execute_run(run)
    decision = executed.decisions[0]
    observation_id = decision.canonical_record_ref.split(":", 1)[1]
    observation = session.get(Observation, observation_id)
    replacement = session.get(Candidate, observation.source_candidate_id)

    assert decision.status == "executed"
    assert observation.content == proposed["content"]
    assert replacement.status == "accepted"
    assert {row.status for row in [session.get(Candidate, first.id), session.get(Candidate, second.id)]} == {
        "superseded"
    }
    assert {
        row.episode_id
        for row in session.scalars(
            select(ObservationEvidence).where(
                ObservationEvidence.observation_id == observation.id
            )
        )
    } == set(decision.evidence_episode_ids)
    assert service.resume_run(executed).decisions[0].canonical_record_ref == (
        decision.canonical_record_ref
    )
    assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_execution_failure_rolls_back_canonical_and_leaves_source_pending(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-rollback",
    )
    service, run = create_run(
        session,
        [candidate],
        action="accept_existing",
        proposed_payload=candidate.payload,
        key="execute:rollback",
    )

    def fail_verification(*_args, **_kwargs):
        raise RuntimeError("simulated verification failure")

    monkeypatch.setattr(service, "_verify_execution", fail_verification)
    result = service.execute_run(run)

    assert result.status == "partial"
    assert result.decisions[0].status == "failed"
    assert result.decisions[0].api_error_code == "execution_failed"
    assert session.get(Candidate, candidate.id).status == "pending"
    assert session.scalar(select(func.count()).select_from(Observation)) == 0

    monkeypatch.undo()
    resumed = service.resume_run(result)
    assert resumed.status == "completed"
    assert resumed.decisions[0].status == "executed"
    assert session.get(Candidate, candidate.id).status == "accepted"
    assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_commit_ack_loss_reconciles_without_second_canonical_write(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-ack-loss",
    )
    service, run = create_run(
        session,
        [candidate],
        action="accept_existing",
        proposed_payload=candidate.payload,
        key="execute:ack-loss",
    )
    run.status = "executing"
    session.commit()
    real_commit = session.commit
    raised = False

    def commit_then_lose_ack():
        nonlocal raised
        real_commit()
        if not raised:
            raised = True
            raise RuntimeError("simulated commit acknowledgement loss")

    monkeypatch.setattr(session, "commit", commit_then_lose_ack)
    result = service.execute_run(run)

    assert result.status == "completed"
    assert result.decisions[0].status == "executed"
    assert result.decisions[0].readback_status == "verified"
    assert session.scalar(select(func.count()).select_from(Observation)) == 1
    assert service.resume_run(result).status == "completed"
    assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_unknown_postcommit_verification_resumes_without_rewrite(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-verification-unknown",
    )
    service, run = create_run(
        session,
        [candidate],
        action="accept_existing",
        proposed_payload=candidate.payload,
        key="execute:verification-unknown",
    )
    def fail_postcommit_verification(_service, decision, *_args, **_kwargs):
        assert decision.status == "executing"
        assert decision.readback_status == "verification_unknown"
        raise RuntimeError("simulated postcommit readback outage")

    monkeypatch.setattr(service, "_postcommit_verify", fail_postcommit_verification)
    partial = service.execute_run(run)

    assert partial.status == "partial"
    assert partial.decisions[0].status == "failed"
    assert partial.decisions[0].readback_status == "verification_unknown"
    assert partial.decisions[0].canonical_record_ref.startswith("observations:")
    assert session.scalar(select(func.count()).select_from(Observation)) == 1

    monkeypatch.undo()
    resumed = service.resume_run(partial)
    assert resumed.status == "completed"
    assert resumed.decisions[0].readback_status == "verified"
    assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_archive_exact_canonical_duplicate_creates_no_second_record(session: Session) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-duplicate",
    )
    canonical = Observation(
        subject_entity_id=entity.id,
        observation_type="communication_preference",
        content=candidate.payload["content"],
        claim_type="preference",
        sensitivity="low",
        ai_use_policy="cautious_use",
        status="active",
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        created_by="user",
    )
    session.add(canonical)
    session.commit()
    service, run = create_run(
        session,
        [candidate],
        action="archive_exact_duplicate",
        proposed_payload={
            **candidate.payload,
            "canonical_record_ref": f"observations:{canonical.id}",
        },
        key="execute:archive-duplicate",
    )

    assert run.decisions[0].status == "allowed"
    executed = service.execute_run(run)

    assert executed.decisions[0].canonical_record_ref == f"observations:{canonical.id}"
    assert session.get(Candidate, candidate.id).status == "archived"
    assert session.scalar(select(func.count()).select_from(Observation)) == 1


def test_archive_exact_duplicate_blocks_mixed_candidate_set(session: Session) -> None:
    entity = setup_person(session)
    exact = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-mixed-exact",
    )
    different = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers voice notes.",
        "thread-mixed-different",
    )
    canonical = Observation(
        subject_entity_id=entity.id,
        observation_type="communication_preference",
        content=exact.payload["content"],
        claim_type="preference",
        sensitivity="low",
        ai_use_policy="cautious_use",
        status="active",
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        created_by="user",
    )
    session.add(canonical)
    session.commit()
    service, run = create_run(
        session,
        [exact, different],
        action="archive_exact_duplicate",
        proposed_payload={
            **exact.payload,
            "canonical_record_ref": f"observations:{canonical.id}",
        },
        key="execute:mixed-duplicate",
    )

    decision = run.decisions[0]
    assert decision.status == "blocked"
    assert "duplicate_not_exact" in decision.reason_codes
    assert session.get(Candidate, exact.id).status == "pending"
    assert session.get(Candidate, different.id).status == "pending"
    with pytest.raises(HTTPException) as exc_info:
        service._execute_duplicate_archive(decision, [exact, different])
    assert exc_info.value.detail["error"]["code"] == "duplicate_not_exact"


def test_exact_readback_rejects_wrong_canonical_content(session: Session) -> None:
    entity = setup_person(session)
    candidate = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers concise scheduling.",
        "thread-wrong-readback",
    )
    service, run = create_run(
        session,
        [candidate],
        action="accept_existing",
        proposed_payload=candidate.payload,
        key="execute:wrong-readback",
    )
    decision = run.decisions[0]
    candidate.status = "accepted"
    wrong = Observation(
        subject_entity_id=entity.id,
        observation_type="communication_preference",
        content="Wrong canonical content.",
        claim_type="preference",
        sensitivity="low",
        ai_use_policy="cautious_use",
        status="active",
        occurred_at=datetime(2026, 8, 24, tzinfo=UTC),
        source_candidate_id=candidate.id,
        created_by="system",
    )
    session.add(wrong)
    session.flush()
    session.add(
        ObservationEvidence(
            observation_id=wrong.id,
            episode_id=candidate.evidence[0].episode_id,
            excerpt=candidate.evidence[0].excerpt,
            confidence=0.9,
        )
    )
    session.flush()

    with pytest.raises(HTTPException) as exc_info:
        service._verify_execution(
            decision,
            [candidate],
            f"observations:{wrong.id}",
        )
    assert exc_info.value.detail["error"]["code"] == "readback_failed"


def test_pending_duplicate_readback_uses_deterministic_retained_source(session: Session) -> None:
    entity = setup_person(session)
    content = "As of 2026-08-24, Casey prefers concise scheduling."
    first = add_candidate(session, entity, content, "thread-pending-duplicate-1")
    second = add_candidate(session, entity, content, "thread-pending-duplicate-2")
    unrelated = add_candidate(
        session,
        entity,
        "As of 2026-08-24, Casey prefers voice notes.",
        "thread-unrelated",
    )
    service, run = create_run(
        session,
        [first, second],
        action="archive_exact_duplicate",
        proposed_payload=first.payload,
        key="execute:pending-duplicate",
    )

    executed = service.execute_run(run)
    decision = executed.decisions[0]
    retained_id = decision.canonical_record_ref.split(":", 1)[1]
    retained = session.get(Candidate, retained_id)
    superseded = next(candidate for candidate in [first, second] if candidate.id != retained_id)

    assert retained.id in {first.id, second.id}
    assert retained.status == "pending"
    assert session.get(Candidate, superseded.id).supersedes_candidate_id == retained.id
    with pytest.raises(HTTPException):
        service._verify_execution(
            decision,
            [session.get(Candidate, first.id), session.get(Candidate, second.id)],
            f"candidates:{unrelated.id}",
        )
