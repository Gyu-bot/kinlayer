#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class SmokeClient:
    def __init__(self, api_url: str, token: str | None = None):
        self.api_url = api_url.rstrip("/")
        self.token = token or ""

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read().decode()
        except urllib.error.HTTPError as exc:
            data = exc.read().decode()
            raise AssertionError(f"{method} {path} failed: HTTP {exc.code} {data}") from exc
        return json.loads(data) if data else {}

    def status(self, method: str, path: str, payload: dict[str, Any] | None = None) -> int:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{self.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def text(self, path: str) -> str:
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.api_url}{path}", headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read().decode()
        except urllib.error.HTTPError as exc:
            data = exc.read().decode()
            raise AssertionError(f"GET {path} failed: HTTP {exc.code} {data}") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", path, payload)

    def patch(self, path: str, payload: dict[str, Any]) -> Any:
        return self.request("PATCH", path, payload)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


def q(params: dict[str, str | int]) -> str:
    return urllib.parse.urlencode(params)


def body_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_fixtures(api_url: str, token: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "load-acceptance-fixtures.py"),
        "--api-url",
        api_url,
    ]
    if token:
        command.extend(["--token", token])
    output = subprocess.check_output(command, text=True, cwd=ROOT)
    return json.loads(output)


def episode(client: SmokeClient, ref: str, excerpt: str) -> dict[str, Any]:
    return client.post(
        "/api/episodes",
        {
            "source_type": "agent_conversation",
            "source_ref": ref,
            "source_description": "Acceptance API smoke",
            "body_excerpt": excerpt,
            "body_hash": body_hash(excerpt),
            "actor": "ai_agent",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )


def observation_candidate(
    client: SmokeClient,
    target_id: str,
    related_id: str,
    content: str,
    source_ref: str,
) -> dict[str, Any]:
    source = episode(client, source_ref, content)
    return client.post(
        "/api/candidates",
        {
            "candidate_type": "observation",
            "target_entity_id": target_id,
            "payload": {
                "subject_entity_id": target_id,
                "related_entity_ids": [related_id],
                "observation_type": "recent_interaction",
                "content": content,
                "claim_type": "fact",
                "ai_use_policy": "cautious_use",
                "sensitivity": "medium",
            },
            "evidence": [{"episode_id": source["id"], "excerpt": content, "confidence": 0.9}],
            "confidence": 0.9,
            "sensitivity": "medium",
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )


def profile_fact_candidate(
    client: SmokeClient,
    target_id: str,
    content: str,
    source_ref: str,
) -> dict[str, Any]:
    source = episode(client, source_ref, content)
    return client.post(
        "/api/candidates",
        {
            "candidate_type": "profile_field",
            "target_entity_id": target_id,
            "payload": {
                "entity_id": target_id,
                "field_path": "profile.email",
                "fact_type": "email",
                "content": content,
                "value": {"kind": "work", "email": content},
                "claim_type": "fact",
                "sensitivity": "high",
                "ai_use_policy": "ask_before_use",
            },
            "evidence": [{"episode_id": source["id"], "excerpt": content, "confidence": 0.9}],
            "confidence": 0.9,
            "sensitivity": "high",
            "suggested_action": "review",
            "created_by": "ai_agent",
        },
    )


def run_smoke(client: SmokeClient, fixtures: dict[str, Any]) -> dict[str, Any]:
    self_id = fixtures["self_id"]
    alex_id = fixtures["people"]["alex"]
    minji_id = fixtures["people"]["minji"]
    stamp = str(int(time.time()))

    assert_true(client.get("/api/system/health")["status"] == "ok", "system health failed")
    assert_true(client.get("/api/system/version")["name"] == "kinlayer", "system version failed")
    assert_true("embedding" in client.get("/api/system/config"), "system config missing embedding")

    entity = client.post(
        "/api/entities",
        {
            "entity_type": "person",
            "display_name": f"Acceptance Disposable {stamp}",
            "confirmation_status": "confirmed",
            "sensitivity": "low",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    entity = client.patch(f"/api/entities/{entity['id']}", {"display_name": f"Acceptance Disposable Patched {stamp}"})
    assert_true(client.get(f"/api/entities/{entity['id']}")["display_name"].endswith(stamp), "entity get/patch failed")

    alias = client.post(f"/api/entities/{entity['id']}/aliases", {"alias": f"Disposable Alias {stamp}", "created_by": "user"})
    alias = client.patch(f"/api/aliases/{alias['id']}", {"alias": f"Disposable Alias Patched {stamp}"})
    assert_true(client.get(f"/api/entities/{entity['id']}/aliases")["total"] >= 1, "alias list failed")
    client.delete(f"/api/aliases/{alias['id']}")

    fact = client.post(
        "/api/entity-facts",
        {
            "entity_id": entity["id"],
            "fact_type": "contact_note",
            "content": f"Disposable fact {stamp}",
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": "low",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    client.patch(f"/api/entity-facts/{fact['id']}", {"content": f"Disposable fact patched {stamp}"})
    assert_true(client.get(f"/api/entity-facts/{fact['id']}")["content"].endswith(stamp), "fact get/patch failed")
    client.delete(f"/api/entity-facts/{fact['id']}")

    edge = client.post(
        "/api/edges",
        {
            "from_entity_id": self_id,
            "to_entity_id": entity["id"],
            "relation_type": "knows",
            "claim_text": f"Disposable edge {stamp}",
            "claim_type": "fact",
            "confidence": 0.8,
            "sensitivity": "low",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    client.patch(f"/api/edges/{edge['id']}", {"confidence": 0.7})
    assert_true(client.get(f"/api/edges/{edge['id']}")["confidence"] == 0.7, "edge get/patch failed")
    client.delete(f"/api/edges/{edge['id']}")
    invalid_agent_edge_status = client.status(
        "POST",
        "/api/edges",
        {
            "from_entity_id": self_id,
            "to_entity_id": entity["id"],
            "relation_type": "reply_strategy",
            "claim_text": f"Invalid edge smoke {stamp}",
            "claim_type": "fact",
            "created_by": "ai_agent",
        },
    )
    assert_true(invalid_agent_edge_status == 422, "invalid relation type edge was not rejected")
    filter_episode = episode(client, f"agent-write-filter-{stamp}", f"Agent write filter smoke {stamp}")
    filter_result = client.post(
        "/api/agent-writes/validate",
        {
            "write_type": "candidate",
            "payload": {
                "candidate_type": "relationship_edge",
                "target_entity_id": entity["id"],
                "payload": {
                    "from_entity_id": self_id,
                    "to_entity_id": entity["id"],
                    "relation_type": "Former coworker",
                    "claim_text": f"Agent write filter smoke {stamp}",
                    "claim_type": "fact",
                },
                "evidence": [
                    {
                        "episode_id": filter_episode["id"],
                        "excerpt": f"Agent write filter smoke {stamp}",
                        "confidence": 0.9,
                    }
                ],
                "confidence": 0.9,
                "sensitivity": "medium",
                "created_by": "ai_agent",
            },
        },
    )
    assert_true(filter_result["accepted"] is True, "agent write dry-run did not accept valid payload")
    assert_true(
        filter_result["validated_payload"]["payload"]["relation_type"] == "former_coworker",
        "agent write dry-run did not normalize relation type",
    )
    edge_diagnostics = client.get("/api/ontology/edge-type-diagnostics")
    assert_true("relation_types" in edge_diagnostics, "edge diagnostics missing relation types")
    assert_true("invalid_edges" in edge_diagnostics, "edge diagnostics missing invalid edge list")

    observation = client.post(
        "/api/observations",
        {
            "subject_entity_id": entity["id"],
            "related_entities": [{"entity_id": self_id, "role": "related"}],
            "observation_type": "recent_interaction",
            "content": f"Disposable observation {stamp}",
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": "low",
            "ai_use_policy": "cautious_use",
            "created_by": "user",
        },
    )
    client.patch(f"/api/observations/{observation['id']}", {"content": f"Disposable observation patched {stamp}"})
    assert_true(client.get(f"/api/observations/{observation['id']}")["content"].endswith(stamp), "observation get/patch failed")
    client.delete(f"/api/observations/{observation['id']}")

    source_episode = episode(client, f"acceptance-api-smoke-{stamp}", f"API smoke episode {stamp}")
    assert_true(client.get(f"/api/episodes/{source_episode['id']}")["body_hash"].startswith("sha256:"), "episode get failed")
    assert_true(client.get("/api/episodes?source_type=agent_conversation")["total"] >= 1, "episode list failed")
    resolved_minji = client.post(
        "/api/entities/resolve",
        {
            "surface": "민지",
            "aliases": ["Minji Fixture"],
            "relation_hint": "회의 전 한국어 요약",
            "entity_type": "person",
            "source": {"kind": "agent"},
        },
    )
    assert_true(
        any(match["entity_id"] == minji_id for match in resolved_minji["matches"]),
        "entity resolve missed Minji",
    )
    unresolved_pronoun = client.post(
        "/api/entities/resolve",
        {
            "surface": "그 사람",
            "entity_type": "person",
            "source": {"kind": "agent"},
        },
    )
    assert_true(unresolved_pronoun["ambiguity"] == "no_match", "pronoun-only resolve should not match")
    assert_true(unresolved_pronoun["matches"] == [], "pronoun-only resolve returned matches")

    reject_candidate = observation_candidate(client, minji_id, self_id, f"Reject candidate smoke {stamp}", f"reject-{stamp}")
    archive_candidate = observation_candidate(client, minji_id, self_id, f"Archive candidate smoke {stamp}", f"archive-{stamp}")
    clarify_candidate = observation_candidate(client, minji_id, self_id, f"Clarify candidate smoke {stamp}", f"clarify-{stamp}")
    edit_candidate = observation_candidate(client, minji_id, self_id, f"Edit candidate smoke {stamp}", f"edit-{stamp}")
    delete_candidate = observation_candidate(client, minji_id, self_id, f"Delete candidate smoke {stamp}", f"delete-{stamp}")

    client.patch(reject_candidate_path := f"/api/candidates/{reject_candidate['id']}", {"suggested_action": "reject"})
    assert_true(client.get(reject_candidate_path)["suggested_action"] == "reject", "candidate get/patch failed")
    assert_true(client.post(f"/api/candidates/{reject_candidate['id']}/reject", {"resolution_note": "smoke"})["status"] == "rejected", "candidate reject failed")
    assert_true(client.post(f"/api/candidates/{archive_candidate['id']}/archive", {})["status"] == "archived", "candidate archive failed")
    assert_true(client.post(f"/api/candidates/{clarify_candidate['id']}/needs-clarification", {})["status"] == "needs_clarification", "candidate clarify failed")
    edited = client.post(
        f"/api/candidates/{edit_candidate['id']}/edit-accept",
        {
            "payload": {
                "subject_entity_id": minji_id,
                "related_entity_ids": [self_id],
                "observation_type": "recent_interaction",
                "content": f"Edited accepted candidate smoke {stamp}",
                "claim_type": "fact",
                "ai_use_policy": "cautious_use",
                "sensitivity": "medium",
            }
        },
    )
    assert_true(edited["canonical_record_ref"].startswith("observations:"), "candidate edit-accept canonical ref failed")
    assert_true(client.delete(f"/api/candidates/{delete_candidate['id']}")["status"] == "archived", "candidate delete/archive failed")

    post_turn_content = f"Post-turn accepted candidate smoke {stamp}"
    post_turn_candidate = observation_candidate(
        client,
        minji_id,
        self_id,
        post_turn_content,
        f"post-turn-candidate-{stamp}",
    )
    post_turn_detail = client.get(f"/api/candidates/{post_turn_candidate['id']}")
    assert_true(post_turn_detail["evidence"][0]["source_type"] == "agent_conversation", "candidate evidence source type missing")
    assert_true(post_turn_detail["evidence"][0]["source_ref"] == f"post-turn-candidate-{stamp}", "candidate evidence source ref missing")
    accepted_post_turn = client.post(f"/api/candidates/{post_turn_candidate['id']}/accept", {})
    assert_true(
        accepted_post_turn["canonical_record_ref"].startswith("observations:"),
        "post-turn candidate accept canonical ref failed",
    )
    accepted_post_turn_observation_id = accepted_post_turn["canonical_record_ref"].split(":", 1)[1]
    accepted_post_turn_observation = client.get(f"/api/observations/{accepted_post_turn_observation_id}")
    assert_true(
        accepted_post_turn_observation["source_candidate_id"] == post_turn_candidate["id"],
        "accepted candidate did not link canonical observation to candidate",
    )

    superseded = observation_candidate(client, minji_id, self_id, f"Superseded candidate smoke {stamp}", f"superseded-{stamp}")
    superseding = observation_candidate(client, minji_id, self_id, f"Superseding candidate smoke {stamp}", f"superseding-{stamp}")
    superseding_id = superseding["id"]
    assert_true(
        client.post(
            f"/api/candidates/{superseded['id']}/supersede",
            {"supersedes_candidate_id": superseding_id},
        )["supersedes_candidate_id"]
        == superseding_id,
        "candidate supersede failed",
    )

    profile_candidate = profile_fact_candidate(
        client,
        minji_id,
        f"acceptance-{stamp}@example.com",
        f"profile-fact-{stamp}",
    )
    accepted_profile = client.post(f"/api/candidates/{profile_candidate['id']}/accept", {})
    assert_true(
        accepted_profile["canonical_record_ref"].startswith("entity_facts:"),
        "profile fact candidate canonical ref failed",
    )
    profile_fact_id = accepted_profile["canonical_record_ref"].split(":", 1)[1]
    profile_fact = client.get(f"/api/entity-facts/{profile_fact_id}")
    assert_true(profile_fact["fact_type"] == "email", "profile fact candidate type not preserved")
    patched_profile_fact = client.patch(
        f"/api/entity-facts/{profile_fact_id}",
        {"content": f"acceptance-patched-{stamp}@example.com"},
    )
    assert_true(
        patched_profile_fact["content"] == f"acceptance-patched-{stamp}@example.com",
        "profile fact canonical patch failed",
    )

    correction = fixtures["correction"]
    assert_true(correction["new_record_ref"].startswith("observations:"), "correction apply fixture failed")
    assert_true(correction["source_actor"] == "user", "fixture correction source actor missing")
    assert_true(correction["submitted_by"] == "ai_agent", "fixture correction submitter missing")

    corrected_content = f"Post-turn corrected observation smoke {stamp}"
    explicit_correction = client.post(
        "/api/corrections/apply",
        {
            "old_record_ref": accepted_post_turn["canonical_record_ref"],
            "new_record": {
                "record_type": "observations",
                "payload": {
                    "subject_entity_id": minji_id,
                    "related_entity_ids": [self_id],
                    "observation_type": "recent_interaction",
                    "content": corrected_content,
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
                "excerpt": corrected_content,
                "source_ref": f"post-turn-correction-{stamp}",
            },
            "created_by": "ai_agent",
        },
    )
    assert_true(explicit_correction["source_actor"] == "user", "explicit correction source actor failed")
    assert_true(explicit_correction["submitted_by"] == "ai_agent", "explicit correction submitter failed")
    assert_true(
        client.get(f"/api/observations/{accepted_post_turn_observation_id}")["status"] == "superseded",
        "explicit correction did not supersede old observation",
    )

    agent_operations = client.get("/api/agent-operations?limit=50")
    assert_true(agent_operations["total"] >= 1, "agent write operation list missing records")
    assert_true(
        any(item["operation_type"].startswith("candidate_") for item in agent_operations["items"]),
        "agent write operation candidate records missing",
    )
    assert_true(
        any(
            item["operation_type"] == "edge_create" and item["result_status"] == "rejected"
            for item in agent_operations["items"]
        ),
        "agent write operation rejected edge create record missing",
    )
    agent_export = client.text("/api/agent-operations/export?limit=50")
    agent_export_lines = [json.loads(line) for line in agent_export.splitlines()]
    assert_true(agent_export_lines[0]["schema_version"] == "agent_write_operations.v1", "agent export manifest missing")
    assert_true(
        any(line.get("record_type") == "agent_write_operation" for line in agent_export_lines[1:]),
        "agent export records missing",
    )

    retrieved = client.post(
        "/api/context/retrieve",
        {
            "query": "민지 한국어 요약 회의 확인",
            "entity_hints": [minji_id],
            "focal_entity_id": self_id,
            "include_debug": True,
            "limit": 5,
        },
    )
    assert_true(any(item["entity_id"] == minji_id for item in retrieved["matched_entities"]), "context retrieve missed Minji")
    packed = client.post(
        "/api/context/pack",
        {
            "query": "민지 한국어 요약 회의 확인",
            "entity_hints": [minji_id],
            "focal_entity_id": self_id,
            "include_debug": True,
            "limit": 5,
        },
    )["context_pack"]
    packed_text = json.dumps(packed, ensure_ascii=False)
    assert_true("다음 회의 전 한국어 요약" in packed_text, "accepted canonical context missing from pack")
    assert_true("long phone calls" not in packed_text, "superseded correction context surfaced")
    assert_true("Reject candidate smoke" not in packed_text, "rejected candidate context surfaced")

    corrected_pack = client.post(
        "/api/context/pack",
        {
            "query": corrected_content,
            "entity_hints": [minji_id],
            "focal_entity_id": self_id,
            "include_debug": True,
            "limit": 5,
        },
    )["context_pack"]
    corrected_pack_text = json.dumps(corrected_pack, ensure_ascii=False)
    assert_true(corrected_content in corrected_pack_text, "explicit correction context missing from pack")
    assert_true(post_turn_content not in corrected_pack_text, "superseded post-turn context surfaced")

    sensitive_pack = client.post(
        "/api/context/pack",
        {
            "query": "Acceptance sensitive detail",
            "entity_hints": [alex_id],
            "focal_entity_id": self_id,
            "limit": 5,
        },
    )["context_pack"]
    direct_ids = {item["entity_id"] for item in sensitive_pack["buckets"]["direct_surface"]}
    assert_true(alex_id not in direct_ids, "never_surface context entered direct_surface")

    card = client.get(f"/api/entities/{minji_id}/context-card")
    assert_true(card["provenance_summary"]["evidence_count"] >= 1, "context card evidence missing")
    assert_true(fixtures["accepted_canonical_record_ref"].split(":", 1)[1] in json.dumps(card), "accepted evidence link missing")
    assert_true(profile_fact_id in json.dumps(card), "accepted profile fact missing from context card")

    graph = client.get(f"/api/graph/ego/{self_id}?depth=1")
    assert_true(len(graph["nodes"]) >= 3 and len(graph["edges"]) >= 2, "ego graph missing fixture nodes/edges")

    ontology = client.get("/api/ontology")
    assert_true("client_contact" in json.dumps(ontology), "ontology aggregate missing edge type")
    for path in ["/api/ontology/edge-types", "/api/ontology/observation-types", "/api/ontology/entity-fact-types", "/api/ontology/policies"]:
        assert_true(client.get(path), f"ontology route failed: {path}")

    embedding = client.get("/api/embeddings/status")
    assert_true("status" in embedding, "embedding status failed")
    assert_true("processed" in client.post("/api/embeddings/backfill?limit=10", {}), "embedding backfill failed")

    client.delete(f"/api/entities/{entity['id']}")
    return {
        "self_id": self_id,
        "alex_id": alex_id,
        "minji_id": minji_id,
        "accepted_canonical_record_ref": fixtures["accepted_canonical_record_ref"],
        "api_smoke": "ok",
    }


def run_token_boundary_smoke(api_url: str, token: str) -> dict[str, str]:
    anonymous = SmokeClient(api_url)
    authorized = SmokeClient(api_url, token)

    assert_true(anonymous.status("GET", "/api/system/health") == 200, "token mode health should remain public")
    assert_true(anonymous.status("GET", "/api/system/version") == 200, "token mode version should remain public")
    assert_true(anonymous.status("GET", "/api/entities") == 401, "token mode entities should reject anonymous reads")
    assert_true(authorized.status("GET", "/api/entities") == 200, "token mode entities should accept bearer token")
    return {"token_boundary": "ok"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Kinlayer acceptance API smoke.")
    parser.add_argument("--api-url", default=os.getenv("KINLAYER_API_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.getenv("KINLAYER_API_TOKEN", ""))
    args = parser.parse_args()
    token_boundary = run_token_boundary_smoke(args.api_url, args.token) if args.token else {}
    fixtures = load_fixtures(args.api_url, args.token)
    result = run_smoke(SmokeClient(args.api_url, args.token), fixtures)
    result.update(token_boundary)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
