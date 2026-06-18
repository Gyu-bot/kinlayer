from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import AllowedEdgeType, Entity, Episode, OntologyRegistryValue
from kinlayer_backend.schemas.candidates import CandidateCreate
from kinlayer_backend.schemas.corrections import CorrectionApplyRequest
from kinlayer_backend.services.corrections import CorrectionService
from kinlayer_backend.services.entities import validate_common
from kinlayer_backend.services.ontology import is_allowed_registry_value

SUGGESTED_ACTIONS = {"review", "accept", "reject", "clarify"}
CORRECTION_RECORD_TYPES = {"entity_edges", "entity_facts", "observations"}


def _registry_key(value: str) -> str:
    return "_".join(value.strip().casefold().replace("-", " ").split())


class AgentWriteFilter:
    def __init__(self, session: Session):
        self.session = session
        self.normalizations: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.controlled_values_checked: list[str] = []
        self.diagnostics: dict[str, Any] = {}

    def validate(self, write_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        state = self._reset_state()
        validated_payload = deepcopy(payload)
        try:
            if write_type == "candidate":
                self._validate_candidate(validated_payload)
            elif write_type == "correction":
                self._validate_correction(validated_payload)
            else:
                self._add_error("unsupported_write_type", "Unsupported write_type.", "write_type")
        except ValidationError as exc:
            self._add_error(
                "schema_validation_failed",
                "Payload does not match the expected schema.",
                details={"errors": exc.errors()},
            )
        state.update(
            {
                "accepted": not self.errors,
                "validated_payload": validated_payload,
                "normalizations_applied": self.normalizations,
                "warnings": self.warnings,
                "errors": self.errors,
                "diagnostics": self.diagnostics,
                "controlled_values_checked": self.controlled_values_checked,
                "audit_ref": None,
            }
        )
        return state

    def enforce(self, write_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.validate(write_type, payload)
        if result["accepted"]:
            return result["validated_payload"]
        raise api_error(
            422,
            "validation_error",
            "Agent write validation failed.",
            {
                "errors": result["errors"],
                "warnings": result["warnings"],
                "diagnostics": result["diagnostics"],
                "normalizations_applied": result["normalizations_applied"],
                "controlled_values_checked": result["controlled_values_checked"],
            },
        )

    def _reset_state(self) -> dict[str, Any]:
        self.normalizations = []
        self.errors = []
        self.warnings = []
        self.controlled_values_checked = []
        self.diagnostics = {}
        return {}

    def _validate_candidate(self, payload: dict[str, Any]) -> None:
        candidate = CandidateCreate.model_validate(payload)
        payload.clear()
        payload.update(candidate.model_dump())
        self._check_registry("candidate_type", payload["candidate_type"], "candidate_type")
        self._check_registry("sensitivity", payload.get("sensitivity", "medium"), "sensitivity")
        suggested_action = payload.get("suggested_action")
        if suggested_action and suggested_action not in SUGGESTED_ACTIONS:
            self._add_error("controlled_value_mismatch", "Invalid suggested_action.", "suggested_action")
        target_entity_id = payload.get("target_entity_id")
        if target_entity_id:
            self._entity(target_entity_id, "target_entity_id")
        if payload.get("created_by") == "ai_agent":
            self._validate_candidate_evidence(payload.get("evidence", []))
        self._validate_candidate_payload(payload)

    def _validate_candidate_payload(self, candidate: dict[str, Any]) -> None:
        candidate_type = candidate["candidate_type"]
        payload = candidate["payload"]
        if candidate_type == "relationship_edge":
            self._validate_edge_payload(payload, "payload.relation_type")
        elif candidate_type == "observation":
            self._entity(payload["subject_entity_id"], "payload.subject_entity_id")
            self._check_registry(
                "observation_type",
                payload["observation_type"],
                "payload.observation_type",
            )
            self._check_registry("claim_type", payload["claim_type"], "payload.claim_type")
            self._check_registry("sensitivity", payload.get("sensitivity", "medium"), "payload.sensitivity")
            self._check_registry(
                "ai_use_policy",
                payload.get("ai_use_policy", "cautious_use"),
                "payload.ai_use_policy",
            )
            for index, entity_id in enumerate(payload.get("related_entity_ids", [])):
                self._entity(entity_id, f"payload.related_entity_ids.{index}")
        elif candidate_type == "profile_field":
            self._entity(payload["entity_id"], "payload.entity_id")
            fact_type = payload.get("fact_type")
            if fact_type:
                normalized = self._normalize_controlled_value("fact_type", fact_type, "payload.fact_type")
                if normalized:
                    payload["fact_type"] = normalized
            self._check_registry("claim_type", payload["claim_type"], "payload.claim_type")
        elif candidate_type == "alias":
            self._entity(payload["entity_id"], "payload.entity_id")
        elif candidate_type == "new_entity":
            validate_common(payload, self.session)
            self._check_registry("entity_type", payload["entity_type"], "payload.entity_type")
            self._check_registry(
                "ai_use_policy",
                payload.get("ai_use_policy", "cautious_use"),
                "payload.ai_use_policy",
            )
            self._check_registry("sensitivity", payload.get("sensitivity", "medium"), "payload.sensitivity")
        elif candidate_type == "merge":
            source = self._entity(payload["source_entity_id"], "payload.source_entity_id")
            target = self._entity(payload["target_entity_id"], "payload.target_entity_id")
            if source and target and source.id == target.id:
                self._add_error(
                    "invalid_merge_target",
                    "Merge source and target must differ.",
                    "payload.target_entity_id",
                )
        elif candidate_type == "conflict":
            for index, record_ref in enumerate(payload["record_refs"]):
                self._validate_record_ref(record_ref, f"payload.record_refs.{index}")
        elif candidate_type == "supersede":
            self._validate_record_ref(payload["old_record_ref"], "payload.old_record_ref")

    def _validate_correction(self, payload: dict[str, Any]) -> None:
        correction = CorrectionApplyRequest.model_validate(payload)
        payload.clear()
        payload.update(correction.model_dump())
        if payload.get("created_by") != "ai_agent":
            return
        source = payload["correction_source"]
        if source.get("user_explicit") is not True:
            self._add_error(
                "explicit_user_correction_required",
                "Direct correction apply requires explicit user correction.",
                "correction_source.user_explicit",
            )
        if not source.get("excerpt") or not source["excerpt"].strip():
            self._add_error(
                "evidence_excerpt_required",
                "Correction evidence excerpt is required.",
                "correction_source.excerpt",
            )
        self._validate_record_ref(payload["old_record_ref"], "old_record_ref")
        new_record = payload["new_record"]
        if new_record["record_type"] not in CORRECTION_RECORD_TYPES:
            self._add_error("unsupported_record_type", "Unsupported new record type.", "new_record.record_type")
            return
        if new_record["record_type"] == "entity_edges":
            self._validate_edge_payload(new_record["payload"], "new_record.payload.relation_type")

    def _validate_edge_payload(self, payload: dict[str, Any], relation_field: str) -> None:
        from_entity = self._entity(payload["from_entity_id"], relation_field.rsplit(".", 1)[0] + ".from_entity_id")
        to_entity = self._entity(payload["to_entity_id"], relation_field.rsplit(".", 1)[0] + ".to_entity_id")
        normalized = self._normalize_edge_type(payload["relation_type"], relation_field)
        if not normalized:
            return
        payload["relation_type"] = normalized
        edge_type = self.session.execute(
            select(AllowedEdgeType).where(
                AllowedEdgeType.relation_type == normalized,
                AllowedEdgeType.active.is_(True),
            )
        ).scalar_one_or_none()
        if not edge_type:
            self._add_relation_type_error(payload["relation_type"], relation_field)
            return
        if (
            from_entity
            and to_entity
            and (
                from_entity.entity_type != edge_type.from_entity_type
                or to_entity.entity_type != edge_type.to_entity_type
            )
        ):
            self._add_error(
                "endpoint_type_mismatch",
                "Relation endpoint entity types do not match.",
                relation_field,
                {
                    "from_entity_type": from_entity.entity_type,
                    "to_entity_type": to_entity.entity_type,
                    "expected_from_entity_type": edge_type.from_entity_type,
                    "expected_to_entity_type": edge_type.to_entity_type,
                },
            )
        self._check_registry("claim_type", payload["claim_type"], relation_field.rsplit(".", 1)[0] + ".claim_type")

    def _normalize_edge_type(self, value: str, field: str) -> str | None:
        normalized = self._normalize_controlled_value("edge_type", value, field)
        if normalized:
            return normalized
        self._add_relation_type_error(value, field)
        return None

    def _normalize_controlled_value(self, category: str, value: str, field: str) -> str | None:
        self._mark_checked(field)
        rows = self.session.execute(
            select(OntologyRegistryValue).where(
                OntologyRegistryValue.category == category,
                OntologyRegistryValue.is_active.is_(True),
            )
        ).scalars()
        if any(row.value == value for row in rows):
            return value
        rows = list(
            self.session.execute(
                select(OntologyRegistryValue).where(
                    OntologyRegistryValue.category == category,
                    OntologyRegistryValue.is_active.is_(True),
                )
            ).scalars()
        )
        target = _registry_key(value)
        matches = [
            row.value
            for row in rows
            if target in {_registry_key(row.value), _registry_key(row.label or "")}
        ]
        unique = sorted(set(matches))
        if len(unique) == 1:
            normalized = unique[0]
            if normalized != value:
                self.normalizations.append(
                    {
                        "field": field,
                        "original": value,
                        "normalized": normalized,
                        "category": category,
                    }
                )
            return normalized
        if len(unique) > 1:
            self._add_error(
                "ambiguous_controlled_value",
                "Controlled value matches multiple registry values.",
                field,
                {"matches": unique},
            )
        return None

    def _check_registry(self, category: str, value: str, field: str) -> None:
        self._mark_checked(field)
        if not is_allowed_registry_value(self.session, category, value):
            self._add_error(
                "controlled_value_mismatch",
                f"Invalid {category}.",
                field,
                {"category": category, "value": value},
            )

    def _validate_candidate_evidence(self, evidence: list[dict[str, Any]]) -> None:
        if not evidence:
            self._add_error("evidence_required", "Agent-submitted candidates require evidence.", "evidence")
            return
        for index, item in enumerate(evidence):
            episode = self.session.get(Episode, item["episode_id"])
            if not episode:
                self._add_error("evidence_episode_not_found", "Evidence episode not found.", f"evidence.{index}")
                continue
            if not item.get("excerpt") or not item["excerpt"].strip():
                self._add_error(
                    "evidence_excerpt_required",
                    "Agent evidence excerpt is required.",
                    f"evidence.{index}.excerpt",
                )
            if not episode.source_ref:
                self._add_error(
                    "evidence_source_ref_required",
                    "Agent evidence source_ref is required.",
                    f"evidence.{index}.episode_id",
                )
            if not episode.body_hash or not episode.actor:
                self._add_error(
                    "evidence_provenance_incomplete",
                    "Agent evidence provenance is incomplete.",
                    f"evidence.{index}.episode_id",
                )
            self._check_registry("evidence_source_type", episode.source_type, f"evidence.{index}.source_type")

    def _validate_record_ref(self, record_ref: str, field: str) -> None:
        try:
            prefix, record_id = CorrectionService(self.session)._parse_record_ref(record_ref)
            CorrectionService(self.session)._get_record(prefix, record_id)
        except Exception:
            self._add_error("invalid_record_ref", "Record reference cannot be resolved.", field)

    def _entity(self, entity_id: str, field: str) -> Entity | None:
        entity = self.session.get(Entity, entity_id)
        if not entity:
            self._add_error("entity_not_found", "Entity not found.", field)
            return None
        return entity

    def _add_relation_type_error(self, value: str, field: str) -> None:
        allowed = self._allowed_edge_types()
        self.diagnostics["allowed_edge_types"] = allowed
        self._add_error(
            "relation_type_not_allowed",
            "relation_type must be an active ontology edge type.",
            field,
            {"submitted_relation_type": value, "allowed_edge_types": allowed},
        )

    def _allowed_edge_types(self) -> list[str]:
        return list(
            self.session.execute(
                select(AllowedEdgeType.relation_type)
                .where(AllowedEdgeType.active.is_(True))
                .order_by(AllowedEdgeType.relation_type)
            ).scalars()
        )

    def _mark_checked(self, field: str) -> None:
        if field not in self.controlled_values_checked:
            self.controlled_values_checked.append(field)

    def _add_error(
        self,
        code: str,
        message: str,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.errors.append(
            {
                "code": code,
                "message": message,
                "field": field,
                "details": details or {},
            }
        )
