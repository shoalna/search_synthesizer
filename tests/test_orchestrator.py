import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from search_agents.evidence_store import EvidenceStore
from search_agents.models import (
    AgentTurnStatus,
    AssignmentStatus,
    ExtractedClaim,
    RetrievedDocument,
    SearchAssignment,
    SourceInfo,
    TaskResult,
    TaskStatus,
    TerminationReason,
)
from search_agents.orchestrator import run_task
from search_agents.providers.base import ProviderCapabilities, TurnResult
from search_agents.providers.fake import FakeSearchProvider
from search_agents.report import render_report


def assignment(assignment_id: str, *, required: bool = True) -> SearchAssignment:
    return SearchAssignment(
        assignment_id=assignment_id, required=required, objective=f"{assignment_id} を調査する"
    )


def found(url: str, text: str, *, material: bool = True) -> TurnResult:
    return TurnResult(
        status=AgentTurnStatus.SUCCESS,
        source_documents=(
            RetrievedDocument(
                source=SourceInfo(url=url, retrieved_at=datetime(2026, 10, 9, tzinfo=UTC)),
                claims=(ExtractedClaim(text=text, material_to_assignment=material),),
            ),
        ),
    )


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "evidence.sqlite3")


def run(
    store: EvidenceStore,
    assignments: Sequence[SearchAssignment],
    script: Mapping[str, Sequence[TurnResult]],
    provider: FakeSearchProvider | None = None,
) -> TaskResult:
    return asyncio.run(
        run_task(
            task_id="task_1",
            keyword="キオクシア",
            assignments=assignments,
            provider=provider or FakeSearchProvider(script=script),
            store=store,
        )
    )


def test_each_assignment_is_searched_and_its_evidence_stored(store: EvidenceStore) -> None:
    result = run(
        store,
        [assignment("a"), assignment("b")],
        {
            "a": [found("https://example.com/a", "売上高は100億円")],
            "b": [found("https://example.com/b", "従業員は500人")],
        },
    )

    assert result.task_id == "task_1"
    assert result.keyword == "キオクシア"
    assert result.provider == "fake"
    assert result.status is TaskStatus.COMPLETE
    assert [(a.assignment_id, a.status) for a in result.assignments] == [
        ("a", AssignmentStatus.COMPLETE),
        ("b", AssignmentStatus.COMPLETE),
    ]
    assert [t.assignment_id for t in result.agent_turns] == ["a", "b"]
    assert list(result.source_documents) == store.source_documents()
    assert list(result.agent_turns) == store.agent_turns()
    assert [c.text for d in result.source_documents for c in d.claims] == [
        "売上高は100億円",
        "従業員は500人",
    ]


def test_turn_request_carries_objective_round_budget_and_known_urls(
    store: EvidenceStore,
) -> None:
    provider = FakeSearchProvider(
        script={
            "a": [found("https://example.com/a", "x")],
            "b": [found("https://example.com/b", "y")],
        }
    )

    run(store, [assignment("a"), assignment("b")], {}, provider)

    first, second = provider.requests
    assert first.assignment_id == "a"
    assert first.objective == "a を調査する"
    assert first.round == 1
    assert first.budget.max_web_search_calls == 15
    assert first.budget.max_wall_time_seconds == 300
    assert first.known_urls == ()
    assert second.assignment_id == "b"
    assert second.known_urls == ("https://example.com/a",)


def test_provider_is_identified_by_its_own_name_not_assumed(store: EvidenceStore) -> None:
    class RenamedFake(FakeSearchProvider):
        name = "another"

    provider = RenamedFake(capabilities=ProviderCapabilities())

    result = run(store, [assignment("a")], {}, provider)

    assert result.provider == "another"
    assert result.status is TaskStatus.COMPLETE


@pytest.mark.parametrize(
    ("turn", "status", "reason"),
    [
        (
            TurnResult(status=AgentTurnStatus.NO_MATERIAL_EVIDENCE),
            AssignmentStatus.COMPLETE,
            TerminationReason.NO_MATERIAL_EVIDENCE,
        ),
        (
            found("https://example.com/a", "関係のない話", material=False),
            AssignmentStatus.COMPLETE,
            TerminationReason.NO_MATERIAL_EVIDENCE,
        ),
        (
            TurnResult(status=AgentTurnStatus.TIMEOUT),
            AssignmentStatus.PARTIAL,
            TerminationReason.TIMEOUT,
        ),
        (
            TurnResult(status=AgentTurnStatus.CANCELLED),
            AssignmentStatus.PARTIAL,
            TerminationReason.CANCELLED,
        ),
        (
            TurnResult(status=AgentTurnStatus.PROVIDER_ERROR, error_type="ServerError"),
            AssignmentStatus.FAILED,
            TerminationReason.PROVIDER_ERROR,
        ),
        (
            TurnResult(status=AgentTurnStatus.RATE_LIMITED),
            AssignmentStatus.FAILED,
            TerminationReason.RATE_LIMITED,
        ),
    ],
)
def test_turn_outcome_decides_assignment_status_and_termination_reason(
    store: EvidenceStore, turn: TurnResult, status: AssignmentStatus, reason: TerminationReason
) -> None:
    result = run(store, [assignment("a")], {"a": [turn]})

    assert result.assignments[0].status is status
    assert result.assignments[0].termination_reason is reason
    assert result.agent_turns[0].status is turn.status


def test_required_assignment_that_did_not_complete_makes_the_task_partial(
    store: EvidenceStore,
) -> None:
    result = run(
        store,
        [assignment("a"), assignment("b")],
        {
            "a": [found("https://example.com/a", "x")],
            "b": [TurnResult(status=AgentTurnStatus.PROVIDER_ERROR)],
        },
    )

    assert result.status is TaskStatus.PARTIAL


def test_optional_assignment_that_failed_leaves_the_task_complete(store: EvidenceStore) -> None:
    result = run(
        store,
        [assignment("a"), assignment("b", required=False)],
        {
            "a": [found("https://example.com/a", "x")],
            "b": [TurnResult(status=AgentTurnStatus.TIMEOUT)],
        },
    )

    assert result.status is TaskStatus.COMPLETE
    assert result.assignments[1].status is AssignmentStatus.PARTIAL


def test_report_names_search_gaps_without_claiming_the_facts_do_not_exist(
    store: EvidenceStore,
) -> None:
    result = run(
        store,
        [assignment("a"), assignment("b"), assignment("c")],
        {
            "a": [found("https://example.com/a", "売上高は100億円")],
            "b": [TurnResult(status=AgentTurnStatus.NO_MATERIAL_EVIDENCE)],
            "c": [TurnResult(status=AgentTurnStatus.TIMEOUT)],
        },
    )

    report = render_report(result)

    assert "**partial**" in report
    assert "PARTIAL" not in report
    gaps = report.split("## Search Gaps")[1].split("\n## ")[0]
    assert "a" not in [line.split("`")[1] for line in gaps.splitlines() if line.startswith("- `")]
    assert "`b`" in gaps and "complete (no_material_evidence)" in gaps
    assert "`c`" in gaps and "partial (timeout)" in gaps
    assert "does not establish that no such facts exist" in gaps


def test_report_keeps_untrusted_source_text_on_one_line(store: EvidenceStore) -> None:
    result = run(
        store,
        [assignment("a")],
        {"a": [found("https://example.com/a", "一行目\n## Injected heading\n続き")]},
    )

    report = render_report(result)

    assert "\n## Injected heading" not in report
    assert "一行目 ## Injected heading 続き" in report


def test_rendering_the_same_result_twice_gives_the_same_report(store: EvidenceStore) -> None:
    result = run(store, [assignment("a")], {"a": [found("https://example.com/a", "x")]})

    assert render_report(result) == render_report(result)
