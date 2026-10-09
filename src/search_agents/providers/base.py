"""The SearchProvider seam: what the Orchestrator asks of any search provider."""

from typing import Protocol, Self

from pydantic import Field, model_validator

from search_agents.models import (
    AgentTurnStatus,
    Model,
    NonEmptyStr,
    ProviderUsage,
    RetrievedDocument,
)


class ProviderCapabilities(Model):
    """What a provider can enforce or report. Control flow may depend on these, never on the name."""

    enforces_web_search_call_cap: bool = False
    restricts_domains: bool = False
    reports_observed_queries: bool = False


class PolicySlice(Model):
    """The part of the SearchPolicy that applies to one assignment. No policy fields exist yet."""


class RoundBudget(Model):
    max_wall_time_seconds: float = Field(default=300, gt=0)
    max_web_search_calls: int = Field(default=15, ge=0)


class TurnRequest(Model):
    assignment_id: NonEmptyStr
    objective: NonEmptyStr
    policy: PolicySlice = PolicySlice()
    round: int = Field(default=1, ge=1)
    budget: RoundBudget = RoundBudget()
    known_urls: tuple[str, ...] = ()


class TurnResult(Model):
    status: AgentTurnStatus
    source_documents: tuple[RetrievedDocument, ...] = ()
    provider_usage: ProviderUsage = ProviderUsage()
    error_type: str | None = None

    @property
    def has_material_claims(self) -> bool:
        return any(
            claim.material_to_assignment
            for document in self.source_documents
            for claim in document.claims
        )

    @model_validator(mode="after")
    def _status_matches_evidence(self) -> Self:
        if self.status is AgentTurnStatus.SUCCESS and not self.source_documents:
            raise ValueError("a successful turn must carry at least one source document")
        if self.status is AgentTurnStatus.NO_MATERIAL_EVIDENCE and self.has_material_claims:
            raise ValueError("a no_material_evidence turn must not carry material claims")
        return self


class SearchProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def run_turn(self, request: TurnRequest) -> TurnResult:
        """Run one AgentTurn for an assignment and report what was found."""
        ...
