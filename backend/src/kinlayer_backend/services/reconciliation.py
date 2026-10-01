from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.schemas.common import without_legacy_sensitivity
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
    ObservationEvidence,
    ReconciliationAction,
)
from kinlayer_backend.repositories.reconciliation import ReconciliationRepository
from kinlayer_backend.schemas.reconciliation import ReconciliationActionCreate
from kinlayer_backend.schemas.reconciliation import ReconciliationExpectedEntity
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

AI_USE_POLICY_RANK = {
    "freely_use": 0,
    "cautious_use": 1,
    "ask_before_use": 2,
    "never_surface": 3,
}


def effective_context_policy(candidate: Candidate, episode: Episode) -> dict[str, str]:
    policies = ("cautious_use", candidate.payload.get("ai_use_policy", "cautious_use"))
    if any(
        value not in AI_USE_POLICY_RANK for value in policies
    ):
        raise api_error(422, "validation_error", "Prepared evidence policy is invalid.")
    return {
        "effective_ai_use_policy": max(policies, key=AI_USE_POLICY_RANK.__getitem__),
    }


def request_fingerprint(body: ReconciliationActionCreate) -> str:
    return _digest({
        "resolution_id": body.resolution_id,
        "action": body.action,
        "candidate_ids": sorted(body.candidate_ids),
        "expected_candidates": [
            {**item.model_dump(mode="json"), "updated_at": _utc(item.updated_at)}
            for item in sorted(body.expected_candidates, key=lambda item: item.id)
        ],
        "expected_entities": [
            {**item.model_dump(mode="json"), "updated_at": _utc(item.updated_at)}
            for item in sorted(body.expected_entities, key=lambda item: item.id)
        ],
        "source_entity_id": body.source_entity_id,
        "target_entity_id": body.target_entity_id,
        "canonical_name": body.canonical_name,
        "display_name": body.display_name,
        "relationship_to_self": (
            body.relationship_to_self.model_dump(mode="json")
            if body.relationship_to_self else None
        ),
        "resolution_note": body.resolution_note,
        "source": body.source.model_dump(mode="json"),
        "context_claims": [
            claim.model_dump(mode="json", exclude_none=True) for claim in body.context_claims
        ],
    })


def _utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _binding_mac(key: str, value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "hmac-sha256:" + hmac.new(key.encode(), raw.encode(), hashlib.sha256).hexdigest()


class ReconciliationService:
    def __init__(
        self,
        session: Session,
        session_factory: sessionmaker[Session],
        commitment_key: str | None = None,
    ):
        self.session = session
        self.session_factory = session_factory
        self.commitment_key = commitment_key
        self.repository = ReconciliationRepository(session)

    def apply(self, body: ReconciliationActionCreate) -> dict[str, Any]:
        binding = self._verify_answer_binding(body)
        if body.relationship_to_self is not None and any(
            claim.kind == "relationship_edge" for claim in body.context_claims
        ):
            raise api_error(
                422, "validation_error",
                "Relationship context must use exactly one representation.",
            )
        fingerprint = request_fingerprint(body)
        existing = self.repository.get_by_resolution_id(body.resolution_id)
        if existing:
            self._ensure_same_request(existing, fingerprint, binding)
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
            readback_summary={
                "answer_binding": binding,
                "context_manifest": [],
                "context_outcomes": [],
            },
        )
        self.session.add(action)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            existing = self.repository.get_by_resolution_id(body.resolution_id)
            if not existing:
                raise
            self._ensure_same_request(existing, fingerprint, binding)
            return self._verify_in_fresh_session(existing.id)

        try:
            candidates = self.repository.lock_candidates(sorted(body.candidate_ids))
            if len(candidates) != len(body.candidate_ids):
                raise api_error(404, "not_found", "Candidate not found.")
            self._validate_snapshots(candidates, body)
            self._validate_candidate_types(candidates, body.action)
            expected_entity_ids = {item.id for item in body.expected_entities}
            entity_ids = set(expected_entity_ids)
            if body.action == "accept_existing_entity_observation_group":
                entity_ids.update(
                    self._existing_observation_entity_ids(candidates, body)
                )
            entities = self.repository.lock_entities(sorted(entity_ids))
            if len(entities) != len(entity_ids):
                raise api_error(404, "not_found", "Entity not found.")
            self._validate_entity_snapshots(
                [entity for entity in entities if entity.id in expected_entity_ids],
                body,
            )
            if body.action == "accept_existing_entity_observation_group":
                target = next(
                    (entity for entity in entities if entity.id == body.target_entity_id),
                    None,
                )
                if not target:
                    raise api_error(404, "not_found", "Entity not found.")
                self._validate_existing_observation_target(target, candidates, body)
            episode = self._create_confirmation_episode(body)
            action.confirmation_episode_id = episode.id
            self._execute(action, candidates, entities, body)
            self._execute_context(action, candidates, body)
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
    def _ensure_same_request(
        action: ReconciliationAction, fingerprint: str, binding: dict[str, Any]
    ) -> None:
        if (
            action.request_fingerprint != fingerprint
            or (action.readback_summary or {}).get("answer_binding") != binding
        ):
            raise api_error(409, "idempotency_conflict", "resolution_id was reused.")

    def _verify_answer_binding(self, body: ReconciliationActionCreate) -> dict[str, Any]:
        if not self.commitment_key or len(self.commitment_key.encode()) < 32:
            raise api_error(
                503,
                "reconciliation_binding_unavailable",
                "Reconciliation answer binding is unavailable.",
            )
        binding = body.answer_bindings[0].model_dump(mode="json")
        commitment = binding.pop("commitment")
        if (
            binding["action_digest"] != request_fingerprint(body)
            or binding["context_claims_digest"]
            != _digest([
                claim.model_dump(mode="json", exclude_none=True)
                for claim in body.context_claims
            ])
            or not hmac.compare_digest(
                commitment, _binding_mac(self.commitment_key, binding)
            )
        ):
            raise api_error(422, "answer_binding_invalid", "Answer binding is invalid.")
        return {**binding, "commitment": commitment}

    def _verify_stored_answer_binding(
        self, action: ReconciliationAction, binding: Any
    ) -> dict[str, Any]:
        if (
            not self.commitment_key
            or len(self.commitment_key.encode()) < 32
            or not isinstance(binding, dict)
        ):
            raise RuntimeError("answer binding unavailable")
        material = dict(binding)
        commitment = material.pop("commitment", None)
        if (
            material.get("resolution_id") != action.resolution_id
            or material.get("action") != action.action_type
            or material.get("action_digest") != action.request_fingerprint
            or not isinstance(commitment, str)
            or not hmac.compare_digest(
                commitment, _binding_mac(self.commitment_key, material)
            )
        ):
            raise RuntimeError("answer binding readback mismatch")
        return binding

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
            if not ReconciliationService._entity_snapshot_matches(entity, item):
                raise api_error(409, "stale_entity", "Entity snapshot changed.")

    @staticmethod
    def _entity_snapshot_matches(
        entity: Entity, item: ReconciliationExpectedEntity
    ) -> bool:
        actual_time = entity.updated_at
        reviewed_time = item.updated_at
        if actual_time.tzinfo is None:
            actual_time = actual_time.replace(tzinfo=UTC)
        if reviewed_time.tzinfo is None:
            reviewed_time = reviewed_time.replace(tzinfo=UTC)
        return (
            entity.id == item.id
            and entity.status == item.status
            and actual_time.astimezone(UTC) == reviewed_time.astimezone(UTC)
            and entity_digest(entity) == item.entity_digest
        )

    def _create_confirmation_episode(self, body: ReconciliationActionCreate) -> Episode:
        return RelationshipService(self.session).create_episode(
            {
                "source_type": body.source.source_type,
                "source_ref": body.source.source_ref,
                "source_description": "Explicit user reconciliation confirmation",
                "body_excerpt": body.source.body_excerpt,
                "body_hash": body.source.body_hash,
                "actor": body.source.source_actor,
                "retention_policy": "excerpt_only",
            },
            commit=False,
        )

    def _execute_context(
        self,
        action: ReconciliationAction,
        reviewed_candidates: list[Candidate],
        body: ReconciliationActionCreate,
    ) -> None:
        if not body.context_claims:
            return
        primary = self.session.get(Entity, action.primary_entity_id)
        if (
            not primary or primary.entity_type != "person" or primary.status != "active"
            or primary.is_system or primary.system_role == "self"
        ):
            raise api_error(422, "validation_error", "Action has no eligible context target.")
        reviewed_ids = {candidate.id for candidate in reviewed_candidates}
        reviewed_by_id = {candidate.id: candidate for candidate in reviewed_candidates}
        current_episode = self.session.get(Episode, action.confirmation_episode_id)
        protected_self = None
        service = CandidateService(self.session)
        outcomes = []
        manifest = []
        for claim in body.context_claims:
            evidence = claim.evidence
            if evidence.evidence_class == "current_reply":
                excerpt_source = body.source.body_excerpt
                if evidence.end > len(excerpt_source):
                    raise api_error(422, "validation_error", "Evidence span is invalid.")
                excerpt = excerpt_source[evidence.start:evidence.end]
                episode = current_episode
                effective_policy = {
                    "effective_ai_use_policy": "cautious_use",
                }
            else:
                if evidence.candidate_id not in reviewed_ids:
                    raise api_error(422, "validation_error", "Prepared evidence is not candidate-bound.")
                row = self.session.get(CandidateEvidence, evidence.evidence_id)
                episode = self.session.get(Episode, evidence.episode_id)
                if (
                    not row or row.candidate_id != evidence.candidate_id
                    or row.episode_id != evidence.episode_id or not episode
                    or episode.actor != "user" or episode.source_type != "agent_conversation"
                    or episode.body_hash != evidence.body_hash
                    or episode.body_hash != "sha256:" + hashlib.sha256(episode.body_excerpt.encode()).hexdigest()
                    or row.excerpt is None
                    or "sha256:" + hashlib.sha256(row.excerpt.encode()).hexdigest() != evidence.excerpt_hash
                    or row.excerpt not in episode.body_excerpt or evidence.end > len(row.excerpt)
                ):
                    raise api_error(422, "validation_error", "Prepared evidence is invalid.")
                excerpt = row.excerpt[evidence.start:evidence.end]
                effective_policy = effective_context_policy(
                    reviewed_by_id[evidence.candidate_id], episode
                )
            if not excerpt or episode is None:
                raise api_error(422, "validation_error", "Evidence span is empty.")
            if (
                claim.ai_use_policy != effective_policy["effective_ai_use_policy"]
            ):
                raise api_error(422, "validation_error", "Context policy commitment is invalid.")
            if claim.kind == "profile_field":
                payload = {
                    "entity_id": primary.id, "field_path": claim.field_path,
                    "fact_type": claim.fact_type, "content": excerpt, "value": excerpt,
                    "claim_type": claim.claim_type,
                    "ai_use_policy": claim.ai_use_policy,
                }
            elif claim.kind == "relationship_edge":
                protected_self = protected_self or self._single_active_protected_self()
                payload = {
                    "from_entity_id": protected_self.id, "to_entity_id": primary.id,
                    "relation_type": claim.relation_type, "directed": True,
                    "claim_text": excerpt, "claim_type": claim.claim_type, "properties": {},
                    "ai_use_policy": claim.ai_use_policy,
                }
            else:
                payload = {
                    "subject_entity_id": primary.id, "related_entity_ids": [],
                    "observation_type": claim.observation_type, "content": excerpt,
                    "claim_type": claim.claim_type, "ai_use_policy": claim.ai_use_policy,
                }
            candidate = service.create_candidate({
                "candidate_type": claim.kind, "target_entity_id": primary.id,
                "payload": payload,
                "evidence": [{"episode_id": episode.id, "excerpt": excerpt, "confidence": 1.0}],
                "confidence": 1.0,
                "suggested_action": "accept", "created_by": "user",
            }, commit=False)
            service.accept_candidate(candidate, resolution_note=body.resolution_note,
                                     resolved_by="user", commit=False)
            commitment = {
                "claim_id": claim.claim_id, "kind": claim.kind,
                "candidate_id": candidate.id, "canonical_ref": candidate.canonical_record_ref,
                "payload_digest": _digest(candidate.payload), "episode_id": episode.id,
                "excerpt_digest": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
                "source_body_hash": episode.body_hash,
                "ai_use_policy": claim.ai_use_policy,
            }
            manifest.append(commitment)
            outcomes.append({"claim_id": claim.claim_id, "kind": claim.kind,
                             "candidate_id": candidate.id,
                             "canonical_ref": candidate.canonical_record_ref})
            action.derived_candidate_ids = [*action.derived_candidate_ids, candidate.id]
            action.outcome_canonical_refs = [*action.outcome_canonical_refs, candidate.canonical_record_ref]
        action.readback_summary = {
            **(action.readback_summary or {}),
            "context_manifest": manifest,
            "context_outcomes": outcomes,
        }

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
        elif body.action == "accept_existing_entity_observation_group":
            target = next(
                entity for entity in entities if entity.id == body.target_entity_id
            )
            for candidate in candidates:
                service.accept_candidate(
                    candidate,
                    resolution_note=body.resolution_note,
                    resolved_by="user",
                    commit=False,
                )
            action.target_entity_id = target.id
            action.primary_entity_id = target.id
            action.outcome_canonical_refs = [
                candidate.canonical_record_ref for candidate in candidates
            ]
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
            retained.target_entity_id = entity_id
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
            if body.relationship_to_self is not None:
                relationship = body.relationship_to_self
                protected_self = self._single_active_protected_self()
                action.source_entity_id = protected_self.id
                edge_candidate = service.create_candidate(
                    {
                        "candidate_type": "relationship_edge",
                        "payload": {
                            "from_entity_id": protected_self.id,
                            "to_entity_id": entity_id,
                            "relation_type": relationship.relation_type,
                            "claim_text": relationship.claim_text,
                            "claim_type": "fact",
                            "properties": {},
                        },
                        "evidence": [
                            {
                                "episode_id": action.confirmation_episode_id,
                                "excerpt": relationship.claim_text,
                                "confidence": 1.0,
                            }
                        ],
                        "confidence": 1.0,
                        "suggested_action": "review",
                        "created_by": "user",
                    },
                    commit=False,
                )
                service.accept_candidate(
                    edge_candidate,
                    resolution_note=body.resolution_note,
                    resolved_by="user",
                    commit=False,
                )
                action.derived_candidate_ids = [
                    *action.derived_candidate_ids,
                    edge_candidate.id,
                ]
                action.outcome_canonical_refs = [
                    *action.outcome_canonical_refs,
                    edge_candidate.canonical_record_ref,
                ]

    def _single_active_protected_self(self) -> Entity:
        protected = list(
            self.session.scalars(
                select(Entity).where(
                    Entity.system_role == "self",
                    Entity.is_system.is_(True),
                    Entity.status == "active",
                )
            ).all()
        )
        if len(protected) != 1 or protected[0].entity_type != "person":
            raise api_error(
                409,
                "protected_self_unavailable",
                "Exactly one active protected self person is required.",
            )
        return protected[0]

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

    @staticmethod
    def _existing_observation_entity_ids(
        candidates: list[Candidate], body: ReconciliationActionCreate
    ) -> set[str]:
        entity_ids = {body.target_entity_id or ""}
        for candidate in candidates:
            subject_entity_id = candidate.payload.get("subject_entity_id")
            related_entity_ids = candidate.payload.get("related_entity_ids", [])
            if (
                not isinstance(subject_entity_id, str)
                or not subject_entity_id
                or not isinstance(related_entity_ids, list)
                or any(not isinstance(entity_id, str) or not entity_id for entity_id in related_entity_ids)
            ):
                raise api_error(
                    422,
                    "validation_error",
                    "Observation entity references must be nonempty IDs.",
                )
            entity_ids.add(subject_entity_id)
            entity_ids.update(related_entity_ids)
        return entity_ids

    @staticmethod
    def _validate_existing_observation_target(
        target: Entity,
        candidates: list[Candidate],
        body: ReconciliationActionCreate,
    ) -> None:
        if target.status != "active":
            raise api_error(409, "conflict", "Target entity is not active.")
        if target.entity_type != "person":
            raise api_error(422, "validation_error", "Target must be an active person.")
        if target.system_role == "self" or target.is_system:
            raise api_error(403, "protected_self", "Protected/system targets are not allowed.")
        if any(
            candidate.candidate_type != "observation"
            or candidate.status != "pending"
            or candidate.target_entity_id != body.target_entity_id
            or candidate.payload.get("subject_entity_id") != body.target_entity_id
            or candidate.canonical_record_ref is not None
            or candidate.supersedes_candidate_id is not None
            for candidate in candidates
        ):
            raise api_error(
                422,
                "validation_error",
                "Observation candidates must have the exact common target entity.",
            )

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
                stored = action.readback_summary or {}
                stored_binding = self._verify_stored_answer_binding(
                    action, stored.get("answer_binding")
                )
                stored_context = stored.get("context_manifest", [])
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
                if action.action_type == "accept_existing_entity_observation_group":
                    canonical_refs = []
                    expected_candidates = {
                        item["id"]: item for item in action.expected_candidates
                    }
                    for candidate in candidates:
                        ref = candidate.canonical_record_ref or ""
                        prefix, separator, observation_id = ref.partition(":")
                        observation = (
                            fresh.get(Observation, observation_id)
                            if separator and prefix == "observations" else None
                        )
                        candidate_evidence_ids = sorted(fresh.scalars(
                            select(CandidateEvidence.episode_id).where(
                                CandidateEvidence.candidate_id == candidate.id
                            )
                        ).all())
                        observation_evidence_ids = sorted(fresh.scalars(
                            select(ObservationEvidence.episode_id).where(
                                ObservationEvidence.observation_id == observation_id
                            )
                        ).all())
                        expected_candidate = expected_candidates.get(candidate.id)
                        if (
                            candidate.status != "accepted"
                            or candidate.resolved_by != "user"
                            or candidate.target_entity_id != action.target_entity_id
                            or not expected_candidate
                            or candidate_payload_digest(candidate)
                            != expected_candidate["payload_digest"]
                            or candidate_evidence_digest(fresh, candidate.id)
                            != expected_candidate["evidence_digest"]
                            or not observation
                            or observation.status != "active"
                            or observation.source_candidate_id != candidate.id
                            or observation.subject_entity_id != action.target_entity_id
                            or candidate_evidence_ids != observation_evidence_ids
                        ):
                            raise RuntimeError("observation group readback mismatch")
                        canonical_refs.append(ref)
                    expected_target = (
                        ReconciliationExpectedEntity.model_validate(action.expected_entities[0])
                        if len(action.expected_entities) == 1 else None
                    )
                    if (
                        not entity or entity.entity_type != "person"
                        or entity.system_role == "self" or entity.is_system
                        or action.primary_entity_id != action.target_entity_id
                        or not expected_target
                        or expected_target.id != action.target_entity_id
                        or not self._entity_snapshot_matches(entity, expected_target)
                        or len(canonical_refs) != len(set(canonical_refs))
                        or canonical_refs != action.outcome_canonical_refs
                    ):
                        raise RuntimeError("observation group target readback mismatch")
                if action.action_type in {
                    "confirm_new_entity_group", "rename_and_accept_new_entity"
                }:
                    retained_status = (
                        "edited_accepted"
                        if action.action_type == "rename_and_accept_new_entity"
                        else "accepted"
                    )
                    retained = candidates[0] if candidates else None
                    canonical_ref = f"entities:{action.primary_entity_id}"
                    if (
                        not entity
                        or entity.entity_type != "person"
                        or entity.status != "active"
                        or [item.status for item in candidates]
                        != [retained_status, *(["superseded"] * (len(candidates) - 1))]
                        or retained.supersedes_candidate_id is not None
                        or any(
                            item.target_entity_id != action.primary_entity_id
                            or item.canonical_record_ref != canonical_ref
                            for item in candidates
                        )
                        or any(
                            item.supersedes_candidate_id != retained.id
                            for item in candidates[1:]
                        )
                    ):
                        raise RuntimeError("group readback mismatch")
                if action.action_type == "rename_and_accept_new_entity":
                    self._verify_relationship_to_self(fresh, action, entity)
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
                self._verify_context_manifest(fresh, action, stored_context)
                action.error_code = None
                summary = self._readback(action, candidates, entity, fresh)
                summary["context_outcomes"] = [
                    {key: item[key] for key in ("claim_id", "kind", "candidate_id", "canonical_ref")}
                    for item in stored_context
                ]
                action.readback_summary = {
                    "answer_binding": stored_binding,
                    "context_manifest": stored_context,
                    "result": summary,
                }
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
    def _verify_context_manifest(
        fresh: Session, action: ReconciliationAction, manifest: list[dict[str, Any]]
    ) -> None:
        context_ids = [item.get("candidate_id") for item in manifest]
        if len(context_ids) != len(set(context_ids)) or any(not item for item in context_ids):
            raise RuntimeError("context manifest invalid")
        if not set(context_ids) <= set(action.derived_candidate_ids):
            raise RuntimeError("context candidate set mismatch")
        for item in manifest:
            candidate = fresh.get(Candidate, item["candidate_id"])
            if (
                not candidate or candidate.status != "accepted" or candidate.resolved_by != "user"
                or candidate.target_entity_id != action.primary_entity_id
                or candidate.candidate_type != item["kind"]
                or candidate.canonical_record_ref != item["canonical_ref"]
                or _digest(candidate.payload) != item["payload_digest"]
                or item["canonical_ref"] not in action.outcome_canonical_refs
            ):
                raise RuntimeError("context candidate readback mismatch")
            evidence = list(fresh.scalars(select(CandidateEvidence).where(
                CandidateEvidence.candidate_id == candidate.id
            )).all())
            episode = fresh.get(Episode, item["episode_id"])
            if (
                len(evidence) != 1 or evidence[0].episode_id != item["episode_id"]
                or not episode or episode.actor != "user" or episode.source_type != "agent_conversation"
                or episode.body_hash != item["source_body_hash"]
                or "sha256:" + hashlib.sha256(episode.body_excerpt.encode()).hexdigest() != episode.body_hash
                or "sha256:" + hashlib.sha256((evidence[0].excerpt or "").encode()).hexdigest()
                != item["excerpt_digest"]
                or evidence[0].excerpt not in episode.body_excerpt
            ):
                raise RuntimeError("context evidence readback mismatch")
            table, _, record_id = (candidate.canonical_record_ref or "").partition(":")
            models = {"entity_facts": EntityFact, "entity_edges": EntityEdge,
                      "observations": Observation}
            model = models.get(table)
            record = fresh.get(model, record_id) if model else None
            if not record or record.source_candidate_id != candidate.id:
                raise RuntimeError("context canonical readback mismatch")
            payload = candidate.payload
            if item["kind"] == "profile_field" and not (
                record.status == "active" and record.entity_id == action.primary_entity_id
                and record.fact_type == payload.get("fact_type")
                and record.content == payload.get("content")
                and record.value == {
                    "field_path": payload.get("field_path"),
                    "value": payload.get("value"),
                }
                and record.claim_type == payload.get("claim_type")
                and record.ai_use_policy == payload.get("ai_use_policy")
            ):
                raise RuntimeError("context profile readback mismatch")
            if item["kind"] == "relationship_edge" and not (
                record.status == "active" and record.to_entity_id == action.primary_entity_id
                and record.from_entity_id == payload.get("from_entity_id")
                and record.to_entity_id == payload.get("to_entity_id")
                and record.relation_type == payload.get("relation_type")
                and record.directed == payload.get("directed")
                and record.claim_text == payload.get("claim_text")
                and record.claim_type == payload.get("claim_type")
                and record.ai_use_policy == payload.get("ai_use_policy")
                and (record.properties or {}) == (payload.get("properties") or {})
            ):
                raise RuntimeError("context relationship readback mismatch")
            if item["kind"] == "observation":
                related_ids = sorted(fresh.scalars(select(ObservationEntity.entity_id).where(
                    ObservationEntity.observation_id == record.id
                )).all())
                observation_evidence = sorted(fresh.scalars(select(ObservationEvidence.episode_id).where(
                    ObservationEvidence.observation_id == record.id
                )).all())
                if not (
                    record.status == "active"
                    and record.subject_entity_id == action.primary_entity_id
                    and without_legacy_sensitivity(payload) == {
                        "subject_entity_id": record.subject_entity_id,
                        "related_entity_ids": related_ids,
                        "observation_type": record.observation_type,
                        "content": record.content, "claim_type": record.claim_type,
                        "ai_use_policy": record.ai_use_policy,
                    }
                    and observation_evidence == [item["episode_id"]]
                ):
                    raise RuntimeError("context observation readback mismatch")

    @staticmethod
    def _verify_relationship_to_self(
        session: Session,
        action: ReconciliationAction,
        primary: Entity | None,
    ) -> None:
        derived = list(
            session.scalars(
                select(Candidate).where(Candidate.id.in_(action.derived_candidate_ids))
            ).all()
        )
        edges = [item for item in derived if item.candidate_type == "relationship_edge"]
        if not action.source_entity_id:
            context_edge_ids = {
                item.get("candidate_id")
                for item in (action.readback_summary or {}).get("context_manifest", [])
                if item.get("kind") == "relationship_edge"
            }
            if {item.id for item in edges} != context_edge_ids:
                raise RuntimeError("unexpected derived relationship candidate")
            return
        if len(edges) != 1 or not primary:
            raise RuntimeError("derived relationship candidate readback mismatch")
        candidate = edges[0]
        evidence_ids = list(
            session.scalars(
                select(CandidateEvidence.episode_id)
                .where(CandidateEvidence.candidate_id == candidate.id)
                .order_by(CandidateEvidence.episode_id)
            ).all()
        )
        edge = session.scalar(
            select(EntityEdge).where(EntityEdge.source_candidate_id == candidate.id)
        )
        payload = candidate.payload
        canonical_ref = f"entity_edges:{edge.id}" if edge else None
        if (
            candidate.status != "accepted"
            or candidate.resolved_by != "user"
            or evidence_ids != [action.confirmation_episode_id]
            or not edge
            or edge.from_entity_id != payload.get("from_entity_id")
            or edge.from_entity_id != action.source_entity_id
            or edge.to_entity_id != primary.id
            or edge.to_entity_id != payload.get("to_entity_id")
            or edge.relation_type != payload.get("relation_type")
            or edge.claim_text != payload.get("claim_text")
            or edge.claim_type != "fact"
            or edge.source_candidate_id != candidate.id
            or candidate.canonical_record_ref != canonical_ref
            or canonical_ref not in action.outcome_canonical_refs
        ):
            raise RuntimeError("derived relationship linkage readback mismatch")

    @staticmethod
    def _readback(
        action: ReconciliationAction,
        candidates: list[Candidate],
        entity: Entity | None,
        session: Session,
    ) -> dict[str, Any]:
        def entity_row(value: Entity | None) -> dict[str, Any] | None:
            if value is None:
                return None
            return {
                "id": value.id,
                "entity_type": value.entity_type,
                "display_name": value.display_name,
                "canonical_name": value.canonical_name,
                "status": value.status,
                "system_role": value.system_role,
                "updated_at": value.updated_at.isoformat(),
                "entity_digest": entity_digest(value),
            }

        candidate_rows = []
        for candidate in candidates:
            evidence_ids = list(session.scalars(
                select(CandidateEvidence.episode_id)
                .where(CandidateEvidence.candidate_id == candidate.id)
                .order_by(CandidateEvidence.episode_id)
            ).all())
            candidate_rows.append({
                "id": candidate.id,
                "candidate_type": candidate.candidate_type,
                "status": candidate.status,
                "updated_at": candidate.updated_at.isoformat(),
                "canonical_record_ref": candidate.canonical_record_ref,
                "target_entity_id": candidate.target_entity_id,
                "payload_digest": candidate_payload_digest(candidate),
                "evidence_digest": candidate_evidence_digest(session, candidate.id),
                "evidence_episode_ids": evidence_ids,
            })
        derived_candidate_rows = []
        for candidate_id in action.derived_candidate_ids:
            candidate = session.get(Candidate, candidate_id)
            if not candidate:
                continue
            evidence_ids = list(session.scalars(
                select(CandidateEvidence.episode_id)
                .where(CandidateEvidence.candidate_id == candidate.id)
                .order_by(CandidateEvidence.episode_id)
            ).all())
            derived_candidate_rows.append({
                "id": candidate.id,
                "candidate_type": candidate.candidate_type,
                "status": candidate.status,
                "canonical_record_ref": candidate.canonical_record_ref,
                "evidence_episode_ids": evidence_ids,
            })
        entity_result = None
        context_card = None
        if entity:
            card = ContextService(session).context_card(entity.id) if entity.status == "active" else None
            aliases = [item.alias for item in card["aliases"]] if card else []
            entity_result = entity_row(entity)
            context_card = {
                "entity_id": entity.id,
                "aliases": aliases,
                "profile_fact_count": len(card["profile_facts"]),
                "relationship_edge_count": len(card["relationship_edges"]),
                "stable_context_count": len(card["stable_context"]),
                "recent_context_count": len(card["recent_context"]),
                "evidence_count": card["provenance_summary"]["evidence_count"],
            } if card else None
        source_entity = None
        if action.action_type in {"merge_existing_entities", "archive_existing_entity"}:
            source_entity = entity_row(session.get(Entity, action.source_entity_id))
        return {
            "id": action.id, "resolution_id": action.resolution_id,
            "action": action.action_type, "status": "verified",
            "verification_state": "verified", "candidate_ids": action.candidate_ids,
            "derived_candidate_ids": action.derived_candidate_ids,
            "derived_candidates": derived_candidate_rows,
            "candidates": candidate_rows, "source_entity_id": action.source_entity_id,
            "target_entity_id": action.target_entity_id,
            "primary_entity_id": action.primary_entity_id,
            "confirmation_episode_id": action.confirmation_episode_id,
            "canonical_refs": action.outcome_canonical_refs, "entity": entity_result,
            "source_entity": source_entity,
            "context_card": context_card, "error_code": action.error_code,
            "answer_binding": (action.readback_summary or {}).get("answer_binding"),
            "created_at": action.created_at.isoformat(),
            "updated_at": action.updated_at.isoformat(),
        }
