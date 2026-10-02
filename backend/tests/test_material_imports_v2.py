"""Fictional V2 imports through production routes; no provider or live service calls."""

import copy
import json
from datetime import datetime
from pathlib import Path

import httpx
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from kinlayer_backend import cli
from kinlayer_backend.models import (
    Candidate, Entity, EntityFact, EntityFactEvidence, Episode, MaterialImport,
    MemoryChange, Observation, ObservationEntity, ObservationEvidence,
)
from kinlayer_backend.schemas.material_imports import (
    MaterialImportRequest, MaterialImportV2Request, json_digest, text_digest,
)
from kinlayer_backend.services.material_imports import request_fingerprint
from test_material_imports import material_request, rebind


def person(client, name="Synthetic Rowan"):
    response = client.post("/api/entities", json={
        "entity_type": "person", "display_name": name, "created_by": "user",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def typed_request(target):
    body = material_request(target)
    body.pop("claims")
    body.update(contract_version="2", idempotency_key="synthetic-typed-import")
    source = body["sources"][0]
    source.update(author="Synthetic Rowan", occurred_at=None,
                  excerpt="I work as a cartographer. I prefer a message before calls.")
    source["excerpt_sha256"] = source["original_sha256"] = text_digest(source["excerpt"])
    other = copy.deepcopy(source)
    other.update(source_id="note-2", source_ref="synthetic://document-2", message_id="line-7",
                 author="Synthetic Quinn", occurred_at="2026-09-01T19:00:00+09:00")
    body["sources"].append(other)
    body["authorization"]["source_ids"] = ["note-1", "note-2"]
    body["authorization"]["excerpt"] = "Save these sources about Synthetic Rowan."
    body["records"] = [
        {"source_ids": ["note-1", "note-2"], "record": {
            "record_type": "entity_facts", "payload": {
                "entity_id": target, "fact_type": "job", "content": "Cartographer",
                "value": {"text": "Cartographer"}, "claim_basis": "reported", "confidence": 0.9,
            },
        }},
        {"source_ids": ["note-1", "note-2"], "record": {
            "record_type": "observations", "payload": {
                "subject_entity_id": target, "observation_type": "communication_preference",
                "content": "Prefers a message before calls.", "claim_basis": "inferred",
                "confidence": 0.7, "related_entities": [],
            },
        }},
    ]
    rebind(body)
    return body


@pytest.fixture
def staged_v2(client):
    client.app.state.settings.material_import_token = "synthetic-import-token"
    headers = {"Authorization": "Bearer synthetic-import-token"}
    return client, headers, typed_request(person(client))


def counts(client):
    with client.app.state.session_factory() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Entity, MaterialImport, Episode, Candidate, EntityFact, EntityFactEvidence,
                          Observation, ObservationEntity, ObservationEvidence, MemoryChange)
        }


def detail(client, ref):
    response = client.get("/api/memories/" + ref.replace(":", "/"))
    assert response.status_code == 200, response.text
    return response.json()


def submit(client, headers, body):
    response = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_v2_cli_to_typed_profile_card_provenance_history(staged_v2, tmp_path, monkeypatch):
    client, headers, body = staged_v2
    related = person(client, "Synthetic Quinn")
    body["records"][1]["record"]["payload"]["related_entities"] = [
        {"entity_id": related, "role": "speaker", "confidence": 0.8},
        {"entity_id": related, "role": "mentioned", "confidence": 0.6},
    ]
    manifest = tmp_path / "synthetic-v2.json"
    manifest.write_text(json.dumps(body))
    monkeypatch.setenv("KINLAYER_API_URL", "http://synthetic.test")
    monkeypatch.setenv("KINLAYER_MATERIAL_IMPORT_TOKEN", "synthetic-import-token")
    monkeypatch.setattr(cli.httpx, "post", lambda url, **kw: client.post(
        urlsplit(url).path, headers=kw.get("headers"), json=kw.get("json"),
    ))
    monkeypatch.setattr(cli.httpx, "get", lambda url, **kw: client.get(
        urlsplit(url).path, headers=kw.get("headers"),
    ))
    runner = CliRunner()
    before = counts(client)
    preview = runner.invoke(cli.app, ["material-import", "--file", str(manifest), "--json"])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.output)["validation_scope"] == "immediate_memories"
    assert counts(client) == before
    result = runner.invoke(cli.app, ["material-import", "--file", str(manifest), "--submit", "--json"])
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["candidate_ids"] == receipt["candidates"] == []
    assert len(receipt["canonical_record_refs"]) == 2
    assert len(receipt["episode_ids"]) == 2
    assert counts(client)["candidates"] == 0
    assert counts(client)["memory_changes"] == 2
    readback = client.get("/api/material-imports/" + receipt["import_id"], headers=headers).json()
    assert readback["manifest"] == MaterialImportV2Request.model_validate(body).model_dump(
        mode="json", exclude={"idempotency_key"},
    )
    for ref in receipt["canonical_record_refs"]:
        memory = detail(client, ref)
        assert len(memory["sources"]) == 2
        provenance = {s["material_provenance"]["source_id"]: s for s in memory["sources"]}
        for source in body["sources"]:
            evidence = provenance[source["source_id"]]
            proof = evidence["material_provenance"]
            assert evidence["actor"] == source["author"]
            assert evidence["excerpt"] == source["excerpt"]
            assert proof["source_occurred_at"] == (
                source["occurred_at"] if source["occurred_at"] else None
            )
            assert proof["message_id"] == source["message_id"]
            assert proof["original_sha256"] == source["original_sha256"]
            assert proof["excerpt_sha256"] == source["excerpt_sha256"]
            assert proof["authorization_source_ids"] == body["authorization"]["source_ids"]
        if ref.startswith("entity_facts:"):
            assert memory["payload"]["value"] == {"text": "Cartographer"}
            assert memory["content"] == "Cartographer"
        else:
            assert memory["payload"]["occurred_at"] is None
            assert memory["payload"]["claim_basis"] == "inferred"
            assert {p["role"] for p in memory["payload"]["related_entities"]} == {"speaker", "mentioned"}
        changes = client.get("/api/memory-changes", params={"record_ref": ref}).json()["items"]
        assert len(changes) == 1 and changes[0]["new_record_ref"] == ref
    card = client.get(f"/api/entities/{body['target_entity_id']}/context-card").json()
    assert card["profile_facts"][0]["value"] == {"text": "Cartographer"}
    assert len(card["provenance_summary"]["evidence"]) == 4
    assert all(e["material_provenance"] for e in card["provenance_summary"]["evidence"])
    after = counts(client)
    replay = runner.invoke(cli.app, ["material-import", "--file", str(manifest), "--submit", "--json"])
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["canonical_record_refs"] == receipt["canonical_record_refs"]
    assert counts(client) == after


@pytest.mark.parametrize("fact_type,value,content", [
    ("birth_date", {"year": 1990, "precision": "year"}, "1990"),
    ("birth_date", {"year": 1990, "month": 6, "precision": "month"}, "1990-06"),
    ("birth_date", {"year": 1990, "month": 6, "day": 2, "precision": "day"}, "1990-06-02"),
    ("birthday", {"month": 6, "precision": "month"}, "--06"),
    ("birthday", {"month": 2, "day": 29, "precision": "day"}, "--02-29"),
])
def test_partial_profile_dates_preserve_precision(staged_v2, fact_type, value, content):
    client, headers, body = staged_v2
    payload = body["records"][0]["record"]["payload"]
    payload.update(fact_type=fact_type, value=value, content=content)
    receipt = submit(client, headers, body)
    ref = next(r for r in receipt["canonical_record_refs"] if r.startswith("entity_facts:"))
    memory = detail(client, ref)
    assert memory["content"] == content
    assert memory["payload"]["value"] == {"year": value.get("year"), "month": value.get("month"),
                                           "day": value.get("day"), "precision": value["precision"]}
    assert memory["valid_from"] is None
    assert all(e["material_provenance"] for e in memory["sources"])


@pytest.mark.parametrize("route", ["validate", "submit"])
@pytest.mark.parametrize("field", ["occurred_at", "valid_from"])
def test_source_time_does_not_limit_explicit_event_or_validity_time(staged_v2, route, field):
    client, headers, body = staged_v2
    source = body["sources"][0]
    source["excerpt"] = "My new work schedule starts on October 3, 2026 at 09:00 UTC."
    source["excerpt_sha256"] = source["original_sha256"] = text_digest(source["excerpt"])
    rebind(body)
    payload = body["records"][1]["record"]["payload"]
    payload["content"] = "Reports a new work schedule beginning October 3."
    payload[field] = "2026-10-03T09:00:00Z"
    before = counts(client)
    response = client.post("/api/material-imports/" + route, json=body, headers=headers)
    assert response.status_code == 200, response.text
    if route == "validate":
        assert counts(client) == before
    else:
        ref = next(r for r in response.json()["canonical_record_refs"] if r.startswith("observations:"))
        stored = client.get("/api/observations/" + ref.split(":", 1)[1])
        assert stored.status_code == 200, stored.text
        assert stored.json()[field].startswith("2026-10-03T09:00:00")


@pytest.mark.parametrize("basis", ["reported", "inferred", "unknown"])
def test_self_target_and_claim_basis(staged_v2, basis):
    client, headers, body = staged_v2
    with client.app.state.session_factory() as session:
        entity = session.get(Entity, body["target_entity_id"])
        entity.system_role = "self"
        session.commit()
    for item in body["records"]:
        item["record"]["payload"]["claim_basis"] = basis
    receipt = submit(client, headers, body)
    assert all(detail(client, r)["claim_basis"] == basis for r in receipt["canonical_record_refs"])
    legacy = material_request(body["target_entity_id"])
    assert client.post("/api/material-imports/submit", json=legacy, headers=headers).status_code == 422


@pytest.mark.parametrize("case", [
    "wrong_target", "missing_participant", "inactive_participant", "new_entity", "edge",
    "assistant_source", "source_hash", "source_locator", "auth_actor", "auth_target",
    "auth_scope", "auth_manifest", "self_authorizing", "future_source",
    "future_profile_date", "unused_source", "duplicate_source_link",
    "extra_raw", "bad_date_precision", "bad_date", "bad_text", "bad_basis", "bad_role",
    "unsupported_version", "mixed_versions",
])
@pytest.mark.parametrize("route", ["validate", "submit"])
def test_v2_rejects_invalid_scope_and_typed_records_atomically(staged_v2, case, route):
    client, headers, body = staged_v2
    fact = body["records"][0]["record"]["payload"]
    observation = body["records"][1]["record"]["payload"]
    source = body["sources"][0]
    auth = body["authorization"]
    if case == "wrong_target":
        fact["entity_id"] = person(client, "Synthetic Other")
    elif case in {"missing_participant", "inactive_participant"}:
        participant = "nonexistent-person"
        if case == "inactive_participant":
            participant = person(client, "Synthetic Archived")
            with client.app.state.session_factory() as session:
                session.get(Entity, participant).status = "archived"
                session.commit()
        observation["related_entities"] = [{"entity_id": participant, "role": "speaker"}]
    elif case in {"new_entity", "edge"}:
        body["records"][0]["record"]["record_type"] = "new_entity" if case == "new_entity" else "entity_edges"
    elif case == "assistant_source":
        source["author"] = "assistant"
        rebind(body)
    elif case == "source_hash":
        source["excerpt"] += " altered"
    elif case == "source_locator":
        source["message_id"] = "changed-line"
    elif case == "auth_actor":
        auth["actor"] = "assistant"
    elif case == "auth_target":
        auth["target_entity_id"] = "another-target"
    elif case == "auth_scope":
        auth["source_ids"] = ["note-1"]
    elif case == "auth_manifest":
        auth["manifest_sha256"] = "sha256:" + "0" * 64
    elif case == "self_authorizing":
        auth["source_ref"] = source["source_ref"]
    elif case == "future_source":
        source["occurred_at"] = "2026-10-01T00:00:00Z"
        rebind(body)
    elif case == "future_profile_date":
        fact.update(fact_type="birth_date", content="2027", value={"year": 2027, "precision": "year"})
    elif case == "unused_source":
        for item in body["records"]:
            item["source_ids"] = ["note-1"]
    elif case == "duplicate_source_link":
        body["records"][0]["source_ids"].append("note-1")
    elif case == "extra_raw":
        source["raw_body"] = "not retained"
    elif case == "bad_date_precision":
        fact.update(fact_type="birthday", content="--06", value={"month": 6, "precision": "year"})
    elif case == "bad_date":
        fact.update(fact_type="birth_date", content="1990-02-30",
                    value={"year": 1990, "month": 2, "day": 30, "precision": "day"})
    elif case == "bad_text":
        fact["value"] = {"text": "Not the same content"}
    elif case == "bad_basis":
        observation["claim_basis"] = "verified"
    elif case == "bad_role":
        observation["related_entities"] = [{"entity_id": body["target_entity_id"], "role": "invented"}]
    elif case == "unsupported_version":
        body["contract_version"] = "3"
    elif case == "mixed_versions":
        body["claims"] = material_request(body["target_entity_id"])["claims"]
    before = counts(client)
    response = client.post("/api/material-imports/" + route, json=body, headers=headers)
    expected = 409 if case == "inactive_participant" else 404 if case == "missing_participant" else 422
    assert response.status_code == expected, response.text
    assert counts(client) == before


@pytest.mark.parametrize("route", ["validate", "submit"])
def test_mixed_batch_rolls_back_after_first_canonical_write(staged_v2, monkeypatch, route):
    from kinlayer_backend.services.memories import MemoryService
    client, headers, body = staged_v2
    body["records"][1]["record"]["payload"]["observation_type"] = "invalid_ontology_value"
    original = MemoryService._write_record
    seen = []

    def inspect(service, *args, **kwargs):
        seen.append(service.session.scalar(select(func.count()).select_from(EntityFact)))
        return original(service, *args, **kwargs)

    monkeypatch.setattr(MemoryService, "_write_record", inspect)
    before = counts(client)
    response = client.post("/api/material-imports/" + route, json=body, headers=headers)
    assert response.status_code == 422, response.text
    assert seen == [0, 1]
    assert counts(client) == before


@pytest.mark.parametrize("mode", ["same", "cross_key", "changed"])
def test_concurrent_replay_and_conflicts(staged_v2, mode):
    client, headers, body = staged_v2
    second = copy.deepcopy(body)
    if mode == "cross_key":
        second["idempotency_key"] += "-other"
    elif mode == "changed":
        second["records"][1]["record"]["payload"]["content"] = "Prefers shorter calls."
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda b: client.post("/api/material-imports/submit", json=b, headers=headers),
                                  [body, second]))
    assert sorted(r.status_code for r in responses) == ([200, 200] if mode == "same" else [200, 409])
    assert counts(client)["material_imports"] == 1
    assert counts(client)["memory_changes"] == 2
    if mode == "same":
        assert responses[0].json()["canonical_record_refs"] == responses[1].json()["canonical_record_refs"]


def test_replay_json_key_order_is_stable_arrays_are_bound(staged_v2):
    client, headers, body = staged_v2
    receipt = submit(client, headers, body)
    reordered = json.loads(json.dumps(body, sort_keys=True))
    assert submit(client, headers, reordered)["canonical_record_refs"] == receipt["canonical_record_refs"]
    body["records"].reverse()
    assert client.post("/api/material-imports/submit", json=body, headers=headers).status_code == 409


@pytest.mark.parametrize("case", ["author", "locator", "hash", "date", "excerpt", "auth", "record", "evidence"])
def test_tampered_persisted_v2_never_reports_verified_provenance(staged_v2, case):
    client, headers, body = staged_v2
    receipt = submit(client, headers, body)
    ref = next(r for r in receipt["canonical_record_refs"] if r.startswith("entity_facts:"))
    assert all(s["material_provenance"] for s in detail(client, ref)["sources"])
    with client.app.state.session_factory() as session:
        episode = session.get(Episode, receipt["episode_ids"][0])
        if case == "author":
            episode.actor = "Someone Else"
        elif case == "locator":
            episode.source_description = "changed locator"
        elif case == "hash":
            episode.body_hash = "sha256:" + "0" * 64
        elif case == "date":
            episode.occurred_at = None if episode.occurred_at else datetime(2000, 1, 1)
        elif case == "excerpt":
            episode.body_excerpt = "changed source"
        elif case == "auth":
            row = session.get(MaterialImport, receipt["import_id"])
            row.manifest = {**row.manifest, "authorization": {}}
        elif case == "record":
            session.get(EntityFact, ref.split(":")[1]).content = "Changed assertion"
        elif case == "evidence":
            session.delete(session.scalar(select(EntityFactEvidence).where(
                EntityFactEvidence.entity_fact_id == ref.split(":")[1],
            )))
        session.commit()
    assert any(not s.get("material_provenance") for s in detail(client, ref)["sources"])


def test_correction_preserves_original_import_lineage(staged_v2):
    client, headers, body = staged_v2
    receipt = submit(client, headers, body)
    ref = next(r for r in receipt["canonical_record_refs"] if r.startswith("entity_facts:"))
    record = copy.deepcopy(body["records"][0]["record"])
    record["payload"].update(content="Surveyor", value={"text": "Surveyor"})
    correction = client.post("/api/memories", json={
        "request_id": "synthetic-correction", "action": "correct", "old_record_ref": ref,
        "record": record, "source": {"source_type": "manual_entry", "actor": "Synthetic Rowan",
                                      "excerpt": "My job is surveyor, not cartographer."},
    })
    assert correction.status_code == 200, correction.text
    old = detail(client, ref)
    assert old["status"] == "superseded"
    assert all(s["material_provenance"] for s in old["sources"])
    assert detail(client, correction.json()["new_record_ref"])["content"] == "Surveyor"
    history = client.get("/api/memory-changes", params={"record_ref": ref}).json()["items"]
    assert {h["change_kind"] for h in history} == {"create", "correct"}
    assert submit(client, headers, body)["canonical_record_refs"] == receipt["canonical_record_refs"]


def test_config_and_v1_digest_contract_unchanged(staged_v2):
    client, _, body = staged_v2
    config = client.get("/api/system/config").json()
    assert config["material_import"] == {"contract_versions": ["1", "2"],
                                          "record_types": ["entity_facts", "observations"], "immediate": True}
    assert config["memory_write"] == {"endpoint": "/api/memories", "review_required": False, "contract_version": "2"}
    v1 = material_request(body["target_entity_id"])
    normalized = MaterialImportRequest.model_validate(v1).model_dump(mode="json", exclude={"idempotency_key"})
    assert normalized == {k: v for k, v in v1.items() if k != "idempotency_key"}
    assert request_fingerprint(MaterialImportRequest.model_validate(v1)) == json_digest(normalized)


def test_cli_unsupported_never_downgrades(staged_v2, tmp_path, monkeypatch):
    _, _, body = staged_v2
    body["contract_version"] = "3"
    path = tmp_path / "unsupported.json"
    path.write_text(json.dumps(body))
    monkeypatch.setattr(cli, "_request", lambda *a, **k: pytest.fail("Unsupported input must not be sent"))
    result = CliRunner().invoke(cli.app, ["material-import", "--file", str(path), "--submit", "--json"])
    assert result.exit_code != 0


def test_cli_verifies_canonical_receipt(staged_v2, tmp_path, monkeypatch):
    client, headers, body = staged_v2
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(body))

    def request(method, endpoint, **kwargs):
        response = client.request(method, endpoint, headers=headers, json=kwargs.get("payload"))
        if method == "GET":
            result = response.json()
            result["canonical_record_refs"] = []
            return httpx.Response(200, json=result)
        return response

    monkeypatch.setattr(cli, "_request", request)
    result = CliRunner().invoke(cli.app, ["material-import", "--file", str(path), "--submit", "--json"])
    assert result.exit_code != 0
    assert "receipt readback did not match" in result.output
    assert counts(client)["material_imports"] == 1


def test_documented_wire_example_is_executable(client):
    text = (Path(__file__).parents[2] / "docs/specs/authorized-material-imports.md").read_text()
    block = text.split("### Exact fictional wire example", 1)[1].split("```json\n", 1)[1].split("```", 1)[0]
    body = json.loads(block)
    with client.app.state.session_factory() as session:
        session.add(Entity(id=body["target_entity_id"], entity_type="person",
                           display_name="Synthetic Rowan", created_by="user"))
        session.commit()
    client.app.state.settings.material_import_token = "synthetic-import-token"
    receipt = submit(client, {"Authorization": "Bearer synthetic-import-token"}, body)
    assert len(receipt["canonical_record_refs"]) == 3
    for ref in receipt["canonical_record_refs"]:
        assert all(source["material_provenance"] for source in detail(client, ref)["sources"])


def test_exact_source_strings_and_explicit_event_time(staged_v2):
    client, headers, body = staged_v2
    source = body["sources"][0]
    source.update(author="  Synthetic Rowan  ", source_ref=" synthetic://exact-source ",
                  excerpt="  A bounded excerpt with preserved whitespace.  ")
    source["excerpt_sha256"] = source["original_sha256"] = text_digest(source["excerpt"])
    rebind(body)
    body["records"][1]["record"]["payload"].update(
        occurred_at="2025-06-02T09:00:00+09:00", valid_from="2025-06-01T00:00:00Z",
    )
    receipt = submit(client, headers, body)
    observation = detail(client, next(r for r in receipt["canonical_record_refs"] if r.startswith("observations:")))
    assert observation["payload"]["occurred_at"] == "2025-06-02T00:00:00Z"
    evidence = next(s for s in observation["sources"] if s["occurred_at"] is None)
    assert evidence["actor"] == source["author"]
    assert evidence["source_ref"] == source["source_ref"]
    assert evidence["excerpt"] == source["excerpt"]
    assert evidence["material_provenance"]["source_date_status"] == "unknown"


@pytest.mark.parametrize("role", ["subject", "related", "mentioned", "speaker", "target", "about", "experiencer"])
def test_observation_roles_and_first_lock_scope(staged_v2, monkeypatch, role):
    from kinlayer_backend.services import material_imports

    client, headers, body = staged_v2
    related = person(client, "Synthetic Participant")
    body["records"][1]["record"]["payload"]["related_entities"] = [{"entity_id": related, "role": role}]
    original = material_imports.lock_active_entities
    scopes = []

    def lock(session, ids):
        scopes.append(list(ids))
        return original(session, ids)

    monkeypatch.setattr(material_imports, "lock_active_entities", lock)
    receipt = submit(client, headers, body)
    assert scopes[0] == sorted([related, body["target_entity_id"]])
    observation = detail(client, next(r for r in receipt["canonical_record_refs"] if r.startswith("observations:")))
    assert observation["payload"]["related_entities"] == [{"entity_id": related, "role": role, "confidence": None}]
