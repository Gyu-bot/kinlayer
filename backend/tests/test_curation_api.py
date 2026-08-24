from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base
from kinlayer_backend.models import Candidate, CurationDecision, CurationRun, Observation
from kinlayer_backend.schemas.curation import CurationRunCreate
from kinlayer_backend.services.curation import CurationService


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


def persisted_recovery_run(
    client: TestClient,
    *,
    run_mode: str = "shadow",
    status: str = "pending",
    policy_version: str = "curation-policy-v1",
    key: str = "recovery-decision",
) -> str:
    with client.app.state.session_factory() as session:
        run = CurationService(session).create_run(
            CurationRunCreate.model_validate(
                {
                    "mode": run_mode,
                    "policy_version": policy_version,
                    "input_candidate_count": 1,
                    "decisions": [
                        {
                            "action": "defer",
                            "risk_level": "low",
                            "candidate_ids": ["missing-candidate"],
                            "target_entity_id": None,
                            "proposed_payload": {},
                            "evidence_episode_ids": [],
                            "reason_codes": [],
                            "policy_version": policy_version,
                            "idempotency_key": key,
                            "planner": {"name": "test", "model": None, "version": "v1"},
                        }
                    ],
                }
            )
        )
        run.status = status
        session.commit()
        return run.id


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
        raw_request = empty_plan("shadow")
        raw_request["diagnostics"] = {
            "nested": [{"raw_provider_request": "full prompt request secret"}]
        }
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
                "proposed_payload": {
                    "nested": [{"providerRequest": "full provider prompt secret"}]
                },
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
        request_response = client.post("/api/curation/runs", json=raw_request)
        assert request_response.status_code == 422
        assert "full prompt request secret" not in request_response.text
        assert client.post("/api/curation/runs", json=oversized).status_code == 422
        assert client.post("/api/curation/runs", json=too_deep).status_code == 422
        proposed_response = client.post("/api/curation/runs", json=proposed)
        assert proposed_response.status_code == 422
        assert "full provider prompt secret" not in proposed_response.text
        with client.app.state.session_factory() as session:
            assert session.query(CurationRun).count() == 0
            assert session.query(CurationDecision).count() == 0
        safe = client.post("/api/curation/runs", json=empty_plan("shadow"))
        assert safe.status_code == 201
        readback = client.get(f"/api/curation/runs/{safe.json()['id']}").text
        assert "RAW_TRANSCRIPT" not in readback
        assert "raw_provider_response" not in readback
        assert "provider_request" not in readback


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


def test_api_source_window_requires_complete_exact_once_coverage(database_url: str) -> None:
    with curation_client(database_url, "shadow") as client:
        with client.app.state.session_factory() as session:
            candidates = [
                Candidate(
                    candidate_type="new_entity",
                    payload={"entity_type": "person", "display_name": f"Casey API {index}"},
                    confidence=0.8,
                    sensitivity="low",
                    status="pending",
                    created_by="user",
                )
                for index in range(3)
            ]
            session.add_all(candidates)
            session.commit()
            all_ids = [candidate.id for candidate in candidates]

        pack = client.post("/api/curation/source-packs", json={"limit": 2}).json()
        packed_ids = [
            item["id"]
            for group in pack["groups"]
            for item in group["candidates"]
        ]
        outside_id = next(candidate_id for candidate_id in all_ids if candidate_id not in packed_ids)

        def plan(
            memberships: list[list[str]],
            *,
            input_count: int = 2,
            action: str = "defer",
        ) -> dict:
            return {
                "mode": "shadow",
                "cursor_started_at": pack["cursor_started"]["created_at"],
                "cursor_started_id": pack["cursor_started"]["candidate_id"],
                "cursor_completed_at": pack["cursor_completed"]["created_at"],
                "cursor_completed_id": pack["cursor_completed"]["candidate_id"],
                "policy_version": "curation-policy-v1",
                "input_candidate_count": input_count,
                "decisions": [
                    {
                        "action": action,
                        "risk_level": "low",
                        "candidate_ids": candidate_ids,
                        "target_entity_id": None,
                        "proposed_payload": {},
                        "evidence_episode_ids": [],
                        "reason_codes": [],
                        "policy_version": "curation-policy-v1",
                        "idempotency_key": f"api-coverage:{index}:{action}",
                        "planner": {"name": "test", "model": None, "version": "v1"},
                    }
                    for index, candidate_ids in enumerate(memberships)
                ],
            }

        rejected = [
            (plan([[packed_ids[0]]]), "source_pack_candidate_coverage_mismatch"),
            (plan([[packed_ids[0]], packed_ids]), "duplicate_candidate_membership"),
            (
                plan([[packed_ids[0]], [packed_ids[1]]], input_count=1),
                "source_pack_count_mismatch",
            ),
            (
                plan([[packed_ids[0]], [packed_ids[1]], [outside_id]]),
                "candidate_outside_source_pack",
            ),
            (empty_plan("shadow") | {"input_candidate_count": 1}, "source_pack_empty_run_mismatch"),
        ]
        for payload, expected_code in rejected:
            response = client.post("/api/curation/runs", json=payload)
            assert response.status_code == 409
            assert response.json()["error"]["code"] == expected_code
            with client.app.state.session_factory() as session:
                assert session.query(CurationRun).count() == 0
                assert session.query(CurationDecision).count() == 0

        one_to_one = client.post(
            "/api/curation/runs",
            json=plan([[packed_ids[0]], [packed_ids[1]]]),
        )
        consolidate = client.post(
            "/api/curation/runs",
            json=plan([packed_ids], action="consolidate_accept"),
        )
        assert one_to_one.status_code == 201
        assert consolidate.status_code == 201


def test_resume_recovers_pending_and_planning_shadow_runs_without_writes(
    database_url: str,
) -> None:
    with curation_client(database_url, "shadow") as client:
        pending_id = persisted_recovery_run(client, key="pending-recovery")
        planning_id = persisted_recovery_run(
            client,
            status="planning",
            key="planning-recovery",
        )

        pending = client.post(f"/api/curation/runs/{pending_id}/resume")
        planning = client.post(f"/api/curation/runs/{planning_id}/resume")
        repeated = client.post(f"/api/curation/runs/{pending_id}/resume")

        assert pending.status_code == 200
        assert pending.json()["status"] == "ready"
        assert pending.json()["decisions"][0]["status"] == "blocked"
        assert planning.status_code == 200
        assert planning.json()["status"] == "ready"
        assert repeated.json() == pending.json()
        with client.app.state.session_factory() as session:
            assert session.query(Candidate).count() == 0
            assert session.query(Observation).count() == 0
            assert session.query(CurationDecision).count() == 2


def test_resume_recovers_pending_shadow_after_server_moves_to_apply(database_url: str) -> None:
    with curation_client(database_url, "apply") as client:
        run_id = persisted_recovery_run(client, key="shadow-under-apply")
        recovered = client.post(f"/api/curation/runs/{run_id}/resume")
        repeated = client.post(f"/api/curation/runs/{run_id}/resume")

        assert recovered.status_code == 200
        assert recovered.json()["mode"] == "shadow"
        assert recovered.json()["status"] == "ready"
        assert repeated.json() == recovered.json()
        with client.app.state.session_factory() as session:
            assert session.query(Observation).count() == 0


def test_resume_recovery_rejects_stale_policy_and_preserves_apply_gate(
    database_url: str,
) -> None:
    with curation_client(database_url, "shadow") as client:
        stale_id = persisted_recovery_run(
            client,
            policy_version="stale-policy",
            key="stale-recovery",
        )
        apply_ready_id = persisted_recovery_run(
            client,
            run_mode="apply",
            status="ready",
            key="apply-ready-under-shadow",
        )

        stale = client.post(f"/api/curation/runs/{stale_id}/resume")
        gated = client.post(f"/api/curation/runs/{apply_ready_id}/resume")

        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "curation_policy_mismatch"
        assert gated.status_code == 409
        assert gated.json()["error"]["code"] == "shadow_mode"
        assert client.get(f"/api/curation/runs/{stale_id}").json()["status"] == "pending"
