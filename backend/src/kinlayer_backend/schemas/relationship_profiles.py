from kinlayer_backend.schemas.common import APIModel
from kinlayer_backend.schemas.memories import MemoryRead


class RelationshipAxisRead(APIModel):
    value: str | None = None
    label: str | None = None
    record: MemoryRead | None = None


class RelationshipProfileRead(APIModel):
    version: str
    entity_id: str
    perspective_entity_id: str | None
    axes: dict[str, RelationshipAxisRead]
