from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from kinlayer_backend.schemas.common import APIModel

Digest = str


class ClosedAPIModel(APIModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ReconciliationExpectedCandidate(ClosedAPIModel):
    id: str = Field(min_length=1, max_length=36)
    status: str = Field(min_length=1, max_length=40)
    updated_at: datetime
    payload_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReconciliationExpectedEntity(ClosedAPIModel):
    id: str = Field(min_length=1, max_length=36)
    status: str = Field(min_length=1, max_length=40)
    updated_at: datetime
    entity_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReconciliationSource(ClosedAPIModel):
    user_explicit: Literal[True]
    source_type: Literal["agent_conversation"]
    source_ref: str = Field(min_length=1, max_length=500)
    source_actor: Literal["user"]
    body_hash: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReconciliationActionCreate(ClosedAPIModel):
    resolution_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    action: Literal[
        "reject_candidates",
        "map_to_existing_entity",
        "confirm_new_entity_group",
        "rename_and_accept_new_entity",
        "merge_existing_entities",
        "archive_existing_entity",
    ]
    candidate_ids: list[str] = Field(default_factory=list, max_length=50)
    expected_candidates: list[ReconciliationExpectedCandidate] = Field(
        default_factory=list, max_length=50
    )
    expected_entities: list[ReconciliationExpectedEntity] = Field(
        default_factory=list, max_length=2
    )
    source_entity_id: str | None = Field(default=None, max_length=36)
    target_entity_id: str | None = Field(default=None, max_length=36)
    canonical_name: str | None = Field(default=None, min_length=2, max_length=240)
    display_name: str | None = Field(default=None, min_length=2, max_length=240)
    resolution_note: str = Field(min_length=1, max_length=500)
    source: ReconciliationSource

    @model_validator(mode="after")
    def validate_shape(self) -> "ReconciliationActionCreate":
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate_ids must be unique")
        expected_ids = [item.id for item in self.expected_candidates]
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError("expected_candidates ids must be unique")
        if set(expected_ids) != set(self.candidate_ids):
            raise ValueError("expected_candidates must exactly match candidate_ids")
        entity_ids = [item.id for item in self.expected_entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("expected_entities ids must be unique")
        cleanup_action = self.action in {
            "merge_existing_entities", "archive_existing_entity"
        }
        if cleanup_action:
            if self.candidate_ids or self.expected_candidates:
                raise ValueError("entity cleanup actions cannot include reviewed candidates")
            required_ids = {self.source_entity_id}
            if self.action == "merge_existing_entities":
                required_ids.add(self.target_entity_id)
            if None in required_ids or set(entity_ids) != required_ids:
                raise ValueError("expected_entities must exactly match entity ids")
        elif self.action == "map_to_existing_entity":
            if not self.candidate_ids:
                raise ValueError("mapping requires at least one candidate")
            if self.source_entity_id is not None or set(entity_ids) != {self.target_entity_id}:
                raise ValueError("mapping requires the exact target entity snapshot")
        elif self.expected_entities or self.source_entity_id is not None:
            raise ValueError("entity snapshots are only allowed for mapping or entity cleanup actions")
        elif not self.candidate_ids:
            raise ValueError("candidate actions require at least one candidate")
        if self.action == "map_to_existing_entity":
            if not self.target_entity_id:
                raise ValueError("target_entity_id is required")
        elif self.action == "merge_existing_entities":
            if not self.source_entity_id or not self.target_entity_id:
                raise ValueError("source_entity_id and target_entity_id are required")
        elif self.target_entity_id is not None:
            raise ValueError("target_entity_id is only allowed for mapping")
        if self.action == "rename_and_accept_new_entity":
            if len(self.candidate_ids) < 1 or not self.display_name:
                raise ValueError("display_name is required for rename")
        elif self.display_name is not None or self.canonical_name is not None:
            raise ValueError("names are only allowed for rename")
        return self


class ReconciliationCandidateRead(ClosedAPIModel):
    id: str
    status: str
    updated_at: datetime
    canonical_record_ref: str | None = None
    evidence_episode_ids: list[str]


class ReconciliationEntitySnapshotRead(ClosedAPIModel):
    id: str
    entity_type: str
    display_name: str
    canonical_name: str | None = None
    status: str
    updated_at: datetime
    entity_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReconciliationEntitySnapshotList(ClosedAPIModel):
    items: list[ReconciliationEntitySnapshotRead]
    limit: int
    offset: int
    total: int


class ReconciliationActionRead(ClosedAPIModel):
    id: str
    resolution_id: str
    action: str
    status: str
    verification_state: str
    candidate_ids: list[str]
    derived_candidate_ids: list[str]
    candidates: list[ReconciliationCandidateRead]
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    primary_entity_id: str | None = None
    confirmation_episode_id: str | None = None
    canonical_refs: list[str]
    entity: dict | None = None
    context_card: dict | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
