from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from kinlayer_backend.schemas.common import APIModel, PublicReadModel

from kinlayer_backend.services.relationship_ontology import EDGE_DEFINITIONS

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
    body_excerpt: str = Field(min_length=1, max_length=4000)


class ReconciliationCurrentReplyEvidence(ClosedAPIModel):
    evidence_class: Literal["current_reply"]
    start: int = Field(ge=0, le=4000)
    end: int = Field(gt=0, le=4000)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end <= self.start:
            raise ValueError("evidence span must be non-empty")
        return self


class ReconciliationPreparedEvidence(ClosedAPIModel):
    evidence_class: Literal["prepared_candidate_evidence"]
    candidate_id: str = Field(min_length=1, max_length=36)
    evidence_id: str = Field(min_length=1, max_length=36)
    episode_id: str = Field(min_length=1, max_length=36)
    body_hash: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    excerpt_hash: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    start: int = Field(ge=0, le=4000)
    end: int = Field(gt=0, le=4000)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end <= self.start:
            raise ValueError("evidence span must be non-empty")
        return self


ContextEvidence = Annotated[
    ReconciliationCurrentReplyEvidence | ReconciliationPreparedEvidence,
    Field(discriminator="evidence_class"),
]


class ReconciliationContextClaim(ClosedAPIModel):
    claim_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    answer_item_id: str = Field(min_length=1, max_length=120)
    target: Literal["primary_entity"]
    kind: Literal["profile_field", "relationship_edge", "observation"]
    fact_type: Literal["role", "job", "organization"] | None = None
    field_path: Literal["role", "job", "organization"] | None = None
    relation_type: str | None = Field(default=None, min_length=1, max_length=80)
    observation_type: Literal[
        "stable_fact", "communication_preference", "relationship_pattern", "care_point",
        "recent_interaction", "user_feeling", "follow_up_context",
    ] | None = None
    claim_type: Literal["fact", "preference", "pattern"]
    ai_use_policy: Literal["cautious_use", "ask_before_use", "never_surface"]
    sensitivity: str | None = Field(default=None, max_length=40, deprecated=True, description="Ignored legacy signing metadata.")
    evidence: ContextEvidence

    @model_validator(mode="after")
    def kind_shape(self):
        if self.evidence.evidence_class == "current_reply" and (
            self.ai_use_policy != "cautious_use"
        ):
            raise ValueError("current reply context policy must be fixed")
        if self.kind == "profile_field":
            if self.fact_type is None or self.fact_type != self.field_path or self.claim_type != "fact":
                raise ValueError("invalid profile field claim")
            if self.relation_type is not None or self.observation_type is not None:
                raise ValueError("invalid profile field claim")
        elif self.kind == "relationship_edge":
            if (self.relation_type not in EDGE_DEFINITIONS
                    or EDGE_DEFINITIONS[self.relation_type].support_level != "supported"
                    or self.claim_type != "fact"):
                raise ValueError("invalid relationship claim")
            if self.fact_type is not None or self.field_path is not None or self.observation_type is not None:
                raise ValueError("invalid relationship claim")
        else:
            if self.observation_type is None:
                raise ValueError("invalid observation claim")
            if self.fact_type is not None or self.field_path is not None or self.relation_type is not None:
                raise ValueError("invalid observation claim")
        return self


class ReconciliationRelationshipToSelf(ClosedAPIModel):
    relation_type: str = Field(min_length=1, max_length=80)
    claim_text: str = Field(min_length=1, max_length=500)


class ReconciliationAnswerBinding(ClosedAPIModel):
    version: Literal["pcr-reconciliation-binding.v1"]
    question_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    answer_item_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    item_fingerprint: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    agenda_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    resolution_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    action: str = Field(min_length=1, max_length=60, pattern=r"^[a-z_]+$")
    context_claims_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    action_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    commitment: str = Field(pattern=r"^hmac-sha256:[0-9a-f]{64}$")


class ReconciliationActionCreate(ClosedAPIModel):
    resolution_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    action: Literal[
        "reject_candidates",
        "map_to_existing_entity",
        "confirm_new_entity_group",
        "accept_existing_entity_observation_group",
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
    relationship_to_self: ReconciliationRelationshipToSelf | None = None
    resolution_note: str = Field(min_length=1, max_length=500)
    source: ReconciliationSource
    context_claims: list[ReconciliationContextClaim] = Field(default_factory=list, max_length=6)
    answer_bindings: list[ReconciliationAnswerBinding] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def validate_shape(self) -> "ReconciliationActionCreate":
        import hashlib

        if self.source.body_hash != "sha256:" + hashlib.sha256(self.source.body_excerpt.encode()).hexdigest():
            raise ValueError("source body hash must match exact body excerpt")
        binding = self.answer_bindings[0]
        if (
            binding.resolution_id != self.resolution_id
            or binding.action != self.action
            or any(claim.answer_item_id != binding.answer_item_id for claim in self.context_claims)
        ):
            raise ValueError("answer binding does not match the action")
        claim_ids = [claim.claim_id for claim in self.context_claims]
        if claim_ids != sorted(set(claim_ids)):
            raise ValueError("context claims must be unique and sorted")
        semantics = [
            (claim.answer_item_id, claim.kind, claim.fact_type, claim.field_path,
             claim.relation_type, claim.observation_type)
            for claim in self.context_claims
        ]
        if len(semantics) != len(set(semantics)):
            raise ValueError("duplicate semantic context claim")
        context_actions = {
            "map_to_existing_entity", "confirm_new_entity_group",
            "accept_existing_entity_observation_group", "rename_and_accept_new_entity",
            "merge_existing_entities",
        }
        if self.context_claims and self.action not in context_actions:
            raise ValueError("action cannot yield a context target")
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
        elif self.action in {
            "map_to_existing_entity", "accept_existing_entity_observation_group"
        }:
            if not self.candidate_ids:
                raise ValueError("targeted action requires at least one candidate")
            if self.source_entity_id is not None or set(entity_ids) != {self.target_entity_id}:
                raise ValueError("targeted action requires the exact target entity snapshot")
        elif self.expected_entities or self.source_entity_id is not None:
            raise ValueError("entity snapshots are only allowed for mapping or entity cleanup actions")
        elif not self.candidate_ids:
            raise ValueError("candidate actions require at least one candidate")
        if self.action in {
            "map_to_existing_entity", "accept_existing_entity_observation_group"
        }:
            if not self.target_entity_id:
                raise ValueError("target_entity_id is required")
        elif self.action == "merge_existing_entities":
            if not self.source_entity_id or not self.target_entity_id:
                raise ValueError("source_entity_id and target_entity_id are required")
        elif self.target_entity_id is not None:
            raise ValueError("target_entity_id is not allowed for this action")
        if self.action == "rename_and_accept_new_entity":
            if len(self.candidate_ids) < 1 or not self.display_name:
                raise ValueError("display_name is required for rename")
        elif self.display_name is not None or self.canonical_name is not None:
            raise ValueError("names are only allowed for rename")
        if self.relationship_to_self is not None and self.action != "rename_and_accept_new_entity":
            raise ValueError("relationship_to_self is only allowed for rename")
        if self.relationship_to_self is not None and any(
            claim.kind == "relationship_edge" for claim in self.context_claims
        ):
            raise ValueError("relationship context must use exactly one representation")
        return self


class ReconciliationCandidateRead(ClosedAPIModel):
    id: str
    candidate_type: str
    status: str
    updated_at: datetime
    canonical_record_ref: str | None = None
    target_entity_id: str | None = None
    payload_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_episode_ids: list[str]


class ReconciliationDerivedCandidateRead(ClosedAPIModel):
    id: str
    candidate_type: str
    status: str
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


class ReconciliationEntityRead(ClosedAPIModel):
    id: str
    entity_type: str
    display_name: str
    canonical_name: str | None = None
    status: str
    system_role: str | None = None
    updated_at: datetime
    entity_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReconciliationCandidateEvidenceRead(ClosedAPIModel):
    id: str = Field(min_length=1, max_length=36)
    episode_id: str = Field(min_length=1, max_length=36)
    excerpt: str = Field(min_length=1, max_length=500)
    source_type: Literal["agent_conversation"]
    actor: Literal["user"]
    body_hash: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    effective_ai_use_policy: Literal["cautious_use", "ask_before_use", "never_surface"]


class ReconciliationCandidateEvidenceSnapshot(ClosedAPIModel):
    id: str = Field(min_length=1, max_length=36)
    status: str = Field(min_length=1, max_length=40)
    updated_at: datetime
    payload_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_digest: Digest = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence: list[ReconciliationCandidateEvidenceRead] = Field(max_length=20)


class ReconciliationCandidateEvidenceSnapshotList(ClosedAPIModel):
    items: list[ReconciliationCandidateEvidenceSnapshot] = Field(max_length=50)


class ReconciliationActionRead(ClosedAPIModel, PublicReadModel):
    id: str
    resolution_id: str
    action: str
    status: str
    verification_state: str
    candidate_ids: list[str]
    derived_candidate_ids: list[str]
    derived_candidates: list[ReconciliationDerivedCandidateRead] = Field(default_factory=list)
    candidates: list[ReconciliationCandidateRead]
    source_entity_id: str | None = None
    target_entity_id: str | None = None
    primary_entity_id: str | None = None
    confirmation_episode_id: str | None = None
    canonical_refs: list[str]
    context_outcomes: list[dict] = Field(default_factory=list)
    answer_binding: ReconciliationAnswerBinding
    entity: ReconciliationEntityRead | None = None
    source_entity: ReconciliationEntityRead | None = None
    context_card: dict | None = None
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime
