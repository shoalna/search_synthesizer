import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from search_agents.evidence_store import EvidenceStore
from search_agents.models import (
    AgentTurn,
    AgentTurnStatus,
    ExtractedClaim,
    Locator,
    ProviderUsage,
    RetrievedDocument,
    SourceInfo,
)
from search_agents.providers.base import TurnResult

STARTED = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)
FINISHED = datetime(2026, 10, 9, 1, 1, tzinfo=UTC)


def document(url: str, *claim_texts: str) -> RetrievedDocument:
    return RetrievedDocument(
        source=SourceInfo(url=url, title=f"Title of {url}", retrieved_at=STARTED, language="ja"),
        claims=tuple(
            ExtractedClaim(
                text=text,
                language="ja",
                material_to_assignment=True,
                locator=Locator(section="本文", excerpt=text),
            )
            for text in claim_texts
        ),
    )


def success(*documents: RetrievedDocument) -> TurnResult:
    return TurnResult(
        status=AgentTurnStatus.SUCCESS,
        source_documents=documents,
        provider_usage=ProviderUsage(web_search_calls=2, observed_queries=("q1",)),
    )


def record(store: EvidenceStore, assignment_id: str, result: TurnResult, round: int = 1) -> AgentTurn:
    return store.record_turn(
        assignment_id=assignment_id,
        round=round,
        result=result,
        started_at=STARTED,
        finished_at=FINISHED,
    )


@pytest.fixture
def store(tmp_path: Path) -> EvidenceStore:
    return EvidenceStore(tmp_path / "evidence.sqlite3")


def test_recorded_turn_stores_its_documents_and_claims(store: EvidenceStore) -> None:
    turn = record(
        store,
        "a",
        success(
            document("https://example.com/1", "売上高は100億円", "営業利益は10億円"),
            document("https://example.com/2", "従業員は500人"),
        ),
    )

    documents = store.source_documents()
    assert turn.assignment_id == "a"
    assert turn.round == 1
    assert turn.status is AgentTurnStatus.SUCCESS
    assert turn.provider_usage.web_search_calls == 2
    assert turn.started_at == STARTED
    assert turn.finished_at == FINISHED
    assert turn.source_document_ids == tuple(d.source_document_id for d in documents)
    assert [d.source.url for d in documents] == ["https://example.com/1", "https://example.com/2"]
    assert [c.text for c in documents[0].claims] == ["売上高は100億円", "営業利益は10億円"]
    assert documents[0].claims[0].locator.excerpt == "売上高は100億円"
    assert documents[0].source.title == "Title of https://example.com/1"
    assert store.agent_turns() == [turn]


def test_every_turn_document_and_claim_gets_its_own_id(store: EvidenceStore) -> None:
    first = record(store, "a", success(document("https://example.com/1", "x", "y")))
    second = record(store, "b", success(document("https://example.com/2", "z")))

    documents = store.source_documents()
    claim_ids = [c.claim_id for d in documents for c in d.claims]
    assert first.agent_turn_id != second.agent_turn_id
    assert len({d.source_document_id for d in documents}) == 2
    assert len(set(claim_ids)) == 3


def test_failed_turn_is_recorded_without_evidence(store: EvidenceStore) -> None:
    turn = record(
        store, "a", TurnResult(status=AgentTurnStatus.PROVIDER_ERROR, error_type="ServerError")
    )

    assert turn.status is AgentTurnStatus.PROVIDER_ERROR
    assert turn.error_type == "ServerError"
    assert turn.source_document_ids == ()
    assert store.source_documents() == []
    assert store.agent_turns() == [turn]


def test_known_urls_are_those_of_stored_documents(store: EvidenceStore) -> None:
    assert store.known_urls() == ()

    record(store, "a", success(document("https://example.com/1", "x")))
    record(store, "b", success(document("https://example.com/2", "y")))

    assert store.known_urls() == ("https://example.com/1", "https://example.com/2")


def test_evidence_survives_reopening_the_store(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    first = EvidenceStore(path)
    turn = record(first, "a", success(document("https://example.com/1", "売上高は100億円")))
    stored = first.source_documents()
    first.close()

    reopened = EvidenceStore(path)

    assert reopened.source_documents() == stored
    assert reopened.agent_turns() == [turn]


def test_later_turns_do_not_change_already_stored_claims(store: EvidenceStore) -> None:
    record(store, "a", success(document("https://example.com/1", "売上高は100億円")))
    before = store.source_documents()[0]

    record(store, "b", success(document("https://example.com/1", "売上高は999億円")), round=2)

    assert store.source_documents()[0] == before


def test_stored_claims_cannot_be_rewritten_or_deleted_in_the_database(tmp_path: Path) -> None:
    path = tmp_path / "evidence.sqlite3"
    store = EvidenceStore(path)
    record(store, "a", success(document("https://example.com/1", "売上高は100億円")))
    before = store.source_documents()

    connection = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        connection.execute("UPDATE claims SET payload = '{}'")
    with pytest.raises(sqlite3.DatabaseError, match="immutable"):
        connection.execute("DELETE FROM claims")
    connection.close()

    assert store.source_documents() == before


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE source_documents SET url = 'https://example.com/elsewhere'",
        "DELETE FROM source_documents",
        "UPDATE agent_turns SET payload = '{}'",
        "DELETE FROM agent_turns",
    ],
)
def test_provenance_of_stored_claims_cannot_be_rewritten_in_the_database(
    tmp_path: Path, statement: str
) -> None:
    path = tmp_path / "evidence.sqlite3"
    store = EvidenceStore(path)
    record(store, "a", success(document("https://example.com/1", "売上高は100億円")))
    before = (store.source_documents(), store.agent_turns())

    connection = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute(statement)
    connection.close()

    assert (store.source_documents(), store.agent_turns()) == before
