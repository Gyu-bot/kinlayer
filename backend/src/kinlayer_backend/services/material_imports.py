"""Atomically save authorized material as canonical memories and source receipts."""

from copy import deepcopy
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import Entity, Episode, MaterialImport, MemoryChange
from kinlayer_backend.schemas.material_imports import MaterialImportRequest, json_digest
from kinlayer_backend.services.agent_write_filter import AgentWriteFilter
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.entity_guards import lock_active_entities


def request_fingerprint(payload: MaterialImportRequest) -> str:
    return json_digest(payload.model_dump(mode="json", exclude={"idempotency_key"}))


class MaterialImportService:
    def __init__(self, session: Session):
        self.session = session

    def _existing(self, payload, fingerprint):
        row = self.session.get(MaterialImport, payload.idempotency_key)
        if row and row.request_sha256 != fingerprint:
            raise api_error(
                409, "material_import_replay_conflict", "Import key has different content."
            )
        if row:
            return row
        duplicate = self.session.scalar(
            select(MaterialImport).where(MaterialImport.request_sha256 == fingerprint)
        )
        if duplicate:
            raise api_error(
                409,
                "material_import_duplicate_content",
                "Content already imported; use the original import key.",
                {"import_id": duplicate.id},
            )
        return None

    def read(self, key):
        row = self.session.get(MaterialImport, key)
        if not row:
            raise api_error(404, "not_found", "Material import not found.")
        return {**self._receipt(row, "replayed"), "manifest": row.manifest}

    @staticmethod
    def _receipt(row, status):
        canonical_refs = sorted(
            link["canonical_record_ref"]
            for link in row.candidate_links.values()
            if link.get("canonical_record_ref")
        )
        return {
            # Old receipts retain their original lifecycle and signed manifest.
            "validation_scope": "immediate_memories" if canonical_refs else "pending_candidates_only",
            "status": status,
            "import_id": row.id,
            "request_sha256": row.request_sha256,
            "candidate_ids": sorted(row.candidate_links),
            "canonical_record_refs": canonical_refs,
            "episode_ids": sorted(
                {eid for link in row.candidate_links.values() for eid in link["episodes"]}
            ),
        }

    def run(self, payload: MaterialImportRequest, *, submit=False):
        fingerprint = request_fingerprint(payload)
        existing = self._existing(payload, fingerprint)
        if existing:
            return self._receipt(existing, "replayed")
        # A supplied identifier is never resolved through names or merged automatically.
        target = self.session.get(Entity, payload.target_entity_id)
        if submit and target:
            target = lock_active_entities(self.session, [target.id])[target.id]
        if (
            not target
            or target.status != "active"
            or target.entity_type != "person"
            or target.system_role == "self"
        ):
            raise api_error(
                422,
                "material_import_target_invalid",
                "An existing active non-self person ID is required.",
            )
        if submit:
            existing = self._existing(payload, fingerprint)
            if existing:
                return self._receipt(existing, "replayed")
        manifest = payload.model_dump(mode="json", exclude={"idempotency_key"})
        row = MaterialImport(
            id=payload.idempotency_key,
            request_sha256=fingerprint,
            manifest=manifest,
            candidate_links={},
        )
        try:
            # Preview uses the identical validators in a rollback-only transaction.
            self.session.add(row)
            self.session.flush()
            episodes = {}
            for source in payload.sources:
                episode = Episode(
                    material_import_id=row.id,
                    source_type="import",
                    source_ref=source.source_ref,
                    source_description=f"{source.kind}; locator={source.message_id}",
                    body_excerpt=source.excerpt,
                    body_hash=source.original_sha256,
                    actor=source.author,
                    # SQLite drops tzinfo, so persist UTC clock time, never local time.
                    # Keep the original offset in the hash-bound source manifest.
                    occurred_at=source.occurred_at.astimezone(UTC)
                    if source.occurred_at is not None else None,
                    retention_policy="excerpt_only",
                )
                self.session.add(episode)
                self.session.flush()
                episodes[source.source_id] = episode
            candidates = []
            candidate_rows = []
            links = {}
            sources = {s.source_id: s for s in payload.sources}
            for claim in payload.claims:
                body = {
                    "candidate_type": "observation",
                    "target_entity_id": target.id,
                    "payload": {
                        "subject_entity_id": target.id,
                        "related_entity_ids": [],
                        "observation_type": claim.observation_type,
                        "content": claim.summary,
                        "claim_type": "fact" if claim.kind == "sourced_report" else "inference",
                        "claim_basis": "reported" if claim.kind == "sourced_report" else "inferred",
                        # Source dates are evidence metadata, not the event date.
                        "occurred_at": None,
                    },
                    "evidence": [
                        {
                            "episode_id": episodes[sid].id,
                            "excerpt": sources[sid].excerpt,
                            "confidence": claim.confidence,
                        }
                        for sid in claim.source_ids
                    ],
                    "confidence": claim.confidence,
                    "suggested_action": "accept",
                    "created_by": "ai_agent",
                }
                result = AgentWriteFilter(self.session).validate("candidate", body)
                if not result["accepted"]:
                    raise api_error(
                        422,
                        "material_import_candidate_invalid",
                        "Imported candidate failed validation.",
                        {"errors": result["errors"], "warnings": result["warnings"]},
                    )
                candidate = CandidateService(self.session).create_candidate(
                    deepcopy(result["validated_payload"]), commit=False, material_import_id=row.id
                )
                links[candidate.id] = {
                    "payload_sha256": json_digest(candidate.payload),
                    "kind": claim.kind,
                    "target_entity_id": target.id,
                    "episodes": {episodes[sid].id: sid for sid in claim.source_ids},
                }
                candidates.append(deepcopy(candidate.payload))
                candidate_rows.append(candidate)
            row.candidate_links = deepcopy(links)
            self.session.flush()
            # Persist source links before accepting so the ordinary provenance
            # verifier checks exactly the same signed manifest and evidence.
            for index, candidate in enumerate(candidate_rows):
                CandidateService(self.session).accept_candidate(
                    candidate,
                    resolved_by="ai_agent",
                    resolution_note="Saved from authorized material import.",
                    commit=False,
                )
                links[candidate.id]["canonical_record_ref"] = candidate.canonical_record_ref
                self.session.add(MemoryChange(
                    request_id=f"material-import:{row.id}:{index}",
                    request_sha256=json_digest({
                        "import_request_sha256": fingerprint, "claim_index": index,
                    }),
                    change_kind="create",
                    new_record_ref=candidate.canonical_record_ref,
                    source_episode_id=candidate.evidence[0].episode_id,
                    actor="ai_agent",
                    reason="Saved from authorized material import.",
                ))
            # Assign a fresh JSON value to make persisted receipts replayable.
            row.candidate_links = deepcopy(links)
            self.session.flush()
            receipt = self._receipt(row, "submitted" if submit else "validated")
            if submit:
                self.session.commit()
                return receipt
            self.session.rollback()
            return {
                **receipt,
                "import_id": None,
                "candidate_ids": [],
                "canonical_record_refs": [],
                "episode_ids": [],
                "candidates": candidates,
            }
        except IntegrityError:
            self.session.rollback()
            existing = self._existing(payload, fingerprint)
            if existing:
                return self._receipt(existing, "replayed")
            raise
        except Exception:
            self.session.rollback()
            raise
