from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator, model_serializer


class MemoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Content = Annotated[str, Field(min_length=1, max_length=4000)]
ClaimBasis = Literal["reported", "inferred", "unknown"]
MemoryRecordType = Literal["entity_facts", "entity_edges", "observations"]
MemoryReadStatus = Literal["active", "history", "all"]


class MemorySource(MemoryModel):
    # Imported material has its own manifest-bound authorization contract.
    source_type: Literal["agent_conversation", "manual_entry"]
    source_ref: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    actor: Annotated[str, Field(min_length=1, max_length=80)]
    excerpt: Content
    occurred_at: AwareDatetime | None = None

    @field_validator("actor")
    @classmethod
    def human_source(cls, value: str) -> str:
        if value.casefold() in {"assistant", "ai_agent", "system", "tool", "unknown"}:
            raise ValueError("Memory evidence must identify a human source actor.")
        return value


class MemoryClaim(MemoryModel):
    claim_basis: ClaimBasis
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def ordered_validity(self):
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to must not precede valid_from.")
        return self


class MemoryFactPayload(MemoryClaim):
    entity_id: Identifier
    fact_type: Annotated[str, Field(min_length=1, max_length=120)]
    content: Content
    value: dict[str, Any]


class MemoryEdgePayload(MemoryClaim):
    from_entity_id: Identifier
    to_entity_id: Identifier
    relation_type: Annotated[str, Field(min_length=1, max_length=120)]
    directed: bool | None = None
    claim_text: Content
    properties: dict[str, Any] = Field(default_factory=dict)


class MemoryRelatedEntity(MemoryModel):
    entity_id: Identifier
    role: Literal["subject", "related", "mentioned", "speaker", "target", "about", "experiencer"]
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class MemoryObservationPayload(MemoryClaim):
    subject_entity_id: Identifier
    observation_type: Annotated[str, Field(min_length=1, max_length=120)]
    content: Content
    occurred_at: AwareDatetime | None = None
    related_entities: list[MemoryRelatedEntity] = Field(default_factory=list, max_length=20)

    perspective_entity_id: Identifier | None = None
    relationship_axis: Annotated[str, Field(min_length=1, max_length=40)] | None = None
    relationship_value: Annotated[str, Field(min_length=1, max_length=40)] | None = None

    @model_serializer(mode="wrap")
    def omit_absent_profile_fields(self, handler):
        result = handler(self)
        if self.observation_type != "relationship_assessment":
            for field in ("perspective_entity_id", "relationship_axis", "relationship_value"):
                if result.get(field) is None:
                    result.pop(field, None)
        return result

    @model_validator(mode="after")
    def relationship_profile_shape(self):
        from kinlayer_backend.services.relationship_profiles import validate_profile_shape
        validate_profile_shape(self.model_dump())
        return self

    @model_validator(mode="after")
    def unique_links(self):
        keys = [(item.entity_id, item.role) for item in self.related_entities]
        if len(keys) != len(set(keys)):
            raise ValueError("Related entity role links must be unique.")
        return self


class MemoryFact(MemoryModel):
    record_type: Literal["entity_facts"]
    payload: MemoryFactPayload


class MemoryEdge(MemoryModel):
    record_type: Literal["entity_edges"]
    payload: MemoryEdgePayload


class MemoryObservation(MemoryModel):
    record_type: Literal["observations"]
    payload: MemoryObservationPayload


MemoryRecord = Annotated[
    MemoryFact | MemoryEdge | MemoryObservation, Field(discriminator="record_type")
]


class MemoryWriteRequest(MemoryModel):
    request_id: Identifier
    action: Literal["create", "correct", "retract", "reattribute"] = "create"
    old_record_ref: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    record: MemoryRecord | None = None
    source: MemorySource
    reason: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    created_by: Literal["ai_agent", "user", "connector", "import", "system"] = "ai_agent"
    expected_updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def action_shape(self):
        if self.action == "create":
            if self.old_record_ref is not None or self.expected_updated_at is not None:
                raise ValueError("Create cannot reference an old record.")
        elif self.old_record_ref is None:
            raise ValueError("A correction, retraction or reattribution requires old_record_ref.")
        if self.action == "retract":
            if self.record is not None:
                raise ValueError("Retraction must not provide a replacement record.")
        elif self.record is None:
            raise ValueError("This action requires a record.")
        return self


class MemoryWriteResponse(MemoryModel):
    change_id: str
    action: str
    old_record_ref: str | None
    new_record_ref: str | None
    source_episode_id: str


class MemoryChangeRead(MemoryModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    request_id: str
    change_kind: str
    old_record_ref: str | None
    new_record_ref: str | None
    source_episode_id: str | None
    actor: str
    reason: str | None
    created_at: datetime


class MemoryChangeList(MemoryModel):
    items: list[MemoryChangeRead]
    total: int
    limit: int
    offset: int


class MemoryReadModel(MemoryModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class MemoryEntityRead(MemoryReadModel):
    id: str
    display_name: str
    role: str


class MemoryEvidenceRead(MemoryReadModel):
    episode_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    actor: str | None = None
    excerpt: str | None = None
    occurred_at: datetime | None = None
    missing: bool = False
    material_provenance: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def omit_absent_material_provenance(self, handler):
        result = handler(self)
        if self.material_provenance is None:
            result.pop("material_provenance", None)
        return result


class MemoryRead(MemoryReadModel):
    record_ref: str
    record_type: MemoryRecordType
    id: str
    content: str
    claim_basis: ClaimBasis
    confidence: float
    status: str
    is_current: bool
    created_at: datetime
    updated_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None
    # Preserve historical legacy values, including null typed values, without inventing data.
    # New memory records contain exactly the corresponding MemoryRecord payload fields.
    payload: dict[str, Any]
    entities: list[MemoryEntityRead]
    sources: list[MemoryEvidenceRead]


class MemoryList(MemoryModel):
    items: list[MemoryRead]
    total: int
    limit: int
    offset: int
