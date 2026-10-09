"""Orchestrator: sends each SearchAssignment through the SearchProvider seam and stores the evidence."""

from collections.abc import Sequence
from datetime import UTC, datetime

from search_agents.evidence_store import EvidenceStore
from search_agents.models import (
    AgentTurnStatus,
    AssignmentStatus,
    SearchAssignment,
    TaskResult,
    TaskStatus,
    TerminationReason,
)
from search_agents.providers.base import (
    PolicySlice,
    RoundBudget,
    SearchProvider,
    TurnRequest,
    TurnResult,
)

_OUTCOME_OF_UNSUCCESSFUL_TURN: dict[
    AgentTurnStatus, tuple[AssignmentStatus, TerminationReason]
] = {
    AgentTurnStatus.NO_MATERIAL_EVIDENCE: (
        AssignmentStatus.COMPLETE,
        TerminationReason.NO_MATERIAL_EVIDENCE,
    ),
    AgentTurnStatus.TIMEOUT: (AssignmentStatus.PARTIAL, TerminationReason.TIMEOUT),
    AgentTurnStatus.CANCELLED: (AssignmentStatus.PARTIAL, TerminationReason.CANCELLED),
    AgentTurnStatus.PROVIDER_ERROR: (AssignmentStatus.FAILED, TerminationReason.PROVIDER_ERROR),
    AgentTurnStatus.RATE_LIMITED: (AssignmentStatus.FAILED, TerminationReason.RATE_LIMITED),
}


async def run_task(
    *,
    task_id: str,
    keyword: str,
    assignments: Sequence[SearchAssignment],
    provider: SearchProvider,
    store: EvidenceStore,
) -> TaskResult:
    """Run one Round of one AgentTurn per assignment and report the task's outcome."""
    finished: list[SearchAssignment] = []
    for assignment in assignments:
        request = TurnRequest(
            assignment_id=assignment.assignment_id,
            objective=assignment.objective,
            policy=PolicySlice(),
            round=1,
            budget=RoundBudget(),
            known_urls=store.known_urls(),
        )
        started_at = datetime.now(UTC)
        result = await provider.run_turn(request)
        store.record_turn(
            assignment_id=assignment.assignment_id,
            round=request.round,
            result=result,
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )
        status, reason = _assignment_outcome(result)
        finished.append(
            assignment.model_copy(update={"status": status, "termination_reason": reason})
        )

    return TaskResult(
        task_id=task_id,
        keyword=keyword,
        provider=provider.name,
        status=_task_status(finished),
        assignments=tuple(finished),
        agent_turns=tuple(store.agent_turns()),
        source_documents=tuple(store.source_documents()),
    )


def _assignment_outcome(result: TurnResult) -> tuple[AssignmentStatus, TerminationReason | None]:
    if result.status is not AgentTurnStatus.SUCCESS:
        return _OUTCOME_OF_UNSUCCESSFUL_TURN[result.status]
    if not result.has_material_claims:
        return AssignmentStatus.COMPLETE, TerminationReason.NO_MATERIAL_EVIDENCE
    # A single successful Round is neither saturated nor stopped by a limit, so no reason applies.
    return AssignmentStatus.COMPLETE, None


def _task_status(assignments: Sequence[SearchAssignment]) -> TaskStatus:
    if any(a.required and a.status is not AssignmentStatus.COMPLETE for a in assignments):
        return TaskStatus.PARTIAL
    return TaskStatus.COMPLETE
