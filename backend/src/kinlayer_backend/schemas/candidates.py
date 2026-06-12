from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from kinlayer_backend.schemas.common import APIModel, ListResponse

CANDIDATE_TYPES = {
    "new_entity",
    "alias",
    "profile_field",
    "relationship_edge",
    "observation",
    "merge",
    "conflict",
    "supersede",
}


class NewEntityPayload(APIModel):
    entity_type: str
    display_name: str
    canonical_name: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ai_use_policy: str = "cautious_use"
    sensitivity: str = "medium"


class AliasPayload(APIModel):
    entity_id: str
    alias: str
    confidence: float | None = None


class ProfileFieldPayload(APIModel):
    entity_id: str
    field_path: str
    value: Any
    fact_type: str | None = None
    content: str | None = None
    claim_type: str
    sensitivity: str | None = None
    ai_use_policy: str | None = None


class RelationshipEdgePayload(APIModel):
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    directed: bool | None = None
    claim_text: str
    claim_type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class ObservationPayload(APIModel):
    subject_entity_id: str
    related_entity_ids: list[str] = Field(default_factory=list)
    observation_type: str
    content: str
    claim_type: str
    ai_use_policy: str = "cautious_use"
    sensitivity: str = "medium"
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class MergePayload(APIModel):
    source_entity_id: str
    target_entity_id: str
    reason: str
    fields_to_merge: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class ConflictPayload(APIModel):
    record_refs: list[str] = Field(min_length=1)
    conflict_type: str
    description: str


class SupersedePayload(APIModel):
    old_record_ref: str
    new_payload: dict[str, Any]
    reason: str


PAYLOAD_MODELS = {
    "new_entity": NewEntityPayload,
    "alias": AliasPayload,
    "profile_field": ProfileFieldPayload,
    "relationship_edge": RelationshipEdgePayload,
    "observation": ObservationPayload,
    "merge": MergePayload,
    "conflict": ConflictPayload,
    "supersede": SupersedePayload,
}


class CandidateEvidenceCreate(APIModel):
    episode_id: str
    excerpt: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CandidateEvidenceRead(CandidateEvidenceCreate):
    id: str
    candidate_id: str
    created_at: datetime


class CandidateCreate(APIModel):
    candidate_type: str
    target_entity_id: str | None = None
    payload: dict[str, Any]
    evidence: list[CandidateEvidenceCreate] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    sensitivity: str = "medium"
    suggested_action: str | None = None
    created_by: str
    supersedes_candidate_id: str | None = None
    supersedes_record_ref: str | None = None

    @model_validator(mode="after")
    def validate_typed_payload(self) -> "CandidateCreate":
        payload_model = PAYLOAD_MODELS.get(self.candidate_type)
        if not payload_model:
            raise ValueError("Invalid candidate_type.")
        self.payload = payload_model.model_validate(self.payload).model_dump(exclude_none=True)
        return self


class CandidatePatch(APIModel):
    target_entity_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    sensitivity: str | None = None
    suggested_action: str | None = None
    resolution_note: str | None = None


class CandidateActionRequest(APIModel):
    resolution_note: str | None = None
    resolved_by: str = "user"
    supersedes_candidate_id: str | None = None


class CandidateEditAcceptRequest(APIModel):
    payload: dict[str, Any]
    resolution_note: str | None = None
    resolved_by: str = "user"


class CandidateRead(APIModel):
    id: str
    candidate_type: str
    target_entity_id: str | None = None
    payload: dict[str, Any]
    confidence: float
    sensitivity: str
    suggested_action: str | None = None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    canonical_record_ref: str | None = None
    supersedes_candidate_id: str | None = None
    supersedes_record_ref: str | None = None
    evidence: list[CandidateEvidenceRead] = Field(default_factory=list)


CandidateList = ListResponse[CandidateRead]
