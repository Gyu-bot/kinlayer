from __future__ import annotations

import hashlib
import fcntl
import math
import sqlite3
import threading
from contextlib import contextmanager
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .config import RouterConfig, gyurin_knowledge_root, hermes_home, is_under_gyurin_knowledge_root
from .cultural import (
    canonical_resolution,
    cultural_item_key,
    cultural_item_label,
    normalized_medium,
    supported_cultural_medium,
)
from .dimensions import is_low_signal
from .logging import KEY_VALUE_SECRET_RE, SECRET_LIKE_VALUE_RE, redact
from .markdown_writer import MarkdownWriteRequest, append_domain_entry
from .manifest import ManifestBundle
from .policy import PolicyDecision


_TS_FMT = "%Y-%m-%dT%H:%M:%S%z"


def _candidate_path(bundle: ManifestBundle) -> tuple[Path, bool]:
    default = gyurin_knowledge_root() / "evidence" / "candidates.jsonl"
    policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
    value = None
    post_turn = policy.get("post_turn") if isinstance(policy.get("post_turn"), dict) else {}
    post_default = post_turn.get("default") if isinstance(post_turn.get("default"), dict) else {}
    if isinstance(post_default, dict):
        value = post_default.get("candidate_path")
    if not value:
        old_default = policy.get("default") if isinstance(policy.get("default"), dict) else {}
        value = old_default.get("candidate_path") if isinstance(old_default, dict) else None
    if not value:
        return default, False
    path = Path(str(value)).expanduser()
    candidate = path if path.is_absolute() else hermes_home() / path
    if not is_under_gyurin_knowledge_root(candidate):
        return default, True
    return candidate, False


def _domain_from_target(
    decision: PolicyDecision,
    bundle: ManifestBundle,
) -> tuple[str, dict[str, Any]] | None:
    domains = bundle.domain_map.get("domains", {}) if isinstance(bundle.domain_map, dict) else {}
    if not isinstance(domains, dict):
        return None

    target = str(decision.post_turn_target or "").strip()
    target_path = Path(target).expanduser() if target else None
    target_names = set()
    if target:
        target_names.update({target, target.replace("-", "_"), target.replace("_", "-")})
        if target_path is not None:
            target_names.update({target_path.name, target_path.stem})

    if target and target in domains and isinstance(domains[target], dict):
        return target, domains[target]

    for name, domain in domains.items():
        if not isinstance(domain, dict):
            continue
        names = {str(name), str(name).replace("-", "_"), str(name).replace("_", "-")}
        for key in ("curated_file", "file", "evidence_ledger"):
            value = str(domain.get(key) or "")
            if not value:
                continue
            path = Path(value).expanduser()
            names.update({path.name, path.stem})
        if target_names & names:
            return str(name), domain

    for active in decision.active_domains:
        name = str(active.get("name") or "")
        if name and name in domains and isinstance(domains[name], dict):
            return name, domains[name]
        if name:
            return name, active
    return None


def _domain_path_from_target(decision: PolicyDecision, bundle: ManifestBundle) -> Path | None:
    found = _domain_from_target(decision, bundle)
    if not found:
        return None
    _, domain = found
    return _resolve_knowledge_path(str(domain.get("curated_file") or domain.get("file") or ""))


def _resolve_knowledge_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = gyurin_knowledge_root() / path
    return path if is_under_gyurin_knowledge_root(path) else None


def _allowlist(bundle: ManifestBundle) -> list[Path]:
    domains = bundle.domain_map.get("domains", {}) if isinstance(bundle.domain_map, dict) else {}
    result: list[Path] = []
    if isinstance(domains, dict):
        for domain in domains.values():
            if not isinstance(domain, dict):
                continue
            for key in ("curated_file", "file"):
                if domain.get(key):
                    path = _resolve_knowledge_path(str(domain[key]))
                    if path:
                        result.append(path)
    return result


def _post_turn_defaults(bundle: ManifestBundle) -> dict[str, Any]:
    policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
    post_turn = policy.get("post_turn") if isinstance(policy.get("post_turn"), dict) else {}
    default = post_turn.get("default") if isinstance(post_turn.get("default"), dict) else {}
    return default if isinstance(default, dict) else {}


def _write_candidate_log_enabled(bundle: ManifestBundle) -> bool:
    default = _post_turn_defaults(bundle)
    if "write_candidate_log" in default:
        return bool(default.get("write_candidate_log"))
    return True


def _write_evidence_enabled(bundle: ManifestBundle) -> bool:
    default = _post_turn_defaults(bundle)
    if "write_evidence_ledger" in default:
        return bool(default.get("write_evidence_ledger"))
    evidence = bundle.storage_policy.get("evidence") if isinstance(bundle.storage_policy, dict) else None
    return bool(evidence) or True


def _storage_allows_auto_write(bundle: ManifestBundle, domain_name: str = "") -> bool:
    policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
    post_default = _post_turn_defaults(bundle)
    post_auto = post_default.get("auto_write_domain_file")
    if post_auto is False:
        return False

    default = policy.get("default") if isinstance(policy.get("default"), dict) else {}
    if isinstance(default, dict) and default.get("global_auto_write_gate") is False:
        return False

    domains = policy.get("domains") if isinstance(policy.get("domains"), dict) else {}
    domain_policy = domains.get(domain_name) if domain_name and isinstance(domains, dict) else None
    if isinstance(domain_policy, dict) and "allow_auto_write" in domain_policy:
        return bool(domain_policy.get("allow_auto_write"))

    if post_auto is True:
        return True

    default_auto_write = (
        bool(default.get("auto_write"))
        if isinstance(default, dict) and "auto_write" in default
        else None
    )
    if default_auto_write is not None:
        return default_auto_write

    targets = policy.get("targets") if isinstance(policy.get("targets"), dict) else {}
    domain_file = targets.get("domain_file_candidate") if isinstance(targets, dict) else {}
    if isinstance(domain_file, dict) and "allow_auto_write" in domain_file:
        return bool(domain_file.get("allow_auto_write"))
    return False


def _auto_write_section(
    bundle: ManifestBundle,
    domain_name: str,
    decision: PolicyDecision | None = None,
) -> str | None:
    if domain_name == "cultural_taste":
        item = decision.cultural_item if decision is not None else {}
        medium = normalized_medium(item.get("medium"))
        domains = bundle.domain_map.get("domains") if isinstance(bundle.domain_map, dict) else {}
        cultural_domain = domains.get("cultural_taste") if isinstance(domains, dict) else {}
        mapping = (
            cultural_domain.get("medium_to_section")
            if isinstance(cultural_domain, dict)
            and isinstance(cultural_domain.get("medium_to_section"), dict)
            else {}
        )
        section = str(mapping.get(medium) or "").strip()
        return section or None

    policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
    domains = policy.get("domains") if isinstance(policy.get("domains"), dict) else {}
    domain_policy = domains.get(domain_name) if domain_name and isinstance(domains, dict) else None
    allowed = domain_policy.get("allowed_sections") if isinstance(domain_policy, dict) else None
    if isinstance(allowed, list):
        sections = [str(section).strip() for section in allowed if str(section).strip()]
        sections = [section for section in sections if section.lower() != "evidence log"]
        if sections:
            return sections[0]
    post_default = _post_turn_defaults(bundle)
    section = str(post_default.get("curated_observation_section") or "Recent Observations").strip()
    if section.lower() == "schema_specific_only":
        if domain_name == "relationships":
            return "Current Known Context"
        return None
    return section or "Recent Observations"


_PERSON_BLOCKLIST = {
    "", "user", "사용자", "self", "나", "저", "우리",
    "romanticinterest", "romantic_interest", "dating_app_dependency", "dating apps",
    "emotionalsupportnetwork", "emotional support network", "support network",
    "AIpersonause", "ai persona use", "assistant", "ai", "bot", "model",
    "강아지", "pet", "dog", "event", "meetup", "모임", "사람", "상대",
}


def _norm_subject(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).strip()
    for suffix in ("선생님께", "선생님", "님께", "씨랑", "님이랑", "이랑", "랑", "씨", "님"):
        if compact.endswith(suffix):
            compact = compact[: -len(suffix)]
            break
    return compact.lower()


def _strip_leading_speaker_label(message: str) -> str:
    text = str(message or "").lstrip()
    if not text.startswith("["):
        return text
    end = text.find("]")
    if 0 < end <= 40:
        return text[end + 1 :].lstrip()
    return text


def _subject_is_self_speaker_only(label: str, user_message: str) -> bool:
    text = str(user_message or "").lstrip()
    end = text.find("]") if text.startswith("[") else -1
    if not 0 < end <= 40 or _norm_subject(text[1:end]) != _norm_subject(label):
        return False
    # A native sender label alone is not a named person in the human statement.
    return _norm_subject(label) not in _norm_subject(_strip_leading_speaker_label(text))


def _usable_person_subjects(subjects: list[str], user_message: str = "") -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    blocked = {_norm_subject(item) for item in _PERSON_BLOCKLIST}
    for raw in subjects:
        label = str(raw or "").strip()
        norm = _norm_subject(label)
        if not label or not norm or len(norm) < 2 or norm in blocked:
            continue
        if _subject_is_self_speaker_only(label, user_message):
            continue
        if any(token in norm for token in ("dependency", "supportnetwork", "persona", "meetup", "교류회")):
            continue
        if norm in seen:
            continue
        seen.add(norm)
        result.append(label)
    return result


def _relationship_person_specific(decision: PolicyDecision, domain_name: str, user_message: str = "") -> bool:
    if decision.cultural_item:
        return False
    if domain_name != "relationships":
        return False
    if not decision.kinlayer_memories and not _usable_person_subjects(decision.subjects, user_message):
        return False
    for policy in decision.active_policies:
        split = policy.get("split") if isinstance(policy.get("split"), dict) else {}
        if isinstance(split, dict) and "real_person_specific" in split:
            return True
    return True


def _kinlayer_request(config: RouterConfig, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = str(config.kinlayer.base_url or "").rstrip("/")
    if not base_url:
        raise RuntimeError("kinlayer_base_url_missing")
    data = None if payload is None else json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    token = os.environ.get("KINLAYER_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=float(config.kinlayer.timeout or 5.0)) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


# Save-first v2 is intentionally separate from retained curation/reconciliation APIs.
_MEMORY_CAPABILITY_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
_MEMORY_LOCK = threading.RLock()
_MEMORY_RECORD_PATHS = {"entity_facts": "entity-facts", "entity_edges": "edges", "observations": "observations"}
_MEMORY_SUBTYPES = {"entity_facts": "fact_type", "entity_edges": "relation_type", "observations": "observation_type"}
_MEMORY_ROLES = {"subject", "related", "mentioned", "speaker", "target", "about", "experiencer"}
_MEMORY_TEXT_FACTS = {"legal_name", "phone", "email", "address", "organization", "role", "job", "external_handle", "location_hint"}


class MemorySkip(Exception):
    """A bounded diagnostic code, never source text or an HTTP response body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _memory_contract_supported(config: RouterConfig) -> bool:
    key = (config.kinlayer.base_url.rstrip("/"), hashlib.sha256(os.environ.get("KINLAYER_API_TOKEN", "").encode()).hexdigest())
    with _MEMORY_LOCK:
        cached = _MEMORY_CAPABILITY_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 30:
            return cached[1]
        try:
            result = _kinlayer_request(config, "GET", "/api/system/config")
            gate = result.get("memory_write", {})
            supported = (isinstance(gate, dict) and gate.get("endpoint") == "/api/memories"
                         and gate.get("contract_version") == "2" and gate.get("review_required") is False)
        except Exception:
            supported = False
        if len(_MEMORY_CAPABILITY_CACHE) >= 16:
            _MEMORY_CAPABILITY_CACHE.clear()
        _MEMORY_CAPABILITY_CACHE[key] = (time.monotonic(), supported)
        return supported


def _registry_values(items: Any, key: str = "value") -> set[str]:
    if not isinstance(items, list):
        return set()
    return {item[key] for item in items if isinstance(item, dict) and isinstance(item.get(key), str)
            and item.get("is_active", item.get("active", True)) is not False}


def _ontology_allowed(ontology: dict[str, Any]) -> dict[str, set[str]]:
    edge_types = ontology.get("edge_types")
    writable_edges = [item for item in edge_types if isinstance(item, dict)
                      and item.get("write_supported") is True
                      and item.get("support_level") == "supported"] if isinstance(edge_types, list) else []
    if not isinstance(ontology.get("version"), str) or not ontology["version"].strip():
        writable_edges = []
    profile = ontology.get("relationship_profile")
    profile = profile if isinstance(profile, dict) and isinstance(profile.get("version"), str) and profile["version"].strip() else {}
    axes = profile.get("axes", {})
    axes = axes if isinstance(axes, dict) else {}
    return {
        "entity_type": _registry_values(ontology.get("entity_types")),
        "fact_type": _registry_values(ontology.get("fact_types")),
        "observation_type": _registry_values(ontology.get("observation_types"), "observation_type"),
        "relation_type": _registry_values(writable_edges, "relation_type"),
        "readable_relation_type": _registry_values(edge_types, "relation_type"),
        "claim_basis": _registry_values(ontology.get("claim_bases")),
        "role": _registry_values(ontology.get("participant_roles")),
        "relationship_profile_version": {profile["version"]} if profile else set(),
        "relationship_axis": set(axes),
        **{"relationship_value:" + axis: _registry_values(row.get("values"))
           for axis, row in axes.items() if isinstance(axis, str) and isinstance(row, dict)},
    }


def _classification_relationship_ontology(config: RouterConfig) -> dict[str, Any]:
    """Fetch fresh server meanings before classification; never guess offline enums."""
    if config.dry_run or not config.kinlayer.enabled:
        return {"available": False}
    try:
        ontology = _kinlayer_request(config, "GET", "/api/ontology")
        version, rows = ontology.get("version"), ontology.get("edge_types")
        if (not isinstance(version, str) or not version.strip() or not isinstance(rows, list)
                or any(not isinstance(row, dict) or not isinstance(row.get("relation_type"), str)
                       or type(row.get("write_supported")) is not bool for row in rows)):
            return {"available": False}
        return {"available": True, "version": version,
                "relationship_profile": ontology.get("relationship_profile"),
                "edge_types": [{key: value for key, value in row.items()
                                if key not in {"created_at", "updated_at"}} for row in rows]}
    except Exception:
        return {"available": False}


def _require_allowed(allowed: dict[str, set[str]], category: str, value: Any) -> None:
    if not isinstance(value, str) or value not in allowed.get(category, set()):
        raise MemorySkip(f"ontology_unsupported:{category}")


def _aware_timestamp(value: Any) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            # ISO date-only strings and naive values are never source timestamps.
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


def _source_occurred_at(kwargs: dict[str, Any], user_message: str = "") -> str | None:
    for key in ("occurred_at", "message_timestamp", "created_at", "ts", "timestamp"):
        parsed = _aware_timestamp(kwargs.get(key))
        if parsed:
            return parsed
    match = re.match(r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (KST|JST|UTC|GMT|[+-]\d{2}:?\d{2})\]", user_message.lstrip())
    if not match:
        return None
    zone = {"KST": "+09:00", "JST": "+09:00", "UTC": "+00:00", "GMT": "+00:00"}.get(match[2], match[2])
    return _aware_timestamp(match[1].replace(" ", "T") + zone)


def _memory_source(claim: dict[str, Any], user_message: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    quote = claim.get("source_quote")
    body = _strip_leading_speaker_label(user_message)
    if not isinstance(quote, str) or not quote.strip() or quote not in body:
        raise MemorySkip("source_quote_not_current_human")
    excerpt = quote
    # Reuse secret patterns without redact()'s whitespace folding/ellipsis: evidence
    # remains an exact current-user span except for explicitly redacted secrets.
    excerpt = KEY_VALUE_SECRET_RE.sub(r"\1=[REDACTED]", excerpt)
    excerpt = SECRET_LIKE_VALUE_RE.sub("[REDACTED]", excerpt)[:4000]
    if not excerpt.strip():
        raise MemorySkip("source_missing")
    source = {"source_type": "agent_conversation", "actor": "user", "excerpt": excerpt,
              "source_ref": "hermes:" + str(kwargs.get("session_id") or "")[:200] + ":" + str(kwargs.get("turn_id") or "")[:200]}
    timestamp = kwargs["_memory_source_time"] if "_memory_source_time" in kwargs else _source_occurred_at(kwargs, user_message)
    if timestamp:
        source["occurred_at"] = timestamp
    return source


def _memory_fact_value(claim: dict[str, Any]) -> dict[str, Any]:
    kind, content, value = claim.get("fact_type"), claim.get("content"), claim.get("value")
    if not isinstance(value, dict):
        raise MemorySkip("invalid_fact_value")
    if kind in _MEMORY_TEXT_FACTS:
        if set(value) != {"text"} or not isinstance(value["text"], str) or value["text"] != content:
            raise MemorySkip("invalid_fact_value")
        text = value["text"].strip()
        if kind == "email" and text.count("@") == 1:
            local, domain = text.split("@", 1)
            text = local + "@" + domain.casefold()
        return {"text": text}
    if kind not in {"birthday", "birth_date"} or set(value) - {"year", "month", "day", "precision"}:
        raise MemorySkip("invalid_fact_type")
    year, month, day = (value.get(key) for key in ("year", "month", "day"))
    for item, lower, upper in ((year, 1, 9999), (month, 1, 12), (day, 1, 31)):
        if item is not None and (type(item) is not int or not lower <= item <= upper):
            raise MemorySkip("invalid_fact_value")
    precision = value.get("precision")
    if precision == "year" and year is not None and month is None and day is None:
        rendered = f"{year:04d}"
    elif precision == "month" and month is not None and day is None and (year is not None or kind == "birthday"):
        rendered = f"{year:04d}-{month:02d}" if year else f"--{month:02d}"
    elif precision == "day" and month is not None and day is not None and (year is not None or kind == "birthday"):
        try:
            date(year or 2000, month, day)
        except ValueError as exc:
            raise MemorySkip("invalid_fact_value") from exc
        rendered = f"{year:04d}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"
    else:
        raise MemorySkip("invalid_fact_value")
    if content != rendered:
        raise MemorySkip("invalid_fact_value")
    return {key: value[key] for key in ("year", "month", "day", "precision") if value.get(key) is not None}


def _validate_memory_claim(claim: dict[str, Any], allowed: dict[str, set[str]]) -> None:
    action, kind = claim.get("action"), claim.get("record_type")
    if action not in {"create", "correct", "retract", "reattribute"} or kind not in _MEMORY_RECORD_PATHS:
        raise MemorySkip("invalid_claim_shape")
    assessment = kind == "observations" and claim.get("observation_type") == "relationship_assessment"
    if action != "create" and not claim.get("target_hint") and not assessment:
        raise MemorySkip("correction_target_ambiguous")
    hint = claim.get("target_hint")
    if isinstance(hint, dict) and "record_type" in hint:
        if hint["record_type"] not in _MEMORY_RECORD_PATHS or (action in {"retract", "reattribute"} and hint["record_type"] != kind):
            raise MemorySkip("invalid_correction_targets")
    if claim.get("claim_basis") not in {"reported", "inferred", "unknown"}:
        raise MemorySkip("invalid_claim_basis")
    _require_allowed(allowed, "claim_basis", claim["claim_basis"])
    confidence = claim.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise MemorySkip("invalid_confidence")
    subtype = _MEMORY_SUBTYPES[kind]
    if action != "retract" or claim.get(subtype):
        category = "readable_relation_type" if kind == "entity_edges" and action in {"correct", "retract"} else subtype
        _require_allowed(allowed, category, claim.get(subtype))
    if assessment:
        if claim.get("claim_basis") != "reported" or claim.get("perspective_subject") != "self":
            raise MemorySkip("invalid_relationship_perspective_or_basis")
        _require_allowed(allowed, "relationship_axis", claim.get("relationship_axis"))
        if action != "retract":
            _require_allowed(allowed, "relationship_value:" + claim["relationship_axis"], claim.get("relationship_value"))
        elif claim.get("relationship_value") is not None:
            raise MemorySkip("invalid_relationship_assessment")
        if claim.get("related") or claim.get("valid_to") is not None:
            raise MemorySkip("invalid_relationship_assessment")
        for key in ("valid_from", "occurred_at"):
            known = _aware_timestamp(claim.get(key))
            if known and datetime.fromisoformat(known) > datetime.now(UTC):
                raise MemorySkip("invalid_relationship_assessment")
    elif any(claim.get(key) is not None for key in ("perspective_subject", "relationship_axis", "relationship_value")):
        raise MemorySkip("invalid_relationship_assessment")
    if action == "retract":
        return
    text = claim.get("claim_text" if kind == "entity_edges" else "content")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise MemorySkip("invalid_content")
    if kind == "entity_facts":
        _memory_fact_value(claim)
    if kind == "entity_edges" and "properties" in claim and not isinstance(claim["properties"], dict):
        raise MemorySkip("invalid_properties")
    if kind == "entity_edges" and "directed" in claim and claim["directed"] is not None and not isinstance(claim["directed"], bool):
        raise MemorySkip("invalid_directed")
    for key in ("valid_from", "valid_to", *( ("occurred_at",) if kind == "observations" else ())):
        if claim.get(key) is not None and not _aware_timestamp(claim[key]):
            raise MemorySkip("invalid_timestamp")
    if claim.get("valid_from") and claim.get("valid_to") and datetime.fromisoformat(_aware_timestamp(claim["valid_to"])) < datetime.fromisoformat(_aware_timestamp(claim["valid_from"])):
        raise MemorySkip("invalid_validity")
    related = claim.get("related", [])
    if not isinstance(related, list) or len(related) > 20:
        raise MemorySkip("invalid_related")
    for link in related:
        if not isinstance(link, dict) or link.get("role") not in _MEMORY_ROLES or not isinstance(link.get("subject"), str):
            raise MemorySkip("invalid_related")
        _require_allowed(allowed, "role", link["role"])
        confidence = link.get("confidence")
        if confidence is not None and (type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise MemorySkip("invalid_related_confidence")


class _IdentityResolutions(dict):
    def __init__(self, config, kwargs, plugin_llm, human):
        super().__init__()
        from .identity import validated_results
        self.results = validated_results(config, kwargs, human)
        self.plugin_llm = plugin_llm
        self.db = None


def _memory_identity_result(config, subject, user_message, allowed, resolved):
    from .identity import IdentityBlocked, preflight
    name = subject.strip() if isinstance(subject, str) else ""
    _require_allowed(allowed, "entity_type", "person")
    if name and name != "self" and _norm_subject(name) not in _norm_subject(_strip_leading_speaker_label(user_message)):
        raise MemorySkip("subject_not_current_user_named_person")
    result = resolved.results.get(name)
    if result is None:
        result = preflight(config, name, user_message, request=_kinlayer_request, hint_queries=[])
        resolved.results[name] = result
    if result["clarification_needed"]:
        raise IdentityBlocked(result)
    if result.get("reason") == "current_agent":
        from .identity import revalidate_candidate, _result
        if not revalidate_candidate(config, result):
            raise IdentityBlocked(_result(name, "candidate_snapshot_stale", cause="unresolved", question=None))
    if name != "self" and not _usable_person_subjects([name], user_message):
        raise MemorySkip("subject_not_current_user_named_person")
    return result


def _preflight_memory_people(config, claim, user_message, allowed, resolved):
    # Validate ALL participants before even a legitimate new person can be created.
    names = [claim[key] for key in ("subject", "from_subject", "to_subject", "new_subject", "perspective_subject") if claim.get(key)]
    names.extend(link["subject"] for link in claim.get("related", []))
    for name in dict.fromkeys(names):
        if name in resolved:
            continue
        result = _memory_identity_result(config, name, user_message, allowed, resolved)
        if result["status"] == "resolved":
            resolved[name] = result["entity_id"]


def _memory_resolve(config: RouterConfig, subject: Any, user_message: str, allowed: dict[str, set[str]], resolved: dict[str, str], *, create: bool) -> str:
    from .identity import IdentityBlocked
    name = subject.strip() if isinstance(subject, str) else ""
    if name in resolved:
        return resolved[name]
    result = _memory_identity_result(config, subject, user_message, allowed, resolved)
    entity_id = result.get("entity_id")
    if result["status"] == "new_person":
        if not create:
            raise IdentityBlocked({**result, "clarification_needed": True, "reason": "new_person_not_correction_target"})
        # Persist intent BEFORE the non-idempotent entity POST. Any failed/unknown
        # creation (including a crash) blocks a second POST across claims/turns.
        # Read-only discovery may recover an existing person; no automatic retry.
        creation_key = _canonical_json([str(hermes_home().resolve()), config.kinlayer.base_url.rstrip("/"), name])
        if resolved.db is None or resolved.db.execute("SELECT 1 FROM entity_creation_attempts WHERE identity_key=?", (creation_key,)).fetchone():
            raise IdentityBlocked({**result, "status": "clarification_needed", "clarification_needed": True,
                                   "reason": "entity_create_outcome_unknown", "question": f"{name} 등록 시도 이력이 있어 중복 등록하지 않고 확인이 필요합니다."})
        resolved.db.execute("INSERT INTO entity_creation_attempts VALUES (?)", (creation_key,))
        resolved.db.commit()
        try:
            entity = _kinlayer_request(config, "POST", "/api/entities", {
                "entity_type": "person", "display_name": name, "created_by": "ai_agent"})
            entity_id = entity.get("id")
            if not isinstance(entity_id, str) or not entity_id:
                raise MemorySkip("entity_id_missing")
            exact = _kinlayer_request(config, "GET", "/api/entities/" + urllib.parse.quote(entity_id, safe=""))
            if (exact.get("id") != entity_id or exact.get("status") != "active"
                    or exact.get("entity_type") != "person" or exact.get("display_name") != name):
                raise MemorySkip("entity_create_readback_mismatch")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            raise IdentityBlocked({**result, "status": "clarification_needed", "clarification_needed": True,
                                   "reason": "entity_create_outcome_unknown", "question":
                                   f"{name} 등록 응답을 확인하지 못했습니다. 중복 등록하지 않고 기존 인물 확인을 먼저 해야 합니다."})
    if not isinstance(entity_id, str) or not entity_id:
        raise MemorySkip("entity_id_missing")
    resolved[name] = entity_id
    return entity_id


def _record_path(record_ref: str) -> str:
    kind, sep, identity = str(record_ref).partition(":")
    if not sep or kind not in _MEMORY_RECORD_PATHS or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity):
        raise MemorySkip("invalid_record_ref")
    return f"/api/{_MEMORY_RECORD_PATHS[kind]}/{identity}"


def _memory_targets(kind: str, row: dict[str, Any]) -> tuple[str, ...]:
    keys = ("from_entity_id", "to_entity_id") if kind == "entity_edges" else ("entity_id" if kind == "entity_facts" else "subject_entity_id",)
    return tuple(row.get(key, "") for key in keys)


def _select_memory_target(config: RouterConfig, claim: dict[str, Any], subject_id: str, user_message: str, plugin_llm: Any) -> tuple[str, dict[str, Any]]:
    hint = claim.get("target_hint")
    kind = hint.get("record_type", claim["record_type"]) if isinstance(hint, dict) else claim["record_type"]
    card = _kinlayer_request(config, "GET", f"/api/entities/{urllib.parse.quote(subject_id, safe='')}/context-card")
    buckets = {"entity_facts": ("profile_facts",), "entity_edges": ("relationship_edges",),
               "observations": ("stable_context", "recent_context", "communication_context", "cautions")}[kind]
    subtype_key = _MEMORY_SUBTYPES[kind]
    hint = claim.get("target_hint")
    subtype = hint.get(subtype_key, claim.get(subtype_key)) if isinstance(hint, dict) else claim.get(subtype_key)
    rows = {}
    for bucket in buckets:
        for row in card.get(bucket, []):
            if not isinstance(row, dict) or not row.get("id") or row.get("status") not in {"active", "disputed"}:
                continue
            if subject_id not in _memory_targets(kind, row) or (subtype and row.get(subtype_key) != subtype):
                continue
            rows[f"{kind}:{row['id']}"] = row
    if len(rows) == 1 and subtype:
        selected = next(iter(rows))
    else:
        selected = None
        if plugin_llm is not None and 0 < len(rows) <= 20:
            options = [{"record_ref": ref, "subtype": row.get(subtype_key), "content": (row.get("content") or row.get("claim_text") or "")[:600],
                        "targets": _memory_targets(kind, row), "occurred_at": row.get("occurred_at"), "valid_from": row.get("valid_from"), "valid_to": row.get("valid_to")} for ref, row in sorted(rows.items())]
            try:
                result = plugin_llm.complete_structured(
                    task="personal_context_router_classifier",
                    instructions="Select the exact existing record the CURRENT USER asks to correct/retract/reattribute. Listed records are lookup context, NEVER evidence. Return only JSON {\"record_ref\": <one listed record_ref or null>}. Return null if ambiguous. Do not invent IDs or change content.",
                    input=[{"type": "text", "text": _canonical_json({"current_user": user_message[:4000], "target_hint": hint, "records": options})}],
                    json_mode=True, schema_name="personal_context_correction_target", temperature=0, max_tokens=160,
                    timeout=float(config.classifier.timeout), provider=config.classifier.provider or None,
                    model=config.classifier.model or None, purpose="personal_context_correction_target")
                parsed = result.parsed if isinstance(result.parsed, dict) else json.loads(result.text)
                selected = parsed.get("record_ref")
            except Exception:
                selected = None
        if not isinstance(selected, str) or selected not in rows:
            raise MemorySkip("correction_target_ambiguous")
    row = _kinlayer_request(config, "GET", _record_path(selected))
    if row.get("id") != selected.split(":", 1)[1] or row.get("status") not in {"active", "disputed"}:
        raise MemorySkip("correction_target_stale")
    if _memory_targets(kind, row) != _memory_targets(kind, rows[selected]) or row.get(subtype_key) != rows[selected].get(subtype_key):
        raise MemorySkip("correction_target_stale")
    return selected, row


def _memory_payload(config: RouterConfig, claim: dict[str, Any], user_message: str, allowed: dict[str, set[str]], resolved: dict[str, str], old: dict[str, Any] | None, old_kind: str | None = None) -> dict[str, Any]:
    kind, action = claim["record_type"], claim["action"]
    def resolve(name: Any) -> str:
        return _memory_resolve(config, name, user_message, allowed, resolved, create=action in {"create", "reattribute"})
    def known_time(value):
        if value is None:
            return None
        aware = _aware_timestamp(value)
        if not aware and isinstance(value, str):
            # Server SQLite readbacks have known UTC semantics, unlike human input.
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                aware = parsed.replace(tzinfo=UTC).isoformat()
        if not aware:
            raise MemorySkip("invalid_stored_timestamp")
        return aware
    payload = {"claim_basis": claim["claim_basis"], "confidence": claim["confidence"]}
    for key in ("valid_from", "valid_to", *(("occurred_at",) if kind == "observations" else ())):
        if key in claim:
            payload[key] = _aware_timestamp(claim[key]) if claim[key] is not None else None
        elif old is not None and key in old:
            payload[key] = known_time(old[key])
    if kind == "entity_edges":
        payload.update(from_entity_id=resolve(claim.get("from_subject")), to_entity_id=resolve(claim.get("to_subject")),
                       relation_type=claim["relation_type"], claim_text=claim["claim_text"].strip())
        for key in ("directed", "properties"):
            if key in claim:
                payload[key] = claim[key]
            elif old is not None and (old_kind or kind) == kind and key in old:
                payload[key] = old[key]
    else:
        name = claim.get("new_subject") if action == "reattribute" else claim.get("subject")
        payload["entity_id" if kind == "entity_facts" else "subject_entity_id"] = resolve(name)
        payload["content"] = claim["content"].strip()
        if kind == "entity_facts":
            value = _memory_fact_value(claim)
            payload.update(fact_type=claim["fact_type"], value=value, content=value.get("text", payload["content"]))
        else:
            payload["observation_type"] = claim["observation_type"]
            if claim["observation_type"] == "relationship_assessment":
                payload.update(perspective_entity_id=_memory_resolve(config, "self", user_message, allowed, resolved, create=False),
                               relationship_axis=claim["relationship_axis"], relationship_value=claim["relationship_value"])
                if old is not None and old.get("relationship_value") != claim["relationship_value"]:
                    for key in ("valid_from", "occurred_at"):
                        if key not in claim:
                            payload[key] = None
            links = [{key: link[key] for key in ("entity_id", "role", "confidence") if key in link}
                     for link in (old or {}).get("related_entities", [])]
            if action == "reattribute" and old:
                for link in links:
                    # Move only the old subject's attribution roles, never an
                    # unrelated experiencer or every participant indiscriminately.
                    if link["entity_id"] == old.get("subject_entity_id") and link["role"] in {"subject", "speaker"}:
                        link["entity_id"] = payload["subject_entity_id"]
            if "related" in claim:
                supplied = [{"entity_id": resolve(link["subject"]), "role": link["role"],
                             **({"confidence": link["confidence"]} if "confidence" in link else {})}
                            for link in claim["related"]]
                # An explicit [] clears links. A nonempty role edit replaces
                # those roles, leaving other known participant roles intact.
                roles = {link["role"] for link in supplied}
                links = [link for link in links if link["role"] not in roles] + supplied if supplied else []
            if len({(link["entity_id"], link["role"]) for link in links}) != len(links):
                raise MemorySkip("duplicate_related_role")
            payload["related_entities"] = links
    if old is not None:
        old_targets, new_targets = _memory_targets(old_kind or kind, old), _memory_targets(kind, payload)
        if (action == "correct" and old_targets != new_targets) or (action == "reattribute" and old_targets == new_targets):
            raise MemorySkip("invalid_correction_targets")
    if kind == "entity_edges" and payload["relation_type"] not in allowed.get("relation_type", set()):
        structural = ("from_entity_id", "to_entity_id", "relation_type", "directed", "properties")
        if (action != "correct" or old is None or (old_kind or kind) != kind
                or any(payload.get(key, {} if key == "properties" else None)
                       != old.get(key, {} if key == "properties" else None) for key in structural)):
            raise MemorySkip("legacy_relationship_structure_changed")
    return payload

@contextmanager
def _memory_journal(config: RouterConfig):
    # Lock across processes as well as threads: target selection, entity creation,
    # and journal preparation for this local adapter cannot race each other.
    root = Path(config.kinlayer.memory_state_dir).expanduser() if config.kinlayer.memory_state_dir else hermes_home() / "state" / "personal-context-router"
    if not root.is_absolute() or root.resolve().is_relative_to(Path(__file__).resolve().parents[1]):
        raise MemorySkip("memory_state_dir_invalid")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _MEMORY_LOCK, (root / "memory-requests.lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / "memory-requests.sqlite3"
        db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        try:
            db.execute("CREATE TABLE IF NOT EXISTS requests (input_key TEXT PRIMARY KEY, body TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS extractions (turn_key TEXT PRIMARY KEY, snapshot TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS outcomes (input_key TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS entity_creation_attempts (identity_key TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE IF NOT EXISTS identity_clearances (scope_key TEXT PRIMARY KEY, cleared_at REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS identity_pending (session_id TEXT, backend TEXT, surface TEXT, payload TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(session_id, backend, surface))")
            # Claims blocked ONLY by an unclear person, kept for one explicit native
            # confirmation in the same profile/backend/session/sender scope.
            db.execute("CREATE TABLE IF NOT EXISTS identity_deferred (scope_key TEXT NOT NULL, input_key TEXT NOT NULL, payload TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(scope_key, input_key))")
            db.commit()
            yield db
        finally:
            db.close()
            fcntl.flock(lock, fcntl.LOCK_UN)


def _memory_turn_identity(config: RouterConfig, kwargs: dict[str, Any], user_message: str) -> str:
    # No clock, generated UUID, or invented turn fallback. The exact human text
    # distinguishes messages even if a host reuses a turn identifier.
    if not all(isinstance(kwargs.get(key), str) and kwargs[key].strip() for key in ("session_id", "turn_id")) or not user_message.strip():
        raise MemorySkip("memory_turn_identity_missing")
    return hashlib.sha256(_canonical_json({
        "profile": str(hermes_home().resolve()), "backend": config.kinlayer.base_url.rstrip("/"),
        "session": kwargs["session_id"], "turn": kwargs["turn_id"],
        "human_message": kwargs.get("_human_message_identity") or hashlib.sha256(user_message.encode()).hexdigest(),
    }).encode()).hexdigest()


def _memory_input_key(config, claim, index, user_message, kwargs):
    if isinstance(kwargs.get("_deferred_input_key"), str) and kwargs["_deferred_input_key"]:
        return kwargs["_deferred_input_key"]  # confirmed replay: distinct, stable key
    turn_key = _memory_turn_identity(config, kwargs, user_message)
    if kwargs.get("_memory_turn_key") == turn_key:
        return f"{turn_key}:{index}"
    # Compatibility for direct adapter callers without an accepted hook snapshot.
    return hashlib.sha256(_canonical_json({"turn": turn_key, "index": index, "claim": claim,
        "source": _memory_source(claim, user_message, kwargs)}).encode()).hexdigest()


def _relationship_assessment_target(config, claim, user_message, allowed, resolved):
    """Select exactly one current axis, never treat a failed/malformed read as unset."""
    subject_id = _memory_resolve(config, claim.get("subject"), user_message, allowed, resolved,
                                 create=claim["action"] == "create")
    perspective_id = _memory_resolve(config, "self", user_message, allowed, resolved, create=False)
    if subject_id == perspective_id:
        raise MemorySkip("invalid_relationship_perspective_or_basis")
    profile = _kinlayer_request(config, "GET", "/api/entities/" + urllib.parse.quote(subject_id, safe="") + "/relationship-profile")
    axis = claim["relationship_axis"]
    if (profile.get("version") not in allowed.get("relationship_profile_version", set())
            or profile.get("entity_id") != subject_id or profile.get("perspective_entity_id") != perspective_id
            or not isinstance(profile.get("axes"), dict) or not isinstance(profile["axes"].get(axis), dict)):
        raise MemorySkip("relationship_profile_unavailable")
    current = profile["axes"][axis]
    if "record" not in current or "value" not in current:
        raise MemorySkip("relationship_profile_unavailable")
    record = current["record"]
    if record is None:
        if current["value"] is not None:
            raise MemorySkip("relationship_profile_unavailable")
        if claim["action"] == "retract":
            raise MemorySkip("relationship_axis_already_unset")
        if claim["action"] != "create":
            raise MemorySkip("correction_target_missing")
        return None, None
    if not isinstance(record, dict):
        raise MemorySkip("relationship_profile_unavailable")
    ref = record.get("record_ref")
    if not isinstance(ref, str) or not re.fullmatch(r"observations:[A-Za-z0-9_-]{1,120}", ref):
        raise MemorySkip("relationship_profile_unavailable")
    exact = _kinlayer_request(config, "GET", "/api/memories/observations/" + ref.split(":", 1)[1])
    payload = exact.get("payload")
    if (exact.get("record_ref") != ref or exact.get("id") != ref.split(":", 1)[1]
            or exact.get("updated_at") != record.get("updated_at") or exact.get("payload") != record.get("payload")
            or exact.get("is_current") is not True or exact.get("status") not in {"active", "disputed"}
            or not isinstance(payload, dict) or payload.get("observation_type") != "relationship_assessment"
            or payload.get("subject_entity_id") != subject_id or payload.get("perspective_entity_id") != perspective_id
            or payload.get("relationship_axis") != axis or payload.get("relationship_value") != current["value"]):
        raise MemorySkip("correction_target_stale")
    return ref, {**payload, **{key: exact[key] for key in ("id", "status", "updated_at")}}


def _memory_request_body(config: RouterConfig, claim: dict[str, Any], index: int, user_message: str, kwargs: dict[str, Any], allowed: dict[str, set[str]], resolved: dict[str, str], db: sqlite3.Connection, plugin_llm: Any) -> tuple[dict[str, Any], bool]:
    source = _memory_source(claim, user_message, kwargs)
    input_key = _memory_input_key(config, claim, index, user_message, kwargs)
    cached = db.execute("SELECT body FROM requests WHERE input_key = ?", (input_key,)).fetchone()
    if cached:
        return json.loads(cached[0]), True
    action, kind = claim["action"], claim["record_type"]
    body: dict[str, Any] = {"action": action, "source": source, "created_by": "ai_agent"}
    old = None
    assessment = kind == "observations" and claim.get("observation_type") == "relationship_assessment"
    if assessment:
        old_ref, old = _relationship_assessment_target(config, claim, user_message, allowed, resolved)
        if old is not None:
            if action == "create":
                action = "correct"
                claim = {**claim, "action": action}
                body["action"] = action
            body["old_record_ref"] = old_ref
    elif action != "create":
        subject = claim.get("subject") or claim.get("to_subject") or claim.get("from_subject")
        subject_id = _memory_resolve(config, subject, user_message, allowed, resolved, create=False)
        old_ref, old = _select_memory_target(config, claim, subject_id, user_message, plugin_llm)
        body["old_record_ref"] = old_ref
    if old is not None:
        # Legacy SQLite readbacks omit UTC offsets; these are server storage
        # timestamps with known UTC semantics, not invented source/event dates.
        updated = old.get("updated_at")
        aware = _aware_timestamp(updated)
        if not aware and isinstance(updated, str):
            try:
                parsed = datetime.fromisoformat(updated)
                if parsed.tzinfo is None:
                    aware = parsed.replace(tzinfo=UTC).isoformat()
            except ValueError:
                pass
        if not aware:
            raise MemorySkip("correction_timestamp_missing")
        body["expected_updated_at"] = aware
    if action != "retract":
        body["record"] = {"record_type": kind, "payload": _memory_payload(config, claim, user_message, allowed, resolved, old, body.get("old_record_ref", "").split(":", 1)[0])}
    reason = claim.get("reason")
    if isinstance(reason, str) and reason.strip():
        body["reason"] = redact(reason, 1000)
    digest = hashlib.sha256(_canonical_json(body).encode()).hexdigest()
    turn_scope = f"{kwargs.get('session_id') or ''}:{kwargs.get('turn_id') or ''}"
    prefix = "hermes:" + re.sub(r"[^A-Za-z0-9_.:-]", "_", turn_scope)[:48] + ":" + hashlib.sha256(input_key.encode()).hexdigest()[:16]
    body["request_id"] = f"{prefix}:{index}:{digest}"
    db.execute("INSERT INTO requests (input_key, body) VALUES (?, ?)", (input_key, _canonical_json(body)))
    # This is durable idempotency state, not an LRU cache. Eviction would let an
    # old correction replay select its replacement and silently mutate it again.
    # Each body is bounded, but rows must survive for as long as turns can replay.
    db.commit()  # Prepared BEFORE network write, including ambiguous transport outcomes.
    return body, False


def _post_memory(config: RouterConfig, body: dict[str, Any]) -> dict[str, Any]:
    for attempt in range(3):
        try:
            return _kinlayer_request(config, "POST", "/api/memories", body)
        except urllib.error.HTTPError:
            raise  # 404/409/422 and other HTTP errors never trigger semantic retry.
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def _verify_memory_receipt(config: RouterConfig, body: dict[str, Any], receipt: dict[str, Any], replay: bool, identities: set[str] | None = None) -> dict[str, Any]:
    required = ("change_id", "action", "old_record_ref", "new_record_ref", "source_episode_id")
    if not isinstance(receipt, dict) or any(key not in receipt for key in required):
        raise MemorySkip("memory_receipt_invalid")
    if receipt["action"] != body["action"] or receipt["old_record_ref"] != body.get("old_record_ref"):
        raise MemorySkip("memory_receipt_invalid")
    if any(not isinstance(receipt[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", receipt[key]) for key in ("change_id", "source_episode_id")):
        raise MemorySkip("memory_receipt_invalid")
    change = _kinlayer_request(config, "GET", f"/api/memory-changes/{receipt['change_id']}")
    expected_change = {"id": receipt["change_id"], "request_id": body["request_id"],
                       "change_kind": body["action"], "old_record_ref": receipt["old_record_ref"],
                       "new_record_ref": receipt["new_record_ref"], "source_episode_id": receipt["source_episode_id"],
                       "actor": body["created_by"]}
    if any(change.get(key) != value for key, value in expected_change.items()):
        raise MemorySkip("memory_change_readback_mismatch")
    episode = _kinlayer_request(config, "GET", f"/api/episodes/{receipt['source_episode_id']}")
    source = body["source"]
    if (episode.get("id") != receipt["source_episode_id"] or episode.get("actor") != source["actor"]
            or episode.get("body_excerpt") != source["excerpt"]
            or episode.get("source_type") != (source["source_type"] if body["action"] == "create" else "correction")
            or episode.get("source_ref") != source.get("source_ref")):
        raise MemorySkip("memory_episode_readback_mismatch")
    def instant(value):
        if value is None:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    if instant(episode.get("occurred_at")) != instant(source.get("occurred_at")):
        raise MemorySkip("memory_episode_readback_mismatch")
    new_ref, old_ref = receipt["new_record_ref"], receipt["old_record_ref"]
    affected = set()
    row = None
    if body["action"] == "retract":
        if new_ref is not None:
            raise MemorySkip("memory_receipt_invalid")
    else:
        if not isinstance(new_ref, str) or new_ref.split(":", 1)[0] != body["record"]["record_type"]:
            raise MemorySkip("memory_receipt_invalid")
        row = _kinlayer_request(config, "GET", _record_path(new_ref))
        statuses = {"active", "disputed", "superseded", "deleted"} if replay else {"active", "disputed"}
        if row.get("id") != new_ref.split(":", 1)[1] or row.get("status") not in statuses:
            raise MemorySkip("memory_readback_mismatch")
        affected.update(_memory_targets(body["record"]["record_type"], row))
        if identities is not None:
            identities.update(_memory_targets(body["record"]["record_type"], row))
            identities.update(link["entity_id"] for link in row.get("related_entities", []))
        for key, value in body["record"]["payload"].items():
            actual = row.get(key)
            if key in {"occurred_at", "valid_from", "valid_to"} and value is not None:
                if not isinstance(actual, str):
                    raise MemorySkip("memory_readback_mismatch")
                parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
                actual = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
                value = datetime.fromisoformat(value)
            elif key == "related_entities":
                by_role = {(link.get("entity_id"), link.get("role")): link for link in (actual or [])}
                if any("confidence" in link and by_role.get((link["entity_id"], link["role"]), {}).get("confidence") != link["confidence"] for link in value):
                    raise MemorySkip("memory_readback_mismatch")
                actual = sorted((link.get("entity_id"), link.get("role")) for link in (actual or []))
                value = sorted((link["entity_id"], link["role"]) for link in value)
            elif key == "value" and isinstance(actual, dict):
                actual = {k: v for k, v in actual.items() if v is not None}
            if actual != value:
                raise MemorySkip("memory_readback_mismatch")
    if old_ref:
        old = _kinlayer_request(config, "GET", _record_path(old_ref))
        if old.get("id") != old_ref.split(":", 1)[1] or old.get("status") != ("deleted" if body["action"] == "retract" else "superseded"):
            raise MemorySkip("memory_readback_mismatch")
        affected.update(_memory_targets(old_ref.split(":", 1)[0], old))
        if identities is not None:
            identities.update(_memory_targets(old_ref.split(":", 1)[0], old))
            identities.update(link["entity_id"] for link in old.get("related_entities", []))
    for entity_id in sorted(affected):
        card = _kinlayer_request(config, "GET", f"/api/entities/{urllib.parse.quote(entity_id, safe='')}/context-card")
        if card.get("entity", {}).get("id") != entity_id:
            raise MemorySkip("memory_context_readback_mismatch")
        current = {f"{kind}:{item['id']}": item for kind, sections in {
            "entity_facts": ("profile_facts",), "entity_edges": ("relationship_edges",),
            "observations": ("stable_context", "recent_context", "communication_context", "cautions")}.items()
            for section in sections for item in card.get(section, []) if item.get("id")}
        for axis in (card.get("relationship_profile") or {}).get("axes", {}).values():
            record = axis.get("record") if isinstance(axis, dict) else None
            if isinstance(record, dict) and isinstance(record.get("payload"), dict):
                if any(not isinstance(record.get(key), str) for key in ("record_ref", "id", "status")):
                    raise MemorySkip("memory_context_readback_mismatch")
                current[record["record_ref"]] = {**record["payload"], "id": record["id"], "status": record["status"]}
        if old_ref in current or (row and row["status"] not in {"active", "disputed"} and new_ref in current):
            raise MemorySkip("memory_context_readback_mismatch")
        if row and row["status"] in {"active", "disputed"} and entity_id in _memory_targets(body["record"]["record_type"], row):
            visible = current.get(new_ref)
            if not visible or visible.get("status") != row["status"] or any(visible.get(key) != row.get(key) for key in body["record"]["payload"]):
                raise MemorySkip("memory_context_readback_mismatch")
            evidence_kind = {"entity_facts": "fact", "entity_edges": "edge", "observations": "observation"}[body["record"]["record_type"]]
            if not any(item.get("record_type") == evidence_kind and item.get("record_id") == row["id"]
                       and item.get("episode_id") == receipt["source_episode_id"]
                       and item.get("actor") == source["actor"] and item.get("excerpt") == source["excerpt"]
                       for item in card.get("provenance_summary", {}).get("evidence", [])):
                raise MemorySkip("memory_context_source_mismatch")
    return {key: receipt[key] for key in required}


def _submit_kinlayer_memories(config: RouterConfig, decision: PolicyDecision, user_message: str, kwargs: dict[str, Any], plugin_llm: Any = None) -> dict[str, Any]:
    claims = decision.kinlayer_memories
    if not claims:
        return {"status": "no_claims", "receipts": [], "errors": []}
    if config.dry_run or not config.kinlayer.enabled:
        return {"status": "no_claims", "receipts": [], "errors": [{"code": "dry_run" if config.dry_run else "kinlayer_disabled"}]}
    if not isinstance(claims, list) or len(claims) > 8:
        return {"status": "failed", "receipts": [], "errors": [{"code": "invalid_claim_count"}]}
    from .identity import IdentityBlocked
    receipts, errors, attention = [], [], []
    try:
        allowed = None
        resolved = _IdentityResolutions(config, kwargs, plugin_llm, user_message)
        with _memory_journal(config) as db:
            resolved.db = db
            for index, claim in enumerate(claims):
                input_key = _memory_input_key(config, claim, index, user_message, kwargs)
                saved = db.execute("SELECT state FROM outcomes WHERE input_key = ?", (input_key,)).fetchone()
                state = json.loads(saved[0]) if saved else {}
                if state.get("noop"):
                    continue
                # Semantic failures are immutable too: a replay is not permission
                # to reselect an ambiguous/stale target after other claims mutate it.
                if state.get("terminal"):
                    errors.append(state["error"])
                    continue
                receipt = state.get("receipt")
                attempted = False
                code = None
                identity_issue = None
                try:
                    if not isinstance(claim, dict):
                        raise MemorySkip("invalid_claim_shape")
                    cached = db.execute("SELECT body FROM requests WHERE input_key = ?", (input_key,)).fetchone()
                    if cached:
                        # A prepared operation is immutable; ontology/capability
                        # read failures must not erase its known commit outcome.
                        body, replay = json.loads(cached[0]), True
                    else:
                        if not _memory_contract_supported(config):
                            raise MemorySkip("contract_unsupported")
                        if allowed is None:
                            allowed = _ontology_allowed(_kinlayer_request(config, "GET", "/api/ontology"))
                        _validate_memory_claim(claim, allowed)
                        _preflight_memory_people(config, claim, user_message, allowed, resolved)
                        body, replay = _memory_request_body(config, claim, index, user_message, kwargs, allowed, resolved, db, plugin_llm)
                    ids: set[str] = set()
                    attempted = True
                    receipt = _post_memory(config, body)
                    # Acknowledged commit survives a crash or failed readback.
                    db.execute("INSERT OR REPLACE INTO outcomes VALUES (?, ?)", (input_key, _canonical_json({"receipt": receipt})))
                    db.commit()
                    verified = _verify_memory_receipt(config, body, receipt, replay, ids)
                    receipts.append(verified)
                    # Legacy identity_pending/deferred rows are retained, not cleared or replayed.
                    db.commit()
                    ids.update(ref.split(":", 1)[1] for ref in (verified["old_record_ref"], verified["new_record_ref"]) if ref)
                    attention.append({"candidate_type": {"entity_facts": "profile_field", "entity_edges": "relationship_edge", "observations": "observation"}[claim["record_type"]], "ids": sorted(value for value in ids if value)})
                except urllib.error.HTTPError as exc:
                    code = f"http_{exc.code}"
                except IdentityBlocked as exc:
                    code = "identity_ambiguous"
                    identity_issue = exc.result
                except MemorySkip as exc:
                    code = exc.code
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    code = "transport_unknown" if attempted and receipt is None else "transport_failed"
                except Exception:
                    code = "memory_write_unknown" if attempted and receipt is None else "memory_write_failed"
                if code:
                    if code == "relationship_axis_already_unset":
                        db.execute("INSERT OR REPLACE INTO outcomes VALUES (?, ?)", (input_key, _canonical_json({"noop": True})))
                        db.commit()
                        continue
                    if (isinstance(claim, dict) and claim.get("record_type") == "entity_edges"
                            and (code == "http_422" or code.startswith("ontology_unsupported:"))):
                        # Refresh for later operations, never mutate/retry this rejected claim.
                        try:
                            allowed = _ontology_allowed(_kinlayer_request(config, "GET", "/api/ontology"))
                        except Exception:
                            allowed = None
                    error = {"claim_index": index, "code": code,
                             "outcome": "committed_but_unverified" if receipt is not None else
                                        "unknown" if code in {"transport_unknown", "memory_write_unknown", "http_500", "http_502", "http_503", "http_504"} else "not_committed"}
                    if identity_issue is not None:
                        error["identity"] = identity_issue
                        if identity_issue["reason"] == "entity_create_outcome_unknown":
                            error["outcome"] = "unknown"
                        # Unresolved is an immutable write outcome, not a forced question.
                        # Preserve pre-0.15 operational/deferred journals byte-for-byte.
                    if receipt is not None:
                        error["receipt"] = receipt
                    errors.append(error)
                    state = {"error": error, "receipt": receipt,
                             "terminal": receipt is None and (isinstance(code, str) and (code.startswith("http_4") or
                                          (code not in {"contract_unsupported", "transport_failed", "transport_unknown", "memory_write_failed", "memory_write_unknown"} and not code.startswith("http_"))))}
                    db.execute("INSERT OR REPLACE INTO outcomes VALUES (?, ?)", (input_key, _canonical_json(state)))
                    db.commit()
    except urllib.error.HTTPError as exc:
        errors.append({"code": f"http_{exc.code}"})
    except MemorySkip as exc:
        errors.append({"code": exc.code})
    except Exception:
        errors.append({"code": "ontology_or_journal_unavailable"})
    status = "no_claims" if not receipts and not errors else "partial" if receipts and errors else "saved" if receipts else "committed_but_unverified" if errors and all(item.get("outcome") == "committed_but_unverified" for item in errors) else "unknown" if any(item.get("outcome") in {"unknown", "committed_but_unverified"} for item in errors) else "contract_unsupported" if errors and all(item["code"] == "contract_unsupported" for item in errors) else "ambiguous" if errors and all("ambiguous" in item["code"] for item in errors) else "failed"
    return {"status": status, "receipts": receipts, "errors": errors, "_attention_identity": attention}


_DEFERRED_KWARGS = ("session_id", "turn_id", "task_id", "_memory_turn_key", "_memory_source_time",
                    "_human_message_identity", "occurred_at", "message_timestamp", "created_at", "ts", "timestamp")


def _deferred_scope_key(scope, surface):
    return _canonical_json([*scope, surface])


def _defer_blocked_claim(db, scope, issue, claim, index, input_key, user_message, kwargs):
    """Keep a claim blocked ONLY by an unclear person for one explicit confirmation.

    The stored source is the original human turn; nothing from the later
    confirmation or the assistant question can become evidence.
    """
    if (not scope or issue.get("reason") != "identity_ambiguous" or not issue.get("candidates")
            or not isinstance(claim, dict) or claim.get("action") != "create"):
        return
    db.execute("DELETE FROM identity_deferred WHERE created_at < ?", (time.time() - 7 * 86400,))
    payload = {"surface": issue["surface"], "claim": claim, "index": index, "user_message": user_message[:4000],
               "candidate_ids": sorted(c["entity_id"] for c in issue["candidates"] if isinstance(c, dict) and c.get("entity_id")),
               "kwargs": {k: kwargs[k] for k in _DEFERRED_KWARGS if k in kwargs and isinstance(kwargs[k], (str, int, float))}}
    db.execute("INSERT OR IGNORE INTO identity_deferred VALUES (?, ?, ?, ?)",
               (_deferred_scope_key(scope, issue["surface"]), input_key, _canonical_json(payload), time.time()))
    db.execute("DELETE FROM identity_deferred WHERE rowid NOT IN (SELECT rowid FROM identity_deferred ORDER BY created_at DESC LIMIT 64)")


def discard_deferred_claims(config: RouterConfig, scope, surface: str) -> int:
    """User said it is NOT that person: the blocked claims are dropped, never saved."""
    with _memory_journal(config) as db:
        count = db.execute("DELETE FROM identity_deferred WHERE scope_key=?", (_deferred_scope_key(scope, surface),)).rowcount
        db.commit()
    return count


def replay_confirmed_claims(config: RouterConfig, scope, confirmed: dict[str, dict[str, Any]], plugin_llm: Any = None) -> list[dict[str, Any]]:
    """Save blocked claims once, after the user explicitly confirmed the person."""
    results = []
    if config.dry_run or not config.kinlayer.enabled:
        return results  # leave rows intact; nothing is consumed without a real write path
    for surface, identity in sorted(confirmed.items()):
        entity_id = identity.get("entity_id") if isinstance(identity, dict) else None
        if not scope or not isinstance(entity_id, str) or not entity_id:
            continue
        key = _deferred_scope_key(scope, surface)
        with _memory_journal(config) as db:
            rows = db.execute("SELECT input_key, payload FROM identity_deferred WHERE scope_key=? AND created_at>? ORDER BY created_at",
                              (key, time.time() - 7 * 86400)).fetchall()
            # Consume before network writes: a second confirmation must not replay.
            db.execute("DELETE FROM identity_deferred WHERE scope_key=?", (key,))
            db.commit()
        for input_key, raw in rows:
            item = json.loads(raw)
            if entity_id not in item.get("candidate_ids", []):
                results.append({"surface": surface, "status": "skipped", "code": "confirmed_person_not_a_candidate"})
                continue
            source_kwargs = dict(item.get("kwargs") or {})
            source_kwargs.update({
                "_identity_scope": list(scope),
                "_deferred_input_key": hashlib.sha256(_canonical_json([input_key, "confirmed", entity_id]).encode()).hexdigest(),
                "_identity_results": {surface: {**identity, "surface": surface, "status": "resolved",
                                                "clarification_needed": False, "entity_id": entity_id}},
            })
            decision = PolicyDecision(kinlayer_memories=[item["claim"]])
            outcome = _safe_submit_kinlayer_memories(config, decision, item["user_message"], source_kwargs, plugin_llm)
            results.append({"surface": surface, "status": outcome["status"],
                             "receipts": outcome.get("receipts", []),
                             "errors": [{k: e.get(k) for k in ("code", "outcome")} for e in outcome.get("errors", [])]})
    return results


def _safe_submit_kinlayer_memories(config: RouterConfig, decision: PolicyDecision, user_message: str, kwargs: dict[str, Any], plugin_llm: Any = None) -> dict[str, Any]:
    try:
        return _submit_kinlayer_memories(config, decision, user_message, kwargs, plugin_llm)
    except Exception:
        return {"status": "failed", "receipts": [], "errors": [{"code": "memory_write_failed"}]}


def _source_summary(label: str) -> str:
    redacted = redact(label, 180)
    if not redacted.startswith("knowledge_file:"):
        return redacted
    parts = redacted.split(":")
    if len(parts) < 3:
        return redacted
    path = Path(parts[1]).expanduser()
    return ":".join(["knowledge_file", path.name or parts[1], *parts[2:]])


def _evidence_summary_entry(
    decision: PolicyDecision,
    domain_name: str,
    target: Path,
    evidence_id: str = "",
) -> str:
    summary = str(decision.evidence_summary or "").strip()
    derived = [str(item).strip() for item in decision.derived_memory if str(item).strip()]

    parts: list[str] = []
    if summary:
        parts.append(summary)
    if derived:
        parts.append(" ".join(derived[:3]))
    note = " ".join(parts).strip()
    note = re.sub(r"\s+", " ", note)
    # Dates/uncertainty in the actual summary stay intact. Write-time and
    # provenance belong to the evidence ledger, not prompt-facing prose.
    return f"- {note}" if note else ""


def _cultural_policy(bundle: ManifestBundle) -> dict[str, Any]:
    domains = bundle.domain_map.get("domains") if isinstance(bundle.domain_map, dict) else {}
    domain = domains.get("cultural_taste") if isinstance(domains, dict) else {}
    policy = domain.get("cultural_item_policy") if isinstance(domain, dict) else {}
    return policy if isinstance(policy, dict) else {}


def _cultural_policy_float(bundle: ManifestBundle, key: str, default: float) -> float:
    try:
        return float(_cultural_policy(bundle).get(key, default))
    except (TypeError, ValueError):
        return default


def _cultural_policy_int(bundle: ManifestBundle, key: str, default: int) -> int:
    try:
        return max(1, int(_cultural_policy(bundle).get(key, default)))
    except (TypeError, ValueError):
        return default


def _useful_cultural_subjects(decision: PolicyDecision) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in decision.subjects:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        key = value.casefold()
        if len(value) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _cultural_candidate_only_reason(
    bundle: ManifestBundle,
    decision: PolicyDecision,
    domain_name: str,
) -> str:
    if domain_name != "cultural_taste":
        return ""

    item = decision.cultural_item
    title = str(item.get("item_title") or "").strip()
    useful_subjects = _useful_cultural_subjects(decision)

    status = str(item.get("resolution_status") or "").strip().casefold()
    non_item_criterion = status == "not_applicable"
    medium = str(item.get("medium") or "").strip()
    if item:
        resolution_min = _cultural_policy_float(
            bundle, "resolution_min_confidence", 0.75
        )
        if not canonical_resolution(item, resolution_min):
            return "unresolved_cultural_item"
        if not non_item_criterion and not title:
            return "unresolved_cultural_item"
        if not non_item_criterion and not medium:
            return "missing_cultural_medium"
        if medium and not supported_cultural_medium(medium):
            return "unsupported_cultural_medium"
    if not non_item_criterion and not title and not useful_subjects:
        return "empty_cultural_identity_and_subjects"

    evidence_min = _cultural_policy_float(
        bundle, "canonical_evidence_min_confidence", 0.70
    )
    if decision.confidence is None or decision.confidence < evidence_min:
        return "low_confidence_cultural_item"
    return ""


def _cultural_item_bullet(decision: PolicyDecision, evidence_id: str) -> str:
    item = decision.cultural_item
    label = cultural_item_label(item)
    qualifiers = [
        str(item.get(field) or "").strip()
        for field in ("medium", "experience_state")
        if str(item.get(field) or "").strip()
    ]
    details: list[str] = []
    reaction = str(item.get("reaction") or "").strip()
    reason = str(item.get("reaction_reason") or "").strip()
    comparison = str(item.get("comparison_target") or "").strip()
    mentions = item.get("mentioned_characters_or_roles")
    if reaction:
        details.append(reaction)
    if reason:
        details.append(f"Reason: {reason}")
    if comparison:
        details.append(f"Compared with: {comparison}")
    if isinstance(mentions, list) and mentions:
        details.append(f"Mentions: {', '.join(str(value) for value in mentions[:5])}")
    if not details:
        details.append(str(decision.evidence_summary or "User-reported item experience.").strip())
    qualifier_text = f" ({'; '.join(qualifiers)})" if qualifiers else ""
    return f"- **{label}**{qualifier_text}: {'; '.join(details)}."


def _cultural_evidence_summary_text(decision: PolicyDecision) -> str:
    item = decision.cultural_item
    label = cultural_item_label(item)
    parts = [
        str(item.get(field) or "").strip()
        for field in (
            "experience_state",
            "reaction",
            "reaction_reason",
            "comparison_target",
        )
        if str(item.get(field) or "").strip()
    ]
    summary = "; ".join(parts)
    return f"{label}: {summary}" if label and summary else label or summary


def _cultural_is_item_experience(decision: PolicyDecision) -> bool:
    if not decision.cultural_item:
        return False
    status = str(
        decision.cultural_item.get("resolution_status") or ""
    ).strip().casefold()
    return status != "not_applicable"


def _candidate_entry(
    config: RouterConfig,
    decision: PolicyDecision,
    user_message: str,
    kwargs: dict[str, Any],
    candidate_only_reason: str = "",
) -> dict[str, Any]:
    cultural = bool(decision.cultural_item)
    cultural_item_experience = _cultural_is_item_experience(decision)
    cultural_summary = _cultural_evidence_summary_text(decision) if cultural else ""
    entry = {
        "ts": time.strftime(_TS_FMT),
        "session_id": str(kwargs.get("session_id") or ""),
        "task_id": str(kwargs.get("task_id") or ""),
        "turn_id": str(kwargs.get("turn_id") or ""),
        "dry_run": config.dry_run,
        "target": decision.post_turn_target,
        **_message_provenance(user_message),
        "selected_sources": decision.selected_sources,
        "raw_transcript_storage": decision.raw_transcript_storage,
        "evidence_summary": (
            cultural_summary or decision.evidence_summary
            if cultural
            else decision.evidence_summary
        ),
        "derived_memory": (
            [] if cultural_item_experience else decision.derived_memory
        ),
        "cultural_item": decision.cultural_item,
        "kinlayer_memory_count": len(decision.kinlayer_memories),
        "subjects": decision.subjects,
        "usable_person_subjects": _usable_person_subjects(decision.subjects, user_message),
        "route_owner": "kinlayer" if _relationship_person_specific(decision, "relationships", user_message) else "domain",
        "confidence": decision.confidence,
    }
    if candidate_only_reason:
        entry["candidate_only_reason"] = candidate_only_reason
    return entry


def _message_provenance(user_message: str) -> dict[str, Any]:
    return {
        "message_length": len(user_message),
        "message_sha256": "sha256:" + hashlib.sha256(user_message.encode("utf-8")).hexdigest(),
    }


def _combined_decision_text(decision: PolicyDecision, user_message: str = "") -> str:
    return " ".join(
        [
            str(user_message or ""),
            str(decision.evidence_summary or ""),
            " ".join(str(item) for item in decision.derived_memory),
        ]
    )


def _third_party_subject_domain_block(
    domain_name: str,
    decision: PolicyDecision,
    user_message: str,
) -> str:
    if domain_name != "cultural_taste":
        return ""
    subjects = _usable_person_subjects(decision.subjects, user_message)
    mentions = decision.cultural_item.get("mentioned_characters_or_roles")
    mentioned_norms = {
        _norm_subject(str(value))
        for value in mentions
        if str(value).strip()
    } if isinstance(mentions, list) else set()
    subjects = [
        subject for subject in subjects
        if _norm_subject(subject) not in mentioned_norms
    ]
    if not subjects:
        return ""
    combined = _combined_decision_text(decision)
    if any(subject and subject in combined for subject in subjects):
        return "blocked_third_party_subject_owner"
    return ""


def _has_post_turn_work(decision: PolicyDecision | None) -> bool:
    if decision is None:
        return False
    return bool(decision.active_policies or decision.active_domains or decision.post_turn_target)


def _domain_confidence(decision: PolicyDecision, domain_name: str) -> float | None:
    for domain in decision.active_domains:
        if str(domain.get("name") or "") != domain_name:
            continue
        activate = domain.get("activate_when")
        if not isinstance(activate, dict):
            return None
        key = f"domains.{domain_name}"
        value = activate.get(key)
        # The activation threshold is policy, not classifier output.  Avoid
        # pretending it is evidence confidence.
        return None if value is not None else None
    return None


def _evidence_guard(bundle: ManifestBundle) -> Path | None:
    policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
    evidence = policy.get("evidence") if isinstance(policy.get("evidence"), dict) else {}
    guard = evidence.get("path_guard") if isinstance(evidence, dict) else None
    if not guard:
        domain_defaults = bundle.domain_map.get("defaults") if isinstance(bundle.domain_map, dict) else {}
        guard = (
            domain_defaults.get("evidence_ledger_base_dir")
            if isinstance(domain_defaults, dict)
            else None
        )
    if not guard:
        return gyurin_knowledge_root()
    path = Path(str(guard)).expanduser()
    if not path.is_absolute():
        path = gyurin_knowledge_root() / path
    return path if is_under_gyurin_knowledge_root(path) else gyurin_knowledge_root()


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(parent.expanduser().resolve())
        return True
    except ValueError:
        return False


def _evidence_ledger_path(
    domain_name: str,
    domain: dict[str, Any],
    bundle: ManifestBundle,
) -> Path | None:
    value = str(domain.get("evidence_ledger") or "")
    if not value:
        policy = bundle.storage_policy if isinstance(bundle.storage_policy, dict) else {}
        evidence = policy.get("evidence") if isinstance(policy.get("evidence"), dict) else {}
        base = evidence.get("base_dir") if isinstance(evidence, dict) else None
        if base:
            base_path = Path(str(base)).expanduser()
            if not base_path.is_absolute():
                base_path = gyurin_knowledge_root() / base_path
            value = str(base_path / f"{domain_name}.jsonl")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = gyurin_knowledge_root() / path
    guard = _evidence_guard(bundle)
    if not is_under_gyurin_knowledge_root(path) or (guard and not _is_under(path, guard)):
        return None
    return path


def _domain_prefix(domain_name: str, domain: dict[str, Any]) -> str:
    prefix = str(domain.get("domain_prefix") or "").strip()
    if prefix:
        return re.sub(r"[^A-Za-z0-9_-]+", "", prefix)[:16] or "ctx"
    return re.sub(r"[^A-Za-z0-9_-]+", "", domain_name.replace("-", "_"))[:16] or "ctx"


def _next_evidence_id(path: Path, domain_name: str, domain: dict[str, Any]) -> str:
    date_compact = time.strftime("%Y%m%d")
    prefix = _domain_prefix(domain_name, domain)
    slug = "post_turn"
    seq = 1
    if path.exists():
        needle = f"ev_{date_compact}_{prefix}_{slug}_"
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if needle in line:
                seq += 1
    return f"ev_{date_compact}_{prefix}_{slug}_{seq:03d}"


def _append_evidence_ledger(
    config: RouterConfig,
    bundle: ManifestBundle,
    decision: PolicyDecision,
    domain_name: str,
    domain: dict[str, Any],
    user_message: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    path = _evidence_ledger_path(domain_name, domain, bundle)
    if path is None:
        return {"write": "no_evidence_ledger"}
    path.parent.mkdir(parents=True, exist_ok=True)
    evidence_id = _next_evidence_id(path, domain_name, domain)
    entry = {
        "id": evidence_id,
        "created_at": time.strftime(_TS_FMT),
        "domain": domain_name,
        "subjects": decision.subjects,
        "source": {
            "type": "post_turn_memory_triage",
            "session_id": str(kwargs.get("session_id") or ""),
            "task_id": str(kwargs.get("task_id") or ""),
            "turn_id": str(kwargs.get("turn_id") or ""),
        },
        "summary": (
            (_cultural_evidence_summary_text(decision) or decision.evidence_summary)
            if domain_name == "cultural_taste"
            else decision.evidence_summary
            or _evidence_summary_entry(decision, domain_name, path, evidence_id)
        ),
        "derived_memory": (
            []
            if domain_name == "cultural_taste" and _cultural_is_item_experience(decision)
            else decision.derived_memory
        ),
        "cultural_item": decision.cultural_item,
        "confidence": decision.confidence,
        "sensitivity": str(domain.get("sensitivity") or "personal_context"),
        "raw_storage": decision.raw_transcript_storage,
        "promoted_to": [],
        **_message_provenance(user_message),
        "selected_sources": decision.selected_sources,
        "dry_run": config.dry_run,
    }
    # Backward-compatible alias for older local probes.
    entry["evidence_id"] = evidence_id
    entry["raw_transcript_storage"] = decision.raw_transcript_storage
    # Exact rendered candidates let retention recognize only generated lines,
    # without visible markers or a second state store. This is not a promotion
    # receipt: policy may still block the subsequent Markdown write.
    context_entries: list[str] = []
    if domain_name != "cultural_taste":
        entry["context_entry"] = _evidence_summary_entry(decision, domain_name, path)
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        previous = json.loads(line)
                    except ValueError:
                        continue
                    value = previous.get("context_entry") if isinstance(previous, dict) else None
                    if isinstance(value, str) and value:
                        context_entries.append(value)
        if entry["context_entry"]:
            context_entries.append(entry["context_entry"])
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return {"write": "evidence_appended", "evidence_path": str(path), "evidence_id": evidence_id,
            "context_entries": context_entries}


def process_post_turn(
    config: RouterConfig,
    bundle: ManifestBundle,
    decision: PolicyDecision | None,
    telemetry: dict[str, int] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    candidate_start = time.monotonic()
    user_message = str(kwargs.get("user_message") or "")
    if (
        not config.enabled
        or not _has_post_turn_work(decision)
        or is_low_signal(user_message)
    ):
        _record_ms(telemetry, "candidate_ms", candidate_start)
        return {"action": "ignored"}
    assert decision is not None

    response: dict[str, Any] = {"action": "ignored"}
    domain_found = _domain_from_target(decision, bundle)
    domain_name = domain_found[0] if domain_found is not None else ""
    candidate_only_reason = _cultural_candidate_only_reason(
        bundle, decision, domain_name
    )
    if _write_candidate_log_enabled(bundle):
        path, used_candidate_fallback = _candidate_path(bundle)
        path.parent.mkdir(parents=True, exist_ok=True)
        candidate = _candidate_entry(
            config,
            decision,
            user_message,
            kwargs,
            candidate_only_reason,
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n")
        response = {"action": "candidate_logged", "path": str(path)}
        if used_candidate_fallback:
            response["candidate_path"] = "fallback_default"
    else:
        response = {"action": "candidate_skipped"}
    _record_ms(telemetry, "candidate_ms", candidate_start)

    kinlayer_person_specific = False
    if domain_found is not None:
        kinlayer_person_specific = _relationship_person_specific(decision, domain_found[0], user_message)
    if kinlayer_person_specific:
        response["route_owner"] = "kinlayer"
        response["kinlayer_person_subjects"] = _usable_person_subjects(decision.subjects, user_message)
        response["kinlayer_memory_count"] = len(decision.kinlayer_memories)
    domain_block_reason = ""
    if domain_found is not None:
        domain_block_reason = _third_party_subject_domain_block(domain_found[0], decision, user_message)
    if domain_block_reason:
        response["route_owner"] = "external_person_candidate_log"
        response["curated_write"] = domain_block_reason
        response["evidence"] = "candidate_log_only"
        return response
    if candidate_only_reason:
        response["candidate_only_reason"] = candidate_only_reason
        response["curated_write"] = f"blocked_{candidate_only_reason}"
        response["evidence"] = "candidate_log_only"
        return response
    if config.dry_run:
        response["evidence"] = "dry_run"
        return response
    if kinlayer_person_specific:
        kinlayer_result = _safe_submit_kinlayer_memories(config, decision, user_message, kwargs, kwargs.get("plugin_llm"))
        response["kinlayer_api"] = kinlayer_result["status"]
        response["kinlayer_receipts"] = kinlayer_result.get("receipts", [])
        response["kinlayer_errors"] = kinlayer_result.get("errors", [])
        if kinlayer_result.get("_attention_identity"):
            response["_attention_identity"] = kinlayer_result["_attention_identity"]

    evidence_start = time.monotonic()
    evidence_result: dict[str, Any] = {"write": "no_domain"}
    if kinlayer_person_specific:
        evidence_result = {"write": "routed_to_kinlayer_memories"}
    elif _write_evidence_enabled(bundle) and domain_found is not None:
        domain_name, domain = domain_found
        evidence_result = _append_evidence_ledger(
            config,
            bundle,
            decision,
            domain_name,
            domain,
            user_message,
            kwargs,
        )
    response["evidence"] = evidence_result.get("write")
    if evidence_result.get("evidence_path"):
        response["evidence_path"] = evidence_result["evidence_path"]
    if evidence_result.get("evidence_id"):
        response["evidence_id"] = evidence_result["evidence_id"]
    _record_ms(telemetry, "evidence_ms", evidence_start)

    if kinlayer_person_specific:
        response["curated_write"] = "blocked_kinlayer_person_owner"
        return response

    if not config.post_turn.auto_write_domain_markdown:
        return response

    markdown_start = time.monotonic()
    target = None
    if domain_found is not None:
        target = _resolve_knowledge_path(
            str(domain_found[1].get("curated_file") or domain_found[1].get("file") or "")
        )
    if target is None:
        target = _domain_path_from_target(decision, bundle)
    if target is None:
        _record_ms(telemetry, "markdown_ms", markdown_start)
        response["curated_write"] = "no_target"
        return response
    domain_name = domain_found[0] if domain_found else target.stem.replace("-", "_")
    if not _storage_allows_auto_write(bundle, domain_name):
        _record_ms(telemetry, "markdown_ms", markdown_start)
        response["curated_write"] = "blocked_policy"
        return response
    if domain_name == "cultural_taste":
        promotion_min = _cultural_policy_float(
            bundle, "curated_promotion_min_confidence", 0.75
        )
        if decision.confidence is None or decision.confidence < promotion_min:
            _record_ms(telemetry, "markdown_ms", markdown_start)
            response["curated_write"] = "blocked_cultural_promotion_confidence"
            return response
        if not str(decision.cultural_item.get("item_title") or "").strip():
            _record_ms(telemetry, "markdown_ms", markdown_start)
            response["curated_write"] = "blocked_cultural_item_required"
            return response
    section = _auto_write_section(bundle, domain_name, decision)
    if section is None:
        _record_ms(telemetry, "markdown_ms", markdown_start)
        response["curated_write"] = "blocked_section_policy"
        return response

    if evidence_result.get("write") != "evidence_appended":
        _record_ms(telemetry, "markdown_ms", markdown_start)
        response["curated_write"] = "blocked_missing_evidence_ledger"
        return response
    entry = (
        _cultural_item_bullet(decision, str(evidence_result.get("evidence_id") or ""))
        if domain_name == "cultural_taste"
        else _evidence_summary_entry(decision, domain_name, target)
    )
    if not entry:
        _record_ms(telemetry, "markdown_ms", markdown_start)
        response["curated_write"] = "blocked_empty_summary"
        return response

    result = append_domain_entry(
        MarkdownWriteRequest(
            domain=domain_name,
            target_path=target,
            section=section,
            entry=entry,
            allowlist=_allowlist(bundle),
            backup_dir=hermes_home() / "backups" / "context-router",
            metadata={
                "subjects": decision.subjects,
                "message": user_message,
                "evidence_id": str(evidence_result.get("evidence_id") or ""),
                "context_entries": evidence_result.get("context_entries", []),
                "domain": domain_name,
                "cultural_item": decision.cultural_item,
                "cultural_item_key": cultural_item_key(decision.cultural_item),
                "max_items_per_section": _cultural_policy_int(
                    bundle, "max_items_per_section", 12
                ),
            },
        )
    )
    _record_ms(telemetry, "markdown_ms", markdown_start)
    response["curated_write"] = result.reason
    response["curated_wrote"] = result.wrote
    return response


def _record_ms(telemetry: dict[str, int] | None, key: str, start: float) -> None:
    if telemetry is not None:
        telemetry[key] = int((time.monotonic() - start) * 1000)
