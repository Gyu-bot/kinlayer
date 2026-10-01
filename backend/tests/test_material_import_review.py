"""Review regressions through production routes; all evidence is synthetic."""

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
    SyntheticPlanner,
    counts,
    pcr as pcr,
    pcr_transport,
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


@pytest.mark.parametrize("review", ["manual", "curation"])
def test_kst_cli_persistence_provenance_and_accept(staged, pcr, tmp_path, monkeypatch, review):
    client, headers, body = staged
    cur, config = pcr
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
    pack = client.post("/api/curation/source-packs", json={}).json()
    candidate = pack["groups"][0]["candidates"][0]
    assert candidate["evidence"], candidate
    assert cur._validate_source_pack(pack, config, None)
    if review == "manual":
        response = client.post("/api/candidates/" + candidate["id"] + "/accept")
        assert response.status_code == 200, response.text
    else:
        result = cur.run_curation(config, SyntheticPlanner(), transport=pcr_transport(client))
        assert result["ok"], result
    observation = canonical(client, candidate["id"])
    assert observation["content"] == candidate["payload"]["content"]
    assert "2026-09-01" in observation["content"]  # original local source date
    assert datetime.fromisoformat(observation["occurred_at"]).replace(tzinfo=UTC) == datetime(
        2026, 8, 31, 16, tzinfo=UTC
    )
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
def test_undated_cli_stays_pending_but_manual_review_keeps_evidence(
    staged, pcr, tmp_path, monkeypatch, mixed, kind, wording
):
    client, headers, body = staged
    cur, config = pcr
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
    assert json.loads(preview.output)["validation_scope"] == "pending_candidates_only"
    candidate_preview = json.loads(preview.output)["candidates"][0]
    assert candidate_preview.get("occurred_at") is None
    assert "date unknown" in candidate_preview["content"]
    submitted = invoke_import(body, tmp_path)
    assert submitted.exit_code == 0, submitted.output
    receipt = json.loads(submitted.output)
    candidate_id = receipt["candidate_ids"][0]
    pack = client.post("/api/curation/source-packs", json={}).json()
    assert cur._validate_source_pack(pack, config, None)
    packed = pack["groups"][0]["candidates"][0]
    assert len(packed["evidence"]) == len(body["sources"])
    undated = next(e for e in packed["evidence"] if e["occurred_at"] is None)
    assert undated["material_provenance"]["source_date_status"] == "unknown"
    planner = SyntheticPlanner()  # deliberately requests autoaccept, no recency keywords
    result = cur.run_curation(config, planner, transport=pcr_transport(client))
    assert result["ok"], result
    assert counts(client)["observations"] == 0
    candidate = client.get("/api/candidates/" + candidate_id).json()
    assert candidate["status"] == "pending"
    run = client.get("/api/curation/runs").json()["items"][0]
    decision = client.get("/api/curation/runs/" + run["id"]).json()["decisions"][0]
    assert decision["status"] == "blocked"
    assert "material_source_date_unknown" in decision["reason_codes"]
    accepted = client.post("/api/candidates/" + candidate_id + "/accept")
    assert accepted.status_code == 200, accepted.text
    observation = canonical(client, candidate_id)
    assert observation["occurred_at"] is None
    assert observation["content"] == candidate_preview["content"]
    assert observation["claim_type"] == ("fact" if kind == "sourced_report" else "inference")
    evidence = client.get("/api/candidates/" + candidate_id).json()["evidence"]
    assert len(evidence) == len(body["sources"])
    with client.app.state.session_factory() as session:
        assert session.get(Episode, undated["episode_id"]).occurred_at is None
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
def test_existing_warning_and_planner_budget_use_manual_route(staged, pcr, case):
    client, headers, body = staged
    cur, config = pcr
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
    pack = client.post("/api/curation/source-packs", json={}).json()
    c = pack["groups"][0]["candidates"][0]
    assert cur._validate_source_pack(pack, config, None)
    result = cur.run_curation(config, SyntheticPlanner(), transport=pcr_transport(client))
    if case == "long_multisource":
        assert len(c["payload"]["content"]) > 300
        assert not result["ok"], result
        assert "model_output_schema_invalid" in json.dumps(result)
    else:
        assert c["validation_warnings"], c
        assert result["ok"], result
        run = client.get("/api/curation/runs").json()["items"][0]
        decision = client.get("/api/curation/runs/" + run["id"]).json()["decisions"][0]
        assert decision["status"] == "blocked"
    assert counts(client)["observations"] == 0
    accepted = client.post("/api/candidates/" + candidate_id + "/accept")
    assert accepted.status_code == 200, accepted.text
    observation = canonical(client, candidate_id)
    assert observation["content"] == c["payload"]["content"]
    if case == "korean_inference":
        assert observation["claim_type"] == "inference"
        assert observation["occurred_at"] is None


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
    response = client.post("/api/material-imports/submit", json=body, headers=headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
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
