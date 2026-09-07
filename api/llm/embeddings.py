"""api/llm/embeddings.py — provider-agnostic dense-embedding wrapper (T4.2a).

The second (and, alongside `api/llm/client.py`, only) file permitted to
import a vendor SDK — same reasoning as that module: a future vendor swap
means editing this file, not every ingest/retrieval call site (T4.2b's
hybrid retrieval, T4.3's `retrieve` node).

Unlike `LLMClient`, this client does not retry. Embedding calls here only
happen at ingest time (`ingest/documents.py`), never on a user-facing
request path — a failed ingest run is simply re-run, so the added
complexity of a backoff loop buys nothing yet. Add it if/when embeddings
move onto a live request path.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import openai
import structlog

logger = structlog.get_logger(__name__)

# USD per million input tokens. Embeddings have no output tokens, unlike
# chat completions — see PRICING_USD_PER_MTOK in api/llm/client.py for the
# same "this is an estimate, not a billed figure" caveat.
PRICING_USD_PER_MTOK: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


class EmbeddingError(Exception):
    """An embedding call failed. See `__cause__` for the underlying SDK error."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    input_tokens: int
    cost_usd: float | None
    latency_ms: float


class _EmbeddingsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _OpenAILike(Protocol):
    """The slice of `openai.OpenAI` this module uses — see the matching
    `_OpenAILike` Protocol in `api/llm/client.py` for why `embeddings` is
    a read-only property (covariance) rather than a plain attribute.
    """

    @property
    def embeddings(self) -> _EmbeddingsResource: ...


def _estimate_cost_usd(model: str, input_tokens: int) -> float | None:
    price = PRICING_USD_PER_MTOK.get(model)
    if price is None:
        logger.warning("embedding_cost_unknown_model", model=model)
        return None
    return (input_tokens / 1_000_000) * price


class EmbeddingClient:
    """Dense embeddings via OpenAI, with token/cost logging.

    `client` is injectable for testing — pass anything structurally matching
    `_OpenAILike`. Production code leaves it unset and gets a real
    `openai.OpenAI()`, which reads `OPENAI_API_KEY` from the environment.
    """

    def __init__(self, client: _OpenAILike | None = None, *, timeout_s: float = 30.0) -> None:
        self._client: _OpenAILike = client if client is not None else openai.OpenAI()  # type: ignore[assignment]
        self._timeout_s = timeout_s

    def embed(
        self, texts: Sequence[str], *, model: str = "text-embedding-3-small"
    ) -> EmbeddingResult:
        if not texts:
            raise ValueError("embed() requires at least one text")

        start = time.perf_counter()
        try:
            response = self._client.embeddings.create(
                input=list(texts), model=model, timeout=self._timeout_s
            )
        except openai.OpenAIError as exc:
            logger.error("embedding_call_failed", model=model, error=str(exc))
            raise EmbeddingError(f"embedding call failed: {exc}") from exc
        latency_ms = (time.perf_counter() - start) * 1000

        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        input_tokens = response.usage.prompt_tokens
        cost_usd = _estimate_cost_usd(model, input_tokens)

        logger.info(
            "embedding_call",
            model=model,
            n_texts=len(texts),
            input_tokens=input_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

        return EmbeddingResult(
            vectors=vectors,
            model=model,
            input_tokens=input_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
