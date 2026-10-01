"""Immediate import and historical receipt regressions using synthetic evidence."""

import copy
import json
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest
from typer.testing import CliRunner
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from kinlayer_backend import cli
from kinlayer_backend.models import Episode, MaterialImport, ObservationEvidence
from test_material_imports import (
    counts,
    pcr as pcr,
    legacy_import,
    rebind,
    staged as staged,
)


def wire_cli(client, monkeypatch, *, reorder_receipt=False):
    monkeypatch.setenv("KINLAYER_API_URL", "http://synthetic.test")
    monkeypatch.setenv("KINLAYER_MATERIAL_IMPORT_TOKEN", "synthetic-import-token")
    posted_ids = []
    reads = []

    def post(url, **kwargs):
        response = client.post(
            urlsplit(url).path, headers=kwargs.get("headers"), json=kwargs.get("json")
        )
        if response.status_code == 200:
            posted_ids[:] = response.json()["candidate_ids"]
        return response

    def get(url, **kwargs):
        if reorder_receipt:
            with client.app.state.session_factory() as session:
                row = session.get(MaterialImport, urlsplit(url).path.rsplit("/", 1)[-1])
                # JSONB preserves object semantics, not insertion order. Force a
                # different order from POST rather than depending on random IDs.
                row.candidate_links = {
                    key: row.candidate_links[key] for key in reversed(posted_ids)
                }
                flag_modified(row, "candidate_links")
                session.commit()
        response = client.get(urlsplit(url).path, headers=kwargs.get("headers"))
        reads.append(response)
        return response

    monkeypatch.setattr(cli.httpx, "post", post)
    monkeypatch.setattr(cli.httpx, "get", get)
    return reads


def invoke_import(body, tmp_path, *, submit=True):
    manifest = tmp_path / "synthetic-review.json"
    manifest.write_text(json.dumps(body))
    args = ["material-import", "--file", str(manifest), "--json"]
    if submit:
        args.append("--submit")
    return CliRunner().invoke(cli.app, args)


def canonical(client, candidate_id):
    candidate = client.get("/api/candidates/" + candidate_id).json()
    assert candidate["status"] == "accepted", candidate
    ref = candidate["canonical_record_ref"].split(":")[1]
    result = client.get("/api/observations/" + ref)
    assert result.status_code == 200, result.text
    return result.json()


def test_kst_cli_persistence_provenance_and_immediate_save(staged, tmp_path, monkeypatch):
    client, headers, body = staged
    body["sources"][0]["occurred_at"] = "2026-09-01T01:00:00+09:00"
    rebind(body)
    reads = wire_cli(client, monkeypatch)
    submitted = invoke_import(body, tmp_path)
    assert submitted.exit_code == 0, submitted.output
    receipt = json.loads(submitted.output)
    assert len(reads) == 1 and reads[0].status_code == 200
    with client.app.state.session_factory() as session:
        occurred = session.get(Episode, receipt["episode_ids"][0]).occurred_at
        assert occurred.replace(tzinfo=UTC) == datetime(2026, 8, 31, 16, tzinfo=UTC)
    candidate = client.get("/api/candidates/" + receipt["candidate_ids"][0]).json()
    assert candidate["status"] == "accepted"
    observation = canonical(client, candidate["id"])
    assert observation["content"] == body["claims"][0]["summary"]
    assert observation["claim_basis"] == "reported"
    assert observation["occurred_at"] is None
    assert counts(client)["memory_changes"] == 1
    readback = client.get("/api/material-imports/" + receipt["import_id"], headers=headers).json()
    assert readback["manifest"]["sources"] == body["sources"]
    assert readback["manifest"]["authorization"] == body["authorization"]


def test_cli_receipt_is_stable_after_json_object_reordering(staged, tmp_path, monkeypatch):
    client, _, body = staged
    body["claims"].append({**body["claims"][0], "summary": "Reports preferring advance notice."})
    reads = wire_cli(client, monkeypatch, reorder_receipt=True)
    submitted = invoke_import(body, tmp_path)
    assert submitted.exit_code == 0, submitted.output
    receipt = json.loads(submitted.output)
    assert len(receipt["candidate_ids"]) == 2
    assert receipt["candidate_ids"] == sorted(receipt["candidate_ids"])
    assert len(reads) == 1
    assert reads[0].json()["candidate_ids"] == receipt["candidate_ids"]
    replay = invoke_import(body, tmp_path)
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.output)["candidate_ids"] == receipt["candidate_ids"]
    assert counts(client)["candidates"] == 2


@pytest.mark.parametrize("key", [".", ".."])
def test_dot_segment_keys_rejected_without_http_or_cli_writes(staged, tmp_path, monkeypatch, key):
    client, headers, body = staged
    body["idempotency_key"] = key
    before = counts(client)
    for route in ("validate", "submit"):
        response = client.post("/api/material-imports/" + route, json=body, headers=headers)
        assert response.status_code == 422, response.text
        assert counts(client) == before
    reads = wire_cli(client, monkeypatch)
    for submit in (False, True):
        result = invoke_import(body, tmp_path, submit=submit)
        assert result.exit_code != 0
        assert counts(client) == before
    assert reads == []


@pytest.mark.parametrize("key", ["a.b_c:d-1", "...", ".a", "a.."])
def test_other_valid_key_characters_still_round_trip(staged, tmp_path, monkeypatch, key):
    client, _, body = staged
    body["idempotency_key"] = key
    reads = wire_cli(client, monkeypatch)
    result = invoke_import(body, tmp_path)
    assert result.exit_code == 0, result.output
    assert reads[0].status_code == 200


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("kind", ["sourced_report", "inference"])
@pytest.mark.parametrize("wording", ["ordinary", "현재", "recently"])
def test_undated_cli_saves_immediately_and_keeps_evidence(
    staged, tmp_path, monkeypatch, mixed, kind, wording
):
    client, headers, body = staged
    body["sources"][0]["occurred_at"] = None
    body["claims"][0]["kind"] = kind
    if wording != "ordinary":
        body["claims"][0]["summary"] = wording + " " + body["claims"][0]["summary"]
    if mixed:
        dated = {**body["sources"][0], "source_id": "note-2", "message_id": "paragraph-3",
                 "occurred_at": "2026-09-01T10:00:00Z"}
        body["sources"].append(dated)
        body["authorization"]["source_ids"].append("note-2")
        body["claims"][0]["source_ids"].append("note-2")
    rebind(body)
    wire_cli(client, monkeypatch)
    before = counts(client)
    preview = invoke_import(body, tmp_path, submit=False)
    assert preview.exit_code == 0, preview.output
    assert counts(client) == before
    assert json.loads(preview.output)["validation_scope"] == "immediate_memories"
    candidate_preview = json.loads(preview.output)["candidates"][0]
    assert candidate_preview.get("occurred_at") is None
    assert candidate_preview["content"] == body["claims"][0]["summary"]
    submitted = invoke_import(body, tmp_path)
    assert submitted.exit_code == 0, submitted.output
    receipt = json.loads(submitted.output)
    candidate_id = receipt["candidate_ids"][0]
    candidate = client.get("/api/candidates/" + candidate_id).json()
    assert candidate["status"] == "accepted"
    assert len(candidate["evidence"]) == len(body["sources"])
    assert counts(client)["observations"] == 1
    observation = canonical(client, candidate_id)
    assert observation["occurred_at"] is None
    assert observation["content"] == candidate_preview["content"]
    assert observation["claim_basis"] == ("reported" if kind == "sourced_report" else "inferred")
    evidence = client.get("/api/candidates/" + candidate_id).json()["evidence"]
    assert len(evidence) == len(body["sources"])
    with client.app.state.session_factory() as session:
        sources = [session.get(Episode, episode_id) for episode_id in receipt["episode_ids"]]
        assert sum(source.occurred_at is None for source in sources) == 1
        canonical_evidence = session.scalars(
            select(ObservationEvidence).where(ObservationEvidence.observation_id == observation["id"])
        ).all()
        assert {e.episode_id for e in canonical_evidence} == set(receipt["episode_ids"])
        assert {e.excerpt for e in canonical_evidence} == {s["excerpt"] for s in body["sources"]}
    readback = client.get("/api/material-imports/" + receipt["import_id"], headers=headers).json()
    assert readback["manifest"]["sources"] == body["sources"]
    assert readback["manifest"]["authorization"] == body["authorization"]
    assert invoke_import(body, tmp_path).exit_code == 0
    assert counts(client)["observations"] == 1


@pytest.mark.parametrize("case", ["korean_inference", "long_multisource"])
def test_inference_and_multiple_sources_save_without_planner_review(staged, case):
    client, headers, body = staged
    if case == "korean_inference":
        body["claims"][0]["kind"] = "inference"
        body["claims"][0]["summary"] = "짧고 부담 없는 연락을 선호하는 것으로 보인다."
    else:
        for n in range(2, 6):
            source = {**body["sources"][0], "source_id": f"note-{n}",
                      "author": "Synthetic Human Author With Attribution " + str(n),
                      "message_id": f"paragraph-{n}"}
            body["sources"].append(source)
            body["authorization"]["source_ids"].append(source["source_id"])
            body["claims"][0]["source_ids"].append(source["source_id"])
        rebind(body)
    preview = client.post("/api/material-imports/validate", json=body, headers=headers)
    assert preview.status_code == 200, preview.text
    assert counts(client)["observations"] == counts(client)["candidates"] == 0
    response = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert response.status_code == 200, response.text
    candidate_id = response.json()["candidate_ids"][0]
    observation = canonical(client, candidate_id)
    assert observation["content"] == body["claims"][0]["summary"]
    assert observation["occurred_at"] is None
    assert observation["claim_basis"] == ("inferred" if case == "korean_inference" else "reported")
    assert counts(client)["observations"] == counts(client)["memory_changes"] == 1
    assert counts(client)["observation_evidence"] == len(body["sources"])


@pytest.mark.parametrize("case", ["unknown_author", "assistant_kind", "ai_report", "undated_authorization"])
def test_undated_does_not_relax_human_or_authorization_requirements(staged, case):
    client, headers, body = staged
    body["sources"][0]["occurred_at"] = None
    if case == "unknown_author":
        body["sources"][0]["author"] = "unknown"
    elif case == "assistant_kind":
        body["sources"][0]["author_kind"] = "assistant"
    elif case == "ai_report":
        body["sources"][0]["kind"] = "assistant_report"
    else:
        body["authorization"]["occurred_at"] = None
    rebind(body)
    before = counts(client)
    for route in ("validate", "submit"):
        response = client.post("/api/material-imports/" + route, json=body, headers=headers)
        assert response.status_code == 422, response.text
        assert counts(client) == before


def test_undated_source_cannot_gain_a_fabricated_date(staged, pcr):
    client, headers, body = staged
    cur, config = pcr
    body["sources"][0]["occurred_at"] = None
    rebind(body)
    receipt = legacy_import(client, body)
    pack = client.post("/api/curation/source-packs", json={}).json()
    changed = copy.deepcopy(pack)
    e = changed["groups"][0]["candidates"][0]["evidence"][0]
    e["occurred_at"] = body["authorization"]["occurred_at"]
    with pytest.raises(cur.CurationError):
        cur._validate_source_pack(changed, config, None)
    with client.app.state.session_factory() as session:
        episode = session.get(Episode, receipt["episode_ids"][0])
        episode.occurred_at = datetime(2026, 9, 30, 1, tzinfo=UTC)
        session.commit()
    accepted = client.post("/api/candidates/" + receipt["candidate_ids"][0] + "/accept")
    assert accepted.status_code == 409, accepted.text
    assert counts(client)["observations"] == 0
