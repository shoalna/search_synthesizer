"""Global Evidence Store: the AgentTurns, SourceDocuments and raw Claims of one task, in SQLite."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from search_agents.models import AgentTurn, Claim, SourceDocument
from search_agents.providers.base import TurnResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_turns (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_documents (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_seq INTEGER NOT NULL REFERENCES source_documents (seq),
    payload TEXT NOT NULL
);
"""

# Raw Claims are immutable, and so is the provenance they are cited to.
_APPEND_ONLY = {
    "claims": "raw claims are immutable",
    "source_documents": "source documents are append-only",
    "agent_turns": "agent turns are append-only",
}
_GUARD = """
CREATE TRIGGER IF NOT EXISTS {table}_no_{name} BEFORE {operation} ON {table}
BEGIN
    SELECT RAISE(ABORT, '{message}');
END;
"""


class EvidenceStore:
    """Append-only store. Ids come from insertion order; a stored raw Claim is never rewritten."""

    def __init__(self, path: Path | str) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(_SCHEMA)
        for table, message in _APPEND_ONLY.items():
            for operation in ("UPDATE", "DELETE"):
                self._connection.executescript(
                    _GUARD.format(
                        table=table, name=operation.lower(), operation=operation, message=message
                    )
                )

    def close(self) -> None:
        self._connection.close()

    def record_turn(
        self,
        *,
        assignment_id: str,
        round: int,
        result: TurnResult,
        started_at: datetime,
        finished_at: datetime,
    ) -> AgentTurn:
        """Store one AgentTurn and the evidence it retrieved, atomically."""
        with self._connection as connection:
            document_ids: list[str] = []
            for retrieved in result.source_documents:
                document_seq = connection.execute(
                    "INSERT INTO source_documents (url, payload) VALUES (?, ?)",
                    (retrieved.source.url, retrieved.model_dump_json(exclude={"claims"})),
                ).lastrowid
                connection.executemany(
                    "INSERT INTO claims (source_document_seq, payload) VALUES (?, ?)",
                    [(document_seq, claim.model_dump_json()) for claim in retrieved.claims],
                )
                document_ids.append(_document_id(document_seq))

            turn = AgentTurn(
                agent_turn_id="unnamed",
                assignment_id=assignment_id,
                round=round,
                status=result.status,
                source_document_ids=tuple(document_ids),
                provider_usage=result.provider_usage,
                started_at=started_at,
                finished_at=finished_at,
                error_type=result.error_type,
            )
            turn_seq = connection.execute(
                "INSERT INTO agent_turns (payload) VALUES (?)",
                (turn.model_dump_json(exclude={"agent_turn_id"}),),
            ).lastrowid
        return turn.model_copy(update={"agent_turn_id": _turn_id(turn_seq)})

    def agent_turns(self) -> list[AgentTurn]:
        rows = self._connection.execute("SELECT seq, payload FROM agent_turns ORDER BY seq")
        return [
            AgentTurn.model_validate({**json.loads(payload), "agent_turn_id": _turn_id(seq)})
            for seq, payload in rows
        ]

    def source_documents(self) -> list[SourceDocument]:
        claims: dict[int, list[Claim]] = {}
        for seq, document_seq, payload in self._connection.execute(
            "SELECT seq, source_document_seq, payload FROM claims ORDER BY seq"
        ):
            claim = Claim.model_validate({**json.loads(payload), "claim_id": _claim_id(seq)})
            claims.setdefault(document_seq, []).append(claim)
        return [
            SourceDocument.model_validate(
                {
                    **json.loads(payload),
                    "source_document_id": _document_id(seq),
                    "claims": claims.get(seq, []),
                }
            )
            for seq, payload in self._connection.execute(
                "SELECT seq, payload FROM source_documents ORDER BY seq"
            )
        ]

    def known_urls(self) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT url FROM source_documents ORDER BY seq")
        return tuple(dict.fromkeys(url for (url,) in rows))


def _claim_id(seq: int) -> str:
    return f"cl_{seq}"


def _document_id(seq: int | None) -> str:
    assert seq is not None, "insert did not yield a row id"
    return f"src_{seq}"


def _turn_id(seq: int | None) -> str:
    assert seq is not None, "insert did not yield a row id"
    return f"turn_{seq}"
