from typing import Any, Literal

from pydantic import Field

from kinlayer_backend.schemas.common import APIModel


class AgentWriteValidateRequest(APIModel):
    write_type: Literal["candidate", "correction"]
    payload: dict[str, Any]


class AgentWriteNormalization(APIModel):
    field: str
    original: Any
    normalized: Any
    category: str


class AgentWriteValidationIssue(APIModel):
    code: str
    message: str
    field: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class AgentWriteValidationResponse(APIModel):
    accepted: bool
    validated_payload: dict[str, Any]
    normalizations_applied: list[AgentWriteNormalization] = Field(default_factory=list)
    warnings: list[AgentWriteValidationIssue] = Field(default_factory=list)
    errors: list[AgentWriteValidationIssue] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    controlled_values_checked: list[str] = Field(default_factory=list)
    audit_ref: str | None = None
