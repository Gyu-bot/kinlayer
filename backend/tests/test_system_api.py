from fastapi.testclient import TestClient

from kinlayer_backend.config import (
    DEFAULT_OPENAI_EMBEDDING_DIM,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    Settings,
)
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


def test_config_requires_optional_bearer_token(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    denied = client.get("/api/system/config")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"

    allowed = client.get("/api/system/config", headers={"Authorization": "Bearer secret"})
    assert allowed.status_code == 200
    assert allowed.json()["auth_token_configured"] is True


def test_config_reports_embedding_api_secret_state_without_exposing_secret(database_url: str) -> None:
    client = TestClient(
        create_app(
            {
                "database_url": database_url,
                "embedding_api_key": "openai-secret",
            }
        )
    )

    response = client.get("/api/system/config")

    assert response.status_code == 200
    body = response.json()
    assert body["embedding"] == {
        "provider": "openai_compatible",
        "model": DEFAULT_OPENAI_EMBEDDING_MODEL,
        "dim": DEFAULT_OPENAI_EMBEDDING_DIM,
        "status": "ready",
        "api_url_configured": True,
        "api_key_configured": True,
    }
    assert "openai-secret" not in response.text


def test_health_and_version_remain_public_with_token(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    assert client.get("/api/system/health").status_code == 200
    assert client.get("/api/system/version").status_code == 200


def test_cors_preflight_is_allowed_with_optional_token(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    response = client.options(
        "/api/entities",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_preflight_allows_lan_web_origin(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    response = client.options(
        "/api/entities",
        headers={
            "Origin": "http://192.168.1.38:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.1.38:5173"


def test_cors_preflight_rejects_unrelated_public_origin(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    response = client.options(
        "/api/entities",
        headers={
            "Origin": "http://example.com:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_app_can_start_before_entity_migrations(database_url: str) -> None:
    with TestClient(create_app({"database_url": database_url})) as client:
        response = client.get("/api/system/version")

    assert response.status_code == 200


def test_app_startup_seeds_protected_self_when_tables_exist(database_url: str) -> None:
    engine = create_db_engine(Settings(database_url=database_url))
    Base.metadata.create_all(engine)

    with TestClient(
        create_app({"database_url": database_url, "bootstrap_self": True, "self_name": "Me"})
    ) as client:
        response = client.get("/api/entities?system_role=self")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["display_name"] == "Me"
    assert body["items"][0]["system_role"] == "self"
