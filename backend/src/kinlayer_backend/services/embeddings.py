from collections import Counter
from datetime import UTC, datetime
import importlib.util
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from kinlayer_backend.config import Settings
from kinlayer_backend.models import Observation

DEFAULT_LOCAL_MODEL = "dragonkue/multilingual-e5-small-ko-v2"
EMBEDDING_BACKFILL_STATUSES = {"pending", "failed", "stale"}


class EmbeddingService:
    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or Settings()

    @property
    def provider(self) -> str:
        return self.settings.embedding_provider or "disabled"

    @property
    def model(self) -> str | None:
        if self.provider == "local_sentence_transformers":
            return self.settings.embedding_model or DEFAULT_LOCAL_MODEL
        return self.settings.embedding_model

    def status(self) -> dict[str, Any]:
        counts = Counter(
            self.session.execute(select(Observation.embedding_status)).scalars().all()
        )
        total = sum(counts.values())
        observation_counts = {
            "total": total,
            "pending": counts.get("pending", 0),
            "ready": counts.get("ready", 0),
            "failed": counts.get("failed", 0),
            "stale": counts.get("stale", 0),
        }
        return {
            "provider": self.provider,
            "model": self.model,
            "dim": self.settings.embedding_dim,
            "status": self._provider_status(),
            "api_url_configured": bool(self.settings.embedding_api_url),
            "api_key_configured": bool(self.settings.embedding_api_key),
            "observations": observation_counts,
        }

    def backfill(self, limit: int = 100) -> dict[str, int]:
        statement = (
            select(Observation)
            .where(Observation.embedding_status.in_(EMBEDDING_BACKFILL_STATUSES))
            .order_by(Observation.updated_at.asc())
            .limit(limit)
        )
        observations = self.session.execute(statement).scalars().all()
        before = {observation.id: observation.embedding_status for observation in observations}
        processed = 0
        failed = 0
        skipped = 0
        for observation in observations:
            result = self.embed_observation(observation)
            if result == "ready":
                processed += 1
            elif result == "failed":
                failed += 1
            elif result == before[observation.id]:
                skipped += 1
            else:
                processed += 1
        return {"processed": processed, "failed": failed, "skipped": skipped}

    def embed_observation(self, observation: Observation) -> str:
        if self.provider == "disabled":
            observation.embedding_status = observation.embedding_status or "pending"
            self.session.commit()
            self.session.refresh(observation)
            return observation.embedding_status
        try:
            embedding = self.generate_embedding(observation.content)
            observation.embedding = self._format_vector(embedding)
            observation.embedding_status = "ready"
            observation.embedding_error = None
            observation.embedding_model = self.model
            observation.embedding_dim = len(embedding)
            observation.embedding_created_at = datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001 - failures must not block observation writes.
            observation.embedding = None
            observation.embedding_status = "failed"
            observation.embedding_error = str(exc)[:1000]
            observation.embedding_model = self.model
            observation.embedding_dim = None
            observation.embedding_created_at = None
        self.session.commit()
        self.session.refresh(observation)
        return observation.embedding_status

    def generate_embedding(self, text: str) -> list[float]:
        if self.provider == "openai_compatible":
            return self._openai_compatible_embedding(text)
        if self.provider == "local_sentence_transformers":
            return self._local_sentence_transformer_embedding(text)
        raise RuntimeError(f"Unsupported embedding provider: {self.provider}")

    def _provider_status(self) -> str:
        if self.provider == "disabled":
            return "disabled"
        if self.provider == "openai_compatible":
            return "ready" if self.settings.embedding_api_url and self.model else "misconfigured"
        if self.provider == "local_sentence_transformers":
            return (
                "ready"
                if importlib.util.find_spec("sentence_transformers") is not None
                else "unavailable"
            )
        return "unsupported"

    def _openai_compatible_embedding(self, text: str) -> list[float]:
        if not self.settings.embedding_api_url:
            raise RuntimeError("KINLAYER_EMBEDDING_API_URL is required.")
        if not self.model:
            raise RuntimeError("KINLAYER_EMBEDDING_MODEL is required.")
        headers = {"Content-Type": "application/json"}
        if self.settings.embedding_api_key:
            headers["Authorization"] = f"Bearer {self.settings.embedding_api_key}"
        response = httpx.post(
            self.settings.embedding_api_url,
            headers=headers,
            json={"model": self.model, "input": text},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        embedding = payload["data"][0]["embedding"]
        if not isinstance(embedding, list) or not embedding:
            raise RuntimeError("Embedding provider returned an empty embedding.")
        return [float(value) for value in embedding]

    def _local_sentence_transformer_embedding(self, text: str) -> list[float]:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is not installed.") from exc
        model = SentenceTransformer(self.model or DEFAULT_LOCAL_MODEL)
        raw = model.encode(text, normalize_embeddings=True)
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        return [float(value) for value in raw]

    def _format_vector(self, embedding: list[float]) -> str:
        return "[" + ",".join(str(value) for value in embedding) + "]"
