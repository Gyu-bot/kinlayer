from datetime import datetime
from typing import Any

from kinlayer_backend.schemas.common import APIModel


class CorrectionSource(APIModel):
    source_type: str
    source_actor: str = "user"
    user_explicit: bool
    excerpt: str
    source_ref: str | None = None
    occurred_at: datetime | None = None


class CorrectionNewRecord(APIModel):
    record_type: str
    payload: dict[str, Any]


class CorrectionApplyRequest(APIModel):
    old_record_ref: str
    new_record: CorrectionNewRecord
    correction_source: CorrectionSource
    created_by: str = "ai_agent"


class CorrectionApplyResponse(APIModel):
    old_record_ref: str
    new_record_ref: str
    episode_id: str
    source_actor: str
    submitted_by: str
