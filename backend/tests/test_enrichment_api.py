from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from pydantic import ValidationError

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine, create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import (
    Base,
    Candidate,
    CandidateEvidence,
    EnrichmentAnswerAction,
    EnrichmentAuthorization,
    Entity,
    EntityAlias,
    EntityFact,
    EntityFactEvidence,
    EntityEdge,
    Episode,
    Observation,
    ObservationEvidence,
    OntologyRegistryValue,
)
from kinlayer_backend.schemas.enrichment import (
    EnrichmentAnswerCreate,
    EnrichmentAuthorizationCreate,
)
from kinlayer_backend.repositories.enrichment import EnrichmentRepository
from kinlayer_backend.services.enrichment import EnrichmentService
from kinlayer_backend.services.candidates import CandidateService


def enrichment_client(database_url: str, token: str | None = "reconcile-secret"):
    settings = {
        "database_url": database_url,
        "reconciliation_token": token,
        "bootstrap_self": True,
        "self_name": "Self",
    }
    Base.metadata.create_all(create_db_engine(Settings(**settings)))
    return TestClient(create_app(settings))


def stage_payload(subject_id: str):
    return {
        "stage_idempotency_key": "stage:one",
        "subject_entity_id": subject_id,
        "topic": "work",
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "slots": [
            {
                "slot_id": "job",
                "kind": "profile_field",
                "fact_type": "job",
                "field_path": "job",
                "claim_type": "fact",
                "ai_use_policy": "cautious_use",
                "sensitivity": "low",
            }
        ],
    }


def answer_payload(authorization_id: str):
    return {
        "resolution_id": "answer:one",
        "authorization_id": authorization_id,
        "source": {
            "user_explicit": True,
            "source_type": "agent_conversation",
            "source_ref": "pcr:turn:1",
            "source_actor": "user",
        },
        "source_excerpt": "I work as an engineer.",
        "answers": [
            {
                "slot_id": "job",
                "state": "known",
                "value": "engineer",
                "evidence_excerpt": "I work as an engineer.",
            }
        ],
    }


def capability_headers(authorization: dict):
    return {"X-Kinlayer-Enrichment-Capability": authorization["answer_capability"]}


def pending_gap_case(subject_id: str, self_id: str, kind: str):
    request = stage_payload(subject_id)
    request["stage_idempotency_key"] = f"stage:pending-gap:{kind}"
    if kind == "profile_field":
        slot = request["slots"][0]
        payload = {"entity_id": subject_id, "fact_type": "job", "field_path": "job"}
    elif kind == "relationship_edge":
        slot = {
            "slot_id": "gap",
            "kind": kind,
            "direction": "self_to_subject",
            "allowed_relation_types": ["coworker"],
        }
        payload = {
            "from_entity_id": self_id,
            "to_entity_id": subject_id,
            "relation_type": "coworker",
        }
    else:
        slot = {
            "slot_id": "gap",
            "kind": kind,
            "allowed_observation_types": ["stable_fact"],
            "claim_type": "fact",
        }
        payload = {
            "subject_entity_id": subject_id,
            "related_entity_ids": [],
            "observation_type": "stable_fact",
        }
    request["slots"] = [slot]
    return request, {
        "candidate_type": kind,
        "target_entity_id": subject_id,
        "payload": payload,
    }


def add_gap_candidate(session, candidate: dict, status: str = "pending"):
    session.add(
        Candidate(
            **candidate,
            confidence=0.8,
            sensitivity="low",
            status=status,
            created_by="user",
        )
    )
    session.commit()


@pytest.mark.parametrize("field", ["question_text", "raw_reply", "entity_id", "payload", "policy"])
def test_enrichment_closed_schemas_reject_untrusted_fields(field):
    payload = stage_payload("entity")
    payload[field] = "forged"
    with pytest.raises(ValidationError):
        EnrichmentAuthorizationCreate.model_validate(payload)


def test_enrichment_answer_schema_requires_sorted_exact_evidence_and_is_closed():
    payload = answer_payload("authorization")
    payload["answers"][0]["entity_id"] = "forged"
    with pytest.raises(ValidationError):
        EnrichmentAnswerCreate.model_validate(payload)
    payload = answer_payload("authorization")
    payload["answers"][0]["evidence_excerpt"] = "not present"
    with pytest.raises(ValidationError):
        EnrichmentAnswerCreate.model_validate(payload)


def test_enrichment_routes_are_dedicated_token_gated(database_url):
    with enrichment_client(database_url, token=None) as client:
        assert (
            client.post("/api/reconciliation/enrichment-authorizations", json={}).status_code == 404
        )
        assert client.post("/api/reconciliation/enrichment-answers", json={}).status_code == 404
        assert client.get("/api/reconciliation/enrichment-answers/missing").status_code == 404
    with enrichment_client(database_url) as client:
        assert client.get("/api/reconciliation/enrichment-answers/missing").status_code == 404


def test_profile_enrichment_is_atomic_evidenced_verified_and_idempotent(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    with enrichment_client(database_url) as client:
        person_response = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Alex", "created_by": "user"},
        )
        assert person_response.status_code == 201
        request = stage_payload(person_response.json()["id"])
        staged = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert staged.status_code == 200, staged.text
        authorization = staged.json()
        assert authorization["slot_states"] == {"job": "open"}
        subject_snapshot = next(
            item
            for item in authorization["entity_snapshots"]
            if item["id"] == person_response.json()["id"]
        )
        assert set(subject_snapshot) == {
            "id",
            "entity_type",
            "display_name",
            "canonical_name",
            "system_role",
            "confirmation_status",
            "status",
            "updated_at",
            "entity_digest",
        }
        assert subject_snapshot == {
            "id": person_response.json()["id"],
            "entity_type": "person",
            "display_name": "Alex",
            "canonical_name": "alex",
            "system_role": None,
            "confirmation_status": "confirmed",
            "status": "active",
            "updated_at": subject_snapshot["updated_at"],
            "entity_digest": subject_snapshot["entity_digest"],
        }
        assert "aliases" not in subject_snapshot
        assert "properties" not in subject_snapshot
        assert "answer_capability" not in subject_snapshot
        retry = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert retry.status_code == 200
        assert retry.json()["id"] == authorization["id"]
        changed = {**request, "topic": "career"}
        assert (
            client.post(
                "/api/reconciliation/enrichment-authorizations", headers=headers, json=changed
            ).status_code
            == 409
        )

        answer = answer_payload(authorization["id"])
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert applied.status_code == 200, applied.text
        body = applied.json()
        assert body["status"] == "verified"
        assert len(body["derived_candidate_ids"]) == 1
        assert (
            client.post(
                "/api/reconciliation/enrichment-answers",
                headers=capability_headers(authorization),
                json=answer,
            ).json()["id"]
            == body["id"]
        )
        assert (
            client.get(
                f"/api/reconciliation/enrichment-answers/{body['id']}",
                headers=capability_headers(authorization),
            ).json()["status"]
            == "verified"
        )

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        action = session.get(EnrichmentAnswerAction, body["id"])
        authorization_row = session.get(EnrichmentAuthorization, authorization["id"])
        candidate = session.get(Candidate, body["derived_candidate_ids"][0])
        fact_id = candidate.canonical_record_ref.split(":", 1)[1]
        fact = session.get(EntityFact, fact_id)
        candidate_evidence = (
            session.query(CandidateEvidence).filter_by(candidate_id=candidate.id).one()
        )
        canonical_evidence = (
            session.query(EntityFactEvidence).filter_by(entity_fact_id=fact.id).one()
        )
        episode = session.get(Episode, action.episode_id)
        assert authorization_row.slot_states == {"job": "known"}
        assert candidate.created_by == candidate.resolved_by == "user"
        assert fact.source_candidate_id == candidate.id
        assert candidate_evidence.episode_id == canonical_evidence.episode_id == episode.id
        assert candidate_evidence.excerpt == canonical_evidence.excerpt == "I work as an engineer."


def test_authorization_snapshot_binds_bob_identity_and_cannot_represent_mina(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    with enrichment_client(database_url) as client:
        bob = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Bob", "created_by": "user"},
        ).json()
        response = client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers=headers,
            json=stage_payload(bob["id"]),
        )
        assert response.status_code == 200, response.text
        subject_snapshot = next(
            item for item in response.json()["entity_snapshots"] if item["id"] == bob["id"]
        )
        assert subject_snapshot["display_name"] == "Bob"
        assert subject_snapshot["canonical_name"] == "bob"
        assert "Mina" not in subject_snapshot.values()


@pytest.mark.parametrize("collision_kind", ["display_name", "canonical_name", "active_alias"])
def test_subject_name_or_alias_collision_blocks_stage(database_url, collision_kind):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        subject = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Mina Kim", "created_by": "user"},
        ).json()
        with factory() as session:
            other = Entity(
                entity_type="person",
                display_name="Other Person",
                canonical_name="other person",
                confirmation_status="confirmed",
                status="active",
                created_by="user",
            )
            if collision_kind == "display_name":
                other.display_name = "  MINA   KIM  "
            elif collision_kind == "canonical_name":
                other.canonical_name = "MINA KIM"
            else:
                other.aliases.append(
                    EntityAlias(alias="MINA KIM", status="active", created_by="user")
                )
            session.add(other)
            session.commit()
        response = client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers=headers,
            json=stage_payload(subject["id"]),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "subject_ambiguous"
    with factory() as session:
        assert session.query(EnrichmentAuthorization).count() == 0
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 0


def test_unrelated_inactive_and_unconfirmed_people_do_not_create_ambiguity(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        subject = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Mina", "created_by": "user"},
        ).json()
        with factory() as session:
            session.add_all(
                [
                    Entity(
                        entity_type="person",
                        display_name="Unrelated",
                        canonical_name="unrelated",
                        confirmation_status="confirmed",
                        status="active",
                        created_by="user",
                    ),
                    Entity(
                        entity_type="person",
                        display_name="Mina",
                        canonical_name="mina",
                        confirmation_status="confirmed",
                        status="inactive",
                        created_by="user",
                    ),
                    Entity(
                        entity_type="person",
                        display_name="Mina",
                        canonical_name="mina",
                        confirmation_status="pending",
                        status="active",
                        created_by="user",
                    ),
                ]
            )
            session.commit()
        response = client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers=headers,
            json=stage_payload(subject["id"]),
        )
        assert response.status_code == 200, response.text


def test_protected_self_bypasses_ordinary_name_collision(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        with factory() as session:
            protected_self = session.query(Entity).filter_by(system_role="self").one()
            session.add(
                Entity(
                    entity_type="person",
                    display_name=protected_self.display_name,
                    canonical_name=protected_self.canonical_name,
                    confirmation_status="confirmed",
                    status="active",
                    created_by="user",
                )
            )
            session.commit()
            self_id = protected_self.id
        request = stage_payload(self_id)
        request["stage_idempotency_key"] = "stage:self:collision"
        response = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert response.status_code == 200, response.text


def test_collision_introduced_after_stage_blocks_answer_before_mutation(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        subject = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Mina", "created_by": "user"},
        ).json()
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers=headers,
            json=stage_payload(subject["id"]),
        ).json()
        with factory() as session:
            session.add(
                Entity(
                    entity_type="person",
                    display_name="Someone Else",
                    canonical_name="someone else",
                    confirmation_status="confirmed",
                    status="active",
                    created_by="user",
                    aliases=[EntityAlias(alias="MINA", status="active", created_by="user")],
                )
            )
            session.commit()
        response = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer_payload(authorization["id"]),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "subject_ambiguous"
    with factory() as session:
        row = session.get(EnrichmentAuthorization, authorization["id"])
        assert row.status == "open"
        assert row.slot_states == {"job": "open"}
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 0
        assert session.query(EntityFact).count() == 0
        assert session.query(EntityEdge).count() == 0
        assert session.query(Observation).count() == 0


def test_enrichment_model_and_migration_forbid_raw_content_columns():
    forbidden = {"question_text", "raw_reply", "model_output", "transcript", "token", "prompt"}
    assert forbidden.isdisjoint(EnrichmentAuthorization.__table__.columns.keys())
    assert forbidden.isdisjoint(EnrichmentAnswerAction.__table__.columns.keys())
    migration = Path(
        "backend/alembic/versions/20260826_0010_conversational_enrichment.py"
    ).read_text()
    assert 'down_revision: str | None = "20260825_0009"' in migration
    for name in forbidden:
        assert f'Column("{name}"' not in migration


def test_composite_known_slots_and_unknown_skip(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Robin", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = "stage:composite"
        request["slots"] = [
            request["slots"][0],
            {
                "slot_id": "relationship",
                "kind": "relationship_edge",
                "direction": "self_to_subject",
                "allowed_relation_types": ["coworker"],
            },
            {
                "slot_id": "style",
                "kind": "observation",
                "allowed_observation_types": ["communication_preference"],
                "claim_type": "preference",
            },
        ]
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        source = "Robin is an engineer, is my coworker, and prefers short messages."
        answer = {
            "resolution_id": "answer:composite",
            "authorization_id": authorization["id"],
            "source": {
                "user_explicit": True,
                "source_type": "agent_conversation",
                "source_ref": "pcr:turn:2",
                "source_actor": "user",
            },
            "source_excerpt": source,
            "answers": [
                {
                    "slot_id": "job",
                    "state": "known",
                    "value": "engineer",
                    "evidence_excerpt": "Robin is an engineer",
                },
                {
                    "slot_id": "relationship",
                    "state": "known",
                    "value": "Robin is my coworker",
                    "evidence_excerpt": "is my coworker",
                },
                {
                    "slot_id": "style",
                    "state": "known",
                    "value": "prefers short messages",
                    "evidence_excerpt": "prefers short messages",
                },
            ],
        }
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert applied.status_code == 200, applied.text
        assert len(applied.json()["derived_candidate_ids"]) == 3

        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = "stage:unknown-skip"
        request["slots"] = [
            {**request["slots"][0], "slot_id": "role", "fact_type": "role", "field_path": "role"},
            {
                "slot_id": "stable",
                "kind": "observation",
                "allowed_observation_types": ["stable_fact"],
                "claim_type": "fact",
            },
        ]
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json={
                "resolution_id": "answer:unknown-skip",
                "authorization_id": authorization["id"],
                "source": {
                    "user_explicit": True,
                    "source_type": "agent_conversation",
                    "source_ref": "pcr:turn:3",
                    "source_actor": "user",
                },
                "answers": [
                    {"slot_id": "role", "state": "unknown"},
                    {"slot_id": "stable", "state": "skip"},
                ],
            },
        )
        assert applied.status_code == 200, applied.text
        outcomes = {item["slot_id"]: item for item in applied.json()["slot_outcomes"]}
        assert outcomes["role"]["candidate_id"] is None
        assert outcomes["stable"]["candidate_id"] is None

    factory = create_session_maker(Settings(database_url=database_url))
    with factory() as session:
        assert session.query(EntityEdge).count() == 1
        assert session.query(Observation).count() == 1
        row = session.get(EnrichmentAuthorization, authorization["id"])
        assert row.slot_states == {"role": "unknown", "stable": "open"}


def test_second_known_write_failure_rolls_back_every_artifact(database_url, monkeypatch):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    original = CandidateService.accept_candidate
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            self.session.rollback()
            raise RuntimeError("injected second write failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CandidateService, "accept_candidate", fail_second)
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Casey", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = "stage:rollback"
        request["slots"] = [
            request["slots"][0],
            {**request["slots"][0], "slot_id": "role", "fact_type": "role", "field_path": "role"},
        ]
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        with pytest.raises(RuntimeError, match="injected"):
            client.post(
                "/api/reconciliation/enrichment-answers",
                headers=capability_headers(authorization),
                json={
                    "resolution_id": "answer:rollback",
                    "authorization_id": authorization["id"],
                    "source": {
                        "user_explicit": True,
                        "source_type": "agent_conversation",
                        "source_ref": "pcr:rollback",
                        "source_actor": "user",
                    },
                    "source_excerpt": "Engineer and team lead.",
                    "answers": [
                        {
                            "slot_id": "job",
                            "state": "known",
                            "value": "engineer",
                            "evidence_excerpt": "Engineer",
                        },
                        {
                            "slot_id": "role",
                            "state": "known",
                            "value": "team lead",
                            "evidence_excerpt": "team lead",
                        },
                    ],
                },
            )
    with factory() as session:
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Candidate).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(EntityFact).count() == 0
        row = session.get(EnrichmentAuthorization, authorization["id"])
        assert row.status == "open"
        assert row.slot_states == {"job": "open", "role": "open"}


def test_tampered_readback_returns_503_without_duplicate_writes(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Taylor", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = "stage:tamper"
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        answer = answer_payload(authorization["id"])
        answer["resolution_id"] = "answer:tamper"
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        ).json()
        with factory() as session:
            action = session.get(EnrichmentAnswerAction, applied["id"])
            candidate = session.get(Candidate, applied["derived_candidate_ids"][0])
            action.status = "committed_unverified"
            candidate.payload = {**candidate.payload, "content": "tampered"}
            session.commit()
        response = client.get(
            f"/api/reconciliation/enrichment-answers/{applied['id']}",
            headers=capability_headers(authorization),
        )
        assert response.status_code == 503
        retry = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert retry.status_code == 503
    with factory() as session:
        assert session.query(Candidate).count() == 1
        assert session.query(EntityFact).count() == 1
        assert session.query(Episode).count() == 1


def test_enrichment_capability_is_scoped_and_stage_retry_recovers_it(database_url):
    stage_headers = {"Authorization": "Bearer reconcile-secret"}
    with enrichment_client(database_url) as client:
        people = [
            client.post(
                "/api/entities",
                json={"entity_type": "person", "display_name": name, "created_by": "user"},
            ).json()
            for name in ("One", "Two")
        ]
        authorizations = []
        for index, person in enumerate(people):
            request = stage_payload(person["id"])
            request["stage_idempotency_key"] = f"stage:scope:{index}"
            response = client.post(
                "/api/reconciliation/enrichment-authorizations",
                headers=stage_headers,
                json=request,
            )
            assert response.status_code == 200
            authorizations.append(response.json())
            if index == 0:
                retry = client.post(
                    "/api/reconciliation/enrichment-authorizations",
                    headers=stage_headers,
                    json=request,
                ).json()
                assert retry["id"] == response.json()["id"]
                assert retry["answer_capability"] == response.json()["answer_capability"]

        answer = answer_payload(authorizations[0]["id"])
        assert client.post(
            "/api/reconciliation/enrichment-answers", headers=stage_headers, json=answer
        ).status_code == 404
        cross = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorizations[1]),
            json=answer,
        )
        assert cross.status_code == 404
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorizations[0]),
            json=answer,
        )
        assert applied.status_code == 200
        action_id = applied.json()["id"]
        for headers in (stage_headers, capability_headers(authorizations[1]), {}):
            response = client.get(
                f"/api/reconciliation/enrichment-answers/{action_id}", headers=headers
            )
            assert response.status_code == 404
        assert client.get(
            "/api/reconciliation/enrichment-answers/does-not-exist",
            headers=capability_headers(authorizations[0]),
        ).status_code == 404
        assert client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers={"Authorization": f"Bearer {authorizations[0]['answer_capability']}"},
            json=stage_payload(people[0]["id"]),
        ).status_code == 401


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_profile_semantic_slots_reject_without_authorization(database_url, reverse):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Duplicate", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        duplicate = {**request["slots"][0], "slot_id": "job2"}
        request["slots"] = [request["slots"][0], duplicate]
        if reverse:
            request["slots"].reverse()
        response = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert response.status_code == 409
    with factory() as session:
        assert session.query(EnrichmentAuthorization).count() == 0
        assert session.query(EntityFact).count() == 0


@pytest.mark.parametrize("kind", ["relationship_edge", "observation"])
def test_duplicate_edge_and_overlapping_observation_slots_reject(database_url, kind):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Overlap", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        if kind == "relationship_edge":
            request["slots"] = [
                {
                    "slot_id": "edge1",
                    "kind": kind,
                    "direction": "self_to_subject",
                    "allowed_relation_types": ["coworker"],
                },
                {
                    "slot_id": "edge2",
                    "kind": kind,
                    "direction": "self_to_subject",
                    "allowed_relation_types": ["friend"],
                },
            ]
        else:
            request["slots"] = [
                {
                    "slot_id": "obs1",
                    "kind": kind,
                    "allowed_observation_types": ["care_point", "stable_fact"],
                    "claim_type": "fact",
                },
                {
                    "slot_id": "obs2",
                    "kind": kind,
                    "allowed_observation_types": ["care_point", "recent_interaction"],
                    "claim_type": "fact",
                },
            ]
        assert client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).status_code == 409
    with factory() as session:
        assert session.query(EnrichmentAuthorization).count() == 0


@pytest.mark.parametrize(
    "field",
    ["allowed_relation_types", "allowed_observation_types"],
)
def test_allowed_type_lists_reject_duplicates(field):
    payload = stage_payload("entity")
    if field == "allowed_relation_types":
        slot = {
            "slot_id": "edge",
            "kind": "relationship_edge",
            "direction": "self_to_subject",
            field: ["coworker", "coworker"],
        }
    else:
        slot = {
            "slot_id": "obs",
            "kind": "observation",
            field: ["stable_fact", "stable_fact"],
            "claim_type": "fact",
        }
    payload["slots"] = [slot]
    with pytest.raises(ValidationError):
        EnrichmentAuthorizationCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("answers", 0, "value"), "   "),
        (("answers", 0, "evidence_excerpt"), " "),
        (("source_excerpt",), "   "),
        (("source", "source_ref"), " pcr:turn:1"),
        (("source", "source_ref"), "pcr:turn:1\r\ninjected"),
        (("source", "source_ref"), "pcr:turn:1\tinjected"),
        (("answers", 0, "value"), "bad\x00value"),
    ],
)
def test_enrichment_answer_rejects_dirty_strings(path, value):
    payload = answer_payload("authorization")
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        EnrichmentAnswerCreate.model_validate(payload)


def test_all_unknown_skip_stores_no_source_or_evidence(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Private", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["slots"] = [
            {**request["slots"][0], "slot_id": "role", "fact_type": "role", "field_path": "role"},
            {
                "slot_id": "stable",
                "kind": "observation",
                "allowed_observation_types": ["stable_fact"],
                "claim_type": "fact",
            },
        ]
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        response = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json={
                "resolution_id": "answer:private",
                "authorization_id": authorization["id"],
                "source": {
                    "user_explicit": True,
                    "source_type": "agent_conversation",
                    "source_ref": "pcr:private",
                    "source_actor": "user",
                },
                "answers": [
                    {"slot_id": "role", "state": "unknown"},
                    {"slot_id": "stable", "state": "skip"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["episode_id"] is None
    with factory() as session:
        action = session.query(EnrichmentAnswerAction).one()
        authorization_row = session.get(EnrichmentAuthorization, authorization["id"])
        assert action.source_snapshot is None
        assert authorization_row.slot_states == {"role": "unknown", "stable": "open"}
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 0
        assert session.query(EntityFact).count() == 0
        assert session.query(Observation).count() == 0
        assert session.query(CandidateEvidence).count() == 0
        assert session.query(EntityFactEvidence).count() == 0
        assert session.query(ObservationEvidence).count() == 0


def test_mixed_answer_episode_contains_only_known_evidence_bundle(database_url):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Mixed", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = "stage:mixed-privacy"
        request["slots"] = [
            request["slots"][0],
            {
                "slot_id": "stable",
                "kind": "observation",
                "allowed_observation_types": ["stable_fact"],
                "claim_type": "fact",
            },
        ]
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        response = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json={
                "resolution_id": "answer:mixed-privacy",
                "authorization_id": authorization["id"],
                "source": {
                    "user_explicit": True,
                    "source_type": "agent_conversation",
                    "source_ref": "pcr:mixed",
                    "source_actor": "user",
                },
                "source_excerpt": "I work as an engineer.",
                "answers": [
                    {
                        "slot_id": "job",
                        "state": "known",
                        "value": "engineer",
                        "evidence_excerpt": "I work as an engineer.",
                    },
                    {"slot_id": "stable", "state": "skip"},
                ],
            },
        )
        assert response.status_code == 200
    with factory() as session:
        action = session.query(EnrichmentAnswerAction).one()
        episode = session.get(Episode, action.episode_id)
        authorization_row = session.get(EnrichmentAuthorization, authorization["id"])
        assert episode.body_excerpt == "I work as an engineer."
        assert authorization_row.slot_states == {"job": "known", "stable": "open"}
        assert session.query(Candidate).count() == 1
        assert session.query(CandidateEvidence).count() == 1


@pytest.mark.parametrize("failure", ["expired", "stale", "gap", "ontology", "forged_slot"])
def test_answer_preconditions_fail_before_any_write(database_url, failure):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Precondition", "created_by": "user"},
        ).json()
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations",
            headers=headers,
            json=stage_payload(person["id"]),
        ).json()
        answer = answer_payload(authorization["id"])
        with factory() as session:
            row = session.get(EnrichmentAuthorization, authorization["id"])
            if failure == "expired":
                row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif failure == "stale":
                entity = session.get(Entity, person["id"])
                entity.display_name = "Changed after stage"
            elif failure == "gap":
                session.add(
                    EntityFact(
                        entity_id=person["id"],
                        fact_type="job",
                        content="already filled",
                        value={"field_path": "job", "value": "already filled"},
                        claim_type="fact",
                        sensitivity="low",
                        ai_use_policy="cautious_use",
                        status="active",
                        created_by="user",
                    )
                )
            elif failure == "ontology":
                registry = session.query(OntologyRegistryValue).filter_by(
                    category="fact_type", value="job"
                ).one()
                registry.is_active = False
            else:
                answer["answers"][0]["slot_id"] = "forged"
            session.commit()
        response = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert response.status_code in {409, 422}
    with factory() as session:
        row = session.get(EnrichmentAuthorization, authorization["id"])
        assert row.slot_states == {"job": "open"}
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 0


@pytest.mark.parametrize("kind", ["profile_field", "relationship_edge", "observation"])
@pytest.mark.parametrize("status", ["pending", "needs_clarification"])
def test_matching_unresolved_candidate_blocks_stage(database_url, kind, status):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Pending", "created_by": "user"},
        ).json()
        with factory() as session:
            self_id = session.query(Entity).filter_by(system_role="self").one().id
            request, candidate = pending_gap_case(person["id"], self_id, kind)
            add_gap_candidate(session, candidate, status)
        response = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "pending_gap_filled"
    with factory() as session:
        assert session.query(EnrichmentAuthorization).count() == 0
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 1


@pytest.mark.parametrize("kind", ["profile_field", "relationship_edge", "observation"])
@pytest.mark.parametrize("status", ["pending", "needs_clarification"])
def test_matching_unresolved_candidate_blocks_answer_before_any_write(database_url, kind, status):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Late Pending", "created_by": "user"},
        ).json()
        with factory() as session:
            self_id = session.query(Entity).filter_by(system_role="self").one().id
        request, candidate = pending_gap_case(person["id"], self_id, kind)
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        with factory() as session:
            add_gap_candidate(session, candidate, status)
        stage_retry = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert stage_retry.status_code == 200
        assert stage_retry.json()["id"] == authorization["id"]
        answer = answer_payload(authorization["id"])
        answer["resolution_id"] = f"answer:pending-gap:{kind}:{status}"
        answer["answers"][0]["slot_id"] = request["slots"][0]["slot_id"]
        response = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "pending_gap_filled"
    with factory() as session:
        row = session.get(EnrichmentAuthorization, authorization["id"])
        assert row.slot_states == {request["slots"][0]["slot_id"]: "open"}
        assert session.query(EnrichmentAnswerAction).count() == 0
        assert session.query(Episode).count() == 0
        assert session.query(Candidate).count() == 1
        assert session.query(EntityFact).count() == 0
        assert session.query(EntityEdge).count() == 0
        assert session.query(Observation).count() == 0


@pytest.mark.parametrize(
    ("kind", "mismatch"),
    [
        ("profile_field", "candidate_type"),
        ("profile_field", "field_path"),
        ("relationship_edge", "endpoint"),
        ("relationship_edge", "allowed_type"),
        ("observation", "related_set"),
        ("observation", "allowed_type"),
        ("observation", "malformed"),
    ],
)
def test_unrelated_or_malformed_candidate_does_not_fill_gap(database_url, kind, mismatch):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Unrelated", "created_by": "user"},
        ).json()
        with factory() as session:
            self_id = session.query(Entity).filter_by(system_role="self").one().id
            request, candidate = pending_gap_case(person["id"], self_id, kind)
            if mismatch == "candidate_type":
                candidate["candidate_type"] = "observation"
            elif mismatch == "field_path":
                candidate["payload"]["field_path"] = "role"
            elif mismatch == "endpoint":
                candidate["payload"]["from_entity_id"] = person["id"]
            elif mismatch == "related_set":
                candidate["payload"]["related_entity_ids"] = [self_id]
            elif mismatch == "allowed_type":
                type_key = "relation_type" if kind == "relationship_edge" else "observation_type"
                candidate["payload"][type_key] = "unrelated"
            else:
                candidate["payload"]["related_entity_ids"] = [None]
            add_gap_candidate(session, candidate)
        first = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert first.status_code == 200, first.text
        retry = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        )
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]


@pytest.mark.parametrize(
    "tamper",
    ["slot_state", "derived_candidates", "episode_source", "candidate_evidence"],
)
def test_fresh_readback_rejects_ledger_and_evidence_tampering(database_url, tamper):
    headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Tamper", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = f"stage:tamper:{tamper}"
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=headers, json=request
        ).json()
        answer = answer_payload(authorization["id"])
        answer["resolution_id"] = f"answer:tamper:{tamper}"
        applied = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        ).json()
        with factory() as session:
            action = session.get(EnrichmentAnswerAction, applied["id"])
            action.status = "committed_unverified"
            if tamper == "slot_state":
                auth = session.get(EnrichmentAuthorization, authorization["id"])
                auth.slot_states = {"job": "open"}
            elif tamper == "derived_candidates":
                action.derived_candidate_ids = []
            elif tamper == "episode_source":
                episode = session.get(Episode, action.episode_id)
                episode.source_ref = "forged:source"
            else:
                evidence = session.query(CandidateEvidence).filter_by(
                    candidate_id=applied["derived_candidate_ids"][0]
                ).one()
                evidence.excerpt = "forged excerpt"
            session.commit()
        response = client.get(
            f"/api/reconciliation/enrichment-answers/{applied['id']}",
            headers=capability_headers(authorization),
        )
        assert response.status_code == 503
        retry = client.post(
            "/api/reconciliation/enrichment-answers",
            headers=capability_headers(authorization),
            json=answer,
        )
        assert retry.status_code == 503
    with factory() as session:
        assert session.query(EnrichmentAnswerAction).count() == 1
        assert session.query(Candidate).count() == 1
        assert session.query(EntityFact).count() == 1
        assert session.query(Episode).count() == 1


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_posts_recheck_resolution_after_authorization_lock(
    database_url, monkeypatch, conflicting
):
    stage_headers = {"Authorization": "Bearer reconcile-secret"}
    factory = create_session_maker(Settings(database_url=database_url))
    with enrichment_client(database_url) as client:
        person = client.post(
            "/api/entities",
            json={"entity_type": "person", "display_name": "Race", "created_by": "user"},
        ).json()
        request = stage_payload(person["id"])
        request["stage_idempotency_key"] = f"stage:race:{conflicting}"
        authorization = client.post(
            "/api/reconciliation/enrichment-authorizations", headers=stage_headers, json=request
        ).json()

    original_lock = EnrichmentRepository.lock_authorization
    a_locked = Event()
    a_done = Event()

    def synchronized_authorization_lock(repository, authorization_id):
        name = __import__("threading").current_thread().name
        if name == "A":
            result = original_lock(repository, authorization_id)
            a_locked.set()
            return result
        assert a_locked.wait(5)
        assert a_done.wait(5)
        return original_lock(repository, authorization_id)

    monkeypatch.setattr(
        EnrichmentRepository, "lock_authorization", synchronized_authorization_lock
    )
    results = {}

    def apply(name, payload):
        try:
            with factory() as session:
                results[name] = EnrichmentService(
                    session,
                    factory,
                    Settings(reconciliation_token="reconcile-secret"),
                ).answer(
                    EnrichmentAnswerCreate.model_validate(payload),
                    authorization["answer_capability"],
                )
        except HTTPException as exc:
            results[name] = exc.status_code
        finally:
            if name == "A":
                a_done.set()

    first = answer_payload(authorization["id"])
    first["resolution_id"] = f"answer:race:{conflicting}"
    second = answer_payload(authorization["id"])
    second["resolution_id"] = first["resolution_id"]
    if conflicting:
        second["source_excerpt"] = "I work as a designer."
        second["answers"][0]["value"] = "designer"
        second["answers"][0]["evidence_excerpt"] = "I work as a designer."
    threads = [
        Thread(target=apply, name="A", args=("A", first)),
        Thread(target=apply, name="B", args=("B", second)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()

    assert results["A"]["status"] == "verified"
    if conflicting:
        assert results["B"] == 409
    else:
        assert results["B"]["id"] == results["A"]["id"]
    with factory() as session:
        assert session.query(EnrichmentAnswerAction).count() == 1
        assert session.query(Candidate).count() == 1
        assert session.query(EntityFact).count() == 1
        assert session.query(Episode).count() == 1
