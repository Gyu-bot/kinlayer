from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


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
