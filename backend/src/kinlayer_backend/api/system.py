from typing import Any

from fastapi import APIRouter, Request

from kinlayer_backend.config import Settings
from kinlayer_backend.database import check_database

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    database_status = check_database(request.app.state.settings)
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "database": database_status,
        "embedding": "disabled",
    }


@router.get("/version")
def version() -> dict[str, str]:
    return {"name": "kinlayer", "version": "0.1.0", "api_version": "v1"}


@router.get("/config")
def config(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "bind_host": settings.bind_host,
        "auth_token_configured": bool(settings.api_token),
        "embedding": _embedding_config(settings),
    }


def _embedding_config(settings: Settings) -> dict[str, Any]:
    provider = settings.embedding_provider or "disabled"
    model = (
        settings.embedding_model
        if provider != "local_sentence_transformers"
        else settings.embedding_model or "dragonkue/multilingual-e5-small-ko-v2"
    )
    status = "disabled"
    if provider == "openai_compatible":
        status = "ready" if settings.embedding_api_url and model else "misconfigured"
    elif provider == "local_sentence_transformers":
        status = "configured"
    elif provider != "disabled":
        status = "unsupported"
    return {
        "provider": provider,
        "model": model,
        "dim": settings.embedding_dim,
        "status": status,
        "api_url_configured": bool(settings.embedding_api_url),
        "api_key_configured": bool(settings.embedding_api_key),
    }
