from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai
import pytest

from api.llm.client import LLMClient, LLMError, Message, _estimate_cost_usd

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeCompletionMessage:
    content: str | None


@dataclass
class _FakeChoice:
    message: _FakeCompletionMessage


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]
    usage: _FakeUsage


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


def _stream_gen(items: list[object]) -> Iterator[_FakeChunk]:
    for item in items:
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, _FakeChunk)
        yield item


@dataclass
class _FakeChatCompletions:
    """Records every call and replays a scripted sequence of responses/errors.

    A non-streaming outcome is a `_FakeCompletion` or `Exception`; a
    streaming outcome (`kwargs["stream"]` truthy) is a list of `_FakeChunk`,
    where a trailing `Exception` entry is raised mid-iteration rather than
    returned up front — matching how a real stream fails partway through.
    """

    to_replay: list[Exception | _FakeCompletion | list[object]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: object) -> _FakeCompletion | Iterator[_FakeChunk]:
        self.calls.append(kwargs)
        outcome = self.to_replay.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if kwargs.get("stream"):
            assert isinstance(outcome, list)
            return _stream_gen(outcome)
        assert isinstance(outcome, _FakeCompletion)
        return outcome


@dataclass
class _FakeChat:
    completions: _FakeChatCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat


def _client(
    to_replay: list[Exception | _FakeCompletion | list[object]], **kwargs: Any
) -> tuple[LLMClient, list[float]]:
    sleeps: list[float] = []
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=to_replay)))
    client = LLMClient(fake, sleep=sleeps.append, **kwargs)
    return client, sleeps


def _ok(text: str = "hello", input_tokens: int = 10, output_tokens: int = 5) -> _FakeCompletion:
    return _FakeCompletion(
        choices=[_FakeChoice(message=_FakeCompletionMessage(content=text))],
        usage=_FakeUsage(input_tokens, output_tokens),
    )


def test_successful_call_returns_completion_result() -> None:
    client, _ = _client([_ok("hi there")])
    result = client.complete(
        [Message(role="user", content="hello")], model="gpt-4o", max_tokens=100
    )
    assert result.text == "hi there"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.retries == 0
    assert result.latency_ms >= 0


def test_cost_computed_for_known_model() -> None:
    client, _ = _client([_ok(input_tokens=1_000_000, output_tokens=1_000_000)])
    result = client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10)
    assert result.cost_usd == pytest.approx(2.50 + 10.0)


def test_cost_is_none_for_unknown_model() -> None:
    client, _ = _client([_ok()])
    result = client.complete([Message("user", "x")], model="some-future-model", max_tokens=10)
    assert result.cost_usd is None


def test_retries_transient_error_then_succeeds() -> None:
    error = openai.APIConnectionError(message="conn", request=REQUEST)
    client, sleeps = _client([error, _ok("recovered")], max_attempts=3)
    result = client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10)
    assert result.text == "recovered"
    assert result.retries == 1
    assert sleeps == [0.5]


def test_exhausts_retries_and_raises_llm_error() -> None:
    error = openai.APIConnectionError(message="conn", request=REQUEST)
    client, sleeps = _client([error, error, error], max_attempts=3)
    with pytest.raises(LLMError):
        client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10)
    assert sleeps == [0.5, 1.0]


def test_rate_limit_and_server_errors_are_retryable() -> None:
    response = httpx2.Response(429, request=REQUEST)
    rate_limited = openai.RateLimitError("rate limited", response=response, body=None)
    client, _ = _client([rate_limited, _ok("ok")], max_attempts=2)
    result = client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10)
    assert result.text == "ok"


def test_non_retryable_error_raises_immediately_without_sleeping() -> None:
    response = httpx2.Response(400, request=REQUEST)
    bad_request = openai.BadRequestError("bad request", response=response, body=None)
    client, sleeps = _client([bad_request, _ok("unreachable")], max_attempts=3)
    with pytest.raises(LLMError):
        client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10)
    assert sleeps == []


def test_temperature_is_passed_through() -> None:
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[_ok()])))
    client = LLMClient(fake)
    client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10, temperature=0.2)
    assert fake.chat.completions.calls[0]["temperature"] == 0.2


def test_system_prompt_is_forwarded_as_first_message() -> None:
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[_ok()])))
    client = LLMClient(fake)
    client.complete([Message("user", "x")], model="gpt-4o", max_tokens=10, system="be terse")
    messages = fake.chat.completions.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be terse"}
    assert messages[1] == {"role": "user", "content": "x"}


def test_estimate_cost_usd_direct() -> None:
    assert _estimate_cost_usd("gpt-4o-mini", 500_000, 250_000) == pytest.approx(
        0.5 * 0.15 + 0.25 * 0.60
    )


def test_stream_yields_chunks_in_order() -> None:
    chunks: list[object] = [
        _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta("Hel"))]),
        _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta("lo, "))]),
        _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta("world"))]),
        _FakeChunk(choices=[], usage=_FakeUsage(3, 4)),
    ]
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[chunks])))
    client = LLMClient(fake)

    result = list(client.stream([Message("user", "hi")], model="gpt-4o", max_tokens=100))
    assert result == ["Hel", "lo, ", "world"]


def test_stream_forwards_system_prompt() -> None:
    chunks: list[object] = [
        _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta("ok"))]),
        _FakeChunk(choices=[], usage=_FakeUsage(1, 1)),
    ]
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[chunks])))
    client = LLMClient(fake)

    list(client.stream([Message("user", "hi")], model="gpt-4o", max_tokens=100, system="be terse"))
    messages = fake.chat.completions.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": "be terse"}


def test_stream_raises_llm_error_on_openai_error_mid_stream() -> None:
    response = httpx2.Response(500, request=REQUEST)
    server_error = openai.InternalServerError("boom", response=response, body=None)
    chunks: list[object] = [
        _FakeChunk(choices=[_FakeStreamChoice(delta=_FakeDelta("partial "))]),
        server_error,
    ]
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[chunks])))
    client = LLMClient(fake)

    with pytest.raises(LLMError):
        list(client.stream([Message("user", "hi")], model="gpt-4o", max_tokens=100))


def test_stream_does_not_retry_on_failure() -> None:
    """Unlike `complete()`, a mid-stream failure is not retried — partial
    text has already been yielded to the caller (see `stream()`'s
    docstring)."""
    response = httpx2.Response(500, request=REQUEST)
    server_error = openai.InternalServerError("boom", response=response, body=None)
    chunks: list[object] = [server_error]
    resource = _FakeChatCompletions(to_replay=[chunks])
    fake = _FakeOpenAI(chat=_FakeChat(completions=resource))
    client = LLMClient(fake)

    with pytest.raises(LLMError):
        list(client.stream([Message("user", "hi")], model="gpt-4o", max_tokens=100))
    assert len(resource.calls) == 1
