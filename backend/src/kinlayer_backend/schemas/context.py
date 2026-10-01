from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from kinlayer_backend.schemas.common import APIModel
from kinlayer_backend.schemas.entities import AliasRead, EntityFactRead, EntityRead
from kinlayer_backend.schemas.relationships import EdgeRead, ObservationRead
from kinlayer_backend.schemas.relationship_profiles import RelationshipProfileRead


class ContextRequestModel(APIModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ContextEntityRead(EntityRead):
    ai_use_policy: str = Field(default="cautious_use", exclude=True)
    confirmation_status: str = Field(default="confirmed", exclude=True)


class ContextEntityFactRead(EntityFactRead):
    ai_use_policy: str = Field(default="cautious_use", exclude=True)
    claim_type: str = Field(default="fact", exclude=True)


class ContextEdgeRead(EdgeRead):
    ai_use_policy: str = Field(default="cautious_use", exclude=True)
    claim_type: str = Field(default="fact", exclude=True)


class ContextObservationRead(ObservationRead):
    ai_use_policy: str = Field(default="cautious_use", exclude=True)
    claim_type: str = Field(default="fact", exclude=True)


class ContextRetrieveRequest(ContextRequestModel):
    query: str
    entity_hints: list[str] = Field(default_factory=list)
    focal_entity_id: str | None = None
    query_embedding: list[float] | None = None
    include_debug: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class RetrievedParticipantRead(APIModel):
    entity_id: str
    role: str
    confidence: float | None = None


class RetrievedObservationRead(APIModel):
    observation_id: str
    subject_entity_id: str
    observation_type: str
    claim_basis: Literal["reported", "inferred", "unknown"]
    confidence: float
    content: str
    score: float
    match_reasons: list[str]
    status: str
    related_entities: list[RetrievedParticipantRead] = Field(default_factory=list)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_at: datetime | None = None
    created_at: datetime | None = None


class MatchedEntityRead(APIModel):
    relationship_profile: RelationshipProfileRead
    entity_id: str
    display_name: str
    entity_type: str
    score: float
    confidence_band: str
    match_reasons: list[str]
    score_breakdown: dict[str, float]
    penalties: dict[str, float]
    surface_bucket: str
    profile_facts: list[ContextEntityFactRead] = Field(default_factory=list)
    observations: list[RetrievedObservationRead] = Field(default_factory=list)


class ContextRetrieveResponse(APIModel):
    matched_entities: list[MatchedEntityRead]
    observations: list[RetrievedObservationRead]
    provenance: list["ProvenanceItem"] = Field(default_factory=list)
    scores: dict[str, float]
    match_reasons: dict[str, list[str]]
    score_breakdown: dict[str, dict[str, float]]
    ambiguity_detected: bool
    debug: dict[str, Any] = Field(default_factory=dict)


class ContextPackRequest(ContextRetrieveRequest):
    situation: str | None = None
    include_provisional: bool = False


class ProvisionalContextRead(APIModel):
    candidate_id: str
    content: str
    observation_type: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_at: datetime | None = None
    created_at: datetime
    label: str = "provisional"
    review_status: str = "unreviewed"
    write_evidence_eligible: bool = False


class ProvenanceItem(APIModel):
    record_type: str
    record_id: str
    episode_id: str | None = None
    actor: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    source_occurred_at: datetime | None = None
    excerpt: str | None = None
    confidence: float | None = None
    created_at: datetime | None = None


class ContextPack(APIModel):
    confidence: str
    suggested_response_policy: str
    ambiguity_detected: bool
    matched_entities: list[MatchedEntityRead]
    buckets: dict[str, list[MatchedEntityRead]]
    recent_context: list[RetrievedObservationRead]
    stable_context: list[RetrievedObservationRead]
    cautions: list[RetrievedObservationRead]
    provenance: list[ProvenanceItem]
    provisional_context: list[ProvisionalContextRead] = Field(default_factory=list)


class ContextPackResponse(APIModel):
    context_pack: ContextPack
    debug: dict[str, Any] = Field(default_factory=dict)


class ProvenanceSummary(APIModel):
    fact_count: int
    edge_count: int
    observation_count: int
    evidence_count: int
    evidence: list[ProvenanceItem]


class RetrievalHints(APIModel):
    entity_id: str
    canonical_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    entity_type: str


class ContextCardResponse(APIModel):
    relationship_profile: RelationshipProfileRead
    entity: ContextEntityRead
    aliases: list[AliasRead]
    profile_facts: list[ContextEntityFactRead]
    relationship_edges: list[ContextEdgeRead]
    stable_context: list[ContextObservationRead]
    recent_context: list[ContextObservationRead]
    communication_context: list[ContextObservationRead]
    cautions: list[ContextObservationRead]
    provenance_summary: ProvenanceSummary
    retrieval_hints: RetrievalHints
    provisional_context: list[ProvisionalContextRead] = Field(default_factory=list)
