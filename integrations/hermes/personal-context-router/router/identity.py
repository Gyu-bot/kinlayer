"""Bounded, source-backed identity lookup and native-session referents.

Assistant questions are referents, never claim evidence. CLI reads cannot establish
native bindings. All model choices are restricted to supplied candidates/references.
"""
from __future__ import annotations

import json
import hashlib
import re
import secrets
import hmac
from contextvars import ContextVar
from copy import deepcopy
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote, urlencode

from .config import hermes_home

MAX_CANDIDATES = 8
MAX_PAGES = 5
PAGE_SIZE = 100
SESSION_TTL = 3600
PENDING_TTL = 7 * 86400
# Causes that are the user's to answer. Anything else (model unavailable or
# malformed, fabricated selection, lookup failure) is never turned into a question.
ASKABLE_CAUSES = set()  # Only the current agent decides whether a question is needed.
# A deferred identity question is usually appended to an ordinary answer, so the
# native response that carries it can be longer than a bare question.
MAX_NATIVE_QUESTION_CHARS = 4000
_UNKNOWN = {"", "그", "그분", "그 사람", "이 사람", "친구", "동료", "누군가", "상대", "someone", "they", "he", "she", "unknown", "그녀", "그들", "그분들", "이분", "저분", "this person", "that person", "him", "her", "it"}
_SELF = {"self"}  # Internal narrator token, never natural-language third-person '본인'.


class IdentityBlocked(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__(result["reason"])


def _hint_label(hint):
    basis = {"reported": "사람이 말한 기록", "inferred": "추정 기록", "unknown": "근거 유형 불명"}.get(hint.get("claim_basis"), "근거 유형 불명")
    return f'{hint["text"]} ({basis})'


def _result(surface, reason, candidates=(), **extra):
    candidates = list(candidates)
    options = []
    for candidate in candidates:
        relation, traits = candidate["relationship_to_user"], candidate["traits_or_recent_context"]
        label = " / ".join([_hint_label(relation[0]) if relation else "사용자와의 관계 근거 없음",
                            _hint_label(traits[0]) if traits else "구별되는 특징·최근 맥락 근거 없음"])
        options.append(f'{candidate["display_name"]} — {label}')
    if len(options) == 1:
        question = f'말씀하신 “{surface}”은 {options[0]}인 그분을 말하는 건가요?'
    elif options:
        question = f'말씀하신 “{surface}”은 ' + "; ".join(options) + " 중 누구인가요?"
    else:
        question = f'말씀하신 “{surface}”은 어떤 관계인 누구인가요? 처음 이야기하는 새 사람인지도 알려 주세요.'
    return {"ok": True, "status": "clarification_needed", "clarification_needed": True,
            "surface": surface, "reason": reason, "entity_id": None, "candidates": candidates,
            "question": question, "write_authorized": False, **extra}


def _active(row):
    return isinstance(row, dict) and row.get("status") == "active" and row.get("entity_type") == "person" and isinstance(row.get("id"), str) and bool(row["id"])


def _hint(row, bucket, evidence):
    if not isinstance(row, dict) or row.get("status") != "active" or not row.get("id"):
        return None
    text = row.get("claim_text") if bucket == "entity_edges" else row.get("content")
    if not isinstance(text, str) or not text.strip():
        return None
    kind = {"entity_edges": "edge", "entity_facts": "fact", "observations": "observation"}[bucket]
    provenance = [{k: e.get(k) for k in ("episode_id", "actor", "source_type", "source_ref", "source_occurred_at")}
                  for e in evidence if e.get("record_type") == kind and e.get("record_id") == row["id"]][:3]
    return {"text": text.strip()[:180], "record_ref": f'{bucket}:{row["id"]}',
            "claim_basis": row.get("claim_basis", "unknown"), "confidence": row.get("confidence"),
            "provenance": provenance, "occurred_at": row.get("occurred_at"), "source": "context-card"}


def _candidate(card, entity, self_id):
    if not isinstance(card, dict) or card.get("entity", {}).get("id") != entity["id"] or not _active(card["entity"]):
        raise ValueError("context_card_identity_mismatch")
    relation, traits = [], []
    evidence = card.get("provenance_summary", {}).get("evidence", [])
    for row in card.get("relationship_edges", []):
        endpoints = {row.get("from_entity_id"), row.get("to_entity_id")}
        if endpoints == {self_id, entity["id"]} and self_id != entity["id"]:
            hint = _hint(row, "entity_edges", evidence)
            if hint:
                relation.append(hint)
    for bucket in ("profile_facts", "recent_context", "stable_context"):
        for row in card.get(bucket, []):
            field = "entity_id" if bucket == "profile_facts" else "subject_entity_id"
            if row.get(field) != entity["id"]:
                continue
            if bucket == "profile_facts" and row.get("fact_type") not in {"organization", "role", "job", "location_hint"}:
                continue
            hint = _hint(row, "entity_facts" if bucket == "profile_facts" else "observations", evidence)
            if hint:
                traits.append(hint)
    if entity.get("system_role") == "self":
        relation.insert(0, {"text": "사용자 본인", "record_ref": "entities:" + entity["id"],
                            "claim_basis": "reported", "confidence": None, "provenance": [], "source": "system_role=self"})
    return {"entity_id": entity["id"], "display_name": entity["display_name"],
            "is_self": entity.get("system_role") == "self",
            "relationship_to_user": relation[:2], "traits_or_recent_context": traits[:3]}


def _pages(config, request, path, params):
    seen, expected, offset, rows = set(), None, 0, []
    for _ in range(MAX_PAGES):
        data = request(config, "GET", path + "?" + urlencode({**params, "limit": PAGE_SIZE, "offset": offset}))
        total, items = data.get("total"), data.get("items")
        if type(total) is not int or total < 0 or not isinstance(items, list) or (expected is not None and total != expected):
            raise ValueError("incomplete_search")
        expected = total
        if not items and offset < total:
            raise ValueError("incomplete_search")
        for row in items:
            key = row.get("record_ref") if path == "/api/memories" else row.get("id")
            if not isinstance(key, str) or not key or key in seen:
                raise ValueError("repeated_search_page")
            seen.add(key)
            rows.append(row)
        offset += len(items)
        if offset > total:
            raise ValueError("inconsistent_search_total")
        if offset == total:
            return rows
    raise ValueError("candidate_scan_incomplete")


def _name_forms(surface):
    forms = [surface]
    if len(surface) >= 3 and surface[-1] in {"이", "아", "야", "씨", "님"}:
        forms.append(surface[:-1])
    return forms


def preflight(config, surface, human_context="", *, request=None, plugin_llm=None,
              hint_queries=None, established=None, proposal=None, native_question="", owner_verified=False,
              prior_human=None, referent_changed=False):
    """Read-only lookup. Session arguments are INTERNAL: never accepted by CLI."""
    from .post_turn import _kinlayer_request
    request = request or _kinlayer_request
    surface = surface.strip() if isinstance(surface, str) else ""
    if not isinstance(human_context, str) or len(surface) > 120 or surface.casefold() in _UNKNOWN:
        return _result(surface[:120], "unknown_person")
    if not config.kinlayer.enabled:
        return _result(surface, "kinlayer_disabled", ok=False)
    try:
        if hint_queries is None:
            hint_queries = []
        if (not isinstance(hint_queries, list) or len(hint_queries) > 2 or
                any(not isinstance(q, str) or not q.strip() or len(q) > 120 or q not in human_context for q in hint_queries)):
            raise ValueError("ungrounded_hint_query")
        own = request(config, "GET", "/api/entities?entity_type=person&status=active&system_role=self&limit=2")
        selves = own.get("items", [])
        if own.get("total") != 1 or len(selves) != 1 or not _active(selves[0]) or selves[0].get("system_role") != "self":
            return _result(surface, "self_identity_ambiguous")
        self_id = selves[0]["id"]
        protected = config.kinlayer.enrichment.protected_self_entity_id
        if protected and protected != self_id:
            return _result(surface, "self_identity_ambiguous")
        if surface in _SELF:
            # Protected narrator identity is metadata, not a natural-language referent guess.
            return _result(surface, "explicit_self", status="resolved", clarification_needed=False, entity_id=self_id, question=None)
        resolution = request(config, "POST", "/api/entities/resolve", {
            "surface": surface, "entity_type": "person", "source": {"include_self": True}, "limit": 25})
        if (resolution.get("ambiguity") not in {"no_match", "single_strong_match", "multiple_close_matches", "low_confidence_match"}
                or not isinstance(resolution.get("matches"), list)
                or (resolution["ambiguity"] == "no_match" and resolution["matches"])):
            raise ValueError("invalid_resolution")
        ids = {m["entity_id"] for m in resolution["matches"] if m.get("entity_type") == "person" and m.get("entity_id")}
        queries = list(dict.fromkeys([surface, *hint_queries]))
        if re.fullmatch(r"[가-힣]{3,4}", surface):
            queries.append(surface[1:])
        # A vocative/honorific form ('하린이', '하린씨') searches its bare name too;
        # this only discovers candidates and never decides identity by itself.
        queries.extend(n for n in _name_forms(surface)[1:] if n not in queries)
        entities = {}
        for query in queries:
            for entity in _pages(config, request, "/api/entities", {"q": query, "entity_type": "person", "status": "active"}):
                if not _active(entity):
                    raise ValueError("invalid_directory_entity")
                entities[entity["id"]] = entity
        # Search claim content, not ignored backend relation_hint. Results contribute
        # candidate IDs only; context cards supply all display/evidence hints.
        for query in dict.fromkeys(hint_queries):
            for row in _pages(config, request, "/api/memories", {"q": query, "status": "active"}):
                if row.get("status") != "active" or row.get("is_current") is not True or not isinstance(row.get("payload"), dict):
                    raise ValueError("invalid_memory_search")
                payload = row["payload"]
                if row.get("record_type") == "entity_edges":
                    ends = {payload.get("from_entity_id"), payload.get("to_entity_id")}
                    if self_id in ends:
                        ids.update(e for e in ends if e and e != self_id)
                else:
                    key = "entity_id" if row.get("record_type") == "entity_facts" else "subject_entity_id"
                    if payload.get(key):
                        ids.add(payload[key])
        if established:
            ids.add(established["entity_id"])
        if proposal:
            ids.add(proposal["entity_id"])
        if len(ids | entities.keys()) > MAX_CANDIDATES or len(resolution["matches"]) >= 25:
            return _result(surface, "too_many_candidates")
        for eid in ids - entities.keys():
            entity = request(config, "GET", "/api/entities/" + quote(eid, safe=""))
            if entity.get("entity_type") != "person":
                continue
            if not _active(entity) or entity["id"] != eid:
                raise ValueError("invalid_resolved_entity")
            entities[eid] = entity
        candidates = [_candidate(request(config, "GET", "/api/entities/" + quote(eid, safe="") + "/context-card"), e, self_id)
                      for eid, e in sorted(entities.items())]
        return _result(surface, "agent_decision_required", candidates, cause="unresolved",
                       ambiguity=resolution["ambiguity"])
    except Exception:
        return _result(surface, "identity_lookup_failed", ok=False, cause="lookup_failed")


def _scope(config, kwargs):
    session, sender = kwargs.get("session_id"), kwargs.get("sender_id")
    platform = str(kwargs.get("platform") or "").lower()
    if kwargs.get("parent_session_id") or not session or not kwargs.get("turn_id") or (not sender and platform not in {"cli", "terminal"}):
        return None
    return (str(hermes_home().resolve()), config.kinlayer.base_url.rstrip("/"), str(session), str(sender or "local-owner"))


TOOL_NAME = "kinlayer_identity"
_NATIVE_TOOL: ContextVar[tuple | None] = ContextVar("pcr_identity_native_tool", default=None)
_HANDOFF_KEY = secrets.token_bytes(32)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _sign(value):
    return hmac.new(_HANDOFF_KEY, _digest(value).encode(), hashlib.sha256).hexdigest()


def _handoff_payload(config, kwargs, human, results, scope):
    from .post_turn import _canonical_json
    full_human_identity = kwargs.get("_human_message_identity") or hashlib.sha256(_canonical_json({
        "session": str(kwargs.get("session_id") or ""), "turn": str(kwargs.get("turn_id") or ""),
        "human_message": human}).encode()).hexdigest()
    return {"profile": str(hermes_home().resolve()), "backend": config.kinlayer.base_url.rstrip("/"),
            "session": str(kwargs.get("session_id") or ""), "turn": str(kwargs.get("turn_id") or ""),
            "human_hash": _digest(human[:4000]), "full_human_identity": full_human_identity,
            "scope": list(scope or []), "results": results}


def validated_results(config, kwargs, human):
    """Only a native pre/tool/post chain may authorize the background writer.

    The proof is process-local: callers, old journals and restarted workers cannot
    manufacture or replay a decision. Claim evidence is independently current-human.
    """
    results, scope = kwargs.get("_identity_results"), kwargs.get("_identity_scope")
    proof = kwargs.get("_identity_proof")
    if not isinstance(results, dict) or not isinstance(scope, (tuple, list)) or len(scope) != 4 or not isinstance(proof, str):
        return {}
    payload = _handoff_payload(config, kwargs, human, results, scope)
    if list(scope[:3]) != [payload["profile"], payload["backend"], payload["session"]]:
        return {}
    return deepcopy(results) if hmac.compare_digest(proof, _sign(payload)) else {}


def revalidate_candidate(config, result):
    """Check live candidate existence and selected source hints again at writer time."""
    from .post_turn import _kinlayer_request as request
    selected = next((c for c in result.get("candidates", []) if c["entity_id"] == result.get("entity_id")), None)
    if not selected:
        return False
    try:
        own = request(config, "GET", "/api/entities?entity_type=person&status=active&system_role=self&limit=2")
        if own.get("total") != 1 or len(own.get("items", [])) != 1:
            return False
        self_id = own["items"][0]["id"]
        eid = selected["entity_id"]
        entity = request(config, "GET", "/api/entities/" + quote(eid, safe=""))
        if not _active(entity) or entity["id"] != eid:
            return False
        card = request(config, "GET", "/api/entities/" + quote(eid, safe="") + "/context-card")
        return _digest(_candidate(card, entity, self_id)) == _digest(selected)
    except Exception:
        return False


def _native_context(history, human):
    """Identity context only, NEVER claim evidence. No auxiliary semantic window."""
    from .hooks import _synthetic_user_message_reason
    texts = [human]
    if isinstance(history, list):
        for row in history:
            if (not isinstance(row, dict) or row.get("role") not in {"user", "assistant"}
                    or row.get("tool_calls") or row.get("_compressed_summary") or row.get("_todo_snapshot_synthetic")
                    or any(m in str(row.get("display_kind") or "").lower() for m in ("compaction", "handoff", "synthetic"))):
                continue
            text = row.get("content")
            if isinstance(text, str) and text and not _synthetic_user_message_reason(text):
                texts.append(text)
    return tuple(dict.fromkeys(texts))


NOTICE = {"context": "[Kinlayer identity handoff — operational, not human evidence]\n"
    "YOU, the current conversational agent, decide who the user means using your actual conversation context. "
    "For relevant person-context work call kinlayer_identity lookup for the smallest candidate set, then decide "
    "with exact context quotes and candidate evidence_refs. A clear name variant needs no extra confirmation. "
    "Compare unfamiliar names with source-backed hints; when genuinely unresolved ask one natural question yourself. "
    "No auxiliary model or spelling rule decides identity. Missing/failed handoff leaves writes unresolved, "
    "not a demand that the user confirm. Never repeat old facts as new evidence, manually duplicate the writer, "
    "or create/alias/merge people after a failed lookup. A decision applies only to THIS native turn; "
    "prior identity context does not supply new claim evidence. status is a no-backend, no-write setup probe."}


class NativeIdentityState:
    """Ephemeral, turn-bound decisions. No persistent aliases or automatic replay."""
    def __init__(self):
        self.turns = OrderedDict()
        self.lock = threading.RLock()

    @staticmethod
    def _key(config, session, turn):
        return (str(hermes_home().resolve()), config.kinlayer.base_url.rstrip("/"), str(session or ""), str(turn or ""))

    def pre(self, config, llm, kwargs):
        scope, human = _scope(config, kwargs), kwargs.get("user_message")
        if not scope or not isinstance(human, str) or not human.strip() or len(human) > 100_000:
            return None
        key = self._key(config, kwargs.get("session_id"), kwargs.get("turn_id"))
        with self.lock:
            now = time.time()
            self.turns = OrderedDict((k, v) for k, v in self.turns.items() if now - v["created"] < SESSION_TTL)
            frame = self.turns.get(key)
            if frame:
                if frame["scope"] != scope or frame["human"] != human:
                    frame["invalid"] = True
                    frame["results"].clear()
                    return None
                return deepcopy(NOTICE) if not frame["invalid"] else None
            self.turns[key] = {"scope": scope, "human": human, "context": _native_context(kwargs.get("conversation_history"), human),
                               "created": now, "invalid": False, "closed": False, "lookups": {}, "results": {}, "conflicts": set()}
            while len(self.turns) > 128:
                self.turns.popitem(last=False)
            return deepcopy(NOTICE)

    def middleware(self, config, **kwargs):
        if kwargs.get("tool_name") != TOOL_NAME:
            return kwargs["next_call"](kwargs["args"])
        key = self._key(config, kwargs.get("session_id"), kwargs.get("turn_id"))
        token = _NATIVE_TOOL.set(key if kwargs.get("tool_call_id") and key[2] and key[3] else None)
        try:
            return kwargs["next_call"](kwargs["args"])
        finally:
            _NATIVE_TOOL.reset(token)

    def tool(self, config, params, *, session_id=None, **kwargs):
        key = _NATIVE_TOOL.get()
        if not key or key != self._key(config, session_id, key[3]):
            return {"ok": False, "reason": "native_turn_binding_required"}
        if not isinstance(params, dict):
            return {"ok": False, "reason": "invalid_arguments"}
        action = params.get("action")
        allowed = {"action", "surface", "hint_queries"} if action == "lookup" else {"action"} if action == "status" else {
            "action", "lookup_token", "candidate_id", "evidence_refs", "context_quotes", "excluded_candidate_ids", "reason", "mention_surfaces"}
        if set(params) - allowed or action not in {"lookup", "decide", "unresolved", "status"}:
            return {"ok": False, "reason": "invalid_arguments"}
        with self.lock:
            frame = self.turns.get(key)
            if action == "status":
                return {"ok": True, "authority": "current_agent", "version": "0.15.0", "native_turn_bound": True,
                        "decision_frame_admitted": bool(frame and not frame["invalid"] and not frame["closed"] and time.time()-frame["created"]<SESSION_TTL),
                        "backend_queried": False, "writes": 0}
            if not frame or frame["invalid"] or frame["closed"] or time.time() - frame["created"] >= SESSION_TTL:
                return {"ok": False, "reason": "native_turn_unavailable"}
            if action == "lookup":
                surface, hints = params.get("surface"), params.get("hint_queries", [])
                if (not isinstance(surface, str) or not surface.strip() or len(surface) > 120
                        or not any(surface in t for t in frame["context"]) or len(frame["lookups"]) >= 8):
                    return {"ok": False, "reason": "ungrounded_or_excess_lookup"}
                context = "\n".join(frame["context"])
                result = preflight(config, surface, context, hint_queries=hints)
                token = secrets.token_urlsafe(24)
                frame["lookups"][token] = {"surface": surface, "hints": deepcopy(hints), "result": deepcopy(result)}
                # Even explicit self lookup is read-only. Only decide authorizes person writes.
                return {**result, "lookup_token": token, "write_authorized": False, "question": None}
            lookup = frame["lookups"].get(params.get("lookup_token")) if isinstance(params.get("lookup_token"), str) else None
            if not lookup:
                return {"ok": False, "reason": "lookup_token_invalid"}
            surface = lookup["surface"]
            def reject(reason):
                frame["results"][surface] = _result(surface, "same_turn_identity_conflict" if surface in frame["conflicts"] else reason, cause="unresolved", question=None)
                return {"ok": False, "reason": reason, "write_authorized": False}
            if action == "unresolved":
                reject("agent_unresolved")
                return {"ok": True, "status": "unresolved", "write_authorized": False}
            result = lookup["result"]
            candidates = result.get("candidates", [])
            selected = next((c for c in candidates if c["entity_id"] == params.get("candidate_id")), None)
            refs, quotes, excluded = params.get("evidence_refs"), params.get("context_quotes"), params.get("excluded_candidate_ids")
            mentions = params.get("mention_surfaces", [surface])
            if (not result.get("ok") or not selected or not isinstance(refs, list) or not refs
                    or not isinstance(mentions, list) or not 1 <= len(mentions) <= 8 or surface not in mentions
                    or any(not isinstance(m, str) or not m.strip() or len(m)>120 or not any(m in t for t in frame["context"]) for m in mentions)
                    or any(not isinstance(r, str) for r in refs) or not isinstance(quotes, list) or not 1 <= len(quotes) <= 6
                    or any(not isinstance(q, str) or not q.strip() or len(q) > 4000 or not any(q in t for t in frame["context"]) for q in quotes)
                    or not isinstance(excluded, list) or any(not isinstance(e, str) for e in excluded)
                    or set(excluded) != {c["entity_id"] for c in candidates if c != selected}
                    or not isinstance(params.get("reason"), str) or not params["reason"].strip() or len(params["reason"]) > 2000):
                return reject("decision_evidence_invalid")
            hints = selected["relationship_to_user"] + selected["traits_or_recent_context"]
            valid_refs = {"entities:" + selected["entity_id"], *(h["record_ref"] for h in hints)}
            if not set(refs) <= valid_refs:
                return reject("decision_refs_invalid")
            # Recheck the entire supplied candidate/evidence snapshot, not a name equality rule.
            fresh = preflight(config, surface, "\n".join(frame["context"]), hint_queries=lookup["hints"])
            if not fresh.get("ok") or _digest(fresh.get("candidates")) != _digest(candidates):
                return reject("candidate_snapshot_stale")
            for mention in mentions:
                previous = frame["results"].get(mention)
                if mention in frame["conflicts"] or (previous and previous.get("entity_id") not in {None, selected["entity_id"]}):
                    frame["conflicts"].add(mention)
                    frame["results"][mention] = _result(mention,"same_turn_identity_conflict",cause="unresolved",question=None)
                    return reject("same_turn_identity_conflict")
            for mention in mentions:
                frame["results"][mention] = {**result, "surface": mention, "status": "resolved", "clarification_needed": False,
                    "reason": "current_agent", "entity_id": selected["entity_id"], "evidence_refs": list(refs), "question": None}
            return {"ok": True, "status": "resolved", "entity_id": selected["entity_id"], "write_authorized": True}

    def post(self, config, llm, kwargs):
        key = self._key(config, kwargs.get("session_id"), kwargs.get("turn_id"))
        with self.lock:
            frame = self.turns.get(key)
            if not frame or frame["invalid"] or frame["human"] != kwargs.get("user_message") or time.time() - frame["created"] >= SESSION_TTL:
                return {}
            frame["closed"] = True
            # Repeated post hooks receive the same immutable proof; journal/queue owns once-only writes.
            results = deepcopy(frame["results"])
            return {"_identity_results": results, "_identity_scope": frame["scope"], "_identity_started_at": frame["created"],
                    "_identity_proof": _sign(_handoff_payload(config, kwargs, frame["human"], results, frame["scope"]))}

    def transform(self, config, kwargs):
        return None  # The plugin NEVER appends an identity question to an agent response.


def pending_context(config, session_id, sender=None):
    return None  # Preserve old journals; do not impose/replay their confirmation ritual.


def setup_commands(commands):
    parser = commands.add_parser("identity-resolve", help="Read-only bounded candidates; current agent owns semantic identity")
    parser.add_argument("--surface", required=True)
    parser.add_argument("--human-context", default="")
    parser.add_argument("--hint-query", action="append", default=[])


def handle_cli(args, *, config):
    result = preflight(config, args.surface, args.human_context, hint_queries=args.hint_query)
    result.update(mode="read_only_candidates", write_authorized=False, question=None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1
