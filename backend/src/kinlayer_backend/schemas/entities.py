from datetime import datetime
from typing import Any

from pydantic import Field

from kinlayer_backend.schemas.common import APIModel, ListResponse


class EntityBase(APIModel):
    entity_type: str = "person"
    display_name: str
    canonical_name: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    confirmation_status: str = "confirmed"
    sensitivity: str = "medium"
    ai_use_policy: str = "cautious_use"
    created_by: str = "user"
    system_role: str | None = None
    is_system: bool = False


class EntityCreate(EntityBase):
    pass


class EntityPatch(APIModel):
    display_name: str | None = None
    canonical_name: str | None = None
    properties: dict[str, Any] | None = None
    confirmation_status: str | None = None
    status: str | None = None
    sensitivity: str | None = None
    ai_use_policy: str | None = None
    system_role: str | None = None


class EntityRead(EntityBase):
    id: str
    status: str
    first_seen_at: datetime | None = None
    last_referenced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class EntityResolveRequest(APIModel):
    surface: str
    aliases: list[str] = Field(default_factory=list)
    relation_hint: str | None = None
    entity_type: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=5, ge=1, le=25)


class EntityResolveMatch(APIModel):
    entity_id: str
    display_name: str
    entity_type: str
    score: float
    match_reasons: list[str]


class EntityResolveResponse(APIModel):
    surface: str
    ambiguity: str
    matches: list[EntityResolveMatch]


class AliasCreate(APIModel):
    alias: str
    status: str = "active"
    confidence: float = 1.0
    created_by: str = "user"


class AliasPatch(APIModel):
    alias: str | None = None
    status: str | None = None
    confidence: float | None = None


class AliasRead(APIModel):
    id: str
    entity_id: str
    alias: str
    normalized_alias: str | None
    status: str
    confidence: float
    source_candidate_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime


class EntityFactCreate(APIModel):
    entity_id: str
    fact_type: str
    content: str
    value: dict[str, Any] | None = None
    claim_type: str = "fact"
    confidence: float = 1.0
    sensitivity: str = "medium"
    ai_use_policy: str = "cautious_use"
    status: str = "active"
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_candidate_id: str | None = None
    created_by: str = "user"


class EntityFactPatch(APIModel):
    fact_type: str | None = None
    content: str | None = None
    value: dict[str, Any] | None = None
    claim_type: str | None = None
    confidence: float | None = None
    sensitivity: str | None = None
    ai_use_policy: str | None = None
    status: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class EntityFactRead(EntityFactCreate):
    id: str
    created_at: datetime
    updated_at: datetime


EntityList = ListResponse[EntityRead]
AliasList = ListResponse[AliasRead]
EntityFactList = ListResponse[EntityFactRead]
