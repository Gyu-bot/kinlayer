from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from datetime import timedelta
import hashlib
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from kinlayer_backend.api.errors import api_error
from kinlayer_backend.services.material_provenance import material_provenance
from kinlayer_backend.schemas.common import without_legacy_sensitivity
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
    RESERVED_CURATION_KEYS,
    RESERVED_CURATION_KEY_TOKENS,
    contains_reserved_curation_marker,
    validate_bounded_curation_json,
)
from kinlayer_backend.services.agent_write_filter import AgentWriteFilter
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.ontology import normalize_name
from kinlayer_backend.services.candidate_snapshots import (
    candidate_evidence_digest,
    candidate_payload_digest,
    candidate_snapshot,
    entity_digest,
)

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
NON_PERSON_NAME_TERMS = {
    "he", "her", "hers", "him", "his", "i", "it", "me", "my", "she", "their",
    "them", "they", "we", "you", "그", "그녀", "그분", "그 사람", "나", "너", "저",
    "가족", "남자친구", "동료", "배우자", "부모", "사장", "선생", "선생님", "아내",
    "아빠", "애인", "엄마", "여자친구", "친구", "파트너", "남편",
}
ROLE_TITLE_TERMS = {
    "ceo", "chief", "coach", "director", "doctor", "dr", "engineer", "manager",
    "president", "professor", "teacher", "과장", "과장님", "대리", "대리님", "대표",
    "대표님", "박사", "부장", "부장님", "사장", "사장님", "상무", "상무님", "선생",
    "선생님", "의사", "이사", "이사님", "임원", "임원님", "전무", "전무님", "차장",
    "차장님", "팀장", "팀장님", "회장", "회장님",
}
UNRESOLVED_NEW_ENTITY_REASON_MARKERS = ("identity", "conflict", "schema", "evidence")
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
MAX_SOURCE_PAYLOAD_STRING_CHARS = 500
MAX_SOURCE_PAYLOAD_LIST_ITEMS = 20
MAX_SOURCE_PAYLOAD_BYTES = 8192
CONTACT_TERMS = {
    "phone",
    "email",
    "e-mail",
    "address",
    "contact",
    "telephone",
    "mobile number",
    "전화",
    "이메일",
    "주소",
    "연락처",
}
EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)")


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
            decision_payload = decision.model_dump(mode="json", exclude={"planner"})
            if not decision_payload["expected_candidates"]:
                candidates = self.repository.candidates_by_ids(decision.candidate_ids)
                if len(candidates) == len(decision.candidate_ids):
                    decision_payload["expected_candidates"] = [
                        candidate_snapshot(self.session, candidate)
                        for candidate in sorted(candidates, key=lambda item: item.id)
                    ]
            decision_payloads.append(decision_payload)
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
        upper_at = request.upper_cursor.created_at if request.upper_cursor else None
        upper_id = request.upper_cursor.candidate_id if request.upper_cursor else None
        created_after = request.as_of - timedelta(days=request.max_age_days)
        rows = self.repository.pending_candidates(
            as_of=request.as_of,
            created_after=created_after,
            cursor_at=cursor_at,
            cursor_id=cursor_id,
            upper_at=upper_at,
            upper_id=upper_id,
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
            "cursor_started": (
                request.cursor.model_dump()
                if request.cursor
                else {"created_at": created_after, "candidate_id": ""}
            ),
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
                "max_source_payload_string_chars": MAX_SOURCE_PAYLOAD_STRING_CHARS,
                "max_source_payload_bytes": MAX_SOURCE_PAYLOAD_BYTES,
            },
            "diagnostics": {
                "selection": "pending_candidates_keyset",
                "evidence_policy": (
                    "user_authored_or_authorized_material_v1"
                    if any(e.episode and e.episode.material_import_id for c in candidates for e in c.evidence)
                    else "user_authored_only"
                ),
            },
        }

    def validate_run_source_window(self, payload: CurationRunCreate) -> None:
        candidate_memberships = [
            candidate_id
            for decision in payload.decisions
            for candidate_id in decision.candidate_ids
        ]
        decision_candidate_ids = set(candidate_memberships)
        if payload.diagnostics.get("replay_checkpoint") is True:
            self._validate_empty_replay_checkpoint(payload, candidate_memberships)
            return
        if payload.input_candidate_count == 0:
            if (
                candidate_memberships
                or payload.decisions
                or payload.cursor_started_at is not None
                or payload.cursor_started_id is not None
                or payload.cursor_completed_at is not None
                or payload.cursor_completed_id is not None
            ):
                raise api_error(
                    409,
                    "source_pack_empty_run_mismatch",
                    "An empty source window requires zero decisions and candidates.",
                )
            return
        if not candidate_memberships:
            raise api_error(
                409,
                "source_pack_empty_run_mismatch",
                "A non-empty source window requires candidate decisions.",
            )
        if len(candidate_memberships) != len(decision_candidate_ids):
            raise api_error(
                409,
                "duplicate_candidate_membership",
                "Each source-pack candidate must appear in exactly one decision.",
            )
        if (
            payload.cursor_started_at is None
            or payload.cursor_started_id is None
            or payload.cursor_completed_at is None
            or payload.cursor_completed_id is None
        ):
            raise api_error(
                409,
                "source_pack_snapshot_mismatch",
                "Non-empty plans require a complete source-pack cursor window.",
            )
        rows = self.repository.pending_candidates(
            as_of=payload.cursor_completed_at,
            created_after=payload.cursor_started_at,
            cursor_at=payload.cursor_started_at,
            cursor_id=payload.cursor_started_id,
            upper_at=payload.cursor_completed_at,
            upper_id=payload.cursor_completed_id,
            limit=payload.input_candidate_count + 1,
        )
        source_candidate_ids = [candidate.id for candidate in rows]
        completed = rows[-1] if rows else None
        if len(rows) != payload.input_candidate_count:
            raise api_error(
                409,
                "source_pack_count_mismatch",
                "Run input_candidate_count does not match the source-pack window.",
            )
        if not completed or self._cursor_key(completed.created_at, completed.id) != self._cursor_key(
            payload.cursor_completed_at,
            payload.cursor_completed_id,
        ):
            raise api_error(
                409,
                "source_pack_snapshot_mismatch",
                "Run cursor/count does not match the current pending source-pack window.",
            )
        source_candidate_id_set = set(source_candidate_ids)
        if decision_candidate_ids - source_candidate_id_set:
            raise api_error(
                409,
                "candidate_outside_source_pack",
                "A decision references a candidate outside the source-pack window.",
            )
        if source_candidate_id_set - decision_candidate_ids:
            raise api_error(
                409,
                "source_pack_candidate_coverage_mismatch",
                "Every source-pack candidate must appear in exactly one decision.",
            )
        expected_snapshots = [
            item.model_dump(mode="json")
            for decision in payload.decisions
            for item in decision.expected_candidates
        ]
        if self._candidate_snapshot_mismatch(rows, expected_snapshots):
            raise api_error(
                409,
                "source_pack_candidate_changed",
                "A source-pack candidate changed after review.",
            )
        payload.diagnostics.update(
            {
                "source_pack_candidate_count": len(source_candidate_ids),
                "source_pack_candidate_ids_hash": hashlib.sha256(
                    "\n".join(source_candidate_ids).encode()
                ).hexdigest(),
                "source_pack_window": {
                    "started_at": payload.cursor_started_at.isoformat(),
                    "started_id": payload.cursor_started_id,
                    "completed_at": payload.cursor_completed_at.isoformat(),
                    "completed_id": payload.cursor_completed_id,
                },
            }
        )
        validate_bounded_curation_json(payload.diagnostics, max_bytes=8192)

    def _validate_empty_replay_checkpoint(
        self,
        payload: CurationRunCreate,
        candidate_memberships: list[str],
    ) -> None:
        if (
            set(payload.diagnostics) != {"replay_checkpoint"}
            or payload.mode != "apply"
            or payload.input_candidate_count != 0
            or payload.decisions
            or candidate_memberships
            or payload.cursor_started_at is None
            or payload.cursor_started_id is None
            or payload.cursor_completed_at is None
            or payload.cursor_completed_id is None
        ):
            raise api_error(
                409,
                "replay_checkpoint_invalid",
                "Replay checkpoints require an empty apply run and complete cursor bounds.",
            )
        if self._cursor_key(
            payload.cursor_completed_at,
            payload.cursor_completed_id,
        ) <= self._cursor_key(payload.cursor_started_at, payload.cursor_started_id):
            raise api_error(
                409,
                "replay_checkpoint_invalid",
                "Replay checkpoint end must be greater than start.",
            )
        pending = self.repository.pending_candidates(
            as_of=payload.cursor_completed_at,
            created_after=payload.cursor_started_at,
            cursor_at=payload.cursor_started_at,
            cursor_id=payload.cursor_started_id,
            upper_at=payload.cursor_completed_at,
            upper_id=payload.cursor_completed_id,
            limit=1,
        )
        if pending:
            raise api_error(
                409,
                "replay_checkpoint_not_empty",
                "Replay checkpoint window still contains pending candidates.",
            )
        payload.diagnostics.update(
            {
                "replay_checkpoint_verified_empty": True,
                "replay_checkpoint_window": {
                    "started_at": payload.cursor_started_at.isoformat(),
                    "started_id": payload.cursor_started_id,
                    "completed_at": payload.cursor_completed_at.isoformat(),
                    "completed_id": payload.cursor_completed_id,
                },
            }
        )
        validate_bounded_curation_json(payload.diagnostics, max_bytes=8192)

    @staticmethod
    def _cursor_key(created_at: datetime, candidate_id: str) -> tuple[datetime, str]:
        if created_at.tzinfo is not None:
            created_at = created_at.astimezone(UTC).replace(tzinfo=None)
        return created_at, candidate_id

    def evaluate_run(self, run: CurationRun) -> CurationRun:
        run = self.repository.get_run(run.id)
        if not run:
            raise api_error(404, "not_found", "Curation run not found.")
        if run.status not in {"pending", "planning"}:
            raise api_error(
                409,
                "invalid_status_transition",
                "Only pending or planning runs can be evaluated.",
            )
        if any(
            decision.canonical_record_ref
            or decision.status not in {"proposed", "allowed", "blocked"}
            for decision in run.decisions
        ):
            raise api_error(
                409,
                "recovery_state_invalid",
                "Planning recovery cannot contain execution state.",
            )
        if run.status == "pending":
            run.status = "planning"
            self.session.commit()
            self.session.expire_all()
            run = self.repository.get_run(run.id)
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
        self.session.expire_all()
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
                    self._reconcile_committed(decision.id)
            self.session.expire_all()
            run = self.repository.get_run(run.id)
            if any(decision.status not in {"executed", "blocked"} for decision in run.decisions):
                run.status = "partial"
                self.session.commit()
            return self.repository.get_run(run.id)
        if run.status not in {"ready", "executing", "partial", "failed"}:
            raise api_error(409, "invalid_status_transition", "Curation run is not executable.")

        if run.status != "executing":
            run.status = "executing"
            run.completed_at = None
            self.session.commit()
        for decision_id in [decision.id for decision in run.decisions]:
            self._execute_decision(decision_id)

        self.session.expire_all()
        run = self.repository.get_run(run.id)
        executed_count = self.repository.count_decisions(run.id, "executed")
        blocked_count = self.repository.count_decisions(run.id, "blocked")
        run.executed_decision_count = executed_count
        run.blocked_decision_count = blocked_count
        run.status = (
            "completed"
            if executed_count + blocked_count == run.planned_decision_count
            else "partial"
        )
        run.completed_at = datetime.now(UTC)
        self.session.commit()
        self.session.expire_all()
        return self.repository.get_run(run.id)

    def resume_run(
        self,
        run: CurationRun,
        *,
        server_mode: str = "apply",
        policy_version: str | None = None,
    ) -> CurationRun:
        run = self.repository.get_run(run.id)
        if not run:
            raise api_error(404, "not_found", "Curation run not found.")
        if server_mode == "disabled":
            raise api_error(409, "curation_disabled", "Curation is disabled.")
        if policy_version is not None and run.policy_version != policy_version:
            raise api_error(
                409,
                "curation_policy_mismatch",
                "Run policy_version must match the configured curation policy.",
            )
        if run.status in {"pending", "planning"}:
            return self.evaluate_run(run)
        if run.mode == "shadow" and run.status in {"ready", "completed"}:
            self.session.expire_all()
            return self.repository.get_run(run.id)
        if run.mode != "apply":
            raise api_error(409, "shadow_mode", "Shadow runs cannot execute decisions.")
        if server_mode != "apply":
            raise api_error(409, "shadow_mode", "Only apply mode can execute curation runs.")
        return self.execute_run(run)

    def is_provisional_candidate(self, candidate: Candidate, entity_id: str) -> bool:
        if (
            candidate.status != "pending"
            or candidate.candidate_type != "observation"
            or candidate.target_entity_id != entity_id
            or candidate.payload.get("subject_entity_id") != entity_id
            or candidate.payload.get("observation_type") not in AUTO_OBSERVATION_TYPES
            or candidate.payload.get("ai_use_policy", "cautious_use")
            in RESTRICTED_AI_USE_POLICIES
            or self._has_high_impact_content(str(candidate.payload.get("content") or ""))
            or not candidate.evidence
            or any(self._evidence_reasons(evidence) for evidence in candidate.evidence)
        ):
            return False
        validation = self._candidate_validation(candidate)
        return (
            bool(validation["safe_payload"])
            and not validation["errors"]
            and not validation["warnings"]
        )

    def _candidate_snapshot_mismatch(
        self,
        candidates: list[Candidate],
        expected_items: list[dict[str, Any]],
    ) -> bool:
        expected = {str(item.get("id") or ""): item for item in expected_items}
        if set(expected) != {candidate.id for candidate in candidates}:
            return True
        for candidate in candidates:
            reviewed = expected[candidate.id]
            actual = candidate_snapshot(self.session, candidate)
            if any(
                actual[field] != reviewed.get(field)
                for field in ("status", "payload_digest", "evidence_digest")
            ):
                return True
            reviewed_at = reviewed.get("updated_at")
            if isinstance(reviewed_at, str):
                try:
                    reviewed_at = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
                except ValueError:
                    return True
            actual_at = candidate.updated_at
            if actual_at.tzinfo is None:
                actual_at = actual_at.replace(tzinfo=UTC)
            if not isinstance(reviewed_at, datetime):
                return True
            if reviewed_at.tzinfo is None:
                reviewed_at = reviewed_at.replace(tzinfo=UTC)
            if actual_at.astimezone(UTC) != reviewed_at.astimezone(UTC):
                return True
        return False

    def _execute_decision(self, decision_id: str) -> None:
        decision = self.repository.get_decision(decision_id)
        if not decision or decision.status in {"blocked", "executed"}:
            return
        if decision.canonical_record_ref:
            self.session.rollback()
            self._reconcile_committed(decision_id)
            return
        if decision.status not in {"allowed", "failed"}:
            return
        # The first read is intentionally unlocked. Expire it before the locking read so
        # an executor that waited on another transaction cannot act on its stale identity-map
        # copy after the other executor commits.
        self.session.expire(decision)
        decision = self.repository.get_decision(decision_id, for_update=True)
        if not decision:
            self.session.rollback()
            return
        candidates = self.repository.lock_candidates(decision.candidate_ids)
        run = self.session.scalar(
            select(CurationRun)
            .where(CurationRun.id == decision.run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if decision.canonical_record_ref or decision.status == "executed":
            self.session.rollback()
            self._reconcile_committed(decision_id)
            return
        if (
            not run
            or run.mode != "apply"
            or run.status not in {"executing", "partial", "failed"}
            or decision.status not in {"allowed", "failed"}
        ):
            self.session.rollback()
            return
        if decision.target_entity_id:
            self.session.scalar(
                select(Entity)
                .where(Entity.id == decision.target_entity_id)
                .with_for_update()
            )
        if self._candidate_snapshot_mismatch(candidates, decision.expected_candidates):
            decision.status = "blocked"
            decision.reason_codes = list(
                dict.fromkeys([*decision.reason_codes, "source_candidate_changed"])
            )
            self.session.commit()
            return
        reasons = self._policy_reasons(decision)
        if reasons:
            decision.status = "blocked"
            decision.reason_codes = list(dict.fromkeys([*decision.reason_codes, *reasons]))
            self.session.commit()
            return

        canonical_ref: str | None = None
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
            decision.readback_status = "verification_unknown"
            decision.readback_summary = summary
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            if self._reconcile_committed(decision_id):
                return
            self._mark_execution_failed(decision_id, exc)
            return
        self._reconcile_committed(decision_id)

    def _reconcile_committed(self, decision_id: str) -> bool:
        with Session(bind=self.session.get_bind(), expire_on_commit=False) as fresh_session:
            service = CurationService(fresh_session)
            decision = service.repository.get_decision(decision_id)
            if not decision or not decision.canonical_record_ref:
                return False
            run = service.repository.get_run(decision.run_id)
            if not run or run.mode != "apply":
                return False
            candidates = service.repository.candidates_by_ids(decision.candidate_ids)
            replacement_candidate_id = decision.readback_summary.get("replacement_candidate_id")
            try:
                summary = self._postcommit_verify(
                    service,
                    decision,
                    candidates,
                    replacement_candidate_id,
                )
            except HTTPException as exc:
                decision.status = "failed"
                decision.readback_status = "failed"
                decision.api_error_code = self._execution_error_code(exc)
                fresh_session.commit()
                return False
            except Exception:
                decision.status = "failed"
                decision.readback_status = "verification_unknown"
                decision.api_error_code = "verification_unknown"
                fresh_session.commit()
                return False
            decision.readback_summary = summary
            decision.readback_status = "verified"
            decision.status = "executed"
            decision.api_error_code = None
            decision.executed_at = datetime.now(UTC)
            fresh_session.commit()
            return True

    def _postcommit_verify(
        self,
        service: "CurationService",
        decision: CurationDecision,
        candidates: list[Candidate],
        replacement_candidate_id: str | None,
    ) -> dict[str, Any]:
        return service._verify_execution(
            decision,
            candidates,
            decision.canonical_record_ref,
            replacement_candidate_id=replacement_candidate_id,
        )

    def _mark_execution_failed(self, decision_id: str, exc: Exception) -> None:
        with Session(bind=self.session.get_bind(), expire_on_commit=False) as fresh_session:
            failed = CurationRepository(fresh_session).get_decision(decision_id)
            if not failed:
                raise exc
            failed.status = "failed"
            failed.api_error_code = self._execution_error_code(exc)
            failed.readback_status = None
            fresh_session.commit()

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
        replacement = CandidateService(self.session).create_candidate(
            {
                "candidate_type": "observation",
                "target_entity_id": decision.target_entity_id,
                "payload": deepcopy(decision.proposed_payload),
                "evidence": list(evidence_by_key.values()),
                "confidence": min(float(candidate.confidence) for candidate in candidates),
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
        if decision.canonical_record_ref and decision.canonical_record_ref != canonical_ref:
            raise api_error(409, "readback_failed", "Decision canonical reference differs.")
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
        elif prefix == "entities" and decision.action == "accept_existing":
            entity = self.session.get(Entity, record_id)
            payload = decision.proposed_payload
            if (
                len(source_candidates) != 1
                or source_candidates[0].candidate_type != "new_entity"
                or not entity
                or entity.status != "active"
                or entity.entity_type != "person"
                or normalize_name(entity.display_name)
                != normalize_name(str(payload.get("display_name") or ""))
                or normalize_name(entity.canonical_name or entity.display_name)
                != normalize_name(str(payload.get("canonical_name") or payload.get("display_name") or ""))
            ):
                raise api_error(409, "readback_failed", "Canonical entity readback failed.")
            target_entity_id = entity.id
            evidence_episode_ids = sorted(decision.evidence_episode_ids)
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
        if decision.action in {"accept_existing", "edit_accept_existing"} and any(
            candidate.canonical_record_ref != canonical_ref for candidate in source_candidates
        ):
            raise api_error(409, "readback_failed", "Source candidate canonical ref differs.")
        if decision.action == "consolidate_accept":
            replacement = (
                self.session.get(Candidate, replacement_candidate_id)
                if replacement_candidate_id
                else None
            )
            if (
                not replacement
                or replacement.status != "accepted"
                or replacement.canonical_record_ref != canonical_ref
            ):
                raise api_error(409, "readback_failed", "Replacement candidate readback failed.")
        target = self.session.get(Entity, target_entity_id) if target_entity_id else None
        return {
            "canonical_record_ref": canonical_ref,
            "record_type": prefix,
            "record_id": record_id,
            "target_entity_id": target_entity_id,
            "target_entity": (
                {
                    "id": target.id,
                    "display_name": self._safe_source_text(target.display_name),
                    "canonical_name": self._safe_source_text(target.canonical_name or ""),
                    "entity_type": target.entity_type,
                    "status": target.status,
                    "updated_at": target.updated_at.isoformat(),
                    "entity_digest": entity_digest(target),
                }
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
        if all(candidate.candidate_type == "new_entity" for candidate in ordered):
            reasons.extend(self._new_entity_policy_reasons(decision, ordered))
            return list(dict.fromkeys(reasons))
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
        policies = {
            *(candidate.payload.get("ai_use_policy", "cautious_use") for candidate in ordered),
            proposed.get("ai_use_policy", "cautious_use"),
        }
        if policies & RESTRICTED_AI_USE_POLICIES:
            reasons.append("restricted_ai_use_policy")

        imported = [e for c in ordered for e in c.evidence if e.episode and e.episode.material_import_id]
        if imported and decision.action not in {"accept_existing", "archive_exact_duplicate"}:
            reasons.append("material_import_requires_unchanged_accept")
        if imported and decision.action == "accept_existing" and without_legacy_sensitivity(proposed) != without_legacy_sensitivity(ordered[0].payload):
            reasons.append("material_import_payload_changed")
        if imported and any(self._has_high_impact_content(e.excerpt or "") for e in imported):
            reasons.append("high_impact_content")
        contents = [
            str(proposed.get("content") or "").strip(),
            *(str(candidate.payload.get("content") or "").strip() for candidate in ordered),
        ]
        if any(self._has_high_impact_content(content) for content in contents):
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
            if candidate.payload and not validation["safe_payload"]:
                reasons.append("unsafe_candidate_payload")
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

    def _new_entity_policy_reasons(
        self,
        decision: CurationDecision,
        candidates: list[Candidate],
    ) -> list[str]:
        if decision.action != "accept_existing" or len(candidates) != 1:
            return ["new_entity_requires_single_accept"]
        candidate = candidates[0]
        payload = candidate.payload
        reasons: list[str] = []
        if decision.target_entity_id is not None or candidate.target_entity_id is not None:
            reasons.append("target_entity_mismatch")
        if without_legacy_sensitivity(decision.proposed_payload) != without_legacy_sensitivity(payload):
            reasons.append("new_entity_payload_inference_not_allowed")
        if payload.get("entity_type") != "person":
            reasons.append("new_entity_person_required")

        display_name = payload.get("display_name")
        canonical_name = payload.get("canonical_name") or display_name
        name = display_name.strip() if isinstance(display_name, str) else ""
        normalized = normalize_name(name) if name else ""
        if len(name) <= 1:
            reasons.append("specific_person_name_required")
        elif self._is_non_person_name(normalized):
            reasons.append("specific_person_name_required")

        validation = self._candidate_validation(candidate)
        reasons.extend(issue["code"] for issue in validation["errors"])
        reasons.extend(issue["code"] for issue in validation["warnings"])
        if candidate.payload and not validation["safe_payload"]:
            reasons.append("unsafe_candidate_payload")
        if any(
            marker in code.casefold()
            for code in decision.reason_codes
            for marker in UNRESOLVED_NEW_ENTITY_REASON_MARKERS
        ):
            reasons.append("unresolved_new_entity_reason")

        evidence_ids = {evidence.episode_id for evidence in candidate.evidence}
        if not evidence_ids or set(decision.evidence_episode_ids) != evidence_ids:
            reasons.append("evidence_episode_set_mismatch")
        supporting_user_evidence = [
            evidence
            for evidence in candidate.evidence
            if evidence.episode
            and evidence.episode.actor == "user"
            and not self._evidence_reasons(evidence)
            and normalized
            and normalized in normalize_name(evidence.excerpt or "")
        ]
        if not supporting_user_evidence:
            reasons.append("user_name_evidence_required")

        protected_names = set()
        self_entity = self.session.scalar(
            select(Entity).where(Entity.system_role == "self", Entity.status == "active")
        )
        if self_entity:
            protected_names.update(
                normalize_name(value)
                for value in (self_entity.display_name, self_entity.canonical_name)
                if value
            )
            protected_names.update(
                alias.normalized_alias or normalize_name(alias.alias)
                for alias in self.session.scalars(
                    select(EntityAlias).where(
                        EntityAlias.entity_id == self_entity.id,
                        EntityAlias.status == "active",
                    )
                )
            )
        if normalized and normalized in protected_names:
            reasons.append("protected_self")

        active_names = {
            normalize_name(value)
            for entity in self.session.scalars(select(Entity).where(Entity.status == "active"))
            for value in (entity.display_name, entity.canonical_name)
            if value
        }
        active_names.update(
            alias.normalized_alias or normalize_name(alias.alias)
            for alias in self.session.scalars(
                select(EntityAlias)
                .join(Entity, Entity.id == EntityAlias.entity_id)
                .where(EntityAlias.status == "active", Entity.status == "active")
            )
        )
        if normalized and normalized in active_names:
            reasons.append("exact_active_identity_collision")
        if canonical_name and normalize_name(str(canonical_name)) != normalized:
            reasons.append("new_entity_payload_inference_not_allowed")
        return reasons

    @staticmethod
    def _is_non_person_name(normalized: str) -> bool:
        if normalized in NON_PERSON_NAME_TERMS or normalized in ROLE_TITLE_TERMS:
            return True
        tokens = set(re.findall(r"[\w가-힣]+", normalized, flags=re.UNICODE))
        return bool(tokens) and tokens <= ROLE_TITLE_TERMS

    def _group_key(self, candidate: Candidate) -> tuple[str, str | None]:
        if candidate.target_entity_id:
            return f"entity:{candidate.target_entity_id}", None
        name = candidate.payload.get("canonical_name") or candidate.payload.get("display_name")
        if candidate.candidate_type == "new_entity" and isinstance(name, str) and name.strip():
            safe_name = self._safe_source_text(name)
            if not safe_name or safe_name == "[redacted]":
                return f"candidate:{candidate.id}", None
            normalized = normalize_name(safe_name)
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
                    **({"material_provenance": material_provenance(self.session, evidence)}
                       if episode.material_import_id else {}),
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
            "payload": validation["safe_payload"],
            "confidence": float(candidate.confidence),
            "suggested_action": candidate.suggested_action,
            "status": candidate.status,
            "created_at": candidate.created_at,
            "updated_at": candidate.updated_at,
            "payload_digest": candidate_payload_digest(candidate),
            "evidence_digest": candidate_evidence_digest(self.session, candidate.id),
            "evidence": evidence_items,
            "validation_errors": self._safe_issue_projection(validation["errors"]),
            "validation_warnings": self._safe_issue_projection(validation["warnings"]),
            "normalizations": self._safe_issue_projection(validation["normalizations"]),
        }

    def _candidate_validation(self, candidate: Candidate) -> dict[str, Any]:
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
                "suggested_action": candidate.suggested_action,
                "created_by": candidate.created_by,
                "supersedes_candidate_id": candidate.supersedes_candidate_id,
                "supersedes_record_ref": candidate.supersedes_record_ref,
            },
        )
        schema_failed = any(issue["code"] == "schema_validation_failed" for issue in result["errors"])
        original_projection = self._safe_source_payload(candidate.payload)
        errors = list(result["errors"])
        if candidate.payload and not original_projection:
            errors.append(
                {
                    "code": "unsafe_candidate_payload",
                    "message": "Candidate payload was redacted by the curation boundary.",
                    "field": "payload",
                }
            )
        raw_safe_payload = (
            {}
            if schema_failed or (candidate.payload and not original_projection)
            else (result.get("validated_payload") or {}).get("payload", {})
        )
        warnings = list(result["warnings"])
        if any(
            e.episode and e.episode.material_import_id and e.episode.occurred_at is None
            for e in candidate.evidence
        ):
            # Independent of recency wording and of any other dated support.
            # Policy consumes these warnings for every automatic action; evidence
            # remains eligible for attribution and explicit manual review.
            warnings.append({
                "code": "material_source_date_unknown",
                "message": "Supporting human material has an unknown date; manual review required.",
                "field": "evidence.occurred_at",
            })
        return {
            "errors": errors,
            "warnings": warnings,
            "normalizations": result["normalizations_applied"],
            "safe_payload": self._safe_source_payload(raw_safe_payload),
        }

    def _safe_source_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        unsafe = False

        def project(value: Any, depth: int = 0) -> Any:
            nonlocal unsafe
            if depth > 5:
                unsafe = True
                return None
            if value is None or isinstance(value, bool | int | float):
                return value
            if isinstance(value, str):
                normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
                if contains_reserved_curation_marker(normalized):
                    unsafe = True
                    return None
                return value[:MAX_SOURCE_PAYLOAD_STRING_CHARS]
            if isinstance(value, list):
                return [
                    project(item, depth + 1)
                    for item in value[:MAX_SOURCE_PAYLOAD_LIST_ITEMS]
                ]
            if isinstance(value, dict):
                projected = {}
                for key, item in list(value.items())[:MAX_SOURCE_PAYLOAD_LIST_ITEMS]:
                    normalized_key = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
                    if (
                        normalized_key in RESERVED_CURATION_KEYS
                        or normalized_key.replace("_", "") in RESERVED_CURATION_KEY_TOKENS
                    ):
                        unsafe = True
                        continue
                    projected[str(key)[:80]] = project(item, depth + 1)
                return projected
            unsafe = True
            return None

        projected = project(payload)
        if unsafe or not isinstance(projected, dict):
            return {}
        if len(str(projected).encode()) > MAX_SOURCE_PAYLOAD_BYTES:
            return {}
        return projected

    @staticmethod
    def _safe_issue_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                key: value[:500] if isinstance(value, str) else value
                for key, value in item.items()
                if key in {"code", "message", "field"}
            }
            for item in items[:20]
        ]

    def _safe_source_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._safe_source_payload({"value": value}).get("value", "[redacted]")

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
        if episode.material_import_id:
            if not material_provenance(self.session, evidence):
                reasons.append("invalid_material_provenance")
        elif episode.source_type == "import":
            reasons.append("unauthorized_material_import")
        elif episode.actor != "user":
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
                "display_name": self._safe_source_text(entity.display_name),
                "canonical_name": self._safe_source_text(entity.canonical_name),
                "status": entity.status,
            },
            "aliases": [
                {"id": alias.id, "alias": self._safe_source_text(alias.alias)}
                for alias in aliases
            ],
            "observations": [
                {
                    "record_ref": f"observations:{observation.id}",
                    "observation_type": observation.observation_type,
                    "content": self._safe_source_payload(
                        {"content": observation.content}
                    ).get("content", "[redacted]"),
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

    @staticmethod
    def _has_high_impact_content(content: str) -> bool:
        normalized = content.casefold()
        phone_match = PHONE_PATTERN.search(content)
        return (
            any(term in normalized for term in HIGH_IMPACT_TERMS | CONTACT_TERMS)
            or EMAIL_PATTERN.search(content) is not None
            or (
                phone_match is not None
                and sum(character.isdigit() for character in phone_match.group()) >= 9
            )
        )

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
