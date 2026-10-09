"""Validated schemas and status enums shared by every component."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Model(BaseModel):
    """Base for all schemas: immutable, and unknown fields are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    SEARCHING = "searching"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    SEARCHING = "searching"
    VALIDATING_EVIDENCE = "validating_evidence"
    RESOLVING_CONFLICT = "resolving_conflict"
    SYNTHESIZING = "synthesizing"
    VALIDATING_REPORT = "validating_report"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class TerminationReason(StrEnum):
    SATURATED = "saturated"
    NO_MATERIAL_EVIDENCE = "no_material_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    CANCELLED = "cancelled"


class AgentTurnStatus(StrEnum):
    SUCCESS = "success"
    NO_MATERIAL_EVIDENCE = "no_material_evidence"
    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class DuplicateType(StrEnum):
    NONE = "none"
    DUPLICATE = "duplicate"
    NEAR_DUPLICATE = "near_duplicate"


class SearchAssignment(Model):
    assignment_id: NonEmptyStr
    required: bool
    objective: NonEmptyStr
    status: AssignmentStatus = AssignmentStatus.PENDING
    termination_reason: TerminationReason | None = None


class ProviderUsage(Model):
    """What the provider reported about one AgentTurn. None means not reported."""

    web_search_calls: int | None = Field(default=None, ge=0)
    observed_queries: tuple[str, ...] = ()


class AgentTurn(Model):
    agent_turn_id: NonEmptyStr
    assignment_id: NonEmptyStr
    round: int = Field(ge=1)
    status: AgentTurnStatus
    source_document_ids: tuple[str, ...] = ()
    provider_usage: ProviderUsage = ProviderUsage()
    started_at: datetime
    finished_at: datetime
    error_type: str | None = None


class SourceInfo(Model):
    url: str
    canonical_url: str | None = None
    title: str | None = None
    publisher: str | None = None
    author: str | None = None
    published_at: str | None = None
    updated_at: str | None = None
    retrieved_at: datetime
    language: str | None = None
    exact_content_hash: str | None = None
    normalized_content_hash: str | None = None

    @field_validator("url", "canonical_url")
    @classmethod
    def _must_be_http(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        if any(char.isspace() or not char.isprintable() or char in "<>" for char in value):
            raise ValueError("must not contain whitespace, control characters or angle brackets")
        return value


class DuplicateInfo(Model):
    duplicate_cluster_id: str | None = None
    duplicate_type: DuplicateType = DuplicateType.NONE


class DeclaredProvenance(Model):
    type: NonEmptyStr
    target_url: NonEmptyStr


class Locator(Model):
    section: str | None = None
    excerpt: str | None = None


class ExtractedClaim(Model):
    """An atomic claim as a provider extracted it, before the Evidence Store names it."""

    text: NonEmptyStr
    language: str | None = None
    material_to_assignment: bool
    locator: Locator = Locator()


class Claim(ExtractedClaim):
    """A raw Claim in the Evidence Store. Never rewritten after it is stored."""

    claim_id: NonEmptyStr


class RetrievedDocument(Model):
    """A source document as a provider returned it, before the Evidence Store names it."""

    source: SourceInfo
    declared_provenance: tuple[DeclaredProvenance, ...] = ()
    claims: tuple[ExtractedClaim, ...] = ()


class SourceDocument(Model):
    source_document_id: NonEmptyStr
    source: SourceInfo
    duplicate: DuplicateInfo = DuplicateInfo()
    declared_provenance: tuple[DeclaredProvenance, ...] = ()
    claims: tuple[Claim, ...] = ()


class TaskResult(Model):
    """The canonical structured output of one task; report.md is rendered from it."""

    task_id: NonEmptyStr
    keyword: NonEmptyStr
    provider: NonEmptyStr
    status: TaskStatus
    assignments: tuple[SearchAssignment, ...]
    agent_turns: tuple[AgentTurn, ...]
    source_documents: tuple[SourceDocument, ...]
