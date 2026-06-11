from typing import Any

from fastapi import APIRouter, Request

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
        "embedding": {
            "provider": settings.embedding_provider or "disabled",
            "model": settings.embedding_model,
            "dim": settings.embedding_dim,
            "status": "disabled",
        },
    }
