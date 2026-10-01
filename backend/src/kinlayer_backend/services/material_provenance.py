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
