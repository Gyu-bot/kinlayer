from __future__ import annotations

from datetime import datetime
from typing import Any

from kinlayer_backend.schemas.common import APIModel, ListResponse


class AgentWriteOperationRead(APIModel):
    id: str
    operation_type: str
    source_path: str
    actor: str
    result_status: str
    api_error_code: str | None = None
    request_summary: dict[str, Any]
    diagnostics: dict[str, Any]
    related_refs: dict[str, Any]
    candidate_id: str | None = None
    correction_id: str | None = None
    episode_id: str | None = None
    canonical_record_ref: str | None = None
    bounded_excerpt: str | None = None
    created_at: datetime
    updated_at: datetime


AgentWriteOperationList = ListResponse[AgentWriteOperationRead]
