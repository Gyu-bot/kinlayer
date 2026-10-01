#!/usr/bin/env python3
"""Deterministic, read-only Kinlayer helper for local agents."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
HERMES_BASE_URL_KEY = "runtime_context_router.kinlayer.base_url"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
Transport = Callable[..., dict[str, Any]]


class ClientError(Exception):
    def __init__(
        self,
        error: str,
        message: str,
        path: str = "",
        status_code: int | None = None,
    ) -> None:
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
        }
        if self.path:
            payload["path"] = self.path
        if self.status_code is not None:
            payload["status_code"] = self.status_code
        return payload


def _emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class JSONArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        _emit(
            {
                "ok": False,
                "error": "argument_error",
                "message": "Invalid command arguments.",
            }
        )
        raise SystemExit(2)


def resolve_base_url() -> str:
    configured = os.environ.get("KINLAYER_API_BASE_URL", "").strip()
    if configured:
        return _normalize_base_url(configured)
    configured = _hermes_base_url()
    if configured:
        try:
            return _normalize_base_url(configured)
        except ClientError:
            pass
    return _normalize_base_url(DEFAULT_BASE_URL)


def _hermes_base_url() -> str | None:
    executable = shutil.which("hermes")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "config", "get", HERMES_BASE_URL_KEY, "--json"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_base_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        valid_port = parsed.port is None or 0 < parsed.port < 65536
    except ValueError as exc:
        raise ClientError("invalid_base_url", "Kinlayer base URL is invalid.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not valid_port
        or any(character.isspace() for character in value)
    ):
        raise ClientError("invalid_base_url", "Kinlayer base URL is invalid.")
    return value.rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = os.environ.get("KINLAYER_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _query_path(path: str, params: list[tuple[str, Any]]) -> str:
    query = urllib.parse.urlencode([(key, value) for key, value in params if value is not None])
    return f"{path}?{query}" if query else path


def http_json_transport(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: int = 5,
) -> dict[str, Any]:
    headers = headers or {}
    request = urllib.request.Request(
        url,
        data=body,
        headers={key: value for key, value in headers.items() if key.lower() != "authorization"},
        method=method,
    )
    authorization = next(
        (value for key, value in headers.items() if key.lower() == "authorization"),
        None,
    )
    if authorization:
        request.add_unredirected_header("Authorization", authorization)
    path = urllib.parse.urlsplit(url).path
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error = "not_found" if exc.code == 404 else "http_error"
        message = (
            "Kinlayer resource was not found."
            if exc.code == 404
            else f"Kinlayer API returned HTTP {exc.code}."
        )
        raise ClientError(error, message, path, exc.code) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ClientError("timeout", "Timed out connecting to Kinlayer API.", path) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ClientError("timeout", "Timed out connecting to Kinlayer API.", path) from exc
        raise ClientError("connection_failed", "Could not connect to Kinlayer API.", path) from exc
    except OSError as exc:
        raise ClientError("connection_failed", "Could not connect to Kinlayer API.", path) from exc
    except UnicodeDecodeError as exc:
        raise ClientError("invalid_json", "Kinlayer API returned invalid JSON.", path) from exc
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise ClientError("invalid_json", "Kinlayer API returned invalid JSON.", path) from exc
    if not isinstance(payload, dict):
        raise ClientError("invalid_json", "Kinlayer API JSON must be an object.", path)
    return payload


def request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    transport: Transport = http_json_transport,
) -> dict[str, Any]:
    headers = _headers()
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    try:
        return transport(
            method,
            f"{resolve_base_url()}/{path.lstrip('/')}",
            headers=headers,
            body=body,
            timeout=5,
        )
    except ClientError:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise ClientError("timeout", "Timed out connecting to Kinlayer API.", path) from exc
    except OSError as exc:
        raise ClientError("connection_failed", "Could not connect to Kinlayer API.", path) from exc


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
    keys = (
        "id",
        "display_name",
        "canonical_name",
        "entity_type",
        "status",
        "confirmation_status",
        "system_role",
    )
    return _compact_list(payload, [_pick(item, keys) for item in payload.get("items", [])])


def compact_context_card(payload: dict[str, Any]) -> dict[str, Any]:
    sections = (
        "aliases",
        "profile_facts",
        "relationship_edges",
        "stable_context",
        "recent_context",
        "communication_context",
        "cautions",
        "provisional_context",
    )
    return {
        "ok": True,
        "entity": _pick(payload.get("entity", {}), ("id", "display_name", "entity_type")),
        "counts": {section: len(payload.get(section, []) or []) for section in sections},
        "profile_facts": [_compact_fact(item) for item in payload.get("profile_facts", [])],
        "relationship_edges": [_compact_edge(item) for item in payload.get("relationship_edges", [])],
        "provenance_summary": {
            **_pick(
                payload.get("provenance_summary", {}),
                ("fact_count", "edge_count", "observation_count", "evidence_count"),
            ),
            "evidence": [
                _compact_provenance(item)
                for item in payload.get("provenance_summary", {}).get("evidence", [])
            ],
        },
        "summary": {
            section: [_compact_observation(item) for item in payload.get(section, [])]
            for section in (
                "stable_context",
                "recent_context",
                "communication_context",
                "cautions",
            )
        },
        "provisional_context": [
            _compact_provisional(item) for item in payload.get("provisional_context", [])
        ],
    }


def compact_observations(payload: dict[str, Any]) -> dict[str, Any]:
    return _compact_list(
        payload,
        [_compact_observation(item) for item in payload.get("items", [])],
    )


def _compact_observation(item: dict[str, Any]) -> dict[str, Any]:
    related_ids = [
        related["entity_id"]
        for related in item.get("related_entities", [])
        if isinstance(related, dict) and related.get("entity_id")
    ]
    result = _pick(
        item,
        (
            "subject_entity_id",
            "observation_type",
            "claim_basis",
            "confidence",
            "content",
            "score",
            "match_reasons",
            "status",
            "valid_from",
            "valid_to",
            "occurred_at",
            "created_at",
            "updated_at",
        ),
    )
    result["id"] = item.get("id") or item.get("observation_id")
    if "related_entities" in item:
        result["related_entities"] = [
            _pick(related, ("entity_id", "role", "confidence"))
            for related in item["related_entities"]
            if isinstance(related, dict) and related.get("entity_id")
        ]
    if related_ids:
        result["related_entity_ids"] = related_ids
    return {key: value for key, value in result.items() if value is not None}


def _compact_fact(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item,
        (
            "id", "entity_id", "fact_type", "content", "value", "claim_basis", "confidence",
            "status", "valid_from", "valid_to", "created_at", "updated_at",
        ),
    )


def _compact_edge(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item,
        (
            "id", "from_entity_id", "to_entity_id", "relation_type", "directed", "claim_text",
            "properties", "claim_basis", "confidence", "status", "valid_from", "valid_to",
            "first_seen_at", "last_seen_at", "created_at", "updated_at",
        ),
    )


def _compact_provenance(item: dict[str, Any]) -> dict[str, Any]:
    # Source statement time and actor must not be inferred from record metadata.
    return _pick(
        item,
        (
            "record_type", "record_id", "episode_id", "actor", "source_type", "source_ref",
            "source_occurred_at", "excerpt", "confidence", "created_at",
        ),
    )


def compact_candidate(item: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    candidate = _pick(
        item,
        (
            "id",
            "status",
            "candidate_type",
            "target_entity_id",
            "confidence",
            "suggested_action",
            "canonical_record_ref",
            "created_at",
            "updated_at",
            "resolved_at",
        ),
    )
    raw_payload = item.get("payload")
    candidate["payload_keys"] = sorted(raw_payload) if isinstance(raw_payload, dict) else []
    if detail:
        candidate["evidence_count"] = len(item.get("evidence", []) or [])
    return candidate


def compact_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    return _compact_list(
        payload,
        [compact_candidate(item) for item in payload.get("items", [])],
    )


def compact_retrieve(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "matched_entities": [
            _compact_matched_entity(item) for item in payload.get("matched_entities", [])
        ],
        "observations": [_compact_observation(item) for item in payload.get("observations", [])],
        "provenance": [_compact_provenance(item) for item in payload.get("provenance", [])],
        "scores": payload.get("scores", {}),
        "match_reasons": payload.get("match_reasons", {}),
        "score_breakdown": payload.get("score_breakdown", {}),
        "ambiguity_detected": bool(payload.get("ambiguity_detected")),
        "debug_present": bool(payload.get("debug")),
    }


def compact_pack(payload: dict[str, Any]) -> dict[str, Any]:
    pack = payload.get("context_pack", {})
    return {
        "ok": True,
        "context_pack": {
            "confidence": pack.get("confidence"),
            "suggested_response_policy": pack.get("suggested_response_policy"),
            "ambiguity_detected": bool(pack.get("ambiguity_detected")),
            "matched_entities": [
                _compact_matched_entity(item) for item in pack.get("matched_entities", [])
            ],
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
            "provisional_context": [
                _compact_provisional(item) for item in pack.get("provisional_context", [])
            ],
            "provenance": [
                _compact_provenance(item) for item in pack.get("provenance", [])
            ],
        },
        "debug_present": bool(payload.get("debug")),
    }


def _compact_matched_entity(item: dict[str, Any]) -> dict[str, Any]:
    result = _pick(
        item,
        (
            "entity_id",
            "display_name",
            "entity_type",
            "score",
            "confidence_band",
            "match_reasons",
            "score_breakdown",
            "penalties",
            "surface_bucket",
        ),
    )
    if "profile_facts" in item:
        result["profile_facts"] = [_compact_fact(fact) for fact in item["profile_facts"]]
    if "observations" in item:
        result["observations"] = [_compact_observation(obs) for obs in item["observations"]]
    return result


def _compact_provisional(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(
        item,
        ("candidate_id", "content", "observation_type", "review_status"),
    )


def compact_ontology(payload: dict[str, Any]) -> dict[str, Any]:
    values = {
        "entity_types": _values(payload.get("entity_types", []), "value"),
        "fact_types": _values(payload.get("fact_types", []), "value"),
        "edge_types": _values(payload.get("edge_types", []), "relation_type"),
        "observation_types": _values(payload.get("observation_types", []), "observation_type"),
    }
    for key, items in payload.get("policies", {}).items():
        values[key] = _values(items, "value")
    return {
        "ok": True,
        "counts": {key: len(items) for key, items in values.items()},
        "values": values,
    }


def compact_schema_summary(payload: dict[str, Any]) -> dict[str, Any]:
    groups: Counter[str] = Counter()
    for path, path_item in payload.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or [_path_group(path)]
            for tag in tags:
                groups[str(tag)] += 1
    schemas = payload.get("components", {}).get("schemas", {})
    models = sorted(
        name
        for name in schemas
        if name.endswith(("Read", "Response", "List")) and name != "ListResponse"
    )
    return {
        "ok": True,
        "endpoint_groups": dict(sorted(groups.items())),
        "important_response_models": models,
    }


def _compact_list(payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "ok": True,
        "total": payload.get("total", len(items)),
        "limit": payload.get("limit"),
        "offset": payload.get("offset"),
        "items": items,
    }


def _pick(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: item[key] for key in keys if key in item and item[key] is not None}


def _values(items: Any, key: str) -> list[str]:
    if not isinstance(items, list):
        return []
    return sorted(
        item[key] for item in items if isinstance(item, dict) and isinstance(item.get(key), str)
    )


def _path_group(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    return parts[1] if len(parts) > 1 and parts[0] == "api" else parts[0] if parts else "root"


def _limit(maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        number = int(value)
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError("limit out of range")
        return number

    return parse


def _nonnegative(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("offset out of range")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = JSONArgumentParser(
        description="Deterministic, read-only Kinlayer helper. It cannot accept candidates or write records."
    )
    parser.add_argument("--raw", action="store_true", help="Emit the full API payload.")
    raw_parent = argparse.ArgumentParser(add_help=False)
    raw_parent.add_argument("--raw", action="store_true", default=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def command(name: str) -> argparse.ArgumentParser:
        return subparsers.add_parser(name, parents=[raw_parent])

    command("health")
    command("version")
    command("ontology")
    command("schema-summary")

    entities = command("entities")
    entities.add_argument("--query", "--q", dest="query")
    entities.add_argument("--entity-type")
    entities.add_argument("--status")
    entities.add_argument("--system-role")
    entities.add_argument("--limit", type=_limit(200), default=50)
    entities.add_argument("--offset", type=_nonnegative, default=0)

    context_card = command("context-card")
    context_card.add_argument("--entity-id", required=True)
    context_card.add_argument("--include-provisional", action="store_true")

    observations = command("observations")
    observations.add_argument("--subject-entity-id")
    observations.add_argument("--related-entity-id")
    observations.add_argument("--observation-type")
    observations.add_argument("--status")
    observations.add_argument("--claim-type")
    observations.add_argument("--limit", type=_limit(200), default=50)
    observations.add_argument("--offset", type=_nonnegative, default=0)

    candidates = command("candidates")
    candidates.add_argument("--status")
    candidates.add_argument("--candidate-type")
    candidates.add_argument("--target-entity-id")
    candidates.add_argument("--limit", type=_limit(200), default=50)
    candidates.add_argument("--offset", type=_nonnegative, default=0)

    candidate = command("candidate")
    candidate.add_argument("--id", required=True, dest="candidate_id")

    retrieve = command("retrieve")
    _add_context_args(retrieve)

    pack = command("pack")
    _add_context_args(pack)
    pack.add_argument("--situation")
    pack.add_argument("--include-provisional", action="store_true")
    return parser


def _add_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True)
    parser.add_argument("--hint", action="append", default=[])
    parser.add_argument("--focal-entity-id")
    parser.add_argument("--include-debug", action="store_true")
    parser.add_argument("--limit", type=_limit(50), default=10)


def run(argv: list[str] | None = None, *, transport: Transport = http_json_transport) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _dispatch(args, transport)
    except ClientError as exc:
        _emit(exc.to_payload())
        return 1
    _emit(payload)
    if args.command == "health":
        status = payload.get("status") if args.raw else payload.get("health")
        return 0 if status == "ok" else 1
    return 0


def _dispatch(args: argparse.Namespace, transport: Transport) -> dict[str, Any]:
    if args.command == "health":
        return _get(args, "/api/system/health", compact_health, transport)
    if args.command == "version":
        return _get(args, "/api/system/version", compact_version, transport)
    if args.command == "ontology":
        return _get(args, "/api/ontology", compact_ontology, transport)
    if args.command == "schema-summary":
        return _get(args, "/openapi.json", compact_schema_summary, transport)
    if args.command == "entities":
        path = _query_path(
            "/api/entities",
            [
                ("q", args.query),
                ("entity_type", args.entity_type),
                ("status", args.status),
                ("system_role", args.system_role),
                ("limit", args.limit),
                ("offset", args.offset),
            ],
        )
        return _get(args, path, compact_entities, transport)
    if args.command == "context-card":
        entity_id = urllib.parse.quote(args.entity_id, safe="")
        path = _query_path(
            f"/api/entities/{entity_id}/context-card",
            [("include_provisional", str(args.include_provisional).lower())],
        )
        return _get(args, path, compact_context_card, transport)
    if args.command == "observations":
        path = _query_path(
            "/api/observations",
            [
                ("subject_entity_id", args.subject_entity_id),
                ("related_entity_id", args.related_entity_id),
                ("observation_type", args.observation_type),
                ("status", args.status),
                ("claim_type", args.claim_type),
                ("limit", args.limit),
                ("offset", args.offset),
            ],
        )
        return _get(args, path, compact_observations, transport)
    if args.command == "candidates":
        path = _query_path(
            "/api/candidates",
            [
                ("status", args.status),
                ("candidate_type", args.candidate_type),
                ("target_entity_id", args.target_entity_id),
                ("limit", args.limit),
                ("offset", args.offset),
            ],
        )
        return _get(args, path, compact_candidates, transport)
    if args.command == "candidate":
        candidate_id = urllib.parse.quote(args.candidate_id, safe="")
        payload = request("GET", f"/api/candidates/{candidate_id}", transport=transport)
        return payload if args.raw else {"ok": True, **compact_candidate(payload, detail=True)}
    body = _context_payload(args)
    if args.command == "pack":
        if args.situation:
            body["situation"] = args.situation
        body["include_provisional"] = args.include_provisional
    path = f"/api/context/{args.command}"
    payload = request("POST", path, payload=body, transport=transport)
    if args.raw:
        return payload
    return compact_retrieve(payload) if args.command == "retrieve" else compact_pack(payload)


def _get(
    args: argparse.Namespace,
    path: str,
    normalize: Callable[[dict[str, Any]], dict[str, Any]],
    transport: Transport,
) -> dict[str, Any]:
    payload = request("GET", path, transport=transport)
    return payload if args.raw else normalize(payload)


def _context_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": args.query,
        "entity_hints": args.hint,
        "include_debug": args.include_debug,
        "limit": args.limit,
    }
    if args.focal_entity_id:
        payload["focal_entity_id"] = args.focal_entity_id
    return payload


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
