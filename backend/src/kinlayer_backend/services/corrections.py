"""Compatibility adapter for explicit conversational corrections."""

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any

from pydantic import ValidationError

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.schemas.corrections import CorrectionApplyRequest
from kinlayer_backend.schemas.memories import MemoryWriteRequest
from kinlayer_backend.services.memories import MemoryService


class CorrectionService(MemoryService):
    def apply_correction(self, payload: dict[str, Any]) -> dict[str, Any]:
        legacy = CorrectionApplyRequest.model_validate(payload)
        source = legacy.correction_source
        if not source.user_explicit or source.source_actor != "user":
            raise api_error(422, "validation_error", "Correction requires an explicit user source.")
        record = deepcopy(legacy.new_record.model_dump()) if legacy.new_record else None
        if record is not None:
            self._upgrade_legacy_payload(record)
        request_id = legacy.request_id
        if request_id is None:
            raw = json.dumps(
                legacy.model_dump(mode="json", exclude={"request_id"}),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            request_id = "legacy-correction:" + sha256(raw.encode()).hexdigest()
        try:
            body = MemoryWriteRequest.model_validate(
                {
                    "request_id": request_id,
                    "action": legacy.action,
                    "old_record_ref": legacy.old_record_ref,
                    "record": record,
                    "source": {
                        "source_type": source.source_type,
                        "actor": source.source_actor,
                        "source_ref": source.source_ref,
                        "excerpt": source.excerpt,
                        "occurred_at": source.occurred_at,
                    },
                    "created_by": legacy.created_by,
                    "reason": legacy.reason,
                    "expected_updated_at": legacy.expected_updated_at,
                }
            )
        except ValidationError as exc:
            raise api_error(
                422, "validation_error", "Invalid correction record or source."
            ) from exc
        result = self.write(body)
        return {
            "old_record_ref": result["old_record_ref"],
            "new_record_ref": result["new_record_ref"],
            "episode_id": result["source_episode_id"],
            "source_actor": source.source_actor,
            "submitted_by": legacy.created_by,
            "change_id": result["change_id"],
            "action": result["action"],
        }

    @staticmethod
    def _upgrade_legacy_payload(record: dict[str, Any]) -> None:
        payload = record["payload"]
        claim_type = payload.pop("claim_type", None)
        payload.setdefault(
            "claim_basis", {"fact": "reported", "inference": "inferred"}.get(claim_type, "unknown")
        )
        # Preserve the old endpoint's omitted-confidence default only for legacy clients.
        payload.setdefault("confidence", 1.0)
        for key in (
            "ai_use_policy",
            "sensitivity",
            "confirmation_status",
            "status",
            "created_by",
            "source_candidate_id",
        ):
            payload.pop(key, None)
        if record["record_type"] == "observations":
            related_ids = payload.pop("related_entity_ids", [])
            payload.setdefault(
                "related_entities",
                [{"entity_id": value, "role": "related"} for value in related_ids],
            )
        if record["record_type"] == "entity_facts" and not payload.get("value"):
            content = payload.get("content")
            if isinstance(content, str):
                payload["value"] = (
                    _date_value(content)
                    if payload.get("fact_type") in {"birth_date", "birthday"}
                    else {"text": content}
                )


def _date_value(content: str) -> dict:
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", content.strip())
    if match:
        result = {
            name: int(value)
            for name, value in zip(("year", "month", "day"), match.groups())
            if value is not None
        }
        result["precision"] = "day" if "day" in result else "month" if "month" in result else "year"
        return result
    match = re.fullmatch(r"--(\d{2})-(\d{2})", content.strip())
    if match:
        return {"month": int(match[1]), "day": int(match[2]), "precision": "day"}
    return {}
