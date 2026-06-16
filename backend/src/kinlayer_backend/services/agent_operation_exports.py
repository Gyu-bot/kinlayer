from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from kinlayer_backend.models import AgentWriteOperationAudit, AllowedEdgeType, Candidate, Entity

SCHEMA_VERSION = "agent_write_operations.v1"
EXPORT_SCOPE = "agent_write_operations_only"
MAX_EXCERPT_CHARS = 500


def _bounded_text(value: str | None, limit: int = MAX_EXCERPT_CHARS) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _error_details(exc: HTTPException) -> tuple[str | None, dict[str, Any]]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    error = detail.get("error", {}) if isinstance(detail, dict) else {}
    code = error.get("code")
    diagnostics = {
        "message": error.get("message", str(exc.detail)),
        "details": error.get("details", {}),
        "http_status": exc.status_code,
    }
    return code, diagnostics


def _candidate_summary(payload: dict[str, Any]) -> dict[str, Any]:
    candidate_payload = payload.get("payload") or {}
    summary: dict[str, Any] = {
        "candidate_type": payload.get("candidate_type"),
        "target_entity_id": payload.get("target_entity_id"),
        "suggested_action": payload.get("suggested_action"),
        "confidence": payload.get("confidence"),
        "sensitivity": payload.get("sensitivity"),
    }
    for key in [
        "entity_id",
        "subject_entity_id",
        "from_entity_id",
        "to_entity_id",
        "relation_type",
        "observation_type",
        "fact_type",
        "claim_type",
    ]:
        if key in candidate_payload:
            summary[key] = candidate_payload[key]
    content = candidate_payload.get("content") or candidate_payload.get("claim_text")
    if content:
        summary["content_excerpt"] = _bounded_text(str(content))
    return {key: value for key, value in summary.items() if value is not None}


def _correction_summary(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("correction_source") or {}
    new_record = payload.get("new_record") or {}
    new_payload = new_record.get("payload") or {}
    summary = {
        "old_record_ref": payload.get("old_record_ref"),
        "new_record_type": new_record.get("record_type"),
        "source_type": source.get("source_type"),
        "user_explicit": source.get("user_explicit"),
        "source_ref": source.get("source_ref"),
    }
    for key in ["from_entity_id", "to_entity_id", "relation_type"]:
        if key in new_payload:
            summary[key] = new_payload[key]
    return summary


def _edge_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "from_entity_id": payload.get("from_entity_id"),
        "to_entity_id": payload.get("to_entity_id"),
        "relation_type": payload.get("relation_type"),
        "claim_type": payload.get("claim_type"),
        "confidence": payload.get("confidence"),
        "sensitivity": payload.get("sensitivity"),
        "ai_use_policy": payload.get("ai_use_policy"),
    }
    claim_text = payload.get("claim_text")
    if claim_text:
        summary["claim_text_excerpt"] = _bounded_text(str(claim_text))
    return {key: value for key, value in summary.items() if value is not None}


def _first_evidence(candidate: Candidate) -> tuple[str | None, str | None]:
    evidence = candidate.evidence[0] if candidate.evidence else None
    if not evidence:
        return None, None
    return evidence.episode_id, _bounded_text(evidence.excerpt)


class AgentOperationService:
    def __init__(self, session: Session):
        self.session = session

    def record_candidate_submit_success(self, candidate: Candidate, source_path: str) -> None:
        if candidate.created_by != "ai_agent":
            return
        episode_id, excerpt = _first_evidence(candidate)
        self._record(
            operation_type="candidate_submit",
            source_path=source_path,
            actor=candidate.created_by,
            result_status="success",
            request_summary=_candidate_summary(
                {
                    "candidate_type": candidate.candidate_type,
                    "target_entity_id": candidate.target_entity_id,
                    "payload": candidate.payload,
                    "confidence": float(candidate.confidence),
                    "sensitivity": candidate.sensitivity,
                    "suggested_action": candidate.suggested_action,
                }
            ),
            candidate_id=candidate.id,
            episode_id=episode_id,
            bounded_excerpt=excerpt,
        )

    def record_candidate_submit_failure(
        self,
        payload: dict[str, Any],
        source_path: str,
        exc: HTTPException,
    ) -> None:
        if payload.get("created_by") != "ai_agent":
            return
        code, diagnostics = _error_details(exc)
        self._record(
            operation_type="candidate_submit",
            source_path=source_path,
            actor=payload["created_by"],
            result_status="rejected",
            api_error_code=code,
            request_summary=_candidate_summary(payload),
            diagnostics=diagnostics,
        )

    def record_candidate_action(self, candidate: Candidate, operation_type: str, source_path: str) -> None:
        if candidate.created_by != "ai_agent":
            return
        episode_id, excerpt = _first_evidence(candidate)
        self._record(
            operation_type=operation_type,
            source_path=source_path,
            actor=candidate.created_by,
            result_status="success",
            request_summary=_candidate_summary(
                {
                    "candidate_type": candidate.candidate_type,
                    "target_entity_id": candidate.target_entity_id,
                    "payload": candidate.payload,
                    "confidence": float(candidate.confidence),
                    "sensitivity": candidate.sensitivity,
                    "suggested_action": candidate.suggested_action,
                }
            ),
            related_refs={
                "candidate_status": candidate.status,
                "resolved_by": candidate.resolved_by,
            },
            candidate_id=candidate.id,
            episode_id=episode_id,
            canonical_record_ref=candidate.canonical_record_ref,
            bounded_excerpt=excerpt,
        )

    def record_candidate_action_failure(
        self,
        candidate: Candidate,
        operation_type: str,
        source_path: str,
        exc: HTTPException,
    ) -> None:
        if candidate.created_by != "ai_agent":
            return
        code, diagnostics = _error_details(exc)
        self._record(
            operation_type=operation_type,
            source_path=source_path,
            actor=candidate.created_by,
            result_status="rejected",
            api_error_code=code,
            request_summary=_candidate_summary(
                {
                    "candidate_type": candidate.candidate_type,
                    "target_entity_id": candidate.target_entity_id,
                    "payload": candidate.payload,
                    "confidence": float(candidate.confidence),
                    "sensitivity": candidate.sensitivity,
                    "suggested_action": candidate.suggested_action,
                }
            ),
            diagnostics=diagnostics,
            candidate_id=candidate.id,
        )

    def record_correction_success(
        self,
        payload: dict[str, Any],
        result: dict[str, str],
        source_path: str,
    ) -> None:
        if payload.get("created_by") != "ai_agent":
            return
        self._record(
            operation_type="correction_apply",
            source_path=source_path,
            actor=payload["created_by"],
            result_status="success",
            request_summary=_correction_summary(payload),
            related_refs={
                "old_record_ref": result["old_record_ref"],
                "new_record_ref": result["new_record_ref"],
            },
            episode_id=result["episode_id"],
            canonical_record_ref=result["new_record_ref"],
            bounded_excerpt=_bounded_text(payload.get("correction_source", {}).get("excerpt")),
        )

    def record_correction_failure(
        self,
        payload: dict[str, Any],
        source_path: str,
        exc: HTTPException,
    ) -> None:
        if payload.get("created_by") != "ai_agent":
            return
        code, diagnostics = _error_details(exc)
        self._record(
            operation_type="correction_apply",
            source_path=source_path,
            actor=payload["created_by"],
            result_status="rejected",
            api_error_code=code,
            request_summary=_correction_summary(payload),
            diagnostics=diagnostics,
            bounded_excerpt=_bounded_text(payload.get("correction_source", {}).get("excerpt")),
        )

    def record_edge_success(
        self,
        payload: dict[str, Any],
        *,
        edge_id: str,
        operation_type: str,
        source_path: str,
    ) -> None:
        actor = payload.get("created_by") or "api_user"
        self._record(
            operation_type=operation_type,
            source_path=source_path,
            actor=actor,
            result_status="success",
            request_summary=_edge_summary(payload),
            related_refs=self._edge_related_refs(payload, edge_id=edge_id),
            canonical_record_ref=f"entity_edges:{edge_id}",
        )

    def record_edge_failure(
        self,
        payload: dict[str, Any],
        *,
        operation_type: str,
        source_path: str,
        exc: HTTPException,
        edge_id: str | None = None,
    ) -> None:
        actor = payload.get("created_by") or "api_user"
        code, diagnostics = _error_details(exc)
        self._record(
            operation_type=operation_type,
            source_path=source_path,
            actor=actor,
            result_status="rejected",
            api_error_code=code,
            request_summary=_edge_summary(payload),
            diagnostics=diagnostics,
            related_refs=self._edge_related_refs(payload, edge_id=edge_id),
            canonical_record_ref=f"entity_edges:{edge_id}" if edge_id else None,
        )

    def list_operations(
        self,
        *,
        actor: str | None = None,
        source_path: str | None = None,
        operation_type: str | None = None,
        result_status: str | None = None,
        has_error: bool | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AgentWriteOperationAudit], int]:
        statement = self._filtered_statement(
            actor=actor,
            source_path=source_path,
            operation_type=operation_type,
            result_status=result_status,
            has_error=has_error,
            created_from=created_from,
            created_to=created_to,
        )
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = (
            self.session.execute(statement.limit(limit).offset(offset)).scalars().unique().all()
        )
        return items, total

    def export_jsonl(
        self,
        *,
        actor: str | None = None,
        source_path: str | None = None,
        operation_type: str | None = None,
        result_status: str | None = None,
        has_error: bool | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> str:
        items, total = self.list_operations(
            actor=actor,
            source_path=source_path,
            operation_type=operation_type,
            result_status=result_status,
            has_error=has_error,
            created_from=created_from,
            created_to=created_to,
            limit=limit,
            offset=offset,
        )
        filters = {
            "actor": actor,
            "source_path": source_path,
            "operation_type": operation_type,
            "result_status": result_status,
            "has_error": has_error,
            "created_from": created_from.isoformat() if created_from else None,
            "created_to": created_to.isoformat() if created_to else None,
            "limit": limit,
            "offset": offset,
        }
        manifest = {
            "record_type": "manifest",
            "schema_version": SCHEMA_VERSION,
            "scope": EXPORT_SCOPE,
            "exported_at": datetime.now(UTC).isoformat(),
            "filters": {key: value for key, value in filters.items() if value is not None},
            "total_matching": total,
            "record_count": len(items),
        }
        lines = [manifest]
        lines.extend(self._export_record(item) for item in items)
        return "\n".join(json.dumps(line, ensure_ascii=False, sort_keys=True) for line in lines) + "\n"

    def _record(
        self,
        *,
        operation_type: str,
        source_path: str,
        actor: str,
        result_status: str,
        api_error_code: str | None = None,
        request_summary: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
        related_refs: dict[str, Any] | None = None,
        candidate_id: str | None = None,
        correction_id: str | None = None,
        episode_id: str | None = None,
        canonical_record_ref: str | None = None,
        bounded_excerpt: str | None = None,
    ) -> AgentWriteOperationAudit:
        row = AgentWriteOperationAudit(
            operation_type=operation_type,
            source_path=source_path,
            actor=actor,
            result_status=result_status,
            api_error_code=api_error_code,
            request_summary=request_summary or {},
            diagnostics=diagnostics or {},
            related_refs=related_refs or {},
            candidate_id=candidate_id,
            correction_id=correction_id,
            episode_id=episode_id,
            canonical_record_ref=canonical_record_ref,
            bounded_excerpt=bounded_excerpt,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def _edge_related_refs(self, payload: dict[str, Any], *, edge_id: str | None = None) -> dict[str, Any]:
        refs: dict[str, Any] = {}
        if edge_id:
            refs["edge_id"] = edge_id
        from_entity_id = payload.get("from_entity_id")
        to_entity_id = payload.get("to_entity_id")
        relation_type = payload.get("relation_type")
        if from_entity_id:
            refs["from_entity_id"] = from_entity_id
        if to_entity_id:
            refs["to_entity_id"] = to_entity_id
        if relation_type:
            refs["relation_type"] = relation_type
        from_type = self._entity_type(from_entity_id)
        to_type = self._entity_type(to_entity_id)
        if from_type:
            refs["from_entity_type"] = from_type
        if to_type:
            refs["to_entity_type"] = to_type
        refs["edge_type_match"] = self._edge_type_match(relation_type, from_type, to_type)
        return refs

    def _entity_type(self, entity_id: str | None) -> str | None:
        if not entity_id:
            return None
        entity = self.session.get(Entity, entity_id)
        return entity.entity_type if entity else None

    def _edge_type_match(
        self,
        relation_type: str | None,
        from_entity_type: str | None,
        to_entity_type: str | None,
    ) -> str:
        if not relation_type:
            return "not_submitted"
        edge_type = self.session.execute(
            select(AllowedEdgeType).where(
                AllowedEdgeType.relation_type == relation_type,
                AllowedEdgeType.active.is_(True),
            )
        ).scalar_one_or_none()
        if not edge_type:
            return "missing_allowed_edge_type"
        if (
            from_entity_type
            and to_entity_type
            and (
                from_entity_type != edge_type.from_entity_type
                or to_entity_type != edge_type.to_entity_type
            )
        ):
            return "endpoint_type_mismatch"
        return "active_allowed_edge_type"

    def _filtered_statement(
        self,
        *,
        actor: str | None,
        source_path: str | None,
        operation_type: str | None,
        result_status: str | None,
        has_error: bool | None,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> Select:
        statement = select(AgentWriteOperationAudit)
        filters = []
        if actor:
            filters.append(AgentWriteOperationAudit.actor == actor)
        if source_path:
            filters.append(AgentWriteOperationAudit.source_path == source_path)
        if operation_type:
            filters.append(AgentWriteOperationAudit.operation_type == operation_type)
        if result_status:
            filters.append(AgentWriteOperationAudit.result_status == result_status)
        if has_error is True:
            filters.append(AgentWriteOperationAudit.api_error_code.is_not(None))
        elif has_error is False:
            filters.append(AgentWriteOperationAudit.api_error_code.is_(None))
        if created_from:
            filters.append(AgentWriteOperationAudit.created_at >= created_from)
        if created_to:
            filters.append(AgentWriteOperationAudit.created_at <= created_to)
        if filters:
            statement = statement.where(*filters)
        return statement.order_by(AgentWriteOperationAudit.created_at.desc())

    def _export_record(self, row: AgentWriteOperationAudit) -> dict[str, Any]:
        return {
            "record_type": "agent_write_operation",
            "schema_version": SCHEMA_VERSION,
            "audit_id": row.id,
            "operation_type": row.operation_type,
            "source_path": row.source_path,
            "actor": row.actor,
            "result_status": row.result_status,
            "api_error_code": row.api_error_code,
            "request_summary": row.request_summary,
            "diagnostics": row.diagnostics,
            "related_refs": row.related_refs,
            "candidate_id": row.candidate_id,
            "correction_id": row.correction_id,
            "episode_id": row.episode_id,
            "canonical_record_ref": row.canonical_record_ref,
            "bounded_excerpt": row.bounded_excerpt,
            "created_at": row.created_at.isoformat(),
        }
