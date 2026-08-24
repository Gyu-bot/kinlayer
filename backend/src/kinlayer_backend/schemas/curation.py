import json
import math
import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinlayer_backend.schemas.common import APIModel, ListResponse


class CurationModel(APIModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


CURATION_DIAGNOSTICS_MAX_BYTES = 8192
CURATION_PROPOSED_PAYLOAD_MAX_BYTES = 16384
CURATION_JSON_MAX_DEPTH = 6
CURATION_JSON_MAX_NODES = 256
CURATION_JSON_MAX_STRING_CHARS = 2000
RESERVED_CURATION_KEYS = {
    "raw_prompt",
    "raw_provider_response",
    "provider_response",
    "raw_provider_request",
    "provider_request",
    "raw_transcript",
    "transcript",
    "session",
    "session_body",
    "session_content",
    "session_data",
    "session_history",
    "session_transcript",
    "raw_session",
    "tool",
    "tools",
    "tool_call",
    "tool_calls",
    "tool_output",
    "tool_result",
}
RESERVED_CURATION_MARKERS = {
    "raw_prompt",
    "raw_provider_response",
    "provider_response",
    "raw_provider_request",
    "provider_request",
    "raw_transcript",
}
RESERVED_CURATION_MARKER_TOKENS = {
    marker.replace("_", "") for marker in RESERVED_CURATION_MARKERS
}
RESERVED_CURATION_KEY_TOKENS = {
    key.replace("_", "") for key in RESERVED_CURATION_KEYS
}


def contains_reserved_curation_marker(value: str) -> bool:
    compact = value.replace("_", "")
    return any(marker in value for marker in RESERVED_CURATION_MARKERS) or any(
        marker in compact for marker in RESERVED_CURATION_MARKER_TOKENS
    )


def validate_bounded_curation_json(value: dict[str, Any], *, max_bytes: int) -> dict[str, Any]:
    nodes = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > CURATION_JSON_MAX_NODES:
            raise ValueError("Curation JSON contains too many values.")
        if depth > CURATION_JSON_MAX_DEPTH:
            raise ValueError("Curation JSON is nested too deeply.")
        if item is None or isinstance(item, bool | int):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("Curation JSON floats must be finite.")
            return
        if isinstance(item, str):
            if len(item) > CURATION_JSON_MAX_STRING_CHARS:
                raise ValueError("Curation JSON string is too long.")
            normalized = re.sub(r"[^a-z0-9]+", "_", item.casefold()).strip("_")
            if contains_reserved_curation_marker(normalized):
                raise ValueError("Curation JSON contains reserved raw-content markers.")
            return
        if isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 80:
                    raise ValueError("Curation JSON keys must be bounded strings.")
                normalized_key = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
                if (
                    normalized_key in RESERVED_CURATION_KEYS
                    or normalized_key.replace("_", "") in RESERVED_CURATION_KEY_TOKENS
                ):
                    raise ValueError("Curation JSON contains a reserved raw-content key.")
                visit(child, depth + 1)
            return
        raise ValueError("Curation JSON must contain JSON-compatible values only.")

    visit(value, 0)
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
        raise ValueError("Curation JSON exceeds the byte limit.")
    return value


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
    upper_cursor: CurationCursor | None = None
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    limit: int = Field(default=50, ge=1, le=200)
    max_age_days: int = Field(default=30, ge=1, le=365)
    max_evidence_per_candidate: int = Field(default=5, ge=1, le=20)
    max_excerpt_chars: int = Field(default=500, ge=1, le=500)

    @model_validator(mode="after")
    def validate_cursor_window(self) -> "CurationSourcePackRequest":
        lower = self.cursor or CurationCursor(
            created_at=self.as_of - timedelta(days=self.max_age_days),
            candidate_id="",
        )
        if self.upper_cursor and _cursor_key(self.upper_cursor) <= _cursor_key(lower):
            raise ValueError("upper_cursor must be greater than cursor.")
        return self


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
    candidate_ids: list[str] = Field(min_length=1, max_length=200)
    target_entity_id: str | None = None
    proposed_payload: dict[str, Any] = Field(default_factory=dict)
    evidence_episode_ids: list[str] = Field(default_factory=list, max_length=200)
    reason_codes: list[str] = Field(default_factory=list, max_length=50)
    policy_version: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=240)
    planner: CurationPlanner

    @field_validator("proposed_payload")
    @classmethod
    def validate_proposed_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_curation_json(
            value,
            max_bytes=CURATION_PROPOSED_PAYLOAD_MAX_BYTES,
        )


class CurationRunCreate(CurationModel):
    mode: CurationMode
    cursor_started_at: datetime | None = None
    cursor_started_id: str | None = None
    cursor_completed_at: datetime | None = None
    cursor_completed_id: str | None = None
    policy_version: str = Field(min_length=1, max_length=120)
    input_candidate_count: int = Field(default=0, ge=0, le=200)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    decisions: list[CurationDecisionCreate] = Field(default_factory=list, max_length=200)

    @field_validator("diagnostics")
    @classmethod
    def validate_diagnostics(cls, value: dict[str, Any]) -> dict[str, Any]:
        validated = validate_bounded_curation_json(
            value,
            max_bytes=CURATION_DIAGNOSTICS_MAX_BYTES,
        )
        if "replay_checkpoint" in validated and validated["replay_checkpoint"] is not True:
            raise ValueError("replay_checkpoint must be true when provided.")
        return validated

    @model_validator(mode="after")
    def validate_cursor_and_plan(self) -> "CurationRunCreate":
        if (self.cursor_started_at is None) != (self.cursor_started_id is None):
            raise ValueError("cursor_started_at and cursor_started_id must be provided together.")
        if (self.cursor_completed_at is None) != (self.cursor_completed_id is None):
            raise ValueError("cursor_completed_at and cursor_completed_id must be provided together.")
        if self.cursor_completed_at is not None:
            if self.cursor_started_at is None:
                raise ValueError("A completed cursor requires a started cursor.")
            if _cursor_key_from_parts(
                self.cursor_completed_at,
                self.cursor_completed_id,
            ) < _cursor_key_from_parts(self.cursor_started_at, self.cursor_started_id):
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

    @field_validator("proposed_payload")
    @classmethod
    def validate_read_proposed_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_curation_json(
            value,
            max_bytes=CURATION_PROPOSED_PAYLOAD_MAX_BYTES,
        )


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

    @field_validator("diagnostics")
    @classmethod
    def validate_read_diagnostics(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_bounded_curation_json(value, max_bytes=CURATION_DIAGNOSTICS_MAX_BYTES)


class CurationRunRead(CurationRunSummaryRead):
    decisions: list[CurationDecisionRead] = Field(default_factory=list)


CurationRunList = ListResponse[CurationRunSummaryRead]


def _cursor_key(cursor: CurationCursor) -> tuple[datetime, str]:
    return _cursor_key_from_parts(cursor.created_at, cursor.candidate_id)


def _cursor_key_from_parts(created_at: datetime, candidate_id: str) -> tuple[datetime, str]:
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(UTC).replace(tzinfo=None)
    return created_at, candidate_id
