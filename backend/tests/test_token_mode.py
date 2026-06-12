from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from kinlayer_backend import cli
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


def test_relationship_data_requires_token_but_health_and_version_remain_public(database_url: str) -> None:
    engine = create_db_engine(create_app({"database_url": database_url}).state.settings)
    Base.metadata.create_all(engine)
    client = TestClient(create_app({"api_token": "secret-token", "database_url": database_url}))

    assert client.get("/api/system/health").status_code == 200
    assert client.get("/api/system/version").status_code == 200

    denied = client.get("/api/entities")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"

    allowed = client.get("/api/entities", headers={"Authorization": "Bearer secret-token"})
    assert allowed.status_code == 200


def test_cli_uses_env_token_without_printing_it(monkeypatch) -> None:
    secret = "secret-token-never-print"

    def fake_get(url, headers, timeout):
        assert headers["Authorization"] == f"Bearer {secret}"
        return cli.httpx.Response(200, json={"database": "ok", "embedding": "disabled"})

    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setenv("KINLAYER_API_TOKEN", secret)

    result = CliRunner().invoke(cli.app, ["status", "--json"])

    assert result.exit_code == 0
    assert secret not in result.stdout
    assert secret not in result.stderr


def test_compose_passes_optional_api_token_to_api_container() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "KINLAYER_API_TOKEN" in compose


def test_compose_passes_embedding_environment_to_api_container() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "KINLAYER_EMBEDDING_PROVIDER" in compose
    assert "KINLAYER_EMBEDDING_API_URL" in compose
    assert "KINLAYER_EMBEDDING_API_KEY" in compose
    assert "KINLAYER_EMBEDDING_MODEL" in compose
    assert "KINLAYER_EMBEDDING_DIM" in compose


def test_compose_persists_postgres_data_in_named_volume() -> None:
    compose = Path("docker-compose.yml").read_text()

    assert "kinlayer-postgres-data:/var/lib/postgresql/data" in compose
    assert "kinlayer-postgres-data:" in compose
