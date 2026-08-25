from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine, create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import (
    AgentWriteOperationAudit,
    Base,
    Candidate,
    CandidateEvidence,
    Entity,
    EntityMerge,
    Episode,
    ReconciliationAction,
)
from kinlayer_backend.repositories.reconciliation import ReconciliationRepository
from kinlayer_backend.schemas.reconciliation import ReconciliationActionCreate
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.reconciliation import (
    ReconciliationService,
    candidate_evidence_digest,
    candidate_payload_digest,
    entity_digest,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def valid_action_payload(**overrides) -> dict:
    candidate_id = "candidate-1"
    payload = {
        "resolution_id": "discord:message-1",
        "action": "reject_candidates",
        "candidate_ids": [candidate_id],
        "expected_candidates": [
            {
                "id": candidate_id,
                "status": "pending",
                "updated_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
                "payload_digest": SHA_A,
                "evidence_digest": SHA_B,
            }
        ],
        "target_entity_id": None,
        "canonical_name": None,
        "display_name": None,
        "resolution_note": "user rejected this identity",
        "source": {
            "user_explicit": True,
            "source_type": "agent_conversation",
            "source_ref": "discord:channel/message-1",
            "source_actor": "user",
            "body_hash": SHA_A,
        },
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), "raw provider payload"),
        (("source", "reply_text"), "the user's raw reply"),
        (("source", "user_explicit"), False),
        (("source", "source_actor"), "ai_agent"),
        (("source", "source_type"), "discord_raw_payload"),
        (("source", "body_hash"), "not-a-digest"),
        (("expected_candidates", 0, "payload_digest"), "sha256:short"),
    ],
)
def test_reconciliation_request_is_closed_and_privacy_guarded(path, value) -> None:
    payload = deepcopy(valid_action_payload())
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value

    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)


def test_reconciliation_request_enforces_collection_and_text_bounds() -> None:
    payload = valid_action_payload(resolution_note="x" * 501)
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)

    ids = [f"candidate-{index}" for index in range(51)]
    expected = [
        {
            "id": candidate_id,
            "status": "pending",
            "updated_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
            "payload_digest": SHA_A,
            "evidence_digest": SHA_B,
        }
        for candidate_id in ids
    ]
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(
            valid_action_payload(candidate_ids=ids, expected_candidates=expected)
        )


def test_reconciliation_request_requires_exact_unique_candidate_snapshot_set() -> None:
    duplicate = valid_action_payload(candidate_ids=["candidate-1", "candidate-1"])
    duplicate["expected_candidates"] *= 2
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(duplicate)

    mismatched = valid_action_payload(candidate_ids=["candidate-2"])
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(mismatched)


@pytest.mark.parametrize(
    "payload",
    [
        valid_action_payload(action="map_to_existing_entity", target_entity_id=None),
        valid_action_payload(action="reject_candidates", target_entity_id="entity-1"),
        valid_action_payload(action="rename_and_accept_new_entity", display_name=None),
        valid_action_payload(action="reject_candidates", display_name="Alex"),
    ],
)
def test_reconciliation_action_specific_fields_are_closed(payload) -> None:
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)


def reconciliation_client(database_url: str, **overrides) -> TestClient:
    settings = {"database_url": database_url, **overrides}
    engine = create_db_engine(Settings(**settings))
    Base.metadata.create_all(engine)
    return TestClient(create_app(settings))


def create_new_entity_candidate(client: TestClient, name: str) -> dict:
    response = client.post(
        "/api/candidates",
        json={
            "candidate_type": "new_entity",
            "payload": {"entity_type": "person", "display_name": name},
            "confidence": 0.9,
            "created_by": "user",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_evidenced_new_entity_candidate(client: TestClient, name: str) -> tuple[dict, dict]:
    episode_response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": f"thread:{name}",
            "source_description": "Named by user",
            "body_excerpt": f"I met {name} today.",
            "body_hash": SHA_B,
            "actor": "user",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert episode_response.status_code == 201
    episode = episode_response.json()
    response = client.post(
        "/api/candidates",
        json={
            "candidate_type": "new_entity",
            "payload": {"entity_type": "person", "display_name": name},
            "confidence": 0.9,
            "created_by": "ai_agent",
            "evidence": [
                {
                    "episode_id": episode["id"],
                    "excerpt": f"I met {name} today.",
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), episode


def action_for(database_url: str, candidate_ids: list[str], **overrides) -> dict:
    factory = create_session_maker(Settings(database_url=database_url))
    expected = []
    with factory() as session:
        for candidate_id in candidate_ids:
            candidate = session.get(Candidate, candidate_id)
            assert candidate is not None
            expected.append(
                {
                    "id": candidate.id,
                    "status": candidate.status,
                    "updated_at": candidate.updated_at.isoformat(),
                    "payload_digest": candidate_payload_digest(candidate),
                    "evidence_digest": candidate_evidence_digest(session, candidate.id),
                }
            )
        if overrides.get("action") == "map_to_existing_entity":
            target = session.get(Entity, overrides.get("target_entity_id"))
            assert target is not None
            overrides.setdefault(
                "expected_entities",
                [
                    {
                        "id": target.id,
                        "status": target.status,
                        "updated_at": target.updated_at.isoformat(),
                        "entity_digest": entity_digest(target),
                    }
                ],
            )
    payload = valid_action_payload(
        candidate_ids=candidate_ids,
        expected_candidates=expected,
        resolution_id=f"resolution:{candidate_ids[0]}",
    )
    payload.update(overrides)
    return payload


def entity_action_for(database_url: str, action: str, entity_ids: list[str], **overrides) -> dict:
    factory = create_session_maker(Settings(database_url=database_url))
    expected = []
    with factory() as session:
        for entity_id in entity_ids:
            entity = session.get(Entity, entity_id)
            assert entity is not None
            expected.append(
                {
                    "id": entity.id,
                    "status": entity.status,
                    "updated_at": entity.updated_at.isoformat(),
                    "entity_digest": entity_digest(entity),
                }
            )
    payload = valid_action_payload(
        resolution_id=f"resolution:{action}:{entity_ids[0]}",
        action=action,
        candidate_ids=[],
        expected_candidates=[],
        expected_entities=expected,
        source_entity_id=entity_ids[0],
    )
    if action == "merge_existing_entities":
        payload["target_entity_id"] = entity_ids[1]
    payload.update(overrides)
    return payload


def create_reviewed_entity(client: TestClient, name: str) -> tuple[dict, dict]:
    candidate = create_new_entity_candidate(client, name)
    accepted = client.post(
        f"/api/candidates/{candidate['id']}/accept",
        json={"resolved_by": "user", "resolution_note": "Reviewed recent person."},
    )
    assert accepted.status_code == 200, accepted.text
    entity_id = accepted.json()["canonical_record_ref"].split(":", 1)[1]
    entity = client.get(f"/api/entities/{entity_id}")
    assert entity.status_code == 200
    return candidate, entity.json()


def test_reconciliation_routes_are_disabled_without_dedicated_token(database_url) -> None:
    with reconciliation_client(database_url) as client:
        assert client.post("/api/reconciliation/actions", json={}).status_code == 404
        assert client.get("/api/reconciliation/actions/missing").status_code == 404


def test_reconciliation_routes_require_only_dedicated_token(database_url) -> None:
    with reconciliation_client(
        database_url, reconciliation_token="reconcile-secret", api_token="broad-secret"
    ) as client:
        assert client.get("/api/reconciliation/actions/missing").status_code == 401
        assert (
            client.get(
                "/api/reconciliation/actions/missing",
                headers={"Authorization": "Bearer broad-secret"},
            ).status_code
            == 401
        )
        response = client.get(
            "/api/reconciliation/actions/missing",
            headers={"Authorization": "Bearer reconcile-secret"},
        )
        assert response.status_code == 404


def test_reconciliation_entity_snapshots_are_token_gated_and_exact(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        entity = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Snapshot Person", "created_by": "user"},
        ).json()
        assert client.get("/api/reconciliation/entity-snapshots").status_code == 401

        response = client.get(
            "/api/reconciliation/entity-snapshots?limit=200&offset=0", headers=headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == entity["id"]
        assert body["items"][0]["entity_digest"].startswith("sha256:")


def test_reject_is_atomic_verified_and_idempotent(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        first = create_new_entity_candidate(client, "Alex Kim")
        second = create_new_entity_candidate(client, "Alex Kimm")
        request = action_for(database_url, [second["id"], first["id"]])

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == body["verification_state"] == "verified"
        assert [row["id"] for row in body["candidates"]] == sorted(
            [first["id"], second["id"]]
        )
        assert {row["status"] for row in body["candidates"]} == {"rejected"}
        assert body["confirmation_episode_id"]

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200
        assert retry.json()["id"] == body["id"]
        changed = deepcopy(request)
        changed["resolution_note"] = "same key, different confirmed decision"
        conflict = client.post(
            "/api/reconciliation/actions", headers=headers, json=changed
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"

        changed = deepcopy(request)
        changed["resolution_note"] = "different user decision"
        conflict = client.post("/api/reconciliation/actions", headers=headers, json=changed)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.query(ReconciliationAction).count() == 1
        episode = session.get(Episode, body["confirmation_episode_id"])
        assert episode is not None
        assert episode.actor == "user"
        assert episode.body_excerpt == request["resolution_note"]


def test_stale_snapshot_rolls_back_action_and_confirmation(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "Casey Park")
        request = action_for(database_url, [candidate["id"]])
        request["expected_candidates"][0]["payload_digest"] = SHA_B
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "stale_candidate"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.get(Candidate, candidate["id"]).status == "pending"
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


def test_group_mutation_failure_rolls_back_every_candidate_and_ledger(
    database_url, monkeypatch
) -> None:
    settings = {"database_url": database_url, "reconciliation_token": "reconcile-secret"}
    engine = create_db_engine(Settings(**settings))
    Base.metadata.create_all(engine)
    original = CandidateService._resolve
    calls = 0

    def fail_second_resolution(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated grouped mutation failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CandidateService, "_resolve", fail_second_resolution)
    headers = {"Authorization": "Bearer reconcile-secret"}
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        first = create_new_entity_candidate(client, "Rollback One")
        second = create_new_entity_candidate(client, "Rollback Two")
        request = action_for(database_url, [first["id"], second["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 500

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert {
            session.get(Candidate, first["id"]).status,
            session.get(Candidate, second["id"]).status,
        } == {"pending"}
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


def test_candidate_locks_are_acquired_in_deterministic_id_order(database_url) -> None:
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        first = create_new_entity_candidate(client, "First Person")
        second = create_new_entity_candidate(client, "Second Person")

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        locked = ReconciliationRepository(session).lock_candidates(
            [second["id"], first["id"]]
        )
        assert [candidate.id for candidate in locked] == sorted([first["id"], second["id"]])


def test_confirm_group_creates_exactly_one_entity_and_preserves_evidence_readback(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        first = create_new_entity_candidate(client, "Jordan Lee")
        second = create_new_entity_candidate(client, "Jordan Lee")
        request = action_for(
            database_url,
            [second["id"], first["id"]],
            action="confirm_new_entity_group",
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["entity"]["display_name"] in {"Jordan Lee", "Jordan Lee"}
        assert {row["status"] for row in body["candidates"]} == {
            "accepted",
            "superseded",
        }
        assert len(set(body["canonical_refs"])) == 1

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        people = session.query(Entity).filter(Entity.display_name.like("Jordan L%")).all()
        assert len(people) == 1


@pytest.mark.parametrize("canonical_name", ["manager", "Self"])
def test_confirm_group_rejects_unsafe_canonical_name(
    database_url, canonical_name
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=True,
        self_name="Self",
    ) as client:
        candidate = create_new_entity_candidate(client, "Safe Display Name")
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            stored = session.get(Candidate, candidate["id"])
            stored.payload = {**stored.payload, "canonical_name": canonical_name}
            session.commit()
        request = action_for(
            database_url,
            [candidate["id"]],
            action="confirm_new_entity_group",
        )
        response = client.post(
            "/api/reconciliation/actions", headers=headers, json=request
        )
        assert response.status_code in {403, 422}

    with factory() as session:
        assert session.get(Candidate, candidate["id"]).status == "pending"
        assert (
            session.query(Entity)
            .filter(Entity.display_name == "Safe Display Name")
            .count()
            == 0
        )


def test_action_readback_contains_exact_candidate_evidence(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate, evidence_episode = create_evidenced_new_entity_candidate(client, "Avery Song")
        request = action_for(database_url, [candidate["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["candidates"][0]["evidence_episode_ids"] == [evidence_episode["id"]]
        get_response = client.get(
            f"/api/reconciliation/actions/{body['id']}", headers=headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["candidates"] == body["candidates"]


@pytest.mark.parametrize(
    "unsafe_name", ["Self", "manager", "교수님", "전무님", "he", "friend", "Mr."]
)
def test_rename_protects_self_and_role_titles(database_url, unsafe_name) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=True,
        self_name="Self",
    ) as client:
        candidate = create_new_entity_candidate(client, "Unknown Person")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name=unsafe_name,
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code in {403, 422}


def test_map_to_existing_entity_sets_all_exact_refs(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        entity_response = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Taylor", "created_by": "user"},
        )
        assert entity_response.status_code == 201
        target = entity_response.json()
        first = create_new_entity_candidate(client, "Tayler")
        second = create_new_entity_candidate(client, "T Taylor")
        request = action_for(
            database_url,
            [first["id"], second["id"]],
            action="map_to_existing_entity",
            target_entity_id=target["id"],
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["primary_entity_id"] == target["id"]
        assert body["canonical_refs"] == [f"entities:{target['id']}"]
        assert all(
            row["status"] == "accepted"
            and row["canonical_record_ref"] == f"entities:{target['id']}"
            for row in body["candidates"]
        )


def test_map_to_existing_entity_rejects_stale_target_snapshot(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Target Person", "created_by": "user"},
        ).json()
        candidate = create_new_entity_candidate(client, "Target Persun")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="map_to_existing_entity",
            target_entity_id=target["id"],
        )
        changed = client.patch(
            f"/api/entities/{target['id']}", json={"display_name": "Changed Target Person"}
        )
        assert changed.status_code == 200

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "stale_entity"
        assert client.get(f"/api/candidates/{candidate['id']}").json()["status"] == "pending"


def test_map_cannot_target_protected_self(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=True,
        self_name="Owner Name",
    ) as client:
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            protected = session.query(Entity).filter(Entity.system_role == "self").one()
            protected_id = protected.id
        candidate = create_new_entity_candidate(client, "Owner")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="map_to_existing_entity",
            target_entity_id=protected_id,
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "protected_self"

def test_committed_unverified_retry_is_readback_only(database_url, monkeypatch) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    original = ReconciliationService._readback
    calls = 0

    def fail_first_readback(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated fresh-session outage")
        return original(*args, **kwargs)

    monkeypatch.setattr(ReconciliationService, "_readback", staticmethod(fail_first_readback))
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "Morgan Choi")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name="Morgan Cho",
        )
        first = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert first.status_code == 503
        assert first.json()["error"]["code"] == "readback_unavailable"

        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            ledger = session.query(ReconciliationAction).one()
            assert ledger.status == "committed_unverified"
            entity_count = session.query(Entity).filter(Entity.display_name == "Morgan Cho").count()
            assert entity_count == 1

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "verified"
        assert retry.json()["error_code"] is None
        with factory() as session:
            assert session.query(Entity).filter(Entity.display_name == "Morgan Cho").count() == 1


@pytest.mark.parametrize(
    "payload",
    [
        valid_action_payload(
            action="merge_existing_entities", candidate_ids=[], expected_candidates=[]
        ),
        valid_action_payload(
            action="archive_existing_entity", candidate_ids=[], expected_candidates=[]
        ),
        valid_action_payload(
            action="reject_candidates",
            source_entity_id="entity-1",
            expected_entities=[
                {
                    "id": "entity-1",
                    "status": "active",
                    "updated_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
                    "entity_digest": SHA_A,
                }
            ],
        ),
    ],
)
def test_entity_cleanup_action_shapes_are_closed(payload) -> None:
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)


def test_merge_existing_entities_is_atomic_linked_and_idempotent(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        source = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Alex Duplicate", "created_by": "user"},
        ).json()
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Alex Canonical", "created_by": "user"},
        ).json()
        alias = client.post(
            f"/api/entities/{source['id']}/aliases",
            json={"alias": "Alex D", "created_by": "user"},
        )
        assert alias.status_code == 201
        request = entity_action_for(
            database_url, "merge_existing_entities", [source["id"], target["id"]]
        )

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "verified"
        assert body["source_entity_id"] == source["id"]
        assert body["target_entity_id"] == target["id"]
        assert body["entity"]["id"] == target["id"]
        assert body["context_card"]["aliases"] == ["Alex D"]
        assert len(body["derived_candidate_ids"]) == 1

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200
        assert retry.json()["id"] == body["id"]

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        derived_id = body["derived_candidate_ids"][0]
        derived = session.get(Candidate, derived_id)
        source_row = session.get(Entity, source["id"])
        merge = session.query(EntityMerge).filter_by(candidate_id=derived_id).one()
        assert derived.status == "accepted"
        assert derived.canonical_record_ref == f"entities:{target['id']}"
        assert source_row.status == "merged"
        assert merge.source_entity_id == source["id"]
        assert merge.target_entity_id == target["id"]
        assert session.query(CandidateEvidence).filter_by(candidate_id=derived_id).count() == 1
        assert session.query(AgentWriteOperationAudit).filter_by(candidate_id=derived_id).count() == 1
        assert session.query(EntityMerge).count() == 1


def test_merge_rejects_stale_snapshot_and_rolls_back(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        source = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Stale A", "created_by": "user"}
        ).json()
        target = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Stale B", "created_by": "user"}
        ).json()
        request = entity_action_for(database_url, "merge_existing_entities", [source["id"], target["id"]])
        request["expected_entities"][0]["entity_digest"] = SHA_B
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "stale_entity"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.get(Entity, source["id"]).status == "active"
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(EntityMerge).count() == 0
        assert session.query(Episode).count() == 0


def test_merge_rejects_same_entity_shape_and_protected_self(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url, reconciliation_token="reconcile-secret", bootstrap_self=True, self_name="Self"
    ) as client:
        same = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Same", "created_by": "user"}
        ).json()
        same_request = entity_action_for(database_url, "archive_existing_entity", [same["id"]])
        same_request.update(action="merge_existing_entities", target_entity_id=same["id"])
        same_response = client.post(
            "/api/reconciliation/actions", headers=headers, json=same_request
        )
        assert same_response.status_code == 422

        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            self_id = session.query(Entity).filter_by(system_role="self").one().id
        target = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Other", "created_by": "user"}
        ).json()
        request = entity_action_for(database_url, "merge_existing_entities", [self_id, target["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "protected_self"

        source = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Source", "created_by": "user"},
        ).json()
        target_self_request = entity_action_for(
            database_url, "merge_existing_entities", [source["id"], self_id]
        )
        target_self = client.post(
            "/api/reconciliation/actions", headers=headers, json=target_self_request
        )
        assert target_self.status_code == 403
        assert target_self.json()["error"]["code"] == "protected_self"


def test_merge_ack_loss_retry_does_not_repeat_merge(database_url, monkeypatch) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    original = ReconciliationService._readback
    calls = 0

    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("ack lost")
        return original(*args, **kwargs)

    monkeypatch.setattr(ReconciliationService, "_readback", staticmethod(fail_first))
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        source = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Retry A", "created_by": "user"}
        ).json()
        target = client.post(
            "/api/entities", json={"entity_type": "person", "display_name": "Retry B", "created_by": "user"}
        ).json()
        request = entity_action_for(database_url, "merge_existing_entities", [source["id"], target["id"]])
        assert client.post("/api/reconciliation/actions", headers=headers, json=request).status_code == 503
        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200, retry.text

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.query(EntityMerge).count() == 1
        assert session.query(Candidate).filter_by(candidate_type="merge").count() == 1


def test_archive_existing_entity_requires_empty_reviewed_person(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        _, entity = create_reviewed_entity(client, "Fresh Mistake")
        request = entity_action_for(database_url, "archive_existing_entity", [entity["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["entity"]["status"] == "deleted"
        assert body["context_card"] is None
        assert client.get("/api/entities", params={"q": "Fresh Mistake"}).json()["total"] == 0


def test_archive_accepts_empty_entity_created_by_named_person_curation(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "Auto Created Mistake")
        accepted = client.post(
            f"/api/candidates/{candidate['id']}/accept",
            json={
                "resolved_by": "system",
                "resolution_note": "curation:accept_existing",
            },
        )
        assert accepted.status_code == 200, accepted.text
        entity_id = accepted.json()["canonical_record_ref"].split(":", 1)[1]
        request = entity_action_for(database_url, "archive_existing_entity", [entity_id])

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 200, response.text
        assert response.json()["entity"]["status"] == "deleted"


def test_archive_rejects_entity_with_context_and_preserves_it(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        _, entity = create_reviewed_entity(client, "Context Owner")
        alias = client.post(
            f"/api/entities/{entity['id']}/aliases",
            json={"alias": "Owner Alias", "created_by": "user"},
        )
        assert alias.status_code == 201
        request = entity_action_for(database_url, "archive_existing_entity", [entity["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "entity_has_context"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.get(Entity, entity["id"]).status == "active"
        assert session.query(ReconciliationAction).count() == 0
