"""api/objection/test_stream.py — the streaming objection path (T6.3)."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.client import LLMClient
from api.llm.embeddings import EmbeddingResult
from api.models import Base, Brand, ServiceCentre, Source
from api.objection.stream import stream_objection_response


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
        volvo = Brand(name="Volvo Cars", segment="luxury")
        db.add(volvo)
        db.flush()
        source = Source(
            kind="service_locator",
            publisher="Test",
            url="https://example.com",
            document_title=None,
            retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
            verified_at=datetime(2026, 9, 4, tzinfo=UTC),
            checksum="deadbeef",
        )
        db.add(source)
        db.flush()
        db.add(
            ServiceCentre(
                brand_id=volvo.id, city="Mumbai", state="MH", address="x", source_id=source.id
            )
        )
        db.commit()
        yield db


@dataclass
class _FakeEmbedder:
    def embed(self, texts: list[str], **_kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] for _ in texts],
            model="fake",
            input_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
        )


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
class _FakeDelta:
    content: str | None


@dataclass
class _FakeStreamChoice:
    delta: _FakeDelta


@dataclass
class _FakeChunk:
    choices: list[_FakeStreamChoice]
    usage: _FakeUsage | None = None


def _stream_gen(chunks: list[str]) -> Any:
    for chunk in chunks:
        yield _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta(chunk))])
    yield _FakeChunk(choices=[], usage=_FakeUsage())


@dataclass
class _FakeChatCompletions:
    to_replay: list[str]
    stream_chunks: list[str]

    def create(self, **kwargs: Any) -> Any:
        if kwargs.get("stream"):
            return _stream_gen(self.stream_chunks)
        text = self.to_replay.pop(0)
        return _FakeCompletion(choices=[_FakeChoice(message=_FakeCompletionMessage(text))])


@dataclass
class _FakeChat:
    completions: _FakeChatCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat


def _llm(create_replies: list[str], stream_chunks: list[str]) -> LLMClient:
    fake = _FakeOpenAI(
        chat=_FakeChat(
            completions=_FakeChatCompletions(to_replay=create_replies, stream_chunks=stream_chunks)
        )
    )
    return LLMClient(fake)


WELL_FORMED_CHUNKS = [
    "WHAT'S TRUE: Volvo has 1 ingested service centre.\n",
    "HOW TO FRAME IT: That's a fair point — Volvo has fewer centres than rivals.\n",
    "WHAT NOT TO CLAIM: Don't promise a new centre opening.",
]


def test_stream_emits_category_then_tokens_then_done(session: Session) -> None:
    llm = _llm(
        create_replies=['{"category": "service_network", "confidence": 0.95}'],
        stream_chunks=WELL_FORMED_CHUNKS,
    )
    events = list(
        stream_objection_response(
            llm,
            _FakeEmbedder(),  # type: ignore[arg-type]
            session,
            "Volvo barely has service centres",
            {"volvo_brand": "Volvo Cars"},
        )
    )

    assert events[0]["type"] == "category"
    assert events[0]["category"] == "service_network"

    token_events = [e for e in events if e["type"] == "token"]
    assert [e["text"] for e in token_events] == WELL_FORMED_CHUNKS

    assert events[-1]["type"] == "done"
    assert events[-1]["violations"] == []
    assert "1 ingested service centre" in events[-1]["response"].what_is_true


def test_stream_abstains_without_streaming_on_low_confidence(session: Session) -> None:
    llm = _llm(
        create_replies=['{"category": "service_network", "confidence": 0.1}'], stream_chunks=[]
    )
    events = list(
        stream_objection_response(llm, _FakeEmbedder(), session, "something vague")  # type: ignore[arg-type]
    )

    assert events[0]["type"] == "category"
    assert events[1]["type"] == "abstained"
    assert len(events) == 2
    assert "product specialist" in events[1]["response"].how_to_frame_it


def test_stream_emits_refused_on_a_verification_violation(session: Session) -> None:
    unsupported_chunks = [
        "WHAT'S TRUE: Volvo has invented a self-repairing chassis.\n",
        "HOW TO FRAME IT: x\n",
        "WHAT NOT TO CLAIM: x",
    ]
    llm = _llm(
        create_replies=['{"category": "spec_comparison", "confidence": 0.95}'],
        stream_chunks=unsupported_chunks,
    )
    events = list(
        stream_objection_response(llm, _FakeEmbedder(), session, "tell me something")  # type: ignore[arg-type]
    )

    assert events[-1]["type"] == "refused"
    assert events[-1]["violations"]
    # No regenerate attempt on the streaming path — exactly one stream call's
    # worth of tokens is emitted before the refusal.
    token_events = [e for e in events if e["type"] == "token"]
    assert [e["text"] for e in token_events] == unsupported_chunks
