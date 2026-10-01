from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.material_imports import MaterialImportRead, MaterialImportRequest
from kinlayer_backend.services.material_imports import MaterialImportService

router = APIRouter(prefix="/api/material-imports", tags=["material-imports"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/validate", response_model=MaterialImportRead)
def validate_material_import(payload: MaterialImportRequest, session: SessionDep):
    return MaterialImportService(session).run(payload)


@router.post("/submit", response_model=MaterialImportRead)
def submit_material_import(payload: MaterialImportRequest, session: SessionDep):
    return MaterialImportService(session).run(payload, submit=True)


@router.get("/{import_id}", response_model=MaterialImportRead)
def read_material_import(import_id: str, session: SessionDep):
    return MaterialImportService(session).read(import_id)
