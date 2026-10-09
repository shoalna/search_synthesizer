"""A scripted search provider that never touches the network."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from search_agents.models import (
    AgentTurnStatus,
    ExtractedClaim,
    Locator,
    ProviderUsage,
    RetrievedDocument,
    SourceInfo,
)
from search_agents.providers.base import ProviderCapabilities, TurnRequest, TurnResult


class FakeSearchProvider:
    """Replays scripted TurnResults per assignment and round.

    An assignment with no script gets one made-up source document derived from its
    objective, so a whole task can run end to end. A scripted assignment whose
    script has run out finds no material evidence.
    """

    name = "fake"

    def __init__(
        self,
        script: Mapping[str, Sequence[TurnResult]] | None = None,
        capabilities: ProviderCapabilities | None = None,
    ) -> None:
        self._script = dict(script or {})
        self.capabilities = capabilities or ProviderCapabilities(
            enforces_web_search_call_cap=True,
            reports_observed_queries=True,
        )
        self.requests: list[TurnRequest] = []

    async def run_turn(self, request: TurnRequest) -> TurnResult:
        self.requests.append(request)
        scripted = self._script.get(request.assignment_id)
        if scripted is None:
            return self._made_up_result(request)
        if request.round <= len(scripted):
            return scripted[request.round - 1]
        return TurnResult(status=AgentTurnStatus.NO_MATERIAL_EVIDENCE)

    def _made_up_result(self, request: TurnRequest) -> TurnResult:
        url = f"https://fake.example/{request.assignment_id}/round-{request.round}"
        document = RetrievedDocument(
            source=SourceInfo(
                url=url,
                canonical_url=url,
                title=f"Fake source for {request.assignment_id}",
                publisher="fake provider",
                retrieved_at=datetime.now(UTC),
            ),
            claims=(
                ExtractedClaim(
                    text=f"[fake evidence] {request.objective}",
                    material_to_assignment=True,
                    locator=Locator(section="fake", excerpt=request.objective),
                ),
            ),
        )
        queries = (f"fake query: {request.assignment_id}",)
        return TurnResult(
            status=AgentTurnStatus.SUCCESS,
            source_documents=(document,),
            provider_usage=ProviderUsage(
                web_search_calls=min(1, request.budget.max_web_search_calls),
                observed_queries=queries if self.capabilities.reports_observed_queries else (),
            ),
        )
