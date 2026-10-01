from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_serializer

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def without_legacy_sensitivity(value: Any) -> Any:
    """Copy retired metadata out of new writes/reads; keep stored digest inputs intact."""
    if isinstance(value, dict):
        return {
            key: without_legacy_sensitivity(item)
            for key, item in value.items()
            if key not in {"sensitivity", "effective_sensitivity", "sensitivity_levels"}
        }
    if isinstance(value, list):
        return [without_legacy_sensitivity(item) for item in value]
    return value


class PublicReadModel(APIModel):
    """Hide retired metadata in untyped historical response payloads."""

    @model_serializer(mode="wrap")
    def public_projection(self, handler):
        return without_legacy_sensitivity(handler(self))


class ListResponse(APIModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int


class APIError(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


def without_retired_write_metadata(value: dict[str, Any]) -> dict[str, Any]:
    """Ignore obsolete approval/permission knobs on compatibility write routes."""
    clean = without_legacy_sensitivity(value)
    clean.pop("ai_use_policy", None)
    clean.pop("confirmation_status", None)
    if isinstance(clean.get("properties"), dict):
        clean["properties"].pop("needs_identity_review", None)
    return clean
