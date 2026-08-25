from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.models import Candidate, CandidateEvidence, Entity, Episode


def digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def candidate_payload_digest(candidate: Candidate) -> str:
    return digest(candidate.payload)


def candidate_evidence_digest(session: Session, candidate_id: str) -> str:
    rows = session.execute(
        select(CandidateEvidence, Episode)
        .join(Episode, Episode.id == CandidateEvidence.episode_id)
        .where(CandidateEvidence.candidate_id == candidate_id)
        .order_by(CandidateEvidence.id)
    ).all()
    return digest(
        [
            {
                "id": evidence.id,
                "episode_id": evidence.episode_id,
                "excerpt": evidence.excerpt,
                "confidence": str(evidence.confidence)
                if evidence.confidence is not None
                else None,
                "source_type": episode.source_type,
                "source_ref": episode.source_ref,
                "body_hash": episode.body_hash,
                "actor": episode.actor,
            }
            for evidence, episode in rows
        ]
    )


def candidate_snapshot(session: Session, candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "status": candidate.status,
        "updated_at": candidate.updated_at.isoformat(),
        "payload_digest": candidate_payload_digest(candidate),
        "evidence_digest": candidate_evidence_digest(session, candidate.id),
    }


def entity_digest(entity: Entity) -> str:
    return digest(
        {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "display_name": entity.display_name,
            "canonical_name": entity.canonical_name,
            "properties": entity.properties or {},
            "confirmation_status": entity.confirmation_status,
            "status": entity.status,
            "sensitivity": entity.sensitivity,
            "ai_use_policy": entity.ai_use_policy,
            "created_by": entity.created_by,
            "system_role": entity.system_role,
            "is_system": entity.is_system,
            "first_seen_at": entity.first_seen_at.isoformat() if entity.first_seen_at else None,
            "last_referenced_at": (
                entity.last_referenced_at.isoformat() if entity.last_referenced_at else None
            ),
        }
    )
