from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.models import Base, Candidate, CurationDecision, CurationRun, Observation
from kinlayer_backend.schemas.curation import (
    CurationDecisionCreate,
    CurationRunCreate,
)
from kinlayer_backend.services.curation import CurationService


def run_payload(**overrides):
    started_at = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    payload = {
        "mode": "shadow",
        "cursor_started_at": started_at,
        "cursor_started_id": "candidate-001",
        "cursor_completed_at": started_at + timedelta(minutes=1),
        "cursor_completed_id": "candidate-002",
        "policy_version": "curation-policy-v1",
        "input_candidate_count": 2,
        "diagnostics": {"source": "focused-test"},
        "decisions": [decision_payload()],
    }
    payload.update(overrides)
    return payload


def decision_payload(**overrides):
    payload = {
        "action": "defer",
        "risk_level": "medium",
        "candidate_ids": ["candidate-001"],
        "target_entity_id": None,
        "proposed_payload": {"reason": "insufficient evidence"},
        "evidence_episode_ids": ["episode-001"],
        "reason_codes": ["needs_source_lookup"],
        "policy_version": "curation-policy-v1",
        "idempotency_key": "curation:decision:001",
        "planner": {
            "name": "external-curator",
            "model": "provider-neutral-model",
            "version": "adapter-v1",
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def session(database_url: str):
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db_session:
        yield db_session


def test_curation_models_define_durable_fields_constraints_and_indexes(database_url: str) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {"curation_runs", "curation_decisions"} <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("curation_runs")} == {
        "id",
        "mode",
        "status",
        "cursor_started_at",
        "cursor_started_id",
        "cursor_completed_at",
        "cursor_completed_id",
        "policy_version",
        "planner_name",
        "planner_model",
        "planner_version",
        "input_candidate_count",
        "planned_decision_count",
        "executed_decision_count",
        "blocked_decision_count",
        "error_code",
        "diagnostics",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    }
    decision_columns = {column["name"] for column in inspector.get_columns("curation_decisions")}
    assert decision_columns == {
        "id",
        "run_id",
        "action",
        "status",
        "risk_level",
        "candidate_ids",
        "target_entity_id",
        "proposed_payload",
        "evidence_episode_ids",
        "reason_codes",
        "policy_version",
        "idempotency_key",
        "canonical_record_ref",
        "readback_status",
        "readback_summary",
        "api_error_code",
        "created_at",
        "updated_at",
        "executed_at",
    }
    assert not decision_columns & {
        "raw_prompt",
        "provider_request",
        "provider_response",
        "session_content",
    }
    assert {index["name"] for index in inspector.get_indexes("curation_runs")} >= {
        "ix_curation_runs_status"
    }
    assert {index["name"] for index in inspector.get_indexes("curation_decisions")} >= {
        "ix_curation_decisions_run_id",
        "ix_curation_decisions_status",
    }
    assert any(
        constraint["name"] == "uq_curation_decisions_idempotency_key"
        for constraint in inspector.get_unique_constraints("curation_decisions")
    )
    assert CurationRun.__table__.columns["status"].default.arg == "pending"
    assert CurationDecision.__table__.columns["status"].default.arg == "proposed"


def test_curation_schemas_reject_invalid_enums_cursors_and_raw_provider_fields() -> None:
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(run_payload(mode="live"))
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(run_payload(cursor_started_id=None))
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(
            run_payload(
                cursor_completed_at=datetime(2026, 8, 23, tzinfo=UTC),
                cursor_completed_id="candidate-999",
            )
        )
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(run_payload(raw_provider_response={"secret": True}))
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(
            run_payload(diagnostics={"nested": [{"rawProviderRequest": "full prompt secret"}]})
        )
    with pytest.raises(ValidationError):
        CurationRunCreate.model_validate(
            run_payload(diagnostics={"nested": ["providerRequest secret"]})
        )
    with pytest.raises(ValidationError):
        CurationDecisionCreate.model_validate(
            decision_payload(
                proposed_payload={
                    "nested": [{"raw_provider_request": "full prompt secret"}]
                }
            )
        )
    with pytest.raises(ValidationError):
        CurationDecisionCreate.model_validate(decision_payload(action="rewrite_canonical"))


def test_curation_run_and_decision_round_trip(session: Session) -> None:
    service = CurationService(session)
    created = service.create_run(CurationRunCreate.model_validate(run_payload()))

    fetched = service.get_run(created.id)
    assert fetched is not None
    assert fetched.mode == "shadow"
    assert fetched.status == "pending"
    assert fetched.policy_version == "curation-policy-v1"
    assert fetched.planner_name == "external-curator"
    assert fetched.planner_model == "provider-neutral-model"
    assert fetched.planner_version == "adapter-v1"
    assert fetched.input_candidate_count == 2
    assert fetched.planned_decision_count == 1
    assert fetched.executed_decision_count == 0
    assert fetched.blocked_decision_count == 0
    assert fetched.diagnostics == {"source": "focused-test"}
    assert len(fetched.decisions) == 1

    decision = fetched.decisions[0]
    assert decision.action == "defer"
    assert decision.status == "proposed"
    assert decision.candidate_ids == ["candidate-001"]
    assert decision.evidence_episode_ids == ["episode-001"]
    assert decision.reason_codes == ["needs_source_lookup"]
    assert decision.policy_version == fetched.policy_version
    assert decision.idempotency_key == "curation:decision:001"


def test_duplicate_decision_idempotency_key_is_rejected_and_session_recovers(
    session: Session,
) -> None:
    service = CurationService(session)
    first = service.create_run(CurationRunCreate.model_validate(run_payload()))

    duplicate = run_payload(
        decisions=[decision_payload(candidate_ids=["candidate-002"])],
        cursor_started_id="candidate-002",
        cursor_completed_id="candidate-003",
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_run(CurationRunCreate.model_validate(duplicate))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"]["code"] == "duplicate_idempotency_key"
    assert service.get_run(first.id) is not None
    assert session.query(CurationRun).count() == 1
    assert session.query(CurationDecision).count() == 1


def test_non_idempotency_integrity_errors_are_not_misreported(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CurationService(session)
    database_error = IntegrityError("insert", {}, Exception("different constraint"))

    def fail_add_run(*_args, **_kwargs):
        raise database_error

    monkeypatch.setattr(service.repository, "add_run", fail_add_run)

    with pytest.raises(IntegrityError) as exc_info:
        service.create_run(CurationRunCreate.model_validate(run_payload()))
    assert exc_info.value is database_error


def test_curation_status_transitions_are_guarded_and_update_counts(session: Session) -> None:
    service = CurationService(session)
    run = service.create_run(CurationRunCreate.model_validate(run_payload()))
    decision = run.decisions[0]

    with pytest.raises(HTTPException) as run_error:
        service.transition_run(run, "executing")
    assert run_error.value.status_code == 409
    assert run.status == "pending"

    service.transition_run(run, "planning")
    service.transition_run(run, "ready")
    service.transition_decision(decision, "blocked")
    service.transition_run(run, "completed")

    assert decision.executed_at is None
    assert run.executed_decision_count == 0
    assert run.blocked_decision_count == 1
    assert run.completed_at is not None
    assert run.cursor_completed_id == "candidate-002"

    with pytest.raises(HTTPException) as decision_error:
        service.transition_decision(decision, "executing")
    assert decision_error.value.status_code == 409
    assert decision.status == "blocked"


def test_shadow_run_cannot_enter_execution_status(session: Session) -> None:
    service = CurationService(session)
    run = service.create_run(CurationRunCreate.model_validate(run_payload()))
    decision = run.decisions[0]
    service.transition_run(run, "planning")
    service.transition_run(run, "ready")
    service.transition_decision(decision, "allowed")

    with pytest.raises(HTTPException) as run_error:
        service.transition_run(run, "executing")
    with pytest.raises(HTTPException) as decision_error:
        service.transition_decision(decision, "executing")

    assert run_error.value.detail["error"]["code"] == "invalid_status_transition"
    assert decision_error.value.detail["error"]["code"] == "invalid_status_transition"
    assert run.status == "ready"
    assert decision.status == "allowed"


def test_executed_decision_requires_verified_canonical_readback(session: Session) -> None:
    service = CurationService(session)
    run = service.create_run(
        CurationRunCreate.model_validate(run_payload(mode="apply"))
    )
    decision = run.decisions[0]
    service.transition_run(run, "planning")
    service.transition_run(run, "ready")
    service.transition_decision(decision, "allowed")

    with pytest.raises(HTTPException) as completion_error:
        service.transition_run(run, "completed")
    assert completion_error.value.detail["error"]["code"] == "completion_not_ready"
    assert run.status == "ready"

    service.transition_run(run, "executing")
    service.transition_decision(decision, "executing")

    with pytest.raises(HTTPException) as error:
        service.transition_decision(decision, "executed")
    assert error.value.detail["error"]["code"] == "readback_required"
    assert decision.status == "executing"

    decision.canonical_record_ref = "observations:synthetic"
    decision.readback_status = "verified"
    service.transition_decision(decision, "executed")
    assert decision.executed_at is not None
    service.transition_run(run, "completed")
    assert run.status == "completed"


def test_curation_read_api_lists_and_returns_persisted_runs(client) -> None:
    with client.app.state.session_factory() as session:
        created = CurationService(session).create_run(
            CurationRunCreate.model_validate(run_payload())
        )
        run_id = created.id

    listed = client.get("/api/curation/runs", params={"mode": "shadow", "status": "pending"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == run_id
    assert "decisions" not in listed.json()["items"][0]

    fetched = client.get(f"/api/curation/runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["decisions"][0]["idempotency_key"] == "curation:decision:001"

    missing = client.get("/api/curation/runs/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_service_resume_recovers_pending_and_planning_shadow_runs_idempotently(
    session: Session,
) -> None:
    service = CurationService(session)
    candidate = Candidate(
        candidate_type="new_entity",
        payload={"entity_type": "person", "display_name": "Casey Recovery"},
        confidence=0.8,
        sensitivity="low",
        status="pending",
        created_by="user",
    )
    session.add(candidate)
    session.commit()
    candidate_payload = dict(candidate.payload)
    pending_payload = run_payload(
        mode="shadow",
        decisions=[
            decision_payload(
                candidate_ids=[candidate.id],
                proposed_payload=candidate.payload,
                target_entity_id=None,
            )
        ],
    )
    pending = service.create_run(
        CurationRunCreate.model_validate(pending_payload)
    )
    decision_count = session.query(CurationDecision).count()

    with pytest.raises(HTTPException) as stale_error:
        service.resume_run(
            pending,
            server_mode="shadow",
            policy_version="curation-policy-v2",
        )
    assert stale_error.value.detail["error"]["code"] == "curation_policy_mismatch"
    session.expire_all()
    assert service.get_run(pending.id).status == "pending"

    recovered = service.resume_run(
        pending,
        server_mode="shadow",
        policy_version="curation-policy-v1",
    )
    repeated = service.resume_run(
        recovered,
        server_mode="shadow",
        policy_version="curation-policy-v1",
    )

    assert recovered.status == "ready"
    assert recovered.decisions[0].status == "blocked"
    assert repeated.id == recovered.id
    assert repeated.status == "ready"
    assert session.query(CurationDecision).count() == decision_count
    assert session.query(Observation).count() == 0
    persisted_candidate = session.get(Candidate, candidate.id)
    assert persisted_candidate.status == "pending"
    assert persisted_candidate.payload == candidate_payload
    assert persisted_candidate.canonical_record_ref is None
    session.expire_all()
    persisted_run = service.get_run(recovered.id)
    assert persisted_run.status == "ready"
    assert persisted_run.decisions[0].id == recovered.decisions[0].id
    assert persisted_run.decisions[0].status == "blocked"

    planning_payload = run_payload(
        mode="shadow",
        decisions=[
            decision_payload(
                idempotency_key="curation:decision:planning",
                candidate_ids=[candidate.id],
                proposed_payload=candidate.payload,
                target_entity_id=None,
            )
        ],
    )
    planning = service.create_run(CurationRunCreate.model_validate(planning_payload))
    planning.status = "planning"
    session.commit()

    recovered_planning = service.resume_run(
        planning,
        server_mode="shadow",
        policy_version="curation-policy-v1",
    )
    assert recovered_planning.status == "ready"
    assert recovered_planning.decisions[0].status == "blocked"
    assert session.query(Observation).count() == 0


def test_service_source_window_requires_exact_once_candidate_coverage(session: Session) -> None:
    service = CurationService(session)
    candidates = [
        Candidate(
            candidate_type="new_entity",
            payload={"entity_type": "person", "display_name": f"Casey Coverage {index}"},
            confidence=0.8,
            sensitivity="low",
            status="pending",
            created_by="user",
        )
        for index in range(3)
    ]
    session.add_all(candidates)
    session.commit()
    ordered = sorted(candidates, key=lambda candidate: (candidate.created_at, candidate.id))
    packed_ids = [candidate.id for candidate in ordered[:2]]
    outside_id = ordered[2].id
    cursor_started = {"created_at": ordered[0].created_at, "candidate_id": ""}
    cursor_completed = {
        "created_at": ordered[1].created_at,
        "candidate_id": ordered[1].id,
    }

    def plan(
        memberships: list[list[str]],
        *,
        input_count: int = 2,
        action: str = "defer",
    ) -> CurationRunCreate:
        return CurationRunCreate.model_validate(
            {
                "mode": "shadow",
                "cursor_started_at": cursor_started["created_at"],
                "cursor_started_id": cursor_started["candidate_id"],
                "cursor_completed_at": cursor_completed["created_at"],
                "cursor_completed_id": cursor_completed["candidate_id"],
                "policy_version": "curation-policy-v1",
                "input_candidate_count": input_count,
                "decisions": [
                    {
                        "action": action,
                        "risk_level": "low",
                        "candidate_ids": candidate_ids,
                        "target_entity_id": None,
                        "proposed_payload": {},
                        "evidence_episode_ids": [],
                        "reason_codes": [],
                        "policy_version": "curation-policy-v1",
                        "idempotency_key": f"coverage:{index}:{action}",
                        "planner": {"name": "test", "model": None, "version": "v1"},
                    }
                    for index, candidate_ids in enumerate(memberships)
                ],
            }
        )

    service.validate_run_source_window(plan([[packed_ids[0]], [packed_ids[1]]]))
    service.validate_run_source_window(
        plan([packed_ids], action="consolidate_accept")
    )

    failures = [
        (plan([[packed_ids[0]]]), "source_pack_candidate_coverage_mismatch"),
        (
            plan([[packed_ids[0]], packed_ids]),
            "duplicate_candidate_membership",
        ),
        (plan([[packed_ids[0]], [packed_ids[1]]], input_count=1), "source_pack_count_mismatch"),
        (
            plan([[packed_ids[0]], [packed_ids[1]], [outside_id]]),
            "candidate_outside_source_pack",
        ),
    ]
    for payload, expected_code in failures:
        with pytest.raises(HTTPException) as exc_info:
            service.validate_run_source_window(payload)
        assert exc_info.value.detail["error"]["code"] == expected_code

    empty = CurationRunCreate.model_validate(empty_plan := {
        "mode": "shadow",
        "policy_version": "curation-policy-v1",
        "input_candidate_count": 0,
        "decisions": [],
    })
    service.validate_run_source_window(empty)
    empty_plan["input_candidate_count"] = 1
    with pytest.raises(HTTPException) as empty_error:
        service.validate_run_source_window(CurationRunCreate.model_validate(empty_plan))
    assert empty_error.value.detail["error"]["code"] == "source_pack_empty_run_mismatch"
