from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    AllowedEdgeType,
    AllowedObservationType,
    Candidate,
    EdgeEvidence,
    Entity,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Episode,
    Observation,
    ObservationEvidence,
)
from kinlayer_backend.repositories.candidates import CandidateRepository
from kinlayer_backend.repositories.entities import EntityRepository
from kinlayer_backend.schemas.candidates import PAYLOAD_MODELS
from kinlayer_backend.services.entities import EntityService, validate_common
from kinlayer_backend.services.ontology import is_allowed_registry_value
from kinlayer_backend.services.relationships import RelationshipService

SUGGESTED_ACTIONS = {"review", "accept", "reject", "clarify"}
TERMINAL_STATUSES = {"accepted", "edited_accepted", "rejected", "archived", "superseded"}


class CandidateService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CandidateRepository(session)

    def create_candidate(self, payload: dict[str, Any]) -> Candidate:
        evidence = payload.pop("evidence", [])
        validate_common(payload, self.session)
        if not is_allowed_registry_value(self.session, "candidate_type", payload["candidate_type"]):
            raise api_error(422, "validation_error", "Invalid candidate_type.")
        suggested_action = payload.get("suggested_action")
        if suggested_action and suggested_action not in SUGGESTED_ACTIONS:
            raise api_error(422, "validation_error", "Invalid suggested_action.")
        target_entity_id = payload.get("target_entity_id")
        if target_entity_id and not self.session.get(Entity, target_entity_id):
            raise api_error(404, "not_found", "Target entity not found.")
        supersedes_candidate_id = payload.get("supersedes_candidate_id")
        if supersedes_candidate_id and not self.session.get(Candidate, supersedes_candidate_id):
            raise api_error(404, "not_found", "Superseded candidate not found.")
        if payload.get("created_by") == "ai_agent" and not evidence:
            raise api_error(422, "validation_error", "Agent-submitted candidates require evidence.")
        for item in evidence:
            episode = self.session.get(Episode, item["episode_id"])
            if not episode:
                raise api_error(404, "not_found", "Evidence episode not found.")
            if payload.get("created_by") == "ai_agent":
                self._validate_agent_evidence(item, episode)
        self._validate_payload(payload["candidate_type"], payload["payload"])
        payload.setdefault("status", "pending")
        return self.repository.add_candidate(payload, evidence)

    def patch_candidate(self, candidate: Candidate, payload: dict[str, Any]) -> Candidate:
        validate_common(payload, self.session)
        suggested_action = payload.get("suggested_action")
        if suggested_action and suggested_action not in SUGGESTED_ACTIONS:
            raise api_error(422, "validation_error", "Invalid suggested_action.")
        target_entity_id = payload.get("target_entity_id")
        if target_entity_id and not self.session.get(Entity, target_entity_id):
            raise api_error(404, "not_found", "Target entity not found.")
        for key, value in payload.items():
            setattr(candidate, key, value)
        return self.repository.commit_refresh(candidate)

    def archive_candidate(
        self,
        candidate: Candidate,
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        return self._resolve(candidate, "archived", resolution_note, resolved_by)

    def reject_candidate(
        self,
        candidate: Candidate,
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        return self._resolve(candidate, "rejected", resolution_note, resolved_by)

    def needs_clarification(
        self,
        candidate: Candidate,
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        return self._resolve(candidate, "needs_clarification", resolution_note, resolved_by)

    def supersede_candidate(
        self,
        candidate: Candidate,
        supersedes_candidate_id: str,
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        if not self.session.get(Candidate, supersedes_candidate_id):
            raise api_error(404, "not_found", "Superseding candidate not found.")
        candidate.supersedes_candidate_id = supersedes_candidate_id
        return self._resolve(candidate, "superseded", resolution_note, resolved_by)

    def accept_candidate(
        self,
        candidate: Candidate,
        status: str = "accepted",
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        try:
            self._ensure_resolvable(candidate)
            canonical_record_ref = self._write_canonical_record(candidate)
            candidate.canonical_record_ref = canonical_record_ref
            self._resolve(candidate, status, resolution_note, resolved_by, commit=False)
            self.session.commit()
            self.session.refresh(candidate)
            return candidate
        except Exception:
            self.session.rollback()
            raise

    def edit_accept_candidate(
        self,
        candidate: Candidate,
        edited_payload: dict[str, Any],
        resolution_note: str | None = None,
        resolved_by: str = "user",
    ) -> Candidate:
        try:
            candidate.payload = PAYLOAD_MODELS[candidate.candidate_type].model_validate(
                edited_payload
            ).model_dump(exclude_none=True)
        except (KeyError, ValidationError) as exc:
            raise api_error(422, "validation_error", "Invalid candidate payload.") from exc
        self._validate_payload(candidate.candidate_type, candidate.payload)
        return self.accept_candidate(
            candidate,
            status="edited_accepted",
            resolution_note=resolution_note,
            resolved_by=resolved_by,
        )

    def _entity(self, entity_id: str) -> Entity:
        entity = self.session.get(Entity, entity_id)
        if not entity:
            raise api_error(404, "not_found", "Entity not found.")
        return entity

    def _validate_agent_evidence(self, item: dict[str, Any], episode: Episode) -> None:
        if not item.get("excerpt") or not item["excerpt"].strip():
            raise api_error(422, "validation_error", "Agent evidence excerpt is required.")
        if not episode.source_ref:
            raise api_error(422, "validation_error", "Agent evidence source_ref is required.")
        if not episode.body_hash or not episode.actor:
            raise api_error(422, "validation_error", "Agent evidence provenance is incomplete.")
        if not is_allowed_registry_value(self.session, "evidence_source_type", episode.source_type):
            raise api_error(422, "validation_error", "Unsupported evidence source_type.")

    def _validate_payload(self, candidate_type: str, payload: dict[str, Any]) -> None:
        if candidate_type == "new_entity":
            validate_common(payload, self.session)
            return
        if candidate_type == "alias":
            self._entity(payload["entity_id"])
            return
        if candidate_type == "profile_field":
            self._entity(payload["entity_id"])
            validate_common(payload, self.session)
            if payload.get("fact_type") and not is_allowed_registry_value(
                self.session, "fact_type", payload["fact_type"]
            ):
                raise api_error(422, "validation_error", "Invalid fact_type.")
            return
        if candidate_type == "relationship_edge":
            self._validate_edge_payload(payload)
            return
        if candidate_type == "observation":
            self._validate_observation_payload(payload)
            return
        if candidate_type == "merge":
            source = self._entity(payload["source_entity_id"])
            target = self._entity(payload["target_entity_id"])
            if source.id == target.id:
                raise api_error(422, "validation_error", "Merge source and target must differ.")
            return
        if candidate_type == "conflict":
            for record_ref in payload["record_refs"]:
                self._validate_record_ref(record_ref)
            return
        if candidate_type == "supersede":
            self._validate_record_ref(payload["old_record_ref"])

    def _ensure_resolvable(self, candidate: Candidate) -> None:
        if candidate.status in TERMINAL_STATUSES:
            raise api_error(409, "conflict", "Candidate is already resolved.")

    def _resolve(
        self,
        candidate: Candidate,
        status: str,
        resolution_note: str | None = None,
        resolved_by: str = "user",
        commit: bool = True,
    ) -> Candidate:
        self._ensure_resolvable(candidate)
        candidate.status = status
        candidate.resolution_note = resolution_note
        candidate.resolved_by = resolved_by
        candidate.resolved_at = datetime.now(UTC)
        if commit:
            return self.repository.commit_refresh(candidate)
        self.session.flush()
        return candidate

    def _write_canonical_record(self, candidate: Candidate) -> str:
        if candidate.candidate_type == "new_entity":
            return self._write_entity(candidate)
        if candidate.candidate_type == "alias":
            return self._write_alias(candidate)
        if candidate.candidate_type == "profile_field":
            return self._write_profile_field(candidate)
        if candidate.candidate_type == "relationship_edge":
            return self._write_edge(candidate)
        if candidate.candidate_type == "observation":
            return self._write_observation(candidate)
        if candidate.candidate_type in {"merge", "conflict", "supersede"}:
            raise api_error(
                422,
                "validation_error",
                "This candidate type requires a later correction or review workflow.",
            )
        raise api_error(422, "validation_error", "Invalid candidate_type.")

    def _write_entity(self, candidate: Candidate) -> str:
        payload = {
            "created_by": candidate.created_by,
            **candidate.payload,
        }
        entity = EntityService(self.session).create_entity(payload, commit=False)
        return f"entities:{entity.id}"

    def _write_alias(self, candidate: Candidate) -> str:
        payload = candidate.payload
        entity = self._entity(payload["entity_id"])
        alias_payload = {
            "alias": payload["alias"],
            "confidence": payload.get("confidence", candidate.confidence),
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
        }
        alias = EntityRepository(self.session).add_alias(entity.id, alias_payload, commit=False)
        return f"entity_aliases:{alias.id}"

    def _write_profile_field(self, candidate: Candidate) -> str:
        payload = candidate.payload
        content = payload.get("content")
        if content is None:
            content = str(payload.get("value", ""))
        fact_payload = {
            "entity_id": payload["entity_id"],
            "fact_type": payload.get("fact_type") or "important_context",
            "content": str(content),
            "value": {
                "field_path": payload.get("field_path"),
                "value": payload.get("value"),
            },
            "claim_type": payload["claim_type"],
            "confidence": candidate.confidence,
            "sensitivity": payload.get("sensitivity") or candidate.sensitivity,
            "ai_use_policy": payload.get("ai_use_policy", "cautious_use"),
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
        }
        fact = EntityService(self.session).create_fact(fact_payload, commit=False)
        self._copy_fact_evidence(candidate, fact.id)
        return f"entity_facts:{fact.id}"

    def _write_edge(self, candidate: Candidate) -> str:
        payload = {
            "confidence": candidate.confidence,
            "sensitivity": candidate.sensitivity,
            "ai_use_policy": "cautious_use",
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
            **candidate.payload,
        }
        edge = RelationshipService(self.session).create_edge(payload, commit=False)
        self._copy_edge_evidence(candidate, edge.id)
        return f"entity_edges:{edge.id}"

    def _write_observation(self, candidate: Candidate) -> str:
        payload = {
            "confidence": candidate.confidence,
            "sensitivity": candidate.sensitivity,
            "ai_use_policy": "cautious_use",
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
            **candidate.payload,
        }
        related_entity_ids = payload.pop("related_entity_ids", [])
        payload["related_entities"] = [
            {"entity_id": entity_id, "role": "related"} for entity_id in related_entity_ids
        ]
        observation = RelationshipService(self.session).create_observation(payload, commit=False)
        self._copy_observation_evidence(candidate, observation.id)
        return f"observations:{observation.id}"

    def _write_merge(self, candidate: Candidate) -> str:
        source = self._entity(candidate.payload["source_entity_id"])
        target = self._entity(candidate.payload["target_entity_id"])
        source.status = "deleted"
        source.confirmation_status = "merged"
        self.session.flush()
        return f"entities:{target.id}"

    def _write_conflict(self, candidate: Candidate) -> str:
        for record_ref in candidate.payload["record_refs"]:
            self._mark_record_status(record_ref, "disputed")
        self.session.flush()
        return f"candidates:{candidate.id}"

    def _write_supersede(self, candidate: Candidate) -> str:
        self._mark_record_status(candidate.payload["old_record_ref"], "superseded")
        self.session.flush()
        return candidate.payload["old_record_ref"]

    def _copy_fact_evidence(self, candidate: Candidate, fact_id: str) -> None:
        for evidence in candidate.evidence:
            self.session.add(
                EntityFactEvidence(
                    entity_fact_id=fact_id,
                    episode_id=evidence.episode_id,
                    excerpt=evidence.excerpt,
                    confidence=evidence.confidence,
                )
            )
        self.session.flush()

    def _copy_edge_evidence(self, candidate: Candidate, edge_id: str) -> None:
        for evidence in candidate.evidence:
            self.session.add(
                EdgeEvidence(
                    edge_id=edge_id,
                    episode_id=evidence.episode_id,
                    excerpt=evidence.excerpt,
                    confidence=evidence.confidence,
                )
            )
        self.session.flush()

    def _copy_observation_evidence(self, candidate: Candidate, observation_id: str) -> None:
        for evidence in candidate.evidence:
            self.session.add(
                ObservationEvidence(
                    observation_id=observation_id,
                    episode_id=evidence.episode_id,
                    excerpt=evidence.excerpt,
                    confidence=evidence.confidence,
                )
            )
        self.session.flush()

    def _mark_record_status(self, record_ref: str, status: str) -> None:
        self._validate_record_ref(record_ref)
        prefix, _separator, record_id = record_ref.partition(":")
        model_by_prefix = {
            "entities": Entity,
            "entity_facts": EntityFact,
            "entity_edges": EntityEdge,
            "observations": Observation,
        }
        model = model_by_prefix.get(prefix)
        if not model:
            return
        record = self.session.get(model, record_id)
        if record and hasattr(record, "status"):
            record.status = status

    def _validate_edge_payload(self, payload: dict[str, Any]) -> None:
        from_entity = self._entity(payload["from_entity_id"])
        to_entity = self._entity(payload["to_entity_id"])
        validate_common(payload, self.session)
        statement = select(AllowedEdgeType).where(
            AllowedEdgeType.relation_type == payload["relation_type"],
            AllowedEdgeType.active.is_(True),
        )
        edge_type = self.session.execute(statement).scalar_one_or_none()
        if not edge_type:
            raise api_error(422, "validation_error", "Invalid relation_type.")
        if (
            from_entity.entity_type != edge_type.from_entity_type
            or to_entity.entity_type != edge_type.to_entity_type
        ):
            raise api_error(422, "validation_error", "Relation endpoint entity types do not match.")

    def _validate_observation_payload(self, payload: dict[str, Any]) -> None:
        self._entity(payload["subject_entity_id"])
        validate_common(payload, self.session)
        statement = select(AllowedObservationType).where(
            AllowedObservationType.observation_type == payload["observation_type"],
            AllowedObservationType.active.is_(True),
        )
        if not self.session.execute(statement).scalar_one_or_none():
            raise api_error(422, "validation_error", "Invalid observation_type.")
        for entity_id in payload.get("related_entity_ids", []):
            self._entity(entity_id)

    def _validate_record_ref(self, record_ref: str) -> None:
        allowed_prefixes = {
            "entities",
            "entity_aliases",
            "entity_facts",
            "entity_edges",
            "observations",
            "candidates",
        }
        prefix, separator, record_id = record_ref.partition(":")
        if not separator or not record_id or prefix not in allowed_prefixes:
            raise api_error(422, "validation_error", "Invalid record reference.")
