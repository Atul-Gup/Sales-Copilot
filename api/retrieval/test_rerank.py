from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx2
import openai
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.client import LLMClient
from api.models import Base, DocumentChunk, Source
from api.retrieval.rerank import rerank

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _chunks(session: Session, n: int) -> list[DocumentChunk]:
    source = Source(
        kind="oem_site",
        publisher="Test",
        url="https://example.com",
        document_title="Test Doc",
        retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
        verified_at=datetime(2026, 9, 4, tzinfo=UTC),
        checksum="deadbeef",
    )
    session.add(source)
    session.flush()
    chunks = []
    for i in range(n):
        chunk = DocumentChunk(
            source_id=source.id,
            document_title="Test Doc",
            section=None,
            page=i + 1,
            text=f"candidate text {i}",
            embedding=[0.0],
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()
    return chunks


@dataclass
class _FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5


@dataclass
class _FakeCompletionMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeCompletionMessage


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]
    usage: _FakeUsage = field(default_factory=_FakeUsage)


@dataclass
class _FakeChatCompletions:
    to_replay: list[Exception | _FakeCompletion]

    def create(self, **_kwargs: Any) -> _FakeCompletion:
        outcome = self.to_replay.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _FakeChat:
    completions: _FakeChatCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat


def _message(text: str) -> _FakeCompletion:
    return _FakeCompletion(choices=[_FakeChoice(message=_FakeCompletionMessage(content=text))])


def _llm(to_replay: list[Exception | _FakeCompletion]) -> LLMClient:
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=to_replay)))
    return LLMClient(fake)


def test_rerank_returns_ids_in_the_models_order(session: Session) -> None:
    chunks = _chunks(session, 3)
    response_text = f"[{chunks[2].id}, {chunks[0].id}]"
    llm = _llm([_message(response_text)])

    result = rerank(llm, "some query", chunks, top_k=2)

    assert result.chunk_ids == [chunks[2].id, chunks[0].id]
    assert result.fell_back is False


def test_rerank_pads_with_leftover_candidates_if_model_returns_too_few(
    session: Session,
) -> None:
    chunks = _chunks(session, 3)
    response_text = f"[{chunks[1].id}]"
    llm = _llm([_message(response_text)])

    result = rerank(llm, "q", chunks, top_k=2)

    assert result.chunk_ids[0] == chunks[1].id
    assert len(result.chunk_ids) == 2


def test_rerank_ignores_ids_not_in_the_candidate_set(session: Session) -> None:
    chunks = _chunks(session, 2)
    response_text = f"[999, {chunks[0].id}]"
    llm = _llm([_message(response_text)])

    result = rerank(llm, "q", chunks, top_k=1)

    assert result.chunk_ids == [chunks[0].id]


def test_rerank_falls_back_on_unparseable_response(session: Session) -> None:
    chunks = _chunks(session, 3)
    llm = _llm([_message("not json at all")])

    result = rerank(llm, "q", chunks, top_k=2)

    assert result.fell_back is True
    assert result.chunk_ids == [chunks[0].id, chunks[1].id]


def test_rerank_falls_back_on_llm_error(session: Session) -> None:
    chunks = _chunks(session, 2)
    error = openai.APIConnectionError(message="conn", request=REQUEST)
    llm = _llm([error, error, error])

    result = rerank(llm, "q", chunks, top_k=2)

    assert result.fell_back is True
    assert result.chunk_ids == [chunks[0].id, chunks[1].id]


def test_rerank_empty_candidates_returns_empty(session: Session) -> None:
    llm = _llm([])
    result = rerank(llm, "q", [], top_k=5)
    assert result.chunk_ids == []
    assert result.fell_back is False
