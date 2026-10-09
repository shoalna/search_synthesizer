"""Formatter: turns a user keyword into SearchAssignment[] from a template."""

from importlib import resources
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from search_agents.models import Model, NonEmptyStr, SearchAssignment

KEYWORD_PLACEHOLDER = "{keyword}"


class TemplateError(Exception):
    """The assignment template is missing or malformed."""


class _TemplateEntry(Model):
    """What a template may say about an assignment; its status is the Orchestrator's to set."""

    assignment_id: NonEmptyStr
    required: bool
    objective: NonEmptyStr


def format_assignments(keyword: str, template: Path | None = None) -> list[SearchAssignment]:
    """Render the template's assignments for `keyword`. Uses the built-in template if none is given."""
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword must not be blank")

    name, text = _read_template(template)
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TemplateError(f"{name}: not valid YAML: {exc}") from exc

    entries: Any = (
        cast(dict[Any, Any], data).get("search_assignments") if isinstance(data, dict) else None
    )
    if not isinstance(entries, list) or not entries:
        raise TemplateError(f"{name}: no search_assignments defined")

    assignments: list[SearchAssignment] = []
    seen: set[str] = set()
    for entry in cast(list[Any], entries):
        # The keyword is substituted after parsing, so it can never alter the template's structure.
        if isinstance(entry, dict):
            raw = cast(dict[Any, Any], entry)
            objective: Any = raw.get("objective")
            if isinstance(objective, str):
                entry = {**raw, "objective": objective.replace(KEYWORD_PLACEHOLDER, keyword)}
        try:
            fields = _TemplateEntry.model_validate(entry)
            assignment = SearchAssignment(**fields.model_dump())
        except ValidationError as exc:
            raise TemplateError(f"{name}: invalid search assignment: {exc}") from exc
        if assignment.assignment_id in seen:
            raise TemplateError(f"{name}: duplicate assignment_id '{assignment.assignment_id}'")
        seen.add(assignment.assignment_id)
        assignments.append(assignment)
    return assignments


def _read_template(template: Path | None) -> tuple[str, str]:
    if template is None:
        builtin = resources.files("search_agents") / "templates" / "default.yaml"
        return "built-in template", builtin.read_text(encoding="utf-8")
    try:
        return str(template), template.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"{template}: cannot read template: {exc.strerror}") from exc
