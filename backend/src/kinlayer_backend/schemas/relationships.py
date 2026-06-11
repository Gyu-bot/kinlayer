from datetime import datetime
from typing import Any

from pydantic import Field

from kinlayer_backend.schemas.common import APIModel, ListResponse


class EdgeCreate(APIModel):
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    directed: bool | None = None
    claim_text: str
    claim_type: str = "fact"
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    status: str = "active"
    valid_from: datetime | None = None
    sensitivity: str = "medium"
    ai_use_policy: str = "cautious_use"
    created_by: str = "user"


class EdgePatch(APIModel):
    relation_type: str | None = None
    directed: bool | None = None
    claim_text: str | None = None
    claim_type: str | None = None
    properties: dict[str, Any] | None = None
    confidence: float | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    sensitivity: str | None = None
    ai_use_policy: str | None = None


class EdgeRead(EdgeCreate):
    id: str
    directed: bool
    valid_to: datetime | None = None
    invalidated_by_edge_id: str | None = None
    source_candidate_id: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RelatedEntityCreate(APIModel):
    entity_id: str
    role: str = "related"
    confidence: float | None = None


class RelatedEntityRead(RelatedEntityCreate):
    id: str
    observation_id: str
    created_at: datetime


class ObservationCreate(APIModel):
    subject_entity_id: str
    related_entities: list[RelatedEntityCreate] = Field(default_factory=list)
    observation_type: str
    content: str
    claim_type: str = "fact"
    confidence: float = 1.0
    sensitivity: str = "medium"
    ai_use_policy: str = "cautious_use"
    status: str = "active"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_at: datetime | None = None
    recency_weight: float | None = None
    created_by: str = "user"
    source_candidate_id: str | None = None


class ObservationPatch(APIModel):
    observation_type: str | None = None
    content: str | None = None
    claim_type: str | None = None
    confidence: float | None = None
    sensitivity: str | None = None
    ai_use_policy: str | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    occurred_at: datetime | None = None
    recency_weight: float | None = None


class ObservationRead(ObservationCreate):
    id: str
    related_entities: list[RelatedEntityRead] = Field(default_factory=list)
    embedding: str | None = None
    embedding_status: str
    embedding_error: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    embedding_created_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EpisodeCreate(APIModel):
    source_type: str
    source_ref: str | None = None
    source_description: str | None = None
    body_excerpt: str
    body_hash: str
    actor: str
    occurred_at: datetime | None = None
    sensitivity: str = "medium"
    retention_policy: str = "excerpt_only"


class EpisodeRead(EpisodeCreate):
    id: str
    ingested_at: datetime
    created_at: datetime
    updated_at: datetime


EdgeList = ListResponse[EdgeRead]
ObservationList = ListResponse[ObservationRead]
EpisodeList = ListResponse[EpisodeRead]
