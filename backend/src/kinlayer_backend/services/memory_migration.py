"""Operator-supplied, reviewed data conversion; never interpret private text here.

The manifest lives outside version control. Every affected row is guarded by its
expected values. Replacements retain originals and copy only existing evidence.
Dry-run executes the same transaction and rolls it back.
"""
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import DateTime, select, text
from sqlalchemy.orm import Session

from kinlayer_backend.models import (
    Base, Candidate, EdgeEvidence, Entity, EntityFactEvidence, MemoryChange,
    Observation, ObservationEntity, ObservationEvidence, now_utc,
)
from kinlayer_backend.schemas.memories import MemoryRecord
from kinlayer_backend.services.entities import EntityService
from kinlayer_backend.services.memories import MemoryService, RECORD_MODELS, utc
from pydantic import TypeAdapter

EVIDENCE = {
    "entity_facts": (EntityFactEvidence, "entity_fact_id"),
    "entity_edges": (EdgeEvidence, "edge_id"),
    "observations": (ObservationEvidence, "observation_id"),
}


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(raw.encode()).hexdigest()


def snapshot_digest(rows, table):
    """Normalize DB driver representations, not the semantics of source content."""
    from decimal import Decimal
    prepared = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(table.c[key].type, DateTime) and value is not None:
                value = datetime.fromisoformat(value) if isinstance(value, str) else value
                item[key] = (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()
            elif isinstance(value, Decimal):
                item[key] = float(value)
        prepared.append(item)
    return digest(sorted(prepared, key=lambda row: row["id"]))


class MemoryDataMigration:
    def __init__(self, session: Session):
        self.session = session
        self.memory = MemoryService(session)
        self.stats = {"replaced": 0, "created": 0, "metadata_updated": 0,
                      "candidates_resolved": 0, "entities_cleaned": 0, "evidence_copied": 0}

    def _row(self, ref: str):
        table, identifier = ref.split(":", 1)
        model = {**RECORD_MODELS, "entities": Entity, "candidates": Candidate}.get(table)
        if model is None:
            raise ValueError("Unsupported migration record type.")
        row = self.session.scalar(select(model).where(model.id == identifier).with_for_update())
        if row is None:
            raise ValueError(f"Migration row missing: {ref}")
        return row

    @staticmethod
    def _guard(row, expected):
        for key, value in expected.items():
            observed = getattr(row, key)
            if isinstance(observed, datetime):
                value = datetime.fromisoformat(value.replace("Z", "+00:00")) if value else value
                # API snapshots carry UTC offsets; SQLite returns naive UTC datetimes.
                # Compare instants so the same guarded manifest can be rehearsed locally.
                observed = utc(observed)
                if isinstance(value, datetime):
                    value = utc(value)
            if observed != value:
                raise ValueError(f"Migration input drift: {row.__tablename__}:{row.id} {key}")

    def _receipt(self, key, fingerprint, old_ref, new_ref, reason, episode_id=None):
        self.session.add(MemoryChange(
            request_id=key, request_sha256=fingerprint, change_kind="migrate",
            old_record_ref=old_ref, new_record_ref=new_ref, actor="system",
            reason=reason, source_episode_id=episode_id,
        ))

    def _new_record(self, item: dict, old=None):
        supplied = deepcopy(item)
        if old is not None:
            time_fields = ("valid_from", "valid_to")
            if supplied["record_type"] == "observations":
                time_fields += ("occurred_at",)
            for key in time_fields:
                if key not in supplied["payload"] and hasattr(old, key):
                    original_time = getattr(old, key)
                    supplied["payload"][key] = utc(original_time) if original_time else None
        record = TypeAdapter(MemoryRecord).validate_python(supplied)
        ref = self.memory._write_record(record.record_type, record.payload.model_dump(), "system")
        row = self._row(ref)
        if old is not None:
            # A representation migration must not make historical events look recent.
            row.created_at = old.created_at
            row.created_by = old.created_by
            if isinstance(row, Observation) and isinstance(old, Observation):
                row.recency_weight = old.recency_weight
        self.stats["created"] += 1
        return ref, row

    def _copy_evidence(self, old_ref, new_ref):
        old_type, old_id = old_ref.split(":", 1)
        new_type, new_id = new_ref.split(":", 1)
        model, key = EVIDENCE[old_type]
        target_model, target_key = EVIDENCE[new_type]
        rows = list(self.session.scalars(select(model).where(getattr(model, key) == old_id)))
        for row in rows:
            self.session.add(target_model(**{
                target_key: new_id, "episode_id": row.episode_id,
                "excerpt": row.excerpt, "confidence": row.confidence,
                "created_at": row.created_at,
            }))
        self.stats["evidence_copied"] += len(rows)
        return rows[0].episode_id if rows else None

    def run(self, manifest: dict, *, apply: bool = False) -> dict:
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported migration manifest version.")
        plan_id = manifest["plan_id"]
        if not isinstance(plan_id, str) or not 1 <= len(plan_id) <= 80:
            raise ValueError("Invalid migration plan ID.")
        fingerprint = digest(manifest)
        root_key = f"migration:{plan_id}"
        try:
            previous = self.session.scalar(select(MemoryChange).where(MemoryChange.request_id == root_key))
            if previous:
                if previous.request_sha256 != fingerprint:
                    raise ValueError("Migration ID has different content.")
                self.session.rollback()
                return {"status": "already_applied", "manifest_sha256": fingerprint}
            for table_name, expected in manifest.get("snapshot", {}).items():
                if table_name not in {"entities", "entity_aliases", "entity_facts", "entity_edges",
                                     "observations", "observation_entities", "episodes",
                                     "entity_fact_evidence", "edge_evidence", "observation_evidence",
                                     "candidates", "candidate_evidence", "material_imports"}:
                    raise ValueError("Unsupported snapshot table.")
                table = Base.metadata.tables[table_name]
                if self.session.bind.dialect.name == "postgresql":
                    self.session.execute(text(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE"))
                columns = [table.c[name] for name in expected["columns"]]
                rows = [dict(row) for row in self.session.execute(select(*columns).order_by(table.c.id)).mappings()]
                if len(rows) != expected["count"] or snapshot_digest(rows, table) != expected["sha256"]:
                    raise ValueError(f"Migration snapshot changed: {table_name}")
            # Serialize attempts of this exact plan before changing any records.
            self._receipt(root_key, fingerprint, None, None, "Schema data conversion receipt")
            self.session.flush()
            for index, item in enumerate(manifest.get("replacements", [])):
                old_ref = item["old_record_ref"]
                old = self._row(old_ref)
                self._guard(old, item["expected"])
                if old.status != "active" or not item["records"]:
                    raise ValueError("Only active records can be split into nonempty replacements.")
                for ordinal, spec in enumerate(item["records"]):
                    new_ref, new = self._new_record(spec, old)
                    episode_id = self._copy_evidence(old_ref, new_ref)
                    if (isinstance(old, Observation) and isinstance(new, Observation)
                            and "related_entities" not in spec["payload"]):
                        existing = {(r.entity_id, r.role) for r in self.session.scalars(
                            select(ObservationEntity).where(ObservationEntity.observation_id == new.id)
                        )}
                        for link in self.session.scalars(select(ObservationEntity).where(
                            ObservationEntity.observation_id == old.id
                        )):
                            if (link.entity_id, link.role) not in existing:
                                self.session.add(ObservationEntity(
                                    observation_id=new.id, entity_id=link.entity_id,
                                    role=link.role, confidence=link.confidence, created_at=link.created_at,
                                ))
                    self._receipt(f"{root_key}:replace:{index}:{ordinal}", digest(spec),
                                  old_ref, new_ref, item["reason"], episode_id)
                old.status = "superseded"
                self.stats["replaced"] += 1
            for index, item in enumerate(manifest.get("metadata", [])):
                row = self._row(item["record_ref"])
                self._guard(row, item["expected"])
                basis = item.get("claim_basis")
                if basis not in {"reported", "inferred", "unknown"}:
                    raise ValueError("Invalid migration evidence basis.")
                row.claim_basis = basis
                if isinstance(row, Observation):
                    for link in item.get("related_entities", []):
                        exists = self.session.scalar(select(ObservationEntity).where(
                            ObservationEntity.observation_id == row.id,
                            ObservationEntity.entity_id == link["entity_id"],
                            ObservationEntity.role == link["role"],
                        ))
                        if not exists:
                            if link["role"] not in {"speaker", "experiencer", "subject", "related", "target", "mentioned", "about"}:
                                raise ValueError("Invalid participant role.")
                            self._row("entities:" + link["entity_id"])
                            self.session.add(ObservationEntity(observation_id=row.id, **link))
                self._receipt(f"{root_key}:metadata:{index}", digest(item), item["record_ref"],
                              item["record_ref"], item["reason"])
                self.stats["metadata_updated"] += 1
            resolved = {}
            for index, item in enumerate(manifest.get("candidates", [])):
                candidate = self._row("candidates:" + item["candidate_id"])
                self._guard(candidate, item["expected"])
                if candidate.status not in {"pending", "needs_clarification"}:
                    raise ValueError("Candidate already resolved.")
                if sorted(e.episode_id for e in candidate.evidence) != sorted(item["episode_ids"]):
                    raise ValueError("Candidate evidence changed.")
                new_ref = None
                if "record" in item:
                    new_ref, row = self._new_record(item["record"], candidate)
                    row.source_candidate_id = candidate.id
                    model, key = EVIDENCE[item["record"]["record_type"]]
                    for ev in candidate.evidence:
                        self.session.add(model(**{key: row.id, "episode_id": ev.episode_id,
                                                  "excerpt": ev.excerpt, "confidence": ev.confidence}))
                        self.stats["evidence_copied"] += 1
                elif "new_person" in item:
                    row = EntityService(self.session).create_entity({
                        "entity_type": "person", "display_name": item["new_person"],
                        "created_by": "system", "properties": {"source": "save_first_migration"},
                    }, commit=False)
                    row.created_at = candidate.created_at
                    new_ref = "entities:" + row.id
                elif "link_existing" in item:
                    new_ref = item["link_existing"]
                    target = self._row(new_ref)
                    target_type, target_id = new_ref.split(":", 1)
                    if target_type in EVIDENCE:
                        evidence_model, evidence_key = EVIDENCE[target_type]
                        for ev in candidate.evidence:
                            exists = self.session.scalar(select(evidence_model).where(
                                getattr(evidence_model, evidence_key) == target_id,
                                evidence_model.episode_id == ev.episode_id,
                            ))
                            if not exists:
                                self.session.add(evidence_model(**{
                                    evidence_key: target_id, "episode_id": ev.episode_id,
                                    "excerpt": ev.excerpt, "confidence": ev.confidence,
                                }))
                                self.stats["evidence_copied"] += 1
                        if item.get("claim_basis") is not None:
                            if item["claim_basis"] not in {"reported", "inferred", "unknown"}:
                                raise ValueError("Invalid linked memory basis.")
                            target.claim_basis = item["claim_basis"]
                elif "link_candidate" in item:
                    new_ref = resolved[item["link_candidate"]]
                elif item.get("archive") is not True:
                    raise ValueError("Candidate has no conversion decision.")
                candidate.status = "accepted" if new_ref else "archived"
                candidate.canonical_record_ref = new_ref
                candidate.resolved_at = now_utc()
                candidate.resolved_by = "system"
                candidate.resolution_note = item["reason"]
                resolved[candidate.id] = new_ref
                self._receipt(f"{root_key}:candidate:{index}", digest(item),
                              "candidates:" + candidate.id, new_ref, item["reason"],
                              candidate.evidence[0].episode_id if candidate.evidence else None)
                self.stats["candidates_resolved"] += 1
            for index, item in enumerate(manifest.get("entities", [])):
                row = self._row("entities:" + item["entity_id"])
                self._guard(row, item["expected"])
                properties = deepcopy(row.properties)
                properties.pop("needs_identity_review", None)
                row.properties = properties
                self._receipt(f"{root_key}:entity:{index}", digest(item), "entities:" + row.id,
                              "entities:" + row.id, "Retired needs_identity_review approval metadata")
                self.stats["entities_cleaned"] += 1
            self.session.flush()
            result = {"status": "applied" if apply else "dry_run", "manifest_sha256": fingerprint,
                      **self.stats}
            if apply:
                self.session.commit()
            else:
                self.session.rollback()
            return result
        except Exception:
            self.session.rollback()
            raise
