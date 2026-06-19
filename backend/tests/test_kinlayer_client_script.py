import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "kinlayer_client.py"


def load_client_module():
    spec = importlib.util.spec_from_file_location("kinlayer_client", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, url, *, headers=None, body=None, timeout=5):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers or {},
                "body": json.loads(body.decode("utf-8")) if body else None,
                "timeout": timeout,
            }
        )
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def run_cli(module, argv, monkeypatch, responses, env_url="http://kinlayer.local:8765"):
    transport = FakeTransport(responses)
    monkeypatch.setenv("KINLAYER_API_BASE_URL", env_url)
    monkeypatch.delenv("KINLAYER_API_TOKEN", raising=False)
    exit_code = module.run(argv, transport=transport)
    return exit_code, transport


def json_stdout(capsys):
    return json.loads(capsys.readouterr().out)


def test_health_and_version_emit_compact_json_without_base_url(monkeypatch, capsys):
    module = load_client_module()

    exit_code, transport = run_cli(
        module,
        ["health"],
        monkeypatch,
        [{"status": "ok", "database": "ok", "embedding": "disabled"}],
    )

    assert exit_code == 0
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"] == "http://kinlayer.local:8765/api/system/health"
    assert json_stdout(capsys) == {
        "ok": True,
        "service": "kinlayer",
        "health": "ok",
        "database": "ok",
        "embedding": "disabled",
    }

    exit_code, transport = run_cli(
        module,
        ["version"],
        monkeypatch,
        [{"name": "kinlayer", "version": "0.1.0", "api_version": "v1"}],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith("/api/system/version")
    assert json_stdout(capsys) == {
        "ok": True,
        "service": "kinlayer",
        "version": "0.1.0",
        "api_version": "v1",
    }


def test_entities_uses_query_filters_and_compacts_results(monkeypatch, capsys):
    module = load_client_module()

    exit_code, transport = run_cli(
        module,
        ["entities", "--query", "Jordan Kim", "--entity-type", "person", "--limit", "10"],
        monkeypatch,
        [
            {
                "total": 1,
                "items": [
                    {
                        "id": "person_jordan",
                        "display_name": "Jordan Kim",
                        "entity_type": "person",
                        "aliases": ["Jordan"],
                        "sensitivity": "medium",
                    }
                ],
            }
        ],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith(
        "/api/entities?q=Jordan+Kim&entity_type=person&limit=10"
    )
    assert json_stdout(capsys) == {
        "ok": True,
        "total": 1,
        "items": [
            {
                "id": "person_jordan",
                "display_name": "Jordan Kim",
                "entity_type": "person",
                "aliases": ["Jordan"],
            }
        ],
    }


def test_context_card_compact_counts_and_raw_dump(monkeypatch, capsys):
    module = load_client_module()
    card = {
        "entity": {"id": "person_jordan", "display_name": "Jordan Kim", "entity_type": "person"},
        "aliases": [{"alias": "Jordan"}],
        "profile_facts": [{"fact_type": "role"}],
        "relationship_edges": [],
        "stable_context": [{"id": "obs_stable", "content": "Prefers concise notes."}],
        "recent_context": [],
        "communication_context": [{"id": "obs_comm", "content": "Use email."}],
        "cautions": [],
    }

    exit_code, _ = run_cli(
        module,
        ["context-card", "--entity-id", "person_jordan"],
        monkeypatch,
        [card],
    )

    assert exit_code == 0
    compact = json_stdout(capsys)
    assert compact["counts"] == {
        "aliases": 1,
        "profile_facts": 1,
        "relationship_edges": 0,
        "stable_context": 1,
        "recent_context": 0,
        "communication_context": 1,
        "cautions": 0,
    }
    assert compact["summary"]["stable_context"][0]["id"] == "obs_stable"

    exit_code, _ = run_cli(
        module,
        ["--raw", "context-card", "--entity-id", "person_jordan"],
        monkeypatch,
        [card],
    )

    assert exit_code == 0
    assert json_stdout(capsys) == card


def test_observations_use_subject_and_related_filters(monkeypatch, capsys):
    module = load_client_module()

    exit_code, transport = run_cli(
        module,
        [
            "observations",
            "--subject-entity-id",
            "person_jordan",
            "--related-entity-id",
            "person_lee",
            "--status",
            "active",
            "--limit",
            "50",
        ],
        monkeypatch,
        [
            {
                "total": 1,
                "items": [
                    {
                        "id": "obs_1",
                        "subject_entity_id": "person_jordan",
                        "related_entities": [{"entity_id": "person_lee", "role": "related"}],
                        "observation_type": "communication_preference",
                        "claim_type": "fact",
                        "content": "Prefers bullets.",
                        "sensitivity": "medium",
                        "ai_use_policy": "cautious_use",
                        "created_at": "2026-06-18T00:00:00Z",
                        "updated_at": "2026-06-18T00:00:00Z",
                    }
                ],
            }
        ],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith(
        "/api/observations?subject_entity_id=person_jordan&related_entity_id=person_lee&status=active&limit=50"
    )
    item = json_stdout(capsys)["items"][0]
    assert item["related_entity_ids"] == ["person_lee"]
    assert item["content"] == "Prefers bullets."


def test_candidates_hide_payload_by_default_and_detail_uses_id_path(monkeypatch, capsys):
    module = load_client_module()
    candidate = {
        "id": "cand_1",
        "status": "pending",
        "candidate_type": "observation",
        "target_entity_id": "person_jordan",
        "canonical_record_ref": None,
        "payload": {"subject_entity_id": "person_jordan", "content": "Sensitive full text."},
    }

    exit_code, transport = run_cli(
        module,
        ["candidates", "--target-entity-id", "person_jordan", "--status", "pending"],
        monkeypatch,
        [{"total": 1, "items": [candidate]}],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith(
        "/api/candidates?status=pending&target_entity_id=person_jordan&limit=50"
    )
    compact = json_stdout(capsys)
    assert compact["items"][0]["payload_keys"] == ["content", "subject_entity_id"]
    assert "payload" not in compact["items"][0]

    exit_code, transport = run_cli(
        module,
        ["candidate", "--id", "cand_1"],
        monkeypatch,
        [candidate],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith("/api/candidates/cand_1")
    assert "payload" not in json_stdout(capsys)


def test_retrieve_and_pack_post_compact_payloads(monkeypatch, capsys):
    module = load_client_module()
    matched_entity = {
        "entity_id": "person_jordan",
        "display_name": "Jordan",
        "entity_type": "person",
        "score": 0.92,
        "confidence_band": "high",
        "match_reasons": ["exact_alias"],
        "score_breakdown": {"alias": 0.7, "semantic_observation": 0.22},
        "penalties": {},
        "surface_bucket": "direct_surface",
        "sensitivity": "medium",
        "ai_use_policy": "cautious_use",
        "confirmation_status": "confirmed",
        "profile_facts": [],
        "observations": [],
    }
    retrieved_observation = {
        "observation_id": "obs_1",
        "content": "Use email.",
        "score": 0.8,
        "match_reasons": ["semantic_observation"],
        "sensitivity": "medium",
        "ai_use_policy": "cautious_use",
        "status": "active",
        "created_at": "2026-06-18T00:00:00Z",
    }

    exit_code, transport = run_cli(
        module,
        [
            "retrieve",
            "--query",
            "relationship context",
            "--hint",
            "Jordan",
            "--hint",
            "Lee",
            "--focal-entity-id",
            "person_jordan",
            "--limit",
            "10",
            "--include-debug",
        ],
        monkeypatch,
        [
            {
                "matched_entities": [matched_entity],
                "observations": [retrieved_observation],
                "scores": {"person_jordan": 0.92},
                "match_reasons": {"person_jordan": ["exact_alias"]},
                "score_breakdown": {"person_jordan": {"alias": 0.7, "semantic_observation": 0.22}},
                "ambiguity_detected": False,
                "debug": {},
            }
        ],
    )

    assert exit_code == 0
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith("/api/context/retrieve")
    assert transport.calls[0]["body"] == {
        "query": "relationship context",
        "entity_hints": ["Jordan", "Lee"],
        "focal_entity_id": "person_jordan",
        "limit": 10,
        "include_debug": True,
    }
    compact = json_stdout(capsys)
    assert compact["ambiguity_detected"] is False
    assert compact["scores"] == {"person_jordan": 0.92}
    assert compact["match_reasons"] == {"person_jordan": ["exact_alias"]}
    assert compact["score_breakdown"]["person_jordan"]["semantic_observation"] == 0.22
    assert compact["matched_entities"][0]["surface_bucket"] == "direct_surface"
    assert compact["observations"][0]["id"] == "obs_1"
    assert compact["debug_present"] is False
    assert "debug" not in compact

    exit_code, transport = run_cli(
        module,
        [
            "pack",
            "--query",
            "draft reply",
            "--hint",
            "Jordan",
            "--situation",
            "message reply",
        ],
        monkeypatch,
        [
            {
                "context_pack": {
                    "matched_entities": [matched_entity],
                    "buckets": {
                        "direct_surface": [matched_entity],
                        "conditional_surface": [],
                        "internal_only": [],
                        "blocked": [],
                    },
                    "recent_context": [retrieved_observation],
                    "stable_context": [],
                    "cautions": [],
                    "provenance": [
                        {
                            "record_type": "observation",
                            "record_id": "obs_1",
                            "episode_id": "episode_1",
                            "excerpt": "Use email.",
                            "confidence": 0.9,
                        }
                    ],
                    "suggested_response_policy": "cautious_use",
                    "confidence": "medium",
                    "ambiguity_detected": False,
                },
                "debug": {"raw": True},
            }
        ],
    )

    assert exit_code == 0
    assert transport.calls[0]["url"].endswith("/api/context/pack")
    assert transport.calls[0]["body"]["situation"] == "message reply"
    compact_pack = json_stdout(capsys)
    assert compact_pack["context_pack"]["ambiguity_detected"] is False
    assert compact_pack["context_pack"]["buckets"]["direct_surface"][0]["entity_id"] == (
        "person_jordan"
    )
    assert compact_pack["context_pack"]["recent_context"][0]["id"] == "obs_1"
    assert compact_pack["context_pack"]["provenance"][0]["record_id"] == "obs_1"
    assert compact_pack["debug_present"] is True


def test_token_header_is_sent_but_not_printed(monkeypatch, capsys):
    module = load_client_module()
    transport = FakeTransport([{"status": "ok", "database": "ok", "embedding": "disabled"}])
    monkeypatch.setenv("KINLAYER_API_BASE_URL", "http://kinlayer.local:8765")
    monkeypatch.setenv("KINLAYER_API_TOKEN", "secret-token")

    exit_code = module.run(["health"], transport=transport)

    assert exit_code == 0
    assert transport.calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    output = capsys.readouterr().out
    assert "secret-token" not in output
    assert "kinlayer.local" not in output


def test_schema_summary_groups_openapi_paths_and_raw_dumps_full_payload(monkeypatch, capsys):
    module = load_client_module()
    openapi = {
        "paths": {
            "/api/entities": {"get": {"operationId": "list_entities"}},
            "/api/entities/{entity_id}": {"get": {"operationId": "get_entity"}},
            "/api/context/retrieve": {"post": {"operationId": "retrieve_context"}},
        },
        "components": {
            "schemas": {
                "EntityRead": {},
                "ContextRetrieveResponse": {},
                "Ignored": {},
            }
        },
    }

    exit_code, _ = run_cli(module, ["schema-summary"], monkeypatch, [openapi])

    assert exit_code == 0
    assert json_stdout(capsys) == {
        "ok": True,
        "endpoint_groups": {"context": 1, "entities": 2},
        "important_response_models": ["ContextRetrieveResponse", "EntityRead"],
    }

    exit_code, _ = run_cli(module, ["--raw", "schema-summary"], monkeypatch, [openapi])

    assert exit_code == 0
    assert json_stdout(capsys) == openapi


def test_connection_failure_returns_structured_json(monkeypatch, capsys):
    module = load_client_module()

    exit_code, transport = run_cli(
        module,
        ["health"],
        monkeypatch,
        [OSError("refused")],
    )

    assert exit_code == 1
    assert transport.calls[0]["url"].endswith("/api/system/health")
    assert json_stdout(capsys) == {
        "ok": False,
        "error": "connection_failed",
        "message": "Could not connect to Kinlayer API",
        "path": "/api/system/health",
    }
