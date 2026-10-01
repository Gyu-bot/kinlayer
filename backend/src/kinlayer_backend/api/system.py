from typing import Any

from fastapi import APIRouter, Request

from kinlayer_backend.config import Settings
from kinlayer_backend.services.relationship_ontology import ONTOLOGY_VERSION
from kinlayer_backend.database import check_database
from kinlayer_backend.services.embeddings import DEFAULT_LOCAL_MODEL

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    database_status = check_database(request.app.state.settings)
    return {
        "status": "ok" if database_status == "ok" else "degraded",
        "database": database_status,
        "embedding": _embedding_config(request.app.state.settings)["status"],
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
        "curation": {
            "mode": settings.curation_mode,
            "policy_version": settings.curation_policy_version,
        },
        "embedding": _embedding_config(settings),
        "ontology": {"version": ONTOLOGY_VERSION, "endpoint": "/api/ontology", "edge_types_endpoint": "/api/ontology/edge-types"},
        "memory_write": {
            "endpoint": "/api/memories",
            "review_required": False,
            "contract_version": "2",
        },
    }


def _embedding_config(settings: Settings) -> dict[str, Any]:
    provider = settings.embedding_provider or "disabled"
    model = (
        settings.embedding_model
        if provider != "local_sentence_transformers"
        else settings.embedding_model or DEFAULT_LOCAL_MODEL
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
