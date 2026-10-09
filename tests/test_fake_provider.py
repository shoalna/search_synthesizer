import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from provider_contract import SearchProviderContract, make_request
from search_agents.models import (
    AgentTurnStatus,
    ExtractedClaim,
    ProviderUsage,
    RetrievedDocument,
    SourceInfo,
)
from search_agents.providers.base import ProviderCapabilities, SearchProvider, TurnResult
from search_agents.providers.fake import FakeSearchProvider
from search_agents.providers.registry import (
    UnknownProviderError,
    create_provider,
    registered_providers,
)


def document(url: str, *, material: bool = True) -> RetrievedDocument:
    return RetrievedDocument(
        source=SourceInfo(url=url, retrieved_at=datetime(2026, 10, 9, tzinfo=UTC)),
        claims=(ExtractedClaim(text=f"claim from {url}", material_to_assignment=material),),
    )


class TestFakeProviderContract(SearchProviderContract):
    @pytest.fixture
    def provider(self) -> SearchProvider:
        return FakeSearchProvider()


class TestScriptedFakeProviderContract(SearchProviderContract):
    """A scripted non-success turn must satisfy the contract too."""

    @pytest.fixture
    def provider(self) -> SearchProvider:
        return FakeSearchProvider(
            script={
                "contract_assignment": [
                    TurnResult(status=AgentTurnStatus.RATE_LIMITED, error_type="RateLimitError")
                ]
            },
            capabilities=ProviderCapabilities(),
        )


def test_unscripted_fake_returns_the_same_evidence_for_the_same_request() -> None:
    provider = FakeSearchProvider()

    first = asyncio.run(provider.run_turn(make_request()))
    second = asyncio.run(provider.run_turn(make_request()))

    assert first.status is AgentTurnStatus.SUCCESS
    assert [d.source.url for d in first.source_documents] == [
        d.source.url for d in second.source_documents
    ]
    assert [d.claims for d in first.source_documents] == [d.claims for d in second.source_documents]


def test_unscripted_fake_gives_each_assignment_its_own_sources() -> None:
    provider = FakeSearchProvider()

    a = asyncio.run(provider.run_turn(make_request(assignment_id="a")))
    b = asyncio.run(provider.run_turn(make_request(assignment_id="b")))

    assert {d.source.url for d in a.source_documents}.isdisjoint(
        d.source.url for d in b.source_documents
    )


def test_scripted_fake_replays_results_per_assignment_and_round() -> None:
    round_one = TurnResult(
        status=AgentTurnStatus.SUCCESS,
        source_documents=(document("https://example.com/1"),),
        provider_usage=ProviderUsage(web_search_calls=3),
    )
    round_two = TurnResult(status=AgentTurnStatus.TIMEOUT, error_type="TimeoutError")
    provider = FakeSearchProvider(script={"a": [round_one, round_two]})

    assert asyncio.run(provider.run_turn(make_request(assignment_id="a", round=1))) == round_one
    assert asyncio.run(provider.run_turn(make_request(assignment_id="a", round=2))) == round_two


def test_scripted_fake_finds_nothing_once_the_script_runs_out() -> None:
    provider = FakeSearchProvider(script={"a": []})

    result = asyncio.run(provider.run_turn(make_request(assignment_id="a", round=1)))

    assert result.status is AgentTurnStatus.NO_MATERIAL_EVIDENCE
    assert result.source_documents == ()


def test_fake_records_the_requests_it_received() -> None:
    provider = FakeSearchProvider()
    request = make_request(assignment_id="a", known_urls=("https://example.com/known",))

    asyncio.run(provider.run_turn(request))

    assert provider.requests == [request]


def test_success_without_documents_is_not_a_valid_turn_result() -> None:
    with pytest.raises(ValidationError):
        TurnResult(status=AgentTurnStatus.SUCCESS)


def test_no_material_evidence_with_material_claims_is_not_a_valid_turn_result() -> None:
    with pytest.raises(ValidationError):
        TurnResult(
            status=AgentTurnStatus.NO_MATERIAL_EVIDENCE,
            source_documents=(document("https://example.com/1", material=True),),
        )


def test_fake_is_the_registered_provider() -> None:
    assert registered_providers() == ["fake"]
    assert create_provider("fake").name == "fake"


def test_unknown_provider_name_lists_the_registered_ones() -> None:
    with pytest.raises(UnknownProviderError) as excinfo:
        create_provider("nope")

    assert "nope" in str(excinfo.value)
    assert "fake" in str(excinfo.value)
