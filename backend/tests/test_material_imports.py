"""Synthetic-only vertical contract; no live services or provider calls."""

import hashlib
import json
import copy
import importlib
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner
from sqlalchemy import select, func

from kinlayer_backend import cli
from kinlayer_backend.models import (
    Candidate, CandidateEvidence, Entity, Episode, MaterialImport, MemoryChange,
    Observation, ObservationEvidence,
)
from kinlayer_backend.schemas.material_imports import MaterialImportRequest
from kinlayer_backend.services.material_imports import request_fingerprint


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
    assert receipt["validation_scope"] == "immediate_memories"
    assert len(receipt["canonical_record_refs"]) == 1
    replay = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["candidate_ids"] == receipt["candidate_ids"]
    assert replay.json()["canonical_record_refs"] == receipt["canonical_record_refs"]
    assert client.get("/api/candidates").json()["total"] == 1
    candidate = client.get("/api/candidates/" + receipt["candidate_ids"][0]).json()
    assert candidate["status"] == "accepted"
    assert candidate["evidence"][0]["actor"] == "Synthetic Alice"
    assert candidate["evidence"][0]["material_import_id"] == receipt["import_id"]
    assert candidate["payload"]["claim_type"] == "fact"
    assert candidate["payload"]["claim_basis"] == "reported"
    assert candidate["payload"]["content"] == body["claims"][0]["summary"]
    assert client.get("/api/candidates", params={"status": "pending"}).json()["total"] == 0
    with client.app.state.session_factory() as session:
        change = session.scalar(select(MemoryChange))
        assert change.new_record_ref == receipt["canonical_record_refs"][0]
        assert change.source_episode_id == receipt["episode_ids"][0]
        assert change.change_kind == "create"
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
            for m in (MaterialImport, Episode, Candidate, Observation, ObservationEvidence, MemoryChange)
        }


def rebind(body):
    body["authorization"]["manifest_sha256"] = digest(
        {"target_entity_id": body["target_entity_id"], "sources": body["sources"]}
    )


def legacy_import(client, body):
    """Frozen pre-save-first import, kept to exercise historical receipt/provenance paths."""
    request = MaterialImportRequest.model_validate(body)
    source = body["sources"][0]
    with client.app.state.session_factory() as session:
        row = MaterialImport(
            id=request.idempotency_key,
            request_sha256=request_fingerprint(request),
            manifest=request.model_dump(mode="json", exclude={"idempotency_key"}),
            candidate_links={},
        )
        session.add(row)
        session.flush()
        episode = Episode(
            material_import_id=row.id, source_type="import", source_ref=source["source_ref"],
            actor=source["author"], body_excerpt=source["excerpt"], body_hash=source["original_sha256"],
            occurred_at=datetime.fromisoformat(source["occurred_at"]) if source["occurred_at"] else None,
            retention_policy="excerpt_only",
        )
        candidate = Candidate(
            candidate_type="observation", target_entity_id=request.target_entity_id,
            payload={
                "subject_entity_id": request.target_entity_id,
                "related_entity_ids": [],
                "observation_type": "communication_preference",
                "content": "Source report [Synthetic Alice, 2026-09-01, paragraph-2]: " + body["claims"][0]["summary"],
                "claim_type": "fact", "ai_use_policy": "cautious_use",
                "occurred_at": source["occurred_at"],
            },
            confidence=0.9, created_by="ai_agent", suggested_action="review",
        )
        session.add_all([episode, candidate])
        session.flush()
        session.add(CandidateEvidence(
            candidate_id=candidate.id, episode_id=episode.id,
            excerpt=source["excerpt"], confidence=0.9,
        ))
        row.candidate_links = {candidate.id: {
            "payload_sha256": digest(candidate.payload), "kind": "sourced_report",
            "target_entity_id": request.target_entity_id,
            "episodes": {episode.id: source["source_id"]},
        }}
        session.commit()
        return {"import_id": row.id, "candidate_ids": [candidate.id], "episode_ids": [episode.id]}


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
        "observation_evidence": 0,
        "memory_changes": 0,
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
        "observations": 1,
        "observation_evidence": 1,
        "memory_changes": 1,
    }


def test_legacy_receipt_replays_without_rewriting_history(staged):
    client, headers, body = staged
    old = legacy_import(client, body)
    with client.app.state.session_factory() as session:
        row = session.get(MaterialImport, old["import_id"])
        before = (copy.deepcopy(row.manifest), row.request_sha256, copy.deepcopy(row.candidate_links))
    before_counts = counts(client)
    for method, path in (("get", "/api/material-imports/" + old["import_id"]),
                         ("post", "/api/material-imports/submit")):
        response = client.request(method, path, headers=headers, **({"json": body} if method == "post" else {}))
        assert response.status_code == 200, response.text
        assert response.json()["validation_scope"] == "pending_candidates_only"
        assert response.json()["canonical_record_refs"] == []
        assert response.json()["candidate_ids"] == old["candidate_ids"]
    assert counts(client) == before_counts
    with client.app.state.session_factory() as session:
        row = session.get(MaterialImport, old["import_id"])
        assert (row.manifest, row.request_sha256, row.candidate_links) == before


@pytest.mark.parametrize("kind,basis", [("sourced_report", "reported"), ("inference", "inferred")])
@pytest.mark.parametrize("source_date", ["2026-09-01T08:00:00Z", None])
def test_import_keeps_source_date_separate_and_ignores_confirmation(staged, kind, basis, source_date):
    client, headers, body = staged
    body["claims"][0]["kind"] = kind
    body["sources"][0]["occurred_at"] = source_date
    body["idempotency_key"] = "x" * 120
    rebind(body)
    with client.app.state.session_factory() as session:
        target = session.get(Entity, body["target_entity_id"])
        target.confirmation_status = "provisional"
        target.ai_use_policy = "never_surface"
        session.commit()
    receipt = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert receipt.status_code == 200, receipt.text
    ref = receipt.json()["canonical_record_refs"][0]
    with client.app.state.session_factory() as session:
        observation = session.get(Observation, ref.split(":")[1])
        episode = session.get(Episode, receipt.json()["episode_ids"][0])
        change = session.scalar(select(MemoryChange))
        assert observation.claim_basis == basis
        assert observation.occurred_at is None
        assert (episode.occurred_at is None) == (source_date is None)
        assert len(change.request_id) <= 160
        assert change.new_record_ref == ref


@pytest.mark.parametrize("route", ["validate", "submit"])
def test_canonical_failure_rolls_back_entire_import(staged, monkeypatch, route):
    from kinlayer_backend.api.errors import api_error
    from kinlayer_backend.services.candidates import CandidateService

    client, headers, body = staged
    body["claims"].append({**body["claims"][0], "summary": "Also prefers an advance notice."})
    original = CandidateService.accept_candidate
    calls = []

    def fail_second(service, candidate, **kwargs):
        calls.append(candidate.id)
        if len(calls) == 2:
            assert service.session.scalar(select(func.count()).select_from(Observation)) == 1
            raise api_error(422, "synthetic_failure", "Synthetic second canonical write failure.")
        return original(service, candidate, **kwargs)

    monkeypatch.setattr(CandidateService, "accept_candidate", fail_second)
    before = counts(client)
    response = client.post("/api/material-imports/" + route, json=body, headers=headers)
    assert response.status_code == 422, response.text
    assert len(calls) == 2
    assert counts(client) == before


def test_preview_validates_canonical_records_without_persisting_them(staged):
    client, headers, body = staged
    before = counts(client)
    preview = client.post("/api/material-imports/validate", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["validation_scope"] == "immediate_memories"
    assert result["candidate_ids"] == result["episode_ids"] == result["canonical_record_refs"] == []
    assert result["candidates"][0]["claim_basis"] == "reported"
    assert counts(client) == before


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


def test_cli_http_immediate_canonical_retrieval(staged, tmp_path, monkeypatch):
    client, headers, body = staged
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
    candidate = client.get("/api/candidates/" + candidate_id).json()
    assert candidate["status"] == "accepted"
    assert counts(client)["observations"] == 1
    assert receipt["canonical_record_refs"] == [candidate["canonical_record_ref"]]
    pack = client.post("/api/curation/source-packs", json={}).json()
    assert all(not group["candidates"] for group in pack["groups"])
    evidence = candidate["evidence"][0]
    assert evidence["actor"] == "Synthetic Alice"
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
    replay = runner.invoke(
        cli.app, ["material-import", "--file", str(manifest), "--submit", "--json"]
    )
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["canonical_record_refs"] == receipt["canonical_record_refs"]
    client.get("/api/entities/" + body["target_entity_id"] + "/context-card")
    assert counts(client) == before


@pytest.mark.parametrize("case", ["high_impact", "source_high_impact", "restricted_policy"])
def test_authorized_import_saves_without_review_or_policy_gate(staged, case):
    client, headers, body = staged
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
    assert counts(client)["observations"] == 1
    candidate = client.get("/api/candidates/" + receipt.json()["candidate_ids"][0]).json()
    assert candidate["status"] == "accepted"
    canonical_id = receipt.json()["canonical_record_refs"][0].split(":")[1]
    observation = client.get("/api/observations/" + canonical_id).json()
    assert observation["content"] == body["claims"][0]["summary"]
    assert observation["claim_basis"] == "reported"
    assert client.get("/api/candidates", params={"status": "pending"}).json()["total"] == 0


@pytest.mark.parametrize("changed", ["actor", "excerpt", "date", "payload", "manifest"])
def test_persisted_tampering_is_excluded_and_accept_blocked(staged, changed):
    client, headers, body = staged
    receipt = legacy_import(client, body)
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
    legacy_import(client, body)
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
    assert c["payload"]["content"] == body["claims"][0]["summary"]
    assert c["payload"]["claim_basis"] == "inferred"
    assert not c["payload"].get("occurred_at")
    assert "2026-09-01" not in c["payload"]["content"]
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
        "observations": 1,
        "observation_evidence": 1,
        "memory_changes": 1,
    }


def test_unreceipted_import_cannot_masquerade_as_user_evidence(staged):
    client, headers, body = staged
    receipt = legacy_import(client, body)
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
    receipt = legacy_import(client, body)
    pack = client.post("/api/curation/source-packs", json={}).json()
    candidates = cur._validate_source_pack(pack, config, None)
    c = pack["groups"][0]["candidates"][0]
    with client.app.state.session_factory() as session:
        stored = session.get(Candidate, receipt["candidate_ids"][0])
        assert "claim_basis" not in stored.payload
        assert c["payload"] == stored.payload
        assert c["payload_digest"] == digest(stored.payload)
        episode = session.get(Episode, receipt["episode_ids"][0])
        assert c["evidence"][0]["excerpt"] == episode.body_excerpt
        assert c["evidence"][0]["body_hash"] == episode.body_hash
        assert c["evidence"][0]["material_provenance"]["import_id"] == receipt["import_id"]
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
