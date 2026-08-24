from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import CurationDecision, CurationRun
from kinlayer_backend.repositories.curation import CurationRepository
from kinlayer_backend.schemas.curation import (
    CurationDecisionStatus,
    CurationRunCreate,
    CurationRunStatus,
)

RUN_TRANSITIONS = {
    "pending": {"planning", "failed"},
    "planning": {"ready", "failed"},
    "ready": {"executing", "completed", "failed"},
    "executing": {"completed", "partial", "failed"},
    "partial": {"executing", "failed"},
    "failed": {"planning", "executing"},
    "completed": set(),
}
DECISION_TRANSITIONS = {
    "proposed": {"allowed", "blocked"},
    "allowed": {"executing", "blocked"},
    "executing": {"executed", "failed"},
    "failed": {"executing"},
    "blocked": set(),
    "executed": set(),
}
RUN_TERMINAL_STATUSES = {"completed", "partial", "failed"}


class CurationService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CurationRepository(session)

    def create_run(self, payload: CurationRunCreate) -> CurationRun:
        decision_payloads = []
        planner = payload.decisions[0].planner if payload.decisions else None
        for decision in payload.decisions:
            if self.repository.get_decision_by_idempotency_key(decision.idempotency_key):
                raise api_error(
                    409,
                    "duplicate_idempotency_key",
                    "Curation decision idempotency_key already exists.",
                )
            decision_payloads.append(decision.model_dump(exclude={"planner"}))
        run_payload = payload.model_dump(exclude={"decisions"})
        run_payload.update(
            status="pending",
            planned_decision_count=len(decision_payloads),
            planner_name=planner.name if planner else None,
            planner_model=planner.model if planner else None,
            planner_version=planner.version if planner else None,
        )
        try:
            run = self.repository.add_run(run_payload, decision_payloads)
            self.session.commit()
            return self.repository.get_run(run.id)
        except IntegrityError as exc:
            self.session.rollback()
            if self._is_idempotency_conflict(exc):
                raise api_error(
                    409,
                    "duplicate_idempotency_key",
                    "Curation decision idempotency_key already exists.",
                ) from exc
            raise

    def get_run(self, run_id: str) -> CurationRun | None:
        return self.repository.get_run(run_id)

    def list_runs(
        self,
        mode: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        return self.repository.list_runs(mode=mode, status=status, limit=limit, offset=offset)

    def transition_run(
        self,
        run: CurationRun,
        target_status: CurationRunStatus | str,
    ) -> CurationRun:
        target = self._status_value(CurationRunStatus, target_status, "run")
        self._ensure_transition(RUN_TRANSITIONS, run.status, target, "run")
        if target == "executing" and run.mode != "apply":
            raise api_error(
                409,
                "invalid_status_transition",
                "Only apply-mode curation runs can enter executing status.",
            )
        if target == "completed" and run.mode == "apply":
            executed_count = self.repository.count_decisions(run.id, "executed")
            blocked_count = self.repository.count_decisions(run.id, "blocked")
            if executed_count + blocked_count != run.planned_decision_count:
                raise api_error(
                    409,
                    "completion_not_ready",
                    "Apply-mode runs require every decision to be executed or blocked.",
                )
            run.executed_decision_count = executed_count
            run.blocked_decision_count = blocked_count
        run.status = target
        run.completed_at = datetime.now(UTC) if target in RUN_TERMINAL_STATUSES else None
        return self._commit_refresh(run)

    def transition_decision(
        self,
        decision: CurationDecision,
        target_status: CurationDecisionStatus | str,
    ) -> CurationDecision:
        target = self._status_value(CurationDecisionStatus, target_status, "decision")
        self._ensure_transition(DECISION_TRANSITIONS, decision.status, target, "decision")
        run = self.repository.get_run(decision.run_id)
        if not run:
            raise api_error(404, "not_found", "Curation run not found.")
        if target == "executing" and run.mode != "apply":
            raise api_error(
                409,
                "invalid_status_transition",
                "Only apply-mode curation decisions can enter executing status.",
            )
        if target == "executed" and (
            not decision.canonical_record_ref or decision.readback_status != "verified"
        ):
            raise api_error(
                409,
                "readback_required",
                "Verified canonical readback is required before execution completes.",
            )
        decision.status = target
        if target == "executed":
            decision.executed_at = datetime.now(UTC)
        try:
            self.session.flush()
            run.executed_decision_count = self.repository.count_decisions(run.id, "executed")
            run.blocked_decision_count = self.repository.count_decisions(run.id, "blocked")
            self.session.commit()
            self.session.refresh(decision)
            return decision
        except HTTPException:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    def _commit_refresh(self, item):
        try:
            self.session.commit()
            self.session.refresh(item)
            return item
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _status_value(enum_type, value, subject: str) -> str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise api_error(422, "validation_error", f"Invalid curation {subject} status.") from exc

    @staticmethod
    def _ensure_transition(transitions: dict, current: str, target: str, subject: str) -> None:
        if target not in transitions.get(current, set()):
            raise api_error(
                409,
                "invalid_status_transition",
                f"Cannot transition curation {subject} from {current} to {target}.",
            )

    @staticmethod
    def _is_idempotency_conflict(exc: IntegrityError) -> bool:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        return constraint_name == "uq_curation_decisions_idempotency_key" or (
            "curation_decisions.idempotency_key" in str(exc.orig)
        )
