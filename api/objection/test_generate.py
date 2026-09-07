from dataclasses import dataclass, field
from typing import Any

from api.llm.client import LLMClient
from api.objection.generate import abstain_response, generate_response, refuse_response
from api.objection.state import RetrievedChunk, RetrievedFact


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
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(kwargs)
        return self.to_replay.pop(0)  # type: ignore[return-value]


@dataclass
class _FakeChat:
    completions: _FakeChatCompletions


@dataclass
class _FakeOpenAI:
    chat: _FakeChat


def _message(text: str) -> _FakeCompletion:
    return _FakeCompletion(choices=[_FakeChoice(message=_FakeCompletionMessage(content=text))])


def _llm(text: str) -> LLMClient:
    fake = _FakeOpenAI(chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[_message(text)])))
    return LLMClient(fake)


WELL_FORMED_RESPONSE = (
    "WHAT'S TRUE: Volvo has 5 service centres.\n"
    "HOW TO FRAME IT: Acknowledge the gap and mention roadside assistance.\n"
    "WHAT NOT TO CLAIM: Don't claim a specific new centre opening date."
)


def test_generate_parses_three_sections() -> None:
    llm = _llm(WELL_FORMED_RESPONSE)
    result = generate_response(
        llm,
        "Volvo barely has service centres",
        [RetrievedFact(claim="Volvo has 5 service centres", source_id=1)],
        [],
    )
    assert "5 service centres" in result.what_is_true
    assert "roadside assistance" in result.how_to_frame_it
    assert "opening date" in result.what_not_to_claim


def test_generate_falls_back_to_raw_text_on_unparseable_response() -> None:
    llm = _llm("a response with no section headers at all")
    result = generate_response(llm, "objection", [], [])
    assert result.what_is_true == ""
    assert result.raw_text == "a response with no section headers at all"


def test_generate_prompt_includes_facts_and_chunks_with_citations() -> None:
    fake = _FakeOpenAI(
        chat=_FakeChat(completions=_FakeChatCompletions(to_replay=[_message(WELL_FORMED_RESPONSE)]))
    )
    llm = LLMClient(fake)
    generate_response(
        llm,
        "objection text",
        [RetrievedFact(claim="fact claim", source_id=42)],
        [RetrievedChunk(text="chunk text", document_title="Doc", page=3, source_id=7)],
    )
    messages = fake.chat.completions.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    sent_prompt = messages[1]["content"]
    assert "fact claim" in sent_prompt
    assert "source_id=42" in sent_prompt
    assert "[Doc p3] chunk text" in sent_prompt


def test_abstain_response_has_no_facts_and_a_generic_message() -> None:
    result = abstain_response()
    assert result.what_is_true == ""
    assert result.what_not_to_claim == ""
    assert "product specialist" in result.how_to_frame_it


def test_refuse_response_includes_the_violation_reasons() -> None:
    result = refuse_response(["unsupported_claim: made up figure"])
    assert result.what_is_true == ""
    assert "unsupported_claim: made up figure" in result.how_to_frame_it


def test_refuse_response_handles_no_violations_gracefully() -> None:
    result = refuse_response([])
    assert "unverified claims" in result.how_to_frame_it
