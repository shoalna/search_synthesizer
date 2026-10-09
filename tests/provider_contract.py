"""Contract every SearchProvider must honour.

To put a provider under contract, subclass `SearchProviderContract` in a test module
and override the `provider` fixture:

    class TestMyProviderContract(SearchProviderContract):
        @pytest.fixture
        def provider(self) -> SearchProvider:
            return MyProvider(...)

Providers that call a remote API must be given stubbed or recorded responses here:
the suite has to run without network access or an API key.
"""

import asyncio

import pytest

from search_agents.models import AgentTurnStatus
from search_agents.providers.base import (
    PolicySlice,
    ProviderCapabilities,
    RoundBudget,
    SearchProvider,
    TurnRequest,
    TurnResult,
)


def make_request(
    *,
    assignment_id: str = "contract_assignment",
    round: int = 1,
    max_web_search_calls: int = 15,
    known_urls: tuple[str, ...] = (),
) -> TurnRequest:
    return TurnRequest(
        assignment_id=assignment_id,
        objective="Company X の 2026 年の売上高を調査する。",
        policy=PolicySlice(),
        round=round,
        budget=RoundBudget(max_wall_time_seconds=300, max_web_search_calls=max_web_search_calls),
        known_urls=known_urls,
    )


class SearchProviderContract:
    @pytest.fixture
    def provider(self) -> SearchProvider:
        raise NotImplementedError("override the `provider` fixture")

    def test_exposes_a_name(self, provider: SearchProvider) -> None:
        assert isinstance(provider.name, str)
        assert provider.name.strip() == provider.name != ""

    def test_exposes_capability_flags(self, provider: SearchProvider) -> None:
        assert isinstance(provider.capabilities, ProviderCapabilities)

    def test_turn_returns_a_valid_turn_result(self, provider: SearchProvider) -> None:
        result = asyncio.run(provider.run_turn(make_request()))

        assert isinstance(result, TurnResult)
        assert result.status in set(AgentTurnStatus)
        assert TurnResult.model_validate(result.model_dump()) == result

    def test_status_is_consistent_with_the_evidence_returned(
        self, provider: SearchProvider
    ) -> None:
        result = asyncio.run(provider.run_turn(make_request()))

        if result.status is AgentTurnStatus.SUCCESS:
            assert result.source_documents
            assert any(document.claims for document in result.source_documents)
            assert result.error_type is None
        if result.status is AgentTurnStatus.NO_MATERIAL_EVIDENCE:
            assert not result.has_material_claims

    def test_every_source_has_an_http_url_and_non_empty_claims(
        self, provider: SearchProvider
    ) -> None:
        result = asyncio.run(provider.run_turn(make_request()))

        for document in result.source_documents:
            assert document.source.url.startswith(("http://", "https://"))
            for claim in document.claims:
                assert claim.text.strip()

    def test_a_source_url_appears_once_per_turn(self, provider: SearchProvider) -> None:
        result = asyncio.run(provider.run_turn(make_request()))

        urls = [document.source.url for document in result.source_documents]
        assert len(urls) == len(set(urls))

    def test_search_call_cap_is_honoured_when_the_provider_claims_to_enforce_it(
        self, provider: SearchProvider
    ) -> None:
        result = asyncio.run(provider.run_turn(make_request(max_web_search_calls=1)))

        calls = result.provider_usage.web_search_calls
        if provider.capabilities.enforces_web_search_call_cap and calls is not None:
            assert calls <= 1

    def test_observed_queries_are_reported_only_with_the_capability(
        self, provider: SearchProvider
    ) -> None:
        result = asyncio.run(provider.run_turn(make_request()))

        if not provider.capabilities.reports_observed_queries:
            assert result.provider_usage.observed_queries == ()

    def test_later_rounds_with_known_urls_are_accepted(self, provider: SearchProvider) -> None:
        first = asyncio.run(provider.run_turn(make_request(round=1)))
        known = tuple(document.source.url for document in first.source_documents)

        second = asyncio.run(provider.run_turn(make_request(round=2, known_urls=known)))

        assert isinstance(second, TurnResult)
