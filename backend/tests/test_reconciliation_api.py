from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import hmac
import json

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
    EntityEdge,
    EntityFact,
    EntityMerge,
    Episode,
    Observation,
    ObservationEvidence,
    ReconciliationAction,
)
from kinlayer_backend.repositories.reconciliation import ReconciliationRepository
from kinlayer_backend.schemas.reconciliation import ReconciliationActionCreate
from kinlayer_backend.services.candidates import CandidateService
from kinlayer_backend.services.reconciliation import (
    ReconciliationService,
    _utc,
    candidate_evidence_digest,
    candidate_payload_digest,
    entity_digest,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
COMMITMENT_KEY = "test-reconciliation-commitment-key-32-bytes"


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _action_material(payload: dict) -> dict:
    def snapshot(value: dict) -> dict:
        result = deepcopy(value)
        parsed = datetime.fromisoformat(str(result["updated_at"]).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        result["updated_at"] = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return result

    return {
        "resolution_id": payload["resolution_id"],
        "action": payload["action"],
        "candidate_ids": sorted(payload.get("candidate_ids", [])),
        "expected_candidates": sorted(
            (snapshot(item) for item in payload.get("expected_candidates", [])),
            key=lambda item: item["id"],
        ),
        "expected_entities": sorted(
            (snapshot(item) for item in payload.get("expected_entities", [])),
            key=lambda item: item["id"],
        ),
        "source_entity_id": payload.get("source_entity_id"),
        "target_entity_id": payload.get("target_entity_id"),
        "canonical_name": payload.get("canonical_name"),
        "display_name": payload.get("display_name"),
        "relationship_to_self": payload.get("relationship_to_self"),
        "resolution_note": payload["resolution_note"],
        "source": payload["source"],
        "context_claims": payload.get("context_claims", []),
    }


def sign_action(payload: dict, **binding_overrides) -> dict:
    payload = deepcopy(payload)
    claims = payload.get("context_claims", [])
    answer_item_id = str(claims[0]["answer_item_id"] if claims else "item-1")
    material = {
        "version": "pcr-reconciliation-binding.v1",
        "question_id": "rq_test_question",
        "answer_item_id": answer_item_id,
        "item_fingerprint": "sha256:" + "1" * 64,
        "agenda_digest": "sha256:" + "2" * 64,
        "resolution_id": payload["resolution_id"],
        "action": payload["action"],
        "context_claims_digest": _digest(claims),
        "action_digest": _digest(_action_material(payload)),
        **binding_overrides,
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["answer_bindings"] = [{
        **material,
        "commitment": "hmac-sha256:" + hmac.new(
            COMMITMENT_KEY.encode(), raw.encode(), hashlib.sha256
        ).hexdigest(),
    }]
    return payload


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
            "body_hash": "sha256:" + hashlib.sha256(b"user rejected this identity").hexdigest(),
            "body_excerpt": "user rejected this identity",
        },
    }
    payload.update(overrides)
    return sign_action(payload)


def test_reconciliation_action_timestamp_normalization_is_cross_runtime_stable() -> None:
    assert _utc(datetime.fromisoformat("2026-08-25T09:00:00+09:00")) == "2026-08-25T00:00:00Z"
    assert _utc(datetime.fromisoformat("2026-08-25T09:00:00")) == "2026-08-25T09:00:00Z"


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
    ("sensitivity", "ai_use_policy"),
    [("low", "cautious_use"), ("high", "cautious_use"), ("medium", "never_surface")],
)
def test_current_reply_policy_is_fixed_but_legacy_sensitivity_is_ignored(
    sensitivity, ai_use_policy
) -> None:
    payload = valid_action_payload(
        action="rename_and_accept_new_entity",
        display_name="Alex",
        canonical_name="Alex",
        context_claims=[{
            "claim_id": "current-1", "answer_item_id": "item-1",
            "target": "primary_entity", "kind": "observation",
            "observation_type": "stable_fact", "claim_type": "fact",
            "sensitivity": sensitivity, "ai_use_policy": ai_use_policy,
            "evidence": {"evidence_class": "current_reply", "start": 0, "end": 4},
        }],
    )
    if ai_use_policy != "cautious_use":
        with pytest.raises(ValidationError):
            ReconciliationActionCreate.model_validate(payload)
    else:
        assert ReconciliationActionCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        valid_action_payload(action="map_to_existing_entity", target_entity_id=None),
        valid_action_payload(action="reject_candidates", target_entity_id="entity-1"),
        valid_action_payload(action="rename_and_accept_new_entity", display_name=None),
        valid_action_payload(action="reject_candidates", display_name="Alex"),
        valid_action_payload(
            action="accept_existing_entity_observation_group", target_entity_id=None
        ),
        valid_action_payload(
            action="accept_existing_entity_observation_group",
            target_entity_id="entity-1",
            display_name="Alex",
        ),
        valid_action_payload(
            action="accept_existing_entity_observation_group",
            target_entity_id="entity-1",
            relationship_to_self={
                "relation_type": "coworker", "claim_text": "same company"
            },
        ),
    ],
)
def test_reconciliation_action_specific_fields_are_closed(payload) -> None:
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)


def test_existing_observation_group_requires_exact_target_snapshot_shape() -> None:
    snapshot = {
        "id": "entity-1",
        "status": "active",
        "updated_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
        "entity_digest": SHA_A,
    }
    valid = valid_action_payload(
        action="accept_existing_entity_observation_group",
        target_entity_id="entity-1",
        expected_entities=[snapshot],
    )
    assert ReconciliationActionCreate.model_validate(valid).expected_entities[0].id == "entity-1"
    for invalid in (
        {**valid, "expected_entities": []},
        {**valid, "expected_entities": [{**snapshot, "id": "entity-2"}]},
        {**valid, "expected_entities": [snapshot, {**snapshot, "id": "entity-2"}]},
    ):
        with pytest.raises(ValidationError):
            ReconciliationActionCreate.model_validate(invalid)


def test_relationship_to_self_shape_is_closed_and_rename_only() -> None:
    valid = valid_action_payload(
        action="rename_and_accept_new_entity",
        display_name="테스트인물",
        canonical_name="테스트인물",
        relationship_to_self={
            "relation_type": "coworker",
            "claim_text": "테스트인물은 보호된사용자와 같은 회사의 전무",
        },
    )
    assert ReconciliationActionCreate.model_validate(valid).relationship_to_self
    for payload in (
        valid_action_payload(
            relationship_to_self={"relation_type": "coworker", "claim_text": "same company"}
        ),
        {**valid, "relationship_to_self": {**valid["relationship_to_self"], "self_id": "x"}},
        {**valid, "relationship_to_self": {"relation_type": "coworker"}},
    ):
        with pytest.raises(ValidationError):
            ReconciliationActionCreate.model_validate(payload)


class SignedReconciliationClient(TestClient):
    def post(self, url, *args, **kwargs):
        if url == "/api/reconciliation/actions" and isinstance(kwargs.get("json"), dict) and kwargs["json"]:
            kwargs["json"] = sign_action(kwargs["json"])
        return super().post(url, *args, **kwargs)


def reconciliation_client(database_url: str, **overrides) -> TestClient:
    settings = {
        "database_url": database_url,
        "reconciliation_token": None,
        "reconciliation_commitment_key": COMMITMENT_KEY,
        **overrides,
    }
    engine = create_db_engine(Settings(**settings))
    Base.metadata.create_all(engine)
    return SignedReconciliationClient(create_app(settings))


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
    excerpt = f"I met {name} today."
    episode_response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": f"thread:{name}",
            "source_description": "Named by user",
            "body_excerpt": excerpt,
            "body_hash": "sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
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
                    "excerpt": excerpt,
                    "confidence": 0.9,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), episode


def create_observation_candidate(
    client: TestClient,
    target_entity_id: str,
    content: str,
    evidence_episode_id: str | None = None,
    related_entity_ids: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/candidates",
        json={
            "candidate_type": "observation",
            "target_entity_id": target_entity_id,
            "payload": {
                "subject_entity_id": target_entity_id,
                "observation_type": "recent_interaction",
                "content": content,
                "claim_type": "fact",
                **(
                    {"related_entity_ids": related_entity_ids}
                    if related_entity_ids is not None
                    else {}
                ),
            },
            "confidence": 0.9,
            "created_by": "user",
            "evidence": ([{
                "episode_id": evidence_episode_id,
                "excerpt": content,
                "confidence": 0.9,
            }] if evidence_episode_id else []),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_observation_episode(client: TestClient, index: int, content: str) -> dict:
    response = client.post(
        "/api/episodes",
        json={
            "source_type": "agent_conversation",
            "source_ref": f"thread:observation-{index}",
            "source_description": "Reviewed observation source",
            "body_excerpt": content,
            "body_hash": "sha256:" + f"{index:x}" * 64,
            "actor": "user",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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
        if overrides.get("action") in {
            "map_to_existing_entity", "accept_existing_entity_observation_group"
        }:
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
    return sign_action(payload)


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
    return sign_action(payload)


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


@pytest.mark.parametrize("legacy_sensitivity", [True, False])
def test_rich_reconciliation_current_reply_is_atomic_and_span_derived(
    database_url, legacy_sensitivity
) -> None:
    reply = "응 맞아. 맞는데 소개팅 이후 잘 안되서 이제 연락은 안해"
    context = "소개팅 이후 잘 안되서 이제 연락은 안해"
    start = reply.index(context)
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "지민")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name="지민",
            canonical_name="지민",
        )
        request["source"] = {
            "user_explicit": True,
            "source_type": "agent_conversation",
            "source_ref": "discord:private/reply-1",
            "source_actor": "user",
            "body_excerpt": reply,
            "body_hash": "sha256:" + hashlib.sha256(reply.encode()).hexdigest(),
        }
        request["context_claims"] = [{
            "claim_id": "context-1",
            "answer_item_id": "item-1",
            "target": "primary_entity",
            "kind": "observation",
            "observation_type": "follow_up_context",
            "claim_type": "fact",
            "sensitivity": "medium", "ai_use_policy": "cautious_use",
            "evidence": {"evidence_class": "current_reply", "start": start, "end": len(reply)},
        }]
        if not legacy_sensitivity:
            request["context_claims"][0].pop("sensitivity")
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        result = response.json()
        assert [item["kind"] for item in result["context_outcomes"]] == ["observation"]
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            observation = session.query(Observation).filter_by(
                source_candidate_id=result["context_outcomes"][0]["candidate_id"]
            ).one()
            assert observation.subject_entity_id == result["primary_entity_id"]
            assert observation.content == context
            assert observation.sensitivity == "medium"
            assert observation.ai_use_policy == "cautious_use"
            derived = session.get(Candidate, result["context_outcomes"][0]["candidate_id"])
            assert derived.sensitivity == "medium"
            assert derived.payload["ai_use_policy"] == "cautious_use"
            assert session.query(ReconciliationAction).count() == 1


def test_candidate_evidence_hydration_is_token_gated_exact_and_bounded(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate, _ = create_evidenced_new_entity_candidate(client, "Hydrated Person")
        path = f"/api/reconciliation/candidate-evidence-snapshots?candidate_id={candidate['id']}"
        assert client.get(path).status_code == 401
        response = client.get(path, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["id"] for item in body["items"]] == [candidate["id"]]
        assert body["items"][0]["evidence"][0]["excerpt"] == "I met Hydrated Person today."
        assert "body_excerpt" not in body["items"][0]["evidence"][0]
        assert "source_ref" not in body["items"][0]["evidence"][0]
        assert "effective_sensitivity" not in body["items"][0]["evidence"][0]
        assert body["items"][0]["evidence"][0]["effective_ai_use_policy"] == "cautious_use"


def test_candidate_evidence_hydration_rejects_over_twenty_without_leak(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "Over Limit")
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            for index in range(21):
                excerpt = f"private evidence {index}"
                episode = Episode(
                    source_type="agent_conversation",
                    source_ref=f"secret-source:{index}",
                    source_description="private source",
                    body_excerpt=excerpt,
                    body_hash="sha256:" + hashlib.sha256(excerpt.encode()).hexdigest(),
                    actor="user",
                    sensitivity="medium",
                    retention_policy="excerpt_only",
                )
                session.add(episode)
                session.flush()
                session.add(CandidateEvidence(
                    candidate_id=candidate["id"],
                    episode_id=episode.id,
                    excerpt=excerpt,
                    confidence=1.0,
                ))
            session.commit()
        path = f"/api/reconciliation/candidate-evidence-snapshots?candidate_id={candidate['id']}"
        assert client.get(path).status_code == 401
        response = client.get(path, headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "candidate_evidence_limit_exceeded"
        assert "secret-source" not in response.text and "private evidence" not in response.text


def test_answer_binding_rejects_bearer_only_substitution_and_replay(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, "Bound Person")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name="Bound Person",
            canonical_name="Bound Person",
        )
        reply = "same workplace"
        request["source"] = {
            "user_explicit": True,
            "source_type": "agent_conversation",
            "source_ref": "discord:private/bound",
            "source_actor": "user",
            "body_excerpt": reply,
            "body_hash": "sha256:" + hashlib.sha256(reply.encode()).hexdigest(),
        }
        request["context_claims"] = [{
            "claim_id": "bound-claim",
            "answer_item_id": "item-1",
            "target": "primary_entity",
            "kind": "observation",
            "observation_type": "stable_fact",
            "claim_type": "fact",
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "evidence": {"evidence_class": "current_reply", "start": 0, "end": len(reply)},
        }]
        request = sign_action(request)

        hostile = []
        for field, value in (
            ("question_id", "rq_wrong_question"),
            ("item_fingerprint", "sha256:" + "3" * 64),
            ("agenda_digest", "sha256:" + "4" * 64),
        ):
            changed = deepcopy(request)
            changed["answer_bindings"][0][field] = value
            hostile.append(changed)
        wrong_item = deepcopy(request)
        wrong_item["answer_bindings"][0]["answer_item_id"] = "wrong-item"
        wrong_item["context_claims"][0]["answer_item_id"] = "wrong-item"
        hostile.append(wrong_item)
        wrong_claim = deepcopy(request)
        wrong_claim["context_claims"][0]["evidence"]["end"] -= 1
        hostile.append(wrong_claim)
        cross_action = deepcopy(request)
        cross_action["action"] = "confirm_new_entity_group"
        cross_action["display_name"] = None
        cross_action["canonical_name"] = None
        cross_action["answer_bindings"][0]["action"] = "confirm_new_entity_group"
        hostile.append(cross_action)
        omitted = deepcopy(request)
        omitted.pop("answer_bindings")
        duplicate = deepcopy(request)
        duplicate["answer_bindings"] *= 2
        hostile.extend((omitted, duplicate))

        for changed in hostile:
            response = TestClient.post(
                client, "/api/reconciliation/actions", headers=headers, json=changed
            )
            assert response.status_code == 422, response.text
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            assert session.query(ReconciliationAction).count() == 0
            assert session.get(Candidate, candidate["id"]).status == "pending"

        applied = TestClient.post(
            client, "/api/reconciliation/actions", headers=headers, json=request
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["answer_binding"] == request["answer_bindings"][0]
        assert "same workplace" not in json.dumps(applied.json()["answer_binding"])
        assert "discord:private/bound" not in json.dumps(applied.json()["answer_binding"])

        for rebound in (
            sign_action(request, question_id="rq_other_question"),
            sign_action(request, agenda_digest="sha256:" + "5" * 64),
        ):
            conflict = TestClient.post(
                client, "/api/reconciliation/actions", headers=headers, json=rebound
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_reconciliation_answer_binding_requires_separate_key(database_url) -> None:
    with pytest.raises(ValidationError):
        Settings(reconciliation_commitment_key="a" * 31)
    assert Settings(reconciliation_commitment_key="a" * 32).reconciliation_commitment_key == "a" * 32
    with pytest.raises(ValidationError):
        Settings(reconciliation_commitment_key="é" * 15 + "a")
    assert Settings(reconciliation_commitment_key="é" * 16).reconciliation_commitment_key == "é" * 16
    assert Settings(reconciliation_commitment_key=None).reconciliation_commitment_key is None
    assert Settings(reconciliation_commitment_key="").reconciliation_commitment_key is None
    with pytest.raises(ValidationError):
        Settings(
            reconciliation_token="same-secret-value-that-is-at-least-32-bytes",
            reconciliation_commitment_key="same-secret-value-that-is-at-least-32-bytes",
        )
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        reconciliation_commitment_key=None,
    ) as client:
        candidate = create_new_entity_candidate(client, "Bearer Only")
        request = action_for(database_url, [candidate["id"]])
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "reconciliation_binding_unavailable"
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            assert session.query(ReconciliationAction).count() == 0
            assert session.get(Candidate, candidate["id"]).status == "pending"


def test_prepared_candidate_evidence_writes_exact_span(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    prior = "민수는 같은 회사의 동료야"
    body_hash = "sha256:" + hashlib.sha256(prior.encode()).hexdigest()
    with reconciliation_client(
        database_url, reconciliation_token="reconcile-secret", bootstrap_self=True
    ) as client:
        episode = client.post("/api/episodes", json={
            "source_type": "agent_conversation", "source_ref": "thread:prepared",
            "source_description": "Prior user evidence", "body_excerpt": prior,
            "body_hash": body_hash, "actor": "user", "sensitivity": "high",
            "retention_policy": "excerpt_only",
        }).json()
        candidate = client.post("/api/candidates", json={
            "candidate_type": "new_entity",
            "payload": {
                "entity_type": "person", "display_name": "민수",
                "ai_use_policy": "never_surface",
            },
            "confidence": 0.9, "created_by": "ai_agent", "sensitivity": "high",
            "evidence": [{"episode_id": episode["id"], "excerpt": prior, "confidence": 0.9}],
        }).json()
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            evidence = session.query(CandidateEvidence).filter_by(candidate_id=candidate["id"]).one()
        request = action_for(
            database_url, [candidate["id"]], action="rename_and_accept_new_entity",
            display_name="민수", canonical_name="민수",
        )
        request["context_claims"] = [{
            "claim_id": "prepared-1", "answer_item_id": "item-1",
            "target": "primary_entity", "kind": "relationship_edge",
            "relation_type": "coworker", "claim_type": "fact",
            "sensitivity": "high", "ai_use_policy": "never_surface",
            "evidence": {
                "evidence_class": "prepared_candidate_evidence",
                "candidate_id": candidate["id"], "evidence_id": evidence.id,
                "episode_id": episode["id"], "body_hash": body_hash,
                "excerpt_hash": "sha256:" + hashlib.sha256(prior.encode()).hexdigest(),
                "start": 0, "end": len(prior),
            },
        }]
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        with factory() as session:
            edge = session.query(EntityEdge).filter_by(
                source_candidate_id=response.json()["context_outcomes"][0]["candidate_id"]
            ).one()
            assert edge.claim_text == prior
            assert edge.sensitivity == "medium"  # Inert storage default, not propagated.
            assert edge.ai_use_policy == "cautious_use"  # Obsolete permission is not propagated.
            derived = session.get(Candidate, edge.source_candidate_id)
            assert derived.sensitivity == "medium"
            assert derived.payload["ai_use_policy"] == "never_surface"
            action = session.get(ReconciliationAction, response.json()["id"])
            assert "sensitivity" not in action.readback_summary["context_manifest"][0]
            assert action.readback_summary["context_manifest"][0]["ai_use_policy"] == "never_surface"
            action.status = "committed_unverified"
            edge.ai_use_policy = "cautious_use"
            session.commit()
        readback = client.get(
            f"/api/reconciliation/actions/{response.json()['id']}", headers=headers
        )
        assert readback.status_code == 200
        with factory() as session:
            action = session.get(ReconciliationAction, response.json()["id"])
            action.status = "committed_unverified"
            stored_edge = session.get(EntityEdge, edge.id)
            stored_edge.claim_text = "Changed canonical claim"
            session.commit()
        readback = client.get(
            f"/api/reconciliation/actions/{response.json()['id']}", headers=headers
        )
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"


@pytest.mark.parametrize(
    "tamper", ["candidate", "evidence", "episode", "hash", "span", "assistant", "system"]
)
def test_prepared_evidence_mismatch_has_zero_reconciliation_mutation(database_url, tamper) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    prior = "민수는 같은 회사의 동료야"
    body_hash = "sha256:" + hashlib.sha256(prior.encode()).hexdigest()
    with reconciliation_client(
        database_url, reconciliation_token="reconcile-secret", bootstrap_self=True
    ) as client:
        episode = client.post("/api/episodes", json={
            "source_type": "agent_conversation", "source_ref": "thread:negative",
            "source_description": "Prior user evidence", "body_excerpt": prior,
            "body_hash": body_hash,
            "actor": tamper if tamper in {"assistant", "system"} else "user",
            "sensitivity": "medium",
            "retention_policy": "excerpt_only",
        }).json()
        candidate = client.post("/api/candidates", json={
            "candidate_type": "new_entity",
            "payload": {"entity_type": "person", "display_name": "민수"},
            "confidence": 0.9, "created_by": "ai_agent",
            "evidence": [{"episode_id": episode["id"], "excerpt": prior, "confidence": 0.9}],
        }).json()
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            evidence_id = session.query(CandidateEvidence).filter_by(
                candidate_id=candidate["id"]
            ).one().id
        request = action_for(
            database_url, [candidate["id"]], action="rename_and_accept_new_entity",
            display_name="민수", canonical_name="민수",
        )
        prepared = {
            "evidence_class": "prepared_candidate_evidence",
            "candidate_id": candidate["id"], "evidence_id": evidence_id,
            "episode_id": episode["id"], "body_hash": body_hash,
            "excerpt_hash": body_hash, "start": 0, "end": len(prior),
        }
        if tamper == "candidate":
            prepared["candidate_id"] = "unrelated-candidate"
        elif tamper == "evidence":
            prepared["evidence_id"] = "wrong-evidence"
        elif tamper == "episode":
            prepared["episode_id"] = "wrong-episode"
        elif tamper == "hash":
            prepared["excerpt_hash"] = SHA_A
        elif tamper == "span":
            prepared["end"] = len(prior) + 1
        request["context_claims"] = [{
            "claim_id": "prepared-negative", "answer_item_id": "item-1",
            "target": "primary_entity", "kind": "observation",
            "observation_type": "stable_fact", "claim_type": "fact",
            "sensitivity": "medium", "ai_use_policy": "cautious_use",
            "evidence": prepared,
        }]
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 422
        with factory() as session:
            assert session.get(Candidate, candidate["id"]).status == "pending"
            assert session.query(ReconciliationAction).count() == 0
            assert session.query(Observation).count() == 0
            assert session.query(Entity).count() == 1


def test_relationship_dual_representation_rejected_with_zero_write(database_url) -> None:
    payload = valid_action_payload(
        action="rename_and_accept_new_entity", display_name="민수", canonical_name="민수",
        relationship_to_self={"relation_type": "coworker", "claim_text": "동료"},
        context_claims=[{
            "claim_id": "edge-1", "answer_item_id": "item-1", "target": "primary_entity",
            "kind": "relationship_edge", "relation_type": "coworker", "claim_type": "fact",
            "sensitivity": "medium", "ai_use_policy": "cautious_use",
            "evidence": {"evidence_class": "current_reply", "start": 0, "end": 4},
        }],
    )
    with pytest.raises(ValidationError):
        ReconciliationActionCreate.model_validate(payload)
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret"):
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            assert session.query(ReconciliationAction).count() == 0


@pytest.mark.parametrize("kind", ["profile_field", "relationship_edge", "observation"])
def test_context_typed_row_tamper_never_verifies(database_url, kind) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    reply = "민수는 같은 회사 동료야"
    claim = {
        "claim_id": "tamper-1", "answer_item_id": "item-1",
        "target": "primary_entity", "kind": kind, "claim_type": "fact",
        "sensitivity": "medium", "ai_use_policy": "cautious_use",
        "evidence": {"evidence_class": "current_reply", "start": 0, "end": len(reply)},
    }
    if kind == "profile_field":
        claim.update(fact_type="organization", field_path="organization")
    elif kind == "relationship_edge":
        claim["relation_type"] = "coworker"
    else:
        claim["observation_type"] = "stable_fact"
    with reconciliation_client(
        database_url, reconciliation_token="reconcile-secret", bootstrap_self=True
    ) as client:
        candidate = create_new_entity_candidate(client, "민수")
        request = action_for(
            database_url, [candidate["id"]], action="rename_and_accept_new_entity",
            display_name="민수", canonical_name="민수",
        )
        request["source"] = {
            "user_explicit": True, "source_type": "agent_conversation",
            "source_ref": "thread:tamper", "source_actor": "user",
            "body_excerpt": reply,
            "body_hash": "sha256:" + hashlib.sha256(reply.encode()).hexdigest(),
        }
        request["context_claims"] = [claim]
        applied = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert applied.status_code == 200, applied.text
        result = applied.json()
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            action = session.get(ReconciliationAction, result["id"])
            action.status = "committed_unverified"
            candidate_id = result["context_outcomes"][0]["candidate_id"]
            model = {"profile_field": EntityFact, "relationship_edge": EntityEdge,
                     "observation": Observation}[kind]
            row = session.query(model).filter_by(source_candidate_id=candidate_id).one()
            if kind == "profile_field":
                row.content = "tampered"
            elif kind == "relationship_edge":
                row.relation_type = "friend"
            else:
                row.subject_entity_id = session.query(Entity).filter(
                    Entity.id != result["primary_entity_id"], Entity.status == "active"
                ).first().id
            session.commit()
        readback = client.get(f"/api/reconciliation/actions/{result['id']}", headers=headers)
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"


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
        expected = {row["id"]: row for row in request["expected_candidates"]}
        assert all(
            row["candidate_type"] == "new_entity"
            and row["target_entity_id"] is None
            and row["payload_digest"] == expected[row["id"]]["payload_digest"]
            and row["evidence_digest"] == expected[row["id"]]["evidence_digest"]
            for row in body["candidates"]
        )
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
    settings = {
        "database_url": database_url,
        "reconciliation_token": "reconcile-secret",
        "reconciliation_commitment_key": COMMITMENT_KEY,
    }
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
        assert {
            row["target_entity_id"] for row in body["candidates"]
        } == {body["primary_entity_id"]}
        assert len(set(body["canonical_refs"])) == 1

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200
        assert retry.json()["id"] == body["id"]
        assert retry.json()["candidates"] == body["candidates"]

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        people = session.query(Entity).filter(Entity.display_name.like("Jordan L%")).all()
        assert len(people) == 1


@pytest.mark.parametrize(
    ("action_type", "display_name"),
    [
        ("confirm_new_entity_group", None),
        ("rename_and_accept_new_entity", "Verified Person"),
    ],
)
@pytest.mark.parametrize(
    "tamper",
    ["status_order", "target", "canonical_ref", "supersedes", "entity_type", "entity_status"],
)
def test_new_entity_group_linkage_tamper_never_verifies(
    database_url, action_type, display_name, tamper
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        first = create_new_entity_candidate(client, "Unverified Person")
        second = create_new_entity_candidate(client, "Unverified Person")
        request = action_for(
            database_url,
            [second["id"], first["id"]],
            action=action_type,
            display_name=display_name,
        )
        applied = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert applied.status_code == 200, applied.text
        body = applied.json()

        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            action = session.get(ReconciliationAction, body["id"])
            candidates = session.query(Candidate).filter(
                Candidate.id.in_(action.candidate_ids)
            ).order_by(Candidate.id).all()
            primary = session.get(Entity, action.primary_entity_id)
            action.status = "committed_unverified"
            if tamper == "status_order":
                candidates[0].status, candidates[1].status = (
                    candidates[1].status,
                    candidates[0].status,
                )
            elif tamper == "target":
                candidates[1].target_entity_id = None
            elif tamper == "canonical_ref":
                candidates[1].canonical_record_ref = None
            elif tamper == "supersedes":
                candidates[1].supersedes_candidate_id = None
            elif tamper == "entity_type":
                primary.entity_type = "organization"
            else:
                primary.status = "deleted"
            session.commit()

        readback = client.get(
            f"/api/reconciliation/actions/{body['id']}", headers=headers
        )
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"

    with factory() as session:
        action = session.get(ReconciliationAction, body["id"])
        assert action.status == "committed_unverified"
        assert action.error_code == "readback_unavailable"


def test_existing_entity_observation_group_accepts_all_six_with_exact_readback(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    contents = [f"대상인물 관찰 기록 {index}" for index in range(1, 7)]
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        episodes = [
            create_observation_episode(client, index, content)
            for index, content in enumerate(contents, start=1)
        ]
        candidates = [
            create_observation_candidate(client, target["id"], content, episode["id"])
            for content, episode in zip(contents, episodes)
        ]
        request = action_for(
            database_url,
            [candidate["id"] for candidate in reversed(candidates)],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == body["verification_state"] == "verified"
        assert body["primary_entity_id"] == body["target_entity_id"] == target["id"]
        assert body["entity"]["id"] == target["id"]
        assert body["entity"]["status"] == "active"
        assert body["entity"]["updated_at"] == request["expected_entities"][0]["updated_at"]
        assert body["entity"]["entity_digest"] == request["expected_entities"][0]["entity_digest"]
        assert body["confirmation_episode_id"]
        assert len(body["candidates"]) == len(body["canonical_refs"]) == 6
        assert len(set(body["canonical_refs"])) == 6
        assert all(ref.startswith("observations:") for ref in body["canonical_refs"])
        assert all(
            row["status"] == "accepted"
            and row["canonical_record_ref"] in body["canonical_refs"]
            and len(row["evidence_episode_ids"]) == 1
            for row in body["candidates"]
        )

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200
        assert retry.json()["id"] == body["id"]

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        stored_candidates = session.query(Candidate).order_by(Candidate.id).all()
        observations = session.query(Observation).order_by(Observation.id).all()
        target_row = session.get(Entity, target["id"])
        expected_target = request["expected_entities"][0]
        assert session.query(Entity).count() == 1
        assert target_row.status == "active"
        assert target_row.updated_at.isoformat() == expected_target["updated_at"]
        assert entity_digest(target_row) == expected_target["entity_digest"]
        assert len(stored_candidates) == len(observations) == 6
        assert {candidate.status for candidate in stored_candidates} == {"accepted"}
        assert {candidate.resolved_by for candidate in stored_candidates} == {"user"}
        assert {candidate.target_entity_id for candidate in stored_candidates} == {target["id"]}
        assert {candidate.supersedes_candidate_id for candidate in stored_candidates} == {None}
        assert {observation.subject_entity_id for observation in observations} == {target["id"]}
        assert {observation.source_candidate_id for observation in observations} == {
            candidate["id"] for candidate in candidates
        }
        assert {observation.content for observation in observations} == set(contents)
        for candidate in stored_candidates:
            observation = session.query(Observation).filter_by(
                source_candidate_id=candidate.id
            ).one()
            candidate_episode_ids = sorted(
                evidence.episode_id
                for evidence in session.query(CandidateEvidence).filter_by(
                    candidate_id=candidate.id
                )
            )
            observation_episode_ids = sorted(
                evidence.episode_id
                for evidence in session.query(ObservationEvidence).filter_by(
                    observation_id=observation.id
                )
            )
            assert observation_episode_ids == candidate_episode_ids
        assert session.query(ReconciliationAction).count() == 1
        assert session.get(Episode, body["confirmation_episode_id"]) is not None


def test_existing_entity_observation_group_prelocks_full_entity_union_in_order(
    database_url,
    monkeypatch,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        related = [
            client.post(
                "/api/entities",
                json={
                    "entity_type": "person",
                    "display_name": name,
                    "created_by": "user",
                },
            ).json()
            for name in ("관련 인물 A", "관련 인물 Z")
        ]
        candidate = create_observation_candidate(
            client,
            target["id"],
            "관련 인물이 함께 있는 기록",
            related_entity_ids=[related[1]["id"], related[0]["id"]],
        )
        request = action_for(
            database_url,
            [candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )

        locked_entity_ids = []
        original = ReconciliationRepository.lock_entities

        def recording_lock_entities(repository, entity_ids):
            locked_entity_ids.append(list(entity_ids))
            return original(repository, entity_ids)

        monkeypatch.setattr(
            ReconciliationRepository,
            "lock_entities",
            recording_lock_entities,
        )

        response = client.post(
            "/api/reconciliation/actions", headers=headers, json=request
        )

        assert response.status_code == 200, response.text
        assert response.json()["primary_entity_id"] == target["id"]
        assert locked_entity_ids == [
            sorted({target["id"], related[0]["id"], related[1]["id"]})
        ]


def test_existing_entity_observation_group_rejects_mixed_targets_and_types(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        first_target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        second_target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "다른 사람", "created_by": "user"},
        ).json()
        first = create_observation_candidate(client, first_target["id"], "첫 기록")
        second = create_observation_candidate(client, second_target["id"], "둘째 기록")
        mixed_target_request = action_for(
            database_url,
            [first["id"], second["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=first_target["id"],
        )
        mixed_target = client.post(
            "/api/reconciliation/actions", headers=headers, json=mixed_target_request
        )
        assert mixed_target.status_code == 422
        assert mixed_target.json()["error"]["code"] == "validation_error"

        new_entity = create_new_entity_candidate(client, "새 사람")
        mixed_type_request = action_for(
            database_url,
            [first["id"], new_entity["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=first_target["id"],
        )
        mixed_type = client.post(
            "/api/reconciliation/actions", headers=headers, json=mixed_type_request
        )
        assert mixed_type.status_code == 422
        assert mixed_type.json()["error"]["code"] == "validation_error"

        nonpending = create_observation_candidate(
            client, first_target["id"], "이미 재검토가 필요한 기록"
        )
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            session.get(Candidate, nonpending["id"]).status = "needs_clarification"
            session.commit()
        nonpending_request = action_for(
            database_url,
            [nonpending["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=first_target["id"],
        )
        nonpending_response = client.post(
            "/api/reconciliation/actions", headers=headers, json=nonpending_request
        )
        assert nonpending_response.status_code == 422
        assert nonpending_response.json()["error"]["code"] == "validation_error"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert all(
            candidate.status not in {"accepted", "edited_accepted", "superseded"}
            for candidate in session.query(Candidate).all()
        )
        assert session.query(Observation).count() == 0
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


def test_existing_entity_observation_group_rejects_missing_candidate_target_and_stale_snapshot(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        missing_target_response = client.post(
            "/api/candidates",
            json={
                "candidate_type": "observation",
                "payload": {
                    "subject_entity_id": target["id"],
                    "observation_type": "recent_interaction",
                    "content": "대상 열이 비어 있는 기록",
                    "claim_type": "fact",
                },
                "confidence": 0.9,
                "created_by": "user",
            },
        )
        assert missing_target_response.status_code == 201
        missing_target_candidate = missing_target_response.json()
        missing_target_request = action_for(
            database_url,
            [missing_target_candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        missing_target = client.post(
            "/api/reconciliation/actions", headers=headers, json=missing_target_request
        )
        assert missing_target.status_code == 422
        assert missing_target.json()["error"]["code"] == "validation_error"

        stale_candidate = create_observation_candidate(client, target["id"], "오래된 스냅샷")
        stale_request = action_for(
            database_url,
            [stale_candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        stale_request["expected_candidates"][0]["payload_digest"] = SHA_B
        stale = client.post(
            "/api/reconciliation/actions", headers=headers, json=stale_request
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "stale_candidate"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert {candidate.status for candidate in session.query(Candidate).all()} == {"pending"}
        assert session.query(Observation).count() == 0
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


@pytest.mark.parametrize(
    ("target_change", "expected_status", "expected_code"),
    [
        ({"status": "deleted"}, 409, "conflict"),
        ({"entity_type": "organization"}, 422, "validation_error"),
        ({"is_system": True}, 403, "protected_self"),
        ({"is_system": True, "system_role": "self"}, 403, "protected_self"),
        ({"request_target": "missing-target"}, 404, "not_found"),
    ],
)
def test_existing_entity_observation_group_rejects_invalid_target_entity(
    database_url, target_change, expected_status, expected_code
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        candidate = create_observation_candidate(client, target["id"], "대상 검증 기록")
        target_change = dict(target_change)
        request_target = target_change.pop("request_target", None)
        factory = create_session_maker(Settings(database_url=database_url))
        if request_target:
            request = action_for(
                database_url,
                [candidate["id"]],
                action="accept_existing_entity_observation_group",
                target_entity_id=target["id"],
            )
            request["target_entity_id"] = request_target
            request["expected_entities"] = [{
                "id": request_target,
                "status": "active",
                "updated_at": datetime(2026, 8, 25, tzinfo=UTC).isoformat(),
                "entity_digest": SHA_A,
            }]
        else:
            with factory() as session:
                stored_target = session.get(Entity, target["id"])
                for field, value in target_change.items():
                    setattr(stored_target, field, value)
                session.commit()
            request = action_for(
                database_url,
                [candidate["id"]],
                action="accept_existing_entity_observation_group",
                target_entity_id=target["id"],
            )

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == expected_status
        assert response.json()["error"]["code"] == expected_code

    with factory() as session:
        assert session.get(Candidate, candidate["id"]).status == "pending"
        assert session.query(Observation).count() == 0
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


def test_existing_entity_observation_group_rejects_stale_target_snapshot(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        candidate = create_observation_candidate(client, target["id"], "대상 스냅샷 기록")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        changed = client.patch(
            f"/api/entities/{target['id']}", json={"display_name": "변경된 대상인물"}
        )
        assert changed.status_code == 200

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "stale_entity"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.get(Candidate, candidate["id"]).status == "pending"
        assert session.query(Observation).count() == 0
        assert session.query(ReconciliationAction).count() == 0


def test_existing_entity_observation_group_rejects_payload_subject_mismatch(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        other = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "다른 사람", "created_by": "user"},
        ).json()
        candidate_response = client.post(
            "/api/candidates",
            json={
                "candidate_type": "observation",
                "target_entity_id": target["id"],
                "payload": {
                    "subject_entity_id": other["id"],
                    "observation_type": "recent_interaction",
                    "content": "잘못 연결된 관찰",
                    "claim_type": "fact",
                },
                "confidence": 0.9,
                "created_by": "user",
            },
        )
        assert candidate_response.status_code == 201
        candidate = candidate_response.json()
        request = action_for(
            database_url,
            [candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("field", ["canonical_record_ref", "supersedes_candidate_id"])
def test_existing_entity_observation_group_rejects_prelinked_candidate(
    database_url, field
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        candidate = create_observation_candidate(client, target["id"], "이미 연결된 기록")
        other = create_observation_candidate(client, target["id"], "연결 대상 기록")
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            stored = session.get(Candidate, candidate["id"])
            setattr(
                stored,
                field,
                "observations:existing" if field == "canonical_record_ref" else other["id"],
            )
            session.commit()
        request = action_for(
            database_url,
            [candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )

        response = client.post("/api/reconciliation/actions", headers=headers, json=request)

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    with factory() as session:
        assert session.get(Candidate, candidate["id"]).status == "pending"
        assert session.query(Observation).count() == 0
        assert session.query(ReconciliationAction).count() == 0


def test_existing_entity_observation_group_fifth_write_failure_rolls_back(
    database_url, monkeypatch
) -> None:
    settings = {
        "database_url": database_url,
        "reconciliation_token": "reconcile-secret",
        "reconciliation_commitment_key": COMMITMENT_KEY,
    }
    engine = create_db_engine(Settings(**settings))
    Base.metadata.create_all(engine)
    original = CandidateService._resolve
    calls = 0

    def fail_fifth_resolution(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise RuntimeError("simulated fifth observation failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CandidateService, "_resolve", fail_fifth_resolution)
    headers = {"Authorization": "Bearer reconcile-secret"}
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        candidates = [
            create_observation_candidate(client, target["id"], f"원자성 기록 {index}")
            for index in range(6)
        ]
        request = action_for(
            database_url,
            [candidate["id"] for candidate in candidates],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 500

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        stored = session.query(Candidate).all()
        target_row = session.get(Entity, target["id"])
        assert len(stored) == 6
        assert {candidate.status for candidate in stored} == {"pending"}
        assert {candidate.resolved_by for candidate in stored} == {None}
        assert {candidate.canonical_record_ref for candidate in stored} == {None}
        assert target_row.updated_at.isoformat() == request["expected_entities"][0]["updated_at"]
        assert entity_digest(target_row) == request["expected_entities"][0]["entity_digest"]
        assert session.query(Observation).count() == 0
        assert session.query(ObservationEvidence).count() == 0
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).count() == 0


def test_existing_entity_observation_group_readback_tamper_never_verifies(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        episode = create_observation_episode(client, 1, "근거 연결 기록")
        candidate = create_observation_candidate(
            client, target["id"], "근거 연결 기록", episode["id"]
        )
        request = action_for(
            database_url,
            [candidate["id"]],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        applied = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert applied.status_code == 200, applied.text
        body = applied.json()

        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            action = session.get(ReconciliationAction, body["id"])
            action.status = "committed_unverified"
            action.readback_summary = None
            evidence = session.query(ObservationEvidence).one()
            session.delete(evidence)
            session.commit()

        readback = client.get(f"/api/reconciliation/actions/{body['id']}", headers=headers)
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"

    with factory() as session:
        action = session.get(ReconciliationAction, body["id"])
        assert action.status == "committed_unverified"
        assert action.error_code == "readback_unavailable"


def test_existing_entity_observation_group_lost_ack_retry_is_readback_only(
    database_url, monkeypatch
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    original_readback = ReconciliationService._readback
    original_accept = CandidateService.accept_candidate
    readback_calls = 0
    accept_calls = 0

    def fail_first_readback(*args, **kwargs):
        nonlocal readback_calls
        readback_calls += 1
        if readback_calls == 1:
            raise RuntimeError("simulated lost acknowledgement")
        return original_readback(*args, **kwargs)

    def count_accepts(self, *args, **kwargs):
        nonlocal accept_calls
        accept_calls += 1
        return original_accept(self, *args, **kwargs)

    monkeypatch.setattr(ReconciliationService, "_readback", staticmethod(fail_first_readback))
    monkeypatch.setattr(CandidateService, "accept_candidate", count_accepts)
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        target = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "대상인물", "created_by": "user"},
        ).json()
        candidates = [
            create_observation_candidate(client, target["id"], f"재시도 기록 {index}")
            for index in range(6)
        ]
        request = action_for(
            database_url,
            [candidate["id"] for candidate in candidates],
            action="accept_existing_entity_observation_group",
            target_entity_id=target["id"],
        )
        first = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert first.status_code == 503
        assert first.json()["error"]["code"] == "readback_unavailable"

        retry = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert retry.status_code == 200, retry.text
        assert retry.json()["status"] == "verified"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert accept_calls == 6
        assert session.query(Observation).count() == 6
        assert session.query(ReconciliationAction).count() == 1


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


def test_rename_group_with_relationship_to_self_is_atomic_verified_and_idempotent(
    database_url,
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=True,
        self_name="보호된사용자",
    ) as client:
        first = create_new_entity_candidate(client, "전무님")
        second = create_new_entity_candidate(client, "전무님")
        request = action_for(
            database_url,
            [first["id"], second["id"]],
            action="rename_and_accept_new_entity",
            display_name="테스트인물",
            canonical_name="테스트인물",
            relationship_to_self={
                "relation_type": "coworker",
                "claim_text": "테스트인물은 보호된사용자와 같은 회사의 전무",
            },
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == body["verification_state"] == "verified"
        assert {item["status"] for item in body["candidates"]} == {
            "edited_accepted",
            "superseded",
        }
        assert {
            item["target_entity_id"] for item in body["candidates"]
        } == {body["primary_entity_id"]}
        edge_summaries = [
            item for item in body["derived_candidates"]
            if item["candidate_type"] == "relationship_edge"
        ]
        assert len(edge_summaries) == 1
        assert edge_summaries[0]["status"] == "accepted"
        assert edge_summaries[0]["evidence_episode_ids"] == [
            body["confirmation_episode_id"]
        ]

        replay = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert replay.status_code == 200
        assert replay.json()["id"] == body["id"]
        assert replay.json()["candidates"] == body["candidates"]
        changed = deepcopy(request)
        changed["relationship_to_self"]["claim_text"] += "입니다"
        conflict = client.post("/api/reconciliation/actions", headers=headers, json=changed)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        people = session.query(Entity).filter(Entity.display_name == "테스트인물").all()
        assert len(people) == 1
        assert people[0].canonical_name == "테스트인물"
        assert session.query(EntityFact).filter(EntityFact.entity_id == people[0].id).count() == 0
        edge_candidates = session.query(Candidate).filter_by(candidate_type="relationship_edge").all()
        assert len(edge_candidates) == 1
        edge_candidate = edge_candidates[0]
        assert edge_candidate.status == "accepted"
        assert edge_candidate.resolved_by == "user"
        assert edge_candidate.payload["properties"] == {}
        edge = session.query(EntityEdge).filter_by(source_candidate_id=edge_candidate.id).one()
        protected = session.query(Entity).filter_by(system_role="self").one()
        assert edge.from_entity_id == protected.id
        assert edge.to_entity_id == people[0].id
        assert edge.relation_type == "coworker"
        assert edge.claim_text == "테스트인물은 보호된사용자와 같은 회사의 전무"
        assert session.query(EntityEdge).count() == 1
        assert session.query(ReconciliationAction).count() == 1


@pytest.mark.parametrize("bootstrap_self", [False, True])
def test_relationship_precommit_validation_failure_rolls_back_everything(
    database_url, bootstrap_self
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=bootstrap_self,
        self_name="보호된사용자",
    ) as client:
        first = create_new_entity_candidate(client, "전무님")
        second = create_new_entity_candidate(client, "전무님")
        request = action_for(
            database_url,
            [first["id"], second["id"]],
            action="rename_and_accept_new_entity",
            display_name="테스트인물",
            canonical_name="테스트인물",
            relationship_to_self={
                "relation_type": "not-an-allowed-edge" if bootstrap_self else "coworker",
                "claim_text": "테스트인물은 보호된사용자와 같은 회사의 전무",
            },
        )
        response = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert response.status_code in {409, 422}

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.query(Candidate).filter_by(candidate_type="new_entity").count() == 2
        assert {item.status for item in session.query(Candidate).all()} == {"pending"}
        assert session.query(Candidate).filter_by(candidate_type="relationship_edge").count() == 0
        assert session.query(Entity).filter_by(display_name="테스트인물").count() == 0
        assert session.query(EntityEdge).count() == 0
        assert session.query(ReconciliationAction).count() == 0
        assert session.query(Episode).filter_by(
            source_description="Explicit user reconciliation confirmation"
        ).count() == 0


def test_relationship_readback_mismatch_never_verifies(database_url) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(
        database_url,
        reconciliation_token="reconcile-secret",
        bootstrap_self=True,
        self_name="보호된사용자",
    ) as client:
        candidate = create_new_entity_candidate(client, "전무님")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name="테스트인물",
            canonical_name="테스트인물",
            relationship_to_self={
                "relation_type": "coworker",
                "claim_text": "테스트인물은 보호된사용자와 같은 회사의 전무",
            },
        )
        applied = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert applied.status_code == 200, applied.text
        body = applied.json()

        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            action = session.get(ReconciliationAction, body["id"])
            action.status = "committed_unverified"
            action.readback_summary = None
            edge = session.query(EntityEdge).one()
            edge.claim_text = "tampered claim"
            session.commit()

        readback = client.get(
            f"/api/reconciliation/actions/{body['id']}", headers=headers
        )
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"

    with factory() as session:
        action = session.get(ReconciliationAction, body["id"])
        assert action.status == "committed_unverified"
        assert action.error_code == "readback_unavailable"


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
        assert retry.json()["answer_binding"] == sign_action(request)["answer_bindings"][0]
        with factory() as session:
            assert session.query(Entity).filter(Entity.display_name == "Morgan Cho").count() == 1
            ledger = session.query(ReconciliationAction).one()
            assert ledger.readback_summary["answer_binding"] == retry.json()["answer_binding"]


@pytest.mark.parametrize(
    "tamper",
    ["commitment", "question_id", "answer_item_id", "action_digest", "missing_key"],
)
def test_committed_unverified_readback_rejects_stored_binding_tamper(
    database_url, tamper
) -> None:
    headers = {"Authorization": "Bearer reconcile-secret"}
    with reconciliation_client(database_url, reconciliation_token="reconcile-secret") as client:
        candidate = create_new_entity_candidate(client, f"Stored Binding {tamper}")
        request = action_for(
            database_url,
            [candidate["id"]],
            action="rename_and_accept_new_entity",
            display_name=f"Stored Binding {tamper}",
        )
        applied = client.post("/api/reconciliation/actions", headers=headers, json=request)
        assert applied.status_code == 200, applied.text
        action_id = applied.json()["id"]
        factory = create_session_maker(Settings(database_url=database_url))
        with factory() as session:
            action = session.get(ReconciliationAction, action_id)
            action.status = "committed_unverified"
            if tamper != "missing_key":
                summary = deepcopy(action.readback_summary)
                binding = summary["answer_binding"]
                binding[tamper] = (
                    "hmac-sha256:" + "0" * 64
                    if tamper == "commitment"
                    else "sha256:" + "0" * 64
                    if tamper == "action_digest"
                    else "tampered"
                )
                action.readback_summary = summary
            session.commit()
        if tamper == "missing_key":
            client.app.state.settings.reconciliation_commitment_key = None
        readback = client.get(f"/api/reconciliation/actions/{action_id}", headers=headers)
        assert readback.status_code == 503
        assert readback.json()["error"]["code"] == "readback_unavailable"
        with factory() as session:
            assert session.query(ReconciliationAction).count() == 1
            assert session.get(Candidate, candidate["id"]).status in {
                "accepted", "edited_accepted"
            }
            assert session.query(Entity).filter(
                Entity.display_name == f"Stored Binding {tamper}"
            ).count() == 1


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
        assert body["source_entity"]["id"] == source["id"]
        assert body["source_entity"]["status"] == "merged"
        assert body["source_entity"]["entity_digest"] != next(
            row["entity_digest"]
            for row in request["expected_entities"]
            if row["id"] == source["id"]
        )

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
        assert body["source_entity"] == body["entity"]
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
