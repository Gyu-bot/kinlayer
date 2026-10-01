import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.services.relationship_ontology import EDGE_DEFINITIONS
from kinlayer_backend.config import Settings
from kinlayer_backend.models import (
    AllowedEdgeType,
    AllowedObservationType,
    Candidate,
    CandidateEvidence,
    EdgeEvidence,
    EnrichmentAnswerAction,
    EnrichmentAuthorization,
    Entity,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Episode,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.repositories.enrichment import EnrichmentRepository
from kinlayer_backend.schemas.enrichment import EnrichmentAnswerCreate, EnrichmentAuthorizationCreate
from kinlayer_backend.services.candidate_snapshots import entity_digest
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.ontology import is_allowed_registry_value, normalize_name
from kinlayer_backend.services.relationships import RelationshipService

ENRICHMENT_SOURCE_DESCRIPTION = "Explicit user conversational enrichment reply"
ENRICHMENT_RETENTION_POLICY = "excerpt_only"
ENRICHMENT_SOURCE_CAPABILITY_VERSION = "ekc1"


def _fingerprint(model: Any) -> str:
    raw = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class EnrichmentService:
    def __init__(
        self,
        session: Session,
        session_factory: sessionmaker[Session],
        settings: Settings | str,
    ):
        self.session = session
        self.session_factory = session_factory
        if isinstance(settings, Settings):
            self.settings = settings
        else:
            self.settings = Settings(
                reconciliation_token=settings,
            )
        self.repository = EnrichmentRepository(session)

    def stage(self, body: EnrichmentAuthorizationCreate) -> dict[str, Any]:
        fingerprint = _fingerprint(body)
        existing = self.repository.authorization_by_stage_key(body.stage_idempotency_key)
        if existing:
            if existing.stage_fingerprint != fingerprint:
                raise api_error(
                    409, "idempotency_conflict", "Stage key was used with a different request."
                )
            self._require_unambiguous_subject(
                self.session.get(Entity, existing.subject_entity_id)
            )
            return self._read_authorization(existing)
        now = datetime.now(UTC)
        if body.expires_at <= now:
            raise api_error(422, "validation_error", "expires_at must be in the future.")
        subject = self.session.get(Entity, body.subject_entity_id)
        self._validate_subject(subject)
        self._require_unambiguous_subject(subject)
        compiled_slots = [self._compile_slot(subject, slot.model_dump(mode="json")) for slot in body.slots]
        self._validate_stored_ontology(compiled_slots)
        self._validate_slot_semantics(compiled_slots, subject.id)
        entity_ids = sorted(
            {subject.id} | {entity_id for slot in compiled_slots for entity_id in slot["related_entity_ids"]}
        )
        entities = list(
            self.session.scalars(
                select(Entity).where(Entity.id.in_(entity_ids)).order_by(Entity.id)
            )
        )
        snapshots = [self._snapshot(entity) for entity in entities]
        self._require_gaps(subject, compiled_slots)
        authorization = EnrichmentAuthorization(
            authorization_ref="enrich:" + uuid.uuid4().hex,
            stage_idempotency_key=body.stage_idempotency_key,
            stage_fingerprint=fingerprint,
            topic=body.topic,
            subject_entity_id=subject.id,
            entity_snapshots=snapshots,
            slots=compiled_slots,
            slot_states={slot["slot_id"]: "open" for slot in compiled_slots},
            status="open",
            expires_at=body.expires_at,
        )
        self.session.add(authorization)
        try:
            self.session.commit()
            self.session.refresh(authorization)
            return self._read_authorization(authorization)
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.repository.authorization_by_stage_key(body.stage_idempotency_key)
            if existing and existing.stage_fingerprint == fingerprint:
                return self._read_authorization(existing)
            raise api_error(409, "idempotency_conflict", "Stage key conflicts.") from exc

    def answer(self, body: EnrichmentAnswerCreate, answer_capability: str) -> dict[str, Any]:
        fingerprint = _fingerprint(body)
        authorization = self.repository.lock_authorization(body.authorization_id)
        self._require_answer_capability(authorization, answer_capability)
        existing = self.repository.action_by_resolution(body.resolution_id)
        if existing:
            if (
                existing.authorization_id == authorization.id
                and existing.request_fingerprint == fingerprint
            ):
                return self._verify_fresh(existing.id)
            raise api_error(
                409,
                "idempotency_conflict",
                "Resolution ID was used with a different request.",
            )
        try:
            now = datetime.now(UTC)
            self._require_unambiguous_subject(
                self.session.get(Entity, authorization.subject_entity_id)
            )
            if _aware(authorization.expires_at) <= now:
                authorization.status = "expired"
                self.session.commit()
                raise api_error(409, "authorization_expired", "Authorization has expired.")
            self._validate_live_authorization(authorization)
            if authorization.status not in {"open", "partially_answered"}:
                raise api_error(409, "conflict", "Authorization is not open.")
            slot_map = {slot["slot_id"]: slot for slot in authorization.slots}
            for answer in body.answers:
                if answer.slot_id not in slot_map:
                    raise api_error(
                        409, "slot_not_authorized", "Answer references an unauthorized slot."
                    )
                if authorization.slot_states.get(answer.slot_id) != "open":
                    raise api_error(409, "slot_already_answered", "Slot is no longer open.")
            entities = self.repository.lock_entities(
                sorted(
                    {slot["subject_entity_id"] for slot in authorization.slots}
                    | {
                        entity_id
                        for slot in authorization.slots
                        for entity_id in slot["related_entity_ids"]
                    }
                )
            )
            if len(entities) != len(authorization.entity_snapshots):
                raise api_error(409, "stale_entity", "Authorized entity set changed.")
            for entity, snapshot in zip(
                entities, sorted(authorization.entity_snapshots, key=lambda item: item["id"])
            ):
                if self._snapshot(entity) != snapshot:
                    raise api_error(409, "stale_entity", "Authorized entity snapshot is stale.")
                self._validate_subject(entity)
            submitted_slots = [slot_map[answer.slot_id] for answer in body.answers]
            self._validate_stored_ontology(authorization.slots)
            self._validate_slot_semantics(authorization.slots, authorization.subject_entity_id)
            self._require_gaps(
                self.session.get(Entity, authorization.subject_entity_id),
                submitted_slots,
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                existing = self.repository.action_by_resolution(body.resolution_id)
                if (
                    existing
                    and existing.authorization_id == authorization.id
                    and existing.request_fingerprint == fingerprint
                ):
                    return self._verify_fresh(existing.id)
            raise
        action = EnrichmentAnswerAction(
            resolution_id=body.resolution_id,
            authorization_id=authorization.id,
            request_fingerprint=fingerprint,
            status="pending",
            slot_outcomes=[],
            derived_candidate_ids=[],
            canonical_refs=[],
        )
        self.session.add(action)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            existing = self.repository.action_by_resolution(body.resolution_id)
            if (
                existing
                and existing.authorization_id == body.authorization_id
                and existing.request_fingerprint == fingerprint
            ):
                return self._verify_fresh(existing.id)
            raise api_error(409, "idempotency_conflict", "Resolution ID conflicts.") from exc
        known_answers = [answer for answer in body.answers if answer.state == "known"]
        episode = self._create_episode(body) if known_answers else None
        action.source_snapshot = (
            self._source_snapshot(body, known_answers, episode) if known_answers else None
        )
        outcomes: list[dict[str, Any]] = []
        new_states = dict(authorization.slot_states)
        known_candidates: list[Candidate] = []
        for answer in body.answers:
            slot = slot_map[answer.slot_id]
            outcome = {
                "slot_id": answer.slot_id,
                "state": answer.state,
                "candidate_id": None,
                "canonical_ref": None,
            }
            if answer.state == "known":
                assert episode is not None
                payload = self._candidate_payload(slot, answer, episode.id)
                candidate = CandidateService(self.session).create_candidate(payload, commit=False)
                candidate = CandidateService(self.session).accept_candidate(
                    candidate, resolved_by="user", commit=False
                )
                outcome.update(
                    candidate_id=candidate.id,
                    canonical_ref=candidate.canonical_record_ref,
                    candidate_payload_digest=_digest(candidate.payload),
                    evidence_digest=_digest(answer.evidence_excerpt),
                )
                known_candidates.append(candidate)
                new_states[answer.slot_id] = "known"
            elif answer.state == "unknown":
                new_states[answer.slot_id] = "unknown"
            outcomes.append(outcome)
        terminal = all(state != "open" for state in new_states.values())
        authorization.slot_states = new_states
        authorization.status = "completed" if terminal else "partially_answered"
        authorization.completed_at = now if terminal else None
        action.slot_outcomes = outcomes
        action.derived_candidate_ids = [candidate.id for candidate in known_candidates]
        action.canonical_refs = [candidate.canonical_record_ref for candidate in known_candidates]
        action.episode_id = episode.id if episode else None
        action.status = "committed_unverified"
        action.committed_at = now
        self.session.commit()
        return self._verify_fresh(action.id)

    def get(self, action_id: str, answer_capability: str) -> dict[str, Any]:
        action = self.repository.action_by_id(action_id)
        if not action:
            raise api_error(404, "not_found", "Enrichment resource not found.")
        authorization = self.session.get(EnrichmentAuthorization, action.authorization_id)
        self._require_answer_capability(authorization, answer_capability)
        return self._verify_fresh(action.id)

    def _verify_fresh(self, action_id: str) -> dict[str, Any]:
        with self.session_factory() as fresh:
            action = fresh.get(EnrichmentAnswerAction, action_id)
            if not action:
                raise api_error(
                    503, "readback_unavailable", "Committed enrichment could not be verified."
                )
            try:
                authorization = fresh.get(EnrichmentAuthorization, action.authorization_id)
                if not authorization:
                    raise ValueError
                self._validate_live_authorization(authorization)
                slots = {slot["slot_id"]: slot for slot in authorization.slots}
                known_outcomes = [outcome for outcome in action.slot_outcomes if outcome["state"] == "known"]
                unknown_outcomes = [outcome for outcome in action.slot_outcomes if outcome["state"] == "unknown"]
                skip_outcomes = [outcome for outcome in action.slot_outcomes if outcome["state"] == "skip"]
                outcome_ids = [outcome["slot_id"] for outcome in action.slot_outcomes]
                if outcome_ids != sorted(outcome_ids) or len(outcome_ids) != len(set(outcome_ids)):
                    raise ValueError
                if not set(outcome_ids) <= set(slots):
                    raise ValueError
                if action.derived_candidate_ids != [
                    outcome["candidate_id"] for outcome in known_outcomes
                ]:
                    raise ValueError
                if action.canonical_refs != [
                    outcome["canonical_ref"] for outcome in known_outcomes
                ]:
                    raise ValueError
                episode = None
                if known_outcomes:
                    episode = fresh.get(Episode, action.episode_id)
                    if not episode:
                        raise ValueError
                    self._verify_episode(action, episode, known_outcomes)
                elif action.episode_id is not None or action.source_snapshot is not None:
                    raise ValueError
                for outcome in known_outcomes:
                    slot = slots[outcome["slot_id"]]
                    if authorization.slot_states[outcome["slot_id"]] != "known":
                        raise ValueError
                    candidate = fresh.get(Candidate, outcome["candidate_id"])
                    if not candidate:
                        raise ValueError
                    self._verify_candidate(fresh, outcome, slot, candidate, episode)
                for outcome in unknown_outcomes:
                    if authorization.slot_states[outcome["slot_id"]] != "unknown":
                        raise ValueError
                    if outcome["candidate_id"] or outcome["canonical_ref"]:
                        raise ValueError
                for outcome in skip_outcomes:
                    if authorization.slot_states[outcome["slot_id"]] != "open":
                        raise ValueError
                    if outcome["candidate_id"] or outcome["canonical_ref"]:
                        raise ValueError
                if len(known_outcomes) + len(unknown_outcomes) + len(skip_outcomes) != len(
                    action.slot_outcomes
                ):
                    raise ValueError
                if action.status != "verified" or action.error_code is not None:
                    action.status = "verified"
                    action.verified_at = action.verified_at or datetime.now(UTC)
                    action.error_code = None
                    fresh.commit()
                return self._read_action(action)
            except (AttributeError, HTTPException, KeyError, TypeError, ValueError):
                action = fresh.get(EnrichmentAnswerAction, action_id)
                if action:
                    action.status = "committed_unverified"
                    action.error_code = "readback_unavailable"
                    fresh.commit()
                raise api_error(
                    503, "readback_unavailable", "Committed enrichment could not be verified."
                )

    def _read_authorization(self, authorization: EnrichmentAuthorization) -> dict[str, Any]:
        return {
            "id": authorization.id,
            "authorization_ref": authorization.authorization_ref,
            "subject_entity_id": authorization.subject_entity_id,
            "topic": authorization.topic,
            "status": authorization.status,
            "entity_snapshots": authorization.entity_snapshots,
            "slots": authorization.slots,
            "slot_states": authorization.slot_states,
            "expires_at": authorization.expires_at,
            "created_at": authorization.created_at,
            "updated_at": authorization.updated_at,
            "answer_capability": self._answer_capability(authorization),
        }

    @staticmethod
    def _read_action(action: EnrichmentAnswerAction) -> dict[str, Any]:
        return {
            "id": action.id,
            "resolution_id": action.resolution_id,
            "authorization_id": action.authorization_id,
            "status": action.status,
            "verification_state": action.status,
            "slot_outcomes": action.slot_outcomes,
            "derived_candidate_ids": action.derived_candidate_ids,
            "episode_id": action.episode_id,
            "canonical_refs": action.canonical_refs,
            "error_code": action.error_code,
            "created_at": action.created_at,
            "updated_at": action.updated_at,
        }

    def _require_answer_capability(
        self,
        authorization: EnrichmentAuthorization | None,
        answer_capability: str,
    ) -> None:
        if not authorization:
            raise api_error(404, "not_found", "Enrichment resource not found.")
        expected = self._answer_capability(authorization)
        if not hmac.compare_digest(answer_capability, expected):
            raise api_error(404, "not_found", "Enrichment resource not found.")

    def _answer_capability(self, authorization: EnrichmentAuthorization) -> str:
        secret = self.settings.reconciliation_token
        if not secret:
            raise api_error(503, "readback_unavailable", "Enrichment capability secret is unavailable.")
        message = (
            f"enrichment-answer-capability:v1:{authorization.id}:{authorization.stage_fingerprint}"
        ).encode()
        digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
        return f"{ENRICHMENT_SOURCE_CAPABILITY_VERSION}_{digest}"

    def _validate_live_authorization(self, authorization: EnrichmentAuthorization) -> None:
        self._validate_stored_ontology(authorization.slots)
        self._validate_slot_semantics(authorization.slots, authorization.subject_entity_id)
        slot_ids = [slot["slot_id"] for slot in authorization.slots]
        if len(slot_ids) != len(set(slot_ids)) or set(slot_ids) != set(authorization.slot_states):
            raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
        for slot in authorization.slots:
            if slot["subject_entity_id"] != authorization.subject_entity_id:
                raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
            if authorization.slot_states[slot["slot_id"]] not in {"open", "unknown", "known"}:
                raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")

    def _validate_slot_semantics(self, slots: list[dict[str, Any]], subject_entity_id: str) -> None:
        profile_semantics: set[tuple[str, str, str]] = set()
        edge_semantics: set[tuple[str, str]] = set()
        observation_semantics: dict[tuple[str, tuple[str, ...]], set[str]] = {}
        for slot in slots:
            slot_id = slot["slot_id"]
            related_entity_ids = sorted(slot.get("related_entity_ids", []))
            if sorted(slot.get("related_entity_ids", [])) != slot.get("related_entity_ids", []):
                raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
            if slot["subject_entity_id"] != subject_entity_id:
                raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
            if slot["kind"] == "profile_field":
                semantic = (slot["subject_entity_id"], slot["fact_type"], slot["field_path"])
                if semantic in profile_semantics:
                    raise api_error(
                        409,
                        "duplicate_semantic_slot",
                        f"Profile slot '{slot_id}' overlaps an existing slot.",
                    )
                profile_semantics.add(semantic)
                continue
            if slot["kind"] == "relationship_edge":
                allowed_relation_types = slot["allowed_relation_types"]
                if allowed_relation_types != sorted(set(allowed_relation_types)):
                    raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
                semantic = (slot["from_entity_id"], slot["to_entity_id"])
                if semantic in edge_semantics:
                    raise api_error(
                        409,
                        "duplicate_semantic_slot",
                        f"Relationship slot '{slot_id}' overlaps an existing slot.",
                    )
                edge_semantics.add(semantic)
                continue
            allowed_observation_types = slot["allowed_observation_types"]
            if allowed_observation_types != sorted(set(allowed_observation_types)):
                raise api_error(409, "authorization_invalid", "Stored authorization is invalid.")
            semantic = (slot["subject_entity_id"], tuple(related_entity_ids))
            existing_types = observation_semantics.setdefault(semantic, set())
            overlap = existing_types & set(allowed_observation_types)
            if overlap:
                raise api_error(
                    409,
                    "duplicate_semantic_slot",
                    f"Observation slot '{slot_id}' overlaps an existing slot.",
                )
            existing_types.update(allowed_observation_types)

    @staticmethod
    def _validate_subject(subject: Entity | None) -> None:
        if (
            not subject
            or subject.entity_type != "person"
            or subject.status != "active"
        ):
            raise api_error(422, "validation_error", "Subject must be an active person.")

    def _require_unambiguous_subject(self, subject: Entity | None) -> None:
        self._validate_subject(subject)
        assert subject is not None
        if subject.system_role == "self":
            return
        subject_identifiers = self._normalized_identifiers(subject)
        if not subject_identifiers:
            return
        others = self.session.scalars(
            select(Entity).where(
                Entity.id != subject.id,
                Entity.entity_type == "person",
                Entity.status == "active",
            )
        )
        if any(subject_identifiers & self._normalized_identifiers(other) for other in others):
            raise api_error(
                409,
                "subject_ambiguous",
                "Subject identity overlaps another active person.",
            )

    @staticmethod
    def _normalized_identifiers(entity: Entity) -> set[str]:
        raw_identifiers = [entity.display_name, entity.canonical_name]
        raw_identifiers.extend(
            alias.alias for alias in entity.aliases if alias.status == "active"
        )
        return {
            normalized
            for value in raw_identifiers
            if value and (normalized := normalize_name(value))
        }

    @staticmethod
    def _validate_related_subject(subject: Entity | None) -> None:
        if (
            not subject
            or subject.system_role == "self"
            or subject.entity_type != "person"
            or subject.status != "active"
        ):
            raise api_error(
                422,
                "validation_error",
                "Related subject must be an active non-self person.",
            )

    def _compile_slot(self, subject: Entity, slot: dict[str, Any]) -> dict[str, Any]:
        compiled = dict(slot)
        compiled["subject_entity_id"] = subject.id
        if compiled["kind"] == "relationship_edge":
            if subject.system_role == "self":
                raise api_error(
                    422, "validation_error", "Protected self cannot be the relationship subject."
                )
            self_entity = self.session.scalar(
                select(Entity).where(Entity.system_role == "self", Entity.status == "active")
            )
            if not self_entity:
                raise api_error(409, "conflict", "Protected self is unavailable.")
            if compiled.pop("direction") == "self_to_subject":
                compiled["from_entity_id"], compiled["to_entity_id"] = self_entity.id, subject.id
            else:
                compiled["from_entity_id"], compiled["to_entity_id"] = subject.id, self_entity.id
            compiled["related_entity_ids"] = [self_entity.id]
            compiled["properties"] = {}
            return compiled
        if compiled["kind"] == "observation":
            related_entity_id = compiled.pop("related_entity_id", None)
            compiled["related_entity_ids"] = []
            if related_entity_id is not None:
                if subject.system_role != "self":
                    raise api_error(
                        422,
                        "validation_error",
                        "Only protected self observations can bind a related subject.",
                    )
                related = self.session.get(Entity, related_entity_id)
                self._validate_related_subject(related)
                compiled["related_entity_ids"] = [related.id]
            return compiled
        compiled["related_entity_ids"] = []
        return compiled

    def _validate_stored_ontology(self, slots: list[dict[str, Any]]) -> None:
        for slot in slots:
            if not all(
                is_allowed_registry_value(self.session, category, slot[key])
                for category, key in (
                    ("claim_type", "claim_type"),
                    ("ai_use_policy", "ai_use_policy"),
                )
            ):
                raise api_error(409, "ontology_inactive", "Authorized ontology is inactive.")
            if slot["kind"] == "profile_field" and not is_allowed_registry_value(
                self.session, "fact_type", slot["fact_type"]
            ):
                raise api_error(409, "ontology_inactive", "Authorized ontology is inactive.")
            if slot["kind"] == "relationship_edge":
                active = set(
                    self.session.scalars(
                        select(AllowedEdgeType.relation_type).where(
                            AllowedEdgeType.active.is_(True)
                        )
                    )
                )
                writable = {key for key, value in EDGE_DEFINITIONS.items() if value.support_level == "supported"}
                if not set(slot["allowed_relation_types"]) <= active & writable:
                    raise api_error(409, "ontology_inactive", "Authorized ontology is inactive.")
            if slot["kind"] == "observation":
                active = set(
                    self.session.scalars(
                        select(AllowedObservationType.observation_type).where(
                            AllowedObservationType.active.is_(True)
                        )
                    )
                )
                if not set(slot["allowed_observation_types"]) <= active:
                    raise api_error(409, "ontology_inactive", "Authorized ontology is inactive.")

    def _require_gaps(self, subject: Entity | None, slots: list[dict[str, Any]]) -> None:
        self._validate_subject(subject)
        for slot in slots:
            if self._pending_candidate_fills_gap(subject.id, slot):
                raise api_error(
                    409,
                    "pending_gap_filled",
                    "Authorized gap already has an unresolved candidate.",
                )
            if slot["kind"] == "profile_field":
                facts = self.session.scalars(
                    select(EntityFact).where(
                        EntityFact.entity_id == subject.id,
                        EntityFact.fact_type == slot["fact_type"],
                        EntityFact.status == "active",
                    )
                )
                if any((fact.value or {}).get("field_path") == slot["field_path"] for fact in facts):
                    raise api_error(409, "gap_filled", "Authorized profile gap is already filled.")
                continue
            if slot["kind"] == "relationship_edge":
                exists = self.session.scalar(
                    select(EntityEdge.id).where(
                        EntityEdge.from_entity_id == slot["from_entity_id"],
                        EntityEdge.to_entity_id == slot["to_entity_id"],
                        EntityEdge.relation_type.in_(slot["allowed_relation_types"]),
                        EntityEdge.status == "active",
                    )
                )
                if exists:
                    raise api_error(
                        409, "gap_filled", "Authorized relationship gap is already filled."
                    )
                continue
            exists = self._authorized_observation_gap_exists(slot)
            if exists:
                raise api_error(409, "gap_filled", "Authorized observation gap is already filled.")

    def _pending_candidate_fills_gap(self, subject_id: str, slot: dict[str, Any]) -> bool:
        candidates = self.session.scalars(
            select(Candidate).where(
                Candidate.target_entity_id == subject_id,
                Candidate.candidate_type == slot["kind"],
                Candidate.status.in_(("pending", "needs_clarification")),
            )
        )
        for candidate in candidates:
            payload = candidate.payload
            if not isinstance(payload, dict):
                continue
            if slot["kind"] == "profile_field":
                matches = (
                    payload.get("entity_id") == subject_id
                    and payload.get("fact_type") == slot["fact_type"]
                    and payload.get("field_path") == slot["field_path"]
                )
            elif slot["kind"] == "relationship_edge":
                matches = (
                    payload.get("from_entity_id") == slot["from_entity_id"]
                    and payload.get("to_entity_id") == slot["to_entity_id"]
                    and payload.get("relation_type") in slot["allowed_relation_types"]
                )
            else:
                related_entity_ids = payload.get("related_entity_ids")
                matches = (
                    payload.get("subject_entity_id") == subject_id
                    and isinstance(related_entity_ids, list)
                    and all(isinstance(entity_id, str) for entity_id in related_entity_ids)
                    and sorted(related_entity_ids) == sorted(slot["related_entity_ids"])
                    and payload.get("observation_type")
                    in slot["allowed_observation_types"]
                )
            if matches:
                return True
        return False

    def _authorized_observation_gap_exists(self, slot: dict[str, Any]) -> str | None:
        candidate_ids = list(
            self.session.scalars(
                select(Observation.id).where(
                    Observation.subject_entity_id == slot["subject_entity_id"],
                    Observation.observation_type.in_(slot["allowed_observation_types"]),
                    Observation.status == "active",
                )
            )
        )
        if not candidate_ids:
            return None
        expected_related = sorted(slot["related_entity_ids"])
        for observation_id in candidate_ids:
            related = sorted(
                self.session.scalars(
                    select(ObservationEntity.entity_id).where(
                        ObservationEntity.observation_id == observation_id
                    )
                )
            )
            if related == expected_related:
                return observation_id
        return None

    def _create_episode(self, body: EnrichmentAnswerCreate) -> Episode:
        assert body.source_excerpt is not None
        return RelationshipService(self.session).create_episode(
            {
                "source_type": body.source.source_type,
                "source_ref": body.source.source_ref,
                "source_description": ENRICHMENT_SOURCE_DESCRIPTION,
                "body_excerpt": body.source_excerpt,
                "body_hash": "sha256:" + hashlib.sha256(body.source_excerpt.encode()).hexdigest(),
                "actor": "user",
                "occurred_at": body.source.occurred_at,
                "retention_policy": ENRICHMENT_RETENTION_POLICY,
            },
            commit=False,
        )

    def _source_snapshot(
        self,
        body: EnrichmentAnswerCreate,
        known_answers: list[Any],
        episode: Episode | None,
    ) -> dict[str, Any] | None:
        if not known_answers:
            return None
        return {
            "source_type": body.source.source_type,
            "source_ref": body.source.source_ref,
            "source_actor": body.source.source_actor,
            "occurred_at": _aware(body.source.occurred_at).isoformat()
            if _aware(body.source.occurred_at)
            else None,
            "retention_policy": ENRICHMENT_RETENTION_POLICY,
            "body_hash": episode.body_hash if episode else None,
            "known_slot_ids": [answer.slot_id for answer in known_answers],
            "known_evidence_digests": [
                {"slot_id": answer.slot_id, "evidence_digest": _digest(answer.evidence_excerpt)}
                for answer in known_answers
            ],
        }

    def _candidate_payload(self, slot: dict[str, Any], answer: Any, episode_id: str) -> dict[str, Any]:
        selected_type = answer.selected_type
        if slot["kind"] == "profile_field":
            if selected_type is not None:
                raise api_error(
                    422, "validation_error", "selected_type is not allowed for profile slots."
                )
            payload = {
                "entity_id": slot["subject_entity_id"],
                "field_path": slot["field_path"],
                "fact_type": slot["fact_type"],
                "content": answer.value,
                "value": answer.value,
                "claim_type": slot["claim_type"],
                "ai_use_policy": slot["ai_use_policy"],
            }
        elif slot["kind"] == "relationship_edge":
            relation_type = selected_type or (
                slot["allowed_relation_types"][0]
                if len(slot["allowed_relation_types"]) == 1
                else None
            )
            if relation_type not in slot["allowed_relation_types"]:
                raise api_error(422, "validation_error", "selected_type is not authorized.")
            payload = {
                "from_entity_id": slot["from_entity_id"],
                "to_entity_id": slot["to_entity_id"],
                "relation_type": relation_type,
                "directed": EDGE_DEFINITIONS[relation_type].directed if slot.get("directed") is None else slot["directed"],
                "claim_text": answer.value,
                "claim_type": slot["claim_type"],
                "properties": slot["properties"],
            }
        else:
            observation_type = selected_type or (
                slot["allowed_observation_types"][0]
                if len(slot["allowed_observation_types"]) == 1
                else None
            )
            if observation_type not in slot["allowed_observation_types"]:
                raise api_error(422, "validation_error", "selected_type is not authorized.")
            payload = {
                "subject_entity_id": slot["subject_entity_id"],
                "related_entity_ids": slot["related_entity_ids"],
                "observation_type": observation_type,
                "content": answer.value,
                "claim_type": slot["claim_type"],
                "ai_use_policy": slot["ai_use_policy"],
            }
        return {
            "candidate_type": slot["kind"],
            "target_entity_id": slot["subject_entity_id"],
            "payload": payload,
            "evidence": [
                {"episode_id": episode_id, "excerpt": answer.evidence_excerpt, "confidence": 1.0}
            ],
            "confidence": 1.0,
            "suggested_action": "accept",
            "created_by": "user",
        }

    def _verify_episode(
        self,
        action: EnrichmentAnswerAction,
        episode: Episode,
        known_outcomes: list[dict[str, Any]],
    ) -> None:
        source_snapshot = action.source_snapshot or {}
        if (
            source_snapshot.get("source_type") != "agent_conversation"
            or episode.source_type != "agent_conversation"
            or source_snapshot.get("source_ref") != episode.source_ref
            or source_snapshot.get("source_actor") != "user"
            or episode.actor != "user"
            or source_snapshot.get("source_actor") != episode.actor
            or source_snapshot.get("retention_policy") != episode.retention_policy
            or source_snapshot.get("body_hash") != episode.body_hash
            or episode.body_hash
            != "sha256:" + hashlib.sha256(episode.body_excerpt.encode()).hexdigest()
            or episode.source_description != ENRICHMENT_SOURCE_DESCRIPTION
            or episode.retention_policy != ENRICHMENT_RETENTION_POLICY
        ):
            raise ValueError
        occurred_at = _aware(episode.occurred_at)
        expected_occurred_at = source_snapshot.get("occurred_at")
        if (occurred_at.isoformat() if occurred_at else None) != expected_occurred_at:
            raise ValueError
        if source_snapshot.get("known_slot_ids") != [outcome["slot_id"] for outcome in known_outcomes]:
            raise ValueError
        if source_snapshot.get("known_evidence_digests") != [
            {"slot_id": outcome["slot_id"], "evidence_digest": outcome["evidence_digest"]}
            for outcome in known_outcomes
        ]:
            raise ValueError

    def _verify_candidate(
        self,
        session: Session,
        outcome: dict[str, Any],
        slot: dict[str, Any],
        candidate: Candidate,
        episode: Episode | None,
    ) -> None:
        if (
            candidate.status != "accepted"
            or candidate.created_by != "user"
            or candidate.resolved_by != "user"
            or candidate.target_entity_id != slot["subject_entity_id"]
            or candidate.canonical_record_ref != outcome["canonical_ref"]
            or _digest(candidate.payload) != outcome["candidate_payload_digest"]
        ):
            raise ValueError
        self._verify_candidate_matches_slot(slot, candidate)
        evidence = list(
            session.scalars(
                select(CandidateEvidence).where(CandidateEvidence.candidate_id == candidate.id)
            )
        )
        if (
            episode is None
            or len(evidence) != 1
            or evidence[0].episode_id != episode.id
            or _digest(evidence[0].excerpt) != outcome["evidence_digest"]
            or evidence[0].excerpt not in episode.body_excerpt
        ):
            raise ValueError
        self._verify_canonical(session, slot, candidate, evidence[0].excerpt, episode.id)

    @staticmethod
    def _verify_candidate_matches_slot(slot: dict[str, Any], candidate: Candidate) -> None:
        payload = candidate.payload
        if candidate.candidate_type != slot["kind"]:
            raise ValueError
        if slot["kind"] == "profile_field":
            if (
                payload.get("entity_id") != slot["subject_entity_id"]
                or payload.get("field_path") != slot["field_path"]
                or payload.get("fact_type") != slot["fact_type"]
                or payload.get("claim_type") != slot["claim_type"]
                or payload.get("content") != payload.get("value")
            ):
                raise ValueError
            return
        if slot["kind"] == "relationship_edge":
            if (
                payload.get("from_entity_id") != slot["from_entity_id"]
                or payload.get("to_entity_id") != slot["to_entity_id"]
                or payload.get("relation_type") not in slot["allowed_relation_types"]
                or payload.get("directed") != (
                    EDGE_DEFINITIONS[payload["relation_type"]].directed
                    if slot.get("directed") is None else slot["directed"]
                )
                or payload.get("claim_type") != slot["claim_type"]
                or payload.get("properties") != slot["properties"]
            ):
                raise ValueError
            return
        if (
            payload.get("subject_entity_id") != slot["subject_entity_id"]
            or payload.get("observation_type") not in slot["allowed_observation_types"]
            or sorted(payload.get("related_entity_ids", [])) != slot["related_entity_ids"]
            or payload.get("claim_type") != slot["claim_type"]
        ):
            raise ValueError

    @staticmethod
    def _snapshot(entity: Entity) -> dict[str, Any]:
        return {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "display_name": entity.display_name,
            "canonical_name": entity.canonical_name,
            "system_role": entity.system_role,
            "confirmation_status": entity.confirmation_status,
            "status": entity.status,
            "updated_at": entity.updated_at.isoformat(),
            "entity_digest": entity_digest(entity),
        }

    @staticmethod
    def _verify_canonical(
        session: Session,
        slot: dict[str, Any],
        candidate: Candidate,
        excerpt: str,
        expected_episode_id: str,
    ) -> None:
        table, record_id = candidate.canonical_record_ref.split(":", 1)
        mapping = {
            "entity_facts": (EntityFact, EntityFactEvidence, "entity_fact_id"),
            "entity_edges": (EntityEdge, EdgeEvidence, "edge_id"),
            "observations": (Observation, ObservationEvidence, "observation_id"),
        }
        model, evidence_model, foreign_key = mapping[table]
        record = session.get(model, record_id)
        if not record or record.source_candidate_id != candidate.id:
            raise ValueError
        payload = candidate.payload
        if table == "entity_facts" and (
            record.entity_id != slot["subject_entity_id"]
            or record.fact_type != slot["fact_type"]
            or record.content != payload["content"]
            or record.value != {"field_path": slot["field_path"], "value": payload["value"]}
            or record.claim_type != slot["claim_type"]
        ):
            raise ValueError
        if table == "entity_edges" and (
            record.from_entity_id != slot["from_entity_id"]
            or record.to_entity_id != slot["to_entity_id"]
            or record.relation_type != payload["relation_type"]
            or record.relation_type not in slot["allowed_relation_types"]
            or record.directed != payload.get("directed")
            or record.claim_text != payload["claim_text"]
            or record.claim_type != slot["claim_type"]
            or record.properties != slot["properties"]
        ):
            raise ValueError
        if table == "observations" and (
            record.subject_entity_id != slot["subject_entity_id"]
            or record.observation_type != payload["observation_type"]
            or record.observation_type not in slot["allowed_observation_types"]
            or record.content != payload["content"]
            or record.claim_type != slot["claim_type"]
        ):
            raise ValueError
        if table == "observations":
            related = sorted(
                session.scalars(
                    select(ObservationEntity.entity_id).where(
                        ObservationEntity.observation_id == record_id
                    )
                )
            )
            if related != slot["related_entity_ids"]:
                raise ValueError
        evidence = list(
            session.scalars(
                select(evidence_model).where(getattr(evidence_model, foreign_key) == record_id)
            )
        )
        if (
            len(evidence) != 1
            or evidence[0].episode_id != expected_episode_id
            or evidence[0].excerpt != excerpt
        ):
            raise ValueError
