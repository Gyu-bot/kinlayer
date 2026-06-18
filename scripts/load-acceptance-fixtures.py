#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


class ApiClient:
    def __init__(self, api_url: str, token: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.token = token or ""

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read().decode()
        except urllib.error.HTTPError as exc:
            data = exc.read().decode()
            raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {data}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc}") from exc
        return json.loads(data) if data else {}

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", path, payload)


def query(params: dict[str, str | int]) -> str:
    return urllib.parse.urlencode(params)


def content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def ensure_self(client: ApiClient) -> dict[str, Any]:
    payload = {
        "entity_type": "person",
        "display_name": "Self",
        "created_by": "system",
        "system_role": "self",
        "is_system": True,
        "confirmation_status": "confirmed",
        "sensitivity": "medium",
        "ai_use_policy": "cautious_use",
    }
    try:
        return client.post("/api/entities", payload)
    except RuntimeError as exc:
        if "HTTP 409" not in str(exc):
            raise
    result = client.get("/api/entities?entity_type=person&system_role=self&limit=1")
    return result["items"][0]


def ensure_person(
    client: ApiClient,
    display_name: str,
    aliases: list[str],
    *,
    sensitivity: str = "medium",
    ai_use_policy: str = "cautious_use",
    note: str = "",
) -> dict[str, Any]:
    result = client.get(
        "/api/entities?"
        + query({"entity_type": "person", "q": display_name, "limit": 50})
    )
    for item in result["items"]:
        if normalize(item["display_name"]) == normalize(display_name):
            entity = item
            break
    else:
        entity = client.post(
            "/api/entities",
            {
                "entity_type": "person",
                "display_name": display_name,
                "properties": {"acceptance_fixture": True, "note": note},
                "confirmation_status": "confirmed",
                "sensitivity": sensitivity,
                "ai_use_policy": ai_use_policy,
                "created_by": "user",
            },
        )
    existing_aliases = client.get(f"/api/entities/{entity['id']}/aliases")["items"]
    existing_names = {normalize(item["alias"]) for item in existing_aliases}
    for alias in aliases:
        if normalize(alias) not in existing_names:
            client.post(
                f"/api/entities/{entity['id']}/aliases",
                {"alias": alias, "created_by": "user", "confidence": 1},
            )
    return entity


def ensure_fact(client: ApiClient, entity_id: str, fact_type: str, content: str) -> dict[str, Any]:
    result = client.get(
        "/api/entity-facts?"
        + query({"entity_id": entity_id, "fact_type": fact_type, "status": "active", "limit": 100})
    )
    for item in result["items"]:
        if item["content"] == content:
            return item
    return client.post(
        "/api/entity-facts",
        {
            "entity_id": entity_id,
            "fact_type": fact_type,
            "content": content,
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )


def ensure_edge(
    client: ApiClient,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    claim_text: str,
) -> dict[str, Any]:
    result = client.get(
        "/api/edges?"
        + query(
            {
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "relation_type": relation_type,
                "status": "active",
                "limit": 100,
            }
        )
    )
    for item in result["items"]:
        if item["claim_text"] == claim_text:
            return item
    return client.post(
        "/api/edges",
        {
            "from_entity_id": from_entity_id,
            "to_entity_id": to_entity_id,
            "relation_type": relation_type,
            "claim_text": claim_text,
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )


def ensure_observation(
    client: ApiClient,
    subject_entity_id: str,
    observation_type: str,
    content: str,
    *,
    related_entity_ids: list[str] | None = None,
    sensitivity: str = "medium",
    ai_use_policy: str = "cautious_use",
    recency_weight: float = 1,
) -> dict[str, Any]:
    result = client.get(
        "/api/observations?"
        + query(
            {
                "subject_entity_id": subject_entity_id,
                "observation_type": observation_type,
                "status": "active",
                "limit": 100,
            }
        )
    )
    for item in result["items"]:
        if item["content"] == content:
            return item
    return client.post(
        "/api/observations",
        {
            "subject_entity_id": subject_entity_id,
            "related_entities": [
                {"entity_id": entity_id, "role": "related"} for entity_id in (related_entity_ids or [])
            ],
            "observation_type": observation_type,
            "content": content,
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": sensitivity,
            "ai_use_policy": ai_use_policy,
            "recency_weight": recency_weight,
            "created_by": "user",
        },
    )


def create_episode(client: ApiClient, source_ref: str, excerpt: str, actor: str = "ai_agent") -> dict[str, Any]:
    return client.post(
        "/api/episodes",
        {
            "source_type": "agent_conversation",
            "source_ref": source_ref,
            "source_description": "Acceptance fixture episode",
            "body_excerpt": excerpt,
            "body_hash": content_hash(excerpt),
            "actor": actor,
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )


def create_candidate(
    client: ApiClient,
    candidate_type: str,
    target_entity_id: str,
    payload: dict[str, Any],
    episode: dict[str, Any],
    *,
    sensitivity: str = "medium",
) -> dict[str, Any]:
    return client.post(
        "/api/candidates",
        {
            "candidate_type": candidate_type,
            "target_entity_id": target_entity_id,
            "payload": payload,
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": episode["body_excerpt"],
                    "confidence": 0.95,
                }
            ],
            "confidence": 0.92,
            "sensitivity": sensitivity,
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )


def load_fixtures(client: ApiClient) -> dict[str, Any]:
    self_entity = ensure_self(client)
    alex = ensure_person(
        client,
        "Acceptance Alex",
        ["Alex Fixture", "알렉스"],
        note="Acceptance fixture contact.",
    )
    minji = ensure_person(
        client,
        "Acceptance Minji",
        ["민지", "Minji Fixture"],
        note="Acceptance fixture Korean semantic retrieval contact.",
    )

    alex_fact = ensure_fact(client, alex["id"], "contact_note", "Prefers concise written updates before calls.")
    minji_fact = ensure_fact(client, minji["id"], "role", "Launch planning collaborator.")
    alex_edge = ensure_edge(
        client,
        self_entity["id"],
        alex["id"],
        "client_contact",
        "Acceptance Alex is a client contact for local smoke verification.",
    )
    minji_edge = ensure_edge(
        client,
        self_entity["id"],
        minji["id"],
        "friend",
        "Acceptance Minji is a trusted friend for Korean retrieval smoke verification.",
    )
    korean_observation = ensure_observation(
        client,
        minji["id"],
        "follow_up_context",
        "민지는 회의 전에 핵심 쟁점을 한국어로 먼저 정리하면 답장이 빠르다.",
        related_entity_ids=[self_entity["id"]],
    )
    never_surface_observation = ensure_observation(
        client,
        alex["id"],
        "caution",
        "Acceptance sensitive detail should never be placed in direct_surface.",
        related_entity_ids=[self_entity["id"]],
        sensitivity="high",
        ai_use_policy="never_surface",
        recency_weight=0.2,
    )

    accepted_episode = create_episode(
        client,
        "acceptance-fixture-accepted-candidate",
        "민지는 회의 전에 핵심 쟁점을 한국어로 먼저 정리하면 답장이 빠르다고 말했다.",
    )
    accepted_candidate = create_candidate(
        client,
        "observation",
        minji["id"],
        {
            "subject_entity_id": minji["id"],
            "related_entity_ids": [self_entity["id"]],
            "observation_type": "recent_interaction",
            "content": "민지는 다음 회의 전 한국어 요약을 먼저 받으면 빠르게 확인한다.",
            "claim_type": "fact",
            "ai_use_policy": "cautious_use",
            "sensitivity": "medium",
        },
        accepted_episode,
    )
    accepted_candidate = client.post(f"/api/candidates/{accepted_candidate['id']}/accept", {})

    pending_episode = create_episode(
        client,
        "acceptance-fixture-pending-candidate",
        "Alex may prefer weekly async summaries; this should remain pending for review.",
    )
    pending_candidate = create_candidate(
        client,
        "observation",
        alex["id"],
        {
            "subject_entity_id": alex["id"],
            "related_entity_ids": [self_entity["id"]],
            "observation_type": "communication_preference",
            "content": "Acceptance Alex may prefer weekly async summaries.",
            "claim_type": "inference",
            "ai_use_policy": "cautious_use",
            "sensitivity": "medium",
        },
        pending_episode,
    )

    old_observation = ensure_observation(
        client,
        alex["id"],
        "communication_preference",
        "Acceptance Alex prefers long phone calls for all updates.",
        related_entity_ids=[self_entity["id"]],
    )
    correction = client.post(
        "/api/corrections/apply",
        {
            "old_record_ref": f"observations:{old_observation['id']}",
            "new_record": {
                "record_type": "observations",
                "payload": {
                    "subject_entity_id": alex["id"],
                    "related_entity_ids": [self_entity["id"]],
                    "observation_type": "communication_preference",
                    "content": "Acceptance Alex prefers concise async written updates before calls.",
                    "claim_type": "fact",
                    "confidence": 1,
                    "sensitivity": "medium",
                    "ai_use_policy": "cautious_use",
                    "recency_weight": 1,
                },
            },
            "correction_source": {
                "source_type": "agent_conversation",
                "source_actor": "user",
                "user_explicit": True,
                "excerpt": "Correction: Alex prefers concise async written updates before calls.",
                "source_ref": "acceptance-fixture-correction",
            },
            "created_by": "ai_agent",
        },
    )

    return {
        "self_id": self_entity["id"],
        "people": {"alex": alex["id"], "minji": minji["id"]},
        "facts": {"alex": alex_fact["id"], "minji": minji_fact["id"]},
        "edges": {"alex": alex_edge["id"], "minji": minji_edge["id"]},
        "observations": {
            "korean_semantic": korean_observation["id"],
            "sensitive_never_surface": never_surface_observation["id"],
            "corrected_old": old_observation["id"],
        },
        "episodes": {
            "accepted_candidate": accepted_episode["id"],
            "pending_candidate": pending_episode["id"],
            "correction": correction["episode_id"],
        },
        "candidates": {
            "accepted": accepted_candidate["id"],
            "pending": pending_candidate["id"],
        },
        "accepted_canonical_record_ref": accepted_candidate["canonical_record_ref"],
        "correction": correction,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Load deterministic Kinlayer acceptance fixtures.")
    parser.add_argument("--api-url", default=os.getenv("KINLAYER_API_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.getenv("KINLAYER_API_TOKEN", ""))
    args = parser.parse_args()

    try:
        result = load_fixtures(ApiClient(args.api_url, args.token))
    except Exception as exc:
        print(f"Fixture load failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
