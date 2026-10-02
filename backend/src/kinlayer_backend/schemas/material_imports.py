"""Explicit source imports are attestations, never inferred from source prose."""

import hashlib
import json
from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator, field_validator

from kinlayer_backend.schemas.memories import MemoryFact, MemoryObservation

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
    ai_use_policy: Literal["cautious_use", "ask_before_use", "never_surface"] = Field(
        default="cautious_use", deprecated=True,
        description="Legacy input retained for signed-manifest compatibility; ignored for memory use.",
    )


class MaterialImportScope(ImportModel):
    idempotency_key: Annotated[
        str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    ]
    target_entity_id: Identifier
    sources: list[MaterialSource] = Field(min_length=1, max_length=20)
    authorization: MaterialAuthorization

    def linked_source_ids(self):
        raise NotImplementedError

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
        for source_ids in self.linked_source_ids():
            if len(set(source_ids)) != len(source_ids) or not set(
                source_ids
            ) <= set(sources):
                raise ValueError("Claim source linkage is out of scope.")
            used.update(source_ids)
        if used != set(sources):
            raise ValueError("Every bounded source must support a claim.")
        if any(s.occurred_at is not None and s.occurred_at > auth.occurred_at for s in self.sources):
            raise ValueError("Source dates exceed the authorization time.")
        if any(not value.strip() for value in (auth.excerpt, auth.source_ref, auth.message_id)):
            raise ValueError("Authorization reference and excerpt must be nonempty.")
        if auth.source_ref in {s.source_ref for s in self.sources}:
            raise ValueError("Source material cannot authorize its own import.")
        return self


class MaterialImportRequest(MaterialImportScope):
    """Unversioned V1: retain its exact normalized manifest and digest."""

    claims: list[MaterialClaim] = Field(min_length=1, max_length=20)

    def linked_source_ids(self):
        for claim in self.claims:
            if not claim.summary.strip():
                raise ValueError("Empty synthesis.")
            yield claim.source_ids


class MaterialRecord(ImportModel):
    source_ids: list[Identifier] = Field(min_length=1, max_length=5)
    record: Annotated[MemoryFact | MemoryObservation, Field(discriminator="record_type")]


class MaterialImportV2Request(MaterialImportScope):
    contract_version: Literal["2"]
    records: list[MaterialRecord] = Field(min_length=1, max_length=20)

    def linked_source_ids(self):
        return (item.source_ids for item in self.records)

    @model_validator(mode="after")
    def check_records(self):
        from kinlayer_backend.services.structured_facts import normalize_profile_fact

        for item in self.records:
            record = item.record
            target = record.payload.entity_id if isinstance(record, MemoryFact) else record.payload.subject_entity_id
            if target != self.target_entity_id:
                raise ValueError("Record target must equal the authorized target.")
            # Authorization bounds source statements, not described event times or
            # applicability. A current source may explicitly describe a future period.
            if isinstance(record, MemoryFact):
                _, value = normalize_profile_fact(record.payload.fact_type, record.payload.content, record.payload.value)
                # Compare only known precision; never invent a birthday's year.
                if value.get("year") is not None and date(
                    value["year"], value.get("month") or 1, value.get("day") or 1,
                ) > self.authorization.occurred_at.date():
                    raise ValueError("Profile date exceeds the authorization time.")
        return self


MaterialImportEnvelope = MaterialImportV2Request | MaterialImportRequest
material_import_adapter = TypeAdapter(MaterialImportEnvelope)


class MaterialImportRead(ImportModel):
    validation_scope: Literal["pending_candidates_only", "immediate_memories"] = "pending_candidates_only"
    status: Literal["validated", "submitted", "replayed"]
    import_id: str | None = None
    request_sha256: SHA256
    candidate_ids: list[str] = Field(default_factory=list)
    canonical_record_refs: list[str] = Field(default_factory=list)
    episode_ids: list[str] = Field(default_factory=list)
    candidates: list[dict] = Field(default_factory=list)
    manifest: dict | None = None
    trust_boundary: Literal["authenticated_caller_attestation"] = "authenticated_caller_attestation"
