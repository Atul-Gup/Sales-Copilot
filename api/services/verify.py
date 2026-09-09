"""api/services/verify.py — verify_grounding, the LangGraph cycle (T4.4).

Per docs/RETRIEVAL.md's "single generation path" decision, there is no
templated SPEC branch protecting numeric fidelity at generation time anymore
— every intent class free-generates via `api/services/generate.py`. That
moved numeric-fidelity risk from generation-time prevention to
verification-time detection, and this module is where it's caught:

1. Every citation marker (`[n]`) a claim uses must exist in the chunks that
   were actually offered to the model.
2. Every number/unit stated in a claim must appear in the text of the
   chunk(s) *that claim cites* — not just somewhere in the whole retrieved
   set. This is deliberately stricter than evals/metrics.py's
   `numeric_fidelity_rate` heuristic: T4.3's real finding (see docs/TASKS.md)
   was a claim about the BMW X3 citing a chunk marker while stating a number
   that only exists in the EX30's chunk — "the number appears somewhere in
   retrieved text" missed that entirely; checking it against the specific
   chunk cited catches it.

`generate → verify → (regenerate once | refuse)` is a genuine cycle with a
counter, which is the actual justification for using LangGraph here rather
than a plain function call — see docs/RETRIEVAL.md's "This whole path is
built as a LangGraph cycle" note.

The `verify` node also runs `api/guardrails/output.py::run_output_guardrails`
(T5.3) over the same generated text, in the same pass — docs/ARCHITECTURE.md:
"a violation triggers one regeneration attempt, then refusal" is exactly the
loop already built here for numeric grounding, so output guardrail
violations (uncited competitor claims, disparagement, service overstatement,
price/promise/certainty violations) are folded into the same
`violations` list and go through the same regenerate-once-then-refuse cycle
rather than a second, separate loop.

`extract_claims`/`Claim` (T7.7) give `POST /chat` a structured citation per
claim (which chunk, which document/section) instead of a flat citation list
scoped to the whole response — built from this module's own marker parsing,
not a second extraction step over the response text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from api.guardrails.output import run_output_guardrails
from api.llm.client import LLMClient
from api.models import Chunk
from api.services.generate import GenerationResult, generate
from api.services.router import QueryType

# 1 initial generation + 1 regeneration on violation, then refuse.
MAX_ATTEMPTS = 2

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")
_TOKEN_RE = re.compile(r"[\w.,]+")
_PURE_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")

REFUSAL_TEXT = (
    "I can't verify this against the sourced documents closely enough to hand it to "
    "you — the numbers in my draft answer didn't match what's actually in the cited "
    "material, even after a second attempt. Rather than guess, I'm flagging the gap: "
    "please check the source document directly for this one."
)


_UNIT_SUFFIX_RE = re.compile(r"^(\d[\d,]*\.?\d*)[A-Za-z]+$")


def _extract_numbers(text: str) -> set[str]:
    """Digit runs at the start of a token, so a model name like "XC60"
    doesn't contribute a spurious "60" (it starts with a letter), but a
    unit glued straight onto a figure with no space — source text spells it
    "48V", the model naturally writes "48 V" — still counts as the same
    number. Real bug found via live testing: "48V" in a chunk and "48 V" in
    the generated answer are the same fact, but a whole-token-only match
    treated them as different, causing a false grounding-violation refusal
    on an otherwise fully correct answer. Mirrors evals/metrics.py::
    _extract_numbers's heuristic, duplicated rather than imported: api/
    must not depend on evals/, which already depends on api/ the other
    way around."""
    numbers = set()
    for token in _TOKEN_RE.findall(text):
        cleaned = token.strip(".,")
        if not cleaned:
            continue
        if _PURE_NUMBER_RE.fullmatch(cleaned):
            numbers.add(cleaned.replace(",", ""))
            continue
        unit_match = _UNIT_SUFFIX_RE.match(cleaned)
        if unit_match:
            numbers.add(unit_match.group(1).replace(",", ""))
    return numbers


def _split_claims(text: str) -> list[str]:
    """Sentence-level split — coarser than clause-level, but good enough
    granularity for "which citation(s) does this claim rely on"."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


@dataclass(frozen=True)
class GroundingViolation:
    claim: str
    reason: str


@dataclass(frozen=True)
class Claim:
    """One customer-facing claim and the specific chunk it cites — the
    structured shape `POST /chat` needs for T7.7's citation UI.

    Built by `extract_claims` from the exact same per-sentence/per-marker
    parsing `find_grounding_violations` already does (`_split_claims`,
    `_CITATION_MARKER_RE`, `citations_by_marker`) — not a second, separate
    extraction pass over the response text. A fabricated marker (cited but
    not actually offered to the model) is silently skipped here rather than
    surfaced as a claim; `find_grounding_violations` is what catches and
    reports that case, and a fabricated marker never reaches `accept` in the
    verify_grounding loop below, so it can't appear in a `Claim` that ships
    to the frontend.
    """

    text_span: str
    chunk_id: int
    source: str


def extract_claims(result: GenerationResult) -> list[Claim]:
    citations_by_marker = {c.marker: c for c in result.citations}
    claims: list[Claim] = []
    for claim_text in _split_claims(result.text):
        for marker in (int(m) for m in _CITATION_MARKER_RE.findall(claim_text)):
            citation = citations_by_marker.get(marker)
            if citation is None:
                continue
            source = citation.model_label or "source document"
            if citation.section:
                source = f"{source} — {citation.section}"
            claims.append(Claim(text_span=claim_text, chunk_id=citation.chunk_id, source=source))
    return claims


def _output_guardrail_violations(
    result: GenerationResult, known_service_cities: frozenset[str] | None
) -> list[GroundingViolation]:
    """Wraps `run_output_guardrails`'s findings as `GroundingViolation`s so
    they flow through the same regenerate-once-then-refuse loop as a
    numeric-grounding failure — see the module docstring."""
    return [
        GroundingViolation(claim=result.text, reason=f"{v.rule_id}: {v.message}")
        for v in run_output_guardrails(result.text, known_service_cities=known_service_cities)
    ]


def find_grounding_violations(result: GenerationResult) -> list[GroundingViolation]:
    """Every numeric claim must cite a real chunk marker, and its numbers
    must actually appear in that marker's chunk text. A claim with no
    numbers in it is not checked here — non-numeric claim-to-source overlap
    is `api/guardrails/output.py::check_uncited_claim`'s job, not this
    module's; this module is specifically the numeric-fidelity strengthening
    docs/RETRIEVAL.md calls for.

    A single-source answer (one chunk backing the whole paragraph) is, in
    live practice, reliably written with one trailing marker at the end of
    the last sentence rather than one per sentence — confirmed via testing
    every objection-guide item, where this was the majority shape for
    SPEC/OBJECTION answers. Requiring a marker on every individual sentence
    made that the normal, correct case refuse. So an unmarked numeric claim
    is allowed to borrow the *next* claim's marker(s) if that next claim
    carries any — its numbers still have to actually appear in that cited
    chunk's text, so a wrong-chunk attribution (the real T4.3 failure mode)
    is still caught; only the requirement that the marker sit on the exact
    same sentence is relaxed.
    """
    citations_by_marker = {c.marker: c for c in result.citations}
    claims = _split_claims(result.text)
    parsed = [(claim, [int(m) for m in _CITATION_MARKER_RE.findall(claim)]) for claim in claims]
    violations = []
    for index, (claim, markers) in enumerate(parsed):
        claim_numbers = _extract_numbers(_CITATION_MARKER_RE.sub("", claim))
        if not claim_numbers:
            continue

        if not markers:
            # Borrow the next sentence's marker(s), if any — see docstring.
            for _, next_markers in parsed[index + 1 :]:
                if next_markers:
                    markers = next_markers
                    break
            if not markers:
                violations.append(
                    GroundingViolation(claim, "numeric claim with no citation marker")
                )
                continue

        cited_numbers: set[str] = set()
        fabricated_markers = [m for m in markers if m not in citations_by_marker]
        if fabricated_markers:
            violations.append(
                GroundingViolation(
                    claim, f"cites marker(s) {fabricated_markers} not offered to the model"
                )
            )
            continue

        for marker in markers:
            cited_numbers |= _extract_numbers(citations_by_marker[marker].text)

        missing = sorted(claim_numbers - cited_numbers)
        if missing:
            violations.append(
                GroundingViolation(
                    claim, f"number(s) {missing} not found in cited chunk(s) {markers}"
                )
            )
    return violations


def _build_retry_feedback(
    violations: list[GroundingViolation], result: GenerationResult | None
) -> str | None:
    """Turn attempt 1's violations into retry guidance. For a wrong-chunk
    number mismatch, name which marker actually has the number instead of
    just naming what was wrong — a real failure mode found via live
    testing: telling the model only "number X not found in chunk [2]" made
    it retry by dropping the sentence into chunk [2] anyway (now attached
    to the wrong marker in a *different* way) rather than moving it to the
    chunk that actually has it. Every citation is one of the chunks that
    was already offered to the model, so pointing at marker [6] instead of
    [2] isn't handing it new information, just narrowing its own search.
    """
    if not violations:
        return None
    if result is None:
        return "; ".join(v.reason for v in violations)

    parts = []
    for v in violations:
        match = re.search(r"number\(s\) \[(.*?)\] not found in cited chunk", v.reason)
        if match is None:
            parts.append(v.reason)
            continue
        missing = {n.strip(" '") for n in match.group(1).split(",")}
        correct_markers = [
            c.marker for c in result.citations if missing <= _extract_numbers(c.text)
        ]
        if correct_markers:
            parts.append(f"{v.reason} — use marker {correct_markers} for these numbers instead")
        else:
            parts.append(v.reason)
    return "; ".join(parts)


class _VerifyGroundingState(TypedDict):
    query: str
    chunks: list[Chunk]
    intent: QueryType
    llm: LLMClient
    model: str
    model_labels: dict[int, str] | None
    known_service_cities: frozenset[str] | None
    attempt: int
    result: GenerationResult | None
    violations: list[GroundingViolation]
    final_text: str
    refused: bool


def _generate_node(state: _VerifyGroundingState) -> dict[str, Any]:
    # On a retry, hand back the first attempt's own violations as feedback —
    # with temperature=0.0 (generate.py) a blind retry reproduces the exact
    # same text and violation every time, so the regenerate-once step is a
    # no-op without this.
    retry_feedback = _build_retry_feedback(state["violations"], state["result"])
    result = generate(
        state["query"],
        state["chunks"],
        intent=state["intent"],
        llm=state["llm"],
        model=state["model"],
        model_labels=state["model_labels"],
        retry_feedback=retry_feedback,
    )
    return {"result": result, "attempt": state["attempt"] + 1}


def _verify_node(state: _VerifyGroundingState) -> dict[str, Any]:
    result = state["result"]
    assert result is not None  # generate always runs before verify
    violations = find_grounding_violations(result) + _output_guardrail_violations(
        result, state["known_service_cities"]
    )
    return {"violations": violations}


def _route_after_verify(state: _VerifyGroundingState) -> str:
    if not state["violations"]:
        return "accept"
    if state["attempt"] < MAX_ATTEMPTS:
        return "regenerate"
    return "refuse"


def _accept_node(state: _VerifyGroundingState) -> dict[str, Any]:
    result = state["result"]
    assert result is not None
    return {"final_text": result.text, "refused": False}


def _refuse_node(_state: _VerifyGroundingState) -> dict[str, Any]:
    return {"final_text": REFUSAL_TEXT, "refused": True}


def _build_graph() -> Any:
    # `_VerifyGroundingState` doesn't satisfy langgraph's `StateT` bound
    # cleanly in mypy's eyes (a typing gap in the library, not a real
    # mismatch — it's a plain TypedDict, exactly what StateGraph expects at
    # runtime), so this is built and used as `Any` rather than fighting the
    # generic.
    graph: Any = StateGraph(_VerifyGroundingState)
    graph.add_node("generate", _generate_node)
    graph.add_node("verify", _verify_node)
    graph.add_node("accept", _accept_node)
    graph.add_node("refuse", _refuse_node)

    graph.add_edge(START, "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges(
        "verify",
        _route_after_verify,
        {"accept": "accept", "regenerate": "generate", "refuse": "refuse"},
    )
    graph.add_edge("accept", END)
    graph.add_edge("refuse", END)
    return graph.compile()


@dataclass(frozen=True)
class VerifiedGenerationResult:
    text: str
    refused: bool
    attempts: int
    violations: list[GroundingViolation] = field(default_factory=list)
    generation: GenerationResult | None = None
    claims: list[Claim] = field(default_factory=list)


def generate_with_verification(
    query: str,
    chunks: list[Chunk],
    *,
    intent: QueryType,
    llm: LLMClient,
    model: str = "gpt-4o-mini",
    model_labels: dict[int, str] | None = None,
    known_service_cities: frozenset[str] | None = None,
) -> VerifiedGenerationResult:
    """Run `generate()` through the verify_grounding loop: accept on a clean
    pass, regenerate once on a violation (numeric-grounding OR output
    guardrail), refuse on a second failure.

    `model_labels` is passed straight through to `generate()` — see its
    docstring; it's what lets a comparison prompt tell two similarly-shaped
    chunks apart by the model they actually belong to.

    `known_service_cities` is passed straight through to
    `check_service_overstatement` (T5.3) — omit it to skip that specific
    city-level check while still running every other output guardrail.
    """
    graph = _build_graph()
    final_state = graph.invoke(
        {
            "query": query,
            "chunks": chunks,
            "intent": intent,
            "llm": llm,
            "model": model,
            "model_labels": model_labels,
            "known_service_cities": known_service_cities,
            "attempt": 0,
            "result": None,
            "violations": [],
            "final_text": "",
            "refused": False,
        }
    )
    result = final_state["result"]
    refused = final_state["refused"]
    # Claims are only meaningful for an accepted response — a refused one
    # has no verified text to attach a citation to.
    claims = extract_claims(result) if not refused and result is not None else []
    return VerifiedGenerationResult(
        text=final_state["final_text"],
        refused=refused,
        attempts=final_state["attempt"],
        violations=final_state["violations"],
        generation=result,
        claims=claims,
    )
