from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base
from kinlayer_backend.models import Candidate, CurationDecision, CurationRun


def curation_client(database_url: str, mode: str) -> TestClient:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    return TestClient(create_app({"database_url": database_url, "curation_mode": mode}))


def empty_plan(mode: str) -> dict:
    return {
        "mode": mode,
        "policy_version": "curation-policy-v1",
        "input_candidate_count": 0,
        "decisions": [],
    }


def test_disabled_mode_rejects_preparation_and_planning(client) -> None:
    assert client.post("/api/curation/source-packs", json={}).status_code == 409
    assert client.post("/api/curation/runs", json=empty_plan("disabled")).status_code == 409


def test_shadow_api_prepares_and_plans_without_execution(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        source_pack = client.post("/api/curation/source-packs", json={"limit": 10})
        created = client.post("/api/curation/runs", json=empty_plan("shadow"))

        assert source_pack.status_code == 200
        assert source_pack.json()["diagnostics"]["selection"] == "pending_candidates_keyset"
        assert created.status_code == 201
        assert created.json()["status"] == "ready"
        run_id = created.json()["id"]
        assert client.get(f"/api/curation/runs/{run_id}").status_code == 200
        blocked = client.post(f"/api/curation/runs/{run_id}/execute")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "shadow_mode"


def test_apply_api_executes_and_resumes_empty_run_idempotently(database_url: str) -> None:
    with curation_client(database_url, "apply") as client:
        created = client.post("/api/curation/runs", json=empty_plan("apply"))
        assert created.status_code == 201
        run_id = created.json()["id"]

        executed = client.post(f"/api/curation/runs/{run_id}/execute")
        resumed = client.post(f"/api/curation/runs/{run_id}/resume")

        assert executed.status_code == 200
        assert executed.json()["status"] == "completed"
        assert resumed.status_code == 200
        assert resumed.json()["id"] == run_id


def test_run_mode_must_match_server_configuration(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        response = client.post("/api/curation/runs", json=empty_plan("apply"))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "curation_mode_mismatch"


def test_run_policy_version_must_match_server_configuration(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        stale = empty_plan("shadow")
        stale["policy_version"] = "stale-policy"
        response = client.post("/api/curation/runs", json=stale)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "curation_policy_mismatch"


def test_execution_rechecks_persisted_policy_version(database_url: str) -> None:
    with curation_client(database_url, "apply") as client:
        run_id = client.post("/api/curation/runs", json=empty_plan("apply")).json()["id"]
        client.app.state.settings.curation_policy_version = "curation-policy-v2"
        response = client.post(f"/api/curation/runs/{run_id}/execute")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "curation_policy_mismatch"


def test_nested_raw_or_unbounded_curation_json_never_persists(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        raw = empty_plan("shadow")
        raw["diagnostics"] = {"safe": [{"raw_provider_response": "RAW_TRANSCRIPT secret"}]}
        oversized = empty_plan("shadow")
        oversized["diagnostics"] = {"note": "x" * 9000}
        too_deep = empty_plan("shadow")
        nested = {}
        cursor = nested
        for _ in range(8):
            cursor["next"] = {}
            cursor = cursor["next"]
        too_deep["diagnostics"] = nested
        proposed = empty_plan("shadow")
        proposed["input_candidate_count"] = 1
        proposed["decisions"] = [
            {
                "action": "defer",
                "risk_level": "low",
                "candidate_ids": ["candidate-id"],
                "target_entity_id": None,
                "proposed_payload": {"nested": [{"tool": "RAW_TRANSCRIPT secret"}]},
                "evidence_episode_ids": [],
                "reason_codes": [],
                "policy_version": "curation-policy-v1",
                "idempotency_key": "raw-json-rejected",
                "planner": {"name": "test", "model": None, "version": "v1"},
            }
        ]

        raw_response = client.post("/api/curation/runs", json=raw)
        assert raw_response.status_code == 422
        assert "RAW_TRANSCRIPT" not in raw_response.text
        assert "secret" not in raw_response.text
        assert client.post("/api/curation/runs", json=oversized).status_code == 422
        assert client.post("/api/curation/runs", json=too_deep).status_code == 422
        assert client.post("/api/curation/runs", json=proposed).status_code == 422
        with client.app.state.session_factory() as session:
            assert session.query(CurationRun).count() == 0
            assert session.query(CurationDecision).count() == 0
        safe = client.post("/api/curation/runs", json=empty_plan("shadow"))
        assert safe.status_code == 201
        readback = client.get(f"/api/curation/runs/{safe.json()['id']}").text
        assert "RAW_TRANSCRIPT" not in readback
        assert "raw_provider_response" not in readback


def test_run_rejects_decision_candidate_outside_server_source_window(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        with client.app.state.session_factory() as session:
            candidates = [
                Candidate(
                    candidate_type="new_entity",
                    payload={"entity_type": "person", "display_name": name},
                    confidence=0.8,
                    sensitivity="low",
                    status="pending",
                    created_by="user",
                )
                for name in ["Casey Window One", "Casey Window Two"]
            ]
            session.add_all(candidates)
            session.commit()
            candidate_ids = [candidate.id for candidate in candidates]

        pack = client.post("/api/curation/source-packs", json={"limit": 1}).json()
        assert pack["input_candidate_count"] == 1
        packed_id = pack["groups"][0]["candidates"][0]["id"]
        outside_id = next(candidate_id for candidate_id in candidate_ids if candidate_id != packed_id)
        plan = {
            "mode": "shadow",
            "cursor_started_at": pack["cursor_started"]["created_at"],
            "cursor_started_id": pack["cursor_started"]["candidate_id"],
            "cursor_completed_at": pack["cursor_completed"]["created_at"],
            "cursor_completed_id": pack["cursor_completed"]["candidate_id"],
            "policy_version": "curation-policy-v1",
            "input_candidate_count": 1,
            "decisions": [
                {
                    "action": "defer",
                    "risk_level": "low",
                    "candidate_ids": [outside_id],
                    "target_entity_id": None,
                    "proposed_payload": {},
                    "evidence_episode_ids": [],
                    "reason_codes": [],
                    "policy_version": "curation-policy-v1",
                    "idempotency_key": "outside-pack",
                    "planner": {"name": "test", "model": None, "version": "v1"},
                }
            ],
        }

        response = client.post("/api/curation/runs", json=plan)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "candidate_outside_source_pack"
        with client.app.state.session_factory() as session:
            assert session.query(CurationRun).count() == 0

        plan["decisions"][0]["candidate_ids"] = [packed_id]
        plan["decisions"][0]["idempotency_key"] = "inside-pack"
        accepted = client.post("/api/curation/runs", json=plan)
        assert accepted.status_code == 201
        assert accepted.json()["diagnostics"]["source_pack_candidate_count"] == 1
