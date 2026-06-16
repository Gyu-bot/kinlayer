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


class EdgeTypeDiagnostic(APIModel):
    relation_type: str
    exists_in_allowed_edge_types: bool
    edge_count: int
    active_edge_count: int


class InvalidEdgeDiagnostic(APIModel):
    edge_id: str
    relation_type: str
    edge_type_match: str
    from_entity_id: str
    to_entity_id: str
    from_entity_type: str | None = None
    to_entity_type: str | None = None
    status: str
    created_by: str
    source_candidate_id: str | None = None
    created_at: datetime
    updated_at: datetime


class EdgeTypeDiagnosticsRead(APIModel):
    relation_types: list[EdgeTypeDiagnostic]
    invalid_edges: list[InvalidEdgeDiagnostic]


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
