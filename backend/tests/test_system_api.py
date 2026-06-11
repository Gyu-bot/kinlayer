from fastapi.testclient import TestClient

from kinlayer_backend.main import create_app


def test_config_requires_optional_bearer_token(database_url: str) -> None:
    client = TestClient(create_app({"api_token": "secret", "database_url": database_url}))

    denied = client.get("/api/system/config")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"

    allowed = client.get("/api/system/config", headers={"Authorization": "Bearer secret"})
    assert allowed.status_code == 200
    assert allowed.json()["auth_token_configured"] is True


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


def test_app_can_start_before_entity_migrations(database_url: str) -> None:
    with TestClient(create_app({"database_url": database_url})) as client:
        response = client.get("/api/system/version")

    assert response.status_code == 200
