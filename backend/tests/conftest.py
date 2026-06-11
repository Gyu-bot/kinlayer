from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'kinlayer-test.db'}"


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    settings = Settings(database_url=database_url)
    engine = create_db_engine(settings)
    Base.metadata.create_all(engine)

    with TestClient(create_app({"database_url": database_url})) as test_client:
        yield test_client
