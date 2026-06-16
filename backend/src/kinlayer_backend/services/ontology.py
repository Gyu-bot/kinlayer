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
        ("memo", "Memo", "supported"),
        ("birthday", "Birthday", "supported"),
        ("contact_note", "Contact note", "supported"),
        ("relationship_note", "Relationship note", "supported"),
        ("important_context", "Important context", "supported"),
        ("external_handle", "External handle", "supported"),
        ("location_hint", "Location hint", "supported"),
    ],
    "claim_type": [
        ("fact", "Fact", "supported"),
        ("inference", "Inference", "supported"),
        ("preference", "Preference", "supported"),
        ("pattern", "Pattern", "supported"),
    ],
    "sensitivity": [
        ("low", "Low", "supported"),
        ("medium", "Medium", "supported"),
        ("high", "High", "supported"),
    ],
    "ai_use_policy": [
        ("freely_use", "Freely use", "supported"),
        ("cautious_use", "Cautious use", "supported"),
        ("ask_before_use", "Ask before use", "supported"),
        ("never_surface", "Never surface", "supported"),
    ],
    "edge_type": [
        ("knows", "Knows", "supported"),
        ("friend", "Friend", "supported"),
        ("family", "Family", "supported"),
        ("acquaintance", "Acquaintance", "supported"),
        ("coworker", "Coworker", "supported"),
        ("former_coworker", "Former coworker", "supported"),
        ("client_contact", "Client contact", "supported"),
        ("vendor_contact", "Vendor contact", "supported"),
        ("reports_to", "Reports to", "supported"),
        ("manager_of", "Manager of", "supported"),
        ("introduced_by", "Introduced by", "supported"),
        ("referred_by", "Referred by", "supported"),
        ("collaborated_with", "Collaborated with", "supported"),
        ("dating_interest", "Dating interest", "supported"),
        ("dating", "Dating", "supported"),
        ("former_dating", "Former dating", "supported"),
        ("romantic_partner", "Romantic partner", "supported"),
        ("former_partner", "Former partner", "supported"),
        ("introduced_for_dating", "Introduced for dating", "supported"),
        ("matched_on_app", "Matched on app", "supported"),
    ],
    "observation_type": [
        ("stable_fact", "Stable fact", "supported"),
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
ENTITY_STATUSES = {"active", "deleted"}
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
        (row.category, row.value)
        for row in session.execute(select(OntologyRegistryValue)).scalars().all()
    }
    for category, rows in REGISTRY_SEEDS.items():
        for sort_order, (value, label, support_level) in enumerate(rows):
            if (category, value) in existing:
                continue
            session.add(
                OntologyRegistryValue(
                    category=category,
                    value=value,
                    label=label,
                    support_level=support_level,
                    sort_order=sort_order,
                )
            )
    session.commit()
    seed_allowed_edge_types(session)
    seed_allowed_observation_types(session)


def seed_allowed_edge_types(session: Session) -> None:
    existing = {
        row.relation_type
        for row in session.execute(select(AllowedEdgeType)).scalars().all()
    }
    directed = {
        "reports_to",
        "manager_of",
        "introduced_by",
        "referred_by",
        "introduced_for_dating",
    }
    for sort_order, (value, label, _support) in enumerate(REGISTRY_SEEDS["edge_type"]):
        if value in existing:
            continue
        session.add(
            AllowedEdgeType(
                relation_type=value,
                from_entity_type="person",
                to_entity_type="person",
                directed_default=value in directed,
                allowed_properties_schema={},
                description=label,
                examples=[],
                active=True,
            )
        )
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
            "entity_types": self.repository.registry_values("entity_type"),
            "fact_types": self.repository.registry_values("fact_type"),
            "edge_types": self.repository.edge_types(),
            "observation_types": self.repository.observation_types(),
            "policies": self.policies(),
        }

    def policies(self) -> dict:
        return {
            "sensitivity_levels": self.repository.registry_values("sensitivity"),
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
