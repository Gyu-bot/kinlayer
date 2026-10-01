from copy import deepcopy

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import (
    AllowedEdgeType,
    AllowedObservationType,
    Entity,
    EntityEdge,
    OntologyRegistryValue,
)
from kinlayer_backend.repositories.ontology import OntologyRepository

from kinlayer_backend.services.relationship_ontology import (
    EDGE_DEFINITIONS, EDGE_PROPERTIES_SCHEMA, ONTOLOGY_VERSION, edge_type_metadata,
)

REGISTRY_SEEDS: dict[str, list[tuple[str, str, str]]] = {
    "entity_type": [
        ("person", "Person", "supported"),
        ("organization", "Organization", "reserved"),
        ("place", "Place", "reserved"),
        ("event", "Event", "reserved"),
        ("topic", "Topic", "reserved"),
        ("account", "Account", "reserved"),
    ],
    "fact_type": [
        ("legal_name", "Legal name", "supported"),
        ("birth_date", "Birth date", "supported"),
        ("phone", "Phone", "supported"),
        ("email", "Email", "supported"),
        ("address", "Address", "supported"),
        ("role", "Role", "supported"),
        ("job", "Job", "supported"),
        ("organization", "Organization", "supported"),
        ("memo", "Memo (legacy)", "legacy"),
        ("birthday", "Birthday", "supported"),
        ("contact_note", "Contact note (legacy)", "legacy"),
        ("relationship_note", "Relationship note (legacy)", "legacy"),
        ("important_context", "Important context (legacy)", "legacy"),
        ("external_handle", "External handle", "supported"),
        ("location_hint", "Location hint", "supported"),
    ],
    "claim_type": [
        ("fact", "Fact", "legacy"),
        ("inference", "Inference", "legacy"),
        ("preference", "Preference", "legacy"),
        ("pattern", "Pattern", "legacy"),
    ],
    "claim_basis": [
        ("reported", "Reported by a source", "supported"),
        ("inferred", "Inferred from sources", "supported"),
        ("unknown", "Basis unknown", "supported"),
    ],
    "participant_role": [
        ("about", "About this person", "supported"),
        ("speaker", "Speaker", "supported"),
        ("experiencer", "Experiencer", "supported"),
        ("subject", "Subject", "supported"),
        ("related", "Related person", "supported"),
        ("mentioned", "Mentioned person", "legacy"),
        ("target", "Target person", "legacy"),
    ],
    "ai_use_policy": [
        ("freely_use", "Freely use", "legacy"),
        ("cautious_use", "Cautious use", "legacy"),
        ("ask_before_use", "Ask before use", "legacy"),
        ("never_surface", "Never surface", "legacy"),
    ],
    "edge_type": [
        (value, definition.label, definition.support_level)
        for value, definition in EDGE_DEFINITIONS.items()
    ],
    "observation_type": [
        ("stable_fact", "Stable fact", "supported"),
        ("preference", "General preferences and interests", "supported"),
        ("communication_preference", "Communication preference", "supported"),
        ("relationship_pattern", "Relationship pattern", "supported"),
        ("care_point", "Care point", "supported"),
        ("caution", "Caution", "supported"),
        ("recent_interaction", "Recent interaction", "supported"),
        ("user_feeling", "User feeling", "supported"),
        ("follow_up_context", "Follow-up context", "supported"),
    ],
    "retention_policy": [
        ("excerpt_only", "Excerpt only", "supported"),
        ("metadata_only", "Metadata only", "supported"),
    ],
    "evidence_source_type": [
        ("agent_conversation", "Agent conversation", "supported"),
        ("manual_entry", "Manual entry", "supported"),
        ("import", "Import", "supported"),
        ("connector", "Connector", "supported"),
        ("correction", "Correction", "supported"),
    ],
    "candidate_type": [
        ("new_entity", "New entity", "supported"),
        ("alias", "Alias", "supported"),
        ("profile_field", "Profile field", "supported"),
        ("relationship_edge", "Relationship edge", "supported"),
        ("observation", "Observation", "supported"),
        ("merge", "Merge", "supported"),
        ("conflict", "Conflict", "supported"),
        ("supersede", "Supersede", "supported"),
    ],
}

CREATED_BY_VALUES = {"user", "ai_agent", "connector", "import", "system"}
ENTITY_STATUSES = {"active", "merged", "deleted"}
CONFIRMATION_STATUSES = {"confirmed", "candidate", "rejected", "deprecated", "merged", "disputed"}
RECORD_STATUSES = {"active", "deprecated", "disputed", "superseded", "deleted"}
CANDIDATE_STATUSES = {
    "pending",
    "accepted",
    "edited_accepted",
    "rejected",
    "archived",
    "needs_clarification",
    "superseded",
}


def normalize_name(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def seed_ontology_values(session: Session) -> None:
    existing = {
        (row.category, row.value): row
        for row in session.execute(select(OntologyRegistryValue)).scalars().all()
    }
    for category, rows in REGISTRY_SEEDS.items():
        for sort_order, (value, label, support_level) in enumerate(rows):
            description = None
            if category == "edge_type":
                description = EDGE_DEFINITIONS[value].description
            elif category == "fact_type" and support_level == "legacy":
                description = (
                    "Legacy free-form fact retained for compatibility. "
                    "Use a specific profile fact or an atomic observation for new records."
                )
            elif category == "ai_use_policy":
                description = "Retired metadata; it does not authorize or restrict AI use."
            elif category == "claim_type":
                description = (
                    "Legacy classification. New records use claim_basis separately "
                    "from their semantic fact, relationship, or observation type."
                )
            elif category == "claim_basis":
                description = {
                    "reported": "A source explicitly states this; it is not independent verification.",
                    "inferred": "An interpretation derived from linked sources.",
                    "unknown": "The stored evidence does not establish the assertion basis.",
                }[value]
            if (category, value) in existing:
                # Registry documentation changes do not rewrite historical records or digests.
                if category == "edge_type":
                    existing[category, value].label = label
                    existing[category, value].sort_order = sort_order
                    existing[category, value].is_active = True
                if description is not None:
                    existing[category, value].support_level = support_level
                    existing[category, value].description = description
                continue
            session.add(
                OntologyRegistryValue(
                    category=category,
                    value=value,
                    label=label,
                    support_level=support_level,
                    description=description,
                    sort_order=sort_order,
                )
            )
    session.commit()
    seed_allowed_edge_types(session)
    seed_allowed_observation_types(session)


def seed_allowed_edge_types(session: Session) -> None:
    existing = {
        row.relation_type: row
        for row in session.execute(select(AllowedEdgeType)).scalars().all()
    }
    for value, definition in EDGE_DEFINITIONS.items():
        row = existing.get(value)
        if row is None:
            row = AllowedEdgeType(relation_type=value)
            session.add(row)
        # Update only definitions; historical EntityEdge values are untouched.
        row.from_entity_type = "person"
        row.to_entity_type = "person"
        row.directed_default = definition.directed
        row.inverse_relation_type = None  # inverse is a view label, not a second predicate
        row.allowed_properties_schema = deepcopy(EDGE_PROPERTIES_SCHEMA)
        row.description = definition.description
        row.examples = [{
            "from_role": definition.label,
            "to_role": definition.inverse_label or definition.label,
            "relation_type": value,
            "directed": definition.directed,
            "properties": {"context": "출처에 명시된 관계 배경"},
        }]
        row.active = True  # legacy kinds stay readable by graph/history queries
    session.commit()


def seed_allowed_observation_types(session: Session) -> None:
    existing = {
        row.observation_type
        for row in session.execute(select(AllowedObservationType)).scalars().all()
    }
    for value, label, _support in REGISTRY_SEEDS["observation_type"]:
        if value in existing:
            continue
        session.add(
            AllowedObservationType(
                observation_type=value,
                description=label,
                examples=[],
                active=True,
            )
        )
    session.commit()


def allowed_values(category: str) -> set[str]:
    return {value for value, _label, _support in REGISTRY_SEEDS[category]}


def is_allowed_registry_value(session: Session, category: str, value: str) -> bool:
    statement = select(OntologyRegistryValue).where(
        OntologyRegistryValue.category == category,
        OntologyRegistryValue.value == value,
        OntologyRegistryValue.is_active.is_(True),
    )
    return session.execute(statement).scalar_one_or_none() is not None


class OntologyReadService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = OntologyRepository(session)

    def all_ontology(self) -> dict:
        return {
            "version": ONTOLOGY_VERSION,
            "entity_types": self.repository.registry_values("entity_type"),
            "fact_types": self.repository.registry_values("fact_type"),
            "claim_bases": self.repository.registry_values("claim_basis"),
            "participant_roles": self.repository.registry_values("participant_role"),
            "edge_types": self.edge_types(),
            "observation_types": self.repository.observation_types(),
            "policies": self.policies(),
        }

    def edge_types(self) -> list[dict]:
        return [
            {**{column.name: getattr(row, column.name) for column in row.__table__.columns},
             **edge_type_metadata(row)}
            for row in self.repository.edge_types()
        ]

    def policies(self) -> dict:
        return {
            "ai_use_policies": self.repository.registry_values("ai_use_policy"),
            "claim_types": self.repository.registry_values("claim_type"),
            "candidate_types": self.repository.registry_values("candidate_type"),
        }

    def edge_type_diagnostics(self) -> dict:
        allowed_by_relation_type = {
            row.relation_type: row
            for row in self.session.execute(
                select(AllowedEdgeType).where(AllowedEdgeType.active.is_(True))
            ).scalars()
        }
        rows = self.session.execute(
            select(
                EntityEdge.relation_type,
                func.count(),
                func.sum(case((EntityEdge.status == "active", 1), else_=0)),
            )
            .group_by(EntityEdge.relation_type)
            .order_by(EntityEdge.relation_type)
        ).all()
        relation_types = [
            {
                "relation_type": relation_type,
                "exists_in_allowed_edge_types": relation_type in allowed_by_relation_type,
                "edge_count": count,
                "active_edge_count": active_count or 0,
            }
            for relation_type, count, active_count in rows
        ]

        invalid_edges = []
        statement = select(EntityEdge).order_by(EntityEdge.created_at.desc())
        for edge in self.session.execute(statement).scalars().all():
            from_entity = self.session.get(Entity, edge.from_entity_id)
            to_entity = self.session.get(Entity, edge.to_entity_id)
            edge_type = allowed_by_relation_type.get(edge.relation_type)
            edge_type_match = "active_allowed_edge_type"
            if not edge_type:
                edge_type_match = "missing_allowed_edge_type"
            elif (
                not from_entity
                or not to_entity
                or from_entity.entity_type != edge_type.from_entity_type
                or to_entity.entity_type != edge_type.to_entity_type
            ):
                edge_type_match = "endpoint_type_mismatch"
            if edge_type_match == "active_allowed_edge_type":
                continue
            invalid_edges.append(
                {
                    "edge_id": edge.id,
                    "relation_type": edge.relation_type,
                    "edge_type_match": edge_type_match,
                    "from_entity_id": edge.from_entity_id,
                    "to_entity_id": edge.to_entity_id,
                    "from_entity_type": from_entity.entity_type if from_entity else None,
                    "to_entity_type": to_entity.entity_type if to_entity else None,
                    "status": edge.status,
                    "created_by": edge.created_by,
                    "source_candidate_id": edge.source_candidate_id,
                    "created_at": edge.created_at,
                    "updated_at": edge.updated_at,
                }
            )
        return {"relation_types": relation_types, "invalid_edges": invalid_edges}
