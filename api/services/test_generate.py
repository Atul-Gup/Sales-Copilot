from api.llm.client import CompletionResult, Message
from api.models import Chunk
from api.services.generate import generate
from api.services.router import QueryType


class _FakeLLMClient:
    """Records the exact prompt it was called with, and returns a canned
    completion — no real OpenAI call, no network."""

    def __init__(self, text: str = "Canned answer [1].") -> None:
        self._text = text
        self.last_messages: list[Message] | None = None
        self.last_system: str | None = None
        self.last_model: str | None = None
        self.last_max_tokens: int | None = None
        self.calls = 0

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        self.calls += 1
        self.last_messages = list(messages)
        self.last_system = system
        self.last_model = model
        self.last_max_tokens = max_tokens
        return CompletionResult(
            text=self._text,
            model=model,
            input_tokens=42,
            output_tokens=7,
            cost_usd=0.0001,
            latency_ms=12.5,
            retries=0,
        )


def _chunk(
    id_: int, text: str, section: str | None = "3. Dimensions", document_id: int = 1
) -> Chunk:
    return Chunk(
        id=id_, source_id=1, document_id=document_id, text=text, embedding=[0.0], section=section
    )


def test_generate_always_calls_the_llm_for_every_intent() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    for intent in QueryType:
        llm = _FakeLLMClient()
        result = generate("boot space?", chunks, intent=intent, llm=llm)  # type: ignore[arg-type]
        assert llm.calls == 1
        assert result.intent == intent
        assert result.text == "Canned answer [1]."


def test_generate_includes_every_chunk_as_a_numbered_citation() -> None:
    chunks = [
        _chunk(1, "Boot space is 709 litres.", section="Dimensions"),
        _chunk(2, "Available in five colours.", section=None),
    ]
    llm = _FakeLLMClient()
    result = generate("boot space?", chunks, intent=QueryType.SPEC, llm=llm)  # type: ignore[arg-type]

    assert [c.marker for c in result.citations] == [1, 2]
    assert [c.chunk_id for c in result.citations] == [1, 2]
    assert result.citations[0].section == "Dimensions"
    assert result.citations[1].section is None
    assert result.citations[1].text == "Available in five colours."


def test_generate_labels_each_chunk_with_its_model_when_given_model_labels() -> None:
    # Real bug: two models' dimension chunks look identical in shape (a
    # generic "3. Dimensions & Capacity" table with no model name inside
    # it), which caused a real wheelbase figure to be attributed to the
    # wrong model. model_labels lets the prompt say which model each chunk
    # is actually about.
    chunks = [
        _chunk(1, "Wheelbase: 2,865 mm.", document_id=10),
        _chunk(2, "Wheelbase: 2,827 mm.", document_id=20),
    ]
    llm = _FakeLLMClient()
    generate(
        "wheelbase?",
        chunks,
        intent=QueryType.COMPARISON,
        llm=llm,  # type: ignore[arg-type]
        model_labels={10: "Volvo XC60", 20: "Audi Q5"},
    )

    assert llm.last_messages is not None
    prompt = llm.last_messages[0].content
    assert "[1] (Volvo XC60)" in prompt
    assert "[2] (Audi Q5)" in prompt


def test_generate_citations_carry_the_model_label() -> None:
    chunks = [_chunk(1, "Wheelbase: 2,865 mm.", document_id=10)]
    llm = _FakeLLMClient()
    result = generate(
        "wheelbase?",
        chunks,
        intent=QueryType.SPEC,
        llm=llm,  # type: ignore[arg-type]
        model_labels={10: "Volvo XC60"},
    )
    assert result.citations[0].model_label == "Volvo XC60"


def test_generate_omits_the_label_prefix_when_no_model_labels_are_given() -> None:
    chunks = [_chunk(1, "Wheelbase: 2,865 mm.", section=None)]
    llm = _FakeLLMClient()
    generate("wheelbase?", chunks, intent=QueryType.SPEC, llm=llm)  # type: ignore[arg-type]

    assert llm.last_messages is not None
    prompt = llm.last_messages[0].content
    assert "[1] Wheelbase" in prompt


def test_generate_puts_every_chunk_text_in_the_prompt_sent_to_the_llm() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres."), _chunk(2, "Ground clearance is 216mm.")]
    llm = _FakeLLMClient()
    generate("specs?", chunks, intent=QueryType.SPEC, llm=llm)  # type: ignore[arg-type]

    assert llm.last_messages is not None
    user_content = llm.last_messages[0].content
    assert "[1]" in user_content
    assert "Boot space is 709 litres." in user_content
    assert "[2]" in user_content
    assert "Ground clearance is 216mm." in user_content
    assert "specs?" in user_content


def test_generate_varies_the_system_prompt_by_intent() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    systems = {}
    for intent in QueryType:
        llm = _FakeLLMClient()
        generate("q", chunks, intent=intent, llm=llm)  # type: ignore[arg-type]
        systems[intent] = llm.last_system

    assert len({v for v in systems.values()}) == len(QueryType)
    objection_system = systems[QueryType.OBJECTION]
    comparison_system = systems[QueryType.COMPARISON]
    assert objection_system is not None and "objection" in objection_system.lower()
    assert comparison_system is not None and "compar" in comparison_system.lower()


def test_generate_returns_no_citations_for_an_empty_chunk_list() -> None:
    llm = _FakeLLMClient()
    result = generate("anything", [], intent=QueryType.SPEC, llm=llm)  # type: ignore[arg-type]
    assert result.citations == []
    assert llm.calls == 1


def test_generate_passes_through_llm_client_metadata() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    llm = _FakeLLMClient()
    result = generate("boot space?", chunks, intent=QueryType.SPEC, llm=llm, model="gpt-4o-mini")  # type: ignore[arg-type]

    assert result.model == "gpt-4o-mini"
    assert result.input_tokens == 42
    assert result.output_tokens == 7
    assert result.cost_usd == 0.0001
    assert result.latency_ms == 12.5
