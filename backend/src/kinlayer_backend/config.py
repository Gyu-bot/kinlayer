from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OPENAI_EMBEDDING_API_URL = "https://api.openai.com/v1/embeddings"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_EMBEDDING_DIM = 1536


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KINLAYER_", env_file=".env", extra="ignore")

    bind_host: str = "127.0.0.1"
    api_port: int = 8765
    api_url: str = "http://127.0.0.1:8765"
    api_token: str | None = None
    database_url: str = "postgresql+psycopg://kinlayer:kinlayer@127.0.0.1:15432/kinlayer"
    bootstrap_self: bool = False
    self_name: str = "Self"
    embedding_provider: str | None = Field(default=None)
    embedding_api_url: str | None = Field(default=None)
    embedding_api_key: str | None = Field(default=None)
    embedding_model: str | None = Field(default=None)
    embedding_dim: int | None = Field(default=None)

    @field_validator("embedding_dim", mode="before")
    @classmethod
    def normalize_optional_int(cls, value: Any) -> Any:
        return None if value == "" else value

    @model_validator(mode="after")
    def apply_embedding_defaults(self) -> "Settings":
        for field_name in (
            "api_token",
            "embedding_provider",
            "embedding_api_url",
            "embedding_api_key",
            "embedding_model",
        ):
            if getattr(self, field_name) == "":
                setattr(self, field_name, None)
        if not self.self_name.strip():
            self.self_name = "Self"

        if self.embedding_api_key and not self.embedding_provider:
            self.embedding_provider = "openai_compatible"

        if self.embedding_provider == "openai_compatible":
            self.embedding_api_url = self.embedding_api_url or DEFAULT_OPENAI_EMBEDDING_API_URL
            self.embedding_model = self.embedding_model or DEFAULT_OPENAI_EMBEDDING_MODEL
            self.embedding_dim = self.embedding_dim or DEFAULT_OPENAI_EMBEDDING_DIM

        return self

    @classmethod
    def from_overrides(cls, overrides: dict[str, Any] | None = None) -> "Settings":
        if not overrides:
            return cls()
        return cls(**overrides)


@lru_cache
def get_settings() -> Settings:
    return Settings()
