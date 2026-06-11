import sys
import types

from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine, create_session_maker
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base, Observation


def create_person(client, name: str) -> dict:
    response = client.post(
        "/api/entities",
        json={"entity_type": "person", "display_name": name, "created_by": "user"},
    )
    assert response.status_code == 201
    return response.json()


def test_embedding_status_reports_disabled_provider_and_counts(client) -> None:
    person = create_person(client, "Alex")
    created = client.post(
        "/api/observations",
        json={
            "subject_entity_id": person["id"],
            "observation_type": "recent_interaction",
            "content": "Alex sent a short follow-up.",
            "claim_type": "fact",
            "created_by": "user",
        },
    )
    assert created.status_code == 201
    assert created.json()["embedding_status"] == "pending"

    status = client.get("/api/embeddings/status")

    assert status.status_code == 200
    body = status.json()
    assert body["provider"] == "disabled"
    assert body["status"] == "disabled"
    assert body["observations"]["pending"] == 1


def test_openai_compatible_provider_embeds_observation_on_create(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    def fake_post(url, headers, json, timeout):
        assert url == "http://embedding.local/v1/embeddings"
        assert json["model"] == "test-model"
        assert json["input"] == "Alex sent a short follow-up."
        return DummyResponse()

    monkeypatch.setattr("kinlayer_backend.services.embeddings.httpx.post", fake_post)
    with TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_provider": "openai_compatible",
                "embedding_api_url": "http://embedding.local/v1/embeddings",
                "embedding_model": "test-model",
                "embedding_dim": 3,
            }
        )
    ) as client:
        person = create_person(client, "Alex")

        created = client.post(
            "/api/observations",
            json={
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": "Alex sent a short follow-up.",
                "claim_type": "fact",
                "created_by": "user",
            },
        )

        assert created.status_code == 201
        assert created.json()["embedding_status"] == "ready"
        assert created.json()["embedding_dim"] == 3


def test_embedding_backfill_processes_pending_observations(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.2, 0.4]}]}

    calls = {"count": 0}

    def flaky_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary embedding failure")
        return DummyResponse()

    monkeypatch.setattr("kinlayer_backend.services.embeddings.httpx.post", flaky_post)
    with TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_provider": "openai_compatible",
                "embedding_api_url": "http://embedding.local/v1/embeddings",
                "embedding_model": "test-model",
                "embedding_dim": 2,
            }
        )
    ) as client:
        person = create_person(client, "Alex")
        created = client.post(
            "/api/observations",
            json={
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": "Alex sent a short follow-up.",
                "claim_type": "fact",
                "created_by": "user",
            },
        )
        observation_id = created.json()["id"]
        assert created.json()["embedding_status"] == "failed"

        backfill = client.post("/api/embeddings/backfill")

        assert backfill.status_code == 200
        assert backfill.json()["processed"] >= 1
        assert client.get(f"/api/observations/{observation_id}").json()[
            "embedding_status"
        ] == "ready"


def test_local_sentence_transformers_provider_uses_configured_model(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    requested_models = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str):
            requested_models.append(model_name)

        def encode(self, text: str, normalize_embeddings: bool):
            assert text == "Alex prefers short Korean summaries."
            assert normalize_embeddings is True
            return [0.3, 0.6]

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    with TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_provider": "local_sentence_transformers",
                "embedding_model": "nlpai-lab/KURE-v1",
                "embedding_dim": 2,
            }
        )
    ) as client:
        person = create_person(client, "Alex")

        created = client.post(
            "/api/observations",
            json={
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": "Alex prefers short Korean summaries.",
                "claim_type": "fact",
                "created_by": "user",
            },
        )

        assert created.status_code == 201
        assert created.json()["embedding_status"] == "ready"
        assert created.json()["embedding_model"] == "nlpai-lab/KURE-v1"
        assert requested_models == ["nlpai-lab/KURE-v1"]


def test_local_sentence_transformers_status_reports_unavailable_when_missing(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "kinlayer_backend.services.embeddings.importlib.util.find_spec",
        lambda package_name: None if package_name == "sentence_transformers" else object(),
    )

    with TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_provider": "local_sentence_transformers",
            }
        )
    ) as client:
        status = client.get("/api/embeddings/status")

    assert status.status_code == 200
    assert status.json()["provider"] == "local_sentence_transformers"
    assert status.json()["model"] == "dragonkue/multilingual-e5-small-ko-v2"
    assert status.json()["status"] == "unavailable"


def test_backfill_failure_clears_stale_embedding(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"
    settings = Settings(database_url=database_url)
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)

    class DummyResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"embedding": [0.2, 0.4]}]}

    def successful_post(*args, **kwargs):
        return DummyResponse()

    monkeypatch.setattr("kinlayer_backend.services.embeddings.httpx.post", successful_post)
    with TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_provider": "openai_compatible",
                "embedding_api_url": "http://embedding.local/v1/embeddings",
                "embedding_model": "test-model",
                "embedding_dim": 2,
            }
        )
    ) as client:
        person = create_person(client, "Alex")
        created = client.post(
            "/api/observations",
            json={
                "subject_entity_id": person["id"],
                "observation_type": "recent_interaction",
                "content": "Alex sent a short follow-up.",
                "claim_type": "fact",
                "created_by": "user",
            },
        )
        observation_id = created.json()["id"]
        assert created.json()["embedding_status"] == "ready"

        with create_session_maker(settings)() as session:
            observation = session.get(Observation, observation_id)
            assert observation is not None
            observation.embedding_status = "stale"
            session.commit()

        def failing_post(*args, **kwargs):
            raise RuntimeError("provider outage")

        monkeypatch.setattr("kinlayer_backend.services.embeddings.httpx.post", failing_post)
        backfill = client.post("/api/embeddings/backfill")

        assert backfill.status_code == 200
        assert backfill.json()["failed"] == 1
        refreshed = client.get(f"/api/observations/{observation_id}").json()
        assert refreshed["embedding_status"] == "failed"
        assert refreshed["embedding"] is None
