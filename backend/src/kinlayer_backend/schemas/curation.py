from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from kinlayer_backend.schemas.common import APIModel, ListResponse


class CurationModel(APIModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class CurationMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"
    APPLY = "apply"


class CurationRunStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    READY = "ready"
    EXECUTING = "executing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class CurationAction(StrEnum):
    ACCEPT_EXISTING = "accept_existing"
    EDIT_ACCEPT_EXISTING = "edit_accept_existing"
    CONSOLIDATE_ACCEPT = "consolidate_accept"
    ARCHIVE_EXACT_DUPLICATE = "archive_exact_duplicate"
    MARK_NEEDS_CLARIFICATION = "mark_needs_clarification"
    DEFER = "defer"
    RECOMMEND_MERGE_REVIEW = "recommend_merge_review"
    RECOMMEND_CONFLICT_REVIEW = "recommend_conflict_review"


class CurationDecisionStatus(StrEnum):
    PROPOSED = "proposed"
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class CurationRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CurationCursor(CurationModel):
    created_at: datetime
    candidate_id: str


class CurationSourcePackRequest(CurationModel):
    cursor: CurationCursor | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limit: int = Field(default=50, ge=1, le=200)
    max_age_days: int = Field(default=30, ge=1, le=365)
    max_evidence_per_candidate: int = Field(default=5, ge=1, le=20)
    max_excerpt_chars: int = Field(default=500, ge=1, le=500)


class CurationSourceEvidenceRead(CurationModel):
    candidate_evidence_id: str
    episode_id: str
    excerpt: str
    confidence: float | None = None
    source_type: str
    source_ref: str | None = None
    body_hash: str
    actor: str
    occurred_at: datetime | None = None
    ingested_at: datetime
    created_at: datetime


class CurationSourceCandidateRead(CurationModel):
    id: str
    candidate_type: str
    target_entity_id: str | None = None
    payload: dict[str, Any]
    confidence: float
    sensitivity: str
    suggested_action: str | None = None
    status: str
    created_at: datetime
    evidence: list[CurationSourceEvidenceRead]
    validation_errors: list[dict[str, Any]]
    validation_warnings: list[dict[str, Any]]
    normalizations: list[dict[str, Any]]


class CurationSourceGroupRead(CurationModel):
    group_key: str
    target_entity_id: str | None = None
    unresolved_identity_key: str | None = None
    candidates: list[CurationSourceCandidateRead]
    target_context: dict[str, Any] | None = None
    signals: dict[str, list[str]]
    reason_codes: list[str]


class CurationSourcePackRead(CurationModel):
    as_of: datetime
    cursor_started: CurationCursor | None = None
    cursor_completed: CurationCursor | None = None
    has_more: bool
    input_candidate_count: int
    groups: list[CurationSourceGroupRead]
    budgets: dict[str, int]
    diagnostics: dict[str, Any]


class CurationPlanner(CurationModel):
    name: str = Field(min_length=1, max_length=160)
    model: str | None = Field(default=None, max_length=240)
    version: str = Field(min_length=1, max_length=120)


class CurationDecisionCreate(CurationModel):
    action: CurationAction
    risk_level: CurationRiskLevel
    candidate_ids: list[str] = Field(min_length=1)
    target_entity_id: str | None = None
    proposed_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_episode_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=240)
    planner: CurationPlanner


class CurationRunCreate(CurationModel):
    mode: CurationMode
    cursor_started_at: datetime | None = None
    cursor_started_id: str | None = None
    cursor_completed_at: datetime | None = None
    cursor_completed_id: str | None = None
    policy_version: str = Field(min_length=1, max_length=120)
    input_candidate_count: int = Field(default=0, ge=0)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    decisions: list[CurationDecisionCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cursor_and_plan(self) -> "CurationRunCreate":
        if (self.cursor_started_at is None) != (self.cursor_started_id is None):
            raise ValueError("cursor_started_at and cursor_started_id must be provided together.")
        if (self.cursor_completed_at is None) != (self.cursor_completed_id is None):
            raise ValueError("cursor_completed_at and cursor_completed_id must be provided together.")
        if self.cursor_completed_at is not None:
            if self.cursor_started_at is None:
                raise ValueError("A completed cursor requires a started cursor.")
            if (self.cursor_completed_at, self.cursor_completed_id) < (
                self.cursor_started_at,
                self.cursor_started_id,
            ):
                raise ValueError("The completed cursor cannot precede the started cursor.")
        if any(decision.policy_version != self.policy_version for decision in self.decisions):
            raise ValueError("Decision policy_version must match the run policy_version.")
        planners = {
            (decision.planner.name, decision.planner.model, decision.planner.version)
            for decision in self.decisions
        }
        if len(planners) > 1:
            raise ValueError("All decisions in a run must use the same planner metadata.")
        return self


class CurationDecisionRead(CurationModel):
    id: str
    run_id: str
    action: CurationAction
    status: CurationDecisionStatus
    risk_level: CurationRiskLevel
    candidate_ids: list[str]
    target_entity_id: str | None = None
    proposed_payload: dict[str, Any]
    evidence_episode_ids: list[str]
    reason_codes: list[str]
    policy_version: str
    idempotency_key: str
    canonical_record_ref: str | None = None
    readback_status: str | None = None
    readback_summary: dict[str, Any]
    api_error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None = None


class CurationRunSummaryRead(CurationModel):
    id: str
    mode: CurationMode
    status: CurationRunStatus
    cursor_started_at: datetime | None = None
    cursor_started_id: str | None = None
    cursor_completed_at: datetime | None = None
    cursor_completed_id: str | None = None
    policy_version: str
    planner_name: str | None = None
    planner_model: str | None = None
    planner_version: str | None = None
    input_candidate_count: int
    planned_decision_count: int
    executed_decision_count: int
    blocked_decision_count: int
    error_code: str | None = None
    diagnostics: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CurationRunRead(CurationRunSummaryRead):
    decisions: list[CurationDecisionRead] = Field(default_factory=list)


CurationRunList = ListResponse[CurationRunSummaryRead]
