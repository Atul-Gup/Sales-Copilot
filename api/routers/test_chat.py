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
from api.services.verify import GroundingViolation, VerifiedGenerationResult, extract_claims


class _FakeLLMClient:
    """Never actually called — `pipeline_answer` is monkeypatched below —
    but the `get_llm` dependency still runs, so this must construct cleanly."""


def _override_llm() -> LLMClient:
    return _FakeLLMClient()  # type: ignore[return-value]


def _override_db() -> Generator[Session]:
    yield None  # type: ignore[misc]


def _patch_answer(fake: Any) -> None:
    app.dependency_overrides[get_llm] = _override_llm
    app.dependency_overrides[get_db] = _override_db
    setattr(chat_module, "pipeline_answer", fake)  # noqa: B010


def _unpatch_answer(original: Any) -> None:
    setattr(chat_module, "pipeline_answer", original)  # noqa: B010
    app.dependency_overrides.clear()


def test_chat_returns_a_no_answer_outside_corpus_warning() -> None:
    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text="I don't have that documented for XC60.",
            refused=True,
            conceded=False,
            intent=QueryType.SPEC,
            top_score=0.0,
            verification=None,
            refusal_reason="no_answer_outside_corpus",
        )

    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    _patch_answer(_fake_answer)
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "Euro NCAP rating for the XC60?"})
        assert response.status_code == 200
        body = response.json()
        assert body["response"] == "I don't have that documented for XC60."
        assert body["claims"] == []
        assert body["warnings"] == [
            {
                "type": "no_answer_outside_corpus",
                "text": "Nothing in the sourced documents answers this — not something to "
                "relay as fact.",
            }
        ]
    finally:
        _unpatch_answer(original)


def test_chat_returns_a_must_concede_warning() -> None:
    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text="By the numbers we have (Volvo: 5, BMW: 2 centres) ...",
            refused=False,
            conceded=True,
            intent=QueryType.OBJECTION,
            top_score=1.0,
            verification=None,
        )

    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    _patch_answer(_fake_answer)
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "BMW has more service centres?"})
        body = response.json()
        assert body["warnings"] == [
            {
                "type": "must_concede",
                "text": "This concedes a known Volvo weakness, verified from real data — "
                "not a deflection.",
            }
        ]
    finally:
        _unpatch_answer(original)


def test_chat_returns_claims_from_a_generated_answer() -> None:
    generation = GenerationResult(
        text="Boot space is 709 litres [1].",
        intent=QueryType.SPEC,
        citations=[
            Citation(
                marker=1,
                chunk_id=1,
                section="Dimensions",
                text="709 litres.",
                model_label="Volvo XC60",
            )
        ],
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )
    verification = VerifiedGenerationResult(
        text=generation.text,
        refused=False,
        attempts=1,
        violations=[],
        generation=generation,
        claims=extract_claims(generation),
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

    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    _patch_answer(_fake_answer)
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "boot space?"})
        assert response.status_code == 200
        body = response.json()
        assert body["response"] == "Boot space is 709 litres [1]."
        assert body["claims"] == [
            {
                "text_span": "Boot space is 709 litres [1].",
                "chunk_id": 1,
                "source": "Volvo XC60 — Dimensions",
            }
        ]
        assert body["warnings"] == []
    finally:
        _unpatch_answer(original)


def test_chat_reuses_verify_grounding_claim_extraction_not_a_second_parse() -> None:
    # T7.7: claims must come from api/services/verify.py::extract_claims,
    # the same parsing find_grounding_violations already does — not a
    # second, independent regex pass in the router. Multiple markers in one
    # sentence, and a chunk with no model label, exercise that shared path.
    generation = GenerationResult(
        text="0-100 km/h is 5.3 seconds [1]. Torque is 343 Nm [1][2].",
        intent=QueryType.SPEC,
        citations=[
            Citation(marker=1, chunk_id=10, section="Powertrain", text="0-100: 5.3s, 343 Nm."),
            Citation(marker=2, chunk_id=11, section=None, text="343 Nm confirmed."),
            Citation(marker=3, chunk_id=12, section="Audio", text="9 speakers."),
        ],
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )
    verification = VerifiedGenerationResult(
        text=generation.text,
        refused=False,
        attempts=1,
        violations=[],
        generation=generation,
        claims=extract_claims(generation),
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

    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    _patch_answer(_fake_answer)
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "0-100 and torque?"})
        body = response.json()
        chunk_ids = [c["chunk_id"] for c in body["claims"]]
        # marker 3 (Audio) is never cited in the text, so it must not appear.
        assert chunk_ids == [10, 10, 11]
        assert body["claims"][2]["source"] == "source document"  # citation.section is None
    finally:
        _unpatch_answer(original)


def test_chat_returns_a_disparagement_warning_alongside_a_refusal() -> None:
    generation = GenerationResult(
        text="The X3 feels cheap compared to the XC60 [1].",
        intent=QueryType.COMPARISON,
        citations=[Citation(marker=1, chunk_id=1, section="Interior", text="Leather trim.")],
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )
    verification = VerifiedGenerationResult(
        text=(
            "I can't verify this against the sourced documents closely enough to hand it " "to you."
        ),
        refused=True,
        attempts=2,
        violations=[
            GroundingViolation(
                claim=generation.text,
                reason="disparagement: State checkable figures, never a characterisation.",
            )
        ],
        generation=generation,
        claims=[],
    )

    def _fake_answer(query: str, session: Session, **kwargs: Any) -> AnswerResult:
        return AnswerResult(
            text=verification.text,
            refused=True,
            conceded=False,
            intent=QueryType.COMPARISON,
            top_score=0.5,
            verification=verification,
            refusal_reason="grounding_violation",
        )

    original = getattr(chat_module, "pipeline_answer")  # noqa: B009
    _patch_answer(_fake_answer)
    try:
        with TestClient(app) as client:
            response = client.post("/chat", json={"query": "is the X3 worse than the XC60?"})
        body = response.json()
        assert body["claims"] == []
        assert body["warnings"] == [
            {
                "type": "disparagement",
                "text": "State checkable figures, never a characterisation.",
            }
        ]
    finally:
        _unpatch_answer(original)


def test_chat_rejects_a_missing_query_field() -> None:
    with TestClient(app) as client:
        response = client.post("/chat", json={})
    assert response.status_code == 422
