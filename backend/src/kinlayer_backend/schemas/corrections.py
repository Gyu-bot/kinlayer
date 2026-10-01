from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from kinlayer_backend.schemas.common import APIModel


class CorrectionSource(APIModel):
    source_type: str
    source_actor: str = "user"
    user_explicit: bool
    excerpt: str = Field(min_length=1, max_length=4000)
    source_ref: str | None = Field(default=None, max_length=500)
    occurred_at: datetime | None = None


class CorrectionNewRecord(APIModel):
    record_type: str
    payload: dict[str, Any]


class CorrectionApplyRequest(APIModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=160)
    action: Literal["correct", "retract", "reattribute"] = "correct"
    old_record_ref: str
    new_record: CorrectionNewRecord | None = None
    correction_source: CorrectionSource
    created_by: str = "ai_agent"
    reason: str | None = Field(default=None, max_length=1000)
    expected_updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "retract" and self.new_record is not None:
            raise ValueError("Retraction cannot contain a replacement record.")
        if self.action != "retract" and self.new_record is None:
            raise ValueError("Correction and reattribution require a replacement record.")
        return self


class CorrectionApplyResponse(APIModel):
    old_record_ref: str
    new_record_ref: str | None
    episode_id: str
    source_actor: str
    submitted_by: str
    change_id: str
    action: str
