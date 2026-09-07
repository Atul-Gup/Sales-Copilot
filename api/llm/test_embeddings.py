from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai
import pytest

from api.llm.embeddings import EmbeddingClient, EmbeddingError, _estimate_cost_usd

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


@dataclass
class _FakeEmbeddingItem:
    embedding: list[float]
    index: int


@dataclass
class _FakeUsage:
    prompt_tokens: int


@dataclass
class _FakeResponse:
    data: list[_FakeEmbeddingItem]
    usage: _FakeUsage


@dataclass
class _FakeEmbeddingsResource:
    to_replay: list[Exception | _FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        outcome = self.to_replay.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@dataclass
class _FakeOpenAI:
    embeddings: _FakeEmbeddingsResource


def _client(to_replay: list[Exception | _FakeResponse]) -> tuple[EmbeddingClient, _FakeOpenAI]:
    fake = _FakeOpenAI(embeddings=_FakeEmbeddingsResource(to_replay=to_replay))
    return EmbeddingClient(fake), fake


def _response(vectors: list[list[float]], prompt_tokens: int = 10) -> _FakeResponse:
    items = [_FakeEmbeddingItem(embedding=v, index=i) for i, v in enumerate(vectors)]
    return _FakeResponse(data=items, usage=_FakeUsage(prompt_tokens=prompt_tokens))


def test_embed_returns_vectors_in_order() -> None:
    client, _ = _client([_response([[0.1, 0.2], [0.3, 0.4]])])
    result = client.embed(["a", "b"])
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert result.input_tokens == 10


def test_embed_reorders_out_of_order_response_by_index() -> None:
    response = _FakeResponse(
        data=[
            _FakeEmbeddingItem(embedding=[9.0], index=1),
            _FakeEmbeddingItem(embedding=[1.0], index=0),
        ],
        usage=_FakeUsage(prompt_tokens=5),
    )
    client, _ = _client([response])
    result = client.embed(["a", "b"])
    assert result.vectors == [[1.0], [9.0]]


def test_cost_computed_for_known_model() -> None:
    client, _ = _client([_response([[0.0]], prompt_tokens=1_000_000)])
    result = client.embed(["x"], model="text-embedding-3-small")
    assert result.cost_usd == pytest.approx(0.02)


def test_cost_is_none_for_unknown_model() -> None:
    client, _ = _client([_response([[0.0]])])
    result = client.embed(["x"], model="some-future-embedding-model")
    assert result.cost_usd is None


def test_empty_input_raises_value_error() -> None:
    client, _ = _client([])
    with pytest.raises(ValueError, match="at least one text"):
        client.embed([])


def test_sdk_error_wrapped_as_embedding_error() -> None:
    error = openai.APIConnectionError(request=REQUEST)
    client, _ = _client([error])
    with pytest.raises(EmbeddingError):
        client.embed(["x"])


def test_model_and_timeout_are_forwarded() -> None:
    client, fake = _client([_response([[0.0]])])
    client.embed(["hello"], model="text-embedding-3-large")
    call = fake.embeddings.calls[0]
    assert call["input"] == ["hello"]
    assert call["model"] == "text-embedding-3-large"
    assert call["timeout"] == 30.0


def test_estimate_cost_usd_direct() -> None:
    assert _estimate_cost_usd("text-embedding-3-large", 500_000) == pytest.approx(0.065)
