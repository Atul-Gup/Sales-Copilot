"""api/objection/generate.py — generate and abstain nodes (T4.3).

`generate_response` drafts the three-block response docs/RETRIEVAL.md
specifies (what's true / how to frame it / what not to claim) from whatever
`retrieve` found. It does not verify its own output — that's T4.4's
`verify_grounding`, a separate cyclic node layered on top of this graph.
`LLMError` is allowed to propagate; T4.4's graph is where a failed generate
call gets a defined outcome (retry once, then refuse).
"""

from __future__ import annotations

import re

from api.llm.client import LLMClient, Message
from api.objection.state import GeneratedResponse, RetrievedChunk, RetrievedFact

GENERATE_MODEL = "gpt-4o"
CHUNK_SNIPPET_CHARS = 400

GENERATE_SYSTEM_PROMPT = (
    "You help a Volvo sales consultant respond to a customer objection. "
    "Using ONLY the facts and document excerpts given below, write a response "
    "in exactly three labelled sections, in this order:\n\n"
    "WHAT'S TRUE: the facts relevant to this objection, stated plainly.\n"
    "HOW TO FRAME IT: how the consultant should present those facts to the "
    "customer.\n"
    "WHAT NOT TO CLAIM: specific claims that would go beyond what the given "
    "facts and documents actually support.\n\n"
    "Never state a number, comparison, or claim that isn't backed by the "
    "given facts or document excerpts. If nothing relevant was retrieved, say "
    "so plainly in WHAT'S TRUE rather than inventing something."
)

_SECTION_RE = re.compile(
    r"WHAT'S TRUE:(?P<true>.*?)HOW TO FRAME IT:(?P<frame>.*?)WHAT NOT TO CLAIM:(?P<not_claim>.*)",
    re.DOTALL | re.IGNORECASE,
)

_ABSTAIN_TEXT = (
    "This objection doesn't map clearly to a specific, sourced area — please "
    "loop in a product specialist rather than guessing. Avoid stating any "
    "figure or comparison until it's clear exactly which model, spec, or "
    "document is being asked about."
)


def _build_user_prompt(
    objection_text: str, facts: list[RetrievedFact], chunks: list[RetrievedChunk]
) -> str:
    lines = [f"Customer objection: {objection_text}", "", "Facts:"]
    if facts:
        lines.extend(f"- {fact.claim} (source_id={fact.source_id})" for fact in facts)
    else:
        lines.append("- none retrieved")
    lines.append("")
    lines.append("Document excerpts:")
    if chunks:
        for chunk in chunks:
            snippet = chunk.text[:CHUNK_SNIPPET_CHARS].replace("\n", " ")
            lines.append(f"- [{chunk.document_title} p{chunk.page}] {snippet}")
    else:
        lines.append("- none retrieved")
    return "\n".join(lines)


def parse_generated_response(raw_text: str) -> GeneratedResponse:
    """Split the model's raw completion into the three labelled sections.
    Shared by `generate_response` (T4.3) and the streaming path
    (`api/objection/stream.py`, T6.3), which accumulates the same raw text
    from a token stream instead of a single `complete()` call and parses it
    identically once the stream ends.
    """
    match = _SECTION_RE.search(raw_text)
    if match is None:
        return GeneratedResponse(
            what_is_true="", how_to_frame_it="", what_not_to_claim="", raw_text=raw_text
        )
    return GeneratedResponse(
        what_is_true=match.group("true").strip(),
        how_to_frame_it=match.group("frame").strip(),
        what_not_to_claim=match.group("not_claim").strip(),
        raw_text=raw_text,
    )


def build_generate_prompt(
    objection_text: str, facts: list[RetrievedFact], chunks: list[RetrievedChunk]
) -> str:
    """Public alias of `_build_user_prompt` — the streaming path (T6.3) needs
    to build the exact same prompt to call `LLMClient.stream` with.
    """
    return _build_user_prompt(objection_text, facts, chunks)


def generate_response(
    llm: LLMClient,
    objection_text: str,
    facts: list[RetrievedFact],
    chunks: list[RetrievedChunk],
) -> GeneratedResponse:
    prompt = _build_user_prompt(objection_text, facts, chunks)
    completion = llm.complete(
        [Message(role="user", content=prompt)],
        model=GENERATE_MODEL,
        max_tokens=600,
        system=GENERATE_SYSTEM_PROMPT,
    )
    return parse_generated_response(completion.text)


def abstain_response() -> GeneratedResponse:
    return GeneratedResponse(
        what_is_true="",
        how_to_frame_it=_ABSTAIN_TEXT,
        what_not_to_claim="",
        raw_text=_ABSTAIN_TEXT,
    )


def refuse_response(violations: list[str]) -> GeneratedResponse:
    """T4.4: reached only after one failed regeneration attempt — the
    generated response still had unverified claims or missed a required
    concession. Refusing rather than shipping an unsupported claim is the
    whole point of the verify_grounding loop (docs/RETRIEVAL.md).
    """
    reason = "; ".join(violations) if violations else "unverified claims"
    text = (
        "I can't confidently answer this without risking an unsupported claim "
        f"({reason}). Please loop in a product specialist rather than repeating "
        "this response to the customer."
    )
    return GeneratedResponse(
        what_is_true="", how_to_frame_it=text, what_not_to_claim="", raw_text=text
    )
