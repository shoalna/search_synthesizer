"""Renderer: turns a TaskResult into the Markdown report. Presentation only."""

from search_agents.models import AssignmentStatus, SearchAssignment, SourceDocument, TaskResult

_NOT_PROOF_OF_ABSENCE = "This does not establish that no such facts exist."


def render_report(result: TaskResult) -> str:
    documents = {d.source_document_id: d for d in result.source_documents}
    documents_by_assignment: dict[str, list[SourceDocument]] = {}
    turn_counts: dict[str, int] = {}
    for turn in result.agent_turns:
        turn_counts[turn.assignment_id] = turn_counts.get(turn.assignment_id, 0) + 1
        documents_by_assignment.setdefault(turn.assignment_id, []).extend(
            documents[document_id] for document_id in turn.source_document_ids
        )
    claim_count = sum(len(d.claims) for d in result.source_documents)

    lines = [
        f"# Search Report: {_one_line(result.keyword)}",
        "",
        "## Summary",
        "",
        f"- Task: `{result.task_id}`",
        f"- Status: **{result.status.value}**",
        f"- Search provider: `{result.provider}`",
        f"- Assignments: {len(result.assignments)}",
        f"- Agent turns: {len(result.agent_turns)}",
        f"- Source documents: {len(result.source_documents)}",
        f"- Claims: {claim_count}",
        "",
        "## Findings",
    ]
    for assignment in result.assignments:
        lines += ["", f"### {assignment.assignment_id}", "", f"> {_one_line(assignment.objective)}", ""]
        cited = [
            f"- {_one_line(claim.text)} [{claim.claim_id}] "
            f"({document.source_document_id}: <{document.source.url}>)"
            + ("" if claim.material_to_assignment else " _(not material to this assignment)_")
            for document in documents_by_assignment.get(assignment.assignment_id, [])
            for claim in document.claims
        ]
        lines += cited or ["_No evidence was retrieved for this assignment._"]

    lines += ["", "## Sources", ""]
    lines += [
        f"- **{d.source_document_id}**: {_one_line(d.source.title or 'Untitled')} <{d.source.url}>"
        for d in result.source_documents
    ] or ["_No sources were retrieved._"]

    lines += ["", "## Search Gaps", ""]
    lines += [_gap(a) for a in result.assignments if _has_gap(a)] or ["_None recorded._"]

    lines += [
        "",
        "## Search Coverage",
        "",
        "| Assignment | Required | Status | Termination reason | Agent turns | Sources | Claims |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for assignment in result.assignments:
        assignment_documents = documents_by_assignment.get(assignment.assignment_id, [])
        lines.append(
            f"| {assignment.assignment_id} "
            f"| {'yes' if assignment.required else 'no'} "
            f"| {assignment.status.value} "
            f"| {_reason(assignment)} "
            f"| {turn_counts.get(assignment.assignment_id, 0)} "
            f"| {len(assignment_documents)} "
            f"| {sum(len(d.claims) for d in assignment_documents)} |"
        )
    return "\n".join(lines) + "\n"


def _has_gap(assignment: SearchAssignment) -> bool:
    return (
        assignment.status is not AssignmentStatus.COMPLETE
        or assignment.termination_reason is not None
    )


def _gap(assignment: SearchAssignment) -> str:
    return (
        f"- `{assignment.assignment_id}`: {assignment.status.value} ({_reason(assignment)}). "
        "No complete set of material evidence was retrieved within this search's policy and budget. "
        f"{_NOT_PROOF_OF_ABSENCE}"
    )


def _reason(assignment: SearchAssignment) -> str:
    return assignment.termination_reason.value if assignment.termination_reason else "-"


def _one_line(text: str) -> str:
    """Source text is untrusted: keep it from starting new Markdown blocks."""
    return " ".join(text.split())
