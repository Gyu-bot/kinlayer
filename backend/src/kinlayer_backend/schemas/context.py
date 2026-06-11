from datetime import datetime
from typing import Any

from pydantic import Field

from kinlayer_backend.schemas.common import APIModel
from kinlayer_backend.schemas.entities import AliasRead, EntityFactRead, EntityRead
from kinlayer_backend.schemas.relationships import EdgeRead, ObservationRead


class ContextRetrieveRequest(APIModel):
    query: str
    entity_hints: list[str] = Field(default_factory=list)
    focal_entity_id: str | None = None
    query_embedding: list[float] | None = None
    include_debug: bool = False
    limit: int = Field(default=10, ge=1, le=50)


class RetrievedObservationRead(APIModel):
    observation_id: str
    content: str
    score: float
    match_reasons: list[str]
    sensitivity: str
    ai_use_policy: str
    status: str


class MatchedEntityRead(APIModel):
    entity_id: str
    display_name: str
    entity_type: str
    score: float
    confidence_band: str
    match_reasons: list[str]
    score_breakdown: dict[str, float]
    penalties: dict[str, float]
    surface_bucket: str
    sensitivity: str
    ai_use_policy: str
    confirmation_status: str
    observations: list[RetrievedObservationRead] = Field(default_factory=list)


class ContextRetrieveResponse(APIModel):
    matched_entities: list[MatchedEntityRead]
    observations: list[RetrievedObservationRead]
    scores: dict[str, float]
    match_reasons: dict[str, list[str]]
    score_breakdown: dict[str, dict[str, float]]
    ambiguity_detected: bool
    debug: dict[str, Any] = Field(default_factory=dict)


class ContextPackRequest(ContextRetrieveRequest):
    situation: str | None = None


class ProvenanceItem(APIModel):
    record_type: str
    record_id: str
    episode_id: str | None = None
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
    entity: EntityRead
    aliases: list[AliasRead]
    profile_facts: list[EntityFactRead]
    relationship_edges: list[EdgeRead]
    stable_context: list[ObservationRead]
    recent_context: list[ObservationRead]
    communication_context: list[ObservationRead]
    cautions: list[ObservationRead]
    provenance_summary: ProvenanceSummary
    retrieval_hints: RetrievalHints
