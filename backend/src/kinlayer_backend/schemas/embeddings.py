from kinlayer_backend.schemas.common import APIModel


class EmbeddingObservationCounts(APIModel):
    total: int
    pending: int
    ready: int
    failed: int
    stale: int


class EmbeddingStatus(APIModel):
    provider: str
    model: str | None = None
    dim: int | None = None
    status: str
    api_url_configured: bool = False
    api_key_configured: bool = False
    observations: EmbeddingObservationCounts


class EmbeddingBackfillResult(APIModel):
    processed: int
    failed: int
    skipped: int
