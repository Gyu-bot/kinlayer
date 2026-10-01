from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from typing import TypeAlias

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    EdgeEvidence,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Episode,
    Observation,
    ObservationEvidence,
)
from kinlayer_backend.repositories.relationships import RelationshipRepository
from kinlayer_backend.schemas.corrections import CorrectionNewRecord
from kinlayer_backend.services.entities import EntityService
from kinlayer_backend.services.relationships import RelationshipService

OldCanonicalRecord: TypeAlias = EntityEdge | EntityFact | Observation


class CorrectionService:
    def __init__(self, session: Session):
        self.session = session

    def apply_correction(self, payload: dict[str, Any]) -> dict[str, str]:
        try:
            source = payload["correction_source"]
            if source["user_explicit"] is not True:
                raise api_error(
                    422,
                    "validation_error",
                    "Direct correction apply requires explicit user correction.",
            )
            old_prefix, old_id = self._parse_record_ref(payload["old_record_ref"])
            old_record = self._get_record(old_prefix, old_id)
            new_record = CorrectionNewRecord.model_validate(payload["new_record"])
            self._validate_fact_replacement(old_record, new_record)
            new_record_ref = self._write_new_record(
                new_record.model_dump(mode="json"),
                payload["created_by"],
            )
            episode = self._create_correction_episode(source, payload["created_by"])
            self._link_evidence(new_record_ref, episode.id, source["excerpt"])
            self._supersede_old_record(old_record, new_record_ref)
            self.session.commit()
            return {
                "old_record_ref": payload["old_record_ref"],
                "new_record_ref": new_record_ref,
                "episode_id": episode.id,
                "source_actor": source.get("source_actor", "user"),
                "submitted_by": payload["created_by"],
            }
        except (HTTPException, SQLAlchemyError, RuntimeError):
            self.session.rollback()
            raise

    def _parse_record_ref(self, record_ref: str) -> tuple[str, str]:
        prefix, separator, record_id = record_ref.partition(":")
        if not separator or not record_id:
            raise api_error(422, "validation_error", "Invalid record reference.")
        return prefix, record_id

    def _get_record(self, prefix: str, record_id: str) -> OldCanonicalRecord:
        if prefix == "entity_edges":
            record = self.session.get(EntityEdge, record_id)
        elif prefix == "entity_facts":
            record = self.session.get(EntityFact, record_id)
        elif prefix == "observations":
            record = self.session.get(Observation, record_id)
        else:
            raise api_error(422, "validation_error", "Unsupported record reference.")
        if not record:
            raise api_error(404, "not_found", "Old canonical record not found.")
        return record

    def _validate_fact_replacement(
        self,
        old_record: OldCanonicalRecord,
        new_record: CorrectionNewRecord,
    ) -> None:
        if not isinstance(old_record, EntityFact):
            return
        if old_record.status != "active":
            raise api_error(409, "conflict", "Old source fact is not active.")
        if new_record.record_type != "entity_facts":
            return
        if new_record.payload["entity_id"] != old_record.entity_id:
            raise api_error(
                422,
                "validation_error",
                "Fact correction replacement must target the old fact entity.",
            )

    def _write_new_record(self, new_record: dict[str, Any], created_by: str) -> str:
        record_type = new_record["record_type"]
        payload = {"created_by": created_by, **new_record["payload"]}
        if record_type == "entity_edges":
            edge = RelationshipService(self.session).create_edge(payload, commit=False)
            return f"entity_edges:{edge.id}"
        if record_type == "observations":
            related_entity_ids = payload.pop("related_entity_ids", [])
            payload.setdefault(
                "related_entities",
                [{"entity_id": entity_id, "role": "related"} for entity_id in related_entity_ids],
            )
            observation = RelationshipService(self.session).create_observation(payload, commit=False)
            return f"observations:{observation.id}"
        if record_type == "entity_facts":
            fact = EntityService(self.session).create_fact(payload, commit=False)
            return f"entity_facts:{fact.id}"
        raise api_error(422, "validation_error", "Unsupported new record type.")

    def _create_correction_episode(self, source: dict[str, Any], created_by: str) -> Episode:
        excerpt = source["excerpt"]
        source_actor = source.get("source_actor", "user")
        return RelationshipRepository(self.session).add_episode(
            {
                "source_type": "correction",
                "source_ref": source.get("source_ref"),
                "source_description": (
                    f"Explicit correction from {source['source_type']}; "
                    f"source_actor={source_actor}; submitted_by={created_by}"
                ),
                "body_excerpt": excerpt,
                "body_hash": f"sha256:{sha256(excerpt.encode()).hexdigest()}",
                "actor": source_actor,
                "occurred_at": source.get("occurred_at"),
                "retention_policy": "excerpt_only",
            },
            commit=False,
        )

    def _link_evidence(self, record_ref: str, episode_id: str, excerpt: str) -> None:
        prefix, record_id = self._parse_record_ref(record_ref)
        if prefix == "entity_edges":
            self.session.add(
                EdgeEvidence(edge_id=record_id, episode_id=episode_id, excerpt=excerpt, confidence=1.0)
            )
        elif prefix == "observations":
            self.session.add(
                ObservationEvidence(
                    observation_id=record_id,
                    episode_id=episode_id,
                    excerpt=excerpt,
                    confidence=1.0,
                )
            )
        elif prefix == "entity_facts":
            self.session.add(
                EntityFactEvidence(
                    entity_fact_id=record_id,
                    episode_id=episode_id,
                    excerpt=excerpt,
                    confidence=1.0,
                )
            )
        self.session.flush()

    def _supersede_old_record(self, record, new_record_ref: str) -> None:
        if hasattr(record, "status"):
            record.status = "superseded"
        if hasattr(record, "valid_to"):
            record.valid_to = datetime.now(UTC)
        new_prefix, _separator, new_id = new_record_ref.partition(":")
        if isinstance(record, EntityEdge) and new_prefix == "entity_edges":
            record.invalidated_by_edge_id = new_id
        self.session.flush()
