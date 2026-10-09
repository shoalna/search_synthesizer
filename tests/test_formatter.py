from pathlib import Path

import pytest

from search_agents.formatter import TemplateError, format_assignments
from search_agents.models import AssignmentStatus

TEMPLATE = """\
search_assignments:
  - assignment_id: price_history
    required: true
    objective: >
      {keyword}の株価推移を調査する。
      {keyword}と同一セクター企業を比較する。
  - assignment_id: us_market
    required: false
    objective: 昨日のアメリカ株の状況を調査する。
"""


def write_template(tmp_path: Path, text: str = TEMPLATE) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_keyword_is_rendered_into_each_objective(tmp_path: Path) -> None:
    assignments = format_assignments("キオクシア", write_template(tmp_path))

    assert [a.assignment_id for a in assignments] == ["price_history", "us_market"]
    assert assignments[0].objective == (
        "キオクシアの株価推移を調査する。 キオクシアと同一セクター企業を比較する。"
    )
    assert assignments[0].required is True
    assert assignments[1].objective == "昨日のアメリカ株の状況を調査する。"
    assert assignments[1].required is False
    assert all(a.status is AssignmentStatus.PENDING for a in assignments)


def test_same_keyword_and_template_give_the_same_assignments(tmp_path: Path) -> None:
    template = write_template(tmp_path)

    assert format_assignments("キオクシア", template) == format_assignments("キオクシア", template)


def test_built_in_template_is_used_when_none_is_given() -> None:
    assignments = format_assignments("キオクシア")

    assert assignments
    assert any("キオクシア" in a.objective for a in assignments)
    assert all("{keyword}" not in a.objective for a in assignments)


def test_keyword_is_inserted_as_text_not_as_template_syntax(tmp_path: Path) -> None:
    keyword = '{keyword} {0} "x"\n  - assignment_id: injected'

    assignments = format_assignments(keyword, write_template(tmp_path))

    assert [a.assignment_id for a in assignments] == ["price_history", "us_market"]
    assert '{0} "x"' in assignments[0].objective


def test_keyword_is_trimmed_and_must_not_be_blank(tmp_path: Path) -> None:
    template = write_template(tmp_path)

    assert format_assignments("  キオクシア \n", template)[0].objective.startswith("キオクシアの")
    with pytest.raises(ValueError, match="keyword"):
        format_assignments("   ", template)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("search_assignments: []\n", "no search_assignments"),
        ("something_else: 1\n", "no search_assignments"),
        ("search_assignments:\n  - assignment_id: a\n    required: true\n", "objective"),
        (
            "search_assignments:\n"
            "  - {assignment_id: a, required: true, objective: x}\n"
            "  - {assignment_id: a, required: true, objective: y}\n",
            "duplicate assignment_id",
        ),
        ("search_assignments: [unclosed\n", "not valid YAML"),
        (
            "search_assignments:\n"
            "  - {assignment_id: a, required: true, objective: x, status: complete}\n",
            "status",
        ),
    ],
)
def test_invalid_template_is_rejected_with_its_path(
    tmp_path: Path, text: str, message: str
) -> None:
    template = write_template(tmp_path, text)

    with pytest.raises(TemplateError, match=message) as excinfo:
        format_assignments("キオクシア", template)

    assert str(template) in str(excinfo.value)


def test_missing_template_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(TemplateError, match="missing.yaml"):
        format_assignments("キオクシア", tmp_path / "missing.yaml")
