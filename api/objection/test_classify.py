from dataclasses import dataclass, field
from typing import Any

import httpx2
import openai

from api.llm.client import LLMClient
from api.objection.classify import CATEGORIES, classify_objection

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


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


def test_classify_parses_valid_response() -> None:
    text = '{"category": "service_network", "confidence": 0.9}'
    llm = _llm([_message(text)])
    result = classify_objection(llm, "Volvo barely has any service centres")
    assert result.category == "service_network"
    assert result.confidence == 0.9


def test_classify_falls_back_to_other_on_unparseable_response() -> None:
    llm = _llm([_message("not json")])
    result = classify_objection(llm, "whatever")
    assert result.category == "other"
    assert result.confidence == 0.0


def test_classify_falls_back_to_other_on_unknown_category() -> None:
    text = '{"category": "made_up", "confidence": 0.9}'
    llm = _llm([_message(text)])
    result = classify_objection(llm, "whatever")
    assert result.category == "other"


def test_classify_falls_back_to_other_on_llm_error() -> None:
    error = openai.APIConnectionError(message="conn", request=REQUEST)
    llm = _llm([error, error, error])
    result = classify_objection(llm, "whatever")
    assert result.category == "other"
    assert result.confidence == 0.0


def test_all_declared_categories_are_valid_json_targets() -> None:
    for category in CATEGORIES:
        text = f'{{"category": "{category}", "confidence": 0.7}}'
        llm = _llm([_message(text)])
        result = classify_objection(llm, "x")
        assert result.category == category
