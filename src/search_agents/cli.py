"""Command line entry point: keyword in, report.md and result.json out."""

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from search_agents.config import ConfigError, load_config
from search_agents.evidence_store import EvidenceStore
from search_agents.formatter import TemplateError, format_assignments
from search_agents.orchestrator import run_task
from search_agents.providers.registry import (
    UnknownProviderError,
    create_provider,
    registered_providers,
)
from search_agents.report import render_report

EVIDENCE_FILE = "evidence.sqlite3"
RESULT_FILE = "result.json"
REPORT_FILE = "report.md"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="search-agents",
        description="Search the web for a keyword and write a cited report.",
    )
    parser.add_argument("keyword", help="what to research")
    parser.add_argument(
        "--provider",
        help=f"search provider for this run (registered: {', '.join(registered_providers())}); "
        "overrides the config file",
    )
    parser.add_argument(
        "--config", type=Path, help="YAML config file (default: ./search_agents.yaml if present)"
    )
    parser.add_argument(
        "--template", type=Path, help="SearchAssignment template (default: built-in)"
    )
    parser.add_argument("--out-dir", type=Path, help="output directory (default: runs/<task id>)")
    args = parser.parse_args(argv)

    task_id = f"task_{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
    out_dir: Path = args.out_dir or Path("runs") / task_id
    try:
        config = load_config(args.config)
        provider = create_provider(args.provider or config.provider)
        assignments = format_assignments(args.keyword, args.template)
        if (out_dir / EVIDENCE_FILE).exists():
            raise FileExistsError(
                f"{out_dir} already holds the evidence of another task; choose a new --out-dir"
            )
    except (ConfigError, UnknownProviderError, TemplateError, ValueError, FileExistsError) as exc:
        print(f"search-agents: error: {exc}", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    store = EvidenceStore(out_dir / EVIDENCE_FILE)
    try:
        result = asyncio.run(
            run_task(
                task_id=task_id,
                keyword=args.keyword.strip(),
                assignments=assignments,
                provider=provider,
                store=store,
            )
        )
    finally:
        store.close()

    (out_dir / RESULT_FILE).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (out_dir / REPORT_FILE).write_text(render_report(result), encoding="utf-8")
    print(f"{result.status.name}: {out_dir / REPORT_FILE}")
    return 0
