"""Read-only verification of the persisted import attestation and source linkage."""

from datetime import UTC

from pydantic import ValidationError

from kinlayer_backend.models import MaterialImport
from kinlayer_backend.schemas.material_imports import (
    MaterialImportRequest,
    json_digest,
    text_digest,
)


def material_provenance(session, evidence):
    episode = evidence.episode
    if not episode or not episode.material_import_id:
        return None
    row = session.get(MaterialImport, episode.material_import_id)
    if not row or json_digest(row.manifest) != row.request_sha256:
        return None
    try:
        payload = MaterialImportRequest.model_validate({"idempotency_key": row.id, **row.manifest})
    except (ValidationError, TypeError):
        return None
    link = row.candidate_links.get(evidence.candidate_id, {})
    candidate = evidence.candidate
    if (
        not candidate
        or candidate.candidate_type != "observation"
        or candidate.target_entity_id != payload.target_entity_id
        or link.get("target_entity_id") != payload.target_entity_id
        or link.get("payload_sha256") != json_digest(candidate.payload)
        or set(link.get("episodes", {})) != {e.episode_id for e in candidate.evidence}
    ):
        return None
    source_id = link.get("episodes", {}).get(episode.id)
    source = next((s for s in payload.sources if s.source_id == source_id), None)
    occurred = episode.occurred_at
    if occurred and occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    if (
        not source
        or episode.source_type != "import"
        or source.source_ref != episode.source_ref
        or source.author != episode.actor
        or source.excerpt != episode.body_excerpt
        or source.excerpt != evidence.excerpt
        or source.original_sha256 != episode.body_hash
        or source.occurred_at != occurred
    ):
        return None
    auth = payload.authorization
    return {
        "import_id": row.id,
        "request_sha256": row.request_sha256,
        "manifest_sha256": auth.manifest_sha256,
        "candidate_id": candidate.id,
        "target_entity_id": payload.target_entity_id,
        "source_id": source.source_id,
        "source_kind": source.kind,
        "source_date_status": "known" if source.occurred_at is not None else "unknown",
        "message_id": source.message_id,
        "author_kind": "human",
        "claim_kind": link["kind"],
        "authorization_ref": auth.source_ref,
        "authorization_message_id": auth.message_id,
        "authorization_occurred_at": auth.occurred_at.isoformat(),
        "authorization_excerpt_sha256": text_digest(auth.excerpt),
        "trust_boundary": "authenticated_caller_attestation",
    }


def canonical_payload_digest(session, record_ref):
    """Bind immutable semantic fields, not status changed by a later correction."""
    from sqlalchemy import select
    from kinlayer_backend.models import EntityFact, Observation, ObservationEntity
    from kinlayer_backend.schemas.memories import MemoryFactPayload, MemoryObservationPayload
    from kinlayer_backend.services.memories import utc

    kind, record_id = record_ref.split(":", 1)
    model, schema = {
        "entity_facts": (EntityFact, MemoryFactPayload),
        "observations": (Observation, MemoryObservationPayload),
    }[kind]
    record = session.get(model, record_id)
    if record is None:
        return None
    session.refresh(record)
    payload = {}
    for field in schema.model_fields:
        if field == "related_entities":
            payload[field] = [
                {"entity_id": link.entity_id, "role": link.role,
                 "confidence": float(link.confidence) if link.confidence is not None else None}
                for link in session.scalars(select(ObservationEntity).where(
                    ObservationEntity.observation_id == record_id,
                ).order_by(ObservationEntity.entity_id, ObservationEntity.role))
            ]
        else:
            value = getattr(record, field)
            if field in {"valid_from", "valid_to", "occurred_at"} and value is not None:
                value = utc(value)
            payload[field] = value
    return json_digest(schema.model_validate(payload).model_dump(mode="json"))


def canonical_material_provenance(session, record_ref, evidence, episode):
    """Verify V2's direct canonical linkage without manufacturing a candidate."""
    from sqlalchemy import select
    from kinlayer_backend.models import EntityFactEvidence, ObservationEvidence
    from kinlayer_backend.schemas.material_imports import MaterialImportV2Request

    if not episode or not episode.material_import_id:
        return None
    row = session.get(MaterialImport, episode.material_import_id)
    if not row or row.manifest.get("contract_version") != "2" or json_digest(row.manifest) != row.request_sha256:
        return None
    try:
        payload = MaterialImportV2Request.model_validate({"idempotency_key": row.id, **row.manifest})
        link = row.candidate_links.get(record_ref, {})
        index = link.get("record_index")
        if type(index) is not int or not 0 <= index < len(payload.records):
            return None
        item = payload.records[index]
        kind, record_id = record_ref.split(":", 1)
        evidence_model, key = {
            "entity_facts": (EntityFactEvidence, EntityFactEvidence.entity_fact_id),
            "observations": (ObservationEvidence, ObservationEvidence.observation_id),
        }[kind]
        linked_episodes = list(session.scalars(select(evidence_model.episode_id).where(key == record_id)))
        if (
            item.record.record_type != kind
            or link.get("canonical_record_ref") != record_ref
            or link.get("target_entity_id") != payload.target_entity_id
            or link.get("payload_sha256") != canonical_payload_digest(session, record_ref)
            or set(link.get("episodes", {})) != set(linked_episodes)
            or len(linked_episodes) != len(item.source_ids)
            or set(link.get("episodes", {}).values()) != set(item.source_ids)
        ):
            return None
        source_id = link["episodes"].get(episode.id)
        source = next((s for s in payload.sources if s.source_id == source_id), None)
        occurred = episode.occurred_at
        if occurred and occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        if (
            not source or episode.source_type != "import"
            or source.source_ref != episode.source_ref
            or source.author != episode.actor
            or source.excerpt != episode.body_excerpt
            or source.excerpt != evidence.excerpt
            or source.original_sha256 != episode.body_hash
            or source.occurred_at != occurred
            or episode.source_description != f"{source.kind}; locator={source.message_id}"
        ):
            return None
    except (ValidationError, TypeError, ValueError, KeyError):
        return None
    auth = payload.authorization
    return {
        "contract_version": "2", "import_id": row.id,
        "request_sha256": row.request_sha256, "manifest_sha256": auth.manifest_sha256,
        "canonical_record_ref": record_ref, "target_entity_id": payload.target_entity_id,
        "source_id": source.source_id, "source_kind": source.kind,
        "source_date_status": "known" if source.occurred_at is not None else "unknown",
        "source_occurred_at": source.occurred_at.isoformat() if source.occurred_at else None,
        "source_ref": source.source_ref, "message_id": source.message_id,
        "author": source.author, "author_kind": source.author_kind,
        "original_sha256": source.original_sha256, "excerpt_sha256": source.excerpt_sha256,
        "claim_basis": item.record.payload.claim_basis,
        "authorization_ref": auth.source_ref, "authorization_message_id": auth.message_id,
        "authorization_occurred_at": auth.occurred_at.isoformat(),
        "authorization_excerpt_sha256": text_digest(auth.excerpt),
        "authorization_source_ids": auth.source_ids,
        "trust_boundary": "authenticated_caller_attestation",
    }
