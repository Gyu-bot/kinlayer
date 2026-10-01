from datetime import datetime
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from kinlayer_backend.schemas.common import APIModel, PublicReadModel

from kinlayer_backend.services.relationship_ontology import EDGE_DEFINITIONS

class ClosedModel(APIModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ProfileSlotCreate(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["profile_field"]
    fact_type: Literal["role", "job", "organization"]
    field_path: Literal["role", "job", "organization"]
    claim_type: Literal["fact"] = "fact"
    ai_use_policy: Literal["cautious_use"] = "cautious_use"
    sensitivity: str = Field(default="low", max_length=40, deprecated=True, description="Ignored legacy fingerprint metadata.")

    @model_validator(mode="after")
    def matching_field(self):
        if self.fact_type != self.field_path:
            raise ValueError("fact_type and field_path must match")
        return self


class EdgeSlotCreate(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["relationship_edge"]
    direction: Literal["self_to_subject", "subject_to_self"]
    allowed_relation_types: list[str] = Field(min_length=1, max_length=3)
    directed: bool | None = None
    claim_type: Literal["fact"] = "fact"
    ai_use_policy: Literal["cautious_use"] = "cautious_use"
    sensitivity: str = Field(default="low", max_length=40, deprecated=True, description="Ignored legacy fingerprint metadata.")

    @field_validator("allowed_relation_types")
    @classmethod
    def unique_sorted_relation_types(cls, value):
        if value != sorted(set(value)):
            raise ValueError("allowed_relation_types must be unique and sorted")
        if any(item not in EDGE_DEFINITIONS or EDGE_DEFINITIONS[item].support_level != "supported" for item in value):
            raise ValueError("allowed_relation_types must use writable ontology types")
        return value


class ObservationSlotCreate(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["observation"]
    allowed_observation_types: list[
        Literal[
            "stable_fact",
            "communication_preference",
            "relationship_pattern",
            "care_point",
            "recent_interaction",
            "user_feeling",
            "follow_up_context",
        ]
    ] = Field(min_length=1, max_length=3)
    related_entity_id: str | None = Field(default=None, min_length=1, max_length=36)
    claim_type: Literal["fact", "preference", "pattern"]
    ai_use_policy: Literal["cautious_use"] = "cautious_use"
    sensitivity: str = Field(default="low", max_length=40, deprecated=True, description="Ignored legacy fingerprint metadata.")

    @field_validator("allowed_observation_types")
    @classmethod
    def unique_sorted_observation_types(cls, value):
        if value != sorted(set(value)):
            raise ValueError("allowed_observation_types must be unique and sorted")
        return value


SlotCreate = Annotated[
    ProfileSlotCreate | EdgeSlotCreate | ObservationSlotCreate,
    Field(discriminator="kind"),
]


class EnrichmentAuthorizationCreate(ClosedModel):
    stage_idempotency_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    subject_entity_id: str = Field(min_length=1, max_length=36)
    topic: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_:-]+$")
    slots: list[SlotCreate] = Field(min_length=1, max_length=3)
    expires_at: datetime

    @model_validator(mode="after")
    def unique_slots(self):
        ids = [slot.slot_id for slot in self.slots]
        if len(ids) != len(set(ids)):
            raise ValueError("slot_id values must be unique")
        return self


class EnrichmentSource(ClosedModel):
    user_explicit: Literal[True]
    source_type: Literal["agent_conversation"]
    source_ref: str = Field(min_length=1, max_length=500)
    source_actor: Literal["user"]
    occurred_at: datetime | None = None

    @field_validator("source_ref")
    @classmethod
    def clean_source_ref(cls, value: str) -> str:
        return _clean_untrusted_string(value, "source_ref", allow_layout_controls=False)


class KnownAnswer(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60)
    state: Literal["known"]
    value: str = Field(min_length=1, max_length=500)
    selected_type: str | None = Field(default=None, min_length=1, max_length=120)
    evidence_excerpt: str = Field(min_length=1, max_length=500)

    @field_validator("value", "evidence_excerpt")
    @classmethod
    def clean_known_string(cls, value: str, info) -> str:
        return _clean_untrusted_string(value, info.field_name)

    @field_validator("selected_type")
    @classmethod
    def clean_selected_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_untrusted_string(value, "selected_type")


class UnknownAnswer(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60)
    state: Literal["unknown"]


class SkipAnswer(ClosedModel):
    slot_id: str = Field(min_length=1, max_length=60)
    state: Literal["skip"]


SlotAnswer = Annotated[KnownAnswer | UnknownAnswer | SkipAnswer, Field(discriminator="state")]


class EnrichmentAnswerCreate(ClosedModel):
    resolution_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    authorization_id: str = Field(min_length=1, max_length=36)
    source: EnrichmentSource
    source_excerpt: str | None = Field(default=None, min_length=1, max_length=2000)
    answers: list[SlotAnswer] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def exact_answers(self):
        ids = [answer.slot_id for answer in self.answers]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("answers must be unique and sorted by slot_id")
        known = [answer for answer in self.answers if answer.state == "known"]
        if known and self.source_excerpt is None:
            raise ValueError("source_excerpt is required for known answers")
        if not known and self.source_excerpt is not None:
            raise ValueError("source_excerpt must be absent without known answers")
        if self.source_excerpt is not None:
            _clean_untrusted_string(self.source_excerpt, "source_excerpt")
        for answer in known:
            if answer.evidence_excerpt not in self.source_excerpt:
                raise ValueError("evidence_excerpt must be contained in source_excerpt")
        return self


class EnrichmentAuthorizationRead(ClosedModel, PublicReadModel):
    id: str
    authorization_ref: str
    subject_entity_id: str
    topic: str
    status: str
    entity_snapshots: list[dict]
    slots: list[dict]
    slot_states: dict[str, str]
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    answer_capability: str


class EnrichmentAnswerRead(ClosedModel, PublicReadModel):
    id: str
    resolution_id: str
    authorization_id: str
    status: str
    verification_state: str
    slot_outcomes: list[dict]
    derived_candidate_ids: list[str]
    episode_id: str | None = None
    canonical_refs: list[str]
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime


def _clean_untrusted_string(
    value: str,
    field_name: str,
    *,
    allow_layout_controls: bool = True,
) -> str:
    if value != value.strip():
        raise ValueError(f"{field_name} must be trimmed and non-blank")
    allowed_controls = {"\t", "\n", "\r"} if allow_layout_controls else set()
    if any(ord(char) < 32 and char not in allowed_controls for char in value):
        raise ValueError(f"{field_name} contains unsupported control characters")
    if "\x7f" in value:
        raise ValueError(f"{field_name} contains unsupported control characters")
    return value
