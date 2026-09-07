"""api/llm/client.py — provider-agnostic LLM wrapper (T4.1).

The only file in this codebase permitted to import a vendor LLM SDK (see
AGENTS.md / ARCHITECTURE.md: "provider-agnostic behind `llm/client.py`. Never
import a vendor SDK outside that module"). Everywhere else sees only
`LLMClient.complete()` and its `Message`/`CompletionResult` types — swapping
the vendor later means editing this file, not every call site (T4.3's
objection generation, T4.4's concession detection, etc.).

Backed by OpenAI's Chat Completions API (T7.4: switched from Anthropic
because only an `OPENAI_API_KEY` was available for the live deploy — every
call site elsewhere in this codebase is unchanged, which is exactly the
point of keeping vendor-specific code confined to this one file).

Retries: a fixed number of attempts with exponential backoff, applied only to
transient failures — rate limits, 5xx, connection drops, timeouts. A bad
request or bad API key is retried zero times, since retrying cannot fix
either.

Cost: computed from the response's reported token counts against
`PRICING_USD_PER_MTOK` below — OpenAI's API reports tokens, not dollars, so
this is this module's own estimate, not a billed figure. See that table's
docstring.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import openai
import structlog

logger = structlog.get_logger(__name__)

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class CompletionResult:
    """One completed LLM call, with everything AGENTS.md requires logged
    (model, tokens, latency, cost) available on the return value too, not
    just in the log line.
    """

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: float
    retries: int


class LLMError(Exception):
    """Every attempt failed, or a non-retryable error was raised immediately.

    Callers should not need to know the vendor SDK's exception hierarchy —
    this is the one error type anything outside this module needs to handle.
    """


# USD per million tokens, as (input_price, output_price). OpenAI's API
# returns token counts, not cost, so this table is this module's own record
# of list pricing, hand-maintained and easy to drift from reality — update it
# when pricing changes, and treat any `cost_usd` derived from it as an
# estimate, never a billed amount. A model missing from this table logs a
# warning and yields `cost_usd=None` rather than a silently wrong number.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
}

_RETRYABLE_OPENAI_ERRORS: tuple[type[Exception], ...] = (
    openai.RateLimitError,
    openai.InternalServerError,
    openai.APIConnectionError,
    openai.APITimeoutError,
)


class _ChatCompletionsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _OpenAILike(Protocol):
    """The slice of `openai.OpenAI` this module actually uses — letting
    tests inject a fake client without needing to construct a real SDK
    client (which needs a real, or at least well-formed, API key).

    `chat` is declared as a read-only property rather than a plain
    attribute: a plain attribute is invariant under structural typing, so a
    fake whose `chat` is typed as the fake's own resource class (not
    literally matching this Protocol) would fail structurally otherwise.
    """

    @property
    def chat(self) -> _ChatNamespace: ...


class _ChatNamespace(Protocol):
    @property
    def completions(self) -> _ChatCompletionsResource: ...


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = PRICING_USD_PER_MTOK.get(model)
    if prices is None:
        logger.warning("llm_cost_unknown_model", model=model)
        return None
    input_price, output_price = prices
    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


def _to_openai_messages(messages: Sequence[Message], system: str | None) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    if system is not None:
        payload.append({"role": "system", "content": system})
    payload.extend({"role": m.role, "content": m.content} for m in messages)
    return payload


class LLMClient:
    """Retries, timeouts, and token/cost logging around the OpenAI SDK.

    `client` is injectable for testing — pass anything structurally matching
    `_OpenAILike` (a `.chat.completions.create(...)`). Production code leaves
    it unset and gets a real `openai.OpenAI()`, which reads `OPENAI_API_KEY`
    from the environment.
    """

    def __init__(
        self,
        client: _OpenAILike | None = None,
        *,
        max_attempts: int = 3,
        timeout_s: float = 30.0,
        backoff_base_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client: _OpenAILike = client if client is not None else openai.OpenAI()  # type: ignore[assignment]
        self._max_attempts = max_attempts
        self._timeout_s = timeout_s
        self._backoff_base_s = backoff_base_s
        self._sleep = sleep

    def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        """Send one completion request, retrying transient failures with
        exponential backoff. Raises `LLMError` if every attempt fails or a
        non-retryable error is raised.
        """
        payload: dict[str, object] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": _to_openai_messages(messages, system),
            "timeout": self._timeout_s,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        start = time.perf_counter()
        response = None
        last_error: Exception | None = None
        attempt = 0
        for attempt in range(self._max_attempts):
            try:
                response = self._client.chat.completions.create(**payload)
                break
            except _RETRYABLE_OPENAI_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "llm_call_retrying",
                    model=model,
                    attempt=attempt + 1,
                    max_attempts=self._max_attempts,
                    error=str(exc),
                )
                if attempt < self._max_attempts - 1:
                    self._sleep(self._backoff_base_s * (2**attempt))
            except openai.OpenAIError as exc:
                logger.error("llm_call_failed", model=model, error=str(exc))
                raise LLMError(f"non-retryable LLM error: {exc}") from exc
        else:
            logger.error("llm_call_exhausted_retries", model=model, max_attempts=self._max_attempts)
            raise LLMError(
                f"LLM call failed after {self._max_attempts} attempts: {last_error}"
            ) from last_error

        latency_ms = (time.perf_counter() - start) * 1000
        text = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        cost_usd = _estimate_cost_usd(model, input_tokens, output_tokens)

        logger.info(
            "llm_call",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            retries=attempt,
        )

        return CompletionResult(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            retries=attempt,
        )

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
    ) -> Iterator[str]:
        """Yield text deltas as they arrive, for a path where perceived
        latency (first token) matters more than total completion time —
        T6.3 ("Stream objection responses. First token is what matters when
        someone is standing there.").

        Deliberately no retry, unlike `complete()`: a stream that fails
        partway through has already shown the caller partial text, so
        restarting it from scratch would either duplicate or contradict
        what's already been displayed. A caller on a streaming path (see
        `api/objection/stream.py`) treats a failed stream as a reason to end
        the response and fall back to a plain refusal, not as a reason to
        retry from an empty buffer.
        """
        payload: dict[str, object] = {
            "model": model,
            "max_completion_tokens": max_tokens,
            "messages": _to_openai_messages(messages, system),
            "timeout": self._timeout_s,
            "stream": True,
            # Only requesting usage on the stream's final chunk (rather than
            # a separate call) keeps this to the one request the non-streaming
            # `complete()` path also makes.
            "stream_options": {"include_usage": True},
        }

        start = time.perf_counter()
        input_tokens = 0
        output_tokens = 0
        try:
            stream = self._client.chat.completions.create(**payload)
            for chunk in stream:
                if chunk.usage is not None:
                    input_tokens = chunk.usage.prompt_tokens
                    output_tokens = chunk.usage.completion_tokens
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except openai.OpenAIError as exc:
            logger.error("llm_stream_failed", model=model, error=str(exc))
            raise LLMError(f"LLM stream failed: {exc}") from exc

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "llm_stream_completed",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_estimate_cost_usd(model, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )
