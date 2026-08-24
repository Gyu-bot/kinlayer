from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.models import (
    Candidate,
    CurationDecision,
    CurationRun,
    Entity,
    EntityAlias,
    Observation,
    ObservationEntity,
    ObservationEvidence,
)
from kinlayer_backend.repositories.curation import CurationRepository
from kinlayer_backend.schemas.curation import (
    CurationDecisionStatus,
    CurationRunCreate,
    CurationRunStatus,
    CurationSourcePackRequest,
)
from kinlayer_backend.services.agent_write_filter import AgentWriteFilter
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.ontology import normalize_name

RUN_TRANSITIONS = {
    "pending": {"planning", "failed"},
    "planning": {"ready", "failed"},
    "ready": {"executing", "completed", "failed"},
    "executing": {"completed", "partial", "failed"},
    "partial": {"executing", "failed"},
    "failed": {"planning", "executing"},
    "completed": set(),
}
DECISION_TRANSITIONS = {
    "proposed": {"allowed", "blocked"},
    "allowed": {"executing", "blocked"},
    "executing": {"executed", "failed"},
    "failed": {"executing"},
    "blocked": set(),
    "executed": set(),
}
RUN_TERMINAL_STATUSES = {"completed", "partial", "failed"}
AUTO_ACTIONS = {
    "accept_existing",
    "edit_accept_existing",
    "consolidate_accept",
    "archive_exact_duplicate",
}
AUTO_OBSERVATION_TYPES = {
    "communication_preference",
    "relationship_pattern",
    "recent_interaction",
    "follow_up_context",
}
TEMPORAL_OBSERVATION_TYPES = {"recent_interaction", "follow_up_context"}
RESTRICTED_AI_USE_POLICIES = {"ask_before_use", "never_surface"}
HIGH_IMPACT_TERMS = {
    "self-harm",
    "suicide",
    "medical",
    "diagnosis",
    "legal",
    "lawsuit",
    "bank account",
    "credential",
    "password",
    "자해",
    "의료",
    "법률",
    "계좌",
    "비밀번호",
}
MAX_POLICY_EVIDENCE_EXCERPT_CHARS = 500
MAX_TARGET_ALIASES = 10
MAX_TARGET_OBSERVATIONS = 20


class CurationService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CurationRepository(session)

    def create_run(self, payload: CurationRunCreate) -> CurationRun:
        decision_payloads = []
        planner = payload.decisions[0].planner if payload.decisions else None
        for decision in payload.decisions:
            if self.repository.get_decision_by_idempotency_key(decision.idempotency_key):
                raise api_error(
                    409,
                    "duplicate_idempotency_key",
                    "Curation decision idempotency_key already exists.",
                )
            decision_payloads.append(decision.model_dump(exclude={"planner"}))
        run_payload = payload.model_dump(exclude={"decisions"})
        run_payload.update(
            status="pending",
            planned_decision_count=len(decision_payloads),
            planner_name=planner.name if planner else None,
            planner_model=planner.model if planner else None,
            planner_version=planner.version if planner else None,
        )
        try:
            run = self.repository.add_run(run_payload, decision_payloads)
            self.session.commit()
            return self.repository.get_run(run.id)
        except IntegrityError as exc:
            self.session.rollback()
            if self._is_idempotency_conflict(exc):
                raise api_error(
                    409,
                    "duplicate_idempotency_key",
                    "Curation decision idempotency_key already exists.",
                ) from exc
            raise

    def get_run(self, run_id: str) -> CurationRun | None:
        return self.repository.get_run(run_id)

    def list_runs(
        self,
        mode: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        return self.repository.list_runs(mode=mode, status=status, limit=limit, offset=offset)

    def build_source_pack(self, request: CurationSourcePackRequest) -> dict[str, Any]:
        cursor_at = request.cursor.created_at if request.cursor else None
        cursor_id = request.cursor.candidate_id if request.cursor else None
        rows = self.repository.pending_candidates(
            as_of=request.as_of,
            created_after=request.as_of - timedelta(days=request.max_age_days),
            cursor_at=cursor_at,
            cursor_id=cursor_id,
            limit=request.limit + 1,
        )
        has_more = len(rows) > request.limit
        candidates = rows[: request.limit]
        grouped: dict[str, list[Candidate]] = defaultdict(list)
        group_meta: dict[str, tuple[str | None, str | None]] = {}
        for candidate in candidates:
            group_key, unresolved_key = self._group_key(candidate)
            grouped[group_key].append(candidate)
            group_meta[group_key] = (candidate.target_entity_id, unresolved_key)

        groups = []
        for group_key, grouped_candidates in grouped.items():
            target_entity_id, unresolved_key = group_meta[group_key]
            packed = [
                self._pack_candidate(
                    candidate,
                    max_evidence=request.max_evidence_per_candidate,
                    max_excerpt_chars=request.max_excerpt_chars,
                )
                for candidate in grouped_candidates
            ]
            reason_codes = set()
            if unresolved_key:
                reason_codes.add("ambiguous_identity")
            if any(not item["evidence"] for item in packed):
                reason_codes.add("needs_source_lookup")
            groups.append(
                {
                    "group_key": group_key,
                    "target_entity_id": target_entity_id,
                    "unresolved_identity_key": unresolved_key,
                    "candidates": packed,
                    "target_context": self._compact_target_context(target_entity_id),
                    "signals": self._duplicate_signals(grouped_candidates, target_entity_id),
                    "reason_codes": sorted(reason_codes),
                }
            )

        completed = candidates[-1] if candidates else None
        return {
            "as_of": request.as_of,
            "cursor_started": request.cursor.model_dump() if request.cursor else None,
            "cursor_completed": (
                {"created_at": completed.created_at, "candidate_id": completed.id}
                if completed
                else None
            ),
            "has_more": has_more,
            "input_candidate_count": len(candidates),
            "groups": groups,
            "budgets": {
                "candidate_limit": request.limit,
                "max_age_days": request.max_age_days,
                "max_evidence_per_candidate": request.max_evidence_per_candidate,
                "max_excerpt_chars": request.max_excerpt_chars,
                "max_target_aliases": MAX_TARGET_ALIASES,
                "max_target_observations": MAX_TARGET_OBSERVATIONS,
            },
            "diagnostics": {
                "selection": "pending_candidates_keyset",
                "evidence_policy": "user_authored_only",
            },
        }

    def evaluate_run(self, run: CurationRun) -> CurationRun:
        if run.status != "pending":
            raise api_error(409, "invalid_status_transition", "Only pending runs can be evaluated.")
        run.status = "planning"
        blocked_count = 0
        for decision in run.decisions:
            reasons = self._policy_reasons(decision)
            allowed = not reasons
            decision.status = "allowed" if allowed else "blocked"
            policy_reasons = ["policy_allowed"] if allowed else reasons
            decision.reason_codes = list(dict.fromkeys([*decision.reason_codes, *policy_reasons]))
            blocked_count += not allowed
        run.blocked_decision_count = blocked_count
        run.status = "ready"
        self.session.commit()
        return self.repository.get_run(run.id)

    def execute_run(self, run: CurationRun) -> CurationRun:
        run = self.repository.get_run(run.id)
        if not run:
            raise api_error(404, "not_found", "Curation run not found.")
        if run.mode == "disabled":
            raise api_error(409, "curation_disabled", "Curation execution is disabled.")
        if run.mode != "apply":
            raise api_error(409, "shadow_mode", "Shadow runs cannot execute decisions.")
        if run.status == "completed":
            for decision in run.decisions:
                if decision.status == "executed":
                    self._verify_execution(
                        decision,
                        self.repository.candidates_by_ids(decision.candidate_ids),
                        decision.canonical_record_ref,
                    )
            return self.repository.get_run(run.id)
        if run.status not in {"ready", "executing", "partial", "failed"}:
            raise api_error(409, "invalid_status_transition", "Curation run is not executable.")

        if run.status != "executing":
            run.status = "executing"
            run.completed_at = None
            self.session.commit()
        for decision_id in [decision.id for decision in run.decisions]:
            self._execute_decision(decision_id)

        run = self.repository.get_run(run.id)
        executed_count = self.repository.count_decisions(run.id, "executed")
        blocked_count = self.repository.count_decisions(run.id, "blocked")
        failed_count = self.repository.count_decisions(run.id, "failed")
        run.executed_decision_count = executed_count
        run.blocked_decision_count = blocked_count
        run.status = "partial" if failed_count else "completed"
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        return self.repository.get_run(run.id)

    def resume_run(self, run: CurationRun) -> CurationRun:
        return self.execute_run(run)

    def is_provisional_candidate(self, candidate: Candidate, entity_id: str) -> bool:
        if (
            candidate.status != "pending"
            or candidate.candidate_type != "observation"
            or candidate.target_entity_id != entity_id
            or candidate.payload.get("subject_entity_id") != entity_id
            or candidate.sensitivity == "high"
            or candidate.payload.get("sensitivity", candidate.sensitivity) == "high"
            or candidate.payload.get("observation_type") not in AUTO_OBSERVATION_TYPES
            or candidate.payload.get("ai_use_policy", "cautious_use")
            in RESTRICTED_AI_USE_POLICIES
            or not candidate.evidence
            or any(self._evidence_reasons(evidence) for evidence in candidate.evidence)
        ):
            return False
        validation = self._candidate_validation(candidate)
        return not validation["errors"] and not validation["warnings"]

    def _execute_decision(self, decision_id: str) -> None:
        decision = self.repository.get_decision(decision_id, for_update=True)
        if not decision or decision.status in {"blocked", "executed"}:
            return
        if decision.status not in {"allowed", "failed"}:
            return
        candidates = self.repository.lock_candidates(decision.candidate_ids)
        if decision.target_entity_id:
            self.session.scalar(
                select(Entity)
                .where(Entity.id == decision.target_entity_id)
                .with_for_update()
            )
        reasons = self._policy_reasons(decision)
        if reasons:
            decision.status = "blocked"
            decision.reason_codes = list(dict.fromkeys([*decision.reason_codes, *reasons]))
            self.session.commit()
            return

        try:
            decision.status = "executing"
            decision.api_error_code = None
            replacement_candidate_id = None
            if decision.action == "accept_existing":
                canonical_ref = self._execute_accept(candidates[0], edit=False)
            elif decision.action == "edit_accept_existing":
                canonical_ref = self._execute_accept(
                    candidates[0],
                    edit=True,
                    payload=decision.proposed_payload,
                )
            elif decision.action == "consolidate_accept":
                canonical_ref, replacement_candidate_id = self._execute_consolidation(
                    decision,
                    candidates,
                )
            elif decision.action == "archive_exact_duplicate":
                canonical_ref = self._execute_duplicate_archive(decision, candidates)
            else:
                raise api_error(422, "unsupported_action", "Unsupported curation action.")

            summary = self._verify_execution(
                decision,
                candidates,
                canonical_ref,
                replacement_candidate_id=replacement_candidate_id,
            )
            decision.canonical_record_ref = canonical_ref
            decision.readback_status = "verified"
            decision.readback_summary = summary
            decision.status = "executed"
            decision.executed_at = datetime.now(UTC)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            failed = self.repository.get_decision(decision_id)
            if not failed:
                raise
            failed.status = "failed"
            failed.api_error_code = self._execution_error_code(exc)
            failed.readback_status = None
            self.session.commit()

    def _execute_accept(
        self,
        candidate: Candidate,
        *,
        edit: bool,
        payload: dict[str, Any] | None = None,
    ) -> str:
        service = CandidateService(self.session)
        if edit:
            result = service.edit_accept_candidate(
                candidate,
                payload or {},
                resolution_note="curation:edit_accept_existing",
                resolved_by="system",
                commit=False,
            )
        else:
            result = service.accept_candidate(
                candidate,
                resolution_note="curation:accept_existing",
                resolved_by="system",
                commit=False,
            )
        return result.canonical_record_ref

    def _execute_consolidation(
        self,
        decision: CurationDecision,
        candidates: list[Candidate],
    ) -> tuple[str, str]:
        if len(candidates) < 2:
            raise api_error(422, "candidate_count_invalid", "Consolidation requires candidates.")
        evidence_by_key = {}
        for candidate in candidates:
            for evidence in candidate.evidence:
                evidence_by_key[(evidence.episode_id, evidence.excerpt)] = {
                    "episode_id": evidence.episode_id,
                    "excerpt": evidence.excerpt,
                    "confidence": (
                        float(evidence.confidence) if evidence.confidence is not None else None
                    ),
                }
        if set(decision.evidence_episode_ids) != {
            item["episode_id"] for item in evidence_by_key.values()
        }:
            raise api_error(
                422,
                "evidence_episode_set_mismatch",
                "Consolidation evidence must match attached candidate evidence.",
            )
        sensitivity_rank = {"low": 0, "medium": 1, "high": 2}
        sensitivity = max(
            (candidate.sensitivity for candidate in candidates),
            key=lambda value: sensitivity_rank.get(value, 99),
        )
        replacement = CandidateService(self.session).create_candidate(
            {
                "candidate_type": "observation",
                "target_entity_id": decision.target_entity_id,
                "payload": deepcopy(decision.proposed_payload),
                "evidence": list(evidence_by_key.values()),
                "confidence": min(float(candidate.confidence) for candidate in candidates),
                "sensitivity": sensitivity,
                "suggested_action": "accept",
                "created_by": "system",
            },
            commit=False,
        )
        accepted = CandidateService(self.session).accept_candidate(
            replacement,
            resolution_note=f"curation:consolidated:{decision.id}",
            resolved_by="system",
            commit=False,
        )
        for candidate in candidates:
            candidate.status = "superseded"
            candidate.supersedes_candidate_id = replacement.id
            candidate.resolution_note = f"curation:consolidated_into:{replacement.id}"
            candidate.resolved_by = "system"
            candidate.resolved_at = datetime.now(UTC)
        self.session.flush()
        return accepted.canonical_record_ref, replacement.id

    def _execute_duplicate_archive(
        self,
        decision: CurationDecision,
        candidates: list[Candidate],
    ) -> str:
        proposed_fingerprint = self._candidate_fingerprint(decision.proposed_payload)
        if proposed_fingerprint is None or any(
            self._candidate_fingerprint(candidate.payload) != proposed_fingerprint
            for candidate in candidates
        ):
            raise api_error(409, "duplicate_not_exact", "Source candidates are not exact duplicates.")
        requested_ref = decision.proposed_payload.get("canonical_record_ref")
        if isinstance(requested_ref, str) and requested_ref.startswith("observations:"):
            observation = self.session.get(Observation, requested_ref.split(":", 1)[1])
            fingerprint = self._candidate_fingerprint(decision.proposed_payload)
            if not observation or self._observation_fingerprint(observation) != fingerprint:
                raise api_error(409, "duplicate_not_exact", "Canonical duplicate is not exact.")
            for candidate in candidates:
                candidate.status = "archived"
                candidate.resolution_note = f"curation:exact_duplicate_of:{requested_ref}"
                candidate.resolved_by = "system"
                candidate.resolved_at = datetime.now(UTC)
            self.session.flush()
            return requested_ref

        if len(candidates) < 2 or len(
            {self._candidate_fingerprint(candidate.payload) for candidate in candidates}
        ) != 1:
            raise api_error(409, "duplicate_not_exact", "Pending duplicate is not exact.")
        retained = min(candidates, key=lambda candidate: (candidate.created_at, candidate.id))
        for candidate in candidates:
            if candidate.id == retained.id:
                continue
            candidate.status = "superseded"
            candidate.supersedes_candidate_id = retained.id
            candidate.resolution_note = f"curation:exact_duplicate_of:{retained.id}"
            candidate.resolved_by = "system"
            candidate.resolved_at = datetime.now(UTC)
        self.session.flush()
        return f"candidates:{retained.id}"

    def _verify_execution(
        self,
        decision: CurationDecision,
        source_candidates: list[Candidate],
        canonical_ref: str | None,
        *,
        replacement_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        if not canonical_ref:
            raise api_error(409, "readback_failed", "Canonical record reference is missing.")
        prefix, _separator, record_id = canonical_ref.partition(":")
        evidence_episode_ids: list[str] = []
        target_entity_id = decision.target_entity_id
        if prefix == "observations":
            observation = self.session.get(Observation, record_id)
            if not observation or observation.subject_entity_id != target_entity_id:
                raise api_error(409, "readback_failed", "Canonical observation readback failed.")
            if self._observation_fingerprint(observation) != self._candidate_fingerprint(
                decision.proposed_payload
            ):
                raise api_error(409, "readback_failed", "Canonical observation content differs.")
            expected_source_candidate_id = (
                replacement_candidate_id
                or decision.readback_summary.get("replacement_candidate_id")
                if decision.action == "consolidate_accept"
                else source_candidates[0].id
            )
            if (
                decision.action != "archive_exact_duplicate"
                and observation.source_candidate_id != expected_source_candidate_id
            ):
                raise api_error(409, "readback_failed", "Canonical source candidate differs.")
            evidence_episode_ids = sorted(
                self.session.scalars(
                    select(ObservationEvidence.episode_id).where(
                        ObservationEvidence.observation_id == observation.id
                    )
                ).all()
            )
            if decision.action != "archive_exact_duplicate" and set(evidence_episode_ids) != set(
                decision.evidence_episode_ids
            ):
                raise api_error(409, "readback_failed", "Canonical evidence readback failed.")
        elif prefix == "candidates":
            retained = self.session.get(Candidate, record_id)
            deterministic_retained = min(
                source_candidates,
                key=lambda candidate: (candidate.created_at, candidate.id),
            )
            fingerprints = {
                self._candidate_fingerprint(candidate.payload) for candidate in source_candidates
            }
            superseded = [
                candidate for candidate in source_candidates if candidate.id != retained.id
            ] if retained else []
            if (
                not retained
                or retained.id != deterministic_retained.id
                or retained.status != "pending"
                or len(fingerprints) != 1
                or None in fingerprints
                or any(
                    candidate.status != "superseded"
                    or candidate.supersedes_candidate_id != retained.id
                    for candidate in superseded
                )
            ):
                raise api_error(409, "readback_failed", "Retained candidate readback failed.")
        else:
            raise api_error(409, "readback_failed", "Unsupported canonical readback reference.")

        source_statuses = {candidate.id: candidate.status for candidate in source_candidates}
        expected_statuses = {
            "accept_existing": {"accepted"},
            "edit_accept_existing": {"edited_accepted"},
            "consolidate_accept": {"superseded"},
            "archive_exact_duplicate": {"archived", "pending", "superseded"},
        }[decision.action]
        if any(status not in expected_statuses for status in source_statuses.values()):
            raise api_error(409, "readback_failed", "Candidate state readback failed.")
        target = self.session.get(Entity, target_entity_id) if target_entity_id else None
        return {
            "canonical_record_ref": canonical_ref,
            "record_type": prefix,
            "record_id": record_id,
            "target_entity_id": target_entity_id,
            "target_entity": (
                {"id": target.id, "display_name": target.display_name, "status": target.status}
                if target
                else None
            ),
            "evidence_episode_ids": evidence_episode_ids,
            "source_candidate_statuses": source_statuses,
            "replacement_candidate_id": replacement_candidate_id,
        }

    @staticmethod
    def _execution_error_code(exc: Exception) -> str:
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            error = exc.detail.get("error", {})
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                return error["code"]
        return "execution_failed"

    def _policy_reasons(self, decision: CurationDecision) -> list[str]:
        reasons: list[str] = []
        if decision.action not in AUTO_ACTIONS:
            reasons.append("unsupported_action")
        candidates = self.repository.candidates_by_ids(decision.candidate_ids)
        by_id = {candidate.id: candidate for candidate in candidates}
        ordered = [by_id[candidate_id] for candidate_id in decision.candidate_ids if candidate_id in by_id]
        if len(ordered) != len(decision.candidate_ids):
            reasons.append("candidate_not_found")
        if decision.action in {"accept_existing", "edit_accept_existing"} and len(ordered) != 1:
            reasons.append("candidate_count_invalid")
        if decision.action == "consolidate_accept" and len(ordered) < 2:
            reasons.append("candidate_count_invalid")
        if not ordered:
            return reasons
        if any(candidate.status != "pending" for candidate in ordered):
            reasons.append("candidate_not_pending")
        if any(candidate.candidate_type != "observation" for candidate in ordered):
            reasons.append("unsupported_candidate_type")
            return list(dict.fromkeys(reasons))

        target_ids = {candidate.target_entity_id for candidate in ordered}
        payload_target_ids = {candidate.payload.get("subject_entity_id") for candidate in ordered}
        if None in target_ids or len(target_ids) != 1 or target_ids != payload_target_ids:
            reasons.append("target_entity_mismatch")
            return list(dict.fromkeys(reasons))
        target_id = next(iter(target_ids))
        if decision.target_entity_id != target_id:
            reasons.append("target_entity_mismatch")
        target = self.session.get(Entity, target_id)
        if not target:
            reasons.append("target_entity_not_found")
        elif target.status != "active":
            reasons.append("target_entity_not_active")
        elif target.system_role == "self":
            reasons.append("protected_self")

        proposed = decision.proposed_payload
        if proposed.get("subject_entity_id") != target_id:
            reasons.append("target_entity_mismatch")
        observation_type = proposed.get("observation_type")
        if observation_type not in AUTO_OBSERVATION_TYPES:
            reasons.append("observation_type_not_auto_eligible")
        sensitivities = {
            *(candidate.sensitivity for candidate in ordered),
            *(candidate.payload.get("sensitivity", candidate.sensitivity) for candidate in ordered),
            proposed.get("sensitivity", "medium"),
        }
        if "high" in sensitivities:
            reasons.append("high_sensitivity")
        policies = {
            *(candidate.payload.get("ai_use_policy", "cautious_use") for candidate in ordered),
            proposed.get("ai_use_policy", "cautious_use"),
        }
        if policies & RESTRICTED_AI_USE_POLICIES:
            reasons.append("restricted_ai_use_policy")

        content = str(proposed.get("content") or "").strip()
        if any(term in content.casefold() for term in HIGH_IMPACT_TERMS):
            reasons.append("high_impact_content")
        if observation_type in TEMPORAL_OBSERVATION_TYPES and not any(
            proposed.get(field) for field in ("occurred_at", "valid_from", "valid_to")
        ):
            reasons.append("missing_temporal_scope")
        valid_from = self._temporal_value(proposed.get("valid_from"))
        valid_to = self._temporal_value(proposed.get("valid_to"))
        if valid_from and valid_to and valid_to < valid_from:
            reasons.append("invalid_temporal_scope")

        evidence_episode_ids = {
            evidence.episode_id for candidate in ordered for evidence in candidate.evidence
        }
        if not evidence_episode_ids:
            reasons.append("evidence_required")
        if not set(decision.evidence_episode_ids) or set(decision.evidence_episode_ids) != (
            evidence_episode_ids
        ):
            reasons.append("evidence_episode_set_mismatch")
        for candidate in ordered:
            for evidence in candidate.evidence:
                reasons.extend(self._evidence_reasons(evidence))
            validation = self._candidate_validation(candidate)
            reasons.extend(issue["code"] for issue in validation["errors"])
            reasons.extend(issue["code"] for issue in validation["warnings"])
        proposal_validation = self._proposal_validation(ordered[0], proposed)
        reasons.extend(issue["code"] for issue in proposal_validation["errors"])
        reasons.extend(issue["code"] for issue in proposal_validation["warnings"])

        if proposed.get("claim_type") == "pattern" and len(evidence_episode_ids) < 2:
            reasons.append("pattern_requires_multiple_episodes")
        duplicate_signals = self._canonical_policy_signals(ordered, proposed)
        if decision.action == "archive_exact_duplicate":
            fingerprints = {self._candidate_fingerprint(candidate.payload) for candidate in ordered}
            proposed_fingerprint = self._candidate_fingerprint(proposed)
            all_match_proposed = (
                proposed_fingerprint is not None
                and fingerprints == {proposed_fingerprint}
            )
            if not (
                all_match_proposed
                and (
                    "exact_canonical_duplicate" in duplicate_signals
                    or len(ordered) >= 2
                )
            ):
                reasons.append("duplicate_not_exact")
        else:
            reasons.extend(duplicate_signals)
        return list(dict.fromkeys(reasons))

    def _group_key(self, candidate: Candidate) -> tuple[str, str | None]:
        if candidate.target_entity_id:
            return f"entity:{candidate.target_entity_id}", None
        name = candidate.payload.get("canonical_name") or candidate.payload.get("display_name")
        if candidate.candidate_type == "new_entity" and isinstance(name, str) and name.strip():
            normalized = normalize_name(name)
            return f"unresolved:{normalized}", normalized
        return f"candidate:{candidate.id}", None

    def _pack_candidate(
        self,
        candidate: Candidate,
        *,
        max_evidence: int,
        max_excerpt_chars: int,
    ) -> dict[str, Any]:
        validation = self._candidate_validation(candidate)
        evidence_items = []
        for evidence in sorted(candidate.evidence, key=lambda item: (item.created_at, item.id)):
            if self._evidence_reasons(evidence):
                continue
            excerpt = evidence.excerpt.strip()[:max_excerpt_chars]
            episode = evidence.episode
            evidence_items.append(
                {
                    "candidate_evidence_id": evidence.id,
                    "episode_id": episode.id,
                    "excerpt": excerpt,
                    "confidence": (
                        float(evidence.confidence) if evidence.confidence is not None else None
                    ),
                    "source_type": episode.source_type,
                    "source_ref": episode.source_ref,
                    "body_hash": episode.body_hash,
                    "actor": episode.actor,
                    "occurred_at": episode.occurred_at,
                    "ingested_at": episode.ingested_at,
                    "created_at": evidence.created_at,
                }
            )
            if len(evidence_items) >= max_evidence:
                break
        return {
            "id": candidate.id,
            "candidate_type": candidate.candidate_type,
            "target_entity_id": candidate.target_entity_id,
            "payload": candidate.payload,
            "confidence": float(candidate.confidence),
            "sensitivity": candidate.sensitivity,
            "suggested_action": candidate.suggested_action,
            "status": candidate.status,
            "created_at": candidate.created_at,
            "evidence": evidence_items,
            "validation_errors": validation["errors"],
            "validation_warnings": validation["warnings"],
            "normalizations": validation["normalizations"],
        }

    def _candidate_validation(self, candidate: Candidate) -> dict[str, list[dict[str, Any]]]:
        result = AgentWriteFilter(self.session).validate(
            "candidate",
            {
                "candidate_type": candidate.candidate_type,
                "target_entity_id": candidate.target_entity_id,
                "payload": deepcopy(candidate.payload),
                "evidence": [
                    {
                        "episode_id": evidence.episode_id,
                        "excerpt": evidence.excerpt,
                        "confidence": (
                            float(evidence.confidence)
                            if evidence.confidence is not None
                            else None
                        ),
                    }
                    for evidence in candidate.evidence
                ],
                "confidence": float(candidate.confidence),
                "sensitivity": candidate.sensitivity,
                "suggested_action": candidate.suggested_action,
                "created_by": candidate.created_by,
                "supersedes_candidate_id": candidate.supersedes_candidate_id,
                "supersedes_record_ref": candidate.supersedes_record_ref,
            },
        )
        return {
            "errors": result["errors"],
            "warnings": result["warnings"],
            "normalizations": result["normalizations_applied"],
        }

    def _proposal_validation(
        self,
        candidate: Candidate,
        proposed_payload: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        result = AgentWriteFilter(self.session).validate(
            "candidate",
            {
                "candidate_type": "observation",
                "target_entity_id": candidate.target_entity_id,
                "payload": deepcopy(proposed_payload),
                "evidence": [],
                "confidence": float(candidate.confidence),
                "sensitivity": candidate.sensitivity,
                "suggested_action": candidate.suggested_action,
                "created_by": "system",
            },
        )
        return {"errors": result["errors"], "warnings": result["warnings"]}

    def _evidence_reasons(self, evidence) -> list[str]:
        episode = evidence.episode
        if not episode:
            return ["evidence_episode_not_found"]
        reasons = []
        excerpt = (evidence.excerpt or "").strip()
        if episode.actor != "user":
            reasons.append("non_user_evidence")
        if not excerpt:
            reasons.append("evidence_excerpt_required")
        elif len(excerpt) > MAX_POLICY_EVIDENCE_EXCERPT_CHARS:
            reasons.append("evidence_excerpt_too_long")
        elif excerpt not in episode.body_excerpt:
            reasons.append("evidence_excerpt_not_source")
        if not episode.source_ref or not episode.body_hash or not episode.source_type:
            reasons.append("evidence_provenance_incomplete")
        return reasons

    def _compact_target_context(self, entity_id: str | None) -> dict[str, Any] | None:
        if not entity_id:
            return None
        entity = self.session.get(Entity, entity_id)
        if not entity:
            return None
        aliases = self.session.scalars(
            select(EntityAlias)
            .where(EntityAlias.entity_id == entity_id, EntityAlias.status == "active")
            .order_by(EntityAlias.created_at)
            .limit(MAX_TARGET_ALIASES)
        ).all()
        observations = self.session.scalars(
            select(Observation)
            .where(Observation.subject_entity_id == entity_id, Observation.status == "active")
            .order_by(Observation.created_at.desc())
            .limit(MAX_TARGET_OBSERVATIONS)
        ).all()
        return {
            "entity": {
                "id": entity.id,
                "display_name": entity.display_name,
                "canonical_name": entity.canonical_name,
                "status": entity.status,
            },
            "aliases": [{"id": alias.id, "alias": alias.alias} for alias in aliases],
            "observations": [
                {
                    "record_ref": f"observations:{observation.id}",
                    "observation_type": observation.observation_type,
                    "content": observation.content,
                    "claim_type": observation.claim_type,
                    "valid_from": observation.valid_from,
                    "valid_to": observation.valid_to,
                    "occurred_at": observation.occurred_at,
                }
                for observation in observations
            ],
        }

    def _duplicate_signals(
        self,
        candidates: list[Candidate],
        target_entity_id: str | None,
    ) -> dict[str, list[str]]:
        pending_by_fingerprint: dict[tuple, list[str]] = defaultdict(list)
        for candidate in candidates:
            fingerprint = self._candidate_fingerprint(candidate.payload)
            if fingerprint:
                pending_by_fingerprint[fingerprint].append(candidate.id)
        pending_duplicates = sorted(
            candidate_id
            for ids in pending_by_fingerprint.values()
            if len(ids) > 1
            for candidate_id in ids
        )
        exact_refs: list[str] = []
        conflict_refs: list[str] = []
        if target_entity_id:
            canonical = self.session.scalars(
                select(Observation).where(
                    Observation.subject_entity_id == target_entity_id,
                    Observation.status == "active",
                )
            ).all()
            candidate_fingerprints = {
                fingerprint
                for candidate in candidates
                if (fingerprint := self._candidate_fingerprint(candidate.payload))
            }
            candidate_scopes = {self._fingerprint_scope(item) for item in candidate_fingerprints}
            for observation in canonical:
                fingerprint = self._observation_fingerprint(observation)
                if fingerprint in candidate_fingerprints:
                    exact_refs.append(f"observations:{observation.id}")
                elif self._fingerprint_scope(fingerprint) in candidate_scopes and any(
                    fingerprint[index] for index in (5, 6, 7)
                ):
                    conflict_refs.append(f"observations:{observation.id}")
        return {
            "exact_pending_duplicate_ids": pending_duplicates,
            "exact_canonical_duplicate_refs": sorted(exact_refs),
            "canonical_conflict_refs": sorted(conflict_refs),
        }

    def _canonical_policy_signals(
        self,
        candidates: list[Candidate],
        proposed_payload: dict[str, Any],
    ) -> list[str]:
        target_id = candidates[0].target_entity_id
        fingerprint = self._candidate_fingerprint(proposed_payload)
        if not target_id or not fingerprint:
            return []
        pending = self.session.scalars(
            select(Candidate).where(
                Candidate.status == "pending",
                Candidate.candidate_type == "observation",
                Candidate.target_entity_id == target_id,
                Candidate.id.not_in([candidate.id for candidate in candidates]),
            )
        ).all()
        if any(self._candidate_fingerprint(candidate.payload) == fingerprint for candidate in pending):
            return ["exact_pending_duplicate"]
        for observation in self.session.scalars(
            select(Observation).where(
                Observation.subject_entity_id == target_id,
                Observation.status == "active",
            )
        ):
            canonical = self._observation_fingerprint(observation)
            if canonical == fingerprint:
                return ["exact_canonical_duplicate"]
            if self._fingerprint_scope(canonical) == self._fingerprint_scope(fingerprint) and any(
                fingerprint[index] for index in (5, 6, 7)
            ):
                return ["same_scope_canonical_difference"]
        return []

    def _candidate_fingerprint(self, payload: dict[str, Any]) -> tuple | None:
        required = ("subject_entity_id", "observation_type", "claim_type", "content")
        if not all(payload.get(field) for field in required):
            return None
        return (
            payload["subject_entity_id"],
            payload["observation_type"],
            payload["claim_type"],
            normalize_name(str(payload["content"])),
            tuple(sorted(payload.get("related_entity_ids") or [])),
            self._temporal_value(payload.get("valid_from")),
            self._temporal_value(payload.get("valid_to")),
            self._temporal_value(payload.get("occurred_at")),
        )

    def _observation_fingerprint(self, observation: Observation) -> tuple:
        related_ids = self.session.scalars(
            select(ObservationEntity.entity_id).where(
                ObservationEntity.observation_id == observation.id
            )
        ).all()
        return (
            observation.subject_entity_id,
            observation.observation_type,
            observation.claim_type,
            normalize_name(observation.content),
            tuple(sorted(related_ids)),
            self._temporal_value(observation.valid_from),
            self._temporal_value(observation.valid_to),
            self._temporal_value(observation.occurred_at),
        )

    @staticmethod
    def _fingerprint_scope(fingerprint: tuple) -> tuple:
        return (*fingerprint[:3], *fingerprint[4:])

    @staticmethod
    def _temporal_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return value
        elif not isinstance(value, datetime):
            return str(value)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed.isoformat()

    def transition_run(
        self,
        run: CurationRun,
        target_status: CurationRunStatus | str,
    ) -> CurationRun:
        target = self._status_value(CurationRunStatus, target_status, "run")
        self._ensure_transition(RUN_TRANSITIONS, run.status, target, "run")
        if target == "executing" and run.mode != "apply":
            raise api_error(
                409,
                "invalid_status_transition",
                "Only apply-mode curation runs can enter executing status.",
            )
        if target == "completed" and run.mode == "apply":
            executed_count = self.repository.count_decisions(run.id, "executed")
            blocked_count = self.repository.count_decisions(run.id, "blocked")
            if executed_count + blocked_count != run.planned_decision_count:
                raise api_error(
                    409,
                    "completion_not_ready",
                    "Apply-mode runs require every decision to be executed or blocked.",
                )
            run.executed_decision_count = executed_count
            run.blocked_decision_count = blocked_count
        run.status = target
        run.completed_at = datetime.now(UTC) if target in RUN_TERMINAL_STATUSES else None
        return self._commit_refresh(run)

    def transition_decision(
        self,
        decision: CurationDecision,
        target_status: CurationDecisionStatus | str,
    ) -> CurationDecision:
        target = self._status_value(CurationDecisionStatus, target_status, "decision")
        self._ensure_transition(DECISION_TRANSITIONS, decision.status, target, "decision")
        run = self.repository.get_run(decision.run_id)
        if not run:
            raise api_error(404, "not_found", "Curation run not found.")
        if target == "executing" and run.mode != "apply":
            raise api_error(
                409,
                "invalid_status_transition",
                "Only apply-mode curation decisions can enter executing status.",
            )
        if target == "executed" and (
            not decision.canonical_record_ref or decision.readback_status != "verified"
        ):
            raise api_error(
                409,
                "readback_required",
                "Verified canonical readback is required before execution completes.",
            )
        decision.status = target
        if target == "executed":
            decision.executed_at = datetime.now(UTC)
        try:
            self.session.flush()
            run.executed_decision_count = self.repository.count_decisions(run.id, "executed")
            run.blocked_decision_count = self.repository.count_decisions(run.id, "blocked")
            self.session.commit()
            self.session.refresh(decision)
            return decision
        except HTTPException:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise

    def _commit_refresh(self, item):
        try:
            self.session.commit()
            self.session.refresh(item)
            return item
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _status_value(enum_type, value, subject: str) -> str:
        try:
            return enum_type(value).value
        except ValueError as exc:
            raise api_error(422, "validation_error", f"Invalid curation {subject} status.") from exc

    @staticmethod
    def _ensure_transition(transitions: dict, current: str, target: str, subject: str) -> None:
        if target not in transitions.get(current, set()):
            raise api_error(
                409,
                "invalid_status_transition",
                f"Cannot transition curation {subject} from {current} to {target}.",
            )

    @staticmethod
    def _is_idempotency_conflict(exc: IntegrityError) -> bool:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        return constraint_name == "uq_curation_decisions_idempotency_key" or (
            "curation_decisions.idempotency_key" in str(exc.orig)
        )
