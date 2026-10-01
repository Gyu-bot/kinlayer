"""Explicit source imports are attestations, never inferred from source prose."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator, field_validator

Text = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^\S(?:.*\S)?$")]
SHA256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


def json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return text_digest(encoded)


def text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


class ImportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MaterialSource(ImportModel):
    source_id: Identifier
    kind: Literal[
        "user_supplied_chat",
        "user_supplied_document",
        "user_supplied_transcript",
        "designated_external",
    ]
    source_ref: Text
    message_id: Identifier
    author: Annotated[str, Field(min_length=1, max_length=80)]
    author_kind: Literal["human"]
    # Required explicit null means the human material has no known date.
    occurred_at: AwareDatetime | None
    original_sha256: SHA256
    excerpt: Text
    excerpt_sha256: SHA256

    @model_validator(mode="after")
    def check_source(self):
        if not self.excerpt.strip() or not self.author.strip():
            raise ValueError("Empty source evidence or author.")
        if self.author.casefold().strip() in {"assistant", "ai_agent", "system", "tool", "unknown"}:
            raise ValueError("An identified human author is required.")
        if text_digest(self.excerpt) != self.excerpt_sha256:
            raise ValueError("Source excerpt hash mismatch.")
        return self


class MaterialAuthorization(ImportModel):
    actor: Literal["user"]
    user_explicit: Literal[True]
    source_ref: Text
    message_id: Identifier
    occurred_at: AwareDatetime
    excerpt: Text
    target_entity_id: Identifier
    source_ids: list[Identifier] = Field(min_length=1, max_length=20)
    manifest_sha256: SHA256

    @field_validator("user_explicit", mode="before")
    @classmethod
    def require_boolean_true(cls, value):
        if value is not True:
            raise ValueError("Authorization must explicitly be boolean true.")
        return value


class MaterialClaim(ImportModel):
    source_ids: list[Identifier] = Field(min_length=1, max_length=5)
    kind: Literal["sourced_report", "inference"]
    observation_type: Annotated[str, Field(min_length=1, max_length=120)]
    summary: Annotated[str, Field(min_length=1, max_length=1000)]
    confidence: float = Field(ge=0, le=1)
    ai_use_policy: Literal["cautious_use", "ask_before_use", "never_surface"] = "cautious_use"


class MaterialImportRequest(ImportModel):
    idempotency_key: Annotated[
        str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    ]
    target_entity_id: Identifier
    sources: list[MaterialSource] = Field(min_length=1, max_length=20)
    authorization: MaterialAuthorization
    claims: list[MaterialClaim] = Field(min_length=1, max_length=20)

    @field_validator("idempotency_key")
    @classmethod
    def reject_dot_segments(cls, value):
        if value in {".", ".."}:
            raise ValueError("Import key cannot be a URL dot segment.")
        return value

    @model_validator(mode="after")
    def check_scope(self):
        sources = [s.source_id for s in self.sources]
        auth = self.authorization
        if len(set(sources)) != len(sources):
            raise ValueError("Duplicate source identifiers.")
        if auth.target_entity_id != self.target_entity_id:
            raise ValueError("Authorization target mismatch.")
        if len(set(auth.source_ids)) != len(auth.source_ids) or set(auth.source_ids) != set(
            sources
        ):
            raise ValueError("Authorization must name the exact source set.")
        manifest = {
            "target_entity_id": self.target_entity_id,
            "sources": [s.model_dump(mode="json") for s in self.sources],
        }
        if json_digest(manifest) != auth.manifest_sha256:
            raise ValueError("Authorization manifest hash mismatch.")
        used = set()
        for claim in self.claims:
            if len(set(claim.source_ids)) != len(claim.source_ids) or not set(
                claim.source_ids
            ) <= set(sources):
                raise ValueError("Claim source linkage is out of scope.")
            used.update(claim.source_ids)
            if not claim.summary.strip():
                raise ValueError("Empty synthesis.")
        if used != set(sources):
            raise ValueError("Every bounded source must support a claim.")
        if any(s.occurred_at is not None and s.occurred_at > auth.occurred_at for s in self.sources):
            raise ValueError("Source dates exceed the authorization time.")
        if any(not value.strip() for value in (auth.excerpt, auth.source_ref, auth.message_id)):
            raise ValueError("Authorization reference and excerpt must be nonempty.")
        if auth.source_ref in {s.source_ref for s in self.sources}:
            raise ValueError("Source material cannot authorize its own import.")
        return self


class MaterialImportRead(ImportModel):
    validation_scope: Literal["pending_candidates_only"] = "pending_candidates_only"
    status: Literal["validated", "submitted", "replayed"]
    import_id: str | None = None
    request_sha256: SHA256
    candidate_ids: list[str] = Field(default_factory=list)
    episode_ids: list[str] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    manifest: dict | None = None
    trust_boundary: Literal["authenticated_caller_attestation"] = "authenticated_caller_attestation"
