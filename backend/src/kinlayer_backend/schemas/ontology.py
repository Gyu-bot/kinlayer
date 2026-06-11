from datetime import datetime
from typing import Any

from kinlayer_backend.schemas.common import APIModel


class RegistryValueRead(APIModel):
    category: str
    value: str
    label: str
    description: str | None = None
    support_level: str
    is_active: bool
    sort_order: int


class EdgeTypeRead(APIModel):
    relation_type: str
    from_entity_type: str
    to_entity_type: str
    directed_default: bool
    inverse_relation_type: str | None = None
    allowed_properties_schema: dict[str, Any] | None = None
    description: str | None = None
    examples: list[Any] | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class ObservationTypeRead(APIModel):
    observation_type: str
    description: str | None = None
    examples: list[Any] | None = None
    active: bool
    created_at: datetime
    updated_at: datetime


class RegistryList(APIModel):
    items: list[RegistryValueRead]


class EdgeTypeList(APIModel):
    items: list[EdgeTypeRead]


class ObservationTypeList(APIModel):
    items: list[ObservationTypeRead]


class PoliciesRead(APIModel):
    sensitivity_levels: list[RegistryValueRead]
    ai_use_policies: list[RegistryValueRead]
    claim_types: list[RegistryValueRead]
    candidate_types: list[RegistryValueRead]


class OntologyRead(APIModel):
    entity_types: list[RegistryValueRead]
    fact_types: list[RegistryValueRead]
    edge_types: list[EdgeTypeRead]
    observation_types: list[ObservationTypeRead]
    policies: PoliciesRead
