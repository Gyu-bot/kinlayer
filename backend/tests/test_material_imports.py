"""Synthetic-only vertical contract; no live services or provider calls."""

import hashlib
import json
import copy
import importlib
import os
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner
from sqlalchemy import select, func

from kinlayer_backend import cli
from kinlayer_backend.models import Candidate, Episode, MaterialImport, Observation


def digest(value):
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
    )


def material_request(target):
    excerpt = "I prefer a short message before a call."
    sources = [
        {
            "source_id": "note-1",
            "kind": "user_supplied_document",
            "source_ref": "synthetic://document-1",
            "message_id": "paragraph-2",
            "author": "Synthetic Alice",
            "author_kind": "human",
            "occurred_at": "2026-09-01T10:00:00Z",
            "original_sha256": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
            "excerpt": excerpt,
            "excerpt_sha256": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
        }
    ]
    return {
        "idempotency_key": "synthetic-import-1",
        "target_entity_id": target,
        "sources": sources,
        "authorization": {
            "actor": "user",
            "user_explicit": True,
            "source_ref": "synthetic://user-turn-1",
            "message_id": "user-message-1",
            "occurred_at": "2026-09-30T01:00:00Z",
            "excerpt": "Save a sourced summary from this document about Synthetic Alice.",
            "target_entity_id": target,
            "source_ids": ["note-1"],
            "manifest_sha256": digest({"target_entity_id": target, "sources": sources}),
        },
        "claims": [
            {
                "source_ids": ["note-1"],
                "kind": "sourced_report",
                "observation_type": "communication_preference",
                "summary": "Prefers a short message before a call.",
                "confidence": 0.9,
                "ai_use_policy": "cautious_use",
            }
        ],
    }


def test_validate_is_read_only_and_submit_is_idempotent(client):
    client.app.state.settings.material_import_token = "synthetic-import-token"
    headers = {"Authorization": "Bearer synthetic-import-token"}
    target = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Synthetic Alice", "created_by": "user"},
    ).json()["id"]
    body = material_request(target)
    preview = client.post("/api/material-imports/validate", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    assert client.get("/api/candidates").json()["total"] == 0
    response = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["status"] == "submitted"
    replay = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["candidate_ids"] == receipt["candidate_ids"]
    assert client.get("/api/candidates").json()["total"] == 1
    candidate = client.get("/api/candidates/" + receipt["candidate_ids"][0]).json()
    assert candidate["status"] == "pending"
    assert candidate["evidence"][0]["actor"] == "Synthetic Alice"
    assert candidate["evidence"][0]["material_import_id"] == receipt["import_id"]
    assert candidate["payload"]["claim_type"] == "fact"
    assert "Source report" in candidate["payload"]["content"]
    body["claims"][0]["summary"] = "Changed content"
    assert (
        client.post("/api/material-imports/submit", json=body, headers=headers).status_code == 409
    )


@pytest.fixture
def staged(client):
    client.app.state.settings.material_import_token = "synthetic-import-token"
    client.app.state.settings.curation_mode = "apply"
    headers = {"Authorization": "Bearer synthetic-import-token"}
    target = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": "Synthetic Alice", "created_by": "user"},
    ).json()["id"]
    return client, headers, material_request(target)


def counts(client):
    with client.app.state.session_factory() as session:
        return {
            m.__tablename__: session.scalar(select(func.count()).select_from(m))
            for m in (MaterialImport, Episode, Candidate, Observation)
        }


def rebind(body):
    body["authorization"]["manifest_sha256"] = digest(
        {"target_entity_id": body["target_entity_id"], "sources": body["sources"]}
    )


@pytest.mark.parametrize(
    "case",
    [
        "no_authorization",
        "not_explicit",
        "assistant_authorization",
        "wrong_target",
        "unknown_target",
        "ambiguous_name",
        "out_of_scope",
        "assistant_source",
        "tool_result",
        "missing_message",
        "missing_date",
        "tampered_excerpt",
        "tampered_manifest",
        "self_authorizing",
        "extra_raw",
        "empty_excerpt",
        "duplicate_source",
    ],
)
def test_invalid_import_has_no_persistent_effect(staged, case):
    client, headers, body = staged
    if case == "no_authorization":
        body.pop("authorization")
    elif case == "not_explicit":
        body["authorization"]["user_explicit"] = False
    elif case == "assistant_authorization":
        body["authorization"]["actor"] = "assistant"
    elif case == "wrong_target":
        body["authorization"]["target_entity_id"] = "other-person"
    elif case in {"unknown_target", "ambiguous_name"}:
        body["target_entity_id"] = body["authorization"]["target_entity_id"] = (
            "missing-id" if case == "unknown_target" else "Synthetic Alice"
        )
        rebind(body)
    elif case == "out_of_scope":
        body["claims"][0]["source_ids"] = ["unapproved"]
    elif case == "assistant_source":
        body["sources"][0]["author"] = "assistant"
        rebind(body)
    elif case == "tool_result":
        body["sources"][0]["kind"] = "tool_result"
        rebind(body)
    elif case == "missing_message":
        body["sources"][0].pop("message_id")
    elif case == "missing_date":
        body["sources"][0].pop("occurred_at")
    elif case == "tampered_excerpt":
        body["sources"][0]["excerpt"] += " changed"
        rebind(body)
    elif case == "tampered_manifest":
        body["sources"][0]["source_ref"] += "changed"
    elif case == "self_authorizing":
        body["authorization"]["source_ref"] = body["sources"][0]["source_ref"]
    elif case == "extra_raw":
        body["sources"][0]["raw_body"] = "not allowed"
    elif case == "empty_excerpt":
        body["sources"][0]["excerpt"] = " "
    elif case == "duplicate_source":
        body["sources"].append(copy.deepcopy(body["sources"][0]))
    before = counts(client)
    for route in ("validate", "submit"):
        response = client.post("/api/material-imports/" + route, json=body, headers=headers)
        assert response.status_code == 422, response.text
        assert counts(client) == before


def test_authentication_and_disabled_routes(staged):
    client, headers, body = staged
    assert client.post("/api/material-imports/submit", json=body).status_code == 401
    assert (
        client.post(
            "/api/material-imports/validate", json=body, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    client.app.state.settings.material_import_token = None
    assert (
        client.post("/api/material-imports/submit", json=body, headers=headers).status_code == 404
    )
    assert counts(client) == {
        "material_imports": 0,
        "episodes": 0,
        "candidates": 0,
        "observations": 0,
    }


def test_preview_rollback_and_cross_key_dedup(staged):
    client, headers, body = staged
    before = counts(client)
    assert (
        client.post("/api/material-imports/validate", json=body, headers=headers).status_code == 200
    )
    assert counts(client) == before
    first = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    body["idempotency_key"] = "different-key"
    second = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "material_import_duplicate_content"
    assert second.json()["error"]["details"]["import_id"] == first["import_id"]
    assert counts(client) == {
        "material_imports": 1,
        "episodes": 1,
        "candidates": 1,
        "observations": 0,
    }


@pytest.fixture
def pcr():
    path = os.environ.get("PCR_PLUGIN_PATH")
    if not path:
        pytest.skip("Set PCR_PLUGIN_PATH to the isolated coordinated PCR checkout.")
    package = types.ModuleType("synthetic_material_pcr")
    package.__path__ = [str(Path(path) / "router")]
    sys.modules[package.__name__] = package
    cur = importlib.import_module(package.__name__ + ".curation")
    config_mod = importlib.import_module(package.__name__ + ".config")
    config = config_mod.RouterConfig()
    config.kinlayer.enabled = True
    config.kinlayer.base_url = "http://synthetic.test"
    config.kinlayer.curation.mode = "apply"
    return cur, config


class SyntheticPlanner:
    """Deterministic fixture at the planner boundary, not a live LLM."""

    def complete_structured(self, **kwargs):
        pack = json.loads(kwargs["input"][0]["text"])
        self.pack = pack
        decisions = []
        for group in pack["groups"]:
            for c in group["candidates"]:
                decisions.append(
                    {
                        "action": "accept_existing",
                        "risk_level": "low",
                        "candidate_ids": [c["id"]],
                        "target_entity_id": c["target_entity_id"],
                        "proposed_payload": c["payload"],
                        "evidence_episode_ids": [e["episode_id"] for e in c["evidence"]],
                        "reason_codes": ["synthetic_source_report"],
                    }
                )
        return types.SimpleNamespace(
            parsed={"decisions": decisions},
            text="",
            provider="synthetic",
            model="deterministic-fixture",
        )


def pcr_transport(client):
    def transport(method, url, payload, timeout, max_bytes):
        parsed = urlsplit(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        response = client.request(method, path, json=payload)
        assert response.status_code < 400, response.text
        return response.json()

    return transport


def test_cli_http_pcr_curation_canonical_retrieval(staged, pcr, tmp_path, monkeypatch):
    client, headers, body = staged
    cur, config = pcr
    manifest = tmp_path / "synthetic-manifest.json"
    manifest.write_text(json.dumps(body))
    monkeypatch.setenv("KINLAYER_API_URL", "http://synthetic.test")
    monkeypatch.setenv("KINLAYER_MATERIAL_IMPORT_TOKEN", "synthetic-import-token")
    # Typer and its real HTTP wrapper reach the production FastAPI routes in-process.
    monkeypatch.setattr(
        cli.httpx,
        "post",
        lambda url, **kw: client.post(
            urlsplit(url).path, headers=kw.get("headers"), json=kw.get("json")
        ),
    )
    monkeypatch.setattr(
        cli.httpx,
        "get",
        lambda url, **kw: client.get(urlsplit(url).path, headers=kw.get("headers")),
    )
    runner = CliRunner()
    preview = runner.invoke(cli.app, ["material-import", "--file", str(manifest), "--json"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["status"] == "validated"
    assert counts(client)["candidates"] == 0
    submitted = runner.invoke(
        cli.app, ["material-import", "--file", str(manifest), "--submit", "--json"]
    )
    assert submitted.exit_code == 0, submitted.output
    receipt = json.loads(submitted.output)
    candidate_id = receipt["candidate_ids"][0]
    pending = client.get("/api/candidates/" + candidate_id).json()
    assert pending["status"] == "pending"
    assert counts(client)["observations"] == 0
    pack = client.post("/api/curation/source-packs", json={}).json()
    assert pack["diagnostics"]["evidence_policy"] == "user_authored_or_authorized_material_v1"
    assert cur._validate_source_pack(pack, config, None)
    planner = SyntheticPlanner()
    result = cur.run_curation(config, planner, transport=pcr_transport(client))
    assert result["ok"], result
    candidate = client.get("/api/candidates/" + candidate_id).json()
    assert candidate["status"] == "accepted", result
    assert candidate["payload"] == pending["payload"]
    evidence = planner.pack["groups"][0]["candidates"][0]["evidence"][0]
    assert evidence["actor"] == "Synthetic Alice"
    assert (
        evidence["material_provenance"]["authorization_ref"] == body["authorization"]["source_ref"]
    )
    canonical_id = candidate["canonical_record_ref"].split(":")[1]
    observation = client.get("/api/observations/" + canonical_id).json()
    assert observation["content"] == candidate["payload"]["content"]
    retrieved = client.post(
        "/api/context/retrieve",
        json={
            "query": "Synthetic Alice short message call",
            "focal_entity_id": body["target_entity_id"],
            "include_debug": True,
        },
    ).json()
    assert canonical_id in json.dumps(retrieved), retrieved
    before = counts(client)
    assert cur.run_curation(config, planner, transport=pcr_transport(client))["ok"]
    assert counts(client) == before
    client.get("/api/entities/" + body["target_entity_id"] + "/context-card")
    assert counts(client) == before
    print(
        json.dumps(
            {
                "vertical_slice": "cli->http->source_pack->pcr->curation->canonical->retrieve",
                "candidate_status": candidate["status"],
                "canonical_count": before["observations"],
                "result": result,
            },
            sort_keys=True,
        )
    )


@pytest.mark.parametrize("case", ["high_impact", "source_high_impact", "restricted_policy"])
def test_import_does_not_bypass_review(staged, pcr, case):
    client, headers, body = staged
    cur, config = pcr
    if case == "high_impact":
        body["claims"][0]["summary"] = "Reports a cancer diagnosis."
    elif case == "source_high_impact":
        source = body["sources"][0]
        source["excerpt"] = "I have a cancer diagnosis."
        source["excerpt_sha256"] = source["original_sha256"] = (
            "sha256:" + hashlib.sha256(source["excerpt"].encode()).hexdigest()
        )
        rebind(body)
    else:
        body["claims"][0]["ai_use_policy"] = "ask_before_use"
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert receipt.status_code == 200, receipt.text
    result = cur.run_curation(config, SyntheticPlanner(), transport=pcr_transport(client))
    assert result["ok"], result
    assert counts(client)["observations"] == 0
    assert (
        client.get("/api/candidates/" + receipt.json()["candidate_ids"][0]).json()["status"]
        == "pending"
    )
    run = client.get("/api/curation/runs").json()["items"][0]
    decision = client.get("/api/curation/runs/" + run["id"]).json()["decisions"][0]
    assert decision["status"] == "blocked"
    assert (
        "restricted_ai_use_policy" if case == "restricted_policy" else "high_impact_content"
    ) in decision["reason_codes"]


@pytest.mark.parametrize("changed", ["actor", "excerpt", "date", "payload", "manifest"])
def test_persisted_tampering_is_excluded_and_accept_blocked(staged, changed):
    client, headers, body = staged
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    with client.app.state.session_factory() as session:
        e = session.get(Episode, receipt["episode_ids"][0])
        if changed == "actor":
            e.actor = "user"
        elif changed == "excerpt":
            e.body_excerpt = "different evidence"
        elif changed == "date":
            e.occurred_at = None
        elif changed == "payload":
            c = session.get(Candidate, receipt["candidate_ids"][0])
            c.payload = {**c.payload, "content": "unattributed objective fact"}
        else:
            r = session.get(MaterialImport, receipt["import_id"])
            r.manifest = {**r.manifest, "authorization": {}}
        session.commit()
    pack = client.post("/api/curation/source-packs", json={}).json()
    assert not pack["groups"][0]["candidates"][0]["evidence"]
    accepted = client.post("/api/candidates/" + receipt["candidate_ids"][0] + "/accept")
    assert accepted.status_code == 409, accepted.text
    assert counts(client)["observations"] == 0


def test_import_evidence_cannot_be_reused_as_ordinary_candidate(staged):
    client, headers, body = staged
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    c = client.get("/api/candidates/" + receipt["candidate_ids"][0]).json()
    payload = {
        k: c[k]
        for k in ("candidate_type", "target_entity_id", "payload", "confidence", "created_by")
    }
    payload["evidence"] = [
        {"episode_id": receipt["episode_ids"][0], "excerpt": body["sources"][0]["excerpt"]}
    ]
    response = client.post("/api/candidates", json=payload)
    assert response.status_code == 422, response.text
    assert counts(client)["candidates"] == 1


def test_pcr_rejects_unbound_or_wrong_scope_material(staged, pcr):
    client, headers, body = staged
    cur, config = pcr
    client.post("/api/material-imports/submit", json=body, headers=headers)
    pack = client.post("/api/curation/source-packs", json={}).json()
    for case in ("absent", "target", "candidate", "policy", "extra", "assistant"):
        changed = copy.deepcopy(pack)
        e = changed["groups"][0]["candidates"][0]["evidence"][0]
        if case == "absent":
            e.pop("material_provenance")
        elif case == "target":
            e["material_provenance"]["target_entity_id"] = "another-person"
        elif case == "candidate":
            e["material_provenance"]["candidate_id"] = "another-candidate"
        elif case == "policy":
            changed["diagnostics"]["evidence_policy"] = "user_authored_only"
        elif case == "extra":
            e["material_provenance"]["approved"] = True
        else:
            e["actor"] = "assistant"
        with pytest.raises(cur.CurationError):
            cur._validate_source_pack(changed, config, None)


def test_atomic_batch_failure_and_inference_temporal_metadata(staged):
    client, headers, body = staged
    body["claims"].append({**body["claims"][0], "observation_type": "invented_type"})
    assert (
        client.post("/api/material-imports/submit", json=body, headers=headers).status_code == 422
    )
    assert counts(client)["episodes"] == counts(client)["candidates"] == 0
    body["claims"].pop()
    body["claims"][0]["kind"] = "inference"
    body["claims"][0]["summary"] = "May prefer low-pressure communication."
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    c = client.get("/api/candidates/" + receipt["candidate_ids"][0]).json()
    assert c["payload"]["claim_type"] == "inference"
    assert "Source-based inference" in c["payload"]["content"]
    assert not c["payload"].get("occurred_at")
    assert "2026-09-01" in c["payload"]["content"]
    assert not c["payload"].get("valid_to")
    readback = client.get("/api/material-imports/" + receipt["import_id"], headers=headers).json()
    assert readback["manifest"]["authorization"] == body["authorization"]
    assert readback["manifest"]["sources"] == body["sources"]


def test_concurrent_same_key_import_is_atomic(staged):
    from concurrent.futures import ThreadPoolExecutor

    client, headers, body = staged
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post("/api/material-imports/submit", json=body, headers=headers),
                range(2),
            )
        )
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json()["candidate_ids"] == responses[1].json()["candidate_ids"]
    assert counts(client) == {
        "material_imports": 1,
        "episodes": 1,
        "candidates": 1,
        "observations": 0,
    }


def test_unreceipted_import_cannot_masquerade_as_user_evidence(staged):
    client, headers, body = staged
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    with client.app.state.session_factory() as session:
        e = session.get(Episode, receipt["episode_ids"][0])
        e.material_import_id = None
        e.actor = "user"
        session.commit()
    pack = client.post("/api/curation/source-packs", json={}).json()
    assert not pack["groups"][0]["candidates"][0]["evidence"]


def test_import_does_not_allow_planner_or_manual_attribution_rewrite(staged, pcr):
    client, headers, body = staged
    cur, config = pcr
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers).json()
    pack = client.post("/api/curation/source-packs", json={}).json()
    candidates = cur._validate_source_pack(pack, config, None)
    c = pack["groups"][0]["candidates"][0]
    proposal = {
        "action": "edit_accept_existing",
        "risk_level": "low",
        "candidate_ids": [c["id"]],
        "target_entity_id": c["target_entity_id"],
        "proposed_payload": {**c["payload"], "content": "Alice dislikes calls."},
        "evidence_episode_ids": [e["episode_id"] for e in c["evidence"]],
        "reason_codes": ["synthetic"],
    }
    with pytest.raises(cur.CurationError, match="material_import_requires_unchanged_accept"):
        cur._validate_plan({"decisions": [proposal]}, candidates)
    proposal["action"] = "accept_existing"
    with pytest.raises(cur.CurationError, match="material_import_payload_changed"):
        cur._validate_plan({"decisions": [proposal]}, candidates)
    edited = client.post(
        "/api/candidates/" + receipt["candidate_ids"][0] + "/edit-accept",
        json={"payload": proposal["proposed_payload"]},
    )
    assert edited.status_code == 409, edited.text
    assert counts(client)["observations"] == 0


@pytest.mark.parametrize(
    "field,value", [("occurred_at", "2026-10-01T00:00:00Z"), ("author_kind", "assistant")]
)
def test_source_dates_and_authorship_are_not_inferred(staged, field, value):
    client, headers, body = staged
    body["sources"][0][field] = value
    rebind(body)
    response = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert response.status_code == 422, response.text
