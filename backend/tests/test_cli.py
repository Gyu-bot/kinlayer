import json

from typer.testing import CliRunner

from kinlayer_backend import cli


class DummyResponse:
    def __init__(self, status_code: int, payload: dict, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self) -> dict:
        return self._payload


def test_status_json_reports_api_health(monkeypatch) -> None:
    def fake_get(url, headers, timeout):
        return DummyResponse(200, {"database": "ok", "embedding": "disabled"})

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    result = CliRunner().invoke(cli.app, ["status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["api"] == "ok"
    assert payload["database"] == "ok"


def test_init_json_posts_protected_self(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(
            201,
            {
                "id": "self-id",
                "entity_type": "person",
                "display_name": json["display_name"],
                "system_role": "self",
                "is_system": True,
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cli.app, ["init", "--self-name", "Me", "--json"])

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/entities")
    assert calls[0][1]["system_role"] == "self"
    assert json.loads(result.stdout)["system_role"] == "self"


def test_person_create_posts_entity_and_aliases(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        if url.endswith("/api/entities"):
            return DummyResponse(201, {"id": "entity-id", **json})
        return DummyResponse(201, {"id": "alias-id", **json})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(
        cli.app,
        [
            "person",
            "create",
            "--name",
            "Alex",
            "--alias",
            "알렉스",
            "--note",
            "Met through work",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/entities")
    assert calls[0][1]["entity_type"] == "person"
    assert calls[0][1]["properties"]["short_note"] == "Met through work"
    assert calls[1][0].endswith("/api/entities/entity-id/aliases")


def test_person_resolve_posts_agent_resolution_payload(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(
            200,
            {
                "surface": "알렉스",
                "ambiguity": "single_strong_match",
                "matches": [
                    {
                        "entity_id": "entity-id",
                        "display_name": "Alex Kim",
                        "score": 1.0,
                        "match_reasons": ["exact_alias"],
                    }
                ],
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(
        cli.app,
        [
            "person",
            "resolve",
            "알렉스",
            "--alias",
            "Alex",
            "--relation-hint",
            "coworker",
            "--entity-type",
            "person",
            "--source-kind",
            "agent",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/entities/resolve")
    assert calls[0][1] == {
        "surface": "알렉스",
        "aliases": ["Alex"],
        "relation_hint": "coworker",
        "entity_type": "person",
        "source": {"kind": "agent"},
    }
    assert json.loads(result.stdout)["matches"][0]["entity_id"] == "entity-id"


def test_embedding_status_cli_reads_api(monkeypatch) -> None:
    def fake_get(url, headers, timeout):
        return DummyResponse(200, {"provider": "disabled", "status": "disabled"})

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    result = CliRunner().invoke(cli.app, ["embedding", "status", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["provider"] == "disabled"


def test_embedding_backfill_cli_posts_api(monkeypatch) -> None:
    def fake_post(url, headers, json, timeout):
        assert url.endswith("/api/embeddings/backfill")
        return DummyResponse(200, {"processed": 1})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cli.app, ["embedding", "backfill", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["processed"] == 1


def test_candidate_submit_reads_json_file_and_posts_api(tmp_path, monkeypatch) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_payload = {
        "candidate_type": "observation",
        "payload": {
            "subject_entity_id": "entity-id",
            "observation_type": "recent_interaction",
            "content": "Alex followed up.",
            "claim_type": "fact",
        },
        "confidence": 0.8,
        "created_by": "ai_agent",
    }
    candidate_path.write_text(json.dumps(candidate_payload))
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return DummyResponse(201, {"id": "candidate-id", "status": "pending", **json})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cli.app, ["candidate", "submit", str(candidate_path), "--json"])

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/candidates")
    assert calls[0][2] == candidate_payload
    assert json.loads(result.stdout)["id"] == "candidate-id"


def test_candidate_list_and_show_support_json_output(monkeypatch) -> None:
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        if "/api/candidates/" in url:
            return DummyResponse(200, {"id": "candidate-id", "status": "pending"})
        return DummyResponse(200, {"items": [{"id": "candidate-id"}], "total": 1})

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    listed = CliRunner().invoke(cli.app, ["candidate", "list", "--status", "pending", "--json"])
    shown = CliRunner().invoke(cli.app, ["candidate", "show", "candidate-id", "--json"])

    assert listed.exit_code == 0
    assert shown.exit_code == 0
    assert "status=pending" in calls[0]
    assert calls[1].endswith("/api/candidates/candidate-id")
    assert json.loads(shown.stdout)["id"] == "candidate-id"


def test_candidate_actions_call_matching_endpoints_and_report_canonical_ref(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(
            200,
            {
                "id": "candidate-id",
                "status": "accepted",
                "canonical_record_ref": "observations:record-id",
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    accepted = CliRunner().invoke(cli.app, ["candidate", "accept", "candidate-id", "--json"])
    rejected = CliRunner().invoke(
        cli.app,
        ["candidate", "reject", "candidate-id", "--resolution-note", "Nope", "--json"],
    )
    archived = CliRunner().invoke(cli.app, ["candidate", "archive", "candidate-id", "--json"])
    clarified = CliRunner().invoke(cli.app, ["candidate", "clarify", "candidate-id", "--json"])

    assert accepted.exit_code == 0
    assert rejected.exit_code == 0
    assert archived.exit_code == 0
    assert clarified.exit_code == 0
    assert calls[0][0].endswith("/api/candidates/candidate-id/accept")
    assert calls[1][0].endswith("/api/candidates/candidate-id/reject")
    assert calls[1][1]["resolution_note"] == "Nope"
    assert calls[2][0].endswith("/api/candidates/candidate-id/archive")
    assert calls[3][0].endswith("/api/candidates/candidate-id/needs-clarification")
    assert json.loads(accepted.stdout)["canonical_record_ref"] == "observations:record-id"


def test_candidate_edit_accept_and_supersede_post_payloads(tmp_path, monkeypatch) -> None:
    edit_path = tmp_path / "edited.json"
    edit_path.write_text(json.dumps({"content": "Edited", "claim_type": "fact"}))
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(200, {"id": "candidate-id", "canonical_record_ref": "observations:id"})

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    edit = CliRunner().invoke(
        cli.app,
        [
            "candidate",
            "edit-accept",
            "candidate-id",
            str(edit_path),
            "--resolution-note",
            "Edited",
            "--json",
        ],
    )
    supersede = CliRunner().invoke(
        cli.app,
        [
            "candidate",
            "supersede",
            "candidate-id",
            "--supersedes-candidate-id",
            "new-candidate-id",
            "--json",
        ],
    )

    assert edit.exit_code == 0
    assert supersede.exit_code == 0
    assert calls[0][0].endswith("/api/candidates/candidate-id/edit-accept")
    assert calls[0][1]["payload"] == {"content": "Edited", "claim_type": "fact"}
    assert calls[0][1]["resolution_note"] == "Edited"
    assert calls[1][0].endswith("/api/candidates/candidate-id/supersede")
    assert calls[1][1]["supersedes_candidate_id"] == "new-candidate-id"


def test_correction_apply_reads_json_file_and_cli_uses_api_token(tmp_path, monkeypatch) -> None:
    correction_path = tmp_path / "correction.json"
    correction_payload = {
        "old_record_ref": "entity_edges:old",
        "new_record": {"record_type": "entity_edges", "payload": {}},
        "correction_source": {
            "source_type": "agent_conversation",
            "user_explicit": True,
            "excerpt": "No, this is corrected.",
        },
        "created_by": "ai_agent",
    }
    correction_path.write_text(json.dumps(correction_payload))
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return DummyResponse(200, {"new_record_ref": "entity_edges:new"})

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    monkeypatch.setenv("KINLAYER_API_TOKEN", "secret-token")

    result = CliRunner().invoke(cli.app, ["correction", "apply", str(correction_path), "--json"])

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/corrections/apply")
    assert calls[0][1]["Authorization"] == "Bearer secret-token"
    assert calls[0][2] == correction_payload
    assert json.loads(result.stdout)["new_record_ref"] == "entity_edges:new"


def test_agent_operations_cli_lists_and_exports_write_operations(monkeypatch) -> None:
    calls = []
    jsonl = (
        '{"record_type":"manifest","schema_version":"agent_write_operations.v1"}\n'
        '{"record_type":"agent_write_operation","operation_type":"candidate_submit"}\n'
    )

    def fake_get(url, headers, timeout):
        calls.append(url)
        if url.endswith("/api/agent-operations/export?limit=25"):
            return DummyResponse(200, {}, text=jsonl)
        return DummyResponse(
            200,
            {
                "items": [
                    {
                        "id": "audit-id",
                        "operation_type": "candidate_submit",
                        "result_status": "success",
                        "actor": "ai_agent",
                    }
                ],
                "limit": 50,
                "offset": 0,
                "total": 1,
            },
        )

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    listed = CliRunner().invoke(cli.app, ["agent-operations", "list", "--json"])
    exported = CliRunner().invoke(
        cli.app,
        ["agent-operations", "export", "--limit", "25"],
    )

    assert listed.exit_code == 0
    assert exported.exit_code == 0
    assert calls[0].endswith("/api/agent-operations")
    assert calls[1].endswith("/api/agent-operations/export?limit=25")
    assert json.loads(listed.stdout)["items"][0]["id"] == "audit-id"
    assert "agent_write_operation" in exported.stdout


def test_ontology_cli_reads_edge_type_diagnostics(monkeypatch) -> None:
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return DummyResponse(
            200,
            {
                "relation_types": [
                    {
                        "relation_type": "reply_strategy",
                        "exists_in_allowed_edge_types": False,
                        "active_edge_count": 1,
                    }
                ],
                "invalid_edges": [{"edge_id": "edge-id", "relation_type": "reply_strategy"}],
            },
        )

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    result = CliRunner().invoke(cli.app, ["ontology", "edge-diagnostics", "--json"])

    assert result.exit_code == 0
    assert calls[0].endswith("/api/ontology/edge-type-diagnostics")
    assert json.loads(result.stdout)["invalid_edges"][0]["edge_id"] == "edge-id"


def test_retrieve_cli_calls_context_retrieve_and_supports_json(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json))
        return DummyResponse(
            200,
            {
                "matched_entities": [{"entity_id": "entity-id", "score": 0.8}],
                "debug": {},
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    monkeypatch.setenv("KINLAYER_API_TOKEN", "secret-token")

    result = CliRunner().invoke(
        cli.app,
        ["retrieve", "Alex concise updates", "--entity-hint", "entity-id", "--json"],
    )

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/context/retrieve")
    assert calls[0][1]["Authorization"] == "Bearer secret-token"
    assert calls[0][2]["query"] == "Alex concise updates"
    assert calls[0][2]["entity_hints"] == ["entity-id"]
    assert json.loads(result.stdout)["matched_entities"][0]["entity_id"] == "entity-id"


def test_context_card_cli_calls_context_card_endpoint(monkeypatch) -> None:
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers))
        return DummyResponse(
            200,
            {
                "entity": {"id": "entity-id", "display_name": "Alex"},
                "aliases": [],
                "profile_facts": [],
                "relationship_edges": [],
                "stable_context": [],
                "recent_context": [],
                "communication_context": [],
                "cautions": [],
                "provenance_summary": {"evidence_count": 0},
                "retrieval_hints": {"entity_id": "entity-id", "aliases": []},
            },
        )

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    result = CliRunner().invoke(cli.app, ["context-card", "entity-id", "--json"])

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/entities/entity-id/context-card")
    assert json.loads(result.stdout)["entity"]["id"] == "entity-id"


def test_context_pack_cli_calls_context_pack(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(
            200,
            {
                "context_pack": {
                    "confidence": "medium",
                    "suggested_response_policy": "conditional_use",
                    "matched_entities": [],
                    "buckets": {},
                },
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(
        cli.app,
        ["context", "pack", "Alex concise updates", "--focal-entity-id", "self-id", "--json"],
    )

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/context/pack")
    assert calls[0][1]["query"] == "Alex concise updates"
    assert calls[0][1]["focal_entity_id"] == "self-id"
    assert json.loads(result.stdout)["context_pack"]["suggested_response_policy"] == "conditional_use"


def test_debug_retrieval_cli_forces_debug_metadata(monkeypatch) -> None:
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return DummyResponse(
            200,
            {
                "matched_entities": [],
                "score_breakdown": {"entity-id": {"alias_name": 0.2}},
                "debug": {"score_weights": {"alias_name": 0.2}},
            },
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cli.app, ["debug", "retrieval", "Alex", "--json"])

    assert result.exit_code == 0
    assert calls[0][0].endswith("/api/context/retrieve")
    assert calls[0][1]["include_debug"] is True
    payload = json.loads(result.stdout)
    assert payload["debug"]["score_weights"]["alias_name"] == 0.2
    assert "score_breakdown" in payload


def test_graph_ego_cli_reads_graph_endpoint(monkeypatch) -> None:
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return DummyResponse(
            200,
            {
                "focal_entity_id": "self-id",
                "nodes": [{"entity_id": "self-id", "display_name": "Self"}],
                "edges": [],
            },
        )

    monkeypatch.setattr(cli.httpx, "get", fake_get)

    result = CliRunner().invoke(
        cli.app,
        [
            "graph",
            "ego",
            "self-id",
            "--relation-type",
            "client_contact",
            "--sensitivity",
            "medium",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert calls[0].endswith(
        "/api/graph/ego/self-id?depth=1&relation_type=client_contact&status=active&sensitivity=medium"
    )
    assert json.loads(result.stdout)["focal_entity_id"] == "self-id"
