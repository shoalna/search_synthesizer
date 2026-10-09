import json
from pathlib import Path

import pytest

from search_agents.cli import main


def test_keyword_with_fake_provider_writes_report_and_result_json(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"

    exit_code = main(["キオクシア", "--provider", "fake", "--out-dir", str(out_dir)])

    assert exit_code == 0
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    assert "キオクシア" in report
    assert result["keyword"] == "キオクシア"
    assert result["provider"] == "fake"
    assert result["status"] == "complete"
    assert len(result["assignments"]) >= 1


def test_report_cites_every_stored_claim_back_to_its_source_url(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"

    main(["キオクシア", "--provider", "fake", "--out-dir", str(out_dir)])

    report = (out_dir / "report.md").read_text(encoding="utf-8")
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    documents = result["source_documents"]
    claims = [(claim, doc) for doc in documents for claim in doc["claims"]]
    assert claims, "the fake provider should yield evidence"
    for claim, doc in claims:
        cited = [line for line in report.splitlines() if claim["claim_id"] in line]
        assert cited, f"{claim['claim_id']} is not cited in the report"
        assert any(claim["text"] in line for line in cited)
        assert any(doc["source_document_id"] in line for line in cited)
        assert doc["source"]["url"] in report


def test_report_shows_each_assignment_status(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"

    main(["キオクシア", "--provider", "fake", "--out-dir", str(out_dir)])

    report = (out_dir / "report.md").read_text(encoding="utf-8")
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    for assignment in result["assignments"]:
        assert assignment["assignment_id"] in report
    assert "**complete**" in report
    assert "COMPLETE" not in report


def test_unknown_provider_fails_listing_registered_providers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "run"

    exit_code = main(["キオクシア", "--provider", "nope", "--out-dir", str(out_dir)])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert "nope" in err
    assert "fake" in err
    assert not (out_dir / "report.md").exists()


def test_provider_can_come_from_config_file(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("provider: fake\n", encoding="utf-8")
    out_dir = tmp_path / "run"

    exit_code = main(["キオクシア", "--config", str(config), "--out-dir", str(out_dir)])

    assert exit_code == 0
    result = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    assert result["provider"] == "fake"


def test_command_line_provider_overrides_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("provider: nope\n", encoding="utf-8")
    out_dir = tmp_path / "run"

    exit_code = main(
        ["キオクシア", "--config", str(config), "--provider", "fake", "--out-dir", str(out_dir)]
    )

    assert exit_code == 0


def test_no_provider_chosen_fails_listing_registered_providers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["キオクシア", "--out-dir", str(tmp_path / "run")])

    assert exit_code != 0
    assert "fake" in capsys.readouterr().err


def test_existing_evidence_in_out_dir_is_not_reused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "run"
    assert main(["キオクシア", "--provider", "fake", "--out-dir", str(out_dir)]) == 0

    exit_code = main(["別の会社", "--provider", "fake", "--out-dir", str(out_dir)])

    assert exit_code != 0
    assert str(out_dir) in capsys.readouterr().err
    assert "キオクシア" in (out_dir / "report.md").read_text(encoding="utf-8")
