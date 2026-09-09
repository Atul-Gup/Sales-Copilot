"""api/services/generate.py — the single generation path (T4.2).

Per docs/RETRIEVAL.md's "single generation path" decision: every intent class
(SPEC, COMPARISON, OBJECTION) generates its response via the LLM over the
retrieved chunks. There is no templated branch for SPEC — an earlier draft
templated spec lookups to protect numeric fidelity at generation time, but
that produced an inconsistent voice across a single chat interface, and
numeric fidelity is now a verification-time concern (T4.4's `verify_grounding`
node), not a generation-time one.

`classify()` (api/services/router.py) only selects which prompt this module
uses — it never skips retrieval and never decides *whether* generation
happens. All three intent classes call `LLMClient.complete()` exactly once.

Grounding is not verified here. This module hands its result to whatever
calls it (T4.4's `verify_grounding` node, once it exists) for the
regenerate-once-then-refuse loop; today it's a straight pass-through of
whatever the model produced from the given chunks.
"""

from __future__ import annotations

from dataclasses import dataclass

from api.llm.client import LLMClient, Message
from api.models import Chunk
from api.services.router import QueryType

_MAX_TOKENS = 600

_SHARED_RULES = """You are a product-knowledge assistant for Volvo Cars India sales \
consultants. You brief the consultant — but write every sentence as something the consultant \
could say to the customer word for word, standing right there in the showroom. Never write \
like a system describing its own inputs.

Rules:
- Answer only from the SOURCE CHUNKS below. Never use outside knowledge, even if you are \
confident it's correct.
- Never use the words "chunk", "context", "corpus", "the retrieved passages", or any other \
description of how you found the information. Never say things like "the chunks don't \
provide...", "based on the context...", or "the provided information doesn't state...". Say \
instead what a knowledgeable person would actually say out loud: "That's not listed in the \
XC60 brochure," "Volvo doesn't publish a figure for that," "I don't have a number for that one." \
The consultant should be able to repeat your sentence to a customer without editing it first.
- Every factual claim must still be traceable to a specific chunk, for internal verification — \
reference chunks inline with their bracketed number, e.g. "[1]" — including a claim that says a \
value isn't stated anywhere: cite the chunk you checked and found it missing from, never state a \
value or its absence with no marker at all. These markers are for verification, not something \
the consultant reads aloud — they sit at the end of the sentence, not inside it.
- If your answer has more than one sentence, EVERY sentence that states a number, figure, \
spec, or feature drawn from a chunk needs its own marker at its own end — never one marker \
saved for the end of the whole answer. A closing sentence with no number in it (a takeaway, a \
summary) needs no marker of its own, but every sentence before it that does state a number does.
- A response with zero "[n]" markers anywhere in it is always wrong and will be rejected, no \
matter how short or simple the answer is — even a one-sentence answer needs its marker.
- If a single sentence combines numbers that come from two different chunks (e.g. the engine \
size from one chunk's overview line and the power/torque from another chunk's spec table), end \
that sentence with every marker it draws from, back to back, e.g. "...370 Nm [2][6]" — not just \
the last chunk you happened to use. A marker only covers numbers that literally appear in that \
chunk's own text; leaving one out for a number it doesn't cover is the same as citing nothing.
- Before writing a number, check whose chunk it actually came from. Multiple models in this \
corpus share similar-looking sections and even identical figures for different specs — copying \
a number into the wrong model's line is a real, seen failure mode. Re-read the chunk's own \
model name in its heading before attributing a figure to any model.
- State numbers and units exactly as they appear in the source chunks. Never round, convert, \
or estimate a figure.
- If the source material doesn't fully answer the question, say plainly, in customer-usable \
language, what isn't documented — rather than filling the gap with a plausible-sounding guess, \
and rather than describing your own retrieval process."""

_INTENT_GUIDANCE: dict[QueryType, str] = {
    QueryType.SPEC: """The consultant is asking a direct factual question. Answer it \
concisely — a short paragraph or a tight list of the relevant figures. No sales framing, \
no comparison to other models unless the chunks themselves draw one.""",
    QueryType.COMPARISON: """The consultant is comparing models. If the question names a \
specific dimension (e.g. boot space, wheelbase, torque), structure the response around that \
dimension, stating each model's figure side by side where the source material supports it. If \
the question is open-ended ("how is X better than Y", "why choose X over Y", "I think X is \
better than Y") rather than naming a dimension, do not open with a line about what you can or \
can't determine or assert — go straight into the dimensions. Pick 2-4 where you actually have \
both models' figures (e.g. dimensions, powertrain, features/audio) and present those, exactly \
as if the consultant had asked about each one. Only say a comparison isn't possible — in plain, \
customer-usable language, never mentioning chunks/context/retrieval — if you genuinely have \
nothing to compare on for either model. Do not declare an overall "winner" — hand the \
consultant the comparative facts and let them make the pitch. Use this exact layout: one line \
per model in the form "<Model>: <figure> <unit> [n]" — the citation marker for that model's own \
chunk goes at the END of every single line, never omitted, even in a short list — then a \
one-sentence takeaway with no number in it that a consultant could say out loud, repeated for \
each dimension you cover. Copy each figure exactly as it appears in its source chunk, character \
for character — do not paraphrase the unit or reformat the number. Every takeaway sentence must \
be neutral: describe what the figures are, not whether the difference is large, small, better, \
or worse.""",
    QueryType.OBJECTION: """The consultant is relaying a customer objection or concern. \
Acknowledge what's true in the objection before responding — do not deflect a valid concern. \
Where the source chunks support a genuine counterpoint, give the consultant that counterpoint. \
Where they don't, say so rather than manufacturing a rebuttal.""",
}


@dataclass(frozen=True)
class Citation:
    marker: int
    chunk_id: int
    section: str | None
    text: str
    model_label: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    """One generation call's output, ready for a grounding check to consume.

    `citations` lists every chunk that was offered to the model as context,
    in the same order as the `[n]` markers used in the prompt — not just the
    chunks the model happened to reference — so a downstream verifier (T4.4)
    can check referenced markers against real chunk text without a second
    retrieval call.
    """

    text: str
    intent: QueryType
    citations: list[Citation]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    latency_ms: float


def _build_context_block(
    chunks: list[Chunk], model_labels: dict[int, str] | None
) -> tuple[str, list[Citation]]:
    lines = []
    citations = []
    labels = model_labels or {}
    for marker, chunk in enumerate(chunks, start=1):
        # document_id is nullable (a chunk with no single owning model,
        # e.g. the objection-handling guide's General items) — there's no
        # label to look up for one, same as an unrecognized id.
        label = labels.get(chunk.document_id) if chunk.document_id is not None else None
        # The model name goes first, ahead of the section — most chunk text
        # is otherwise anonymous (a generic "3. Dimensions & Capacity" table
        # with no model name inside it at all), which is a real, confirmed
        # cause of cross-model mislabeling (a wheelbase figure attributed to
        # the wrong model — see docs/TASKS.md's T7 chat-bug entries).
        prefix = f" ({label})" if label else ""
        section = f" ({chunk.section})" if chunk.section else ""
        lines.append(f"[{marker}]{prefix}{section} {chunk.text}")
        citations.append(
            Citation(
                marker=marker,
                chunk_id=chunk.id,
                section=chunk.section,
                text=chunk.text,
                model_label=label,
            )
        )
    return "\n".join(lines), citations


def generate(
    query: str,
    chunks: list[Chunk],
    *,
    intent: QueryType,
    llm: LLMClient,
    model: str = "gpt-4o-mini",
    model_labels: dict[int, str] | None = None,
    retry_feedback: str | None = None,
) -> GenerationResult:
    """Generate a natural-language response to `query` over `chunks`.

    `chunks` must already be the retrieved, in-corpus set (the caller runs
    the `in_corpus?` gate and `hybrid_search`/`hybrid_search_scored` before
    calling this — this function always generates, it never checks whether
    it should refuse). `intent` selects which of the three prompt styles
    above to use; it never changes whether the LLM is called.

    `model_labels` maps a chunk's `document_id` (i.e. `Model.id`) to a
    display label ("Volvo XC60") so each context line can say which model
    it's actually about — most chunk text is otherwise anonymous (a generic
    numbered section table with no model name inside it), which is a
    confirmed real cause of cross-model mislabeling. Optional and omittable
    (falls back to no label) so callers without a session handy — tests,
    mainly — aren't forced to build this map.

    `retry_feedback`, when set, is appended to the prompt describing exactly
    what verify_grounding's first attempt got wrong. Necessary because
    `temperature=0.0` makes this call deterministic: without feedback, a
    blind second attempt at the same prompt reproduces the same output
    (and the same violation) every time, silently turning the
    regenerate-once step into a no-op. Real bug found via live testing —
    every objection-guide multi-sentence answer that missed a marker on
    attempt 1 refused 100% of the time instead of self-correcting.
    """
    context_block, citations = _build_context_block(chunks, model_labels)
    system = f"{_SHARED_RULES}\n\n{_INTENT_GUIDANCE[intent]}"
    user_content = f"SOURCE CHUNKS:\n{context_block}\n\nQUESTION: {query}"
    if retry_feedback:
        user_content += (
            f"\n\nYour previous answer was rejected for this reason: {retry_feedback}\n"
            "Rewrite the answer from scratch, fixing that specific problem."
        )

    result = llm.complete(
        [Message(role="user", content=user_content)],
        model=model,
        max_tokens=_MAX_TOKENS,
        system=system,
        # Real bug found via live testing: with no temperature set (the API
        # default, ~1.0), the model would sometimes state a correct, fully
        # grounded figure but omit its `[n]` marker — a pure formatting
        # miss, not a factual one — which verify_grounding (correctly)
        # treats as an uncited claim and refuses after a second failure.
        # Same query, asked twice, could get a citation once and a false
        # refusal once. There's no benefit to stylistic variety here — the
        # shared rules already mandate copying figures verbatim — so a low
        # temperature trades away creativity this task never needed for
        # much more reliable format compliance.
        temperature=0.0,
    )

    return GenerationResult(
        text=result.text,
        intent=intent,
        citations=citations,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        latency_ms=result.latency_ms,
    )
