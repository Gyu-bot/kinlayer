from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ListResponse(APIModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int
    total: int


class APIError(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)
