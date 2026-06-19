#!/usr/bin/env python3
"""Deterministic Kinlayer read/debug helper for local agents."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
Transport = Callable[..., dict[str, Any]]


class ClientError(Exception):
    def __init__(self, error: str, message: str, path: str, status_code: int | None = None):
        super().__init__(message)
        self.error = error
        self.message = message
        self.path = path
        self.status_code = status_code

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": self.error,
            "message": self.message,
            "path": self.path,
        }
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def _base_url() -> str:
    for key in ("KINLAYER_API_BASE_URL", "KINLAYER_API_URL"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip().rstrip("/")
    config_url = _hermes_config_base_url()
    if config_url:
        return config_url.rstrip("/")
    return DEFAULT_BASE_URL


def _hermes_config_base_url() -> str | None:
    inline = os.environ.get("HERMES_RUNTIME_CONTEXT_ROUTER")
    if inline:
        value = _base_url_from_config_text(inline)
        if value:
            return value
    for key in ("HERMES_RUNTIME_CONTEXT_ROUTER_PATH", "RUNTIME_CONTEXT_ROUTER_PATH"):
        path = os.environ.get(key)
        if not path:
            continue
        try:
            value = _base_url_from_config_text(open(path, encoding="utf-8").read())
        except OSError:
            continue
        if value:
            return value
    return None


def _base_url_from_config_text(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    router = payload.get("runtime_context_router", payload)
    if not isinstance(router, dict):
        return None
    kinlayer = router.get("kinlayer")
    if not isinstance(kinlayer, dict):
        return None
    base_url = kinlayer.get("base_url")
    return base_url if isinstance(base_url, str) and base_url.strip() else None


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = os.environ.get("KINLAYER_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _query_path(path: str, params: list[tuple[str, Any]]) -> str:
    clean_params = [(key, value) for key, value in params if value is not None]
    if not clean_params:
        return path
    return f"{path}?{urllib.parse.urlencode(clean_params)}"


def http_json_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 5,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        path = urllib.parse.urlsplit(url).path
        raise ClientError("http_error", f"Kinlayer API returned HTTP {exc.code}", path, exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        path = urllib.parse.urlsplit(url).path
        if isinstance(exc, TimeoutError):
            raise ClientError("timeout", "Timed out connecting to Kinlayer API", path)
        raise ClientError("connection_failed", "Could not connect to Kinlayer API", path)
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        path = urllib.parse.urlsplit(url).path
        raise ClientError("invalid_json", "Kinlayer API returned invalid JSON", path) from exc
    if not isinstance(payload, dict):
        path = urllib.parse.urlsplit(url).path
        raise ClientError("invalid_json", "Kinlayer API JSON response must be an object", path)
    return payload


def request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    transport: Transport = http_json_transport,
) -> dict[str, Any]:
    body = None
    headers = _headers()
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    try:
        return transport(method, _url(_base_url(), path), headers=headers, body=body, timeout=5)
    except ClientError:
        raise
    except TimeoutError:
        raise ClientError("timeout", "Timed out connecting to Kinlayer API", path)
    except OSError:
        raise ClientError("connection_failed", "Could not connect to Kinlayer API", path)


def compact_health(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": payload.get("status") == "ok",
        "service": "kinlayer",
        "health": payload.get("status", "unknown"),
        "database": payload.get("database", "unknown"),
        "embedding": payload.get("embedding", "unknown"),
    }


def compact_version(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "service": payload.get("name", "kinlayer"),
        "version": payload.get("version"),
        "api_version": payload.get("api_version"),
    }


def compact_entities(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "total": payload.get("total", len(payload.get("items", []))),
        "items": [
            {
                "id": item.get("id"),
                "display_name": item.get("display_name"),
                "entity_type": item.get("entity_type"),
                "aliases": _aliases(item),
            }
            for item in payload.get("items", [])
        ],
    }


def _aliases(item: dict[str, Any]) -> list[Any]:
    aliases = item.get("aliases", [])
    if not isinstance(aliases, list):
        return []
    return [
        alias.get("alias", alias.get("value")) if isinstance(alias, dict) else alias
        for alias in aliases
    ]


def compact_context_card(payload: dict[str, Any]) -> dict[str, Any]:
    sections = [
        "aliases",
        "profile_facts",
        "relationship_edges",
        "stable_context",
        "recent_context",
        "communication_context",
        "cautions",
    ]
    return {
        "ok": True,
        "entity": payload.get("entity", {}),
        "counts": {section: len(payload.get(section, []) or []) for section in sections},
        "summary": {
            section: [_compact_observation(item) for item in payload.get(section, [])]
            for section in (
                "stable_context",
                "recent_context",
                "communication_context",
                "cautions",
            )
        },
    }


def compact_observations(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "total": payload.get("total", len(payload.get("items", []))),
        "items": [_compact_observation(item) for item in payload.get("items", [])],
    }


def _compact_observation(item: dict[str, Any]) -> dict[str, Any]:
    related = item.get("related_entities", [])
    related_ids = [
        related_item.get("entity_id")
        for related_item in related
        if isinstance(related_item, dict) and related_item.get("entity_id")
    ]
    return {
        key: value
        for key, value in {
            "id": item.get("id") or item.get("observation_id"),
            "subject_entity_id": item.get("subject_entity_id"),
            "related_entity_ids": related_ids,
            "observation_type": item.get("observation_type"),
            "claim_type": item.get("claim_type"),
            "content": item.get("content"),
            "sensitivity": item.get("sensitivity"),
            "ai_use_policy": item.get("ai_use_policy"),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
        }.items()
        if value not in (None, [], {})
    }


def compact_candidate(item: dict[str, Any]) -> dict[str, Any]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "candidate_type": item.get("candidate_type"),
        "target_entity_id": item.get("target_entity_id"),
        "canonical_record_ref": item.get("canonical_record_ref"),
        "payload_keys": sorted(payload.keys()),
    }


def compact_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "total": payload.get("total", len(payload.get("items", []))),
        "items": [compact_candidate(item) for item in payload.get("items", [])],
    }


def compact_retrieve(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "matched_entities": [
            _compact_matched_entity(item) for item in payload.get("matched_entities", [])
        ],
        "observations": [_compact_observation(item) for item in payload.get("observations", [])],
        "scores": payload.get("scores", {}),
        "match_reasons": payload.get("match_reasons", {}),
        "score_breakdown": payload.get("score_breakdown", {}),
        "ambiguity_detected": bool(payload.get("ambiguity_detected", False)),
        "debug_present": bool(payload.get("debug")),
    }


def compact_pack(payload: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("context_pack", {})
    return {
        "ok": True,
        "context_pack": {
            "matched_entities": [
                _compact_matched_entity(item) for item in pack.get("matched_entities", [])
            ],
            "confidence": pack.get("confidence"),
            "suggested_response_policy": pack.get("suggested_response_policy"),
            "ambiguity_detected": bool(pack.get("ambiguity_detected", False)),
            "buckets": {
                bucket: [_compact_matched_entity(item) for item in items]
                for bucket, items in pack.get("buckets", {}).items()
            },
            "stable_context": [
                _compact_observation(item) for item in pack.get("stable_context", [])
            ],
            "recent_context": [
                _compact_observation(item) for item in pack.get("recent_context", [])
            ],
            "cautions": [_compact_observation(item) for item in pack.get("cautions", [])],
            "provenance": [_compact_provenance(item) for item in pack.get("provenance", [])],
        },
        "debug_present": bool(payload.get("debug")),
    }


def _compact_matched_entity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "entity_id": item.get("entity_id"),
            "display_name": item.get("display_name"),
            "entity_type": item.get("entity_type"),
            "score": item.get("score"),
            "confidence_band": item.get("confidence_band"),
            "match_reasons": item.get("match_reasons"),
            "score_breakdown": item.get("score_breakdown"),
            "surface_bucket": item.get("surface_bucket"),
            "sensitivity": item.get("sensitivity"),
            "ai_use_policy": item.get("ai_use_policy"),
            "confirmation_status": item.get("confirmation_status"),
        }.items()
        if value not in (None, [], {})
    }


def _compact_provenance(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "record_type": item.get("record_type"),
            "record_id": item.get("record_id"),
            "episode_id": item.get("episode_id"),
            "confidence": item.get("confidence"),
            "created_at": item.get("created_at"),
        }.items()
        if value is not None
    }


def compact_ontology(payload: dict[str, Any]) -> dict[str, Any]:
    counts = {key: len(value) for key, value in payload.items() if isinstance(value, list)}
    return {"ok": True, "counts": counts, "keys": sorted(payload.keys())}


def compact_schema_summary(payload: dict[str, Any]) -> dict[str, Any]:
    groups = Counter()
    for path in payload.get("paths", {}):
        parts = [part for part in path.split("/") if part]
        group = parts[1] if len(parts) > 1 and parts[0] == "api" else parts[0] if parts else "root"
        groups[group] += 1
    schemas = payload.get("components", {}).get("schemas", {})
    important_models = sorted(
        name
        for name in schemas
        if name.endswith(("Read", "Response", "List")) and name != "ListResponse"
    )
    return {
        "ok": True,
        "endpoint_groups": dict(sorted(groups.items())),
        "important_response_models": important_models,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic Kinlayer read/debug helper. It never accepts candidates."
    )
    parser.add_argument("--raw", action="store_true", help="Emit the full API payload.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")
    subparsers.add_parser("version")
    subparsers.add_parser("ontology")
    subparsers.add_parser("schema-summary")

    entities = subparsers.add_parser("entities")
    entities.add_argument("--query", "--q", dest="query")
    entities.add_argument("--entity-type")
    entities.add_argument("--limit", type=int, default=10)

    context_card = subparsers.add_parser("context-card")
    context_card.add_argument("--entity-id", required=True)

    observations = subparsers.add_parser("observations")
    observations.add_argument("--subject-entity-id")
    observations.add_argument("--related-entity-id")
    observations.add_argument("--status", default="active")
    observations.add_argument("--limit", type=int, default=50)

    candidates = subparsers.add_parser("candidates")
    candidates.add_argument("--status", default="pending")
    candidates.add_argument("--target-entity-id")
    candidates.add_argument("--limit", type=int, default=50)

    candidate = subparsers.add_parser("candidate")
    candidate.add_argument("--id", required=True, dest="candidate_id")

    retrieve = subparsers.add_parser("retrieve")
    _add_context_args(retrieve)
    retrieve.add_argument("--include-debug", action="store_true")

    pack = subparsers.add_parser("pack")
    _add_context_args(pack)
    pack.add_argument("--situation")

    return parser


def _add_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True)
    parser.add_argument("--hint", action="append", default=[])
    parser.add_argument("--focal-entity-id")
    parser.add_argument("--limit", type=int, default=10)


def run(argv: list[str] | None = None, *, transport: Transport = http_json_transport) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _dispatch(args, transport)
    except ClientError as exc:
        _emit(exc.to_payload())
        return 1
    _emit(payload)
    return 0


def _dispatch(args: argparse.Namespace, transport: Transport) -> dict[str, Any]:
    command = args.command
    if command == "health":
        payload = request("GET", "/api/system/health", transport=transport)
        return payload if args.raw else compact_health(payload)
    if command == "version":
        payload = request("GET", "/api/system/version", transport=transport)
        return payload if args.raw else compact_version(payload)
    if command == "ontology":
        payload = request("GET", "/api/ontology", transport=transport)
        return payload if args.raw else compact_ontology(payload)
    if command == "schema-summary":
        payload = request("GET", "/openapi.json", transport=transport)
        return payload if args.raw else compact_schema_summary(payload)
    if command == "entities":
        path = _query_path(
            "/api/entities",
            [("q", args.query), ("entity_type", args.entity_type), ("limit", args.limit)],
        )
        payload = request("GET", path, transport=transport)
        return payload if args.raw else compact_entities(payload)
    if command == "context-card":
        path = f"/api/entities/{urllib.parse.quote(args.entity_id, safe='')}/context-card"
        payload = request("GET", path, transport=transport)
        return payload if args.raw else compact_context_card(payload)
    if command == "observations":
        path = _query_path(
            "/api/observations",
            [
                ("subject_entity_id", args.subject_entity_id),
                ("related_entity_id", args.related_entity_id),
                ("status", args.status),
                ("limit", args.limit),
            ],
        )
        payload = request("GET", path, transport=transport)
        return payload if args.raw else compact_observations(payload)
    if command == "candidates":
        path = _query_path(
            "/api/candidates",
            [
                ("status", args.status),
                ("target_entity_id", args.target_entity_id),
                ("limit", args.limit),
            ],
        )
        payload = request("GET", path, transport=transport)
        return payload if args.raw else compact_candidates(payload)
    if command == "candidate":
        path = f"/api/candidates/{urllib.parse.quote(args.candidate_id, safe='')}"
        payload = request("GET", path, transport=transport)
        return payload if args.raw else compact_candidate(payload)
    if command == "retrieve":
        payload = request(
            "POST",
            "/api/context/retrieve",
            payload=_context_payload(args),
            transport=transport,
        )
        return payload if args.raw else compact_retrieve(payload)
    if command == "pack":
        body = _context_payload(args)
        if args.situation:
            body["situation"] = args.situation
        payload = request("POST", "/api/context/pack", payload=body, transport=transport)
        return payload if args.raw else compact_pack(payload)
    raise ClientError("unknown_command", f"Unsupported command: {command}", "")


def _context_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": args.query,
        "entity_hints": args.hint,
        "limit": args.limit,
    }
    if args.focal_entity_id:
        payload["focal_entity_id"] = args.focal_entity_id
    if hasattr(args, "include_debug"):
        payload["include_debug"] = bool(args.include_debug)
    return payload


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
