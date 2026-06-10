from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KINLAYER_", env_file=".env", extra="ignore")

    bind_host: str = "127.0.0.1"
    api_port: int = 8765
    api_url: str = "http://127.0.0.1:8765"
    api_token: str | None = None
    database_url: str = "postgresql+psycopg://kinlayer:kinlayer@127.0.0.1:15432/kinlayer"
    embedding_provider: str | None = Field(default=None)
    embedding_model: str | None = Field(default=None)
    embedding_dim: int | None = Field(default=None)

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None = None) -> "Settings":
        if not overrides:
            return cls()
        return cls(**overrides)


@lru_cache
def get_settings() -> Settings:
    return Settings()
