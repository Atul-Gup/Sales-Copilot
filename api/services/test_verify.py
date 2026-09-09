from api.llm.client import CompletionResult, Message
from api.models import Chunk
from api.services.generate import Citation, GenerationResult
from api.services.router import QueryType
from api.services.verify import (
    MAX_ATTEMPTS,
    REFUSAL_TEXT,
    Claim,
    extract_claims,
    find_grounding_violations,
    generate_with_verification,
)


def _chunk(id_: int, text: str) -> Chunk:
    return Chunk(id=id_, source_id=1, document_id=1, text=text, embedding=[0.0], section=None)


def _result(text: str, citations: list[Citation]) -> GenerationResult:
    return GenerationResult(
        text=text,
        intent=QueryType.SPEC,
        citations=citations,
        model="gpt-4o-mini",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1.0,
    )


class _ScriptedLLMClient:
    """Returns a different canned completion on each call, in order —
    lets a test simulate "the model got it wrong once, then right"."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
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
        text = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        return CompletionResult(
            text=text,
            model=model,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
            latency_ms=1.0,
            retries=0,
        )


def test_find_grounding_violations_accepts_a_correctly_cited_number() -> None:
    citations = [Citation(marker=1, chunk_id=1, section=None, text="Boot space is 709 litres.")]
    result = _result("Boot space is 709 litres [1].", citations)
    assert find_grounding_violations(result) == []


def test_find_grounding_violations_flags_a_number_not_in_the_cited_chunk() -> None:
    # T4.3's real finding, reproduced directly: the claim cites [1] but the
    # number it states only lives in a different chunk (here, not offered
    # at all as [1]'s content).
    citations = [
        Citation(marker=1, chunk_id=1, section=None, text="The X3 has 750 W output."),
    ]
    result = _result("The X3 has 1,040 W output [1].", citations)
    violations = find_grounding_violations(result)
    assert len(violations) == 1
    assert "1040" in violations[0].reason


def test_find_grounding_violations_flags_a_numeric_claim_with_no_citation() -> None:
    result = _result("The XC60 has 709 litres of boot space.", [])
    violations = find_grounding_violations(result)
    assert len(violations) == 1
    assert "no citation marker" in violations[0].reason


def test_find_grounding_violations_flags_a_fabricated_marker() -> None:
    result = _result("The XC60 has 709 litres [3].", [])
    violations = find_grounding_violations(result)
    assert len(violations) == 1
    assert "not offered" in violations[0].reason


def test_find_grounding_violations_ignores_non_numeric_claims() -> None:
    citations = [Citation(marker=1, chunk_id=1, section=None, text="Available in five colours.")]
    result = _result("Several exterior colours are available [1].", citations)
    assert find_grounding_violations(result) == []


def test_extract_claims_pairs_each_cited_sentence_with_its_chunk_and_source() -> None:
    citations = [
        Citation(
            marker=1,
            chunk_id=42,
            section="Dimensions",
            text="Boot space is 709 litres.",
            model_label="Volvo XC60",
        )
    ]
    result = _result("Boot space is 709 litres [1].", citations)
    claims = extract_claims(result)
    assert claims == [
        Claim(
            text_span="Boot space is 709 litres [1].",
            chunk_id=42,
            source="Volvo XC60 — Dimensions",
        )
    ]


def test_extract_claims_falls_back_to_a_generic_source_label() -> None:
    # No model_label (chunk's document couldn't be resolved) and no section
    # — still produces a claim, just with a plain fallback source string
    # rather than failing or omitting it.
    citations = [Citation(marker=1, chunk_id=7, section=None, text="Available in five colours.")]
    result = _result("Several exterior colours are available [1].", citations)
    claims = extract_claims(result)
    assert len(claims) == 1
    assert claims[0].chunk_id == 7
    assert claims[0].source == "source document"


def test_extract_claims_splits_one_sentence_citing_two_markers_into_two_claims() -> None:
    citations = [
        Citation(marker=1, chunk_id=1, section="Powertrain", text="343 Nm."),
        Citation(marker=2, chunk_id=2, section="Powertrain", text="343 Nm confirmed."),
    ]
    result = _result("Torque is 343 Nm [1][2].", citations)
    claims = extract_claims(result)
    assert [c.chunk_id for c in claims] == [1, 2]
    assert all(c.text_span == "Torque is 343 Nm [1][2]." for c in claims)


def test_extract_claims_skips_a_fabricated_marker_not_offered_to_the_model() -> None:
    # find_grounding_violations already flags this case as a violation
    # (test_find_grounding_violations_flags_a_fabricated_marker above) — a
    # response with a fabricated marker never reaches accept, so this just
    # confirms extract_claims itself doesn't crash or invent a claim for it.
    result = _result("The XC60 has 709 litres [3].", [])
    assert extract_claims(result) == []


def test_extract_claims_ignores_claims_with_no_citation_marker_at_all() -> None:
    citations = [Citation(marker=1, chunk_id=1, section=None, text="709 litres.")]
    result = _result("Boot space is 709 litres [1]. This is a spacious SUV overall.", citations)
    claims = extract_claims(result)
    assert len(claims) == 1
    assert claims[0].text_span == "Boot space is 709 litres [1]."


def test_generate_with_verification_accepts_a_clean_first_attempt() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    llm = _ScriptedLLMClient(["Boot space is 709 litres [1]."])

    outcome = generate_with_verification(
        "boot space?",
        chunks,
        intent=QueryType.SPEC,
        llm=llm,  # type: ignore[arg-type]
    )

    assert outcome.refused is False
    assert outcome.attempts == 1
    assert outcome.violations == []
    assert outcome.text == "Boot space is 709 litres [1]."
    assert llm.calls == 1


def test_generate_with_verification_regenerates_once_then_accepts() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    llm = _ScriptedLLMClient(
        [
            "Boot space is 750 litres [1].",  # wrong number, first attempt
            "Boot space is 709 litres [1].",
        ]  # corrected on regeneration
    )

    outcome = generate_with_verification(
        "boot space?",
        chunks,
        intent=QueryType.SPEC,
        llm=llm,  # type: ignore[arg-type]
    )

    assert outcome.refused is False
    assert outcome.attempts == 2
    assert outcome.text == "Boot space is 709 litres [1]."
    assert llm.calls == 2


def test_generate_with_verification_regenerates_on_an_output_guardrail_violation() -> None:
    # No citation markers at all here, so find_grounding_violations has
    # nothing numeric to flag — this violation can only be caught by
    # run_output_guardrails (T5.3) folded into the same verify node
    # (here: check_disparagement, "feels cheap" on the first attempt).
    chunks = [_chunk(1, "The BMW X3 has a comparable infotainment system to the XC60.")]
    llm = _ScriptedLLMClient(
        [
            "The BMW X3's infotainment feels cheap compared to the XC60's.",
            "Both systems offer comparable infotainment features.",
        ]
    )

    outcome = generate_with_verification(
        "how does the X3 compare?",
        chunks,
        intent=QueryType.COMPARISON,
        llm=llm,  # type: ignore[arg-type]
    )

    assert outcome.refused is False
    assert outcome.attempts == 2
    assert outcome.text == "Both systems offer comparable infotainment features."
    assert llm.calls == 2


def test_generate_with_verification_refuses_on_a_persistent_output_guardrail_violation() -> None:
    chunks = [_chunk(1, "The BMW X3 has a comparable infotainment system to the XC60.")]
    llm = _ScriptedLLMClient(["The BMW X3's infotainment feels cheap."])  # always disparaging

    outcome = generate_with_verification(
        "how does the X3 compare?",
        chunks,
        intent=QueryType.COMPARISON,
        llm=llm,  # type: ignore[arg-type]
    )

    assert outcome.refused is True
    assert outcome.text == REFUSAL_TEXT
    assert any("disparagement" in v.reason for v in outcome.violations)


def test_generate_with_verification_refuses_after_max_attempts() -> None:
    chunks = [_chunk(1, "Boot space is 709 litres.")]
    llm = _ScriptedLLMClient(["Boot space is 750 litres [1]."])  # always wrong

    outcome = generate_with_verification(
        "boot space?",
        chunks,
        intent=QueryType.SPEC,
        llm=llm,  # type: ignore[arg-type]
    )

    assert outcome.refused is True
    assert outcome.text == REFUSAL_TEXT
    assert outcome.attempts == MAX_ATTEMPTS
    assert llm.calls == MAX_ATTEMPTS
    assert len(outcome.violations) == 1
