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
from api.objection.graph import build_objection_graph

WELL_FORMED_RESPONSE = (
    "WHAT'S TRUE: Volvo has 1 ingested service centre.\n"
    "HOW TO FRAME IT: Acknowledge the gap honestly.\n"
    "WHAT NOT TO CLAIM: Don't promise a new centre opening."
)


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
class _FakeChatCompletions:
    to_replay: list[_FakeCompletion]

    def create(self, **_kwargs: Any) -> _FakeCompletion:
        return self.to_replay.pop(0)


@dataclass
class _FakeChat:
    completions: _FakeChatCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat


def _llm(responses: list[str]) -> LLMClient:
    fake = _FakeOpenAI(
        chat=_FakeChat(
            completions=_FakeChatCompletions(
                to_replay=[
                    _FakeCompletion(choices=[_FakeChoice(message=_FakeCompletionMessage(r))])
                    for r in responses
                ]
            )
        )
    )
    return LLMClient(fake)


def test_graph_classifies_retrieves_and_generates(session: Session) -> None:
    llm = _llm(
        [
            '{"category": "service_network", "confidence": 0.9}',
            WELL_FORMED_RESPONSE,
        ]
    )
    graph = build_objection_graph(llm=llm, embedder=_FakeEmbedder(), session=session)  # type: ignore[arg-type]

    result = graph.invoke(
        {
            "objection_text": "Volvo barely has service centres",
            "context": {"volvo_brand": "Volvo Cars"},
        }
    )

    assert result["category"] == "service_network"
    assert result["abstained"] is False
    assert len(result["facts"]) == 1
    assert "1 ingested service centre" in result["response"].what_is_true
    assert result["violations"] == []


def test_graph_abstains_on_low_confidence(session: Session) -> None:
    llm = _llm(['{"category": "service_network", "confidence": 0.1}'])
    graph = build_objection_graph(llm=llm, embedder=_FakeEmbedder(), session=session)  # type: ignore[arg-type]

    result = graph.invoke({"objection_text": "something vague", "context": {}})

    assert result["abstained"] is True
    assert result.get("facts") is None
    assert "product specialist" in result["response"].how_to_frame_it


def test_graph_abstains_on_other_category_regardless_of_confidence(session: Session) -> None:
    llm = _llm(['{"category": "other", "confidence": 0.99}'])
    graph = build_objection_graph(llm=llm, embedder=_FakeEmbedder(), session=session)  # type: ignore[arg-type]

    result = graph.invoke({"objection_text": "tell me a joke", "context": {}})

    assert result["abstained"] is True


def test_graph_regenerates_once_then_succeeds_after_a_violation(session: Session) -> None:
    unsupported_response = (
        "WHAT'S TRUE: Volvo has invented a self-repairing chassis.\n"
        "HOW TO FRAME IT: x\n"
        "WHAT NOT TO CLAIM: x"
    )
    llm = _llm(
        [
            '{"category": "service_network", "confidence": 0.9}',
            unsupported_response,
            WELL_FORMED_RESPONSE,
        ]
    )
    graph = build_objection_graph(llm=llm, embedder=_FakeEmbedder(), session=session)  # type: ignore[arg-type]

    result = graph.invoke(
        {
            "objection_text": "Volvo barely has service centres",
            "context": {"volvo_brand": "Volvo Cars"},
        }
    )

    assert result["attempts"] == 2
    assert result["violations"] == []
    assert result.get("refused") is not True
    assert "1 ingested service centre" in result["response"].what_is_true


def test_graph_refuses_after_a_second_failed_verification(session: Session) -> None:
    unsupported_response = (
        "WHAT'S TRUE: Volvo has invented a self-repairing chassis.\n"
        "HOW TO FRAME IT: x\n"
        "WHAT NOT TO CLAIM: x"
    )
    llm = _llm(
        [
            '{"category": "service_network", "confidence": 0.9}',
            unsupported_response,
            unsupported_response,
        ]
    )
    graph = build_objection_graph(llm=llm, embedder=_FakeEmbedder(), session=session)  # type: ignore[arg-type]

    result = graph.invoke(
        {
            "objection_text": "Volvo barely has service centres",
            "context": {"volvo_brand": "Volvo Cars"},
        }
    )

    assert result["attempts"] == 2
    assert result["refused"] is True
    assert result["abstained"] is True
    assert "unsupported_claim" in result["response"].how_to_frame_it
