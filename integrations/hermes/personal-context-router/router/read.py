"""Unregistered legacy personal-context helper retained for loaded handlers.

The current plugin entrypoint does not register this helper or its schema as a
model-facing tool. Keep it intact until an authorized Gateway restart and its
seven-day verification window have passed, because an older loaded handler may
still call ``PersonalContextRouter.personal_context()``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import gyurin_knowledge_root, hermes_home
from .logging import append_decision


DOMAINS = (
    "profile",
    "relationships",
    "cultural_taste",
    "finance_context",
    "work_style",
    "home_infrastructure",
)
_AGGREGATE_CURATED_CHARS = 12_000
_HINDSIGHT_MAX_TOKENS = 1_200
_HINDSIGHT_MAX_RESULTS = 8
_HTTP_MAX_BYTES = 1_000_000


def personal_context_schema() -> dict[str, Any]:
    """Return the legacy schema; the current entrypoint does not register it."""
    return {
        "name": "personal_context",
        "description": (
            "Retrieve a bounded, source-aware personal-context packet. Pass only the "
            "smallest relevant curated domains; opt into Hindsight only when native "
            "hybrid auto-recall is absent or insufficient. Returns context, not a final recommendation."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "domains": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(DOMAINS)},
                    "uniqueItems": True,
                },
                "include_hindsight": {"type": "boolean", "default": False},
                "person_hint": {"type": "string"},
                "need_exact_history": {"type": "boolean"},
                "need_live_state": {"type": "boolean"},
                "need_current_public_fact": {"type": "boolean"},
            },
            "required": ["query"],
        },
    }


def build_personal_context(
    args: Any,
    *,
    bundle: Any,
    hindsight_active: bool = False,
    hindsight_config_loader: Callable[[], dict[str, Any]] | None = None,
    http_transport: Callable[[str, dict[str, Any], dict[str, str], float], Any] | None = None,
    secret_loader: Callable[[str], str] | None = None,
) -> str:
    start = time.monotonic()
    payload = args if isinstance(args, Mapping) else {}
    query = str(payload.get("query") or "").strip()
    requested_domains, invalid_domains = _requested_domains(payload.get("domains"))
    result: dict[str, Any] = {
        "selected_sources": [],
        "context": [],
        "next_lookups": _next_lookups(payload),
        "uncertainties": [],
        "latency_ms": 0,
        "hindsight": {"requested": False, "status": "not_requested", "count": 0},
    }
    hindsight_error_class = ""
    api_key = ""

    if not query:
        result["uncertainties"].append("invalid_query:query must be a non-empty string")
    if invalid_domains:
        result["uncertainties"].append(
            "invalid_domains:" + ",".join(invalid_domains)
        )

    if query and not invalid_domains:
        _add_curated_context(bundle, requested_domains, result)
        if payload.get("include_hindsight") is True:
            result["hindsight"]["requested"] = True
            if not hindsight_active:
                result["hindsight"]["status"] = "inactive"
                result["uncertainties"].append("hindsight_inactive")
            else:
                try:
                    api_key = (secret_loader or _load_secret)("HINDSIGHT_API_KEY") or ""
                except Exception:
                    api_key = ""
                memories, status, uncertainty = _recall_hindsight(
                    query,
                    config_loader=hindsight_config_loader or _load_hindsight_config,
                    transport=http_transport or _http_post,
                    api_key=api_key,
                )
                result["hindsight"] = status
                hindsight_error_class = str(status.get("error_class") or "")
                if memories:
                    result["selected_sources"].append("hindsight")
                    result["context"].append({"source": "hindsight", "memories": memories})
                if uncertainty:
                    result["uncertainties"].append(uncertainty)

    result["latency_ms"] = _elapsed_ms(start)
    _audit_read(
        query=query,
        requested_domains=requested_domains,
        result=result,
        hindsight_error_class=hindsight_error_class,
    )
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    return serialized.replace(api_key, "[REDACTED]") if api_key else serialized


def _requested_domains(raw: Any) -> tuple[list[str], list[str]]:
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], ["domains_must_be_an_array"]
    requested: list[str] = []
    invalid: list[str] = []
    for value in raw:
        name = str(value)
        if name not in DOMAINS:
            invalid.append(name[:80])
        elif name not in requested:
            requested.append(name)
    return requested, invalid


def _next_lookups(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    lookups: list[dict[str, str]] = []
    if str(payload.get("person_hint") or "").strip():
        lookups.append({"source": "kinlayer", "reason": "person_specific_context"})
    if payload.get("need_exact_history") is True:
        lookups.append({"source": "session_search", "reason": "exact_history_required"})
    if payload.get("need_live_state") is True:
        lookups.append({"source": "live_tools", "reason": "current_state_required"})
    if payload.get("need_current_public_fact") is True:
        lookups.append({"source": "web_search", "reason": "current_public_fact_required"})
    return lookups


def _add_curated_context(bundle: Any, domains: list[str], result: dict[str, Any]) -> None:
    if getattr(bundle, "error", ""):
        result["uncertainties"].append(f"domain_map_unavailable:{bundle.error}")
        return
    domain_map = bundle.domain_map if isinstance(getattr(bundle, "domain_map", None), dict) else {}
    configured = domain_map.get("domains") if isinstance(domain_map, dict) else None
    if not isinstance(configured, dict):
        result["uncertainties"].append("domain_map_unavailable")
        return

    remaining = _AGGREGATE_CURATED_CHARS
    root = gyurin_knowledge_root().resolve()
    evidence_root = (root / "evidence").resolve()
    for domain in domains:
        spec = configured.get(domain)
        if not isinstance(spec, Mapping):
            result["uncertainties"].append(f"domain_not_configured:{domain}")
            continue
        path = _safe_curated_path(spec.get("curated_file"), root, evidence_root)
        if path is None:
            result["uncertainties"].append(f"curated_path_blocked:{domain}")
            continue
        if not path.is_file():
            result["uncertainties"].append(f"curated_file_unavailable:{domain}")
            continue
        prompt_sections = spec.get("prompt_sections")
        if not isinstance(prompt_sections, list) or not prompt_sections:
            result["uncertainties"].append(f"prompt_sections_unavailable:{domain}")
            continue
        try:
            domain_budget = max(0, int(spec.get("budget_tokens") or 0) * 4)
        except (TypeError, ValueError):
            domain_budget = 0
        allowed_chars = min(domain_budget, remaining)
        if allowed_chars <= 0:
            result["uncertainties"].append(f"curated_budget_exhausted:{domain}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        sections, truncated = _extract_sections(text, prompt_sections, allowed_chars)
        if not sections:
            result["uncertainties"].append(f"curated_sections_empty:{domain}")
            continue
        used = sum(len(item["heading"]) + len(item["text"]) for item in sections)
        remaining -= used
        result["selected_sources"].append(f"curated:{domain}")
        result["context"].append(
            {
                "source": f"curated:{domain}",
                "domain": domain,
                "sections": sections,
            }
        )
        if truncated:
            result["uncertainties"].append(f"curated_budget_truncated:{domain}")


def _safe_curated_path(raw: Any, root: Path, evidence_root: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    try:
        path.relative_to(evidence_root)
        return None
    except ValueError:
        pass
    if path.suffix.casefold() != ".md" or path.name == "candidates.jsonl":
        return None
    return path


def _extract_sections(text: str, headings: list[Any], budget_chars: int) -> tuple[list[dict[str, str]], bool]:
    lines = text.splitlines()
    starts: dict[str, tuple[int, int]] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+.+?\s*$", line)
        if match:
            starts.setdefault(line.strip(), (index, len(match.group(1))))

    sections: list[dict[str, str]] = []
    remaining = budget_chars
    truncated = False
    for raw_heading in headings:
        heading = str(raw_heading).strip()
        found = starts.get(heading)
        if found is None:
            continue
        start, level = found
        end = len(lines)
        for index in range(start + 1, len(lines)):
            match = re.match(r"^(#{1,6})\s+", lines[index])
            if match and len(match.group(1)) <= level:
                end = index
                break
        body = "\n".join(lines[start + 1 : end]).strip()
        cost = len(heading) + len(body)
        if cost > remaining:
            body = body[: max(0, remaining - len(heading))].rstrip()
            truncated = True
            cost = len(heading) + len(body)
        if cost <= 0 or remaining < len(heading):
            truncated = True
            break
        sections.append({"heading": heading, "text": body})
        remaining -= cost
        if remaining <= 0:
            truncated = True
            break
    return sections, truncated


def _load_hindsight_config() -> dict[str, Any]:
    path = hermes_home() / "hindsight" / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_secret(name: str) -> str:
    try:
        from agent.secret_scope import get_secret

        return str(get_secret(name, "") or "").strip()
    except Exception:
        return ""


def _recall_hindsight(
    query: str,
    *,
    config_loader: Callable[[], dict[str, Any]],
    transport: Callable[[str, dict[str, Any], dict[str, str], float], Any],
    api_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    status: dict[str, Any] = {"requested": True, "status": "unavailable", "count": 0}
    try:
        config = config_loader()
    except Exception as exc:
        status["error_class"] = type(exc).__name__
        return [], status, f"hindsight_unavailable:{type(exc).__name__}"
    if not isinstance(config, dict) or not config:
        return [], status, "hindsight_unavailable:config_missing"
    if str(config.get("mode") or "").casefold() == "disabled":
        status["status"] = "disabled"
        return [], status, "hindsight_disabled"

    api_url = str(config.get("api_url") or "").rstrip("/")
    bank_id = str(config.get("bank_id") or _nested_bank_id(config) or "").strip()
    if not api_url or not bank_id:
        return [], status, "hindsight_unavailable:api_url_or_bank_missing"
    budget = str(config.get("recall_budget") or config.get("budget") or "mid")
    if budget not in {"low", "mid", "high"}:
        budget = "mid"
    types = _string_list(config.get("recall_types")) or ["observation"]
    tags = _string_list(config.get("recall_tags")) or _string_list(config.get("retain_tags"))
    try:
        configured_tokens = int(config.get("recall_max_tokens", 4096))
    except (TypeError, ValueError):
        configured_tokens = 4096
    try:
        configured_timeout = float(config.get("timeout", 5.0))
    except (TypeError, ValueError):
        configured_timeout = 5.0
    body: dict[str, Any] = {
        "query": query[:2_000],
        "budget": budget,
        "types": types[:4],
        "max_tokens": max(1, min(configured_tokens, _HINDSIGHT_MAX_TOKENS)),
    }
    if tags:
        body["tags"] = tags[:8]
        body["tags_match"] = str(config.get("recall_tags_match") or "any")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{api_url}/v1/default/banks/{quote(bank_id, safe='')}/memories/recall"
    try:
        response = transport(url, body, headers, max(0.25, min(configured_timeout, 8.0)))
        results = response.get("results") if isinstance(response, Mapping) else None
        raw_results = results if isinstance(results, list) else []
        memories = [
            memory
            for item in raw_results[:_HINDSIGHT_MAX_RESULTS]
            if (memory := _bounded_memory(item, api_key)) is not None
        ]
        status["count"] = len(memories)
        status["status"] = "ok" if memories else "empty"
        return memories, status, "" if memories else "hindsight_empty"
    except Exception as exc:
        status["status"] = "error"
        status["error_class"] = type(exc).__name__
        return [], status, f"hindsight_recall_failed:{type(exc).__name__}"


def _nested_bank_id(config: Mapping[str, Any]) -> str:
    banks = config.get("banks")
    hermes = banks.get("hermes") if isinstance(banks, Mapping) else None
    return str(hermes.get("bankId") or "") if isinstance(hermes, Mapping) else ""


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _bounded_memory(raw: Any, api_key: str) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None

    def scalar(name: str, limit: int) -> str:
        value = str(raw.get(name) or "")[:limit]
        return value.replace(api_key, "[REDACTED]") if api_key else value

    memory: dict[str, Any] = {"source": "hindsight"}
    for name, limit in (
        ("id", 128),
        ("text", 1_000),
        ("type", 40),
        ("context", 500),
        ("occurred_start", 80),
        ("occurred_end", 80),
        ("mentioned_at", 80),
    ):
        value = scalar(name, limit)
        if value:
            memory[name] = value
    for name, count, limit in (("entities", 8, 120), ("source_fact_ids", 12, 128)):
        values = raw.get(name)
        if isinstance(values, list):
            bounded = [str(value)[:limit] for value in values[:count]]
            if api_key:
                bounded = [value.replace(api_key, "[REDACTED]") for value in bounded]
            if bounded:
                memory[name] = bounded
    return memory if memory.get("text") else None


def _http_post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> Any:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read(_HTTP_MAX_BYTES + 1)
    if len(data) > _HTTP_MAX_BYTES:
        raise ValueError("hindsight_response_too_large")
    return json.loads(data.decode("utf-8"))


def _audit_read(
    *,
    query: str,
    requested_domains: list[str],
    result: dict[str, Any],
    hindsight_error_class: str,
) -> None:
    try:
        append_decision(
            {
                "event": "personal_context_read",
                "selected_sources": ",".join(result["selected_sources"]),
                "requested_domains": ",".join(requested_domains),
                "context_count": len(result["context"]),
                "hindsight_count": int(result["hindsight"].get("count") or 0),
                "hindsight_status": str(result["hindsight"].get("status") or ""),
                "hindsight_error_class": hindsight_error_class,
                "uncertainty_count": len(result["uncertainties"]),
                "query_length": len(query),
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
                "latency_ms": int(result["latency_ms"]),
            }
        )
    except Exception:
        pass


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
