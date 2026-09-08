from collections.abc import Generator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import api.routers.chat as chat_module
from api.db import get_db
from api.llm.client import LLMClient
from api.main import app
from api.routers.chat import get_llm
from api.services.generate import Citation, GenerationResult
from api.services.pipeline import AnswerResult
from api.services.router import QueryType
from api.services.verify import VerifiedGenerationResult


class _FakeLLMClient:
    """Never actually called — `pipeline_answer` is monkeypatched below —
    but the `get_llm` dependency still runs, so this must construct cleanly."""


def _override_llm() -> LLMClient:
    return _FakeLLMClient()  # type: ignore[return-value]


def _override_db() -> Generator[Session]:
    yield None  # type: ignore[misc]


def test_chat_returns_a_refusal_shape() -> None:
    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text="That's not something I have in the sourced documents for XC60.",
            refused=True,
            conceded=False,
            intent=QueryType.SPEC,
            top_score=0.0,
            verification=None,
        )

    app.dependency_overrides[get_llm] = _override_llm
    app.dependency_overrides[get_db] = _override_db
    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    setattr(chat_module, "pipeline_answer", _fake_answer)  # noqa: B010
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "Euro NCAP rating for the XC60?"})
        assert response.status_code == 200
        body = response.json()
        assert body["refused"] is True
        assert body["conceded"] is False
        assert body["citations"] == []
        assert body["intent"] == "SPEC"
    finally:
        setattr(chat_module, "pipeline_answer", original)  # noqa: B010
        app.dependency_overrides.clear()


def test_chat_returns_citations_from_a_generated_answer() -> None:
    generation = GenerationResult(
        text="Boot space is 709 litres [1].",
        intent=QueryType.SPEC,
        citations=[Citation(marker=1, chunk_id=1, section="Dimensions", text="709 litres.")],
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )
    verification = VerifiedGenerationResult(
        text=generation.text, refused=False, attempts=1, violations=[], generation=generation
    )

    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text=generation.text,
            refused=False,
            conceded=False,
            intent=QueryType.SPEC,
            top_score=0.5,
            verification=verification,
        )

    app.dependency_overrides[get_llm] = _override_llm
    app.dependency_overrides[get_db] = _override_db
    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    setattr(chat_module, "pipeline_answer", _fake_answer)  # noqa: B010
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "boot space?"})
        assert response.status_code == 200
        body = response.json()
        assert body["text"] == "Boot space is 709 litres [1]."
        assert body["citations"] == [{"marker": 1, "section": "Dimensions", "text": "709 litres."}]
    finally:
        setattr(chat_module, "pipeline_answer", original)  # noqa: B010
        app.dependency_overrides.clear()


def test_chat_only_returns_citations_the_answer_actually_references() -> None:
    # Real user report: the answer text cites [1], but generate() offers many
    # more chunks as context than the model ends up using — the response
    # must not dump every offered chunk into `citations`.
    generation = GenerationResult(
        text="0-100 km/h is 5.3 seconds [1].",
        intent=QueryType.SPEC,
        citations=[
            Citation(marker=1, chunk_id=1, section="Powertrain", text="0-100 km/h: 5.3 seconds."),
            Citation(marker=2, chunk_id=2, section="Audio", text="9 speakers."),
            Citation(marker=3, chunk_id=3, section="Interior", text="Leather-free cabin."),
        ],
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )
    verification = VerifiedGenerationResult(
        text=generation.text, refused=False, attempts=1, violations=[], generation=generation
    )

    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text=generation.text,
            refused=False,
            conceded=False,
            intent=QueryType.SPEC,
            top_score=0.5,
            verification=verification,
        )

    app.dependency_overrides[get_llm] = _override_llm
    app.dependency_overrides[get_db] = _override_db
    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    setattr(chat_module, "pipeline_answer", _fake_answer)  # noqa: B010
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "0-100 for the EX30?"})
        body = response.json()
        assert len(body["citations"]) == 1
        assert body["citations"][0]["marker"] == 1
    finally:
        setattr(chat_module, "pipeline_answer", original)  # noqa: B010
        app.dependency_overrides.clear()


def test_chat_rejects_a_missing_query_field() -> None:
    with TestClient(app) as client:
        response = client.post("/chat", json={})
    assert response.status_code == 422
