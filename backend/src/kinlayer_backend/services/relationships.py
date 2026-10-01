from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.schemas.common import without_retired_write_metadata
from kinlayer_backend.config import Settings
from kinlayer_backend.models import (
    AllowedEdgeType,
    AllowedObservationType,
    Entity,
    EntityEdge,
    Episode,
    Observation,
)
from kinlayer_backend.repositories.relationships import RelationshipRepository
from kinlayer_backend.services.embeddings import EmbeddingService
from kinlayer_backend.services.entity_guards import lock_active_entities, require_memory_change_for_tracked_record
from kinlayer_backend.services.entities import validate_common
from kinlayer_backend.services.ontology import is_allowed_registry_value

OBSERVATION_ROLES = {"subject", "related", "mentioned", "speaker", "target", "experiencer", "about"}


class RelationshipService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or Settings()
        self.repository = RelationshipRepository(session)

    def _entity(self, entity_id: str) -> Entity:
        entity = self.session.get(Entity, entity_id)
        if not entity:
            raise api_error(404, "not_found", "Entity not found.")
        return entity

    def _edge_type(self, relation_type: str) -> AllowedEdgeType:
        statement = select(AllowedEdgeType).where(
            AllowedEdgeType.relation_type == relation_type,
            AllowedEdgeType.active.is_(True),
        )
        edge_type = self.session.execute(statement).scalar_one_or_none()
        if not edge_type:
            raise api_error(422, "validation_error", "Invalid relation_type.")
        return edge_type

    def create_edge(self, payload: dict[str, Any], commit: bool = True) -> EntityEdge:
        payload = without_retired_write_metadata(payload)
        validate_common(payload, self.session)
        entities = lock_active_entities(
            self.session, [payload["from_entity_id"], payload["to_entity_id"]]
        )
        from_entity = entities[payload["from_entity_id"]]
        to_entity = entities[payload["to_entity_id"]]
        edge_type = self._edge_type(payload["relation_type"])
        if (
            from_entity.entity_type != edge_type.from_entity_type
            or to_entity.entity_type != edge_type.to_entity_type
        ):
            raise api_error(422, "validation_error", "Relation endpoint entity types do not match.")
        if payload.get("directed") is None:
            payload["directed"] = edge_type.directed_default
        return self.repository.add_edge(payload, commit=commit)

    def patch_edge(self, edge: EntityEdge, payload: dict[str, Any]) -> EntityEdge:
        require_memory_change_for_tracked_record(self.session, edge)
        payload = without_retired_write_metadata(payload)
        validate_common(payload, self.session)
        lock_active_entities(
            self.session, [edge.from_entity_id, edge.to_entity_id]
        )
        if "relation_type" in payload and payload["relation_type"]:
            from_entity = self._entity(edge.from_entity_id)
            to_entity = self._entity(edge.to_entity_id)
            edge_type = self._edge_type(payload["relation_type"])
            if (
                from_entity.entity_type != edge_type.from_entity_type
                or to_entity.entity_type != edge_type.to_entity_type
            ):
                raise api_error(
                    422,
                    "validation_error",
                    "Relation endpoint entity types do not match.",
                )
        for key, value in payload.items():
            setattr(edge, key, value)
        self.repository.commit_refresh(edge)
        return edge

    def delete_edge(self, edge: EntityEdge) -> EntityEdge:
        require_memory_change_for_tracked_record(self.session, edge)
        edge.status = "deleted"
        edge.valid_to = datetime.now(UTC)
        self.repository.commit_refresh(edge)
        return edge

    def _validate_observation_type(self, observation_type: str) -> None:
        statement = select(AllowedObservationType).where(
            AllowedObservationType.observation_type == observation_type,
            AllowedObservationType.active.is_(True),
        )
        if not self.session.execute(statement).scalar_one_or_none():
            raise api_error(422, "validation_error", "Invalid observation_type.")

    def create_observation(self, payload: dict[str, Any], commit: bool = True) -> Observation:
        payload = without_retired_write_metadata(payload)
        related_entities = payload.pop("related_entities", [])
        validate_common(payload, self.session)
        lock_active_entities(
            self.session,
            [payload["subject_entity_id"]]
            + [related["entity_id"] for related in related_entities],
        )
        self._validate_observation_type(payload["observation_type"])
        for related in related_entities:
            if related["role"] not in OBSERVATION_ROLES:
                raise api_error(422, "validation_error", "Invalid related entity role.")
        self._parse_observation_temporal_fields(payload)
        payload["embedding_status"] = "pending"
        observation = self.repository.add_observation(payload, related_entities, commit=commit)
        EmbeddingService(self.session, self.settings).embed_observation(observation, commit=commit)
        return observation

    def patch_observation(self, observation: Observation, payload: dict[str, Any]) -> Observation:
        require_memory_change_for_tracked_record(self.session, observation)
        payload = without_retired_write_metadata(payload)
        validate_common(payload, self.session)
        related = self.repository.list_observation_entities(observation.id)
        lock_active_entities(
            self.session,
            [observation.subject_entity_id]
            + [item.entity_id for item in related],
        )
        if "observation_type" in payload and payload["observation_type"]:
            self._validate_observation_type(payload["observation_type"])
        content_changed = "content" in payload and payload["content"] != observation.content
        for key, value in payload.items():
            setattr(observation, key, value)
        if content_changed:
            observation.embedding_status = "pending"
            observation.embedding = None
            observation.embedding_error = None
            observation.embedding_created_at = None
        self.repository.commit_refresh(observation)
        if content_changed:
            EmbeddingService(self.session, self.settings).embed_observation(observation)
        return observation

    def _parse_observation_temporal_fields(self, payload: dict[str, Any]) -> None:
        for field in ("valid_from", "valid_to", "occurred_at"):
            value = payload.get(field)
            if isinstance(value, str):
                try:
                    payload[field] = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise api_error(422, "validation_error", f"Invalid {field}.") from exc

    def delete_observation(self, observation: Observation) -> Observation:
        require_memory_change_for_tracked_record(self.session, observation)
        observation.status = "deleted"
        observation.valid_to = datetime.now(UTC)
        self.repository.commit_refresh(observation)
        return observation

    def create_episode(self, payload: dict[str, Any], commit: bool = True) -> Episode:
        payload = without_retired_write_metadata(payload)
        validate_common(payload, self.session)
        if not is_allowed_registry_value(self.session, "retention_policy", payload["retention_policy"]):
            raise api_error(422, "validation_error", "Invalid retention_policy.")
        if not is_allowed_registry_value(self.session, "evidence_source_type", payload["source_type"]):
            raise api_error(422, "validation_error", "Invalid source_type.")
        return self.repository.add_episode(payload, commit=commit)
