"""Atomic, source-preserving writes without a candidate approval stage."""

from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    AllowedObservationType,
    EdgeEvidence,
    Entity,
    EntityAlias,
    EntityEdge,
    EntityFact,
    EntityFactEvidence,
    Episode,
    MemoryChange,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.schemas.memories import MemoryWriteRequest
from kinlayer_backend.services.entity_guards import lock_active_entities
from kinlayer_backend.services.ontology import is_allowed_registry_value
from kinlayer_backend.services.relationship_ontology import validate_edge_write
from kinlayer_backend.services.relationship_profiles import ASSESSMENT_TYPE, validate_assessment_change, validate_assessment_write

RECORD_MODELS = {
    "entity_facts": EntityFact,
    "entity_edges": EntityEdge,
    "observations": Observation,
}


def memory_fingerprint(body: MemoryWriteRequest) -> str:
    raw = json.dumps(
        body.model_dump(mode="json", exclude={"request_id"}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + sha256(raw.encode()).hexdigest()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class MemoryService:
    def __init__(self, session: Session):
        self.session = session

    def get_change(self, change_id: str) -> MemoryChange:
        row = self.session.get(MemoryChange, change_id)
        if row is None:
            raise api_error(404, "not_found", "Memory change not found.")
        return row

    def list_changes(
        self, record_ref: str | None, limit: int, offset: int, *, entity_id: str | None = None
    ) -> dict[str, Any]:
        query = select(MemoryChange)
        if entity_id:
            from kinlayer_backend.services.memory_reads import canonical_entity_scope, memory_index

            entity_ids = canonical_entity_scope(self.session, entity_id)
            index = memory_index(
                now=datetime.now(UTC), status="all",
                entity_ids=entity_ids,
            )
            # Migration receipts also preserve identity and alias changes. Include
            # inactive aliases and merged predecessors without inventing old values.
            refs = union_all(
                select(index.c.record_ref),
                select(literal("entities:") + Entity.id).where(Entity.id.in_(entity_ids)),
                select(literal("entity_aliases:") + EntityAlias.id).where(
                    EntityAlias.entity_id.in_(entity_ids),
                ),
            )
            query = query.where(or_(MemoryChange.old_record_ref.in_(refs),
                                    MemoryChange.new_record_ref.in_(refs)))
        if record_ref is not None:
            prefix, separator, record_id = record_ref.partition(":")
            if not separator or not record_id or (
                prefix not in RECORD_MODELS and prefix not in {"entities", "entity_aliases"}
            ):
                raise api_error(422, "validation_error", "Unsupported record_ref.")
            query = query.where(
                or_(
                    MemoryChange.old_record_ref == record_ref,
                    MemoryChange.new_record_ref == record_ref,
                )
            )
        total = self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.session.scalars(
            query.order_by(MemoryChange.created_at.desc(), MemoryChange.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return {"items": rows, "total": total, "limit": limit, "offset": offset}

    def _existing(self, request_id: str, fingerprint: str) -> MemoryChange | None:
        row = self.session.scalar(select(MemoryChange).where(MemoryChange.request_id == request_id))
        if row is not None and row.request_sha256 != fingerprint:
            raise api_error(
                409, "idempotency_conflict", "request_id already has different content."
            )
        return row

    @staticmethod
    def _receipt(row: MemoryChange) -> dict[str, Any]:
        return {
            "change_id": row.id,
            "action": row.change_kind,
            "old_record_ref": row.old_record_ref,
            "new_record_ref": row.new_record_ref,
            "source_episode_id": row.source_episode_id,
        }

    def write(self, body: MemoryWriteRequest) -> dict[str, Any]:
        fingerprint = memory_fingerprint(body)
        try:
            existing = self._existing(body.request_id, fingerprint)
            if existing is not None:
                return self._receipt(existing)
            # Reserve the unique request before reading/modifying the old record.
            # Concurrent replays wait on this insert, then read its committed receipt.
            change = MemoryChange(
                request_id=body.request_id,
                request_sha256=fingerprint,
                change_kind=body.action,
                old_record_ref=body.old_record_ref,
                actor=body.created_by,
                reason=body.reason,
            )
            self.session.add(change)
            self.session.flush()
            old = (
                self._lock_old(body.old_record_ref, body.expected_updated_at)
                if body.old_record_ref
                else None
            )
            if old is not None and body.record is not None:
                self._validate_targets(old, body)
            # Release a current assessment's unique axis slot inside this same atomic
            # transaction; a rejected replacement restores the original via rollback.
            if old is not None and isinstance(old, Observation) and old.observation_type == ASSESSMENT_TYPE and body.record is not None:
                old.status = "superseded"
                self.session.flush()
            episode = self._create_episode(body)
            change.source_episode_id = episode.id
            if body.record is not None:
                new_ref = self._write_record(
                    body.record.record_type, body.record.payload.model_dump(), body.created_by,
                    previous=old if body.action == "correct" and isinstance(old, EntityEdge) else None,
                )
                self._link_evidence(new_ref, episode.id, body.source.excerpt)
                change.new_record_ref = new_ref
            if old is not None:
                old.status = "deleted" if body.action == "retract" else "superseded"
                # valid_to is when the claim stopped being true, not when we corrected it.
                if (
                    isinstance(old, EntityEdge)
                    and change.new_record_ref
                    and change.new_record_ref.startswith("entity_edges:")
                ):
                    old.invalidated_by_edge_id = change.new_record_ref.split(":", 1)[1]
            self.session.flush()
            receipt = self._receipt(change)
            self.session.commit()
            return receipt
        except IntegrityError:
            self.session.rollback()
            existing = self._existing(body.request_id, fingerprint)
            if existing is not None:
                return self._receipt(existing)
            if body.record is not None and body.record.record_type == "observations" and body.record.payload.observation_type == ASSESSMENT_TYPE:
                from kinlayer_backend.services.relationship_profiles import axis_conflict
                payload = body.record.payload
                current = self.session.scalar(select(Observation).where(
                    Observation.subject_entity_id == payload.subject_entity_id,
                    Observation.perspective_entity_id == payload.perspective_entity_id,
                    Observation.relationship_axis == payload.relationship_axis,
                    Observation.status.in_(("active", "disputed")),
                ))
                if current is not None:
                    axis_conflict(current)
            raise
        except Exception:
            self.session.rollback()
            raise

    def _lock_old(self, record_ref: str, expected_updated_at: datetime | None):
        prefix, separator, record_id = record_ref.partition(":")
        model = RECORD_MODELS.get(prefix)
        if not separator or not record_id or model is None:
            raise api_error(422, "validation_error", "Unsupported old_record_ref.")
        row = self.session.scalar(
            select(model)
            .where(model.id == record_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise api_error(404, "not_found", "Old memory record not found.")
        if row.status not in {"active", "disputed"}:
            raise api_error(
                409,
                "conflict",
                "Old memory record is no longer current.",
                {
                    "errors": [{"code": "stale_record_ref", "field": "old_record_ref"}],
                },
            )
        if expected_updated_at is not None and utc(row.updated_at) != utc(expected_updated_at):
            raise api_error(409, "stale_record_ref", "Old memory changed since it was read.")
        return row

    @staticmethod
    def _targets(record_type: str, payload: dict[str, Any]) -> tuple[str, ...]:
        if record_type == "entity_edges":
            return (payload["from_entity_id"], payload["to_entity_id"])
        return (payload["entity_id" if record_type == "entity_facts" else "subject_entity_id"],)

    def _validate_targets(self, old, body: MemoryWriteRequest) -> None:
        validate_assessment_change(old, body.record.record_type, body.record.payload.model_dump())
        old_type = body.old_record_ref.split(":", 1)[0]
        old_targets = self._targets(old_type, vars(old))
        new_targets = self._targets(body.record.record_type, body.record.payload.model_dump())
        if body.action == "correct" and old_targets != new_targets:
            raise api_error(422, "validation_error", "Use reattribute to change a memory's target.")
        if body.action == "reattribute" and (
            old_type != body.record.record_type or old_targets == new_targets
        ):
            raise api_error(
                422,
                "validation_error",
                "Reattribution requires the same record type and a different target.",
            )

    def _create_episode(self, body: MemoryWriteRequest) -> Episode:
        source = body.source
        episode = Episode(
            source_type=source.source_type if body.action == "create" else "correction",
            source_ref=source.source_ref,
            source_description=f"Memory {body.action} from {source.source_type}; source_actor={source.actor}; submitted_by={body.created_by}",
            actor=source.actor,
            body_excerpt=source.excerpt,
            body_hash="sha256:" + sha256(source.excerpt.encode()).hexdigest(),
            occurred_at=source.occurred_at.astimezone(UTC) if source.occurred_at else None,
            retention_policy="excerpt_only",
        )
        self.session.add(episode)
        self.session.flush()
        return episode

    def _write_record(self, record_type: str, payload: dict[str, Any], created_by: str, *, previous: EntityEdge | None = None) -> str:
        payload = dict(payload)
        for field in ("valid_from", "valid_to", "occurred_at"):
            if payload.get(field) is not None:
                payload[field] = payload[field].astimezone(UTC)
        # The legacy physical column is retained for compatibility, never accepted
        # from the new API and never used as an approval or retrieval gate.
        payload["claim_type"] = "fact" if payload["claim_basis"] == "reported" else "inference"
        payload.update(created_by=created_by, status="active")
        if record_type == "entity_facts":
            from kinlayer_backend.services.structured_facts import normalize_profile_fact

            lock_active_entities(self.session, [payload["entity_id"]])
            if not is_allowed_registry_value(self.session, "fact_type", payload["fact_type"]):
                raise api_error(422, "validation_error", "Invalid fact_type.")
            if payload["fact_type"] in {
                "memo",
                "important_context",
                "relationship_note",
                "contact_note",
            }:
                raise api_error(422, "validation_error", "Store contextual notes as observations.")
            try:
                payload["content"], payload["value"] = normalize_profile_fact(
                    payload["fact_type"], payload["content"], payload["value"]
                )
            except ValueError as exc:
                raise api_error(422, "validation_error", str(exc)) from exc
            row = EntityFact(**payload)
        elif record_type == "entity_edges":
            lock_active_entities(
                self.session, [payload["from_entity_id"], payload["to_entity_id"]]
            )
            validate_edge_write(self.session, payload, previous=previous)
            row = EntityEdge(**payload)
        else:
            validate_assessment_write(self.session, payload)
            related = payload.pop("related_entities")
            lock_active_entities(
                self.session,
                [payload["subject_entity_id"], *(link["entity_id"] for link in related)],
            )
            if (
                self.session.scalar(
                    select(AllowedObservationType).where(
                        AllowedObservationType.observation_type == payload["observation_type"],
                        AllowedObservationType.active.is_(True),
                    )
                )
                is None
            ):
                raise api_error(422, "validation_error", "Invalid observation_type.")
            row = Observation(**payload, embedding_status="pending")
            self.session.add(row)
            self.session.flush()
            for link in related:
                self.session.add(ObservationEntity(observation_id=row.id, **link))
        self.session.add(row)
        self.session.flush()
        return f"{record_type}:{row.id}"

    def _link_evidence(self, record_ref: str, episode_id: str, excerpt: str) -> None:
        prefix, record_id = record_ref.split(":", 1)
        model, key = {
            "entity_facts": (EntityFactEvidence, "entity_fact_id"),
            "entity_edges": (EdgeEvidence, "edge_id"),
            "observations": (ObservationEvidence, "observation_id"),
        }[prefix]
        self.session.add(model(**{key: record_id, "episode_id": episode_id, "excerpt": excerpt}))
        self.session.flush()
