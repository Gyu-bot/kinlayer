from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from typing import assert_never

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.schemas.common import without_legacy_sensitivity
from kinlayer_backend.models import (
    AllowedEdgeType,
    AllowedObservationType,
    Candidate,
    EdgeEvidence,
    Entity,
    EntityAlias,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    EntityMerge,
    Episode,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.repositories.candidates import CandidateRepository
from kinlayer_backend.schemas.candidates import PAYLOAD_MODELS
from kinlayer_backend.services.entities import (
    EntityService,
    FactPromotionPayload,
    JsonValue,
    validate_common,
)
from kinlayer_backend.services.entity_guards import lock_active_entities
from kinlayer_backend.services.ontology import is_allowed_registry_value
from kinlayer_backend.services.relationships import RelationshipService
from kinlayer_backend.services.structured_facts import (
    InvalidStructuredFactContent,
    ValidStructuredFactContent,
    is_structured_fact_type,
    validate_structured_fact_content,
)

SUGGESTED_ACTIONS = {"review", "accept", "reject", "clarify"}
TERMINAL_STATUSES = {"accepted", "edited_accepted", "rejected", "archived", "superseded"}
DEFAULT_MERGE_FIELDS = ["aliases", "profile_facts", "edges", "observations"]


@dataclass(frozen=True, slots=True)
class CandidatePayloadValidation:
    candidate_type: str
    payload: dict[str, JsonValue]
    target_entity_id: str | None = None
    supersedes_record_ref: str | None = None


class CandidateService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CandidateRepository(session)

    def create_candidate(self, payload: dict[str, Any], *, commit: bool = True,
                         material_import_id: str | None = None) -> Candidate:
        payload = without_legacy_sensitivity(payload)
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
            if episode.material_import_id and episode.material_import_id != material_import_id:
                raise api_error(422, "material_import_link_required", "Use the explicit material import operation.")
            if payload.get("created_by") == "ai_agent":
                self._validate_agent_evidence(item, episode)
        self._validate_payload(
            CandidatePayloadValidation(
                candidate_type=payload["candidate_type"],
                payload=payload["payload"],
                target_entity_id=payload.get("target_entity_id"),
                supersedes_record_ref=payload.get("supersedes_record_ref"),
            )
        )
        payload.setdefault("status", "pending")
        return self.repository.add_candidate(payload, evidence, commit=commit)

    def patch_candidate(self, candidate: Candidate, payload: dict[str, Any]) -> Candidate:
        payload = without_legacy_sensitivity(payload)
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
        commit: bool = True,
    ) -> Candidate:
        candidate = self._lock_resolvable_candidate(candidate.id)
        return self._accept_locked_candidate(
            candidate,
            status=status,
            resolution_note=resolution_note,
            resolved_by=resolved_by,
            commit=commit,
        )

    def _accept_locked_candidate(
        self,
        candidate: Candidate,
        *,
        status: str,
        resolution_note: str | None,
        resolved_by: str,
        commit: bool,
    ) -> Candidate:
        try:
            from kinlayer_backend.services.material_provenance import material_provenance

            for evidence in candidate.evidence:
                if (evidence.episode.material_import_id or evidence.episode.source_type == "import") and not material_provenance(self.session, evidence):
                    raise api_error(409, "material_import_changed", "Imported source linkage or synthesis changed; re-import for review.")
            candidate.resolved_by = resolved_by
            canonical_record_ref = self._write_canonical_record(candidate)
            candidate.canonical_record_ref = canonical_record_ref
            self._resolve(candidate, status, resolution_note, resolved_by, commit=False)
            if commit:
                self.session.commit()
                self.session.refresh(candidate)
            else:
                self.session.flush()
            return candidate
        except IntegrityError as exc:
            self.session.rollback()
            if self._is_source_candidate_conflict(exc):
                raise api_error(
                    409,
                    "candidate_already_canonicalized",
                    "Candidate already produced a canonical record.",
                ) from exc
            raise
        except Exception:
            self.session.rollback()
            raise

    def edit_accept_candidate(
        self,
        candidate: Candidate,
        edited_payload: dict[str, Any],
        resolution_note: str | None = None,
        resolved_by: str = "user",
        commit: bool = True,
    ) -> Candidate:
        candidate = self._lock_resolvable_candidate(candidate.id)
        try:
            validated_payload = PAYLOAD_MODELS[candidate.candidate_type].model_validate(
                edited_payload
            ).model_dump(mode="json", exclude_none=True)
        except (KeyError, ValidationError) as exc:
            raise api_error(422, "validation_error", "Invalid candidate payload.") from exc
        self._validate_payload(
            CandidatePayloadValidation(
                candidate_type=candidate.candidate_type,
                payload=validated_payload,
                target_entity_id=candidate.target_entity_id,
                supersedes_record_ref=candidate.supersedes_record_ref,
            )
        )
        candidate.payload = validated_payload
        return self._accept_locked_candidate(
            candidate,
            status="edited_accepted",
            resolution_note=resolution_note,
            resolved_by=resolved_by,
            commit=commit,
        )

    def _lock_resolvable_candidate(self, candidate_id: str) -> Candidate:
        candidate = self.repository.lock_candidate(candidate_id)
        if not candidate:
            raise api_error(404, "not_found", "Candidate not found.")
        self._ensure_resolvable(candidate)
        return candidate

    @staticmethod
    def _is_source_candidate_conflict(exc: IntegrityError) -> bool:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        return constraint_name in {
            "ux_entity_aliases_source_candidate_id",
            "ux_entity_facts_source_candidate_id",
            "ux_entity_edges_source_candidate_id",
            "ux_observations_source_candidate_id",
            "ux_entity_merges_candidate_id",
        } or "source_candidate_id" in str(exc.orig) or "entity_merges.candidate_id" in str(exc.orig)

    def _entity(self, entity_id: str) -> Entity:
        entity = self.session.get(Entity, entity_id)
        if not entity:
            raise api_error(404, "not_found", "Entity not found.")
        if entity.status != "active":
            raise api_error(409, "conflict", "Entity is not active.")
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

    def _validate_payload(self, request: CandidatePayloadValidation) -> None:
        candidate_type = request.candidate_type
        payload = request.payload
        if candidate_type == "new_entity":
            validate_common(payload, self.session)
            return
        if candidate_type == "alias":
            self._entity(payload["entity_id"])
            return
        if candidate_type == "profile_field":
            self._entity(payload["entity_id"])
            if request.target_entity_id and payload["entity_id"] != request.target_entity_id:
                raise api_error(
                    422,
                    "validation_error",
                    "Profile field target_entity_id must match payload entity_id.",
                )
            if request.supersedes_record_ref:
                self._validate_profile_field_supersedes_ref(
                    request.supersedes_record_ref,
                    payload["entity_id"],
                )
            validate_common(payload, self.session)
            fact_type = payload.get("fact_type") or "important_context"
            if payload.get("fact_type") and not is_allowed_registry_value(self.session, "fact_type", fact_type):
                raise api_error(422, "validation_error", "Invalid fact_type.")
            content = payload.get("content")
            if content is None and is_structured_fact_type(fact_type):
                content = payload.get("value")
                if not isinstance(content, str):
                    raise api_error(
                        422,
                        "validation_error",
                        "Structured fact content must be a string.",
                    )
            if content is not None:
                result = validate_structured_fact_content(fact_type, content)
                match result:
                    case ValidStructuredFactContent(content=normalized):
                        payload["content"] = normalized
                    case InvalidStructuredFactContent(message=message):
                        raise api_error(422, "validation_error", message)
                    case unreachable:
                        assert_never(unreachable)
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
            if source.system_role == "self" or target.system_role == "self":
                raise api_error(403, "forbidden", "Protected self cannot be merged.")
            if source.entity_type != "person" or target.entity_type != "person":
                raise api_error(422, "validation_error", "Only person entities can be merged.")
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
        if candidate.candidate_type == "merge":
            return self._write_merge(candidate)
        if candidate.candidate_type in {"conflict", "supersede"}:
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
        alias_payload = {
            "alias": payload["alias"],
            "confidence": payload.get("confidence", candidate.confidence),
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
        }
        entity = self._entity(payload["entity_id"])
        alias = EntityService(self.session).create_alias(entity, alias_payload, commit=False)
        return f"entity_aliases:{alias.id}"

    def _write_profile_field(self, candidate: Candidate) -> str:
        payload = candidate.payload
        fact_type = payload.get("fact_type") or "important_context"
        content = payload.get("content")
        if content is None:
            value = payload.get("value", "")
            if is_structured_fact_type(fact_type) and not isinstance(value, str):
                raise api_error(422, "validation_error", "Structured fact content must be a string.")
            content = value if isinstance(value, str) else str(value)
        if not isinstance(content, str):
            if is_structured_fact_type(fact_type):
                raise api_error(422, "validation_error", "Structured fact content must be a string.")
            content = str(content)
        if candidate.supersedes_record_ref:
            return self._promote_profile_field(candidate, content)
        fact_payload = {
            "entity_id": payload["entity_id"],
            "fact_type": fact_type,
            "content": content,
            "value": {
                "field_path": payload.get("field_path"),
                "value": payload.get("value"),
            },
            "claim_type": payload["claim_type"],
            "claim_basis": payload.get("claim_basis", "inferred" if payload["claim_type"] == "inference" else "unknown"),
            "confidence": candidate.confidence,
            "ai_use_policy": payload.get("ai_use_policy", "cautious_use"),
            "created_by": candidate.created_by,
            "source_candidate_id": candidate.id,
        }
        fact = EntityService(self.session).create_fact(fact_payload, commit=False)
        self._copy_fact_evidence(candidate, fact.id)
        return f"entity_facts:{fact.id}"

    def _promote_profile_field(self, candidate: Candidate, content: str) -> str:
        payload = candidate.payload
        source = self._source_fact_from_ref(candidate.supersedes_record_ref)
        result = EntityService(self.session).promote_fact(
            source,
            FactPromotionPayload(
                entity_id=payload["entity_id"],
                fact_type=payload.get("fact_type") or "important_context",
                content=content,
                field_path=payload.get("field_path"),
                value=payload.get("value"),
                ai_use_policy=payload.get("ai_use_policy"),
                created_by=candidate.created_by,
                source_candidate_id=candidate.id,
            ),
            commit=False,
        )
        self._copy_fact_evidence(candidate, result.replacement.id)
        return f"entity_facts:{result.replacement.id}"

    def _write_edge(self, candidate: Candidate) -> str:
        payload = {
            "confidence": candidate.confidence,
            "claim_basis": "inferred" if candidate.payload["claim_type"] == "inference" else "unknown",
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
            "claim_basis": "inferred" if candidate.payload["claim_type"] == "inference" else "unknown",
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
        entities = lock_active_entities(
            self.session,
            [candidate.payload["source_entity_id"], candidate.payload["target_entity_id"]],
        )
        source = entities[candidate.payload["source_entity_id"]]
        target = entities[candidate.payload["target_entity_id"]]
        if source.id == target.id:
            raise api_error(422, "validation_error", "Merge source and target must differ.")
        if source.system_role == "self" or target.system_role == "self":
            raise api_error(403, "forbidden", "Protected self cannot be merged.")
        if source.entity_type != "person" or target.entity_type != "person":
            raise api_error(422, "validation_error", "Only person entities can be merged.")
        fields_to_merge = candidate.payload.get("fields_to_merge") or DEFAULT_MERGE_FIELDS
        previous_refs = self._merge_previous_refs(source.id)
        if "aliases" in fields_to_merge:
            self._merge_aliases(source.id, target.id)
        if "profile_facts" in fields_to_merge or "facts" in fields_to_merge:
            self._merge_facts(source.id, target.id)
        if "edges" in fields_to_merge:
            self._repoint_merge_edges(source.id, target.id)
        if "observations" in fields_to_merge:
            self._repoint_merge_observations(source.id, target.id)
        merged_entity_ref = f"entities:{target.id}"
        source.status = "merged"
        source.confirmation_status = "merged"
        source.properties = {
            **(source.properties or {}),
            "merged_entity_ref": merged_entity_ref,
            "merge_candidate_id": candidate.id,
        }
        self.session.add(
            EntityMerge(
                source_entity_id=source.id,
                target_entity_id=target.id,
                candidate_id=candidate.id,
                merge_plan={
                    "fields_to_merge": fields_to_merge,
                    **(candidate.payload.get("merge_plan") or {}),
                },
                conflict_decisions=candidate.payload.get("field_conflict_policy") or {},
                actor=candidate.resolved_by or candidate.created_by,
                canonical_record_ref=merged_entity_ref,
                previous_refs=previous_refs,
            )
        )
        self.session.flush()
        return merged_entity_ref

    def _merge_previous_refs(self, source_id: str) -> dict[str, list[str]]:
        aliases = self.session.execute(
            select(EntityAlias.id).where(EntityAlias.entity_id == source_id)
        ).scalars().all()
        facts = self.session.execute(
            select(EntityFact.id).where(EntityFact.entity_id == source_id)
        ).scalars().all()
        edges = self.session.execute(
            select(EntityEdge.id).where(
                (EntityEdge.from_entity_id == source_id) | (EntityEdge.to_entity_id == source_id)
            )
        ).scalars().all()
        observations = self.session.execute(
            select(Observation.id).where(Observation.subject_entity_id == source_id)
        ).scalars().all()
        related_observations = self.session.execute(
            select(ObservationEntity.observation_id).where(ObservationEntity.entity_id == source_id)
        ).scalars().all()
        return {
            "aliases": aliases,
            "profile_facts": facts,
            "edges": edges,
            "observations": sorted(set([*observations, *related_observations])),
        }

    def _merge_aliases(self, source_id: str, target_id: str) -> None:
        target_aliases = {
            alias.normalized_alias
            for alias in self.session.execute(
                select(EntityAlias).where(
                    EntityAlias.entity_id == target_id,
                    EntityAlias.status == "active",
                )
            ).scalars()
        }
        for alias in self.session.execute(
            select(EntityAlias).where(
                EntityAlias.entity_id == source_id,
                EntityAlias.status == "active",
            )
        ).scalars():
            if alias.normalized_alias in target_aliases:
                alias.status = "deprecated"
                continue
            alias.entity_id = target_id
            target_aliases.add(alias.normalized_alias)

    def _merge_facts(self, source_id: str, target_id: str) -> None:
        target_facts = self.session.execute(
            select(EntityFact).where(EntityFact.entity_id == target_id, EntityFact.status == "active")
        ).scalars().all()
        for fact in self.session.execute(
            select(EntityFact).where(EntityFact.entity_id == source_id, EntityFact.status == "active")
        ).scalars():
            duplicate = next(
                (
                    target_fact
                    for target_fact in target_facts
                    if target_fact.fact_type == fact.fact_type and target_fact.content == fact.content
                ),
                None,
            )
            conflict = any(
                target_fact.fact_type == fact.fact_type and target_fact.content != fact.content
                for target_fact in target_facts
            )
            if duplicate:
                fact.status = "deprecated"
                continue
            if conflict:
                continue
            fact.entity_id = target_id
            target_facts.append(fact)

    def _repoint_merge_edges(self, source_id: str, target_id: str) -> None:
        edges = self.session.execute(
            select(EntityEdge).where(
                EntityEdge.status == "active",
                (EntityEdge.from_entity_id == source_id) | (EntityEdge.to_entity_id == source_id),
            )
        ).scalars().all()
        for edge in edges:
            next_from = target_id if edge.from_entity_id == source_id else edge.from_entity_id
            next_to = target_id if edge.to_entity_id == source_id else edge.to_entity_id
            if next_from == next_to or self._active_duplicate_edge(edge, next_from, next_to):
                edge.status = "deprecated"
                continue
            edge.from_entity_id = next_from
            edge.to_entity_id = next_to

    def _active_duplicate_edge(self, edge: EntityEdge, from_entity_id: str, to_entity_id: str) -> bool:
        statement = select(EntityEdge.id).where(
            EntityEdge.id != edge.id,
            EntityEdge.status == "active",
            EntityEdge.from_entity_id == from_entity_id,
            EntityEdge.to_entity_id == to_entity_id,
            EntityEdge.relation_type == edge.relation_type,
            EntityEdge.directed == edge.directed,
        )
        return self.session.execute(statement).first() is not None

    def _repoint_merge_observations(self, source_id: str, target_id: str) -> None:
        for observation in self.session.execute(
            select(Observation).where(
                Observation.status == "active",
                Observation.subject_entity_id == source_id,
            )
        ).scalars():
            observation.subject_entity_id = target_id
        rows = self.session.execute(
            select(ObservationEntity).where(ObservationEntity.entity_id == source_id)
        ).scalars().all()
        for row in rows:
            duplicate = self.session.execute(
                select(ObservationEntity).where(
                    ObservationEntity.id != row.id,
                    ObservationEntity.observation_id == row.observation_id,
                    ObservationEntity.entity_id == target_id,
                    ObservationEntity.role == row.role,
                )
            ).scalar_one_or_none()
            if duplicate:
                self.session.delete(row)
            else:
                row.entity_id = target_id

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

    def _validate_profile_field_supersedes_ref(
        self,
        record_ref: str,
        entity_id: str,
    ) -> None:
        source = self._source_fact_from_ref(record_ref)
        if source.entity_id != entity_id:
            raise api_error(
                422,
                "validation_error",
                "Profile field supersedes_record_ref must belong to the same entity.",
            )

    def _source_fact_from_ref(self, record_ref: str | None) -> EntityFact:
        if record_ref is None:
            raise api_error(422, "validation_error", "supersedes_record_ref is required.")
        prefix, separator, record_id = record_ref.partition(":")
        if not separator or not record_id or prefix != "entity_facts":
            raise api_error(
                422,
                "validation_error",
                "Profile field supersedes_record_ref must use entity_facts:<id>.",
            )
        source = self.session.get(EntityFact, record_id)
        if source is None:
            raise api_error(404, "not_found", "Superseded source fact not found.")
        if source.status != "active":
            raise api_error(409, "conflict", "Superseded source fact is not active.")
        self._entity(source.entity_id)
        return source
