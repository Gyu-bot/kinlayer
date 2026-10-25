from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib
import json
import os
import re
import secrets
import stat
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .config import EnrichmentConfig, RouterConfig, hermes_home
from .attention import (
    AttentionError,
    attention_begin_delivery,
    attention_cancel,
    attention_complete,
    attention_release,
    attention_release_visible,
    attention_submit,
    bridge_cancel,
    bridge_consume_reply_proof,
    bridge_context,
    bridge_deliver,
    bridge_spec,
    bridge_stage,
    bridge_status,
)


SCHEMA_VERSION = "enrichment.v1"
ADAPTER_VERSION = "0.1.0"
ACTIVE_STATES = {"authorizing", "staged", "awaiting_reply", "applying", "submission_unknown", "committed_unverified"}
TERMINAL_STATES = {"verified_applied", "unknown", "skipped", "stale", "expired", "cancelled"}
TOPICS = {"work_context", "relationship_context", "communication_preference", "interaction_style", "care_point", "current_context", "recent_interaction", "follow_up_context", "self_boundary"}
USE_CASES = {"advice", "message_tone", "schedule_prep", "relationship_interpretation"}
SUPPRESSIONS = {"declined", "later", "topic_never", "person_never"}
RELATIONS = {"knows", "friend", "family", "acquaintance", "coworker", "former_coworker", "client_contact", "vendor_contact", "reports_to", "manager_of", "introduced_by", "referred_by", "collaborated_with"}
OBSERVATIONS = {"stable_fact", "communication_preference", "relationship_pattern", "care_point", "recent_interaction", "user_feeling", "follow_up_context"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:@/-]{1,160}$")
SLOT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,60}$")
MAX_REPLY_CODEPOINTS = 4_000
MAX_ANSWER_BYTES = 24_000
APPLY_LEASE_SECONDS = 30
SNAPSHOT_KEYS = {"id", "entity_type", "display_name", "canonical_name", "system_role", "confirmation_status", "status", "updated_at", "entity_digest"}
DELIVERED_BRIDGE_STATES = {"awaiting_first_reply", "bound", "conversing"}
ATTENTION_PRODUCER = "kinlayer-enrichment"
ATTENTION_STATES = {"queued", "claimed", "sending", "delivery_unknown", "delivered", "completed", "cancelled", "expired"}
ATTENTION_KEYS = {"producer", "context_tag", "intent_id", "state", "submitted_at", "claimed_at", "sending_at", "delivered_at", "completed_at", "cancelled_at", "lease_id", "lease_expires_at", "bridge_conversation_id", "receipt_ref"}
TEMPLATES = {
    "work_context": {"work_context_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}에게 다음에 조언할 때 알아두면 좋을 요즘 일 맥락이 뭐야?"},
    "relationship_context": {"relationship_context_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}와는 어떤 관계야?"},
    "communication_preference": {"communication_preference_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}에게 말할 때 특히 맞추면 좋은 소통 방식이 있어?"},
    "interaction_style": {"interaction_style_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}와 대화할 때 어떤 방식이 제일 잘 맞아?"},
    "care_point": {"care_point_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}를 대할 때 특히 배려하면 좋은 점이 있어?"},
    "current_context": {"current_context_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}에 대해 요즘 알아두면 좋을 상황이 있어?"},
    "recent_interaction": {"recent_interaction_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}와 최근에 있었던 일 중 다음 대화에 도움 될 만한 게 있어?"},
    "follow_up_context": {"follow_up_context_v1": "그러고 보니 전에 했던 {subject} 얘기와 관련해서 궁금한 게 하나 있어. {subject}에게 다음에 이어서 물어보면 좋을 일이 있어?"},
    "self_boundary": {"self_boundary_v1": "그러고 보니 전에 나눴던 우리 얘기와 관련해서 궁금한 게 하나 있어. 내가 답할 때 지켜줬으면 하는 선이 있어?"},
}
QUESTION_DENY = (
    "데이터베이스", "기록", "프로필", "후보", "저장", "기억해둘까", "기억할까", "병합", "별칭", "정체성", "정정", "수정", "코드", "식별자", "아이디",
    "이메일", "위치", "사는 동네", "실시간 위치", "계정", "법적 이름", "본명", "주민등록번호", "나이", "성별", "정신건강", "진단", "약", "약물", "성적 관계", "성적 지향", "성 정체성", "종교", "기독교인", "정치", "소득", "연봉", "빚", "부채", "자산", "계좌", "법적 분쟁", "범죄", "폭력", "가정폭력", "자해", "중독", "타인의 비밀", "속마음", "의도 추정",
)
Transport = Callable[[str, str, dict[str, Any] | None, dict[str, str], float, int], dict[str, Any]]


class EnrichmentError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _context_tag(value: Any) -> str:
    return "person:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _attention(q: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = q.get("attention")
    return value if isinstance(value, Mapping) else None


def _bridge_id(q: Mapping[str, Any]) -> str | None:
    value = (_attention(q) or {}).get("bridge_conversation_id") or q.get("bridge_conversation_id")
    return str(value) if value else None


def _validate_attention(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) - ATTENTION_KEYS:
        raise EnrichmentError("state_attention_invalid")
    if not {"producer", "context_tag", "intent_id", "state", "submitted_at"} <= set(value) or value.get("producer") != ATTENTION_PRODUCER:
        raise EnrichmentError("state_attention_invalid")
    for key in ("intent_id", "lease_id", "bridge_conversation_id", "receipt_ref"):
        if value.get(key) is not None and not SAFE_ID.fullmatch(str(value[key])):
            raise EnrichmentError("state_attention_invalid")
    if not re.fullmatch(r"person:[0-9a-f]{32}", str(value.get("context_tag") or "")) or value.get("state") not in ATTENTION_STATES or _parse_time(value.get("submitted_at")) is None:
        raise EnrichmentError("state_attention_invalid")
    for key in ("claimed_at", "sending_at", "delivered_at", "completed_at", "cancelled_at", "lease_expires_at"):
        if value.get(key) is not None and _parse_time(value[key]) is None:
            raise EnrichmentError("state_attention_invalid")
    if value.get("lease_id") is not None and value.get("state") not in {"claimed", "sending", "delivery_unknown"}:
        raise EnrichmentError("state_attention_invalid")
    if value.get("receipt_ref") is not None and value.get("state") not in {"delivered", "completed"}:
        raise EnrichmentError("state_attention_invalid")


@contextmanager
def route_arbitration(path: Path | None = None) -> Iterator[None]:
    """Lock order is route arbitration -> reconciliation store -> enrichment store."""
    root = path or hermes_home() / "state" / "personal-context-router"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    fd = os.open(root / "conversation-route.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600); fcntl.flock(fd, fcntl.LOCK_EX); yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


class EnrichmentStateStore:
    def __init__(self, plugin_state: Any = None, path: Path | None = None):
        self.plugin_state = plugin_state
        self.path = path or hermes_home() / "state" / "personal-context-router" / "kinlayer-enrichment.json"
        self.lock_path = self.path.with_suffix(".lock")

    @contextmanager
    def update(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read()
            state.setdefault("schema_version", SCHEMA_VERSION)
            state.setdefault("questions", {})
            state.setdefault("suppressions", {})
            state.setdefault("sent_at", [])
            state.setdefault("answered_at", [])
            yield state
            self._validate(state)
            self._write(state)

    def read(self) -> dict[str, Any]:
        with self.update() as state:
            return json.loads(json.dumps(state))

    def peek(self) -> dict[str, Any]:
        """Best-effort read for hot-path guards; never creates or rewrites state."""
        state = self._read()
        state.setdefault("schema_version", SCHEMA_VERSION)
        state.setdefault("questions", {})
        state.setdefault("suppressions", {})
        state.setdefault("sent_at", [])
        state.setdefault("answered_at", [])
        return json.loads(json.dumps(state))

    def _read(self) -> dict[str, Any]:
        if self.plugin_state is not None:
            try:
                value = self.plugin_state.get(SCHEMA_VERSION, {})
                if isinstance(value, Mapping):
                    return dict(value)
            except Exception:
                pass
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, state: dict[str, Any]) -> None:
        if self.plugin_state is not None:
            try:
                setter = getattr(self.plugin_state, "set", None)
                setter(SCHEMA_VERSION, state) if callable(setter) else self.plugin_state.__setitem__(SCHEMA_VERSION, state)
                return
            except Exception:
                pass
        fd, name = tempfile.mkstemp(prefix=".enrichment-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush(); os.fsync(stream.fileno())
            os.replace(name, self.path); os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(name): os.unlink(name)

    @staticmethod
    def _validate(state: dict[str, Any]) -> None:
        if state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("questions"), dict):
            raise EnrichmentError("state_schema_invalid")
        for question in state.get("questions", {}).values():
            if not isinstance(question, Mapping):
                raise EnrichmentError("state_schema_invalid")
            _validate_attention(question.get("attention"))
        raw = json.dumps(state, ensure_ascii=False)
        if len(raw) > 500_000:
            raise EnrichmentError("state_too_large")
        forbidden = ("reply_text", "evidence_excerpt", "source_excerpt", "transcript", "provider_output", "context_card", "bearer ")
        if any(term in raw.casefold() for term in forbidden):
            raise EnrichmentError("state_privacy_violation")


def setup_commands(commands: Any) -> None:
    stage_p = commands.add_parser("enrichment-stage"); stage_p.add_argument("--plan-file", required=True); stage_p.add_argument("--bridge-spec-file")
    attach_p = commands.add_parser("enrichment-attach-bridge"); attach_p.add_argument("--question-id", required=True); attach_p.add_argument("--conversation-id", required=True)
    submit_p = commands.add_parser("enrichment-attention-submit"); submit_p.add_argument("--question-id", required=True)
    dispatch_p = commands.add_parser("enrichment-attention-dispatch"); dispatch_p.add_argument("--question-id", required=True); dispatch_p.add_argument("--intent-id", required=True); dispatch_p.add_argument("--lease-id", required=True)
    recover_p = commands.add_parser("enrichment-attention-recover"); recover_p.add_argument("--question-id", required=True); recover_p.add_argument("--intent-id", required=True)
    complete_p = commands.add_parser("enrichment-attention-complete"); complete_p.add_argument("--question-id", required=True)
    question_p = commands.add_parser("enrichment-question"); question_p.add_argument("--question-id", required=True)
    apply_p = commands.add_parser("enrichment-apply"); apply_p.add_argument("--question-id", required=True); apply_p.add_argument("--bridge-conversation-id", required=True); apply_p.add_argument("--answers-file", required=True)
    cancel_p = commands.add_parser("enrichment-cancel"); cancel_p.add_argument("--question-id", required=True)
    commands.add_parser("enrichment-status")


def handle_cli(args: argparse.Namespace, *, config: RouterConfig, store: EnrichmentStateStore, reconciliation_store: Any = None, transport: Transport | None = None, runner: Any = None) -> int:
    command = str(getattr(args, "context_router_command", ""))
    try:
        if command == "enrichment-stage": result = stage(config, store, Path(args.plan_file), Path(args.bridge_spec_file) if args.bridge_spec_file else None, transport, reconciliation_store)
        elif command == "enrichment-attach-bridge": result = attach_bridge(store, args.question_id, args.conversation_id)
        elif command == "enrichment-attention-submit": result = submit_attention(config, store, args.question_id)
        elif command == "enrichment-attention-dispatch": result = dispatch_attention(config, store, args.question_id, args.intent_id, args.lease_id)
        elif command == "enrichment-attention-recover": result = recover_attention(config, store, args.question_id, args.intent_id, runner=runner)
        elif command == "enrichment-attention-complete": result = complete_attention(store, args.question_id)
        elif command == "enrichment-question": result = question(store, args.question_id)
        elif command == "enrichment-apply": result = apply_answers(config, store, args.question_id, args.bridge_conversation_id, Path(args.answers_file), transport)
        elif command == "enrichment-cancel": result = cancel(store, args.question_id)
        elif command == "enrichment-status": result = status(config, store)
        else: raise EnrichmentError("invalid_cli_command")
    except EnrichmentError as exc:
        result = {"ok": False, "error": exc.code}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


def _enabled(config: RouterConfig) -> EnrichmentConfig:
    cfg = config.kinlayer.enrichment
    if cfg.error: raise EnrichmentError(cfg.error)
    if cfg.mode != "enabled": raise EnrichmentError("enrichment_disabled")
    if not config.kinlayer.base_url: raise EnrichmentError("kinlayer_base_url_missing")
    if len(cfg.owner_ids) != 1 or not all(re.fullmatch(r"[0-9]{1,32}", x) for x in (cfg.guild_id, cfg.channel_id, cfg.parent_channel_id, cfg.owner_ids[0])):
        raise EnrichmentError("enrichment_route_invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,36}", cfg.protected_self_entity_id): raise EnrichmentError("enrichment_protected_self_invalid")
    return cfg


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if len(raw) > 100_000: raise EnrichmentError(code)
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError): raise EnrichmentError(code)
    if not isinstance(value, dict): raise EnrichmentError(code)
    return value


def _validate_slot(value: Any, subject_is_self: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not SLOT_ID.fullmatch(str(value.get("slot_id") or "")): raise EnrichmentError("plan_slot_invalid")
    # Accept the retired field only as bounded legacy metadata; normalize before
    # authorization/fingerprinting so it cannot affect planning or new writes.
    if "sensitivity" in value and value["sensitivity"] not in ("low", "medium", "high"): raise EnrichmentError("plan_slot_invalid")
    value = {k: v for k, v in value.items() if k != "sensitivity"}
    kind = value.get("kind")
    common = {"slot_id", "kind", "claim_type", "ai_use_policy"}
    if value.get("ai_use_policy") != "cautious_use": raise EnrichmentError("plan_slot_invalid")
    if kind == "profile_field":
        if set(value) != common | {"fact_type", "field_path"} or value.get("fact_type") not in {"role", "job", "organization"} or value.get("field_path") != value.get("fact_type") or value.get("claim_type") != "fact": raise EnrichmentError("plan_slot_invalid")
    elif kind == "relationship_edge":
        types = value.get("allowed_relation_types")
        if subject_is_self or set(value) != common | {"direction", "allowed_relation_types", "directed"} or value.get("direction") not in {"self_to_subject", "subject_to_self"} or value.get("directed") is not True or value.get("claim_type") != "fact" or not isinstance(types, list) or types != sorted(set(types)) or not 1 <= len(types) <= 3 or not set(types) <= RELATIONS: raise EnrichmentError("plan_slot_invalid")
    elif kind == "observation":
        types = value.get("allowed_observation_types")
        if set(value) != common | {"allowed_observation_types", "related_entity_id"} or value.get("claim_type") not in {"fact", "preference", "pattern"} or not isinstance(types, list) or types != sorted(set(types)) or not 1 <= len(types) <= 3 or not set(types) <= OBSERVATIONS: raise EnrichmentError("plan_slot_invalid")
        related = value.get("related_entity_id")
        if related is not None and (not subject_is_self or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,36}", str(related))): raise EnrichmentError("plan_slot_invalid")
    else: raise EnrichmentError("plan_slot_invalid")
    return dict(value)


def _validate_plan(value: dict[str, Any], cfg: EnrichmentConfig) -> dict[str, Any]:
    allowed_plan = {"subject", "topic", "question_template_id", "question", "use_case", "slots", "gap_check"}
    if set(value) - allowed_plan or not {"subject", "topic", "question_template_id", "use_case", "slots"} <= set(value): raise EnrichmentError("plan_schema_invalid")
    subject = value.get("subject")
    if not isinstance(subject, Mapping) or set(subject) != {"entity_id", "display_name", "kind", "status"} or subject.get("kind") not in {"self", "person"} or subject.get("status") != "active_confirmed": raise EnrichmentError("plan_subject_invalid")
    entity_id, display = str(subject.get("entity_id") or ""), str(subject.get("display_name") or "")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,36}", entity_id) or not display.strip() or display != display.strip() or len(display) > 80: raise EnrichmentError("plan_subject_invalid")
    if (subject["kind"] == "self") != (entity_id == cfg.protected_self_entity_id): raise EnrichmentError("plan_subject_invalid")
    topic = str(value.get("topic") or "")
    if topic not in TOPICS: raise EnrichmentError("plan_topic_invalid")
    use = value.get("use_case")
    if not isinstance(use, Mapping) or set(use) != {"name", "reuse", "impact", "answerability", "naturalness", "total"} or use.get("name") not in USE_CASES: raise EnrichmentError("plan_score_invalid")
    scores = [use.get(k) for k in ("reuse", "impact", "answerability", "naturalness")]
    if any(type(x) is not int for x in scores) or not 0 <= scores[0] <= 3 or not 0 <= scores[1] <= 3 or not 0 <= scores[2] <= 2 or not 0 <= scores[3] <= 2 or type(use.get("total")) is not int or sum(scores) != use["total"] or scores[3] != 2 or use["total"] < 9: raise EnrichmentError("plan_score_invalid")
    template_id = value.get("question_template_id")
    template = TEMPLATES.get(topic, {}).get(template_id)
    if not template: raise EnrichmentError("plan_question_template_invalid")
    rendered_subject = display if subject["kind"] == "person" else "나"
    q = template.format(subject=rendered_subject)
    if value.get("question") is not None and value["question"] != q: raise EnrichmentError("plan_question_mismatch")
    if len(q) > min(180, cfg.max_message_chars) or q.count("?") != 1 or not q.endswith("?") or any(term.casefold() in q.casefold() for term in QUESTION_DENY): raise EnrichmentError("plan_question_forbidden")
    slots_raw = value.get("slots")
    if not isinstance(slots_raw, list) or not 1 <= len(slots_raw) <= 3: raise EnrichmentError("plan_slot_invalid")
    slots = [_validate_slot(x, subject["kind"] == "self") for x in slots_raw]
    if [x["slot_id"] for x in slots] != sorted(x["slot_id"] for x in slots) or len({x["slot_id"] for x in slots}) != len(slots): raise EnrichmentError("plan_slot_invalid")
    kinds = {x["kind"] for x in slots}
    if len(kinds) != 1: raise EnrichmentError("plan_slots_mixed_predicate")
    topic_shapes = {
        "work_context": ("profile_field", {"role", "job", "organization"}),
        "relationship_context": ("relationship_edge", RELATIONS),
        "communication_preference": ("observation", {"communication_preference"}),
        "interaction_style": ("observation", {"relationship_pattern"}),
        "care_point": ("observation", {"care_point"}),
        "current_context": ("observation", {"stable_fact", "user_feeling"}),
        "recent_interaction": ("observation", {"recent_interaction"}),
        "follow_up_context": ("observation", {"follow_up_context"}),
        "self_boundary": ("observation", {"communication_preference"}),
    }
    required_kind, allowed_types = topic_shapes[topic]
    for slot in slots:
        semantic = {slot["fact_type"]} if required_kind == "profile_field" else set(slot.get("allowed_relation_types", slot.get("allowed_observation_types", [])))
        if slot["kind"] != required_kind or not semantic <= allowed_types:
            raise EnrichmentError("plan_slots_mixed_predicate")
    gap = value.get("gap_check")
    if gap is not None and (not isinstance(gap, Mapping) or set(gap) != {"subject_unique", "canonical_missing", "pending_missing", "checked_at"} or _parse_time(gap.get("checked_at")) is None): raise EnrichmentError("plan_gap_unverified")
    return {"subject": dict(subject), "topic": topic, "question_template_id": template_id, "question": q, "use_case": dict(use), "slots": slots, "gap_check": dict(gap) if gap else None}


def _fingerprint(plan: Mapping[str, Any]) -> str:
    semantics = [{k: v for k, v in slot.items() if k not in {"slot_id", "sensitivity"}} for slot in plan["slots"]]
    return _digest({"subject": plan["subject"]["entity_id"], "topic": plan["topic"], "slots": semantics})


def _active_reconciliation(store: Any) -> bool:
    if store is None:
        path = hermes_home() / "state" / "personal-context-router" / "kinlayer-reconciliation.json"
        try: state = json.loads(path.read_text(encoding="utf-8"))
        except Exception: return False
    else:
        try:
            with store.update() as state:
                now = _now()
                for delivery in state.get("delivery_sets", {}).values():
                    for question in delivery.get("questions", {}).values():
                        staged = _parse_time(question.get("staged_at"))
                        ttl = question.get("bridge_initial_ttl_seconds")
                        if question.get("state") == "staged" and staged and isinstance(ttl, int) and staged + timedelta(seconds=ttl) <= now:
                            question["state"] = "expired"; question["expired_at"] = _iso(now)
                state = json.loads(json.dumps(state))
        except Exception: return True
    return any(q.get("state") in {"staged", "awaiting_reply", "applying", "committed_unverified"} for d in state.get("delivery_sets", {}).values() for q in d.get("questions", {}).values())


def _gates(state: Mapping[str, Any], cfg: EnrichmentConfig, fingerprint: str, subject: str, topic: str) -> None:
    if any(q.get("state") in ACTIVE_STATES for q in state["questions"].values()): raise EnrichmentError("active_enrichment_exists")
    now = _now(); local = now.astimezone(ZoneInfo(cfg.timezone)); current = local.strftime("%H:%M")
    quiet = current >= cfg.quiet_start or current < cfg.quiet_end if cfg.quiet_start > cfg.quiet_end else cfg.quiet_start <= current < cfg.quiet_end
    if quiet: raise EnrichmentError("quiet_hours")
    sent = [_parse_time(x) for x in state.get("sent_at", [])]; sent = [x for x in sent if x]
    if sent and (now - max(sent)).total_seconds() < cfg.global_cooldown_seconds: raise EnrichmentError("global_cooldown")
    if sum(x >= now - timedelta(days=7) for x in sent) >= cfg.weekly_limit: raise EnrichmentError("weekly_limit")
    for key in ("fp:" + fingerprint, "topic:" + subject + ":" + topic, "person:" + subject):
        entry = state.get("suppressions", {}).get(key)
        if entry and (entry.get("until") is None or (_parse_time(entry.get("until")) or now) > now): raise EnrichmentError("suppressed")


def _bridge_spec(cfg: EnrichmentConfig, q: Mapping[str, Any]) -> dict[str, Any]:
    ordinary = cfg.parent_channel_id == cfg.channel_id
    spec = {"adapter_key": "kinlayer-enrichment", "adapter_version": ADAPTER_VERSION, "conversation_key": "pcr-enrich-" + q["plan_digest"][:32], "conversation_ref": q["question_id"], "platform": "discord", "scope_id": cfg.guild_id, "channel_id": cfg.channel_id if ordinary else cfg.parent_channel_id, "thread_id": None if ordinary else cfg.channel_id, "owner_id": cfg.owner_ids[0], "question": q["question"], "skills": ["gyurin-personal-context", "kinlayer-local"], "initial_ttl_seconds": cfg.initial_ttl_seconds, "lease_idle_seconds": cfg.lease_idle_seconds, "idempotency_key": "pcr-enrich-" + q["plan_digest"][:48]}
    try:
        validated = bridge_spec(spec)
    except AttentionError as exc:
        raise EnrichmentError("bridge_spec_invalid") from exc
    if validated != spec: raise EnrichmentError("bridge_spec_invalid")
    return spec


def stage(config: RouterConfig, store: EnrichmentStateStore, plan_file: Path, bridge_spec_file: Path | None = None, transport: Transport | None = None, reconciliation_store: Any = None) -> dict[str, Any]:
    with route_arbitration(store.path.parent):
        return _stage_locked(config, store, plan_file, bridge_spec_file, transport, reconciliation_store)


def _stage_locked(config: RouterConfig, store: EnrichmentStateStore, plan_file: Path, bridge_spec_file: Path | None, transport: Transport | None, reconciliation_store: Any) -> dict[str, Any]:
    cfg = _enabled(config)
    with store.update() as mutable:
        _expire_due(mutable)
    existing = store.read()
    active = [q for q in existing["questions"].values() if q.get("state") in ACTIVE_STATES]
    recovering_authorization = False
    if active:
        if len(active) != 1: raise EnrichmentError("multiple_active_enrichment")
        q = active[0]
        if q.get("state") in {"staged", "awaiting_reply"}:
            result = _public_stage(q, True)
            if bridge_spec_file:
                _write_private_json(bridge_spec_file, _bridge_spec(cfg, q))
                result["bridge_spec_file"] = str(bridge_spec_file)
            return result
        if q.get("state") != "authorizing":
            return {"ok": True, "action": "recovery_pending", "question_id": q["question_id"], "state": q["state"], "resumed": True}
        recovering_authorization = True
    if _active_reconciliation(reconciliation_store): raise EnrichmentError("active_reconciliation_exists")
    plan = _validate_plan(_read_json(plan_file, "plan_file_invalid"), cfg)
    digest = _digest(plan); fp = _fingerprint(plan); qid = "eq_" + digest[:24]
    if recovering_authorization and (q.get("question_id") != qid or q.get("plan_digest") != digest):
        raise EnrichmentError("authorization_recovery_plan_mismatch")
    with store.update() as state:
        if not recovering_authorization:
            _gates(state, cfg, fp, plan["subject"]["entity_id"], plan["topic"])
        prior = state["questions"].get(qid)
        if prior and prior.get("plan_digest") != digest: raise EnrichmentError("stage_id_conflict")
        expires = _now() + timedelta(seconds=cfg.initial_ttl_seconds)
        q = prior or {"question_id": qid, "adapter_version": ADAPTER_VERSION, "state": "authorizing", "plan_digest": digest, "fingerprint": fp, "subject_id": plan["subject"]["entity_id"], "subject_name": plan["subject"]["display_name"], "subject_kind": plan["subject"]["kind"], "topic": plan["topic"], "question": plan["question"], "slots": plan["slots"], "slot_ids": [x["slot_id"] for x in plan["slots"]], "stage_idempotency_key": "enrich.stage." + digest[:48], "created_at": _iso(), "expires_at": _iso(expires), "later_count": 0}
        state["questions"][qid] = q
    payload = {"stage_idempotency_key": q["stage_idempotency_key"], "subject_entity_id": q["subject_id"], "topic": q["topic"], "slots": q["slots"], "expires_at": q["expires_at"]}
    try: auth = _request(config, transport, "POST", "/api/reconciliation/enrichment-authorizations", payload, trusted=True)
    except EnrichmentError as exc:
        if exc.code in {"stale_entity", "stale_gap", "stale_ontology", "gap_filled", "pending_gap_filled", "subject_ambiguous", "kinlayer_http_409", "kinlayer_http_422"}:
            with store.update() as state:
                state["questions"][qid]["state"] = "stale"
                _scrub_authority(state["questions"][qid])
        raise
    capability = auth.get("answer_capability")
    snapshots = auth.get("entity_snapshots")
    compiled_slots = auth.get("slots")
    subject_snapshot = next((x for x in snapshots if isinstance(x, Mapping) and x.get("id") == q["subject_id"]), None) if isinstance(snapshots, list) else None
    if (not isinstance(capability, str) or not re.fullmatch(r"ekc1_[0-9a-f]{64}", capability) or auth.get("status") != "open" or auth.get("subject_entity_id") != q["subject_id"] or auth.get("topic") != q["topic"] or not isinstance(auth.get("id"), str) or not auth.get("id") or not isinstance(auth.get("authorization_ref"), str) or not auth.get("authorization_ref") or not isinstance(snapshots, list) or any(not isinstance(x, Mapping) or set(x) != SNAPSHOT_KEYS for x in snapshots) or not isinstance(subject_snapshot, Mapping) or subject_snapshot.get("entity_type") != "person" or subject_snapshot.get("confirmation_status") != "confirmed" or subject_snapshot.get("status") != "active" or subject_snapshot.get("display_name") != q["subject_name"] or not isinstance(compiled_slots, list) or [x.get("slot_id") for x in compiled_slots if isinstance(x, Mapping)] != q["slot_ids"] or set((auth.get("slot_states") or {}).items()) != {(x, "open") for x in q["slot_ids"]}): raise EnrichmentError("authorization_response_invalid")
    for requested, compiled in zip(q["slots"], compiled_slots):
        expected = {k: v for k, v in requested.items() if k != "sensitivity"}; expected["subject_entity_id"] = q["subject_id"]
        if requested["kind"] == "relationship_edge":
            direction = expected.pop("direction")
            expected["from_entity_id"], expected["to_entity_id"] = ((cfg.protected_self_entity_id, q["subject_id"]) if direction == "self_to_subject" else (q["subject_id"], cfg.protected_self_entity_id))
            expected["related_entity_ids"] = [cfg.protected_self_entity_id]; expected["properties"] = {}
        elif requested["kind"] == "observation":
            related = expected.pop("related_entity_id", None); expected["related_entity_ids"] = [] if related is None else [related]
        if (
            not isinstance(compiled, Mapping)
            or ("sensitivity" in compiled and compiled["sensitivity"] not in ("low", "medium", "high"))
            or {k: v for k, v in compiled.items() if k != "sensitivity"} != expected
        ): raise EnrichmentError("authorization_slots_mismatch")
    with store.update() as state:
        current = state["questions"][qid]; current.update(state="staged", authorization_id=str(auth.get("id")), authorization_ref=str(auth.get("authorization_ref")), capability=capability, authorization_digest=_digest({"subject": subject_snapshot, "slots": compiled_slots, "slot_states": auth.get("slot_states"), "expires_at": auth.get("expires_at")}))
        q = dict(current)
    result = _public_stage(q, False)
    if bridge_spec_file:
        _write_private_json(bridge_spec_file, _bridge_spec(cfg, q))
        result["bridge_spec_file"] = str(bridge_spec_file)
    return result


def _public_stage(q: Mapping[str, Any], resumed: bool) -> dict[str, Any]:
    result = {"ok": True, "action": "resume_bridge" if resumed else "staged", "resumed": resumed, "question_id": q["question_id"], "state": q["state"]}
    if _bridge_id(q): result["bridge_conversation_id"] = _bridge_id(q)
    return result


def _attention_route(cfg: EnrichmentConfig) -> dict[str, Any]:
    ordinary = cfg.parent_channel_id == cfg.channel_id
    return {"platform": "discord", "scope_id": cfg.guild_id, "channel_id": cfg.channel_id if ordinary else cfg.parent_channel_id, "thread_id": None if ordinary else cfg.channel_id, "owner_id": cfg.owner_ids[0]}


def _attention_spec(cfg: EnrichmentConfig, q: Mapping[str, Any]) -> dict[str, Any]:
    created = _parse_time(q.get("created_at")); expires = _parse_time(q.get("expires_at"))
    if created is None or expires is None: raise EnrichmentError("attention_timestamp_invalid")
    return {"producer": ATTENTION_PRODUCER, "intent_ref": q["question_id"], "idempotency_key": "pcr-attention-" + hashlib.sha256((ATTENTION_PRODUCER + "\0" + q["question_id"]).encode()).hexdigest()[:48], **_attention_route(cfg), "priority": "normal", "delivery_mode": "adaptive", "context_tags": [_context_tag(q["subject_id"])], "interruptibility": "deferable", "cooldown_group": "kinlayer-question", "created_at": _iso(created), "not_before": _iso(created), "expires_at": _iso(expires)}


def submit_attention(config: RouterConfig, store: EnrichmentStateStore, question_id: str, runner: Any = None) -> dict[str, Any]:
    cfg = _enabled(config); q = store.read()["questions"].get(question_id)
    if not q: raise EnrichmentError("question_not_found")
    if q.get("state") != "staged": raise EnrichmentError("question_not_attention_submittable")
    prior_attention = _attention(q)
    if prior_attention is not None: return {"ok": True, "action": "attention_submitted", "question_id": question_id, "intent_id": str(prior_attention["intent_id"]), "state": str(prior_attention["state"]), "idempotent": True}
    spec = _attention_spec(cfg, q)
    with store.update() as state:
        target = state["questions"].get(question_id)
        if not target or target.get("state") != "staged": raise EnrichmentError("question_not_attention_submittable")
        try: submitted = attention_submit(spec, runner=runner)
        except AttentionError as exc: raise EnrichmentError("attention_submit_failed") from exc
        prior = _attention(target)
        if prior and prior.get("intent_id") != submitted["intent_id"]: raise EnrichmentError("attention_intent_conflict")
        target["attention"] = {"producer": ATTENTION_PRODUCER, "context_tag": spec["context_tags"][0], "intent_id": submitted["intent_id"], "state": submitted["state"], "submitted_at": (prior or {}).get("submitted_at") or _iso()}
    return {"ok": True, "action": "attention_submitted", "question_id": question_id, "intent_id": submitted["intent_id"], "state": submitted["state"], "idempotent": bool(submitted.get("idempotent"))}


def _cancel_attention_before_send(store: EnrichmentStateStore, question_id: str, intent_id: str, lease_id: str | None, runner: Any) -> dict[str, Any]:
    try: attention_cancel(intent_id, lease_id=lease_id, runner=runner)
    except AttentionError as exc: raise EnrichmentError("attention_cancel_failed") from exc
    with store.update() as state:
        q = state["questions"].get(question_id)
        if not q: raise EnrichmentError("question_not_found")
        value = dict(_attention(q) or {}); value.update(state="cancelled", cancelled_at=_iso()); value.pop("lease_id", None); value.pop("lease_expires_at", None); q["attention"] = value
        if q.get("state") not in TERMINAL_STATES: q["state"] = "expired" if (_parse_time(q.get("expires_at")) or _now()) <= _now() else "cancelled"; q[q["state"] + "_at"] = _iso(); _scrub_authority(q)
    return {"ok": True, "action": "attention_cancelled", "question_id": question_id, "intent_id": intent_id}


def dispatch_attention(config: RouterConfig, store: EnrichmentStateStore, question_id: str, intent_id: str, lease_id: str, runner: Any = None) -> dict[str, Any]:
    cfg = _enabled(config); q = store.read()["questions"].get(question_id)
    if not q: raise EnrichmentError("question_not_found")
    attention = _attention(q)
    if not attention or attention.get("producer") != ATTENTION_PRODUCER or attention.get("intent_id") != intent_id: raise EnrichmentError("attention_authority_mismatch")
    if attention.get("lease_id") not in {None, lease_id}: raise EnrichmentError("attention_authority_mismatch")
    if attention.get("state") == "delivered" and q.get("state") == "awaiting_reply": return {"ok": True, "action": "attention_delivered", "question_id": question_id, "intent_id": intent_id, "idempotent": True}
    if q.get("state") != "staged" or (_parse_time(q.get("expires_at")) or _now()) <= _now(): return _cancel_attention_before_send(store, question_id, intent_id, lease_id, runner)
    conversation_id = str(attention.get("bridge_conversation_id") or "")
    if not conversation_id:
        try: staged = bridge_stage(_bridge_spec(cfg, q), runner=runner)
        except AttentionError as exc:
            try: attention_release(intent_id, lease_id, "failed_before_send", runner=runner)
            except AttentionError: pass
            raise EnrichmentError("bridge_stage_failed") from exc
        conversation_id = str(staged["conversation_id"])
    if attention.get("state") == "queued" or (attention.get("state") == "claimed" and not attention.get("lease_id")):
        with store.update() as state:
            target = state["questions"].get(question_id)
            if not target or target.get("state") != "staged": raise EnrichmentError("question_not_dispatchable")
            value = dict(_attention(target) or {}); existing = value.get("bridge_conversation_id")
            if existing and existing != conversation_id: raise EnrichmentError("bridge_conversation_conflict")
            value.update(state="claimed", claimed_at=value.get("claimed_at") or _iso(), lease_id=lease_id, bridge_conversation_id=conversation_id); target["attention"] = value
        attention = dict(attention); attention.update(state="claimed", claimed_at=attention.get("claimed_at") or _iso(), lease_id=lease_id, bridge_conversation_id=conversation_id)
    if attention.get("state") == "claimed":
        try: attention_begin_delivery(intent_id, lease_id, runner=runner)
        except AttentionError as exc: raise EnrichmentError("attention_begin_failed") from exc
        with store.update() as state:
            target = state["questions"][question_id]; value = dict(_attention(target) or {}); value.update(state="sending", sending_at=value.get("sending_at") or _iso(), lease_id=lease_id, bridge_conversation_id=conversation_id); target["attention"] = value
    try: delivered = bridge_deliver(conversation_id, runner=runner)
    except AttentionError as exc:
        with store.update() as state:
            target = state["questions"].get(question_id)
            if target:
                value = dict(_attention(target) or {}); value.update(state="delivery_unknown", lease_id=lease_id, bridge_conversation_id=conversation_id); target["attention"] = value
        raise EnrichmentError("bridge_delivery_unknown") from exc
    if delivered.get("ok") is not True:
        with store.update() as state:
            target = state["questions"].get(question_id)
            if target: value = dict(_attention(target) or {}); value.update(state="delivery_unknown", lease_id=lease_id, bridge_conversation_id=conversation_id); target["attention"] = value
        return {"ok": False, "action": "delivery_unknown", "question_id": question_id, "intent_id": intent_id}
    try: context = bridge_context(conversation_id, runner=runner); receipt = bridge_status(conversation_id, runner=runner)
    except AttentionError as exc: raise EnrichmentError("bridge_receipt_unavailable") from exc
    if context.get("conversation_ref") != question_id or context.get("adapter") != {"key": "kinlayer-enrichment", "version": ADAPTER_VERSION} or context.get("state") not in DELIVERED_BRIDGE_STATES or receipt.get("state") != context.get("state") or not receipt.get("message_id"): raise EnrichmentError("bridge_receipt_invalid")
    try: attention_complete(intent_id, lease_id, conversation_id, runner=runner)
    except AttentionError as exc: raise EnrichmentError("attention_complete_failed") from exc
    with store.update() as state:
        target = state["questions"].get(question_id)
        if not target: raise EnrichmentError("question_not_found")
        value = dict(_attention(target) or {}); value.update(state="delivered", delivered_at=_iso(), bridge_conversation_id=conversation_id, receipt_ref=conversation_id); value.pop("lease_id", None); value.pop("lease_expires_at", None); target["attention"] = value
        target["state"] = "awaiting_reply"; target["sent_at"] = target.get("sent_at") or _iso()
        if target["sent_at"] not in state["sent_at"]: state["sent_at"].append(target["sent_at"])
    return {"ok": True, "action": "attention_delivered", "question_id": question_id, "intent_id": intent_id, "conversation_id": conversation_id, "idempotent": bool(delivered.get("duplicate"))}


def recover_attention(config: RouterConfig, store: EnrichmentStateStore, question_id: str, intent_id: str, runner: Any = None) -> dict[str, Any]:
    q = store.read()["questions"].get(question_id)
    if not q: raise EnrichmentError("question_not_found")
    attention = _attention(q)
    if not attention or attention.get("producer") != ATTENTION_PRODUCER or attention.get("intent_id") != intent_id: raise EnrichmentError("attention_authority_mismatch")
    state = str(attention.get("state") or "")
    if state in {"delivered", "completed"}: return {"ok": True, "action": "attention_" + state, "question_id": question_id, "intent_id": intent_id, "state": state, "idempotent": True}
    lease_id = str(attention.get("lease_id") or "")
    if state in {"queued", "claimed"} and (q.get("state") != "staged" or (_parse_time(q.get("expires_at")) or _now()) <= _now()): return _cancel_attention_before_send(store, question_id, intent_id, lease_id or None, runner)
    if not lease_id:
        if state in {"queued", "claimed"}: return {"ok": True, "action": "waiting_for_claim_lease_expiry", "state": "claimed"}
        raise EnrichmentError("attention_recovery_lease_missing")
    if state not in {"claimed", "sending", "delivery_unknown"}: raise EnrichmentError("attention_not_recoverable")
    return dispatch_attention(config, store, question_id, intent_id, lease_id, runner=runner)


def complete_attention(store: EnrichmentStateStore, question_id: str, runner: Any = None) -> dict[str, Any]:
    q = store.read()["questions"].get(question_id)
    if not q: raise EnrichmentError("question_not_found")
    attention = _attention(q)
    if attention is None:
        if q.get("state") not in TERMINAL_STATES: raise EnrichmentError("question_not_terminal")
        return {"ok": True, "action": "legacy_no_attention", "question_id": question_id, "idempotent": True}
    if attention.get("state") == "completed": return {"ok": True, "action": "attention_completed", "question_id": question_id, "idempotent": True}
    if q.get("state") not in TERMINAL_STATES or q.get("state") == "cancelled": raise EnrichmentError("question_not_terminal")
    conversation_id = str(attention.get("bridge_conversation_id") or ""); receipt_ref = str(attention.get("receipt_ref") or "")
    if attention.get("state") != "delivered" or not conversation_id or receipt_ref != conversation_id: raise EnrichmentError("attention_not_delivered")
    try:
        if bridge_status(conversation_id, runner=runner).get("state") != "completed": raise EnrichmentError("bridge_not_terminal")
        attention_release_visible(str(attention["intent_id"]), receipt_ref, runner=runner)
    except AttentionError as exc: raise EnrichmentError("attention_release_visible_failed") from exc
    with store.update() as state:
        target = state["questions"].get(question_id)
        if not target: raise EnrichmentError("question_not_found")
        value = dict(_attention(target) or {}); value.update(state="completed", completed_at=_iso()); target["attention"] = value
    return {"ok": True, "action": "attention_completed", "question_id": question_id, "idempotent": False}


def attention_signal_matches(store: EnrichmentStateStore, identity_ids: set[str], cfg: EnrichmentConfig) -> list[dict[str, Any]]:
    matches = []
    for q in store.peek().get("questions", {}).values():
        attention = _attention(q)
        if q.get("state") == "staged" and attention and attention.get("state") == "queued" and str(q.get("subject_id") or "") in identity_ids:
            matches.append({"question_id": str(q["question_id"]), "producer": ATTENTION_PRODUCER, "context_tag": str(attention["context_tag"]), "route": _attention_route(cfg)})
    return matches


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    directory_fd = file_fd = None
    identity: tuple[int, int] | None = None
    complete = False
    try:
        if not path.is_absolute() or not path.name or path != path.parent / path.name:
            raise EnrichmentError("bridge_spec_file_outside_root")
        parent_path = path.parent.lstat()
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
            or (parent.st_dev, parent.st_ino) != (parent_path.st_dev, parent_path.st_ino)
        ):
            raise EnrichmentError("bridge_spec_parent_invalid")
        file_fd = os.open(
            path.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        info = os.fstat(file_fd)
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        identity = (info.st_dev, info.st_ino)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or identity != (current.st_dev, current.st_ino)
        ):
            raise EnrichmentError("bridge_spec_file_invalid")
        os.fchmod(file_fd, 0o600)
        with os.fdopen(file_fd, "w", encoding="utf-8") as stream:
            file_fd = None
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
            parent = os.fstat(directory_fd)
            named_parent = path.parent.lstat()
            written = os.fstat(stream.fileno())
            current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            if (
                stat.S_IMODE(parent.st_mode) != 0o700
                or (parent.st_dev, parent.st_ino) != (named_parent.st_dev, named_parent.st_ino)
                or not stat.S_ISREG(written.st_mode)
                or written.st_nlink != 1
                or stat.S_IMODE(written.st_mode) != 0o600
                or identity != (written.st_dev, written.st_ino)
                or identity != (current.st_dev, current.st_ino)
            ):
                raise EnrichmentError("bridge_spec_file_invalid")
        complete = True
    except FileExistsError as exc:
        raise EnrichmentError("bridge_spec_file_exists") from exc
    except EnrichmentError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise EnrichmentError("bridge_spec_file_invalid") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            if identity is not None and not complete:
                try:
                    current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                    if identity == (current.st_dev, current.st_ino):
                        os.unlink(path.name, dir_fd=directory_fd)
                except OSError:
                    pass
            os.close(directory_fd)


def attach_bridge(store: EnrichmentStateStore, question_id: str, conversation_id: str, runner: Any = None) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(conversation_id): raise EnrichmentError("bridge_conversation_invalid")
    try:
        context = bridge_context(conversation_id, runner=runner)
        bridge_result = bridge_status(conversation_id, runner=runner)
    except AttentionError as exc:
        raise EnrichmentError("bridge_context_unavailable" if exc.code.endswith("_unavailable") else "bridge_not_delivered") from exc
    if context.get("ok") is not True or bridge_result.get("ok") is not True or context.get("conversation_id") != conversation_id or bridge_result.get("conversation_id") != conversation_id or context.get("conversation_ref") != question_id or context.get("adapter") != {"key": "kinlayer-enrichment", "version": ADAPTER_VERSION}:
        raise EnrichmentError("bridge_context_mismatch")
    message_id = bridge_result.get("message_id")
    if context.get("state") not in DELIVERED_BRIDGE_STATES or bridge_result.get("state") != context.get("state") or not isinstance(message_id, str) or not SAFE_ID.fullmatch(message_id): raise EnrichmentError("bridge_not_delivered")
    with store.update() as state:
        q = state["questions"].get(question_id)
        if not q or q.get("state") not in {"staged", "awaiting_reply"}: raise EnrichmentError("question_not_attachable")
        if _attention(q) is not None: raise EnrichmentError("attention_dispatch_required")
        for other in state["questions"].values():
            if other is not q and other.get("bridge_conversation_id") == conversation_id: raise EnrichmentError("bridge_conversation_conflict")
        if q.get("bridge_conversation_id") and q["bridge_conversation_id"] != conversation_id: raise EnrichmentError("bridge_conversation_conflict")
        if q.get("bridge_message_id") and q["bridge_message_id"] != message_id: raise EnrichmentError("bridge_delivery_receipt_mismatch")
        q["bridge_conversation_id"] = conversation_id; q["bridge_message_id"] = message_id; q["state"] = "awaiting_reply"; q["sent_at"] = q.get("sent_at") or _iso()
        if q["sent_at"] not in state["sent_at"]: state["sent_at"].append(q["sent_at"])
    return {"ok": True, "action": "attached", "question_id": question_id, "conversation_id": conversation_id}


def question(store: EnrichmentStateStore, question_id: str) -> dict[str, Any]:
    with store.update() as state:
        _expire_due(state)
        q = json.loads(json.dumps(state["questions"].get(question_id))) if state["questions"].get(question_id) else None
    if not q: raise EnrichmentError("question_not_found")
    slots = []
    for slot in q["slots"]:
        public = {"answer_handle": _answer_handle(q["question_id"], slot["slot_id"]), "kind": slot["kind"]}
        for key in ("fact_type", "field_path", "allowed_relation_types", "allowed_observation_types"):
            if key in slot: public[key] = slot[key]
        slots.append(public)
    return {"ok": True, "state": q["state"], "question": q["question"], "subject_name": q["subject_name"], "topic": q["topic"], "attention_managed": _attention(q) is not None, "slots": slots}


def _answer_handle(question_id: str, slot_id: str) -> str:
    return "eh_" + hashlib.sha256((question_id + "\0" + slot_id).encode()).hexdigest()[:24]


def _secure_answers(path: Path) -> dict[str, Any]:
    root = hermes_home() / "tmp" / "personal-context-router"
    directory_fd = file_fd = None
    opened_identity = None
    name = path.name
    try:
        if not name or name in {".", ".."} or path != path.parent / name: raise EnrichmentError("answers_file_outside_root")
        if path.parent.resolve(strict=True) != root.resolve(strict=True): raise EnrichmentError("answers_file_outside_root")
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        parent_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(parent_info.st_mode) or stat.S_IMODE(parent_info.st_mode) != 0o700: raise EnrichmentError("answers_parent_invalid")
        file_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1: raise EnrichmentError("answers_file_not_regular")
        opened_identity = (info.st_dev, info.st_ino)
        if stat.S_IMODE(info.st_mode) != 0o600: raise EnrichmentError("answers_file_mode_invalid")
        raw = os.read(file_fd, MAX_ANSWER_BYTES + 1)
        if len(raw) > MAX_ANSWER_BYTES: raise EnrichmentError("answers_file_too_large")
        decoder = json.JSONDecoder(); text = raw.decode("utf-8"); value, end = decoder.raw_decode(text)
        if text[end:] != "" or not isinstance(value, dict): raise EnrichmentError("answers_file_invalid")
        return value
    except EnrichmentError: raise
    except (OSError, UnicodeError, json.JSONDecodeError): raise EnrichmentError("answers_file_invalid")
    finally:
        if file_fd is not None: os.close(file_fd)
        if directory_fd is not None:
            try:
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if opened_identity == (current.st_dev, current.st_ino) or stat.S_ISLNK(current.st_mode):
                    os.unlink(name, dir_fd=directory_fd)
            except OSError: pass
            os.close(directory_fd)


def _validate_answers(value: dict[str, Any], q: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    if set(value) != {"reply_text", "answers"} or not isinstance(value.get("reply_text"), str) or len(value["reply_text"]) > MAX_REPLY_CODEPOINTS or not isinstance(value.get("answers"), list) or not 1 <= len(value["answers"]) <= 3: raise EnrichmentError("answers_schema_invalid")
    reply = value["reply_text"]; supplied = value["answers"]
    handle_map = {_answer_handle(q["question_id"], slot_id): slot_id for slot_id in q["slot_ids"]}
    normalized = []
    for raw_answer in supplied:
        if not isinstance(raw_answer, Mapping): raise EnrichmentError("answers_slot_invalid")
        answer = dict(raw_answer)
        handle = answer.pop("answer_handle", None)
        legacy = answer.pop("slot_id", None)
        if handle not in handle_map or legacy is not None: raise EnrichmentError("answers_slot_invalid")
        answer["slot_id"] = handle_map[handle]; normalized.append(answer)
    supplied = normalized
    ids = [x.get("slot_id") for x in supplied]
    if ids != sorted(ids) or len(ids) != len(set(ids)) or not set(ids) <= set(q["slot_ids"]): raise EnrichmentError("answers_slot_invalid")
    slots = {x["slot_id"]: x for x in q["slots"]}; canonical = []; backend = []
    for answer in supplied:
        state = answer.get("state"); slot_id = answer.get("slot_id"); slot = slots[slot_id]
        if state == "known":
            if set(answer) != {"slot_id", "state", "value", "selected_type", "evidence"} or not isinstance(answer.get("value"), str) or answer["value"] != answer["value"].strip() or not 1 <= len(answer["value"]) <= 500: raise EnrichmentError("known_answer_invalid")
            ev = answer.get("evidence")
            if not isinstance(ev, Mapping) or set(ev) != {"start", "end"} or type(ev.get("start")) is not int or type(ev.get("end")) is not int or not 0 <= ev["start"] < ev["end"] <= len(reply): raise EnrichmentError("evidence_invalid")
            excerpt = reply[ev["start"]:ev["end"]]
            if excerpt != excerpt.strip() or not excerpt.strip() or len(excerpt) > 500: raise EnrichmentError("evidence_invalid")
            if answer["value"] != excerpt: raise EnrichmentError("evidence_value_mismatch")
            selected = answer.get("selected_type")
            allowed = [] if slot["kind"] == "profile_field" else slot.get("allowed_relation_types", slot.get("allowed_observation_types", []))
            if slot["kind"] == "profile_field" and selected is not None: raise EnrichmentError("selected_type_invalid")
            if slot["kind"] != "profile_field" and (selected not in allowed if selected is not None else len(allowed) != 1): raise EnrichmentError("selected_type_invalid")
            canonical.append({"slot_id": slot_id, "state": state, "value": answer["value"], "selected_type": selected, "start": ev["start"], "end": ev["end"], "excerpt_digest": _digest(excerpt)})
            backend.append({"slot_id": slot_id, "state": state, "value": answer["value"], "selected_type": selected, "evidence_excerpt": excerpt})
        elif state == "unknown":
            if set(answer) != {"slot_id", "state"}: raise EnrichmentError("unknown_answer_invalid")
            canonical.append({"slot_id": slot_id, "state": state}); backend.append(dict(answer))
        elif state == "skip":
            if set(answer) != {"slot_id", "state", "suppression"} or answer.get("suppression") not in SUPPRESSIONS: raise EnrichmentError("skip_answer_invalid")
            canonical.append(dict(answer)); backend.append({"slot_id": slot_id, "state": state})
        else: raise EnrichmentError("answer_state_invalid")
    return reply, canonical, backend


def apply_answers(config: RouterConfig, store: EnrichmentStateStore, question_id: str, bridge_conversation_id: str, answers_file: Path, transport: Transport | None = None, runner: Any = None) -> dict[str, Any]:
    cfg = _enabled(config)
    q0 = store.read()["questions"].get(question_id)
    if not q0: raise EnrichmentError("question_not_found")
    value = _secure_answers(answers_file)
    reply, canonical, backend_answers = _validate_answers(value, q0)
    answer_input_digest = _digest({"reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(), "answers": canonical})
    if q0.get("state") in TERMINAL_STATES:
        if q0.get("answer_input_digest") == answer_input_digest: return _terminal_result(q0, True)
        raise EnrichmentError("question_not_applicable")
    if _bridge_id(q0) != bridge_conversation_id or not SAFE_ID.fullmatch(bridge_conversation_id): raise EnrichmentError("bridge_conversation_mismatch")
    bundle = {"version": 1, "purpose": "kinlayer-enrichment-answer", "conversation_id": bridge_conversation_id, "conversation_ref": question_id, "question_digest": _digest(q0["question"]), "authorization_id": q0.get("authorization_id"), "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(), "answers": canonical}
    submission_digest = _digest(bundle); resolution_id = "enrich.answer." + submission_digest[:48]
    owner = secrets.token_hex(16)
    with store.update() as state:
        q = state["questions"].get(question_id)
        if not q: raise EnrichmentError("question_not_found")
        if q.get("state") in TERMINAL_STATES:
            if q.get("submission_digest") == submission_digest: return _terminal_result(q, True)
            raise EnrichmentError("question_not_applicable")
        if q.get("state") not in {"awaiting_reply", "applying", "submission_unknown", "committed_unverified"}: raise EnrichmentError("question_not_applicable")
        if not q.get("capability") or not q.get("authorization_id") or set(q["slot_ids"]) != set(q0["slot_ids"]): raise EnrichmentError("authorization_state_invalid")
        if q.get("submission_digest") and q["submission_digest"] != submission_digest: raise EnrichmentError("submission_retry_mismatch")
        lease = q.get("apply_lease")
        lease_expired = not isinstance(lease, Mapping) or (_parse_time(lease.get("expires_at")) or _now()) <= _now()
        if q.get("state") in {"applying", "submission_unknown", "committed_unverified"} and not lease_expired: raise EnrichmentError("recovery_pending")
        if q.get("state") == "applying" and q.get("submission_digest") != submission_digest: raise EnrichmentError("submission_retry_mismatch")
        q["submission_digest"] = submission_digest; q["answer_input_digest"] = answer_input_digest; q["backend_request_digest"] = _digest({"resolution_id": resolution_id, "answers": backend_answers}); q["resolution_id"] = resolution_id
        prior_state = q["state"]
        if prior_state != "committed_unverified": q["state"] = "applying"
        q["apply_lease"] = {"owner": owner, "submission_digest": submission_digest, "expires_at": _iso(_now() + timedelta(seconds=APPLY_LEASE_SECONDS)), "generation": int((lease or {}).get("generation", 0)) + 1}
        capability, authorization_id = q["capability"], q["authorization_id"]
        action_id = q.get("action_id") if prior_state == "committed_unverified" else None
    if prior_state != "committed_unverified":
        try:
            proof_json = bridge_consume_reply_proof(bridge_conversation_id, question_id, submission_digest, reply, timeout=min(cfg.api_timeout, 30.0), runner=runner)
        except AttentionError as exc:
            _restore_after_proof_failure(store, question_id, owner, submission_digest)
            raise EnrichmentError("bridge_reply_proof_unavailable" if exc.code.endswith("_unavailable") else "bridge_reply_proof_invalid")
        if proof_json.get("ok") is not True or proof_json.get("action") != "consume-reply-proof" or proof_json.get("conversation_id") != bridge_conversation_id or proof_json.get("state") not in {"awaiting_first_reply", "bound", "conversing"}:
            _restore_after_proof_failure(store, question_id, owner, submission_digest)
            raise EnrichmentError("bridge_reply_proof_invalid")
    source_excerpt = "\n".join(x["evidence_excerpt"] for x in backend_answers if x["state"] == "known") or None
    payload = {"resolution_id": resolution_id, "authorization_id": authorization_id, "source": {"user_explicit": True, "source_type": "agent_conversation", "source_ref": "enrichment:" + question_id, "source_actor": "user"}, "answers": backend_answers}
    if source_excerpt is not None: payload["source_excerpt"] = source_excerpt
    if not action_id:
        try: receipt = _request(config, transport, "POST", "/api/reconciliation/enrichment-answers", payload, capability=capability)
        except EnrichmentError as exc:
            _owned_transition(store, question_id, owner, submission_digest, {"applying"}, "submission_unknown")
            if exc.code in {"stale_entity", "stale_gap", "stale_ontology", "gap_filled", "pending_gap_filled", "subject_ambiguous", "authorization_expired", "slot_already_answered"}:
                _owned_terminal(store, question_id, owner, submission_digest, "stale")
            raise
        action_id = str(receipt.get("id") or "") if isinstance(receipt, Mapping) else ""
        if not action_id:
            _owned_transition(store, question_id, owner, submission_digest, {"applying"}, "submission_unknown"); raise EnrichmentError("answer_receipt_invalid")
        with store.update() as state:
            q = state["questions"][question_id]
            if not _owns(q, owner, submission_digest, {"applying"}): raise EnrichmentError("recovery_pending")
            q.update(action_id=action_id, state="committed_unverified")
    try: readback = _request(config, transport, "GET", "/api/reconciliation/enrichment-answers/" + action_id, None, capability=capability)
    except EnrichmentError:
        with store.update() as state:
            q = state["questions"].get(question_id)
            if q and _owns(q, owner, submission_digest, {"committed_unverified"}): q["apply_lease"]["expires_at"] = _iso()
        raise
    if not isinstance(readback, Mapping) or readback.get("id") != action_id or readback.get("resolution_id") != resolution_id or readback.get("authorization_id") != authorization_id or readback.get("status") != "verified" or readback.get("verification_state") != "verified": raise EnrichmentError("answer_readback_unverified")
    outcomes = readback.get("slot_outcomes")
    required_outcome_keys = {"slot_id", "state", "candidate_id", "canonical_ref"}
    allowed_outcome_keys = required_outcome_keys | {"candidate_payload_digest", "evidence_digest"}
    if not isinstance(outcomes, list) or any(
        not isinstance(x, Mapping)
        or not required_outcome_keys <= set(x)
        or not set(x) <= allowed_outcome_keys
        for x in outcomes
    ) or [(x.get("slot_id"), x.get("state")) for x in outcomes] != [(x["slot_id"], x["state"]) for x in backend_answers]: raise EnrichmentError("answer_readback_mismatch")
    by_slot = {x["slot_id"]: x for x in backend_answers}
    for outcome in outcomes:
        answer = by_slot[outcome["slot_id"]]
        if answer["state"] == "known" and outcome.get("evidence_digest") != "sha256:" + _digest(answer["evidence_excerpt"]): raise EnrichmentError("answer_readback_digest_mismatch")
        if answer["state"] == "known" and outcome.get("candidate_payload_digest") != _candidate_digest(q0, answer, str(readback.get("episode_id") or ""), cfg): raise EnrichmentError("answer_readback_digest_mismatch")
        if answer["state"] != "known" and any(outcome.get(k) is not None for k in ("candidate_id", "canonical_ref", "candidate_payload_digest", "evidence_digest")): raise EnrichmentError("answer_readback_mismatch")
    known = [x for x in backend_answers if x["state"] == "known"]
    if not known and (readback.get("episode_id") is not None or readback.get("derived_candidate_ids") or readback.get("canonical_refs")): raise EnrichmentError("answer_readback_data_minimization_failed")
    final_state = "verified_applied" if known else ("unknown" if any(x["state"] == "unknown" for x in backend_answers) else "skipped")
    with store.update() as state:
        q = state["questions"][question_id]
        if not _owns(q, owner, submission_digest, {"committed_unverified"}): raise EnrichmentError("recovery_pending")
        q.update(state=final_state, verified_at=_iso(), answer_counts={"known": len(known), "unknown": sum(x["state"] == "unknown" for x in backend_answers), "skip": sum(x["state"] == "skip" for x in backend_answers)}, audit_commitment=_digest({"action_id": action_id, "resolution_id": resolution_id, "outcomes": outcomes}))
        _scrub_authority(q); state["answered_at"].append(q["verified_at"])
        _apply_suppressions(state, q, canonical, cfg)
    return _terminal_result({"state": final_state, "answer_counts": {"known": len(known), "unknown": sum(x["state"] == "unknown" for x in backend_answers), "skip": sum(x["state"] == "skip" for x in backend_answers)}}, False)


def _owns(q: Mapping[str, Any], owner: str, digest: str, states: set[str]) -> bool:
    lease = q.get("apply_lease")
    return q.get("state") in states and isinstance(lease, Mapping) and lease.get("owner") == owner and lease.get("submission_digest") == digest and q.get("submission_digest") == digest


def _owned_transition(store: EnrichmentStateStore, question_id: str, owner: str, digest: str, expected: set[str], target: str) -> None:
    with store.update() as state:
        q = state["questions"].get(question_id)
        if q and _owns(q, owner, digest, expected):
            q["state"] = target
            if isinstance(q.get("apply_lease"), dict): q["apply_lease"]["expires_at"] = _iso()


def _owned_terminal(store: EnrichmentStateStore, question_id: str, owner: str, digest: str, target: str) -> None:
    with store.update() as state:
        q = state["questions"].get(question_id)
        if q and _owns(q, owner, digest, {"applying", "submission_unknown", "committed_unverified"}):
            q["state"] = target; _scrub_authority(q)


def _restore_after_proof_failure(store: EnrichmentStateStore, question_id: str, owner: str, digest: str) -> None:
    with store.update() as state:
        q = state["questions"].get(question_id)
        if q and _owns(q, owner, digest, {"applying"}):
            q["state"] = "committed_unverified" if q.get("action_id") else "awaiting_reply"
            q.pop("apply_lease", None)


def _scrub_authority(q: dict[str, Any]) -> None:
    for key in ("capability", "authorization_ref", "authorization_id", "resolution_id", "action_id", "backend_request_digest", "apply_lease"):
        q.pop(key, None)


def _terminal_result(q: Mapping[str, Any], idempotent: bool) -> dict[str, Any]:
    counts = q.get("answer_counts") if isinstance(q.get("answer_counts"), Mapping) else {}
    verified = q.get("state") in {"verified_applied", "unknown", "skipped"}
    return {"ok": verified, "action": q.get("state"), "verified": verified, "updated_count": int(counts.get("known", 0)), "unknown_count": int(counts.get("unknown", 0)), "skipped_count": int(counts.get("skip", 0)), "bridge_terminal_recommended": True}


def _candidate_digest(q: Mapping[str, Any], answer: Mapping[str, Any], episode_id: str, cfg: EnrichmentConfig) -> str:
    if not episode_id: raise EnrichmentError("answer_readback_mismatch")
    slot = next((x for x in q["slots"] if x["slot_id"] == answer["slot_id"]), None)
    if not slot: raise EnrichmentError("answer_readback_mismatch")
    if slot["kind"] == "profile_field":
        payload = {"entity_id": q["subject_id"], "field_path": slot["field_path"], "fact_type": slot["fact_type"], "content": answer["value"], "value": answer["value"], "claim_type": slot["claim_type"], "ai_use_policy": slot["ai_use_policy"]}
    elif slot["kind"] == "relationship_edge":
        from_id, to_id = ((cfg.protected_self_entity_id, q["subject_id"]) if slot["direction"] == "self_to_subject" else (q["subject_id"], cfg.protected_self_entity_id))
        selected = answer.get("selected_type") or slot["allowed_relation_types"][0]
        payload = {"from_entity_id": from_id, "to_entity_id": to_id, "relation_type": selected, "directed": slot["directed"], "claim_text": answer["value"], "claim_type": slot["claim_type"], "properties": {}}
    else:
        related = slot.get("related_entity_id")
        selected = answer.get("selected_type") or slot["allowed_observation_types"][0]
        payload = {"subject_entity_id": q["subject_id"], "related_entity_ids": [] if related is None else [related], "observation_type": selected, "content": answer["value"], "claim_type": slot["claim_type"], "ai_use_policy": slot["ai_use_policy"]}
    return "sha256:" + _digest(payload)


def _apply_suppressions(state: dict[str, Any], q: dict[str, Any], answers: list[dict[str, Any]], cfg: EnrichmentConfig) -> None:
    now = _now()
    for answer in answers:
        reason = "declined" if answer["state"] == "unknown" else answer.get("suppression")
        if not reason: continue
        if reason == "topic_never": key, until = "topic:" + q["subject_id"] + ":" + q["topic"], None
        elif reason == "person_never": key, until = "person:" + q["subject_id"], None
        else:
            key = "fp:" + q["fingerprint"]
            if reason == "later":
                q["later_count"] = int(q.get("later_count", 0)) + 1; days = cfg.later_snooze_days if q["later_count"] == 1 else cfg.second_later_snooze_days
            else: days = cfg.unknown_suppression_days
            until = _iso(now + timedelta(days=days))
        state["suppressions"][key] = {"reason": reason, "until": until, "updated_at": _iso(now)}


def cancel(store: EnrichmentStateStore, question_id: str, runner: Any = None) -> dict[str, Any]:
    before = store.read(); q0 = before["questions"].get(question_id)
    if not q0: raise EnrichmentError("question_not_found")
    attention0 = _attention(q0)
    if q0.get("state") != "cancelled" and q0.get("state") in {"applying", "submission_unknown", "committed_unverified"}: raise EnrichmentError("question_not_cancellable")
    if q0.get("state") in TERMINAL_STATES - {"cancelled"}: return {"ok": True, "action": "cancelled", "question_id": question_id, "idempotent": True}
    if q0.get("state") == "cancelled" and attention0 and attention0.get("state") == "delivered":
        try:
            conversation_id = str(attention0.get("bridge_conversation_id") or "")
            if bridge_status(conversation_id, runner=runner).get("state") != "cancelled": raise EnrichmentError("bridge_not_terminal")
            attention_release_visible(str(attention0["intent_id"]), str(attention0["receipt_ref"]), runner=runner)
        except AttentionError as exc: raise EnrichmentError("attention_release_visible_failed") from exc
        with store.update() as state:
            value = dict(_attention(state["questions"][question_id]) or {}); value.update(state="completed", completed_at=_iso()); state["questions"][question_id]["attention"] = value
        return {"ok": True, "action": "cancelled", "question_id": question_id, "idempotent": True}
    if attention0 and q0.get("state") != "cancelled":
        try:
            if attention0.get("state") in {"queued", "claimed"}: attention_cancel(str(attention0["intent_id"]), lease_id=str(attention0.get("lease_id") or "") or None, runner=runner)
            elif attention0.get("state") == "delivered":
                conversation_id = str(attention0.get("bridge_conversation_id") or ""); bridge_cancel(conversation_id, outcome="user_cancelled", runner=runner)
                if bridge_status(conversation_id, runner=runner).get("state") != "cancelled": raise EnrichmentError("bridge_not_terminal")
            else: raise EnrichmentError("attention_recovery_required")
        except AttentionError as exc: raise EnrichmentError("attention_cancel_failed") from exc
    with store.update() as state:
        q = state["questions"].get(question_id)
        if not q: raise EnrichmentError("question_not_found")
        if q.get("state") in {"applying", "submission_unknown", "committed_unverified"}: raise EnrichmentError("question_not_cancellable")
        if q.get("state") not in TERMINAL_STATES:
            q["state"] = "cancelled"; q["cancelled_at"] = _iso(); _scrub_authority(q)
            if _attention(q) is not None:
                value = dict(_attention(q) or {})
                if value.get("state") in {"queued", "claimed"}: value.update(state="cancelled", cancelled_at=_iso())
                q["attention"] = value
    if attention0 and attention0.get("state") == "delivered":
        try: attention_release_visible(str(attention0["intent_id"]), str(attention0["receipt_ref"]), runner=runner)
        except AttentionError as exc: raise EnrichmentError("attention_release_visible_failed") from exc
        with store.update() as state:
            value = dict(_attention(state["questions"][question_id]) or {}); value.update(state="completed", completed_at=_iso()); state["questions"][question_id]["attention"] = value
    return {"ok": True, "action": "cancelled", "question_id": question_id}


def status(config: RouterConfig, store: EnrichmentStateStore) -> dict[str, Any]:
    with store.update() as mutable:
        _expire_due(mutable)
    state = store.read(); active = [q for q in state["questions"].values() if q.get("state") in ACTIVE_STATES]
    result = {"ok": True, "mode": config.kinlayer.enrichment.mode, "schema_version": SCHEMA_VERSION, "adapter_version": ADAPTER_VERSION, "active_question": None, "counts": {}}
    for q in state["questions"].values(): result["counts"][q.get("state", "unknown")] = result["counts"].get(q.get("state", "unknown"), 0) + 1
    if len(active) == 1:
        q = active[0]; public = {"question_id": q["question_id"], "state": q["state"], "resumable": q["state"] in {"staged", "awaiting_reply"}}
        if _bridge_id(q): public["bridge_conversation_id"] = _bridge_id(q)
        if _attention(q): public["attention"] = {"intent_id": _attention(q)["intent_id"], "state": _attention(q)["state"]}
        result["active_question"] = public
    return result


def _expire_due(state: dict[str, Any]) -> None:
    now = _now()
    for q in state.get("questions", {}).values():
        expires = _parse_time(q.get("expires_at"))
        if q.get("state") in {"authorizing", "staged", "awaiting_reply"} and expires and expires <= now:
            q["state"] = "expired"
            q["expired_at"] = _iso(now)
            _scrub_authority(q)


def _runtime_secret(name: str) -> str:
    try: return str(importlib.import_module("agent.secret_scope").get_secret(name, "") or "").strip()
    except ImportError: return os.environ.get(name, "").strip()
    except Exception: return ""


def _request(config: RouterConfig, transport: Transport | None, method: str, path: str, payload: dict[str, Any] | None, *, trusted: bool = False, capability: str | None = None) -> dict[str, Any]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if trusted:
        token = _runtime_secret("KINLAYER_RECONCILIATION_TOKEN")
        if not token: raise EnrichmentError("reconciliation_token_missing")
        headers["Authorization"] = "Bearer " + token
    elif capability:
        headers["X-Kinlayer-Enrichment-Capability"] = capability
    else: raise EnrichmentError("enrichment_auth_missing")
    if transport:
        result = transport(method, path, payload, headers, config.kinlayer.enrichment.api_timeout, 200_000)
        if not isinstance(result, dict): raise EnrichmentError("kinlayer_response_invalid")
        return result
    request = Request(config.kinlayer.base_url.rstrip("/") + path, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=config.kinlayer.enrichment.api_timeout) as response: raw = response.read(200_001)
    except HTTPError as exc:
        code = f"kinlayer_http_{exc.code}"
        try:
            body = json.loads(exc.read(20_001)); detail = body.get("error", {}).get("code")
            if detail in {"stale_entity", "stale_gap", "stale_ontology", "gap_filled", "pending_gap_filled", "subject_ambiguous", "authorization_expired", "slot_already_answered"}: code = detail
        except Exception: pass
        raise EnrichmentError(code) from exc
    except (URLError, TimeoutError): raise EnrichmentError("kinlayer_request_failed")
    if len(raw) > 200_000: raise EnrichmentError("kinlayer_response_too_large")
    try: value = json.loads(raw)
    except json.JSONDecodeError: raise EnrichmentError("kinlayer_response_invalid")
    if not isinstance(value, dict): raise EnrichmentError("kinlayer_response_invalid")
    return value
