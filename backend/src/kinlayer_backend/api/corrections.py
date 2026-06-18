from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from kinlayer_backend.database import get_session
from kinlayer_backend.schemas.corrections import CorrectionApplyRequest, CorrectionApplyResponse
from kinlayer_backend.services.agent_operation_exports import AgentOperationService
from kinlayer_backend.services.agent_write_filter import AgentWriteFilter
from kinlayer_backend.services.corrections import CorrectionService

router = APIRouter(tags=["corrections"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/api/corrections/apply", response_model=CorrectionApplyResponse)
def apply_correction(payload: CorrectionApplyRequest, session: SessionDep):
    body = payload.model_dump()
    filter_result = None
    try:
        if body.get("created_by") == "ai_agent":
            filter_result = AgentWriteFilter(session).validate("correction", body)
            if not filter_result["accepted"]:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": {
                            "code": "validation_error",
                            "message": "Agent write validation failed.",
                            "details": {
                                "errors": filter_result["errors"],
                                "warnings": filter_result["warnings"],
                                "diagnostics": filter_result["diagnostics"],
                                "normalizations_applied": filter_result[
                                    "normalizations_applied"
                                ],
                                "controlled_values_checked": filter_result[
                                    "controlled_values_checked"
                                ],
                            },
                        }
                    },
                )
            body = filter_result["validated_payload"]
        result = CorrectionService(session).apply_correction(body)
    except HTTPException as exc:
        AgentOperationService(session).record_correction_failure(
            body,
            "/api/corrections/apply",
            exc,
        )
        raise
    AgentOperationService(session).record_correction_success(
        body,
        result,
        "/api/corrections/apply",
        filter_result=filter_result,
    )
    return result
