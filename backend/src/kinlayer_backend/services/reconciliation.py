from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    AgentWriteOperationAudit,
    Candidate,
    CandidateEvidence,
    Entity,
    EntityAlias,
    EntityEdge,
    EntityFact,
    EntityMerge,
    Episode,
    Observation,
    ObservationEntity,
    ReconciliationAction,
)
from kinlayer_backend.repositories.reconciliation import ReconciliationRepository
from kinlayer_backend.schemas.reconciliation import ReconciliationActionCreate
from kinlayer_backend.services.candidate_snapshots import (
    candidate_evidence_digest,
    candidate_payload_digest,
    digest as _digest,
    entity_digest,
)
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.candidates import DEFAULT_MERGE_FIELDS
from kinlayer_backend.services.context import ContextService
from kinlayer_backend.services.entities import EntityService
from kinlayer_backend.services.ontology import normalize_name
from kinlayer_backend.services.relationships import RelationshipService

ROLE_TITLES = {
    "boss", "ceo", "coach", "coworker", "colleague", "doctor", "friend",
    "manager", "mentor", "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "professor",
    "teacher", "he", "her", "him", "she", "they", "them", "you", "엄마", "아빠",
    "친구", "동료", "과장", "과장님", "교수님", "대리", "대리님", "대표", "대표님",
    "부장", "부장님", "사장", "사장님", "상무", "상무님", "선생님", "이사", "이사님",
    "임원", "임원님", "전무", "전무님", "차장", "차장님", "팀장", "팀장님", "회장",
    "회장님",
}


def request_fingerprint(body: ReconciliationActionCreate) -> str:
    normalized = body.model_dump(mode="json")
    normalized["candidate_ids"] = sorted(normalized["candidate_ids"])
    normalized["expected_candidates"] = sorted(
        normalized["expected_candidates"], key=lambda item: item["id"]
    )
    normalized["expected_entities"] = sorted(
        normalized["expected_entities"], key=lambda item: item["id"]
    )
    return _digest(normalized)


class ReconciliationService:
    def __init__(self, session: Session, session_factory: sessionmaker[Session]):
        self.session = session
        self.session_factory = session_factory
        self.repository = ReconciliationRepository(session)

    def apply(self, body: ReconciliationActionCreate) -> dict[str, Any]:
        fingerprint = request_fingerprint(body)
        existing = self.repository.get_by_resolution_id(body.resolution_id)
        if existing:
            self._ensure_same_request(existing, fingerprint)
            return self._verify_in_fresh_session(existing.id)

        action = ReconciliationAction(
            resolution_id=body.resolution_id,
            action_type=body.action,
            request_fingerprint=fingerprint,
            candidate_ids=sorted(body.candidate_ids),
            expected_candidates=[
                item.model_dump(mode="json")
                for item in sorted(body.expected_candidates, key=lambda item: item.id)
            ],
            expected_entities=[
                item.model_dump(mode="json")
                for item in sorted(body.expected_entities, key=lambda item: item.id)
            ],
            source_entity_id=body.source_entity_id,
            target_entity_id=body.target_entity_id,
        )
        self.session.add(action)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            existing = self.repository.get_by_resolution_id(body.resolution_id)
            if not existing:
                raise
            self._ensure_same_request(existing, fingerprint)
            return self._verify_in_fresh_session(existing.id)

        try:
            candidates = self.repository.lock_candidates(sorted(body.candidate_ids))
            if len(candidates) != len(body.candidate_ids):
                raise api_error(404, "not_found", "Candidate not found.")
            self._validate_snapshots(candidates, body)
            self._validate_candidate_types(candidates, body.action)
            entities = self.repository.lock_entities(sorted(
                item.id for item in body.expected_entities
            ))
            if len(entities) != len(body.expected_entities):
                raise api_error(404, "not_found", "Entity not found.")
            self._validate_entity_snapshots(entities, body)
            episode = self._create_confirmation_episode(body)
            action.confirmation_episode_id = episode.id
            self._execute(action, candidates, entities, body)
            action.status = "committed_unverified"
            action.committed_at = datetime.now(UTC)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self._verify_in_fresh_session(action.id)

    def get(self, action_id: str) -> dict[str, Any]:
        action = self.repository.get_by_id(action_id)
        if not action:
            raise api_error(404, "not_found", "Reconciliation action not found.")
        return self._verify_in_fresh_session(action.id)

    def list_entity_snapshots(self, limit: int, offset: int) -> dict[str, Any]:
        where = (Entity.entity_type == "person", Entity.status == "active")
        total = self.session.scalar(select(func.count(Entity.id)).where(*where)) or 0
        entities = list(
            self.session.scalars(
                select(Entity)
                .where(*where)
                .order_by(Entity.id)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        return {
            "items": [
                {
                    "id": entity.id,
                    "entity_type": entity.entity_type,
                    "display_name": entity.display_name,
                    "canonical_name": entity.canonical_name,
                    "status": entity.status,
                    "updated_at": entity.updated_at,
                    "entity_digest": entity_digest(entity),
                }
                for entity in entities
            ],
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    @staticmethod
    def _ensure_same_request(action: ReconciliationAction, fingerprint: str) -> None:
        if action.request_fingerprint != fingerprint:
            raise api_error(409, "idempotency_conflict", "resolution_id was reused.")

    def _validate_snapshots(
        self, candidates: list[Candidate], body: ReconciliationActionCreate
    ) -> None:
        expected = {item.id: item for item in body.expected_candidates}
        for candidate in candidates:
            item = expected[candidate.id]
            actual_time = candidate.updated_at
            reviewed_time = item.updated_at
            if actual_time.tzinfo is None:
                actual_time = actual_time.replace(tzinfo=UTC)
            if reviewed_time.tzinfo is None:
                reviewed_time = reviewed_time.replace(tzinfo=UTC)
            exact = (
                candidate.status == item.status
                and actual_time.astimezone(UTC) == reviewed_time.astimezone(UTC)
                and candidate_payload_digest(candidate) == item.payload_digest
                and candidate_evidence_digest(self.session, candidate.id) == item.evidence_digest
            )
            if not exact:
                raise api_error(409, "stale_candidate", "Candidate snapshot changed.")

    @staticmethod
    def _validate_candidate_types(candidates: list[Candidate], action: str) -> None:
        if action in {
            "map_to_existing_entity", "confirm_new_entity_group",
            "rename_and_accept_new_entity",
        } and any(item.candidate_type != "new_entity" for item in candidates):
            raise api_error(422, "validation_error", "Action requires new_entity candidates.")
        if action == "rename_and_accept_new_entity" and not candidates:
            raise api_error(422, "validation_error", "Rename requires a candidate.")

    @staticmethod
    def _validate_entity_snapshots(
        entities: list[Entity], body: ReconciliationActionCreate
    ) -> None:
        expected = {item.id: item for item in body.expected_entities}
        for entity in entities:
            item = expected[entity.id]
            actual_time = entity.updated_at
            reviewed_time = item.updated_at
            if actual_time.tzinfo is None:
                actual_time = actual_time.replace(tzinfo=UTC)
            if reviewed_time.tzinfo is None:
                reviewed_time = reviewed_time.replace(tzinfo=UTC)
            if not (
                entity.status == item.status
                and actual_time.astimezone(UTC) == reviewed_time.astimezone(UTC)
                and entity_digest(entity) == item.entity_digest
            ):
                raise api_error(409, "stale_entity", "Entity snapshot changed.")

    def _create_confirmation_episode(self, body: ReconciliationActionCreate) -> Episode:
        return RelationshipService(self.session).create_episode(
            {
                "source_type": body.source.source_type,
                "source_ref": body.source.source_ref,
                "source_description": "Explicit user reconciliation confirmation",
                "body_excerpt": body.resolution_note,
                "body_hash": body.source.body_hash,
                "actor": body.source.source_actor,
                "sensitivity": "medium",
                "retention_policy": "excerpt_only",
            },
            commit=False,
        )

    def _execute(
        self,
        action: ReconciliationAction,
        candidates: list[Candidate],
        entities: list[Entity],
        body: ReconciliationActionCreate,
    ) -> None:
        service = CandidateService(self.session)
        retained = candidates[0] if candidates else None
        if body.action == "reject_candidates":
            for candidate in candidates:
                service._resolve(
                    candidate, "rejected", body.resolution_note, "user", commit=False
                )
        elif body.action == "map_to_existing_entity":
            target = entities[0]
            self._validate_map_target(target)
            for candidate in candidates:
                candidate.target_entity_id = target.id
                candidate.canonical_record_ref = f"entities:{target.id}"
                service._resolve(candidate, "accepted", body.resolution_note, "user", commit=False)
            action.target_entity_id = target.id
            action.primary_entity_id = target.id
            action.outcome_canonical_refs = [f"entities:{target.id}"]
        elif body.action == "merge_existing_entities":
            by_id = {entity.id: entity for entity in entities}
            source = by_id[body.source_entity_id or ""]
            target = by_id[body.target_entity_id or ""]
            self._validate_merge_entities(source, target)
            merge_candidate = service.create_candidate(
                {
                    "candidate_type": "merge",
                    "target_entity_id": target.id,
                    "payload": {
                        "source_entity_id": source.id,
                        "target_entity_id": target.id,
                        "reason": "Explicit user reconciliation confirmation",
                        "fields_to_merge": DEFAULT_MERGE_FIELDS,
                        "merge_plan": {
                            "aliases": "copy_non_conflicting",
                            "profile_facts": "copy_non_conflicting",
                            "edges": "repoint_without_self_or_duplicate_edges",
                            "observations": "repoint_related_entities",
                        },
                        "field_conflict_policy": {
                            "display_name": "keep_target",
                            "canonical_name": "keep_target",
                            "sensitivity": "use_more_restrictive",
                            "ai_use_policy": "use_more_restrictive",
                        },
                        "risk_notes": ["User explicitly confirmed this canonical merge."],
                        "merged_entity_ref": f"entities:{target.id}",
                    },
                    "evidence": [{
                        "episode_id": action.confirmation_episode_id,
                        "excerpt": body.resolution_note,
                        "confidence": 1.0,
                    }],
                    "confidence": 1.0,
                    "sensitivity": source.sensitivity or "medium",
                    "suggested_action": "review",
                    "created_by": "user",
                },
                commit=False,
            )
            service.accept_candidate(
                merge_candidate, resolution_note=body.resolution_note,
                resolved_by="user", commit=False,
            )
            self.session.add(AgentWriteOperationAudit(
                operation_type="reconciliation_merge_accept",
                source_path="reconciliation.actions",
                actor="user",
                result_status="success",
                request_summary={"action": body.action},
                diagnostics={},
                related_refs={"ledger_action_id": action.id},
                candidate_id=merge_candidate.id,
                episode_id=action.confirmation_episode_id,
                canonical_record_ref=f"entities:{target.id}",
                bounded_excerpt=body.resolution_note,
            ))
            action.primary_entity_id = target.id
            action.target_entity_id = target.id
            action.derived_candidate_ids = [merge_candidate.id]
            action.outcome_canonical_refs = [f"entities:{target.id}"]
        elif body.action == "archive_existing_entity":
            source = entities[0]
            self._validate_archive_entity(source)
            EntityService(self.session).delete_entity(source, commit=False)
            action.primary_entity_id = source.id
            action.outcome_canonical_refs = [f"entities:{source.id}"]
        else:
            assert retained is not None
            if body.action == "rename_and_accept_new_entity":
                self._assert_safe_new_name(body.display_name or "")
                if body.canonical_name:
                    self._assert_safe_new_name(body.canonical_name)
                edited_payload = {
                    **retained.payload,
                    "display_name": body.display_name,
                    "canonical_name": body.canonical_name or normalize_name(body.display_name or ""),
                }
            else:
                self._assert_safe_new_name(str(retained.payload.get("display_name", "")))
                canonical_name = retained.payload.get("canonical_name")
                if canonical_name:
                    self._assert_safe_new_name(str(canonical_name))
            if body.action == "rename_and_accept_new_entity":
                service.edit_accept_candidate(
                    retained, edited_payload, body.resolution_note, "user", commit=False
                )
            else:
                service.accept_candidate(
                    retained,
                    resolution_note=body.resolution_note,
                    resolved_by="user",
                    commit=False,
                )
            entity_id = (retained.canonical_record_ref or "").partition(":")[2]
            action.primary_entity_id = entity_id
            action.derived_candidate_ids = [item.id for item in candidates[1:]]
            action.outcome_canonical_refs = [retained.canonical_record_ref]
            for duplicate in candidates[1:]:
                duplicate.target_entity_id = entity_id
                duplicate.canonical_record_ref = retained.canonical_record_ref
                duplicate.supersedes_candidate_id = retained.id
                service._resolve(
                    duplicate, "superseded", body.resolution_note, "user", commit=False
                )

    @staticmethod
    def _validate_merge_entities(source: Entity, target: Entity) -> None:
        if source.id == target.id:
            raise api_error(422, "validation_error", "Merge source and target must differ.")
        if source.status != "active" or target.status != "active":
            raise api_error(409, "conflict", "Merge entities must both be active.")
        if source.entity_type != "person" or target.entity_type != "person":
            raise api_error(422, "validation_error", "Only person entities can be merged.")
        if source.system_role == "self" or target.system_role == "self" or source.is_system or target.is_system:
            raise api_error(403, "protected_self", "Protected/system entities cannot be merged.")

    def _validate_archive_entity(self, source: Entity) -> None:
        if source.status != "active":
            raise api_error(409, "conflict", "Archive source must be active.")
        if source.entity_type != "person":
            raise api_error(422, "validation_error", "Archive source must be a person.")
        if source.system_role == "self" or source.is_system:
            raise api_error(403, "protected_self", "Protected/system entities cannot be archived.")
        origin = self.session.scalar(select(Candidate).where(
            Candidate.candidate_type == "new_entity",
            Candidate.status.in_(["accepted", "edited_accepted"]),
            Candidate.canonical_record_ref == f"entities:{source.id}",
            or_(
                Candidate.resolved_by == "user",
                and_(
                    Candidate.resolved_by == "system",
                    Candidate.resolution_note == "curation:accept_existing",
                ),
            ),
        ))
        if not origin:
            raise api_error(409, "archive_not_eligible", "Entity was not created by the reviewed new-entity path.")
        owns_context = any(self.session.scalar(statement) is not None for statement in [
            select(EntityAlias.id).where(EntityAlias.entity_id == source.id, EntityAlias.status == "active").limit(1),
            select(EntityFact.id).where(EntityFact.entity_id == source.id, EntityFact.status == "active").limit(1),
            select(EntityEdge.id).where(EntityEdge.status == "active", ((EntityEdge.from_entity_id == source.id) | (EntityEdge.to_entity_id == source.id))).limit(1),
            select(Observation.id).where(Observation.status == "active", Observation.subject_entity_id == source.id).limit(1),
            select(ObservationEntity.id).join(Observation, Observation.id == ObservationEntity.observation_id).where(Observation.status == "active", ObservationEntity.entity_id == source.id).limit(1),
            select(EntityMerge.id).where((EntityMerge.source_entity_id == source.id) | (EntityMerge.target_entity_id == source.id)).limit(1),
        ])
        if owns_context:
            raise api_error(409, "entity_has_context", "Entity owns context; merge or correction is required.")

    def _validate_map_target(self, target: Entity) -> None:
        if target.status != "active":
            raise api_error(409, "conflict", "Target entity is not active.")
        if target.entity_type != "person":
            raise api_error(422, "validation_error", "Target must be an active person.")
        if target.system_role == "self" or target.is_system:
            raise api_error(403, "protected_self", "Protected self cannot be mapped.")
        self._assert_safe_new_name(target.display_name)

    def _assert_safe_new_name(self, name: str) -> None:
        normalized = normalize_name(name)
        if len(normalized) < 2 or normalized in ROLE_TITLES:
            raise api_error(422, "role_title_identity", "A stable person name is required.")
        protected = self.session.scalar(select(Entity).where(Entity.system_role == "self"))
        if protected:
            names = {normalize_name(protected.display_name), normalize_name(protected.canonical_name or "")}
            names.update(self.session.scalars(
                select(EntityAlias.alias).where(EntityAlias.entity_id == protected.id)
            ).all())
            if normalized in {normalize_name(item) for item in names if item}:
                raise api_error(403, "protected_self", "Protected self cannot be created.")

    def _verify_in_fresh_session(self, action_id: str) -> dict[str, Any]:
        try:
            with self.session_factory() as fresh:
                action = fresh.get(ReconciliationAction, action_id)
                if not action:
                    raise api_error(404, "not_found", "Reconciliation action not found.")
                if action.status == "verified" and action.readback_summary:
                    return action.readback_summary
                candidates = list(fresh.scalars(
                    select(Candidate).where(Candidate.id.in_(action.candidate_ids)).order_by(Candidate.id)
                ).all())
                entity = fresh.get(Entity, action.primary_entity_id) if action.primary_entity_id else None
                if len(candidates) != len(action.candidate_ids):
                    raise RuntimeError("candidate readback failed")
                if action.primary_entity_id and not entity:
                    raise RuntimeError("entity readback failed")
                if action.action_type != "archive_existing_entity" and entity and entity.status != "active":
                    raise RuntimeError("active entity readback failed")
                statuses = {item.status for item in candidates}
                if action.action_type == "reject_candidates" and statuses != {"rejected"}:
                    raise RuntimeError("rejected candidate readback mismatch")
                if action.action_type == "map_to_existing_entity" and any(
                    item.status != "accepted"
                    or item.canonical_record_ref != f"entities:{action.primary_entity_id}"
                    for item in candidates
                ):
                    raise RuntimeError("mapped candidate readback mismatch")
                if action.action_type in {
                    "confirm_new_entity_group", "rename_and_accept_new_entity"
                } and sum(
                    item.status in {"accepted", "edited_accepted"} for item in candidates
                ) != 1:
                    raise RuntimeError("group readback mismatch")
                if action.action_type == "merge_existing_entities":
                    derived = (
                        fresh.get(Candidate, action.derived_candidate_ids[0])
                        if len(action.derived_candidate_ids) == 1 else None
                    )
                    source = fresh.get(Entity, action.source_entity_id)
                    merge = fresh.scalar(select(EntityMerge).where(
                        EntityMerge.candidate_id == (derived.id if derived else "")
                    ))
                    evidence_ids = list(fresh.scalars(select(CandidateEvidence.episode_id).where(
                        CandidateEvidence.candidate_id == (derived.id if derived else "")
                    )).all())
                    audit = fresh.scalar(select(AgentWriteOperationAudit).where(
                        AgentWriteOperationAudit.candidate_id == (derived.id if derived else ""),
                        AgentWriteOperationAudit.episode_id == action.confirmation_episode_id,
                    ))
                    if (
                        not derived or derived.candidate_type != "merge"
                        or derived.status != "accepted" or derived.resolved_by != "user"
                        or derived.canonical_record_ref != f"entities:{action.target_entity_id}"
                        or not source or source.status != "merged"
                        or (source.properties or {}).get("merged_entity_ref") != f"entities:{action.target_entity_id}"
                        or not merge or merge.source_entity_id != action.source_entity_id
                        or merge.target_entity_id != action.target_entity_id
                        or evidence_ids != [action.confirmation_episode_id]
                        or not audit or audit.canonical_record_ref != f"entities:{action.target_entity_id}"
                    ):
                        raise RuntimeError("merge linkage readback mismatch")
                if action.action_type == "archive_existing_entity" and (
                    not entity or entity.status != "deleted"
                    or entity.confirmation_status != "deprecated"
                    or fresh.scalar(select(Entity.id).where(
                        Entity.id == action.source_entity_id,
                        Entity.status == "active",
                    )) is not None
                ):
                    raise RuntimeError("archived entity readback mismatch")
                if action.confirmation_episode_id and not fresh.get(
                    Episode, action.confirmation_episode_id
                ):
                    raise RuntimeError("confirmation episode readback failed")
                action.error_code = None
                summary = self._readback(action, candidates, entity, fresh)
                action.readback_summary = summary
                action.status = "verified"
                action.verified_at = datetime.now(UTC)
                fresh.commit()
                return summary
        except HTTPException:
            raise
        except Exception as exc:
            try:
                with self.session_factory() as error_session:
                    failed = error_session.get(ReconciliationAction, action_id)
                    if failed and failed.status == "committed_unverified":
                        failed.error_code = "readback_unavailable"
                        error_session.commit()
            except Exception:
                pass
            raise api_error(503, "readback_unavailable", "Committed action awaits readback retry.") from exc

    @staticmethod
    def _readback(
        action: ReconciliationAction,
        candidates: list[Candidate],
        entity: Entity | None,
        session: Session,
    ) -> dict[str, Any]:
        candidate_rows = []
        for candidate in candidates:
            evidence_ids = list(session.scalars(
                select(CandidateEvidence.episode_id)
                .where(CandidateEvidence.candidate_id == candidate.id)
                .order_by(CandidateEvidence.episode_id)
            ).all())
            candidate_rows.append({
                "id": candidate.id,
                "status": candidate.status,
                "updated_at": candidate.updated_at.isoformat(),
                "canonical_record_ref": candidate.canonical_record_ref,
                "evidence_episode_ids": evidence_ids,
            })
        entity_row = None
        context_card = None
        if entity:
            card = ContextService(session).context_card(entity.id) if entity.status == "active" else None
            aliases = [item.alias for item in card["aliases"]] if card else []
            entity_row = {
                "id": entity.id, "entity_type": entity.entity_type,
                "display_name": entity.display_name, "canonical_name": entity.canonical_name,
                "status": entity.status, "system_role": entity.system_role,
            }
            context_card = {
                "entity_id": entity.id,
                "aliases": aliases,
                "profile_fact_count": len(card["profile_facts"]),
                "relationship_edge_count": len(card["relationship_edges"]),
                "stable_context_count": len(card["stable_context"]),
                "recent_context_count": len(card["recent_context"]),
                "evidence_count": card["provenance_summary"]["evidence_count"],
            } if card else None
        return {
            "id": action.id, "resolution_id": action.resolution_id,
            "action": action.action_type, "status": "verified",
            "verification_state": "verified", "candidate_ids": action.candidate_ids,
            "derived_candidate_ids": action.derived_candidate_ids,
            "candidates": candidate_rows, "source_entity_id": action.source_entity_id,
            "target_entity_id": action.target_entity_id,
            "primary_entity_id": action.primary_entity_id,
            "confirmation_episode_id": action.confirmation_episode_id,
            "canonical_refs": action.outcome_canonical_refs, "entity": entity_row,
            "context_card": context_card, "error_code": action.error_code,
            "created_at": action.created_at.isoformat(),
            "updated_at": action.updated_at.isoformat(),
        }
