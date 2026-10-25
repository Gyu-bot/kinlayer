from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
import stat
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from .config import ReconciliationConfig, RouterConfig, hermes_home
from .enrichment import (
    ACTIVE_STATES as ENRICHMENT_ACTIVE_STATES,
    EnrichmentError,
    EnrichmentStateStore,
    _write_private_json as _write_enrichment_private_json,
    route_arbitration,
)
from .attention import (
    AttentionError,
    attention_begin_delivery,
    attention_cancel,
    attention_complete,
    attention_release,
    attention_release_visible,
    attention_signal,
    attention_submit,
    bridge_cancel,
    bridge_consume_reply_proof,
    bridge_context,
    bridge_deliver,
    bridge_spec,
    bridge_stage,
    bridge_status,
)


SCHEMA_VERSION = "reconciliation.v1"
ADAPTER_VERSION = "0.8.0"
TARGET_GUILD_ID = ""  # Legacy symbol; no deployment identifiers in published source.
TARGET_CHANNEL_ID = ""
QUESTION_STATES = {"staged", "awaiting_reply", "applying", "committed_unverified"}
LEGACY_NONTERMINAL_STATES = {"planned", "sending", "delivered", "delivery_failed", "awaiting_reply", "claimed", "applying", "committed_unverified"}
TERMINAL_STATES = {"verified_applied", "deferred", "stale", "expired", "cancelled"}
ALLOWED_OPTIONS = {"map_existing", "different_person", "same_person", "provide_name", "keep", "correct", "do_not_store", "unsure", "confirmed_same_canonical_person", "archive_unwanted_canonical_person"}
ALLOWED_ACTIONS = {"reject_candidates", "map_to_existing_entity", "confirm_new_entity_group", "accept_existing_entity_observation_group", "rename_and_accept_new_entity", "merge_existing_entities", "archive_existing_entity"}
OPTION_ACTIONS = {
    "do_not_store": {"reject_candidates"},
    "map_existing": {"map_to_existing_entity"},
    "same_person": {"confirm_new_entity_group", "accept_existing_entity_observation_group", "rename_and_accept_new_entity"},
    "provide_name": {"rename_and_accept_new_entity"},
    "different_person": {"rename_and_accept_new_entity"},
    "keep": set(),
    "correct": set(),
    "unsure": set(),
    "confirmed_same_canonical_person": {"merge_existing_entities"},
    "archive_unwanted_canonical_person": {"archive_existing_entity"},
}
PLAN_DISPOSITIONS = {"question", "no_anomaly", "keep_open"}
MAX_IDS = 50
MAX_STRING = 500
Transport = Callable[[str, str, dict[str, Any] | None, float, int], dict[str, Any]]
BRIDGE_MARKER_RE = re.compile(r"\[\[HERMES-PCB-CLAIM-V1 token=([A-Za-z0-9_-]{16,256})\]\]")
USER_REPLY_SEPARATOR = "\n[USER-REPLY]\n"
MAX_BRIDGE_USER_TEXT = 4_000
MAX_REPLY_CODEPOINTS = 4_000
MAX_CONTEXT_CLAIMS = 6
MAX_ANSWER_BYTES = 200_000
# Require a meaningful verbatim slice before treating a summary as copied source.
# Full excerpt containment is always blocked, even when shorter.
MIN_SUMMARY_SOURCE_SLICE_CHARS = 16
SAFE_BRIDGE_ID = re.compile(r"^[A-Za-z0-9_.:@/-]{1,160}$")
DELIVERED_BRIDGE_STATES = {"awaiting_first_reply", "bound", "conversing"}
ATTENTION_PRODUCER = "kinlayer-reconciliation"
ATTENTION_STATES = {"queued", "claimed", "sending", "delivery_unknown", "delivered", "completed", "cancelled", "expired"}
ATTENTION_KEYS = {
    "producer", "context_tag", "intent_id", "state", "submitted_at", "claimed_at",
    "sending_at", "delivered_at", "completed_at", "cancelled_at", "lease_id",
    "lease_expires_at", "bridge_conversation_id", "receipt_ref",
}
CONTEXT_TYPE_FIELDS = {
    "profile_field": ("fact_type", {"role", "job", "organization"}),
    "relationship_edge": ("relation_type", {
        "knows", "friend", "family", "acquaintance", "coworker",
        "former_coworker", "client_contact", "vendor_contact", "reports_to",
        "manager_of", "introduced_by", "referred_by", "collaborated_with",
    }),
    "observation": ("observation_type", {
        "stable_fact", "communication_preference", "relationship_pattern",
        "care_point", "recent_interaction", "user_feeling", "follow_up_context",
    }),
}
CONTEXT_ACTIONS = {
    "map_to_existing_entity", "confirm_new_entity_group",
    "accept_existing_entity_observation_group", "rename_and_accept_new_entity",
    "merge_existing_entities",
}
CONTEXT_AI_USE_POLICIES = {"cautious_use", "ask_before_use", "never_surface"}
AI_USE_POLICY_RANK = {
    "freely_use": 0, "cautious_use": 1, "ask_before_use": 2, "never_surface": 3,
}


class ReconciliationError(RuntimeError):
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


def _compact(value: Any, limit: int = MAX_STRING) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _action_material(action: Mapping[str, Any]) -> dict[str, Any]:
    def snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        parsed = _parse_time(result.get("updated_at"))
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            result["updated_at"] = _iso(parsed.astimezone(UTC))
        return result

    return {
        "resolution_id": action["resolution_id"],
        "action": action["action"],
        "candidate_ids": sorted(action.get("candidate_ids", [])),
        "expected_candidates": sorted(
            (snapshot(item) for item in action.get("expected_candidates", [])),
            key=lambda item: item["id"],
        ),
        "expected_entities": sorted(
            (snapshot(item) for item in action.get("expected_entities", [])),
            key=lambda item: item["id"],
        ),
        "source_entity_id": action.get("source_entity_id"),
        "target_entity_id": action.get("target_entity_id"),
        "canonical_name": action.get("canonical_name"),
        "display_name": action.get("display_name"),
        "relationship_to_self": action.get("relationship_to_self"),
        "resolution_note": action["resolution_note"],
        "source": action["source"],
        "context_claims": action.get("context_claims", []),
    }


def _answer_binding(
    q: Mapping[str, Any], item_id: str, action: Mapping[str, Any]
) -> dict[str, Any]:
    key = _runtime_secret("KINLAYER_RECONCILIATION_COMMITMENT_KEY")
    key_bytes = key.encode()
    if len(key_bytes) < 32:
        raise ReconciliationError("reconciliation_binding_key_missing")
    token = _runtime_secret("KINLAYER_RECONCILIATION_TOKEN")
    if token and hmac.compare_digest(key_bytes, token.encode()):
        raise ReconciliationError("reconciliation_binding_key_reused")
    agenda = _validated_agenda(q)
    item = next((entry for entry in agenda if entry.get("item_id") == item_id), None)
    if item is None:
        raise ReconciliationError("agenda_state_invalid")
    material = {
        "version": "pcr-reconciliation-binding.v1",
        "question_id": q["question_id"],
        "answer_item_id": item_id,
        "item_fingerprint": item["fingerprint"],
        "agenda_digest": _digest(agenda),
        "resolution_id": action["resolution_id"],
        "action": action["action"],
        "context_claims_digest": _digest(action.get("context_claims", [])),
        "action_digest": _digest(_action_material(action)),
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **material,
        "commitment": "hmac-sha256:" + hmac.new(
            key_bytes, raw.encode(), hashlib.sha256
        ).hexdigest(),
    }


def _context_tag(value: Any) -> str:
    return "person:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _attention(q: Mapping[str, Any]) -> Mapping[str, Any] | None:
    value = q.get("attention")
    return value if isinstance(value, Mapping) else None


def _bridge_id(q: Mapping[str, Any]) -> str | None:
    value = (_attention(q) or {}).get("bridge_conversation_id") or q.get("bridge_conversation_id")
    return str(value) if value else None


def _validate_attention(value: Any, question_id: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping) or set(value) - ATTENTION_KEYS:
        raise ReconciliationError("state_attention_invalid")
    required = {"producer", "context_tag", "intent_id", "state", "submitted_at"}
    if not required <= set(value) or value.get("producer") != ATTENTION_PRODUCER:
        raise ReconciliationError("state_attention_invalid")
    for key in ("intent_id", "lease_id", "bridge_conversation_id", "receipt_ref"):
        item = value.get(key)
        if item is not None and not SAFE_BRIDGE_ID.fullmatch(str(item)):
            raise ReconciliationError("state_attention_invalid")
    if not re.fullmatch(r"person:[0-9a-f]{32}", str(value.get("context_tag") or "")):
        raise ReconciliationError("state_attention_invalid")
    if value.get("state") not in ATTENTION_STATES or _parse_time(value.get("submitted_at")) is None:
        raise ReconciliationError("state_attention_invalid")
    for key in ("claimed_at", "sending_at", "delivered_at", "completed_at", "cancelled_at", "lease_expires_at"):
        if value.get(key) is not None and _parse_time(value[key]) is None:
            raise ReconciliationError("state_attention_invalid")
    transient = {"claimed", "sending", "delivery_unknown"}
    if value.get("lease_id") is not None and value.get("state") not in transient:
        raise ReconciliationError("state_attention_invalid")
    if value.get("receipt_ref") is not None and value.get("state") not in {"delivered", "completed"}:
        raise ReconciliationError("state_attention_invalid")


def _secure_answers(path: Path, root_override: Path | None = None) -> dict[str, Any]:
    """Read and unlink one private answer envelope through a verified directory FD."""
    root = root_override if root_override is not None else hermes_home() / "tmp" / "personal-context-router"
    directory_fd = file_fd = None
    opened_identity: tuple[int, int] | None = None
    name = path.name
    try:
        if not path.is_absolute() or not name or name in {".", ".."} or path != path.parent / name:
            raise ReconciliationError("answers_file_outside_root")
        root_resolved = root.resolve(strict=True)
        parent_root = path.parent.resolve(strict=True) if root_override is not None else path.parent.parent.resolve(strict=True)
        if parent_root != root_resolved:
            raise ReconciliationError("answers_file_outside_root")
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(parent_info.st_mode) or stat.S_IMODE(parent_info.st_mode) != 0o700:
            raise ReconciliationError("answers_parent_invalid")
        file_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ReconciliationError("answers_file_not_regular")
        opened_identity = (info.st_dev, info.st_ino)
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise ReconciliationError("answers_file_mode_invalid")
        chunks = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(65_536, MAX_ANSWER_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_ANSWER_BYTES:
                raise ReconciliationError("answers_file_too_large")
        raw = b"".join(chunks)
        decoder = json.JSONDecoder()
        text = raw.decode("utf-8")
        value, end = decoder.raw_decode(text)
        if text[end:] != "" or not isinstance(value, dict):
            raise ReconciliationError("answers_schema_invalid")
        return value
    except ReconciliationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise ReconciliationError("answers_file_invalid") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            try:
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if opened_identity == (current.st_dev, current.st_ino) or stat.S_ISLNK(current.st_mode):
                    os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
            os.close(directory_fd)


def _read_stage_plan(path: Path) -> dict[str, Any]:
    """Consume every private-run plan once; keep legacy raw-free plans reusable."""
    root = hermes_home() / "tmp" / "personal-context-router"
    private = (
        path.is_absolute()
        and path.name not in {"", ".", ".."}
        and path.parent.parent == root
    )
    if not private:
        directory_fd = file_fd = None
        identity: tuple[int, int] | None = None
        source_bearing = False
        try:
            directory_fd = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            file_fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
            opened = os.fstat(file_fd)
            identity = (opened.st_dev, opened.st_ino)
            chunks = []
            total = 0
            while True:
                chunk = os.read(file_fd, min(65_536, 1_000_001 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                raw = b"".join(chunks)
                source_bearing = source_bearing or any(
                    b'"' + key + b'"' in raw
                    for key in (
                        b"prepared_context_claims", b"candidate_evidence_handle",
                        b"evidence_excerpt", b"source_ref", b"evidence_id",
                        b"episode_id", b"body_hash",
                    )
                )
                if total > 1_000_000:
                    raise ReconciliationError("input_too_large")
            text = b"".join(chunks).decode("utf-8")
            value, end = json.JSONDecoder().raw_decode(text)
            if text[end:] or not isinstance(value, dict):
                raise ReconciliationError("input_invalid")
            def has_source(item: Any) -> bool:
                if isinstance(item, Mapping):
                    if set(item) & {
                        "prepared_context_claims", "candidate_evidence_handle",
                        "evidence_excerpt", "source_ref", "evidence_id", "episode_id",
                        "body_hash",
                    }:
                        return True
                    return any(has_source(child) for child in item.values())
                if isinstance(item, list):
                    return any(has_source(child) for child in item)
                return False
            source_bearing = source_bearing or has_source(value)
            if source_bearing:
                raise ReconciliationError("plan_file_outside_root")
            return value
        except ReconciliationError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise ReconciliationError("input_invalid") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                if source_bearing and identity is not None:
                    try:
                        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                        if identity == (current.st_dev, current.st_ino):
                            os.unlink(path.name, dir_fd=directory_fd)
                    except OSError:
                        pass
                os.close(directory_fd)

    directory_fd = file_fd = None
    identity: tuple[int, int] | None = None
    try:
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        parent = os.fstat(directory_fd)
        try:
            file_fd = os.open(
                path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory_fd,
            )
        except OSError:
            current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
            identity = (current.st_dev, current.st_ino)
            raise
        opened = os.fstat(file_fd)
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise ReconciliationError("plan_file_private_mode_invalid")
        chunks = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(65_536, 1_000_001 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 1_000_000:
                raise ReconciliationError("input_too_large")
        parent = os.fstat(directory_fd)
        opened = os.fstat(file_fd)
        current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            stat.S_IMODE(parent.st_mode) != 0o700
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o600
            or identity != (opened.st_dev, opened.st_ino)
            or identity != (current.st_dev, current.st_ino)
        ):
            raise ReconciliationError("plan_file_private_mode_invalid")
        text = b"".join(chunks).decode("utf-8")
        value, end = json.JSONDecoder().raw_decode(text)
        if text[end:] or not isinstance(value, dict):
            raise ReconciliationError("input_invalid")
        return value
    except ReconciliationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise ReconciliationError("input_invalid") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            if identity is not None:
                try:
                    current = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
                    if identity == (current.st_dev, current.st_ino):
                        os.unlink(path.name, dir_fd=directory_fd)
                except OSError:
                    pass
            os.close(directory_fd)


def _validated_agenda(q: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if q.get("adapter_version") != ADAPTER_VERSION:
        return []
    agenda = q.get("agenda")
    if not isinstance(agenda, list) or not 1 <= len(agenda) <= MAX_IDS:
        raise ReconciliationError("agenda_state_invalid")
    if any(not isinstance(entry, Mapping) for entry in agenda):
        raise ReconciliationError("agenda_state_invalid")
    if [entry.get("item_id") for entry in agenda] != q.get("item_ids"):
        raise ReconciliationError("agenda_state_invalid")
    if [entry.get("fingerprint") for entry in agenda] != q.get("item_fingerprints"):
        raise ReconciliationError("agenda_state_invalid")
    if q.get("message") != agenda[0].get("question") or q.get("message_digest") != _digest(q.get("message")):
        raise ReconciliationError("agenda_state_invalid")
    for entry in agenda:
        if set(entry) not in (
            {"item_id", "fingerprint", "question", "options", "record_summaries"},
            {"item_id", "fingerprint", "question", "options", "record_summaries", "prepared_context_claims"},
        ):
            raise ReconciliationError("agenda_state_invalid")
        _validate_natural_question(str(entry["question"]))
        options = entry["options"]
        summaries = entry["record_summaries"]
        if not isinstance(options, list) or not options or len(options) != len(set(options)) or any(option not in OPTION_ACTIONS for option in options):
            raise ReconciliationError("agenda_state_invalid")
        if not isinstance(summaries, list) or len(summaries) > MAX_IDS or any(not isinstance(summary, Mapping) or set(summary) != {"record_id", "record_digest", "summary"} for summary in summaries):
            raise ReconciliationError("agenda_state_invalid")
        try:
            for summary in summaries:
                _validate_record_summary(summary["summary"])
        except ReconciliationError as exc:
            raise ReconciliationError("agenda_state_invalid") from exc
        claims = entry.get("prepared_context_claims", [])
        if claims and not any(OPTION_ACTIONS[str(option)] & CONTEXT_ACTIONS for option in options):
            raise ReconciliationError("agenda_state_invalid")
        if (
            not isinstance(claims, list)
            or len(claims) > MAX_CONTEXT_CLAIMS
            or any(
                not isinstance(claim, Mapping)
                or claim.get("answer_item_id") != entry.get("item_id")
                or not _stored_prepared_claim_valid(claim)
                for claim in claims
            )
        ):
            raise ReconciliationError("agenda_state_invalid")
        claim_ids = [str(claim.get("claim_id") or "") for claim in claims]
        if claim_ids != sorted(set(claim_ids)) or len({_claim_semantic(claim) for claim in claims}) != len(claims):
            raise ReconciliationError("agenda_state_invalid")
    return agenda


def _claim_semantic(claim: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        claim.get("answer_item_id") or claim.get("item_id"),
        claim.get("kind"),
        claim.get("fact_type"),
        claim.get("field_path"),
        claim.get("relation_type"),
        claim.get("observation_type"),
    )


def _claim_typing_valid(claim: Mapping[str, Any]) -> bool:
    claim_id = claim.get("claim_id")
    kind = str(claim.get("kind") or "")
    if not isinstance(claim_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", claim_id):
        return False
    if claim.get("target") != "primary_entity" or kind not in CONTEXT_TYPE_FIELDS:
        return False
    type_key, allowed_types = CONTEXT_TYPE_FIELDS[kind]
    selected = claim.get(type_key)
    if selected not in allowed_types:
        return False
    if kind == "profile_field":
        return claim.get("field_path") == selected and claim.get("claim_type") == "fact"
    if kind == "relationship_edge":
        return claim.get("claim_type") == "fact"
    return claim.get("claim_type") in {"fact", "preference", "pattern"}


def _stored_prepared_claim_valid(claim: Mapping[str, Any]) -> bool:
    type_keys = {"fact_type", "field_path", "relation_type", "observation_type"}
    allowed = {
        "claim_id", "answer_item_id", "target", "kind", "claim_type",
        "sensitivity", "ai_use_policy", "evidence", *type_keys,
    }
    evidence = claim.get("evidence")
    if (
        set(claim) - allowed
        or not _claim_typing_valid(claim)
        or ("sensitivity" in claim and claim["sensitivity"] not in ("low", "medium", "high"))
        or claim.get("ai_use_policy") not in CONTEXT_AI_USE_POLICIES
        or not isinstance(evidence, Mapping)
        or set(evidence) != {
            "evidence_class", "handle", "candidate_id", "evidence_id", "episode_id",
            "body_hash", "excerpt_hash", "start", "end",
        }
        or evidence.get("evidence_class") != "prepared_candidate_evidence"
        or not re.fullmatch(r"evidence:[0-9a-f]{32}", str(evidence.get("handle") or ""))
        or any(not str(evidence.get(key) or "") or len(str(evidence[key])) > 120 for key in ("candidate_id", "evidence_id", "episode_id"))
        or any(not re.fullmatch(r"sha256:[0-9a-f]{64}", str(evidence.get(key) or "")) for key in ("body_hash", "excerpt_hash"))
        or type(evidence.get("start")) is not int
        or type(evidence.get("end")) is not int
        or not 0 <= evidence["start"] < evidence["end"] <= 500
    ):
        return False
    kind = str(claim.get("kind") or "")
    selected_key = CONTEXT_TYPE_FIELDS[kind][0]
    permitted = {selected_key} | ({"field_path"} if kind == "profile_field" else set())
    return not any(key in claim for key in type_keys - permitted)


class StateStore:
    """PluginState-compatible store with a locked, mode-0600 file fallback."""

    def __init__(self, plugin_state: Any = None, path: Path | None = None):
        self.plugin_state = plugin_state
        self.path = path or hermes_home() / "state" / "personal-context-router" / "kinlayer-reconciliation.json"
        self.lock_path = self.path.with_suffix(".lock")

    def _plugin_read(self) -> dict[str, Any] | None:
        state = self.plugin_state
        if state is None:
            return None
        try:
            if isinstance(state, Mapping):
                value = state.get(SCHEMA_VERSION, {})
            elif callable(getattr(state, "get", None)):
                value = state.get(SCHEMA_VERSION, {})
            else:
                return None
            return dict(value) if isinstance(value, Mapping) else {}
        except Exception:
            return None

    def _plugin_write(self, value: dict[str, Any]) -> bool:
        state = self.plugin_state
        if state is None:
            return False
        try:
            if callable(getattr(state, "set", None)):
                state.set(SCHEMA_VERSION, value)
            else:
                state[SCHEMA_VERSION] = value
            return True
        except Exception:
            return False

    @contextmanager
    def update(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            with os.fdopen(fd, "r+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                state = self._plugin_read()
                if state is None:
                    state = self._read_file()
                state.setdefault("schema_version", SCHEMA_VERSION)
                state.setdefault("fingerprints", {})
                state.setdefault("prepared_items", {})
                state.setdefault("delivery_sets", {})
                # Preserve legacy claim records read-only until explicit deployment migration.
                state.setdefault("claims", {})
                state.setdefault("run_audits", {})
                try:
                    yield state
                except Exception:
                    raise
                else:
                    self._validate_state(state)
                    if not self._plugin_write(state):
                        self._write_file(state)
        finally:
            pass

    def read(self) -> dict[str, Any]:
        with self.update() as state:
            return json.loads(json.dumps(state))

    def peek(self) -> dict[str, Any]:
        """Best-effort read for output guards; never creates or rewrites state."""
        state = self._plugin_read()
        if state is None:
            state = self._read_file()
        state.setdefault("schema_version", SCHEMA_VERSION)
        state.setdefault("fingerprints", {})
        state.setdefault("prepared_items", {})
        state.setdefault("delivery_sets", {})
        return json.loads(json.dumps(state))

    def _read_file(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _write_file(self, state: dict[str, Any]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=".reconciliation-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    @staticmethod
    def _validate_state(state: dict[str, Any]) -> None:
        if state.get("schema_version") != SCHEMA_VERSION:
            raise ReconciliationError("state_schema_invalid")
        encoded = json.dumps(state, ensure_ascii=False)
        if len(encoded) > 2_000_000:
            raise ReconciliationError("state_too_large")
        lowered = encoded.casefold()
        for forbidden in (
            "raw_transcript", "session_body", "provider_response", "bot_token", "bearer ",
            '"reply_text"', '"reply_proof"', '"answers_file"', '"consumed_submission_digest"',
            '"evidence_excerpt"', '"prepared_context_sources"',
        ):
            if forbidden in lowered:
                raise ReconciliationError("state_privacy_violation")
        for delivery in state.get("delivery_sets", {}).values():
            for q in delivery.get("questions", {}).values():
                agenda = _validated_agenda(q)
                for entry in agenda:
                    prepared = state.get("prepared_items", {}).get(entry.get("item_id"))
                    if not isinstance(prepared, Mapping) or any(
                        not _stored_claim_matches_prepared(claim, prepared)
                        for claim in entry.get("prepared_context_claims", [])
                    ):
                        raise ReconciliationError("agenda_state_invalid")
                _validate_attention(q.get("attention"), str(q.get("question_id") or ""))
                for key in ("submission_digest", "last_submission_digest"):
                    value = q.get(key)
                    if value is not None and not re.fullmatch(r"[0-9a-f]{64}", str(value)):
                        raise ReconciliationError("state_submission_digest_invalid")
                message_id = q.get("bridge_message_id")
                if message_id is not None and not SAFE_BRIDGE_ID.fullmatch(str(message_id)):
                    raise ReconciliationError("state_bridge_receipt_invalid")
                cached = q.get("last_apply_result")
                if cached is not None and (
                    not isinstance(cached, Mapping)
                    or cached.get("ok") is not True
                    or cached.get("question_id") != q.get("question_id")
                    or len(json.dumps(cached, ensure_ascii=False)) > 100_000
                ):
                    raise ReconciliationError("state_apply_result_invalid")


def _stored_claim_matches_prepared(
    claim: Mapping[str, Any], prepared: Mapping[str, Any]
) -> bool:
    evidence = claim.get("evidence")
    if not isinstance(evidence, Mapping):
        return False
    matches = [
        commitment
        for candidate in prepared.get("candidates", [])
        if isinstance(candidate, Mapping)
        for commitment in candidate.get("evidence", [])
        if isinstance(commitment, Mapping) and commitment.get("handle") == evidence.get("handle")
    ]
    if len(matches) != 1:
        return False
    commitment = matches[0]
    return (
        all(evidence.get(key) == commitment.get(key) for key in (
            "candidate_id", "evidence_id", "episode_id", "body_hash", "excerpt_hash"
        ))
        and claim.get("ai_use_policy") == commitment.get("effective_ai_use_policy")
        and type(evidence.get("end")) is int
        and evidence["end"] <= int(commitment.get("excerpt_codepoints") or 0)
    )


def setup_cli(parser: argparse.ArgumentParser) -> None:
    commands = parser.add_subparsers(dest="context_router_command", required=True)
    setup_commands(commands)


def setup_commands(commands: Any) -> None:
    prepare = commands.add_parser("reconciliation-prepare")
    prepare.add_argument("--quiet-no-change", action="store_true")
    stage = commands.add_parser("reconciliation-stage")
    stage.add_argument("--plan-file", required=True)
    stage.add_argument("--bridge-spec-file")
    attach = commands.add_parser("reconciliation-attach-bridge")
    attach.add_argument("--question-id", required=True)
    attach.add_argument("--conversation-id", required=True)
    attention_submit_parser = commands.add_parser("reconciliation-attention-submit")
    attention_submit_parser.add_argument("--question-id", required=True)
    attention_dispatch_parser = commands.add_parser("reconciliation-attention-dispatch")
    attention_dispatch_parser.add_argument("--question-id", required=True)
    attention_dispatch_parser.add_argument("--intent-id", required=True)
    attention_dispatch_parser.add_argument("--lease-id", required=True)
    attention_recover_parser = commands.add_parser("reconciliation-attention-recover")
    attention_recover_parser.add_argument("--question-id", required=True)
    attention_recover_parser.add_argument("--intent-id", required=True)
    attention_complete_parser = commands.add_parser("reconciliation-attention-complete")
    attention_complete_parser.add_argument("--question-id", required=True)
    deliver = commands.add_parser("reconciliation-deliver")
    deliver.add_argument("--delivery-set-id", required=True)
    question = commands.add_parser("reconciliation-question")
    question.add_argument("--question-id", required=True)
    question.add_argument("--bridge-conversation-id", required=True)
    apply = commands.add_parser("reconciliation-apply")
    apply.add_argument("--question-id", required=True)
    apply.add_argument("--bridge-conversation-id", required=True)
    apply.add_argument("--answers-file", required=True)
    cancel = commands.add_parser("reconciliation-cancel")
    cancel.add_argument("--question-id", required=True)
    reissue = commands.add_parser("reconciliation-reissue-expired")
    reissue.add_argument("--question-id", required=True)
    reissue.add_argument("--bridge-spec-file", required=True)
    commands.add_parser("reconciliation-status")


def handle_cli(
    args: argparse.Namespace,
    *,
    config: RouterConfig,
    store: StateStore,
    transport: Transport | None = None,
    runner: Any = None,
) -> int:
    command = str(getattr(args, "context_router_command", ""))
    try:
        if command == "reconciliation-prepare":
            result = prepare(config, store, transport)
        elif command == "reconciliation-stage":
            result = stage(
                config,
                store,
                Path(args.plan_file),
                Path(args.bridge_spec_file) if getattr(args, "bridge_spec_file", None) else None,
                transport,
            )
        elif command == "reconciliation-attach-bridge":
            result = attach_bridge(store, str(args.question_id), str(args.conversation_id))
        elif command == "reconciliation-attention-submit":
            result = submit_attention(config, store, str(args.question_id))
        elif command == "reconciliation-attention-dispatch":
            result = dispatch_attention(config, store, str(args.question_id), str(args.intent_id), str(args.lease_id))
        elif command == "reconciliation-attention-recover":
            result = recover_attention(config, store, str(args.question_id), str(args.intent_id), runner=runner)
        elif command == "reconciliation-attention-complete":
            result = complete_attention(store, str(args.question_id))
        elif command == "reconciliation-deliver":
            result = deliver(config, store, str(args.delivery_set_id))
        elif command == "reconciliation-question":
            result = question(store, str(args.question_id), str(args.bridge_conversation_id))
        elif command == "reconciliation-apply":
            result = apply_answers(config, store, str(args.question_id), str(args.bridge_conversation_id), Path(args.answers_file), transport)
        elif command == "reconciliation-cancel":
            result = cancel_question(store, str(args.question_id))
        elif command == "reconciliation-reissue-expired":
            result = reissue_expired_question(
                config,
                store,
                str(args.question_id),
                Path(args.bridge_spec_file),
            )
        elif command == "reconciliation-status":
            result = status(config, store)
        else:
            raise ReconciliationError("invalid_cli_command")
    except ReconciliationError as exc:
        result = {"ok": False, "error": exc.code}
    quiet = bool(getattr(args, "quiet_no_change", False))
    if not (quiet and result.get("ok") and result.get("action") in {"disabled", "no_change"}):
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


def _enabled(config: RouterConfig) -> ReconciliationConfig:
    cfg = config.kinlayer.reconciliation
    if cfg.error:
        raise ReconciliationError(cfg.error)
    if cfg.mode == "disabled":
        raise ReconciliationError("reconciliation_disabled")
    if (not re.fullmatch(r"[0-9]{1,32}", cfg.approved_guild_id) or
            not re.fullmatch(r"[0-9]{1,32}", cfg.approved_channel_id) or
            cfg.guild_id != cfg.approved_guild_id or cfg.channel_id != cfg.approved_channel_id):
        raise ReconciliationError("reconciliation_target_invalid")
    if len(cfg.owner_ids) != 1:
        raise ReconciliationError("reconciliation_owner_invalid")
    if not re.fullmatch(r"[0-9]{1,32}", cfg.reconciliation_parent_channel_id):
        raise ReconciliationError("reconciliation_parent_channel_missing")
    if not 300 <= cfg.initial_ttl_seconds <= 604_800 or not 1_800 <= cfg.lease_idle_seconds <= 3_600:
        raise ReconciliationError("reconciliation_bridge_ttl_invalid")
    if not config.kinlayer.base_url:
        raise ReconciliationError("kinlayer_base_url_missing")
    return cfg


def _entity_snapshot_items(
    config: RouterConfig,
    transport: Transport | None,
    cfg: ReconciliationConfig,
) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    total: int | None = None
    offset = 0
    while True:
        listing = _request(
            config,
            transport,
            "GET",
            f"/api/reconciliation/entity-snapshots?limit=200&offset={offset}",
            None,
            auth=True,
        )
        page = listing.get("items")
        page_total = listing.get("total")
        if (
            not isinstance(page, list)
            or len(page) > 200
            or any(not isinstance(item, Mapping) or _entity_snapshot(item) is None for item in page)
            or not isinstance(page_total, int)
            or isinstance(page_total, bool)
            or page_total < offset + len(page)
            or (total is not None and page_total != total)
        ):
            raise ReconciliationError("entity_snapshot_list_invalid")
        total = page_total
        if total > cfg.entity_snapshot_limit:
            raise ReconciliationError("entity_snapshot_bound_exceeded")
        items.extend(page)
        if len(items) == total:
            break
        if not page:
            raise ReconciliationError("entity_snapshot_list_invalid")
        offset += len(page)
    ids = [str(item.get("id") or item.get("entity_id") or "") for item in items]
    if len(ids) != len(set(ids)):
        raise ReconciliationError("entity_snapshot_list_invalid")
    return items


def prepare(config: RouterConfig, store: StateStore, transport: Transport | None = None) -> dict[str, Any]:
    if config.kinlayer.reconciliation.mode == "disabled":
        return {"ok": True, "action": "disabled", "schema_version": SCHEMA_VERSION}
    cfg = _enabled(config)
    state_before = store.read()
    run_cursor = state_before.get("last_run_cursor")
    listing = _request(
        config, transport, "GET",
        f"/api/curation/runs?mode=apply&status=completed&limit={min(cfg.canonical_limit, 200)}&offset=0",
        None, auth=False,
    )
    summaries = listing.get("items")
    if not isinstance(summaries, list) or len(summaries) > min(cfg.canonical_limit, 200):
        raise ReconciliationError("run_list_invalid")
    total = listing.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < len(summaries):
        raise ReconciliationError("run_list_invalid")
    summary_rows: list[tuple[dict[str, str], Mapping[str, Any]]] = []
    for summary in summaries:
        if not isinstance(summary, Mapping):
            raise ReconciliationError("run_list_invalid")
        cursor = _run_cursor(summary)
        summary_rows.append((cursor, summary))
    if any(
        _cursor_key(summary_rows[index][0]) < _cursor_key(summary_rows[index + 1][0])
        for index in range(len(summary_rows) - 1)
    ):
        raise ReconciliationError("run_list_order_invalid")
    if (
        run_cursor
        and len(summary_rows) == min(cfg.canonical_limit, 200)
        and summary_rows
        and _cursor_key(summary_rows[-1][0]) > _cursor_key(run_cursor)
    ):
        raise ReconciliationError("run_backlog_exceeds_bound")
    relevant = []
    for cursor, summary in reversed(summary_rows):
        if run_cursor and _cursor_key(cursor) <= _cursor_key(run_cursor):
            continue
        run_id = _compact(summary.get("id"), 128)
        if not run_id or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ReconciliationError("run_list_invalid")
        detail = _request(config, transport, "GET", f"/api/curation/runs/{run_id}", None, auth=False)
        if _compact(detail.get("id"), 128) != run_id or detail.get("mode") != "apply" or detail.get("status") != "completed":
            raise ReconciliationError("run_detail_invalid")
        relevant.append((cursor, detail))
    payload = {"limit": min(cfg.candidate_limit, 200), "max_age_days": cfg.max_age_days, "max_evidence_per_candidate": 20, "max_excerpt_chars": 500}
    source = _request(config, transport, "POST", "/api/curation/source-packs", payload, auth=False)
    candidates = source.get("candidates", [])
    if not candidates and isinstance(source.get("groups"), list):
        candidates = [candidate for group in source["groups"] if isinstance(group, Mapping) for candidate in list(group.get("candidates", []))]
    canonicals = source.get("recent_canonical", source.get("canonical_records", []))
    entities = source.get("entities", [])
    aliases = source.get("aliases", [])
    if not all(isinstance(value, list) for value in (candidates, canonicals, entities, aliases)):
        raise ReconciliationError("source_pack_invalid")
    candidates, canonicals, entities, aliases = map(
        list, (candidates, canonicals, entities, aliases)
    )
    entities.extend(_entity_snapshot_items(config, transport, cfg))
    if isinstance(source.get("groups"), list):
        for group in source["groups"]:
            if not isinstance(group, Mapping):
                continue
            context = group.get("target_context")
            if isinstance(context, Mapping):
                if isinstance(context.get("entity"), Mapping):
                    entities.append(context["entity"])
                aliases.extend(value for value in list(context.get("aliases", [])) if isinstance(value, Mapping))
            for candidate in list(group.get("candidates", [])):
                if isinstance(candidate, dict) and group.get("signals"):
                    candidate.setdefault("duplicate_signals", list(group.get("signals", []))[:20])
    run_canonicals, needed_candidate_ids = _canonical_writes(relevant)
    if len(needed_candidate_ids) > min(cfg.candidate_limit, 200):
        raise ReconciliationError("candidate_detail_budget_exceeded")
    known_candidate_ids = {str(item.get("id") or "") for item in candidates if isinstance(item, Mapping)}
    for candidate_id in needed_candidate_ids - known_candidate_ids:
        detail = _request(config, transport, "GET", f"/api/candidates/{candidate_id}", None, auth=False)
        if _compact(detail.get("id"), 120) != candidate_id:
            raise ReconciliationError("candidate_detail_invalid")
        candidates.append(detail)
    candidate_sources: dict[str, tuple[list[str], list[str]]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        refs = sorted({
            _compact(evidence.get("source_ref"), 240)
            for evidence in list(candidate.get("evidence", []))[:20]
            if isinstance(evidence, Mapping) and evidence.get("actor") == "user" and evidence.get("source_ref")
        })
        candidate_sources[_compact(candidate.get("id"), 120)] = (refs, sorted({_source_session_id(ref) for ref in refs if _source_session_id(ref)}))
    for canonical in run_canonicals:
        pairs = [candidate_sources.get(candidate_id, ([], [])) for candidate_id in canonical.pop("candidate_ids", [])]
        canonical["source_refs"] = sorted({ref for refs, _ in pairs for ref in refs})[:20]
        canonical["source_session_ids"] = sorted({session for _, sessions in pairs for session in sessions})[:20]
    canonicals.extend(run_canonicals)
    items = build_anomalies(candidates, canonicals, entities, aliases, cfg)
    run_by_ref = {
        ref: cursor
        for cursor, detail in relevant
        for ref in _run_canonical_refs(detail)
    }
    for item in items:
        cursors = [run_by_ref[ref] for ref in item.get("canonical_refs", []) if ref in run_by_ref]
        if cursors:
            item["run_cursor"] = max(cursors, key=_cursor_key)
    now = _now()
    output: list[dict[str, Any]] = []
    with store.update() as state:
        fingerprints = state["fingerprints"]
        prepared = state["prepared_items"]
        open_question_fingerprints = {
            fingerprint
            for delivery_set in state["delivery_sets"].values()
            for question_item in delivery_set.get("questions", {}).values()
            if question_item.get("state") in QUESTION_STATES
            for fingerprint in question_item.get("item_fingerprints", [])
        }
        for item in items:
            prior = fingerprints.get(item["fingerprint"], {})
            if prior.get("terminal") is True:
                continue
            if item["fingerprint"] in open_question_fingerprints:
                continue
            suppressed = _parse_time(prior.get("suppressed_until"))
            if suppressed and suppressed > now:
                continue
            prepared[item["item_id"]] = item
            fingerprints[item["fingerprint"]] = {"item_id": item["item_id"], "seen_at": _iso(now)}
            output.append(item)
        state["current_prepared_item_ids"] = [item["item_id"] for item in output]
        state["last_candidate_cursor"] = _bounded_cursor(source.get("candidate_cursor"))
        for cursor, detail in relevant:
            run_id = _compact(detail.get("id"), 128)
            run_items = [item["fingerprint"] for item in items if item.get("run_cursor") == cursor]
            state["run_audits"][run_id] = {"cursor": cursor, "fingerprints": run_items, "reviewed": not run_items}
        _advance_run_cursor(state)
    return {"ok": True, "action": "prepared" if output else "no_change", "items": output, "count": len(output)}


def build_anomalies(candidates: list[Any], canonicals: list[Any], entities: list[Any], aliases: list[Any], cfg: ReconciliationConfig) -> list[dict[str, Any]]:
    entity_names: dict[str, list[dict[str, Any]]] = {}
    snapshots_by_id = {
        snapshot["id"]: snapshot
        for entity in entities
        if isinstance(entity, Mapping)
        for snapshot in [_entity_snapshot(entity)]
        if snapshot
    }
    seen_entity_names: set[tuple[str, str]] = set()
    for entity in entities + aliases:
        if not isinstance(entity, Mapping):
            continue
        name = _name(entity)
        if name:
            snapshot = _entity_snapshot(entity) or snapshots_by_id.get(_compact(entity.get("entity_id"), 36))
            if snapshot:
                key = (snapshot["id"], _normalize(name))
                if key in seen_entity_names:
                    continue
                seen_entity_names.add(key)
                entity_names.setdefault(key[1], []).append({"name": name, "snapshot": snapshot})
    all_entities = [entry for values in entity_names.values() for entry in values]
    grouped: dict[str, list[dict[str, Any]]] = {}
    ordered_candidates = sorted(
        [
            raw
            for raw in candidates
            if isinstance(raw, Mapping)
            and str(raw.get("status", "pending"))
            in {"pending", "blocked", "needs_clarification"}
        ],
        key=lambda raw: (
            _compact(raw.get("id"), 120),
            _compact(raw.get("updated_at"), 80),
            _compact(raw.get("payload_digest"), 80),
            _compact(raw.get("evidence_digest"), 80),
            _digest(raw),
        ),
    )
    eligible_candidates: list[Mapping[str, Any]] = []
    candidate_source_digests: dict[str, str] = {}
    for raw in ordered_candidates:
        source_id = _compact(raw.get("id"), 120)
        source_digest = _digest(raw)
        previous_digest = candidate_source_digests.get(source_id)
        if previous_digest is not None:
            if previous_digest != source_digest:
                raise ReconciliationError("candidate_source_duplicate_id")
            continue
        candidate_source_digests[source_id] = source_digest
        eligible_candidates.append(raw)
    for raw in eligible_candidates[: cfg.candidate_limit]:
        candidate = _candidate_snapshot(raw)
        name = _name(raw)
        key = _compact(raw.get("person_key") or raw.get("unresolved_identity_key") or raw.get("duplicate_group_id"), 160) or _normalize(name) or _compact(raw.get("target_entity_id") or raw.get("id"), 160)
        grouped.setdefault(key, []).append(candidate)
    results: list[dict[str, Any]] = []
    for key, members in grouped.items():
        members = sorted(members, key=lambda value: (str(value["id"]), str(value["fingerprint"])))
        names = sorted({_name(item) for item in members if _name(item)})
        kind = _classify_group(key, members, entity_names)
        observation_targets = {
            member.get("target_entity_id")
            for member in members
            if member.get("candidate_type") == "observation"
        }
        observation_target_id = (
            next(iter(observation_targets))
            if len(observation_targets) == 1
            and None not in observation_targets
            and all(member.get("candidate_type") == "observation" for member in members)
            else None
        )
        if observation_target_id:
            exact_observation_target = snapshots_by_id.get(observation_target_id)
            reviewed_target = (
                {"snapshot": exact_observation_target}
                if exact_observation_target else None
            )
        else:
            matched_entities = {
                entry["snapshot"]["id"]: entry
                for name in names
                for entry in all_entities
                if _likely_same_name(_normalize(name), _normalize(entry["name"]))
            }
            reviewed_target = (
                next(iter(matched_entities.values())) if len(matched_entities) == 1 else None
            )
        snapshot = {
            "kind": kind,
            "person_key": key,
            "candidate_ids": [m["id"] for m in members],
            "candidate_fingerprints": [m["fingerprint"] for m in members],
            "target_entity_id": reviewed_target["snapshot"]["id"] if reviewed_target else None,
            "target_entity_digest": reviewed_target["snapshot"]["entity_digest"] if reviewed_target else None,
        }
        fingerprint = _digest(snapshot)
        source_refs = sorted({_compact(e.get("source_ref"), 240) for m in members for e in m["evidence"] if e.get("source_ref")})[:20]
        session_ids = sorted({_source_session_id(ref) for ref in source_refs if _source_session_id(ref)})[:20]
        options = _options_for(kind)
        if reviewed_target is None:
            options = [option for option in options if option != "map_existing"]
        elif "map_existing" not in options:
            options = ["map_existing", *options]
        results.append({
            "item_id": "ri_" + fingerprint[7:31], "fingerprint": fingerprint, "kind": kind,
            "person_key": key[:160], "display_names": names[:10], "candidates": members[:MAX_IDS],
            "source_session_ids": session_ids, "source_refs": source_refs,
            "search_terms": names[:5], "current_fingerprint": fingerprint,
            "target_entity_id": reviewed_target["snapshot"]["id"] if reviewed_target else None,
            "expected_entities": [reviewed_target["snapshot"]] if reviewed_target else [],
            "allowed_options": options, "prepared_at": _iso(),
        })
    canonical_entities: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for raw in canonicals[: cfg.canonical_limit]:
        if not isinstance(raw, Mapping) or not raw.get("anomaly_signals"):
            if isinstance(raw, Mapping) and (_compact(raw.get("type"), 80) in {"entity", "entities", "person"} or _compact(raw.get("entity_type"), 80) == "person"):
                snapshot = _entity_snapshot(raw)
                if snapshot is None:
                    raw_id = _compact(raw.get("id") or raw.get("entity_id"), 36)
                    snapshot = next((entry["snapshot"] for values in entity_names.values() for entry in values if entry["snapshot"]["id"] == raw_id), None)
                if snapshot:
                    canonical_entities.append((raw, snapshot))
                    compact = {"id": snapshot["id"], "type": "person", "updated_at": snapshot["updated_at"], "anomaly_signals": []}
                    fingerprint = _digest({"kind": "recent_canonical_person_review", "entity": snapshot, "canonical_refs": list(raw.get("canonical_refs", []))[:MAX_IDS]})
                    results.append(
                        {
                            "item_id": "ri_" + fingerprint[7:31],
                            "fingerprint": fingerprint,
                            "kind": "recent_canonical_person_review",
                            "person_key": _normalize(_name(raw)) or snapshot["id"],
                            "display_names": [_name(raw)] if _name(raw) else [],
                            "candidates": [],
                            "canonical": compact,
                            "canonical_refs": list(raw.get("canonical_refs", []))[:MAX_IDS],
                            "source_session_ids": list(raw.get("source_session_ids", []))[:20],
                            "source_refs": list(raw.get("source_refs", []))[:20],
                            "search_terms": [_name(raw)] if _name(raw) else [],
                            "source_entity_id": snapshot["id"],
                            "target_entity_id": None,
                            "expected_entities": [snapshot],
                            "current_fingerprint": fingerprint,
                            "allowed_options": [
                                "keep",
                                "archive_unwanted_canonical_person",
                                "unsure",
                            ],
                            "prepared_at": _iso(),
                        }
                    )
            elif isinstance(raw, Mapping) and raw.get("canonical_refs"):
                compact = {"id": _compact(raw.get("id"), 120), "type": _compact(raw.get("type"), 80), "updated_at": _compact(raw.get("updated_at"), 80), "anomaly_signals": []}
                fingerprint = _digest({"kind": "recent_canonical_write_review", "canonical": compact, "canonical_refs": list(raw.get("canonical_refs", []))[:MAX_IDS]})
                results.append({"item_id": "ri_" + fingerprint[7:31], "fingerprint": fingerprint, "kind": "recent_canonical_write_review", "person_key": compact["id"], "display_names": [], "candidates": [], "canonical": compact, "canonical_refs": list(raw.get("canonical_refs", []))[:MAX_IDS], "source_session_ids": list(raw.get("source_session_ids", []))[:20], "source_refs": list(raw.get("source_refs", []))[:20], "search_terms": [], "current_fingerprint": fingerprint, "allowed_options": ["keep", "unsure"], "prepared_at": _iso()})
            continue
        compact = {"id": _compact(raw.get("id"), 120), "type": _compact(raw.get("type"), 80), "updated_at": _compact(raw.get("updated_at"), 80), "anomaly_signals": [_compact(x, 120) for x in list(raw.get("anomaly_signals", []))[:10]]}
        fingerprint = _digest(compact)
        results.append({"item_id": "ri_" + fingerprint[7:31], "fingerprint": fingerprint, "kind": "recent_canonical_anomaly", "person_key": _normalize(_name(raw)) or compact["id"], "display_names": [_name(raw)] if _name(raw) else [], "candidates": [], "canonical": compact, "canonical_refs": list(raw.get("canonical_refs", []))[:MAX_IDS], "source_session_ids": list(raw.get("source_session_ids", []))[:20], "source_refs": list(raw.get("source_refs", []))[:20], "search_terms": [_name(raw)] if _name(raw) else [], "current_fingerprint": fingerprint, "allowed_options": _options_for("recent_canonical_anomaly"), "prepared_at": _iso()})
    for raw, source_snapshot in canonical_entities:
        source_name = _name(raw)
        normalized = _normalize(source_name)
        matches = [entry for entry in all_entities if entry["snapshot"]["id"] != source_snapshot["id"] and _likely_same_name(normalized, _normalize(entry["name"]))]
        for match in matches[:5]:
            expected = sorted([source_snapshot, match["snapshot"]], key=lambda value: value["id"])
            fingerprint = _digest({"kind": "duplicate_canonical_person", "expected_entities": expected})
            refs = list(raw.get("canonical_refs", []))[:MAX_IDS]
            results.append({"item_id": "ri_" + fingerprint[7:31], "fingerprint": fingerprint, "kind": "duplicate_canonical_person", "person_key": normalized or source_snapshot["id"], "display_names": sorted({source_name, match["name"]}), "candidates": [], "canonical_refs": refs, "source_session_ids": list(raw.get("source_session_ids", []))[:20], "source_refs": list(raw.get("source_refs", []))[:20], "search_terms": [source_name], "source_entity_id": source_snapshot["id"], "target_entity_id": match["snapshot"]["id"], "expected_entities": expected, "current_fingerprint": fingerprint, "allowed_options": ["confirmed_same_canonical_person", "keep", "unsure"], "prepared_at": _iso()})
    return sorted(results, key=lambda item: (item["kind"], item["person_key"], item["item_id"]))[: cfg.hard_question_limit * 4]


def _run_cursor(run: Mapping[str, Any]) -> dict[str, str]:
    created = _compact(run.get("started_at"), 80)
    run_id = _compact(run.get("id"), 128)
    if not created or not run_id or _parse_time(created) is None:
        raise ReconciliationError("run_cursor_invalid")
    return {"started_at": created, "run_id": run_id}


def _cursor_key(cursor: Mapping[str, Any]) -> tuple[datetime, str]:
    parsed = _parse_time(cursor.get("started_at") or cursor.get("completed_at"))
    if parsed is None:
        raise ReconciliationError("run_cursor_invalid")
    return parsed, _compact(cursor.get("run_id"), 128)


def _run_canonical_refs(run: Mapping[str, Any]) -> set[str]:
    return {
        _compact(decision.get("canonical_record_ref"), 160)
        for decision in list(run.get("decisions", []))[:200]
        if isinstance(decision, Mapping)
        and decision.get("status") == "executed"
        and decision.get("readback_status") == "verified"
        and decision.get("canonical_record_ref")
    }


def _canonical_writes(relevant: list[tuple[dict[str, str], Mapping[str, Any]]]) -> tuple[list[dict[str, Any]], set[str]]:
    records: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    for _, run in relevant:
        decisions = run.get("decisions")
        if not isinstance(decisions, list) or len(decisions) > 200:
            raise ReconciliationError("run_detail_invalid")
        for decision in decisions:
            if not isinstance(decision, Mapping) or decision.get("status") != "executed" or decision.get("readback_status") != "verified":
                continue
            ref = _compact(decision.get("canonical_record_ref"), 160)
            if not ref:
                continue
            ids = [_compact(value, 120) for value in list(decision.get("candidate_ids", []))[:MAX_IDS]]
            candidate_ids.update(value for value in ids if value)
            summary_value = decision.get("readback_summary")
            summary: Mapping[str, Any] = summary_value if isinstance(summary_value, Mapping) else {}
            entity_payload = summary.get("entity")
            target_payload = summary.get("target_entity")
            if isinstance(entity_payload, Mapping):
                raw = entity_payload
            elif isinstance(target_payload, Mapping):
                raw = target_payload
            else:
                raw = summary
            record = {
                "id": _compact(raw.get("id") or ref.partition(":")[2], 120),
                "type": _compact(raw.get("type") or raw.get("entity_type") or ref.partition(":")[0], 80),
                "entity_type": _compact(raw.get("entity_type"), 80),
                "display_name": _compact(raw.get("display_name"), 160),
                "canonical_name": _compact(raw.get("canonical_name"), 160),
                "status": _compact(raw.get("status"), 40),
                "updated_at": _compact(raw.get("updated_at") or decision.get("updated_at"), 80),
                "entity_digest": _compact(raw.get("entity_digest"), 80),
                "canonical_refs": [ref],
                "candidate_ids": ids,
                "readback_summary": {key: _compact(summary.get(key), 160) for key in ("entity_id", "record_type", "verification") if summary.get(key) is not None},
            }
            records.append(record)
    return records, candidate_ids


def _entity_snapshot(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    entity_id = _compact(raw.get("id") or raw.get("entity_id"), 36)
    status = _compact(raw.get("status"), 40)
    updated_at = _compact(raw.get("updated_at"), 80)
    digest = _compact(raw.get("entity_digest"), 80)
    if not entity_id or not status or _parse_time(updated_at) is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        return None
    return {"id": entity_id, "status": status, "updated_at": updated_at, "entity_digest": digest}


def _likely_same_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    a, b = (left, right) if len(left) <= len(right) else (right, left)
    return len(a) >= 3 and (a in b or _edit_distance_at_most_one(a, b))


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1] <= 1


def _mark_terminal(state: dict[str, Any], fingerprint: str, resolution: str) -> None:
    state["fingerprints"].setdefault(fingerprint, {}).update({"terminal": True, "resolution": resolution, "resolved_at": _iso()})


def _review_run_items(state: dict[str, Any], fingerprints: set[str]) -> None:
    for audit in state.get("run_audits", {}).values():
        if set(audit.get("fingerprints", [])).issubset({fp for fp, value in state["fingerprints"].items() if value.get("terminal") or fp in fingerprints}):
            audit["reviewed"] = True
    _advance_run_cursor(state)


def _advance_run_cursor(state: dict[str, Any]) -> None:
    audits = sorted(state.get("run_audits", {}).values(), key=lambda value: _cursor_key(value["cursor"]))
    current = state.get("last_run_cursor")
    for audit in audits:
        if current and _cursor_key(audit["cursor"]) <= _cursor_key(current):
            continue
        if not audit.get("reviewed"):
            break
        current = audit["cursor"]
    if current:
        state["last_run_cursor"] = current


def _bridge_conversation_key(person_key: str, fingerprints: list[str]) -> str:
    material = json.dumps(
        {"person_key": person_key, "fingerprints": sorted(fingerprints)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "pcr-person-" + hashlib.sha256(material).hexdigest()[:48]


def _bridge_spec_for_question(
    config: RouterConfig,
    delivery: Mapping[str, Any],
    q: Mapping[str, Any],
) -> dict[str, Any]:
    cfg = config.kinlayer.reconciliation
    fingerprints = sorted(str(value) for value in q.get("item_fingerprints", []))
    conversation_key = str(q.get("bridge_conversation_key") or "")
    if not conversation_key:
        conversation_key = _bridge_conversation_key(str(q.get("person_key") or ""), fingerprints)
    idempotency_key = str(q.get("bridge_idempotency_key") or "")
    if not idempotency_key:
        idempotency_key = "pcr:" + _digest(
            {"question_id": q["question_id"], "fingerprints": fingerprints}
        )[7:]
    owner_ids = delivery.get("owner_ids") or cfg.owner_ids
    if not isinstance(owner_ids, (list, tuple)) or len(owner_ids) != 1:
        raise ReconciliationError("bridge_owner_metadata_invalid")
    target_channel_id = str(delivery.get("channel_id") or cfg.channel_id)
    route_parent_channel_id = str(
        delivery.get("parent_channel_id") or cfg.reconciliation_parent_channel_id
    )
    ordinary_channel = route_parent_channel_id == target_channel_id
    return bridge_spec({
        "adapter_key": "kinlayer-reconciliation",
        "adapter_version": str(q.get("adapter_version") or ADAPTER_VERSION),
        "conversation_key": conversation_key,
        "conversation_ref": str(q["question_id"]),
        "platform": "discord",
        "scope_id": str(delivery.get("guild_id") or cfg.guild_id),
        "channel_id": target_channel_id if ordinary_channel else route_parent_channel_id,
        "thread_id": None if ordinary_channel else target_channel_id,
        "owner_id": str(owner_ids[0]),
        "question": str(q["message"]),
        "skills": ["gyurin-personal-context", "kinlayer-local"],
        "initial_ttl_seconds": int(q.get("bridge_initial_ttl_seconds") or cfg.initial_ttl_seconds),
        "lease_idle_seconds": int(q.get("bridge_lease_idle_seconds") or cfg.lease_idle_seconds),
        "idempotency_key": idempotency_key,
    })


def stage(
    config: RouterConfig,
    store: StateStore,
    plan_file: Path,
    bridge_spec_file: Path | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    plan = _read_stage_plan(plan_file) if os.path.lexists(plan_file) else {}
    with route_arbitration(store.path.parent):
        enrichment_path = store.path.parent / "kinlayer-enrichment.json"
        try:
            enrichment_store = EnrichmentStateStore(path=enrichment_path)
            with enrichment_store.update() as enrichment_state:
                for question in enrichment_state.get("questions", {}).values():
                    expires = _parse_time(question.get("expires_at"))
                    if question.get("state") in {"authorizing", "staged"} and expires and expires <= _now():
                        question["state"] = "expired"; question["expired_at"] = _iso()
                        for key in ("capability", "authorization_ref", "authorization_id", "resolution_id", "action_id", "backend_request_digest", "apply_lease"): question.pop(key, None)
                enrichment_state = json.loads(json.dumps(enrichment_state))
        except Exception as exc:
            raise ReconciliationError("enrichment_state_unavailable") from exc
        if any(q.get("state") in ENRICHMENT_ACTIVE_STATES for q in enrichment_state.get("questions", {}).values() if isinstance(q, Mapping)):
            raise ReconciliationError("active_enrichment_exists")
        return _stage_locked(config, store, plan, bridge_spec_file, transport)


def _stage_locked(
    config: RouterConfig,
    store: StateStore,
    plan: Mapping[str, Any],
    bridge_spec_file: Path | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    cfg = _enabled(config)
    delivery_id = "ds_" + secrets.token_hex(12)
    result: dict[str, Any]
    plan_record_identifiers: set[str] = set()
    with store.update() as state:
        legacy = _legacy_report(state)
        if legacy["applying"] or legacy["committed_unverified"]:
            raise ReconciliationError("legacy_action_in_progress")
        if any(legacy[name] for name in ("awaiting_reply", "claimed", "other_nonterminal")):
            raise ReconciliationError("legacy_state_requires_migration")
        active = [
            (delivery, q) for delivery in state["delivery_sets"].values()
            for q in delivery.get("questions", {}).values()
            if q.get("adapter_version") == ADAPTER_VERSION and q.get("state") in QUESTION_STATES
        ]
        if active:
            if len(active) != 1:
                raise ReconciliationError("active_bridge_question_exists")
            active_delivery, active_q = active[0]
            if active_q.get("state") not in {"staged", "awaiting_reply"}:
                raise ReconciliationError("active_bridge_question_exists")
            result = {
                "ok": True,
                "action": "resume_bridge",
                "resumed": True,
                "delivery_set_id": str(active_delivery["delivery_set_id"]),
                "question_id": str(active_q["question_id"]),
                "state": str(active_q["state"]),
                **(
                    {"bridge_conversation_id": str(_bridge_id(active_q))}
                    if _bridge_id(active_q) else {}
                ),
            }
        else:
            if set(plan) - {"items", "rationale"} or not isinstance(plan.get("items"), list):
                raise ReconciliationError("plan_schema_invalid")
            plan_item_ids = {
                str(entry.get("item_id") or "")
                for entry in plan["items"]
                if isinstance(entry, Mapping)
            }
            plan_record_identifiers = {
                identifier
                for entry in plan["items"]
                if isinstance(entry, Mapping)
                for item in [state["prepared_items"].get(str(entry.get("item_id") or ""))]
                if isinstance(item, Mapping)
                for binding in _summary_record_bindings(item)
                for identifier in (binding["record_id"], binding["record_digest"])
                if identifier
            }
            closed_item_ids = {
                str(item_id)
                for delivery in state["delivery_sets"].values()
                for q in delivery.get("questions", {}).values()
                if q.get("adapter_version") == ADAPTER_VERSION
                and q.get("state") in TERMINAL_STATES
                for item_id in (
                    q.get("resolved_item_ids", [])
                    if q.get("state") == "deferred"
                    else q.get("item_ids", [])
                )
            }
            if plan_item_ids & closed_item_ids:
                raise ReconciliationError("question_already_terminal")
            result = {}
        if result:
            pass
        else:
            question_groups: dict[str, list[tuple[dict[str, Any], Mapping[str, Any]]]] = {}
            reviewed_fingerprints: set[str] = set()
            for entry in plan["items"]:
                question_item = _validate_plan_item(
                    entry,
                    state["prepared_items"],
                    set(state.get("current_prepared_item_ids", [])),
                    plan_record_identifiers,
                )
                disposition = entry["disposition"]
                if disposition == "no_anomaly":
                    _mark_terminal(state, question_item["fingerprint"], "audited_no_anomaly")
                    reviewed_fingerprints.add(question_item["fingerprint"])
                    continue
                if disposition == "keep_open":
                    continue
                question_groups.setdefault(question_item["person_key"], []).append((question_item, entry))
            _review_run_items(state, reviewed_fingerprints)
            if not question_groups:
                return {"ok": True, "action": "no_questions", "count": 0}
            person_key = sorted(question_groups)[0]
            all_members = question_groups[person_key]
            members = all_members[:cfg.operational_question_limit]
            visible_summaries = [
                str(summary.get("summary") or "")
                for _, entry in members
                for summary in entry.get("record_summaries", [])
                if isinstance(summary, Mapping)
            ]
            visible_questions = [str(entry["question"]) for _, entry in members]
            _assert_visible_texts_do_not_expose_prepared_excerpts(
                members, [*visible_questions, *visible_summaries]
            )
            agenda = [
                {
                    "item_id": item["item_id"],
                    "fingerprint": item["fingerprint"],
                    "question": str(entry["question"]),
                    "options": [str(option) for option in entry["options"]],
                    "record_summaries": _validate_record_summaries(
                        entry.get("record_summaries"), item, plan_record_identifiers
                    ),
                    **(
                        {"prepared_context_claims": _stage_prepared_context_claims(
                            config, transport, item, entry, visible_summaries
                        )}
                        if entry.get("prepared_context_claims")
                        else {}
                    ),
                }
                for item, entry in members
            ]
            rendered_message = agenda[0]["question"]
            if len(rendered_message) > min(cfg.max_message_chars, 1_800):
                raise ReconciliationError("question_too_large")
            qid = "rq_" + secrets.token_hex(12)
            fingerprints = sorted(item["fingerprint"] for item, _ in members)
            conversation_key = _bridge_conversation_key(person_key, fingerprints)
            idempotency_key = "pcr:" + _digest(
                {"question_id": qid, "fingerprints": fingerprints}
            )[7:]
            q = {
                "question_id": qid,
                "item_ids": [item["item_id"] for item, _ in members],
                "item_fingerprints": [item["fingerprint"] for item, _ in members],
                "person_key": person_key,
                "allowed_options": sorted({str(option) for _, entry in members for option in entry["options"]}),
                "agenda": agenda,
                "message": rendered_message,
                "message_digest": _digest(rendered_message),
                "state": "staged",
                "adapter_version": ADAPTER_VERSION,
                "bridge_conversation_id": None,
                "bridge_conversation_key": conversation_key,
                "bridge_idempotency_key": idempotency_key,
                "bridge_initial_ttl_seconds": cfg.initial_ttl_seconds,
                "bridge_lease_idle_seconds": cfg.lease_idle_seconds,
                "staged_at": _iso(),
            }
            suppressed_until = _iso(_now() + timedelta(seconds=cfg.cooldown_seconds))
            for fingerprint in q["item_fingerprints"]:
                state["fingerprints"].setdefault(fingerprint, {})["suppressed_until"] = suppressed_until
            state["delivery_sets"][delivery_id] = {
                "delivery_set_id": delivery_id,
                "state": "staged",
                "guild_id": cfg.guild_id,
                "channel_id": cfg.channel_id,
                "parent_channel_id": cfg.reconciliation_parent_channel_id,
                "owner_ids": list(cfg.owner_ids),
                "staged_at": _iso(),
                "questions": {qid: q},
            }
            selected = {item["fingerprint"] for item, _ in members}
            _review_run_items(state, selected)
            residual_count = len(all_members) - len(members)
            result = {
                "ok": True,
                "action": "staged",
                "resumed": False,
                "delivery_set_id": delivery_id,
                "question_id": qid,
                "count": 1,
                "remaining_item_count": residual_count + sum(
                    len(group) for key, group in question_groups.items() if key != person_key
                ),
                "remaining_person_group_count": len(question_groups) - 1 + int(residual_count > 0),
            }
    if bridge_spec_file is not None:
        state = store.read()
        found = _find_question(state, str(result["question_id"]))
        if not found:
            raise ReconciliationError("question_not_found")
        _write_private_json(
            bridge_spec_file,
            _bridge_spec_for_question(config, found[0], found[1]),
        )
        result["bridge_spec_file"] = str(bridge_spec_file)
    return result


def _attention_route(delivery: Mapping[str, Any], cfg: ReconciliationConfig) -> dict[str, Any]:
    target = str(delivery.get("channel_id") or cfg.channel_id)
    parent = str(delivery.get("parent_channel_id") or cfg.reconciliation_parent_channel_id)
    owners = delivery.get("owner_ids") or cfg.owner_ids
    if not isinstance(owners, (list, tuple)) or len(owners) != 1:
        raise ReconciliationError("attention_route_invalid")
    return {
        "platform": "discord",
        "scope_id": str(delivery.get("guild_id") or cfg.guild_id),
        "channel_id": target if parent == target else parent,
        "thread_id": None if parent == target else target,
        "owner_id": str(owners[0]),
    }


def _attention_spec(config: RouterConfig, delivery: Mapping[str, Any], q: Mapping[str, Any]) -> dict[str, Any]:
    cfg = _enabled(config)
    created = _parse_time(q.get("staged_at"))
    if created is None:
        raise ReconciliationError("attention_timestamp_invalid")
    expires = created + timedelta(seconds=int(q.get("bridge_initial_ttl_seconds") or cfg.initial_ttl_seconds))
    route = _attention_route(delivery, cfg)
    return {
        "producer": ATTENTION_PRODUCER,
        "intent_ref": str(q["question_id"]),
        "idempotency_key": "pcr-attention-" + hashlib.sha256(
            (ATTENTION_PRODUCER + "\0" + str(q["question_id"])).encode("utf-8")
        ).hexdigest()[:48],
        **route,
        "priority": "normal",
        "delivery_mode": "adaptive",
        "context_tags": [_context_tag(q.get("person_key"))],
        "interruptibility": "deferable",
        "cooldown_group": "kinlayer-question",
        "created_at": _iso(created),
        "not_before": _iso(created),
        "expires_at": _iso(expires),
    }


def submit_attention(
    config: RouterConfig,
    store: StateStore,
    question_id: str,
    runner: Any = None,
) -> dict[str, Any]:
    state = store.read()
    found = _find_question(state, question_id)
    if not found:
        raise ReconciliationError("question_not_found")
    delivery, q = found
    if q.get("adapter_version") != ADAPTER_VERSION or q.get("state") != "staged":
        raise ReconciliationError("question_not_attention_submittable")
    prior_attention = _attention(q)
    if prior_attention is not None:
        return {"ok": True, "action": "attention_submitted", "question_id": question_id, "intent_id": str(prior_attention["intent_id"]), "state": str(prior_attention["state"]), "idempotent": True}
    spec = _attention_spec(config, delivery, q)
    with store.update() as mutable:
        current = _find_question(mutable, question_id)
        if not current or current[1].get("state") != "staged":
            raise ReconciliationError("question_not_attention_submittable")
        try:
            submitted = attention_submit(spec, runner=runner)
        except AttentionError as exc:
            raise ReconciliationError("attention_submit_failed") from exc
        target = current[1]
        prior = _attention(target)
        if prior and prior.get("intent_id") != submitted["intent_id"]:
            raise ReconciliationError("attention_intent_conflict")
        target["attention"] = {
            "producer": ATTENTION_PRODUCER,
            "context_tag": spec["context_tags"][0],
            "intent_id": submitted["intent_id"],
            "state": submitted["state"],
            "submitted_at": (prior or {}).get("submitted_at") or _iso(),
        }
    return {
        "ok": True,
        "action": "attention_submitted",
        "question_id": question_id,
        "intent_id": submitted["intent_id"],
        "state": submitted["state"],
        "idempotent": bool(submitted.get("idempotent")),
    }


def _cancel_attention_before_send(
    store: StateStore,
    question_id: str,
    intent_id: str,
    lease_id: str | None,
    runner: Any,
) -> dict[str, Any]:
    try:
        attention_cancel(intent_id, lease_id=lease_id, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("attention_cancel_failed") from exc
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        delivery, q = found
        attention = dict(_attention(q) or {})
        attention.update(state="cancelled", cancelled_at=_iso())
        for key in ("lease_id", "lease_expires_at"):
            attention.pop(key, None)
        q["attention"] = attention
        if q.get("state") not in TERMINAL_STATES:
            q["state"] = "expired" if _parse_time(q.get("staged_at")) and _parse_time(q["staged_at"]) + timedelta(seconds=int(q.get("bridge_initial_ttl_seconds") or 0)) <= _now() else "cancelled"
            q[q["state"] + "_at"] = _iso()
        delivery["state"] = q["state"]
    return {"ok": True, "action": "attention_cancelled", "question_id": question_id, "intent_id": intent_id}


def dispatch_attention(
    config: RouterConfig,
    store: StateStore,
    question_id: str,
    intent_id: str,
    lease_id: str,
    runner: Any = None,
) -> dict[str, Any]:
    cfg = _enabled(config)
    state = store.read()
    found = _find_question(state, question_id)
    if not found:
        raise ReconciliationError("question_not_found")
    delivery, q = found
    attention = _attention(q)
    if not attention or attention.get("producer") != ATTENTION_PRODUCER or attention.get("intent_id") != intent_id:
        raise ReconciliationError("attention_authority_mismatch")
    if attention.get("lease_id") not in {None, lease_id}:
        raise ReconciliationError("attention_authority_mismatch")
    if attention.get("state") == "delivered" and q.get("state") == "awaiting_reply":
        return {"ok": True, "action": "attention_delivered", "question_id": question_id, "intent_id": intent_id, "idempotent": True}
    created = _parse_time(q.get("staged_at"))
    expired = created is None or created + timedelta(seconds=int(q.get("bridge_initial_ttl_seconds") or cfg.initial_ttl_seconds)) <= _now()
    if q.get("state") != "staged" or expired:
        return _cancel_attention_before_send(store, question_id, intent_id, lease_id, runner)
    conversation_id = str(attention.get("bridge_conversation_id") or "")
    if not conversation_id:
        try:
            staged = bridge_stage(_bridge_spec_for_question(config, delivery, q), runner=runner)
        except AttentionError as exc:
            try:
                attention_release(intent_id, lease_id, "failed_before_send", runner=runner)
            except AttentionError:
                pass
            raise ReconciliationError("bridge_stage_failed") from exc
        conversation_id = str(staged["conversation_id"])
    if attention.get("state") == "queued" or (attention.get("state") == "claimed" and not attention.get("lease_id")):
        with store.update() as mutable:
            current = _find_question(mutable, question_id)
            if not current or current[1].get("state") != "staged":
                raise ReconciliationError("question_not_dispatchable")
            target_attention = dict(_attention(current[1]) or {})
            existing = target_attention.get("bridge_conversation_id")
            if existing and existing != conversation_id:
                raise ReconciliationError("bridge_conversation_conflict")
            target_attention.update(
                state="claimed",
                claimed_at=target_attention.get("claimed_at") or _iso(),
                lease_id=lease_id,
                bridge_conversation_id=conversation_id,
            )
            current[1]["attention"] = target_attention
        attention = dict(attention)
        attention.update(
            state="claimed",
            claimed_at=attention.get("claimed_at") or _iso(),
            lease_id=lease_id,
            bridge_conversation_id=conversation_id,
        )
    if attention.get("state") == "claimed":
        try:
            attention_begin_delivery(intent_id, lease_id, runner=runner)
        except AttentionError as exc:
            raise ReconciliationError("attention_begin_failed") from exc
        with store.update() as mutable:
            target = _find_question(mutable, question_id)
            if not target:
                raise ReconciliationError("question_not_found")
            target_attention = dict(_attention(target[1]) or {})
            target_attention.update(
                state="sending",
                sending_at=target_attention.get("sending_at") or _iso(),
                lease_id=lease_id,
                bridge_conversation_id=conversation_id,
            )
            target[1]["attention"] = target_attention
    try:
        delivered = bridge_deliver(conversation_id, runner=runner)
    except AttentionError as exc:
        with store.update() as mutable:
            target = _find_question(mutable, question_id)
            if target:
                target_attention = dict(_attention(target[1]) or {})
                target_attention.update(
                    state="delivery_unknown",
                    lease_id=lease_id,
                    bridge_conversation_id=conversation_id,
                )
                target[1]["attention"] = target_attention
        raise ReconciliationError("bridge_delivery_unknown") from exc
    if delivered.get("ok") is not True:
        with store.update() as mutable:
            target = _find_question(mutable, question_id)
            if target:
                target_attention = dict(_attention(target[1]) or {})
                target_attention.update(
                    state="delivery_unknown",
                    lease_id=lease_id,
                    bridge_conversation_id=conversation_id,
                )
                target[1]["attention"] = target_attention
        return {"ok": False, "action": "delivery_unknown", "question_id": question_id, "intent_id": intent_id}
    try:
        context = bridge_context(conversation_id, runner=runner)
        receipt = bridge_status(conversation_id, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("bridge_receipt_unavailable") from exc
    if (
        context.get("conversation_ref") != question_id
        or context.get("adapter") != {"key": "kinlayer-reconciliation", "version": ADAPTER_VERSION}
        or context.get("state") not in DELIVERED_BRIDGE_STATES
        or receipt.get("state") != context.get("state")
        or not receipt.get("message_id")
    ):
        raise ReconciliationError("bridge_receipt_invalid")
    try:
        attention_complete(intent_id, lease_id, conversation_id, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("attention_complete_failed") from exc
    with store.update() as mutable:
        current = _find_question(mutable, question_id)
        if not current:
            raise ReconciliationError("question_not_found")
        delivery, target = current
        target_attention = dict(_attention(target) or {})
        target_attention.update(
            state="delivered", delivered_at=_iso(), bridge_conversation_id=conversation_id,
            receipt_ref=conversation_id,
        )
        for key in ("lease_id", "lease_expires_at"):
            target_attention.pop(key, None)
        target["attention"] = target_attention
        target["state"] = "awaiting_reply"
        delivery["state"] = "awaiting_reply"
    return {"ok": True, "action": "attention_delivered", "question_id": question_id, "intent_id": intent_id, "conversation_id": conversation_id, "idempotent": bool(delivered.get("duplicate"))}


def recover_attention(
    config: RouterConfig,
    store: StateStore,
    question_id: str,
    intent_id: str,
    runner: Any = None,
) -> dict[str, Any]:
    found = _find_question(store.read(), question_id)
    if not found:
        raise ReconciliationError("question_not_found")
    _, q = found
    attention = _attention(q)
    if not attention or attention.get("producer") != ATTENTION_PRODUCER or attention.get("intent_id") != intent_id:
        raise ReconciliationError("attention_authority_mismatch")
    state = str(attention.get("state") or "")
    if state in {"delivered", "completed"}:
        return {
            "ok": True,
            "action": "attention_" + state,
            "question_id": question_id,
            "intent_id": intent_id,
            "state": state,
            "idempotent": True,
        }
    lease_id = str(attention.get("lease_id") or "")
    created = _parse_time(q.get("staged_at"))
    expired = created is None or created + timedelta(seconds=int(q.get("bridge_initial_ttl_seconds") or _enabled(config).initial_ttl_seconds)) <= _now()
    if state in {"queued", "claimed"} and (q.get("state") != "staged" or expired):
        return _cancel_attention_before_send(store, question_id, intent_id, lease_id or None, runner)
    if not lease_id:
        if state in {"queued", "claimed"}:
            return {"ok": True, "action": "waiting_for_claim_lease_expiry", "state": "claimed"}
        raise ReconciliationError("attention_recovery_lease_missing")
    if state not in {"claimed", "sending", "delivery_unknown"}:
        raise ReconciliationError("attention_not_recoverable")
    return dispatch_attention(config, store, question_id, intent_id, lease_id, runner=runner)


def complete_attention(store: StateStore, question_id: str, runner: Any = None) -> dict[str, Any]:
    state = store.read()
    found = _find_question(state, question_id)
    if not found:
        raise ReconciliationError("question_not_found")
    _, q = found
    attention = _attention(q)
    if attention is None:
        if q.get("state") not in TERMINAL_STATES:
            raise ReconciliationError("question_not_terminal")
        return {"ok": True, "action": "legacy_no_attention", "question_id": question_id, "idempotent": True}
    if attention.get("state") == "completed":
        return {"ok": True, "action": "attention_completed", "question_id": question_id, "idempotent": True}
    if q.get("state") not in TERMINAL_STATES or q.get("state") == "cancelled":
        raise ReconciliationError("question_not_terminal")
    conversation_id = str(attention.get("bridge_conversation_id") or "")
    receipt_ref = str(attention.get("receipt_ref") or "")
    if attention.get("state") != "delivered" or not conversation_id or receipt_ref != conversation_id:
        raise ReconciliationError("attention_not_delivered")
    try:
        bridge_result = bridge_status(conversation_id, runner=runner)
        if bridge_result.get("state") != "completed":
            raise ReconciliationError("bridge_not_terminal")
        attention_release_visible(str(attention["intent_id"]), receipt_ref, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("attention_release_visible_failed") from exc
    with store.update() as mutable:
        current = _find_question(mutable, question_id)
        if not current:
            raise ReconciliationError("question_not_found")
        target_attention = dict(_attention(current[1]) or {})
        target_attention.update(state="completed", completed_at=_iso())
        current[1]["attention"] = target_attention
    return {"ok": True, "action": "attention_completed", "question_id": question_id, "idempotent": False}


def attention_signal_matches(store: StateStore, identity_ids: set[str]) -> list[dict[str, Any]]:
    if not identity_ids:
        return []
    state = store.peek()
    matches: list[dict[str, Any]] = []
    for delivery in state.get("delivery_sets", {}).values():
        for q in delivery.get("questions", {}).values():
            attention = _attention(q)
            if q.get("state") != "staged" or not attention or attention.get("state") != "queued":
                continue
            exact_ids: set[str] = set()
            for item_id in q.get("item_ids", []):
                item = state.get("prepared_items", {}).get(item_id, {})
                for key in ("source_entity_id", "target_entity_id"):
                    if item.get(key):
                        exact_ids.add(str(item[key]))
                for candidate in item.get("candidates", []):
                    if isinstance(candidate, Mapping) and candidate.get("id"):
                        exact_ids.add(str(candidate["id"]))
                for entity in item.get("expected_entities", []):
                    if isinstance(entity, Mapping) and entity.get("id"):
                        exact_ids.add(str(entity["id"]))
            if exact_ids & identity_ids:
                target = str(delivery.get("channel_id") or "")
                parent = str(delivery.get("parent_channel_id") or target)
                owners = delivery.get("owner_ids") or []
                if len(owners) != 1:
                    continue
                matches.append({
                    "question_id": str(q["question_id"]),
                    "producer": ATTENTION_PRODUCER,
                    "context_tag": str(attention["context_tag"]),
                    "route": {
                        "platform": "discord", "scope_id": str(delivery.get("guild_id") or ""),
                        "channel_id": target if parent == target else parent,
                        "thread_id": None if parent == target else target, "owner_id": str(owners[0]),
                    },
                })
    return matches


def deliver(config: RouterConfig, store: StateStore, delivery_set_id: str) -> dict[str, Any]:
    _enabled(config)
    if delivery_set_id not in store.read().get("delivery_sets", {}):
        raise ReconciliationError("delivery_set_not_found")
    return {
        "ok": False,
        "action": "bridge_required",
        "error": "reconciliation_deliver_deprecated",
        "delivery_set_id": delivery_set_id,
        "sent_count": 0,
    }


def attach_bridge(
    store: StateStore,
    question_id: str,
    conversation_id: str,
    runner: Any = None,
) -> dict[str, Any]:
    conversation_id = _compact(conversation_id, 160)
    if not conversation_id or not SAFE_BRIDGE_ID.fullmatch(conversation_id):
        raise ReconciliationError("bridge_conversation_id_invalid")
    try:
        context = bridge_context(conversation_id, runner=runner)
        bridge_result = bridge_status(conversation_id, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("bridge_context_unavailable" if exc.code.endswith("_unavailable") else "bridge_not_delivered") from exc
    if (
        context.get("ok") is not True
        or bridge_result.get("ok") is not True
        or context.get("conversation_id") != conversation_id
        or bridge_result.get("conversation_id") != conversation_id
        or context.get("conversation_ref") != question_id
        or context.get("adapter") != {"key": "kinlayer-reconciliation", "version": ADAPTER_VERSION}
        or context.get("state") not in DELIVERED_BRIDGE_STATES
        or bridge_result.get("state") != context.get("state")
        or not isinstance(bridge_result.get("message_id"), str)
        or not SAFE_BRIDGE_ID.fullmatch(bridge_result["message_id"])
    ):
        raise ReconciliationError("bridge_not_delivered")
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        delivery_set, q = found
        if q.get("adapter_version") != ADAPTER_VERSION or q.get("state") in TERMINAL_STATES:
            raise ReconciliationError("question_not_attachable")
        if _attention(q) is not None:
            raise ReconciliationError("attention_dispatch_required")
        if q.get("state") != "staged" and not q.get("bridge_conversation_id"):
            raise ReconciliationError("question_not_attachable")
        conflict = next(
            (other for d in state["delivery_sets"].values() for other in d.get("questions", {}).values()
             if other is not q and other.get("bridge_conversation_id") == conversation_id),
            None,
        )
        if conflict:
            raise ReconciliationError("bridge_conversation_conflict")
        existing = q.get("bridge_conversation_id")
        if existing and existing != conversation_id:
            raise ReconciliationError("bridge_conversation_conflict")
        existing_message = q.get("bridge_message_id")
        if existing_message and existing_message != bridge_result["message_id"]:
            raise ReconciliationError("bridge_delivery_receipt_mismatch")
        q["bridge_conversation_id"] = conversation_id
        q["bridge_message_id"] = bridge_result["message_id"]
        q["state"] = "awaiting_reply"
        q.setdefault("bridge_attached_at", _iso())
        delivery_set["state"] = "awaiting_reply"
        return {"ok": True, "action": "bridge_attached", "question_id": question_id, "conversation_id": conversation_id, "idempotent": bool(existing)}


def question(
    store: StateStore,
    question_id: str,
    bridge_conversation_id: str,
) -> dict[str, Any]:
    state = store.read()
    found = _find_question(state, question_id)
    if not found:
        raise ReconciliationError("question_not_found")
    delivery_set, q = found
    if q.get("adapter_version") != ADAPTER_VERSION:
        raise ReconciliationError("legacy_state_requires_migration")
    if (
        not bridge_conversation_id
        or not SAFE_BRIDGE_ID.fullmatch(bridge_conversation_id)
        or _bridge_id(q) != bridge_conversation_id
    ):
        raise ReconciliationError("bridge_conversation_mismatch")
    if q.get("state") != "awaiting_reply":
        raise ReconciliationError("question_not_available")
    attention = _attention(q)
    if attention is not None:
        if (
            attention.get("state") != "delivered"
            or attention.get("bridge_conversation_id") != bridge_conversation_id
            or attention.get("receipt_ref") != bridge_conversation_id
        ):
            raise ReconciliationError("attention_receipt_mismatch")
    elif not q.get("bridge_message_id"):
        raise ReconciliationError("bridge_delivery_receipt_missing")
    handled = set(q.get("resolved_item_ids", [])) | set(q.get("deferred_item_ids", []))
    pending = []
    for entry in _validated_agenda(q):
        if entry.get("item_id") in handled:
            continue
        prepared = state["prepared_items"].get(entry.get("item_id"), {})
        if prepared.get("fingerprint") != entry.get("fingerprint"):
            raise ReconciliationError("prepared_item_missing")
        private = {
            "item_id": entry["item_id"],
            "fingerprint": entry["fingerprint"],
            "question": entry["question"],
            "allowed_options": list(entry["options"]),
            "authorized_actions": {
                option: sorted(OPTION_ACTIONS[option])
                for option in entry["options"]
            },
            "record_summaries": [
                {"summary": summary["summary"]}
                for summary in entry.get("record_summaries", [])
            ],
            "prepared_context_claim_count": len(entry.get("prepared_context_claims", [])),
        }
        for key in ("source_entity_id", "target_entity_id"):
            if prepared.get(key):
                private[key] = prepared[key]
        pending.append(private)
    if not pending and q.get("state") in QUESTION_STATES:
        raise ReconciliationError("agenda_state_invalid")
    return {
        "ok": True,
        "question_id": question_id,
        "state": q["state"],
        "attention_managed": _attention(q) is not None,
        "pending_item_ids": [entry["item_id"] for entry in pending],
        "pending_agenda": pending,
        "next_question": pending[0]["question"] if pending else None,
    }


def cancel_question(store: StateStore, question_id: str, runner: Any = None) -> dict[str, Any]:
    before = store.read()
    found_before = _find_question(before, question_id)
    if not found_before:
        raise ReconciliationError("question_not_found")
    attention_before = _attention(found_before[1])
    state_before = found_before[1].get("state")
    if state_before != "cancelled" and state_before in {"applying", "committed_unverified", "verified_applied", "stale", "expired"}:
        raise ReconciliationError("question_not_cancellable")
    if state_before != "cancelled" and state_before not in {"staged", "awaiting_reply", "planned", "sending", "delivered", "delivery_failed", "claimed"}:
        raise ReconciliationError("question_not_cancellable")
    if found_before[1].get("state") == "cancelled" and attention_before and attention_before.get("state") == "delivered":
        try:
            conversation_id = str(attention_before.get("bridge_conversation_id") or "")
            if bridge_status(conversation_id, runner=runner).get("state") != "cancelled":
                raise ReconciliationError("bridge_not_terminal")
            attention_release_visible(str(attention_before["intent_id"]), str(attention_before["receipt_ref"]), runner=runner)
        except AttentionError as exc:
            raise ReconciliationError("attention_release_visible_failed") from exc
        with store.update() as state:
            current = _find_question(state, question_id)
            if current:
                value = dict(_attention(current[1]) or {})
                value.update(state="completed", completed_at=_iso())
                current[1]["attention"] = value
        return {"ok": True, "action": "cancelled", "question_id": question_id, "bridge_cancel_recommended": False, "idempotent": True}
    if attention_before and found_before[1].get("state") != "cancelled":
        try:
            if attention_before.get("state") in {"queued", "claimed"}:
                attention_cancel(
                    str(attention_before["intent_id"]),
                    lease_id=str(attention_before.get("lease_id") or "") or None,
                    runner=runner,
                )
            elif attention_before.get("state") == "delivered":
                conversation_id = str(attention_before.get("bridge_conversation_id") or "")
                receipt_ref = str(attention_before.get("receipt_ref") or "")
                if not conversation_id or receipt_ref != conversation_id:
                    raise ReconciliationError("attention_receipt_invalid")
                bridge_cancel(conversation_id, outcome="user_cancelled", runner=runner)
                if bridge_status(conversation_id, runner=runner).get("state") != "cancelled":
                    raise ReconciliationError("bridge_not_terminal")
            else:
                raise ReconciliationError("attention_recovery_required")
        except AttentionError as exc:
            raise ReconciliationError("attention_cancel_failed") from exc
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        delivery_set, q = found
        if q.get("state") == "cancelled":
            return {"ok": True, "action": "cancelled", "question_id": question_id, "bridge_cancel_recommended": bool(_bridge_id(q)) and _attention(q) is None, "idempotent": True}
        if q.get("state") in {"applying", "committed_unverified", "verified_applied", "stale", "expired"}:
            raise ReconciliationError("question_not_cancellable")
        if q.get("state") not in {"staged", "awaiting_reply", "planned", "sending", "delivered", "delivery_failed", "claimed"}:
            raise ReconciliationError("question_not_cancellable")
        q["state"] = "cancelled"
        q["cancelled_at"] = _iso()
        if _attention(q) is not None:
            current_attention = dict(_attention(q) or {})
            if current_attention.get("state") in {"queued", "claimed"}:
                current_attention.update(state="cancelled", cancelled_at=_iso())
            q["attention"] = current_attention
        for fingerprint in q.get("item_fingerprints", []):
            still_open = any(
                other is not q
                and other.get("state") in QUESTION_STATES
                and fingerprint in other.get("item_fingerprints", [])
                for candidate_set in state.get("delivery_sets", {}).values()
                for other in candidate_set.get("questions", {}).values()
            )
            if not still_open:
                state.get("fingerprints", {}).get(fingerprint, {}).pop("suppressed_until", None)
        states = {item.get("state") for item in delivery_set.get("questions", {}).values()}
        delivery_set["state"] = "cancelled" if states <= TERMINAL_STATES else "awaiting_reply"
        result = {"ok": True, "action": "cancelled", "question_id": question_id, "delivery_set_id": delivery_set["delivery_set_id"], "delivery_set_state": delivery_set["state"], "bridge_cancel_recommended": bool(_bridge_id(q)) and _attention(q) is None, "idempotent": False}
    if attention_before and attention_before.get("state") == "delivered":
        try:
            attention_release_visible(str(attention_before["intent_id"]), str(attention_before["receipt_ref"]), runner=runner)
        except AttentionError as exc:
            raise ReconciliationError("attention_release_visible_failed") from exc
        with store.update() as state:
            current = _find_question(state, question_id)
            if current:
                current_attention = dict(_attention(current[1]) or {})
                current_attention.update(state="completed", completed_at=_iso())
                current[1]["attention"] = current_attention
    return result


def reissue_expired_question(
    config: RouterConfig,
    store: StateStore,
    question_id: str,
    bridge_spec_file: Path | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    _enabled(config)
    state_before = store.read()
    found_before = _find_question(state_before, question_id)
    if not found_before:
        raise ReconciliationError("question_not_found")
    _, q_before = found_before
    old_conversation_id = _compact(_bridge_id(q_before), 160)
    if (
        q_before.get("adapter_version") != ADAPTER_VERSION
        or q_before.get("state") != "cancelled"
        or not old_conversation_id
        or q_before.get("pending_actions")
        or q_before.get("resolved_item_ids")
        or q_before.get("deferred_item_ids")
    ):
        raise ReconciliationError("question_not_reissuable")
    try:
        bridge_result = bridge_status(old_conversation_id, runner=runner)
    except AttentionError as exc:
        raise ReconciliationError("bridge_status_unavailable") from exc
    if (
        bridge_result.get("ok") is not True
        or bridge_result.get("conversation_id") != old_conversation_id
        or bridge_result.get("state") != "expired"
    ):
        raise ReconciliationError("bridge_not_expired")

    with route_arbitration(store.path.parent):
        with store.update() as state:
            found = _find_question(state, question_id)
            if not found:
                raise ReconciliationError("question_not_found")
            delivery_set, q = found
            if (
                q.get("adapter_version") != ADAPTER_VERSION
                or q.get("state") != "cancelled"
                or _bridge_id(q) != old_conversation_id
                or q.get("pending_actions")
                or q.get("resolved_item_ids")
                or q.get("deferred_item_ids")
            ):
                raise ReconciliationError("question_not_reissuable")
            if any(
                other is not q
                and other.get("adapter_version") == ADAPTER_VERSION
                and other.get("state") in QUESTION_STATES
                for candidate_set in state.get("delivery_sets", {}).values()
                for other in candidate_set.get("questions", {}).values()
            ):
                raise ReconciliationError("active_bridge_question_exists")
            new_question_id = "rq_" + secrets.token_hex(12)
            new_q = json.loads(json.dumps(q))
            for key in (
                "bridge_attached_at",
                "bridge_conversation_id",
                "bridge_message_id",
                "attention",
                "cancelled_at",
                "last_error",
                "pending_action_plan_digest",
                "pending_actions",
                "resolved_item_ids",
                "deferred_item_ids",
            ):
                new_q.pop(key, None)
            new_q.update(
                question_id=new_question_id,
                state="staged",
                staged_at=_iso(),
                reissued_from_question_id=question_id,
                bridge_idempotency_key="pcr:" + _digest(
                    {
                        "question_id": new_question_id,
                        "fingerprints": sorted(
                            str(value) for value in new_q.get("item_fingerprints", [])
                        ),
                    }
                )[7:],
            )
            delivery_set["questions"][new_question_id] = new_q
            delivery_set["state"] = "staged"
            result = {
                "ok": True,
                "action": "reissued",
                "question_id": new_question_id,
                "state": "staged",
            }
    if bridge_spec_file is not None:
        state = store.read()
        found = _find_question(state, str(result["question_id"]))
        if not found:
            raise ReconciliationError("question_not_found")
        _write_private_json(
            bridge_spec_file,
            _bridge_spec_for_question(config, found[0], found[1]),
        )
        result["bridge_spec_file"] = str(bridge_spec_file)
    return result


def _resolution_id(q: Mapping[str, Any], item_id: str, option: str, action: str) -> str:
    return "rr_" + _digest(
        {"question": q["question_id"], "item": item_id, "option": option, "action": action}
    )[7:39]


def _observation_group_target(item: Mapping[str, Any]) -> str:
    candidates = item.get("candidates")
    if not isinstance(candidates, list) or not candidates or any(
        not isinstance(candidate, Mapping)
        or candidate.get("candidate_type") != "observation"
        or candidate.get("status") != "pending"
        for candidate in candidates
    ):
        raise ReconciliationError("answer_action_invalid")
    targets = {_compact(candidate.get("target_entity_id"), 36) for candidate in candidates}
    if "" in targets or len(targets) != 1:
        raise ReconciliationError("answer_entity_mismatch")
    return targets.pop()


def _transient_prepared_for_apply(
    prepared: Mapping[str, Mapping[str, Any]],
    answers: list[Any],
    q: Mapping[str, Any],
    snapshot_items: list[Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    transient = {
        item_id: json.loads(json.dumps(item))
        for item_id, item in prepared.items()
    }
    pending_by_resolution = {
        str(entry.get("resolution_id") or ""): entry
        for entry in q.get("pending_actions", [])
        if isinstance(entry, Mapping)
    }
    for answer in answers:
        if not isinstance(answer, Mapping) or answer.get("action") != "accept_existing_entity_observation_group":
            continue
        item_id = str(answer.get("item_id") or "")
        item = transient.get(item_id)
        if item is None:
            raise ReconciliationError("answer_item_invalid")
        target_entity_id = _observation_group_target(item)
        if snapshot_items is not None:
            matches = [
                snapshot
                for raw in snapshot_items
                for snapshot in [_entity_snapshot(raw)]
                if snapshot and snapshot["id"] == target_entity_id
            ]
            if len(matches) != 1:
                raise ReconciliationError("answer_entity_snapshot_invalid")
            snapshot = matches[0]
            stored = item.get("expected_entities")
            if stored and (not isinstance(stored, list) or stored != [snapshot]):
                raise ReconciliationError("stale_entity")
        else:
            resolution_id = _resolution_id(
                q,
                item_id,
                str(answer.get("option") or ""),
                str(answer.get("action") or ""),
            )
            pending = pending_by_resolution.get(resolution_id)
            expected_entities = pending.get("expected_entities") if isinstance(pending, Mapping) else None
            if (
                not isinstance(expected_entities, list)
                or len(expected_entities) != 1
                or not isinstance(expected_entities[0], Mapping)
                or expected_entities[0].get("id") != target_entity_id
            ):
                raise ReconciliationError("action_retry_mismatch")
            snapshot = dict(expected_entities[0])
        item["target_entity_id"] = target_entity_id
        item["expected_entities"] = [snapshot]
    return transient


def _restore_after_proof_failure(
    store: StateStore,
    question_id: str,
    submission_digest: str,
) -> None:
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            return
        q = found[1]
        pending = q.get("pending_actions", [])
        if (
            q.get("state") == "applying"
            and q.get("submission_digest") == submission_digest
            and isinstance(pending, list)
            and not any(entry.get("action_id") for entry in pending if isinstance(entry, Mapping))
        ):
            q["state"] = "awaiting_reply"
            q.pop("pending_action_plan_digest", None)
            q.pop("pending_actions", None)
            q.pop("submission_digest", None)


def apply_answers(
    config: RouterConfig,
    store: StateStore,
    question_id: str,
    bridge_conversation_id: str,
    answers_file: Path,
    transport: Transport | None = None,
    runner: Any = None,
    answers_root: Path | None = None,
) -> dict[str, Any]:
    cfg = _enabled(config)
    state_before = store.read()
    found_before = _find_question(state_before, question_id)
    if not found_before:
        raise ReconciliationError("question_not_found")
    q_before = found_before[1]
    if q_before.get("adapter_version") != ADAPTER_VERSION:
        raise ReconciliationError("legacy_state_requires_migration")
    if any(
        state_before["prepared_items"].get(entry["item_id"], {}).get("fingerprint") != entry["fingerprint"]
        for entry in _validated_agenda(q_before)
    ):
        raise ReconciliationError("prepared_item_missing")
    if not bridge_conversation_id or _bridge_id(q_before) != bridge_conversation_id:
        raise ReconciliationError("bridge_conversation_mismatch")
    envelope = _secure_answers(answers_file, answers_root)
    if set(envelope) not in ({"reply_text", "answers"}, {"reply_text", "answers", "context_claims"}):
        raise ReconciliationError("answers_schema_invalid")
    reply = envelope.get("reply_text")
    supplied_answers = envelope.get("answers")
    supplied_context_claims = envelope.get("context_claims", [])
    if (
        not isinstance(reply, str)
        or len(reply) > MAX_REPLY_CODEPOINTS
        or not isinstance(supplied_answers, list)
        or not 1 <= len(supplied_answers) <= MAX_IDS
        or not isinstance(supplied_context_claims, list)
        or len(supplied_context_claims) > MAX_CONTEXT_CLAIMS
    ):
        raise ReconciliationError("answers_schema_invalid")
    prepared_submission_claims = _prepared_context_for_answers(q_before, supplied_answers)
    submission_digest = _digest(
        {
            "version": 1,
            "purpose": "kinlayer-reconciliation-answer",
            "conversation_id": bridge_conversation_id,
            "conversation_ref": question_id,
            "agenda_digest": _digest(q_before["agenda"]),
            "reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest(),
            "answers": supplied_answers,
            "context_claims": supplied_context_claims,
            "prepared_context_claims": prepared_submission_claims,
        }
    )[7:]
    if q_before.get("last_submission_digest") == submission_digest:
        prior_result = q_before.get("last_apply_result")
        if isinstance(prior_result, Mapping):
            return {**json.loads(json.dumps(prior_result)), "idempotent": True}
    if q_before.get("state") in TERMINAL_STATES:
        raise ReconciliationError("question_not_pending")
    handled_before = set(q_before.get("resolved_item_ids", [])) | set(
        q_before.get("deferred_item_ids", [])
    )
    pending_answers = [
        answer
        for answer in supplied_answers
        if not isinstance(answer, Mapping)
        or str(answer.get("item_id") or "") not in handled_before
    ]
    snapshot_items = (
        _entity_snapshot_items(config, transport, cfg)
        if q_before.get("state") == "awaiting_reply"
        and any(
            isinstance(answer, Mapping)
            and answer.get("action") == "accept_existing_entity_observation_group"
            for answer in pending_answers
        )
        else None
    )
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        _, q = found
        if q.get("adapter_version") != ADAPTER_VERSION:
            raise ReconciliationError("legacy_state_requires_migration")
        if not bridge_conversation_id or _bridge_id(q) != bridge_conversation_id:
            raise ReconciliationError("bridge_conversation_mismatch")
        if q.get("last_submission_digest") == submission_digest and isinstance(q.get("last_apply_result"), Mapping):
            return {**json.loads(json.dumps(q["last_apply_result"])), "idempotent": True}
        if q.get("state") not in {"awaiting_reply", "applying", "committed_unverified"}:
            raise ReconciliationError("question_not_pending")
        if q.get("submission_digest") and q.get("submission_digest") != submission_digest:
            raise ReconciliationError("submission_retry_mismatch")
        item_ids = set(q["item_ids"])
        stored_prepared = {item_id: state["prepared_items"].get(item_id) for item_id in item_ids}
        if any(not item for item in stored_prepared.values()):
            q["state"] = "stale"
            raise ReconciliationError("prepared_item_missing")
        prior_state = q["state"]
        prepared = _transient_prepared_for_apply(
            stored_prepared,
            pending_answers,
            q,
            snapshot_items if prior_state == "awaiting_reply" else None,
        )
        actions = _answer_actions(supplied_answers, q, prepared)
        compiled_context = _compile_context_claims(
            supplied_context_claims, supplied_answers, reply, prepared
        )
        compiled_context = _merge_context_claims(
            compiled_context,
            _prepared_context_for_answers(q, supplied_answers),
        )
        legacy_relationship_items = {
            str(answer.get("item_id") or "")
            for answer in supplied_answers
            if isinstance(answer, Mapping) and answer.get("relationship_to_self") is not None
        }
        if any(
            claim.get("kind") == "relationship_edge"
            for item_id in legacy_relationship_items
            for claim in compiled_context.get(item_id, [])
        ):
            raise ReconciliationError("relationship_context_representation_conflict")
        reply_hash = "sha256:" + hashlib.sha256(reply.encode("utf-8")).hexdigest()
        for action in actions:
            if action is None:
                continue
            item_id = action.pop("_answer_item_id")
            action["context_claims"] = compiled_context.get(item_id, [])
            action["source"]["body_hash"] = reply_hash
            action["source"]["body_excerpt"] = reply
            action["answer_bindings"] = [_answer_binding(q, item_id, action)]
        action_plan_digest = _digest(actions)
        action_payloads = [action for action in actions if action is not None]
        if prior_state in {"applying", "committed_unverified"}:
            if q.get("pending_action_plan_digest") != action_plan_digest:
                raise ReconciliationError("action_retry_mismatch")
            pending_actions = q.get("pending_actions")
            if (
                not isinstance(pending_actions, list)
                or [entry.get("resolution_id") for entry in pending_actions]
                != [action["resolution_id"] for action in action_payloads]
                or any(
                    entry.get("payload_digest") != _digest(action)
                    for entry, action in zip(pending_actions, action_payloads)
                )
            ):
                raise ReconciliationError("action_retry_mismatch")
        else:
            q["pending_actions"] = [
                {
                    "resolution_id": action["resolution_id"],
                    "payload_digest": _digest(action),
                    "expected_entities": action.get("expected_entities", []),
                    "action_id": None,
                    "state": "planned",
                    "outcome": None,
                }
                for action in action_payloads
            ]
        q["state"] = (
            "committed_unverified"
            if any(entry.get("action_id") for entry in q.get("pending_actions", []))
            else "applying"
        )
        q["pending_action_plan_digest"] = action_plan_digest
        q["submission_digest"] = submission_digest

    if prior_state != "committed_unverified":
        try:
            proof_json = bridge_consume_reply_proof(
                bridge_conversation_id,
                question_id,
                submission_digest,
                reply,
                timeout=min(cfg.api_timeout, 30.0),
                runner=runner,
            )
        except AttentionError as exc:
            _restore_after_proof_failure(store, question_id, submission_digest)
            raise ReconciliationError("bridge_reply_proof_unavailable" if exc.code.endswith("_unavailable") else "bridge_reply_proof_invalid") from None
        if (
            proof_json.get("ok") is not True
            or proof_json.get("action") != "consume-reply-proof"
            or proof_json.get("conversation_id") != bridge_conversation_id
            or proof_json.get("state") not in DELIVERED_BRIDGE_STATES
        ):
            _restore_after_proof_failure(store, question_id, submission_digest)
            raise ReconciliationError("bridge_reply_proof_invalid")

    for action in action_payloads:
        resolution_id = action["resolution_id"]
        with store.update() as state:
            found = _find_question(state, question_id)
            if not found:
                raise ReconciliationError("question_not_found")
            q = found[1]
            pending = next(
                (
                    entry
                    for entry in q.get("pending_actions", [])
                    if entry.get("resolution_id") == resolution_id
                ),
                None,
            )
            if not pending or pending.get("payload_digest") != _digest(action):
                raise ReconciliationError("action_retry_mismatch")
            action_id = _compact(pending.get("action_id"), 120)
            if pending.get("state") == "verified" and isinstance(pending.get("outcome"), Mapping):
                continue
        if not action_id:
            try:
                created = _request(
                    config,
                    transport,
                    "POST",
                    "/api/reconciliation/actions",
                    action,
                    auth=True,
                )
            except ReconciliationError as exc:
                if exc.code in {"stale_candidate", "stale_entity", "idempotency_conflict"}:
                    with store.update() as state:
                        found = _find_question(state, question_id)
                        if found:
                            pending_actions = found[1].get("pending_actions", [])
                            if not any(entry.get("action_id") for entry in pending_actions):
                                found[1]["state"] = "stale"
                            found[1]["last_error"] = exc.code
                elif re.fullmatch(r"kinlayer_http_422(?::[A-Za-z0-9_.-]+)?", exc.code):
                    with store.update() as state:
                        found = _find_question(state, question_id)
                        if found:
                            pending_actions = found[1].get("pending_actions")
                            if (
                                found[1].get("state") == "applying"
                                and isinstance(pending_actions, list)
                                and all(
                                    entry.get("state") == "planned"
                                    and not entry.get("action_id")
                                    and not entry.get("outcome")
                                    and not entry.get("receipt")
                                    for entry in pending_actions
                                )
                            ):
                                found[1]["state"] = "awaiting_reply"
                                found[1]["last_error"] = exc.code
                                found[1].pop("pending_action_plan_digest", None)
                                found[1].pop("pending_actions", None)
                                found[1].pop("submission_digest", None)
                raise
            action_id = _compact(created.get("id") or created.get("action_id"), 120)
            if not action_id:
                raise ReconciliationError("action_receipt_invalid")
            with store.update() as state:
                found = _find_question(state, question_id)
                if not found:
                    raise ReconciliationError("question_not_found")
                q = found[1]
                pending = next(
                    entry
                    for entry in q.get("pending_actions", [])
                    if entry.get("resolution_id") == resolution_id
                )
                existing_action_id = _compact(pending.get("action_id"), 120)
                if existing_action_id and existing_action_id != action_id:
                    raise ReconciliationError("action_receipt_conflict")
                pending["action_id"] = action_id
                pending["state"] = "committed_unverified"
                q["state"] = "committed_unverified"
        try:
            readback = _request(
                config,
                transport,
                "GET",
                f"/api/reconciliation/actions/{action_id}",
                None,
                auth=True,
            )
            if not _verified_action(readback, action, action_id):
                readback = _request(
                    config,
                    transport,
                    "GET",
                    f"/api/reconciliation/actions/{action_id}",
                    None,
                    auth=True,
                )
        except ReconciliationError:
            with store.update() as state:
                found = _find_question(state, question_id)
                if found:
                    found[1]["state"] = "committed_unverified"
            raise
        if not _verified_action(readback, action, action_id):
            with store.update() as state:
                found = _find_question(state, question_id)
                if found:
                    found[1]["state"] = "committed_unverified"
            raise ReconciliationError("action_readback_unverified")
        outcome = _compact_outcome(readback)
        with store.update() as state:
            found = _find_question(state, question_id)
            if not found:
                raise ReconciliationError("question_not_found")
            pending = next(
                entry
                for entry in found[1].get("pending_actions", [])
                if entry.get("resolution_id") == resolution_id
            )
            pending["state"] = "verified"
            pending["outcome"] = outcome

    eligible_item_ids = set(q_before.get("item_ids", [])) - handled_before
    action_item_ids = {
        str(answer.get("item_id") or "")
        for answer in supplied_answers
        if isinstance(answer, Mapping)
        and answer.get("action")
        and str(answer.get("item_id") or "") in eligible_item_ids
    }
    reviewed_no_action_ids = {
        str(answer.get("item_id") or "")
        for answer in supplied_answers
        if isinstance(answer, Mapping)
        and answer.get("option") == "keep"
        and str(answer.get("item_id") or "") in eligible_item_ids
    }
    deferred_now = {
        str(answer.get("item_id") or "")
        for answer in supplied_answers
        if isinstance(answer, Mapping)
        and answer.get("option") == "unsure"
        and str(answer.get("item_id") or "") in eligible_item_ids
    }
    resolved_now = action_item_ids | reviewed_no_action_ids
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        delivery_set, q = found
        results = [
            entry["outcome"]
            for entry in q.get("pending_actions", [])
            if entry.get("state") == "verified" and isinstance(entry.get("outcome"), Mapping)
        ]
        resolved_item_ids = set(q.get("resolved_item_ids", [])) | resolved_now
        deferred_item_ids = set(q.get("deferred_item_ids", [])) | deferred_now
        handled_item_ids = resolved_item_ids | deferred_item_ids
        pending_item_ids = [
            entry["item_id"]
            for entry in q.get("agenda", [])
            if entry["item_id"] not in handled_item_ids
        ]
        q["resolved_item_ids"] = [entry["item_id"] for entry in q.get("agenda", []) if entry["item_id"] in resolved_item_ids]
        q["deferred_item_ids"] = [entry["item_id"] for entry in q.get("agenda", []) if entry["item_id"] in deferred_item_ids]
        q["state"] = "awaiting_reply" if pending_item_ids else "deferred" if deferred_item_ids else "verified_applied"
        q["verified_outcomes"] = [
            *q.get("verified_outcomes", []),
            *[
                outcome
                for outcome in results
                if outcome.get("action_id")
                not in {existing.get("action_id") for existing in q.get("verified_outcomes", [])}
            ],
        ]
        q["resolution_ids"] = sorted(
            set(q.get("resolution_ids", []))
            | {action["resolution_id"] for action in action_payloads}
        )
        q.pop("pending_action_plan_digest", None)
        q.pop("pending_actions", None)
        resolved_fingerprints = set()
        for item_id, fingerprint in zip(q.get("item_ids", []), q.get("item_fingerprints", [])):
            if item_id in resolved_now:
                _mark_terminal(state, fingerprint, "verified_resolved")
                resolved_fingerprints.add(fingerprint)
            elif item_id in deferred_now:
                state["fingerprints"].setdefault(fingerprint, {})["suppressed_until"] = _iso(
                    _now() + timedelta(seconds=cfg.cooldown_seconds)
                )
        if resolved_fingerprints:
            _review_run_items(state, resolved_fingerprints)
        delivery_set["state"] = q["state"]
    if results:
        result_action = "partially_applied" if pending_item_ids else q["state"]
    elif reviewed_no_action_ids:
        result_action = "partially_reviewed" if pending_item_ids else "deferred" if deferred_now else "reviewed_no_change"
    elif deferred_now:
        result_action = "partially_deferred" if pending_item_ids else "deferred"
    else:
        result_action = "ambiguous_noop"
    result = {
        "ok": True,
        "action": result_action,
        "question_id": question_id,
        "outcomes": results,
        "resolved_item_ids": [entry["item_id"] for entry in q.get("agenda", []) if entry["item_id"] in resolved_now],
        "deferred_item_ids": [entry["item_id"] for entry in q.get("agenda", []) if entry["item_id"] in deferred_now],
        "pending_item_ids": pending_item_ids,
        "next_question": next((entry["question"] for entry in q.get("agenda", []) if entry["item_id"] in set(pending_item_ids)), None),
        "bridge_terminal_recommended": not pending_item_ids,
    }
    with store.update() as state:
        found = _find_question(state, question_id)
        if not found:
            raise ReconciliationError("question_not_found")
        current = found[1]
        if current.get("submission_digest") != submission_digest:
            raise ReconciliationError("submission_retry_mismatch")
        current["last_submission_digest"] = submission_digest
        current["last_apply_result"] = json.loads(json.dumps(result))
        current.pop("submission_digest", None)
    return result


def status(config: RouterConfig, store: StateStore) -> dict[str, Any]:
    state = store.read()
    counts: dict[str, int] = {}
    for delivery_set in state["delivery_sets"].values():
        for q in delivery_set.get("questions", {}).values():
            counts[q.get("state", "unknown")] = counts.get(q.get("state", "unknown"), 0) + 1
    cfg = config.kinlayer.reconciliation
    active = [
        (delivery, q)
        for delivery in state["delivery_sets"].values()
        for q in delivery.get("questions", {}).values()
        if q.get("adapter_version") == ADAPTER_VERSION
        and q.get("state") in QUESTION_STATES
    ]
    active_question = None
    if len(active) == 1:
        delivery, q = active[0]
        resumable = q.get("state") in {"staged", "awaiting_reply"}
        active_question = {
            "delivery_set_id": str(delivery["delivery_set_id"]),
            "question_id": str(q["question_id"]),
            "state": str(q["state"]),
            "resumable": resumable,
            **(
                {"bridge_conversation_id": str(_bridge_id(q))}
                if _bridge_id(q) else {}
            ),
            **({"attention": {"intent_id": str(_attention(q)["intent_id"]), "state": str(_attention(q)["state"])}} if _attention(q) else {}),
        }
    return {
        "ok": True,
        "mode": cfg.mode,
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "target_guild_id": cfg.guild_id,
        "target_parent_channel_id": cfg.reconciliation_parent_channel_id,
        "target_thread_id": cfg.channel_id,
        "owner_count": len(cfg.owner_ids),
        "question_states": counts,
        "prepared_count": len(state["prepared_items"]),
        "active_question": active_question,
        "legacy_migration": _legacy_report(state),
    }


def _legacy_report(state: Mapping[str, Any]) -> dict[str, int]:
    report = {"awaiting_reply": 0, "claimed": 0, "applying": 0, "committed_unverified": 0, "other_nonterminal": 0}
    for delivery in state.get("delivery_sets", {}).values():
        for q in delivery.get("questions", {}).values():
            if q.get("adapter_version") == ADAPTER_VERSION or q.get("state") in TERMINAL_STATES:
                continue
            name = str(q.get("state") or "")
            if name in report:
                report[name] += 1
            elif name in LEGACY_NONTERMINAL_STATES:
                report["other_nonterminal"] += 1
    return report


def _summary_record_bindings(item: Mapping[str, Any]) -> list[dict[str, str]]:
    candidates = item.get("candidates")
    if isinstance(candidates, list) and candidates:
        return sorted(
            [
                {
                    "record_id": str(candidate.get("id") or ""),
                    "record_digest": str(candidate.get("fingerprint") or ""),
                }
                for candidate in candidates
                if isinstance(candidate, Mapping)
            ],
            key=lambda value: (value["record_id"], value["record_digest"]),
        )
    entities = item.get("expected_entities")
    if isinstance(entities, list) and entities:
        return sorted(
            [
                {
                    "record_id": str(entity.get("id") or ""),
                    "record_digest": str(entity.get("entity_digest") or ""),
                }
                for entity in entities
                if isinstance(entity, Mapping)
            ],
            key=lambda value: (value["record_id"], value["record_digest"]),
        )
    return []


def _validate_record_summary(
    value: Any,
    forbidden_identifiers: set[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 300:
        raise ReconciliationError("plan_record_summaries_invalid")
    if "\n" in value or "\r" in value or re.search(r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]", value):
        raise ReconciliationError("plan_record_summaries_invalid")
    normalized = unicodedata.normalize("NFKC", value)
    lowered = normalized.casefold()
    forbidden = {
        "options:", "actions:", "record_summaries", "source_session", "session_id",
        "conversation_id", "question_id", "item_id", "message_id", "fingerprint",
        "payload_digest", "evidence_digest", "candidate_id", "entity_id", "claim_token",
        *ALLOWED_OPTIONS, *ALLOWED_ACTIONS,
    }
    if any(token in lowered for token in forbidden):
        raise ReconciliationError("plan_record_summaries_invalid")
    if _contains_private_identifier(value, forbidden_identifiers):
        raise ReconciliationError("plan_record_summaries_invalid")
    if re.search(r"sha256:[0-9a-f]{32,}|\b[0-9a-f]{64}\b", value, re.IGNORECASE):
        raise ReconciliationError("plan_record_summaries_invalid")
    if re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", value, re.IGNORECASE):
        raise ReconciliationError("plan_record_summaries_invalid")
    if re.search(r"(?:^|\s)(?:rq|ri|ds|pc|candidate|entity|session)[_:-][A-Za-z0-9_-]{4,}", value, re.IGNORECASE):
        raise ReconciliationError("plan_record_summaries_invalid")
    if re.match(r"^(?:user|assistant|system|사용자|어시스턴트|봇)\s*[:：]", value, re.IGNORECASE):
        raise ReconciliationError("plan_record_summaries_invalid")
    if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
        raise ReconciliationError("plan_record_summaries_invalid")
    return value


def _contains_private_identifier(
    text: str,
    forbidden_identifiers: set[str] | None = None,
) -> bool:
    normalized = unicodedata.normalize("NFKC", text)
    if re.search(r"evidence:[0-9a-f]{32}", normalized, re.IGNORECASE):
        return True
    return any(
        identifier
        and re.search(
            rf"(?<![A-Za-z0-9_-]){re.escape(unicodedata.normalize('NFKC', identifier))}(?![A-Za-z0-9_-])",
            normalized,
            re.IGNORECASE,
        )
        for identifier in forbidden_identifiers or set()
    )


def _validate_record_summaries(
    value: Any,
    item: Mapping[str, Any],
    additional_forbidden_identifiers: set[str] | None = None,
) -> list[dict[str, str]]:
    expected = _summary_record_bindings(item)
    if not expected:
        if value in (None, []):
            return []
        raise ReconciliationError("plan_record_summaries_invalid")
    if len(expected) == 1 and value is None:
        return []
    if not isinstance(value, list) or len(value) != len(expected):
        raise ReconciliationError("plan_record_summaries_invalid")
    validated: list[dict[str, str]] = []
    forbidden_identifiers = {
        identifier
        for binding in expected
        for identifier in (binding["record_id"], binding["record_digest"])
    }
    forbidden_identifiers.update(additional_forbidden_identifiers or set())
    for supplied, binding in zip(value, expected):
        if not isinstance(supplied, Mapping) or set(supplied) != {
            "record_id",
            "record_digest",
            "summary",
        }:
            raise ReconciliationError("plan_record_summaries_invalid")
        if (
            str(supplied.get("record_id") or "") != binding["record_id"]
            or str(supplied.get("record_digest") or "") != binding["record_digest"]
            or not binding["record_id"]
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", binding["record_digest"])
        ):
            raise ReconciliationError("plan_record_summaries_invalid")
        validated.append(
            {
                **binding,
                "summary": _validate_record_summary(
                    supplied.get("summary"),
                    forbidden_identifiers,
                ),
            }
        )
    if len({entry["summary"] for entry in validated}) != len(validated):
        raise ReconciliationError("plan_record_summaries_invalid")
    return validated


def _normalized_summary_excerpt(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _summary_exposes_excerpt(summary: str, excerpt: str) -> bool:
    """Reject full excerpt reuse and substantial verbatim source slices after conservative normalization."""
    normalized_summary = _normalized_summary_excerpt(summary)
    normalized_excerpt = _normalized_summary_excerpt(excerpt)
    if not normalized_summary or not normalized_excerpt:
        return False
    if normalized_excerpt in normalized_summary:
        return True
    return any(
        normalized_excerpt[index:index + MIN_SUMMARY_SOURCE_SLICE_CHARS]
        in normalized_summary
        for index in range(
            len(normalized_excerpt) - MIN_SUMMARY_SOURCE_SLICE_CHARS + 1
        )
    )


def _assert_visible_texts_do_not_expose_prepared_excerpts(
    entries: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
    visible_texts: list[str],
) -> None:
    prepared_excerpts = [
        excerpt
        for _, entry in entries
        for claim in entry.get("prepared_context_claims", [])
        if isinstance(claim, Mapping)
        for excerpt in [claim.get("evidence_excerpt")]
        if isinstance(excerpt, str) and excerpt.strip()
    ]
    if any(
        _summary_exposes_excerpt(text, excerpt)
        for text in visible_texts
        for excerpt in prepared_excerpts
    ):
        raise ReconciliationError("plan_prepared_context_excerpt_invalid")


def _validate_plan_item(
    entry: Any,
    prepared: dict[str, Any],
    current_ids: set[str],
    plan_record_identifiers: set[str] | None = None,
) -> dict[str, Any]:
    allowed = {"item_id", "fingerprint", "inspected_session_ids", "name_query", "rationale", "disposition", "question", "options", "record_summaries", "prepared_context_claims"}
    if not isinstance(entry, Mapping) or set(entry) - allowed:
        raise ReconciliationError("plan_schema_invalid")
    item = prepared.get(str(entry.get("item_id")))
    if not item or item.get("item_id") not in current_ids or entry.get("fingerprint") != item.get("fingerprint"):
        raise ReconciliationError("plan_stale")
    inspected = entry.get("inspected_session_ids")
    if not isinstance(inspected, list) or any(_compact(v, 160) != str(v) for v in inspected) or not _compact(entry.get("rationale"), 500):
        raise ReconciliationError("plan_inspection_missing")
    required = set(item.get("source_session_ids", []))
    if set(inspected) != required or len(inspected) != len(required):
        raise ReconciliationError("plan_source_sessions_uninspected")
    name_query = entry.get("name_query")
    if name_query is not None and (not isinstance(name_query, str) or len(name_query) > 160):
        raise ReconciliationError("plan_name_query_invalid")
    allowed_queries = item.get("search_terms", [])
    if (name_query is None and allowed_queries) or (name_query is not None and name_query not in allowed_queries):
        raise ReconciliationError("plan_name_query_invalid")
    disposition = str(entry.get("disposition") or "")
    if disposition not in PLAN_DISPOSITIONS:
        raise ReconciliationError("plan_disposition_invalid")
    raw_question = entry.get("question")
    question_text = raw_question if isinstance(raw_question, str) else ""
    options = entry.get("options")
    if disposition == "question":
        if not question_text.strip() or len(question_text) > 1_000:
            raise ReconciliationError("plan_question_missing")
        _validate_natural_question(question_text, plan_record_identifiers)
        if not isinstance(options, list) or not options or any(str(x) not in item["allowed_options"] for x in options):
            raise ReconciliationError("plan_options_invalid")
        _validate_record_summaries(
            entry.get("record_summaries"),
            item,
            plan_record_identifiers,
        )
        claims = entry.get("prepared_context_claims", [])
        if not isinstance(claims, list) or len(claims) > MAX_CONTEXT_CLAIMS:
            raise ReconciliationError("plan_prepared_context_invalid")
        if claims and not any(OPTION_ACTIONS[str(option)] & CONTEXT_ACTIONS for option in options):
            raise ReconciliationError("plan_prepared_context_action_ineligible")
    elif question_text or options not in (None, []) or entry.get("prepared_context_claims") not in (None, []):
        raise ReconciliationError("plan_question_not_allowed")
    return item


def _stage_prepared_context_claims(
    config: RouterConfig,
    transport: Transport | None,
    item: Mapping[str, Any],
    entry: Mapping[str, Any],
    visible_summaries: list[str],
) -> list[dict[str, Any]]:
    supplied = entry.get("prepared_context_claims", [])
    if not supplied:
        return []
    candidates = item.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ReconciliationError("plan_prepared_context_candidate_invalid")
    candidate_ids = [str(candidate.get("id") or "") for candidate in candidates if isinstance(candidate, Mapping)]
    if len(candidate_ids) != len(candidates) or len(candidate_ids) != len(set(candidate_ids)):
        raise ReconciliationError("plan_prepared_context_candidate_invalid")
    query = urlencode([("candidate_id", candidate_id) for candidate_id in sorted(candidate_ids)])
    response = _request(
        config,
        transport,
        "GET",
        f"/api/reconciliation/candidate-evidence-snapshots?{query}",
        None,
        auth=True,
    )
    current_items = response.get("items")
    if not isinstance(current_items, list) or len(current_items) != len(candidate_ids):
        raise ReconciliationError("prepared_evidence_snapshot_invalid")
    current_by_id = {
        str(candidate.get("id") or ""): candidate
        for candidate in current_items
        if isinstance(candidate, Mapping)
    }
    if set(current_by_id) != set(candidate_ids) or len(current_by_id) != len(current_items):
        raise ReconciliationError("prepared_evidence_snapshot_invalid")

    authoritative: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for stored_candidate in candidates:
        candidate_id = str(stored_candidate["id"])
        current = current_by_id[candidate_id]
        if (
            current.get("status") != stored_candidate.get("status")
            or _parse_time(current.get("updated_at")) != _parse_time(stored_candidate.get("updated_at"))
            or current.get("payload_digest") != stored_candidate.get("payload_digest")
            or current.get("evidence_digest") != stored_candidate.get("evidence_digest")
        ):
            raise ReconciliationError("prepared_evidence_stale")
        stored_evidence = stored_candidate.get("evidence")
        current_evidence = current.get("evidence")
        if not isinstance(stored_evidence, list) or not isinstance(current_evidence, list):
            raise ReconciliationError("prepared_evidence_snapshot_invalid")
        stored_by_handle = {
            str(evidence.get("handle") or ""): evidence
            for evidence in stored_evidence
            if isinstance(evidence, Mapping)
        }
        if len(stored_by_handle) != len(stored_evidence):
            raise ReconciliationError("prepared_evidence_commitment_mismatch")
        matched_handles = set()
        for evidence in current_evidence:
            if not isinstance(evidence, Mapping) or set(evidence) - {"effective_sensitivity"} != {
                "id", "episode_id", "excerpt", "source_type", "actor", "body_hash",
                "effective_ai_use_policy",
            }:
                raise ReconciliationError("prepared_evidence_snapshot_invalid")
            excerpt = evidence.get("excerpt")
            if (
                evidence.get("actor") != "user"
                or evidence.get("source_type") != "agent_conversation"
                or not isinstance(excerpt, str)
                or not 1 <= len(excerpt) <= 500
                or ("effective_sensitivity" in evidence and evidence["effective_sensitivity"] not in ("low", "medium", "high"))
                or evidence.get("effective_ai_use_policy") not in CONTEXT_AI_USE_POLICIES
            ):
                raise ReconciliationError("prepared_evidence_source_invalid")
            commitment = {
                "candidate_id": candidate_id,
                "evidence_id": str(evidence.get("id") or ""),
                "episode_id": str(evidence.get("episode_id") or ""),
                "body_hash": str(evidence.get("body_hash") or ""),
                "excerpt_hash": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
                "excerpt_codepoints": len(excerpt),
                "effective_ai_use_policy": evidence["effective_ai_use_policy"],
            }
            # Preserve legacy stored handles/digests without making the retired
            # label authoritative. Compare every live provenance/policy field,
            # then verify the original stored commitment hash before using it.
            matches = [
                (handle, stored) for handle, stored in stored_by_handle.items()
                if {k: v for k, v in stored.items() if k not in {"handle", "effective_sensitivity"}} == commitment
            ]
            if len(matches) != 1:
                raise ReconciliationError("prepared_evidence_commitment_mismatch")
            handle, stored = matches[0]
            if (
                ("effective_sensitivity" in stored and stored["effective_sensitivity"] not in ("low", "medium", "high"))
                or handle != "evidence:" + _digest({k: v for k, v in stored.items() if k != "handle"})[7:39]
                or handle in matched_handles
            ):
                raise ReconciliationError("prepared_evidence_commitment_mismatch")
            matched_handles.add(handle)
            authoritative[handle] = (commitment, evidence)
        if matched_handles != set(stored_by_handle):
            raise ReconciliationError("prepared_evidence_commitment_mismatch")

    stored_claims = []
    for raw in supplied:
        allowed = {
            "claim_id", "target", "kind", "fact_type", "field_path", "relation_type",
            "observation_type", "claim_type", "candidate_evidence_handle", "evidence_excerpt",
        }
        if not isinstance(raw, Mapping) or set(raw) - allowed:
            raise ReconciliationError("plan_prepared_context_schema_invalid")
        typed = {key: value for key, value in raw.items() if key not in {"candidate_evidence_handle", "evidence_excerpt"}}
        typed["answer_item_id"] = item["item_id"]
        if not _claim_typing_valid(typed):
            raise ReconciliationError("plan_prepared_context_typing_invalid")
        kind = str(typed["kind"])
        type_key = CONTEXT_TYPE_FIELDS[kind][0]
        permitted_type_keys = {type_key} | ({"field_path"} if kind == "profile_field" else set())
        if any(key in typed for key in {"fact_type", "field_path", "relation_type", "observation_type"} - permitted_type_keys):
            raise ReconciliationError("plan_prepared_context_typing_invalid")
        handle = str(raw.get("candidate_evidence_handle") or "")
        excerpt = raw.get("evidence_excerpt")
        match = authoritative.get(handle)
        if match is None:
            raise ReconciliationError("plan_prepared_context_handle_invalid")
        if not isinstance(excerpt, str) or not 1 <= len(excerpt) <= 500:
            raise ReconciliationError("plan_prepared_context_excerpt_invalid")
        if any(_summary_exposes_excerpt(summary, excerpt) for summary in visible_summaries):
            raise ReconciliationError("plan_prepared_context_excerpt_invalid")
        full_excerpt = str(match[1]["excerpt"])
        start = full_excerpt.find(excerpt)
        if start < 0 or full_excerpt.find(excerpt, start + 1) >= 0:
            raise ReconciliationError("plan_prepared_context_excerpt_invalid")
        commitment = match[0]
        stored_claims.append({
            **typed,
            "ai_use_policy": commitment["effective_ai_use_policy"],
            "evidence": {
                "evidence_class": "prepared_candidate_evidence",
                "handle": handle,
                "candidate_id": commitment["candidate_id"],
                "evidence_id": commitment["evidence_id"],
                "episode_id": commitment["episode_id"],
                "body_hash": commitment["body_hash"],
                "excerpt_hash": commitment["excerpt_hash"],
                "start": start,
                "end": start + len(excerpt),
            },
        })
    claim_ids = [str(claim.get("claim_id") or "") for claim in stored_claims]
    if claim_ids != sorted(set(claim_ids)):
        raise ReconciliationError("plan_prepared_context_order_invalid")
    if len({_claim_semantic(claim) for claim in stored_claims}) != len(stored_claims):
        raise ReconciliationError("plan_prepared_context_duplicate")
    return stored_claims


INTERVIEW_FORM_PATTERNS = (
    r"(?:^|\n)\s*\d+[.)]\s+",
    r"(?:^|\n)\s*[-*•]\s+",
    r"\b(?:question|item|record)\s*#?\s*\d+\b",
    r"(?:질문|항목|기록)\s*\d+",
    r"(?:첫|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*번째\s*(?:질문|항목|기록)",
    r"(?<!\d)\d+\s*/\s*\d+(?!\d)",
    r"(?:선택지|보기|옵션)\s*[:：]",
    r"(?:다음|남은)\s*(?:질문|항목)",
    r"(?:번호|숫자)로\s*(?:답|대답)",
)


def contains_form_like_interview_language(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in INTERVIEW_FORM_PATTERNS)


def _validate_natural_question(
    text: str,
    forbidden_identifiers: set[str] | None = None,
) -> None:
    if (
        text != text.strip()
        or len(text) > 180
        or "\n" in text
        or "\r" in text
        or text.count("?") != 1
        or not text.endswith("?")
    ):
        raise ReconciliationError("plan_question_form_like")
    if re.search(r"[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]", text):
        raise ReconciliationError("plan_question_technical_content")
    lowered = text.casefold()
    forbidden_literals = {
        "options:", "[kinlayer-", "nonce=", "fingerprint", "claim_token",
        "claim token", "question_id", "question id", "item_id", "item id",
        "delivery_set_id", "delivery set id", "message_id", "message id",
        *ALLOWED_OPTIONS, *ALLOWED_ACTIONS,
    }
    if any(value in lowered for value in forbidden_literals):
        raise ReconciliationError("plan_question_technical_content")
    if _contains_private_identifier(text, forbidden_identifiers):
        raise ReconciliationError("plan_question_technical_content")
    if re.search(r"(?:^|\s)(?:rq|ri|ds)_[A-Za-z0-9_-]{4,}", text):
        raise ReconciliationError("plan_question_technical_content")
    if contains_form_like_interview_language(text):
        raise ReconciliationError("plan_question_form_like")


def _relationship_to_self(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"relation_type", "claim_text"}:
        raise ReconciliationError("answer_relationship_schema_invalid")
    relation_type = value.get("relation_type")
    claim_text = value.get("claim_text")
    if (
        not isinstance(relation_type, str)
        or not relation_type.strip()
        or len(relation_type) > 80
        or _compact(relation_type, 80) != relation_type.strip()
        or not isinstance(claim_text, str)
        or not claim_text.strip()
        or len(claim_text) > 500
        or _compact(claim_text, 500) != claim_text.strip()
    ):
        raise ReconciliationError("answer_relationship_schema_invalid")
    return {"relation_type": relation_type.strip(), "claim_text": claim_text.strip()}


def _answer_actions(answers: list[Any], q: dict[str, Any], prepared: dict[str, Any]) -> list[dict[str, Any] | None]:
    results = []
    seen = set()
    handled = set(q.get("resolved_item_ids", [])) | set(q.get("deferred_item_ids", []))
    for answer in answers:
        allowed = {"item_id", "option", "action", "source_entity_id", "target_entity_id", "canonical_name", "display_name", "relationship_to_self", "resolution_note"}
        if not isinstance(answer, Mapping) or set(answer) - allowed:
            raise ReconciliationError("answer_schema_invalid")
        item_id = str(answer.get("item_id") or "")
        if item_id in handled:
            continue
        if item_id not in prepared or item_id in seen:
            raise ReconciliationError("answer_item_invalid")
        seen.add(item_id)
        option = str(answer.get("option") or "")
        item = prepared[item_id]
        if option not in item.get("allowed_options", []):
            raise ReconciliationError("answer_option_invalid")
        allowed_actions = OPTION_ACTIONS.get(option)
        if allowed_actions is None:
            raise ReconciliationError("answer_option_invalid")
        relationship_to_self = _relationship_to_self(answer.get("relationship_to_self"))
        if not allowed_actions:
            if answer.get("action") or relationship_to_self is not None:
                raise ReconciliationError("answer_action_not_allowed_for_option")
            results.append(None)
            continue
        action = str(answer.get("action") or "")
        if action not in ALLOWED_ACTIONS or action not in allowed_actions:
            raise ReconciliationError("answer_action_invalid")
        if relationship_to_self is not None and not (
            option == "same_person" and action == "rename_and_accept_new_entity"
        ):
            raise ReconciliationError("answer_relationship_not_allowed")
        expected = [{"id": c["id"], "status": c["status"], "updated_at": c["updated_at"], "payload_digest": c["payload_digest"], "evidence_digest": c["evidence_digest"]} for c in item["candidates"]]
        source_entity_id = _compact(answer.get("source_entity_id"), 36) or None
        target_entity_id = _compact(answer.get("target_entity_id"), 36) or None
        canonical_name = _compact(answer.get("canonical_name"), 160) or None
        display_name = _compact(answer.get("display_name"), 160) or None
        expected_entities: list[dict[str, Any]] = []
        if action == "merge_existing_entities":
            if item.get("kind") != "duplicate_canonical_person":
                raise ReconciliationError("answer_action_invalid")
            if source_entity_id != item.get("source_entity_id") or target_entity_id != item.get("target_entity_id"):
                raise ReconciliationError("answer_entity_mismatch")
            expected_entities = list(item.get("expected_entities", []))
            if len(expected_entities) != 2 or {x.get("id") for x in expected_entities} != {source_entity_id, target_entity_id}:
                raise ReconciliationError("answer_entity_snapshot_invalid")
            if expected or item.get("candidates"):
                raise ReconciliationError("answer_entity_candidate_mismatch")
            if canonical_name or display_name:
                raise ReconciliationError("answer_name_not_allowed")
        elif action == "archive_existing_entity":
            if item.get("kind") != "recent_canonical_person_review":
                raise ReconciliationError("answer_action_invalid")
            if source_entity_id != item.get("source_entity_id") or target_entity_id is not None:
                raise ReconciliationError("answer_entity_mismatch")
            expected_entities = list(item.get("expected_entities", []))
            if len(expected_entities) != 1 or expected_entities[0].get("id") != source_entity_id:
                raise ReconciliationError("answer_entity_snapshot_invalid")
            if expected or item.get("candidates"):
                raise ReconciliationError("answer_entity_candidate_mismatch")
            if canonical_name or display_name:
                raise ReconciliationError("answer_name_not_allowed")
        elif source_entity_id is not None:
            raise ReconciliationError("answer_source_entity_not_allowed")
        if action == "accept_existing_entity_observation_group":
            reviewed_target_entity_id = _observation_group_target(item)
            if target_entity_id and target_entity_id != reviewed_target_entity_id:
                raise ReconciliationError("answer_entity_mismatch")
            target_entity_id = reviewed_target_entity_id
            expected_entities = list(item.get("expected_entities", []))
            if (
                len(expected_entities) != 1
                or expected_entities[0].get("id") != target_entity_id
            ):
                raise ReconciliationError("answer_entity_snapshot_invalid")
        if action == "map_to_existing_entity":
            if not target_entity_id or target_entity_id != item.get("target_entity_id"):
                raise ReconciliationError("answer_entity_mismatch")
            expected_entities = list(item.get("expected_entities", []))
            if len(expected_entities) != 1 or expected_entities[0].get("id") != target_entity_id:
                raise ReconciliationError("answer_entity_snapshot_invalid")
        elif action not in {"accept_existing_entity_observation_group", "merge_existing_entities", "archive_existing_entity"} and target_entity_id is not None:
            raise ReconciliationError("answer_target_entity_not_allowed")
        if action == "rename_and_accept_new_entity":
            if not display_name:
                raise ReconciliationError("answer_display_name_required")
        elif canonical_name or display_name:
            raise ReconciliationError("answer_name_not_allowed")
        resolution_id = _resolution_id(q, item_id, option, action)
        conversation_id = _compact(_bridge_id(q), 160)
        result = {"resolution_id": resolution_id, "action": action, "candidate_ids": [c["id"] for c in item["candidates"]], "expected_candidates": expected, "expected_entities": expected_entities, "source_entity_id": source_entity_id, "target_entity_id": target_entity_id, "canonical_name": canonical_name, "display_name": display_name, "resolution_note": _compact(answer.get("resolution_note") or f"verified reconciliation {option}", 300), "source": {"user_explicit": True, "source_type": "agent_conversation", "source_ref": conversation_id, "source_actor": "user"}, "_answer_item_id": item_id}
        if relationship_to_self is not None:
            result["relationship_to_self"] = relationship_to_self
        results.append(result)
    return results


def _compile_context_claims(
    claims: list[Any], answers: list[Any], reply: str, prepared: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    answer_actions = {
        str(answer.get("item_id")): str(answer.get("action") or "")
        for answer in answers if isinstance(answer, Mapping)
    }
    compiled: dict[str, list[dict[str, Any]]] = {}
    seen_semantics = set()
    prior_claim_id = ""
    for raw in claims:
        allowed = {
            "claim_id", "item_id", "target", "kind", "fact_type", "field_path",
            "relation_type", "observation_type", "claim_type", "evidence",
        }
        if not isinstance(raw, Mapping) or set(raw) - allowed:
            raise ReconciliationError("context_claim_schema_invalid")
        claim_id = str(raw.get("claim_id") or "")
        item_id = str(raw.get("item_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", claim_id) or claim_id <= prior_claim_id:
            raise ReconciliationError("context_claim_order_invalid")
        prior_claim_id = claim_id
        if item_id not in prepared or answer_actions.get(item_id) not in CONTEXT_ACTIONS:
            raise ReconciliationError("context_claim_item_invalid")
        if raw.get("target") != "primary_entity":
            raise ReconciliationError("context_claim_target_invalid")
        kind = str(raw.get("kind") or "")
        claim_type = str(raw.get("claim_type") or "")
        if kind not in CONTEXT_TYPE_FIELDS:
            raise ReconciliationError("context_claim_kind_invalid")
        type_key, allowed_types = CONTEXT_TYPE_FIELDS[kind]
        selected_type = str(raw.get(type_key) or "")
        if selected_type not in allowed_types:
            raise ReconciliationError("context_claim_type_invalid")
        if kind == "profile_field" and (
            raw.get("field_path") != selected_type or claim_type != "fact"
        ):
            raise ReconciliationError("context_claim_type_invalid")
        if kind == "relationship_edge" and claim_type != "fact":
            raise ReconciliationError("context_claim_type_invalid")
        if kind == "observation" and claim_type not in {"fact", "preference", "pattern"}:
            raise ReconciliationError("context_claim_type_invalid")
        semantic = (item_id, kind, selected_type, raw.get("field_path"))
        if semantic in seen_semantics:
            raise ReconciliationError("context_claim_duplicate")
        seen_semantics.add(semantic)
        evidence = raw.get("evidence")
        if not isinstance(evidence, Mapping):
            raise ReconciliationError("context_evidence_invalid")
        evidence_class = evidence.get("evidence_class")
        if evidence_class == "current_reply":
            if set(evidence) != {"evidence_class", "start", "end"}:
                raise ReconciliationError("context_evidence_invalid")
            start, end = evidence.get("start"), evidence.get("end")
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or not 0 <= start < end <= len(reply):
                raise ReconciliationError("context_evidence_span_invalid")
            compiled_evidence = {"evidence_class": "current_reply", "start": start, "end": end}
        else:
            raise ReconciliationError("context_evidence_invalid")
        result = {
            "claim_id": claim_id, "answer_item_id": item_id, "target": "primary_entity",
            "kind": kind, "claim_type": claim_type, "ai_use_policy": "cautious_use",
            type_key: selected_type, "evidence": compiled_evidence,
        }
        if kind == "profile_field":
            result["field_path"] = selected_type
        compiled.setdefault(item_id, []).append(result)
    return compiled


def _prepared_context_for_answers(
    q: Mapping[str, Any], answers: list[Any]
) -> dict[str, list[dict[str, Any]]]:
    answer_actions = {
        str(answer.get("item_id") or ""): str(answer.get("action") or "")
        for answer in answers
        if isinstance(answer, Mapping)
    }
    return {
        str(entry["item_id"]): json.loads(json.dumps(entry.get("prepared_context_claims", [])))
        for entry in _validated_agenda(q)
        if answer_actions.get(str(entry["item_id"])) in CONTEXT_ACTIONS
        and entry.get("prepared_context_claims")
    }


def _merge_context_claims(
    explicit: dict[str, list[dict[str, Any]]],
    prepared: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    for item_id in sorted(set(explicit) | set(prepared)):
        claims = json.loads(json.dumps([*explicit.get(item_id, []), *prepared.get(item_id, [])]))
        for claim in claims:
            claim.pop("sensitivity", None)  # Inert legacy stored claims, never new API output.
            evidence = claim.get("evidence")
            if isinstance(evidence, dict) and evidence.get("evidence_class") == "prepared_candidate_evidence":
                evidence.pop("handle", None)
        claims.sort(key=lambda claim: str(claim.get("claim_id") or ""))
        claim_ids = [str(claim.get("claim_id") or "") for claim in claims]
        if len(claims) > MAX_CONTEXT_CLAIMS:
            raise ReconciliationError("context_claim_limit_exceeded")
        if claim_ids != sorted(set(claim_ids)):
            raise ReconciliationError("context_claim_duplicate")
        if len({_claim_semantic(claim) for claim in claims}) != len(claims):
            raise ReconciliationError("context_claim_duplicate")
        merged[item_id] = claims
    return merged


def _candidate_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    evidence = []
    for value in list(raw.get("evidence", []))[:20]:
        if (
            isinstance(value, Mapping)
            and value.get("actor") == "user"
            and value.get("source_type") == "agent_conversation"
        ):
            excerpt = str(value.get("excerpt") or "")
            candidate_id = _compact(raw.get("id"), 120)
            evidence_id = _compact(
                value.get("id") or value.get("evidence_id") or value.get("candidate_evidence_id"),
                36,
            )
            episode_id = _compact(value.get("episode_id"), 36)
            payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
            candidate_policy = str(payload.get("ai_use_policy") or "cautious_use")
            if candidate_policy not in AI_USE_POLICY_RANK:
                raise ReconciliationError("candidate_evidence_policy_invalid")
            commitment = {
                "candidate_id": candidate_id, "evidence_id": evidence_id,
                "episode_id": episode_id,
                "body_hash": _compact(value.get("body_hash"), 80),
                "excerpt_hash": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
                "excerpt_codepoints": len(excerpt),
                "effective_ai_use_policy": max(
                    ("cautious_use", candidate_policy),
                    key=AI_USE_POLICY_RANK.__getitem__,
                ),
            }
            if (
                not all((candidate_id, evidence_id, episode_id))
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", commitment["body_hash"])
                or not 1 <= commitment["excerpt_codepoints"] <= 500
            ):
                raise ReconciliationError("candidate_evidence_commitment_invalid")
            commitment["handle"] = "evidence:" + _digest(commitment)[7:39]
            evidence.append(commitment)
    payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else {}
    identity_keys = {"entity_type", "display_name", "canonical_name", "name", "protected_self", "person_key", "unresolved_identity_key", "duplicate_group_id"}
    compact_payload = {str(k): _compact(v, 300) for k, v in payload.items() if k in identity_keys}
    snapshot = {"id": _compact(raw.get("id"), 120), "candidate_type": _compact(raw.get("candidate_type") or raw.get("type"), 80), "status": _compact(raw.get("status") or "pending", 40), "updated_at": _compact(raw.get("updated_at"), 80), "target_entity_id": _compact(raw.get("target_entity_id"), 120) or None, "payload": compact_payload, "evidence": evidence}
    snapshot["payload_digest"] = _compact(raw.get("payload_digest"), 80)
    snapshot["evidence_digest"] = _compact(raw.get("evidence_digest"), 80)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot["payload_digest"]):
        raise ReconciliationError("candidate_payload_digest_missing")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot["evidence_digest"]):
        raise ReconciliationError("candidate_evidence_digest_missing")
    if not snapshot["updated_at"]:
        raise ReconciliationError("candidate_updated_at_missing")
    snapshot["fingerprint"] = _digest({k: snapshot[k] for k in ("id", "status", "updated_at", "payload_digest", "evidence_digest")})
    return snapshot


def _classify_group(key: str, members: list[dict[str, Any]], entity_names: dict[str, list[str]]) -> str:
    if any(str(m["payload"].get("protected_self", "")).casefold() == "true" for m in members):
        return "self_entity_false_positive"
    if len(members) > 1:
        return "duplicate_new_entity_group"
    name = _name(members[0])
    normalized = _normalize(name)
    if normalized in entity_names:
        return "existing_entity_name_variant"
    if not name or _role_title(name):
        return "role_title_identity"
    return "existing_entity_name_variant"


def _options_for(kind: str) -> list[str]:
    return {"self_entity_false_positive": ["do_not_store", "unsure"], "duplicate_new_entity_group": ["same_person", "different_person", "do_not_store", "unsure"], "role_title_identity": ["provide_name", "do_not_store", "unsure"], "recent_canonical_anomaly": ["keep", "unsure"]}.get(kind, ["map_existing", "different_person", "do_not_store", "unsure"])


def _name(value: Mapping[str, Any]) -> str:
    payload = value.get("payload") if isinstance(value.get("payload"), Mapping) else value
    return _compact(payload.get("display_name") or payload.get("canonical_name") or payload.get("name"), 160)


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", value.casefold())


def _role_title(name: str) -> bool:
    return bool(re.fullmatch(r"(?:[가-힣]{1,8})(?:님|씨|선생님|팀장님|대표님|전무님|부장님)", name))


def _source_session_id(ref: str) -> str:
    match = re.search(r"(?:session[:/=]|sessions/)([A-Za-z0-9_.:-]{1,160})", ref)
    if match:
        return match.group(1)
    prefix = ref.split(":", 1)[0]
    if re.fullmatch(r"(?:\d{8}_\d{6}_[A-Za-z0-9]+|cron_[A-Za-z0-9_-]{1,150})", prefix):
        return prefix
    return ""


def _bounded_cursor(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    return {str(k)[:40]: _compact(v, 120) for k, v in list(value.items())[:5]}


def parse_bridge_user_message(text: str) -> dict[str, str] | None:
    """Strip one exact PCB v1 wrapper for evidence hygiene; this grants no authority."""
    markers = list(BRIDGE_MARKER_RE.finditer(text))
    if len(markers) != 1 or text.count("[[HERMES-PCB-CLAIM-V1") != 1:
        return None
    marker = markers[0]
    tail = text[marker.end():]
    if not tail.startswith(USER_REPLY_SEPARATOR) or tail.count(USER_REPLY_SEPARATOR) != 1:
        return None
    user_reply = tail[len(USER_REPLY_SEPARATOR):]
    if len(user_reply) > MAX_BRIDGE_USER_TEXT or "[[HERMES-PCB-CLAIM-V1" in user_reply or "[USER-REPLY]" in user_reply:
        return None
    return {"user_reply": user_reply}


def _find_question(state: dict[str, Any], question_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for delivery_set in state.get("delivery_sets", {}).values():
        q = delivery_set.get("questions", {}).get(question_id)
        if q:
            return delivery_set, q
    return None


def _verified_action(
    value: Mapping[str, Any],
    expected_action: Mapping[str, Any] | None = None,
    action_id: str = "",
) -> bool:
    if not expected_action:
        return False
    readback_keys = {
        "id", "resolution_id", "action", "status", "verification_state",
        "candidate_ids", "derived_candidate_ids", "derived_candidates", "candidates",
        "source_entity_id", "target_entity_id", "primary_entity_id",
        "confirmation_episode_id", "canonical_refs", "context_outcomes",
        "answer_binding", "entity", "source_entity", "context_card", "error_code",
        "created_at", "updated_at",
    }
    if set(value) != readback_keys:
        return False
    bindings = expected_action.get("answer_bindings")
    action = expected_action.get("action")
    expected_ids = sorted(expected_action.get("candidate_ids", []))
    expected_candidates = expected_action.get("expected_candidates")
    expected_entities = expected_action.get("expected_entities", [])
    candidate_ids = value.get("candidate_ids")
    candidates = value.get("candidates")
    derived_ids = value.get("derived_candidate_ids")
    derived = value.get("derived_candidates")
    canonical_refs = value.get("canonical_refs")
    if (
        not isinstance(bindings, list)
        or len(bindings) != 1
        or value.get("answer_binding") != bindings[0]
        or not isinstance(action_id, str)
        or not action_id
        or value.get("id") != action_id
        or value.get("resolution_id") != expected_action.get("resolution_id")
        or action not in ALLOWED_ACTIONS
        or value.get("action") != action
        or value.get("status") != "verified"
        or value.get("verification_state") != "verified"
        or value.get("error_code") is not None
        or _parse_time(value.get("created_at")) is None
        or _parse_time(value.get("updated_at")) is None
        or not isinstance(value.get("confirmation_episode_id"), str)
        or not value["confirmation_episode_id"]
        or not all(isinstance(items, list) for items in (
            candidate_ids, candidates, derived_ids, derived, canonical_refs
        ))
        or not isinstance(expected_candidates, list)
        or [row.get("id") for row in expected_candidates if isinstance(row, Mapping)] != expected_ids
        or len(expected_candidates) != len(expected_ids)
        or len(expected_ids) != len(set(expected_ids))
        or not isinstance(expected_entities, list)
    ):
        return False
    if (
        candidate_ids != expected_ids
        or len(candidate_ids) != len(set(candidate_ids))
        or [row.get("id") for row in candidates if isinstance(row, Mapping)] != expected_ids
        or len(candidates) != len(expected_ids)
        or any(not _candidate_readback_row(row) for row in candidates)
        or len(derived_ids) != len(set(derived_ids))
        or [row.get("id") for row in derived if isinstance(row, Mapping)] != derived_ids
        or len(derived) != len(derived_ids)
        or any(not _derived_readback_row(row) for row in derived)
        or any(not isinstance(ref, str) or not ref for ref in canonical_refs)
        or len(canonical_refs) != len(set(canonical_refs))
    ):
        return False
    expected_by_id = {row["id"]: row for row in expected_candidates}
    if any(
        not isinstance(row, Mapping)
        or set(row) != {"id", "status", "updated_at", "payload_digest", "evidence_digest"}
        for row in expected_candidates
    ) or any(
        (
            not (action == "rename_and_accept_new_entity" and row["id"] == expected_ids[0])
            and row["payload_digest"] != expected_by_id[row["id"]]["payload_digest"]
        )
        or row["evidence_digest"] != expected_by_id[row["id"]]["evidence_digest"]
        for row in candidates
    ):
        return False
    if value.get("entity") is None:
        if value.get("context_card") is not None:
            return False
    elif value["entity"].get("status") == "active" and not _context_card_matches(
        value.get("context_card"), value.get("primary_entity_id")
    ):
        return False
    elif value["entity"].get("status") != "active" and value.get("context_card") is not None:
        return False
    context = value.get("context_outcomes")
    expected_context = expected_action.get("context_claims", [])
    if not isinstance(context, list) or not isinstance(expected_context, list):
        return False
    if len(context) != len(expected_context) or any(
        not isinstance(row, Mapping)
        or set(row) != {"claim_id", "kind", "candidate_id", "canonical_ref"}
        or (row.get("claim_id"), row.get("kind")) != (claim.get("claim_id"), claim.get("kind"))
        or not isinstance(row.get("candidate_id"), str)
        or not row.get("candidate_id")
        or not isinstance(row.get("canonical_ref"), str)
        or not row.get("canonical_ref")
        for row, claim in zip(context, expected_context)
        if isinstance(claim, Mapping)
    ) or any(not isinstance(claim, Mapping) for claim in expected_context):
        return False
    context_ids = [row["candidate_id"] for row in context]
    context_refs = [row["canonical_ref"] for row in context]
    if (
        len(context_ids) != len(set(context_ids))
        or len(context_refs) != len(set(context_refs))
        or not set(context_ids).isdisjoint(expected_ids)
    ):
        return False
    confirmation_id = value["confirmation_episode_id"]
    context_rows = derived[-len(context):] if context else []
    if [row["id"] for row in context_rows] != context_ids or any(
        row.get("candidate_type") != outcome.get("kind")
        or row.get("status") != "accepted"
        or row.get("canonical_record_ref") != outcome.get("canonical_ref")
        or not re.fullmatch(
            {
                "profile_field": r"entity_facts:[A-Za-z0-9_-]{1,120}",
                "relationship_edge": r"entity_edges:[A-Za-z0-9_-]{1,120}",
                "observation": r"observations:[A-Za-z0-9_-]{1,120}",
            }.get(str(outcome.get("kind")), r"(?!)"),
            str(outcome.get("canonical_ref") or ""),
        )
        or row.get("evidence_episode_ids") != [
            confirmation_id
            if claim.get("evidence", {}).get("evidence_class") == "current_reply"
            else claim.get("evidence", {}).get("episode_id")
        ]
        for row, outcome, claim in zip(context_rows, context, expected_context)
    ):
        return False
    prefix = derived[:len(derived) - len(context)] if context else derived
    entity_ref = lambda entity_id: f"entities:{entity_id}"
    source_id = expected_action.get("source_entity_id")
    target_id = expected_action.get("target_entity_id")
    primary_id = value.get("primary_entity_id")
    entity = value.get("entity")
    source_entity = value.get("source_entity")
    base_refs: list[str] = []

    if action == "reject_candidates":
        valid = (
            all(row["status"] == "rejected" and row["canonical_record_ref"] is None for row in candidates)
            and not prefix and not context and entity is None
            and value.get("source_entity_id") is None and value.get("target_entity_id") is None
            and primary_id is None
            and expected_entities == []
            and source_entity is None
        )
    elif action == "map_to_existing_entity":
        base_refs = [entity_ref(target_id)]
        valid = (
            source_id is None and target_id and value.get("source_entity_id") is None
            and value.get("target_entity_id") == target_id and primary_id == target_id
            and all(row["status"] == "accepted" and row["canonical_record_ref"] == base_refs[0] for row in candidates)
            and all(row["candidate_type"] == "new_entity" and row["target_entity_id"] == target_id for row in candidates)
            and not prefix and len(expected_entities) == 1
            and _entity_readback_matches(entity, target_id, expected_entities)
            and source_entity is None
        )
    elif action in {"confirm_new_entity_group", "rename_and_accept_new_entity"}:
        base_refs = [entity_ref(primary_id)]
        retained_status = "edited_accepted" if action == "rename_and_accept_new_entity" else "accepted"
        expected_prefix_ids = expected_ids[1:]
        relationship = expected_action.get("relationship_to_self")
        relationship_rows = []
        if action == "rename_and_accept_new_entity" and relationship is not None:
            if len(prefix) != len(expected_prefix_ids) + 1:
                return False
            relationship_rows = prefix[-1:]
            prefix = prefix[:-1]
            base_refs.append(relationship_rows[0]["canonical_record_ref"])
        valid = (
            value.get("target_entity_id") is None and primary_id
            and (
                isinstance(value.get("source_entity_id"), str)
                and bool(value.get("source_entity_id"))
                if relationship is not None
                else value.get("source_entity_id") is None
            )
            and [row["id"] for row in prefix] == expected_prefix_ids
            and all(row["candidate_type"] == "new_entity" and row["status"] == "superseded" and row["canonical_record_ref"] == base_refs[0] for row in prefix)
            and [row["status"] for row in candidates] == [retained_status] + ["superseded"] * (len(candidates) - 1)
            and all(row["canonical_record_ref"] == base_refs[0] for row in candidates)
            and all(row["candidate_type"] == "new_entity" and row["target_entity_id"] == primary_id for row in candidates)
            and expected_entities == []
            and _entity_readback_matches(entity, primary_id)
            and (action != "rename_and_accept_new_entity" or entity.get("display_name") == expected_action.get("display_name"))
            and (expected_action.get("canonical_name") is None or entity.get("canonical_name") == expected_action.get("canonical_name"))
            and (
                not relationship_rows
                or relationship_rows[0]["candidate_type"] == "relationship_edge"
                and relationship_rows[0]["status"] == "accepted"
                and re.fullmatch(r"entity_edges:[A-Za-z0-9_-]{1,120}", relationship_rows[0]["canonical_record_ref"] or "")
                and relationship_rows[0]["evidence_episode_ids"] == [confirmation_id]
            )
            and source_entity is None
        )
    elif action == "accept_existing_entity_observation_group":
        row_refs = [row["canonical_record_ref"] for row in candidates]
        base_refs = row_refs
        valid = (
            source_id is None and target_id and value.get("source_entity_id") is None
            and value.get("target_entity_id") == target_id and primary_id == target_id
            and all(row["status"] == "accepted" for row in candidates)
            and all(row["candidate_type"] == "observation" and row["target_entity_id"] == target_id for row in candidates)
            and all(isinstance(ref, str) and re.fullmatch(r"observations:[A-Za-z0-9_-]{1,120}", ref) for ref in row_refs)
            and len(row_refs) == len(set(row_refs)) and not prefix
            and len(expected_entities) == 1
            and _entity_readback_matches(entity, target_id, expected_entities)
            and source_entity is None
        )
    elif action == "merge_existing_entities":
        base_refs = [entity_ref(target_id)]
        valid = (
            source_id and target_id and source_id != target_id
            and value.get("source_entity_id") == source_id
            and value.get("target_entity_id") == target_id and primary_id == target_id
            and not candidates and len(prefix) == 1
            and prefix[0]["candidate_type"] == "merge" and prefix[0]["status"] == "accepted"
            and prefix[0]["canonical_record_ref"] == base_refs[0]
            and prefix[0]["evidence_episode_ids"] == [confirmation_id]
            and len(expected_entities) == 2
            and {item.get("id") for item in expected_entities if isinstance(item, Mapping)} == {source_id, target_id}
            and _entity_readback_matches(
                entity, target_id,
                [item for item in expected_entities if isinstance(item, Mapping) and item.get("id") == target_id],
            )
            and _entity_readback_matches(source_entity, source_id, statuses={"merged"})
            and source_entity.get("entity_digest") != next(
                item.get("entity_digest") for item in expected_entities
                if isinstance(item, Mapping) and item.get("id") == source_id
            )
        )
    elif action == "archive_existing_entity":
        base_refs = [entity_ref(source_id)]
        valid = (
            source_id and value.get("source_entity_id") == source_id
            and value.get("target_entity_id") is None and primary_id == source_id
            and not candidates and not prefix and not context
            and _entity_readback_matches(entity, source_id, statuses={"deleted"})
            and isinstance(expected_entities, list) and len(expected_entities) == 1
            and expected_entities[0].get("id") == source_id
            and entity.get("entity_digest") != expected_entities[0].get("entity_digest")
            and source_entity == entity
        )
    else:
        return False
    return bool(valid and canonical_refs == [*base_refs, *context_refs])


def _candidate_readback_row(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {
            "id", "candidate_type", "status", "updated_at", "canonical_record_ref",
            "target_entity_id", "payload_digest", "evidence_digest", "evidence_episode_ids",
        }
        and isinstance(value.get("id"), str) and value["id"]
        and isinstance(value.get("candidate_type"), str) and value["candidate_type"]
        and isinstance(value.get("status"), str) and value["status"]
        and _parse_time(value.get("updated_at")) is not None
        and (value.get("canonical_record_ref") is None or isinstance(value.get("canonical_record_ref"), str))
        and (value.get("target_entity_id") is None or isinstance(value.get("target_entity_id"), str))
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("payload_digest") or ""))
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("evidence_digest") or ""))
        and isinstance(value.get("evidence_episode_ids"), list)
        and all(isinstance(item, str) and item for item in value["evidence_episode_ids"])
        and len(value["evidence_episode_ids"]) == len(set(value["evidence_episode_ids"]))
    )


def _derived_readback_row(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {"id", "candidate_type", "status", "canonical_record_ref", "evidence_episode_ids"}
        and isinstance(value.get("id"), str) and value["id"]
        and isinstance(value.get("candidate_type"), str) and value["candidate_type"]
        and isinstance(value.get("status"), str) and value["status"]
        and (value.get("canonical_record_ref") is None or isinstance(value.get("canonical_record_ref"), str))
        and isinstance(value.get("evidence_episode_ids"), list)
        and all(isinstance(item, str) and item for item in value["evidence_episode_ids"])
        and len(value["evidence_episode_ids"]) == len(set(value["evidence_episode_ids"]))
    )


def _entity_readback_matches(
    value: Any,
    entity_id: Any,
    expected: Any = None,
    statuses: set[str] | None = None,
) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"id", "entity_type", "display_name", "canonical_name", "status", "system_role", "updated_at", "entity_digest"}
        or value.get("id") != entity_id
        or value.get("entity_type") != "person"
        or value.get("status") not in (statuses or {"active"})
        or value.get("system_role") is not None
        or _parse_time(value.get("updated_at")) is None
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("entity_digest") or ""))
    ):
        return False
    if expected in (None, []):
        return True
    return bool(
        isinstance(expected, list)
        and len(expected) == 1
        and isinstance(expected[0], Mapping)
        and expected[0].get("id") == entity_id
        and expected[0].get("entity_digest") == value.get("entity_digest")
        and _parse_time(expected[0].get("updated_at")) == _parse_time(value.get("updated_at"))
    )


def _context_card_matches(value: Any, entity_id: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and set(value) == {
            "entity_id", "aliases", "profile_fact_count", "relationship_edge_count",
            "stable_context_count", "recent_context_count", "evidence_count",
        }
        and value.get("entity_id") == entity_id
        and isinstance(value.get("aliases"), list)
        and all(isinstance(item, str) and item for item in value["aliases"])
        and len(value["aliases"]) == len(set(value["aliases"]))
        and all(
            isinstance(value.get(key), int) and not isinstance(value.get(key), bool) and value[key] >= 0
            for key in (
                "profile_fact_count", "relationship_edge_count",
                "stable_context_count", "recent_context_count", "evidence_count",
            )
        )
    )


def _compact_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    candidates = value.get("candidates") if isinstance(value.get("candidates"), list) else []
    context = value.get("context_outcomes") if isinstance(value.get("context_outcomes"), list) else []
    return {
        "action_id": _compact(value.get("id") or value.get("action_id"), 120),
        "status": _compact(value.get("status"), 40),
        "verification_state": _compact(value.get("verification_state"), 40),
        "resolution_id": _compact(value.get("resolution_id"), 120),
        "action": _compact(value.get("action") or value.get("action_type"), 80),
        "target_entity_id": _compact(value.get("target_entity_id"), 36) or None,
        "primary_entity_id": _compact(value.get("primary_entity_id"), 36) or None,
        "candidate_statuses": [
            {
                "id": _compact(item.get("id"), 120),
                "status": _compact(item.get("status"), 40),
                "canonical_record_ref": _compact(item.get("canonical_record_ref"), 120) or None,
            }
            for item in candidates[:MAX_IDS]
            if isinstance(item, Mapping)
        ],
        "canonical_refs": list(value.get("canonical_refs", []))[:MAX_IDS],
        "verified_context": {
            "count": len(context),
            "categories": sorted({str(item.get("kind")) for item in context if isinstance(item, Mapping)}),
        },
    }


def _read_json(path: Path, max_bytes: int) -> dict[str, Any]:
    try:
        if path.stat().st_size > max_bytes:
            raise ReconciliationError("input_too_large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError("input_invalid") from exc
    if not isinstance(value, dict):
        raise ReconciliationError("input_invalid")
    return value

def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    try:
        _write_enrichment_private_json(path, dict(value))
    except EnrichmentError as exc:
        raise ReconciliationError(exc.code) from exc


def _session_env(name: str, default: str = "") -> str:
    try:
        session_context = importlib.import_module("gateway.session_context")
    except ImportError:
        return os.environ.get(name, default)
    try:
        get_session_env = getattr(session_context, "get_session_env")
        return str(get_session_env(name, default) or "")
    except Exception:
        return default


def _runtime_secret(name: str) -> str:
    try:
        secret_scope = importlib.import_module("agent.secret_scope")
    except ImportError:
        return os.environ.get(name, "").strip()
    try:
        get_secret = getattr(secret_scope, "get_secret")
        return str(get_secret(name, "") or "").strip()
    except Exception:
        return ""


def _request(config: RouterConfig, transport: Transport | None, method: str, path: str, payload: dict[str, Any] | None, *, auth: bool) -> dict[str, Any]:
    if transport:
        result = transport(method, path, payload, config.kinlayer.reconciliation.api_timeout, 2_000_000)
        if not isinstance(result, dict):
            raise ReconciliationError("kinlayer_response_invalid")
        return result
    url = config.kinlayer.base_url.rstrip("/") + path
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if auth:
        token = _runtime_secret("KINLAYER_RECONCILIATION_TOKEN")
        if not token:
            raise ReconciliationError("reconciliation_token_missing")
        headers["Authorization"] = f"Bearer {token}"
    else:
        token = _runtime_secret("KINLAYER_API_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
    try:
        with urlopen(request, timeout=config.kinlayer.reconciliation.api_timeout) as response:
            raw = response.read(2_000_001)
    except HTTPError as exc:
        error_code = ""
        try:
            error_body = exc.read(200_001)
            if len(error_body) <= 200_000:
                parsed_error = json.loads(error_body)
                if isinstance(parsed_error, Mapping):
                    error = parsed_error.get("error")
                    if isinstance(error, Mapping):
                        error_code = _compact(error.get("code"), 80)
        except Exception:
            error_code = ""
        if error_code in {"stale_candidate", "stale_entity", "idempotency_conflict"}:
            raise ReconciliationError(error_code) from exc
        suffix = f":{error_code}" if error_code else ""
        raise ReconciliationError(f"kinlayer_http_{exc.code}{suffix}") from exc
    except (URLError, TimeoutError) as exc:
        raise ReconciliationError("kinlayer_request_failed") from exc
    if len(raw) > 2_000_000:
        raise ReconciliationError("kinlayer_response_too_large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReconciliationError("kinlayer_response_invalid") from exc
    if not isinstance(value, dict):
        raise ReconciliationError("kinlayer_response_invalid")
    return value
