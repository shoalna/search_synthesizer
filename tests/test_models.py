from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from search_agents.models import (
    AgentTurn,
    AgentTurnStatus,
    AssignmentStatus,
    Claim,
    SearchAssignment,
    SourceDocument,
    TaskStatus,
    TerminationReason,
)

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def source_document_json() -> dict[str, Any]:
    """The README's SourceDocument example, with the elided values filled in."""
    return {
        "source_document_id": "src_123",
        "source": {
            "url": "https://example.com/a",
            "canonical_url": "https://example.com/a",
            "title": "Title",
            "publisher": "Publisher",
            "author": "Author",
            "published_at": "2026-06-01",
            "updated_at": None,
            "retrieved_at": "2026-10-09T00:00:00Z",
            "language": "en",
            "exact_content_hash": "abc",
            "normalized_content_hash": "def",
        },
        "duplicate": {"duplicate_cluster_id": None, "duplicate_type": "none"},
        "declared_provenance": [],
        "claims": [
            {
                "claim_id": "cl_001",
                "text": "Company X launched Product Y in June 2026",
                "language": "en",
                "material_to_assignment": True,
                "locator": {"section": "Intro", "excerpt": "launched Product Y"},
            }
        ],
    }


def test_readme_search_assignment_example_validates() -> None:
    assignment = SearchAssignment.model_validate(
        {
            "assignment_id": "historical_etf_impact",
            "required": True,
            "objective": "ETF分配金発生時のキオクシア株価への過去影響を調査する",
            "status": "pending",
            "termination_reason": None,
        }
    )

    assert assignment.status is AssignmentStatus.PENDING
    assert assignment.termination_reason is None


def test_new_search_assignment_is_pending() -> None:
    assignment = SearchAssignment(assignment_id="a", required=True, objective="調査する")

    assert assignment.status is AssignmentStatus.PENDING


@pytest.mark.parametrize(
    "bad",
    [
        {"assignment_id": "", "required": True, "objective": "x"},
        {"assignment_id": "a", "required": True, "objective": "   "},
        {"assignment_id": "a", "required": True, "objective": "x", "status": "done"},
        {"assignment_id": "a", "required": True, "objective": "x", "termination_reason": "bored"},
        {"assignment_id": "a", "required": True, "objective": "x", "unknown_field": 1},
    ],
)
def test_invalid_search_assignment_is_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SearchAssignment.model_validate(bad)


def test_readme_status_and_reason_values_exist() -> None:
    assert {s.value for s in AgentTurnStatus} == {
        "success",
        "no_material_evidence",
        "cancelled",
        "provider_error",
        "timeout",
        "rate_limited",
    }
    assert {r.name for r in TerminationReason} == {
        "SATURATED",
        "NO_MATERIAL_EVIDENCE",
        "BUDGET_EXHAUSTED",
        "TIMEOUT",
        "PROVIDER_ERROR",
        "RATE_LIMITED",
        "CANCELLED",
    }
    assert {s.name for s in TaskStatus} == {
        "PENDING",
        "SEARCHING",
        "VALIDATING_EVIDENCE",
        "RESOLVING_CONFLICT",
        "SYNTHESIZING",
        "VALIDATING_REPORT",
        "COMPLETE",
        "PARTIAL",
        "FAILED",
    }
    assert {"COMPLETE", "PARTIAL", "FAILED"} <= {s.name for s in AssignmentStatus}


def test_readme_agent_turn_example_validates() -> None:
    turn = AgentTurn.model_validate(
        {
            "agent_turn_id": "turn_123",
            "assignment_id": "historical_etf_impact",
            "round": 1,
            "status": "success",
            "source_document_ids": ["src_1", "src_2"],
            "provider_usage": {"web_search_calls": 7, "observed_queries": []},
            "started_at": "2026-10-09T00:00:00Z",
            "finished_at": "2026-10-09T00:01:00Z",
            "error_type": None,
        }
    )

    assert turn.status is AgentTurnStatus.SUCCESS
    assert turn.provider_usage.web_search_calls == 7


def test_agent_turn_rejects_unknown_status_and_round_zero() -> None:
    base: dict[str, Any] = {
        "agent_turn_id": "turn_1",
        "assignment_id": "a",
        "round": 1,
        "status": "success",
        "started_at": NOW,
        "finished_at": NOW,
    }
    with pytest.raises(ValidationError):
        AgentTurn.model_validate({**base, "status": "ok"})
    with pytest.raises(ValidationError):
        AgentTurn.model_validate({**base, "round": 0})


def test_readme_source_document_example_validates() -> None:
    document = SourceDocument.model_validate(source_document_json())

    assert document.source.url == "https://example.com/a"
    assert document.claims[0].claim_id == "cl_001"
    assert document.claims[0].locator.excerpt == "launched Product Y"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/a\n## Injected heading",
        "https://example.com/a b",
        "https://example.com/a>[x](https://evil.example)",
    ],
)
def test_source_url_must_be_a_plain_http_url(url: str) -> None:
    data = source_document_json()
    data["source"]["url"] = url

    with pytest.raises(ValidationError):
        SourceDocument.model_validate(data)


def test_claim_text_must_not_be_empty() -> None:
    data = source_document_json()
    data["claims"][0]["text"] = "  "

    with pytest.raises(ValidationError):
        SourceDocument.model_validate(data)


def test_claim_cannot_be_modified() -> None:
    document = SourceDocument.model_validate(source_document_json())
    claim: Claim = document.claims[0]

    with pytest.raises(ValidationError):
        claim.text = "something else"  # pyright: ignore[reportAttributeAccessIssue]
    with pytest.raises(ValidationError):
        document.claims = ()  # pyright: ignore[reportAttributeAccessIssue]
