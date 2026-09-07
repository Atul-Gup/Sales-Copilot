"""api/objection/stream.py — streaming variant of the objection path (T6.3).

docs/TASKS.md T6.3: "Stream objection responses. First token is what
matters when someone is standing there." Streaming and T4.4's
generate -> verify_grounding -> regenerate-once-then-refuse cycle
(`api/objection/graph.py`) are in real tension: verification needs the
complete response text, but the entire point of streaming is showing text
*before* the complete response exists.

This module resolves that tension by narrowing, not ignoring, the
guarantee: `classify` and `retrieve` run as ordinary blocking calls first
(classify is one short LLM call; retrieve is direct SQL / hybrid search,
no LLM at all), since the caller needs the category and abstain outcome
before there's anything worth streaming. The `generate` call is then
streamed token-by-token as it arrives. Once the stream ends, the exact same
`verify_grounding` check the non-streaming graph uses runs against the
accumulated text — but on a violation, this path emits a `refused` event
instead of regenerating. Regenerating would mean discarding everything
already streamed to the caller and starting over, which defeats the reason
to stream in the first place; a caller wanting the full retry-then-refuse
guarantee should use `api/objection/graph.py` instead. Every response is
still guardrail-checked before being called `done` — this trims the retry
attempt, not the safety check itself.

Usage — the caller (an SSE endpoint, `api/routers/objection.py`) iterates
`stream_objection_response` and forwards each event to the client as it's
produced; only a `token` event should be shown incrementally, since a
`refused` event means the response shown so far must be treated as
retracted (the client's job, not this module's — see that router's
docstring for the exact wire format).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from sqlalchemy.orm import Session

from api.llm.client import LLMClient, Message
from api.llm.embeddings import EmbeddingClient
from api.objection.classify import CONFIDENCE_THRESHOLD, classify_objection
from api.objection.generate import (
    GENERATE_MODEL,
    GENERATE_SYSTEM_PROMPT,
    abstain_response,
    build_generate_prompt,
    parse_generated_response,
    refuse_response,
)
from api.objection.retrieve import retrieve_chunks, retrieve_facts
from api.objection.state import GeneratedResponse
from api.objection.verify import verify_grounding

EventType = Literal["category", "token", "done", "refused", "abstained"]


class StreamEvent(TypedDict, total=False):
    type: EventType
    category: str
    confidence: float
    text: str
    response: GeneratedResponse
    violations: list[str]


def stream_objection_response(
    llm: LLMClient,
    embedder: EmbeddingClient,
    session: Session,
    objection_text: str,
    context: dict[str, Any] | None = None,
) -> Iterator[StreamEvent]:
    context = context or {}

    classification = classify_objection(llm, objection_text)
    yield {
        "type": "category",
        "category": classification.category,
        "confidence": classification.confidence,
    }

    if classification.category == "other" or classification.confidence < CONFIDENCE_THRESHOLD:
        yield {"type": "abstained", "response": abstain_response()}
        return

    facts = retrieve_facts(session, classification.category, context)
    chunks = retrieve_chunks(session, embedder, objection_text)

    prompt = build_generate_prompt(objection_text, facts, chunks)
    accumulated = ""
    for text_chunk in llm.stream(
        [Message(role="user", content=prompt)],
        model=GENERATE_MODEL,
        max_tokens=600,
        system=GENERATE_SYSTEM_PROMPT,
    ):
        accumulated += text_chunk
        yield {"type": "token", "text": text_chunk}

    response = parse_generated_response(accumulated)
    violations = verify_grounding(classification.category, facts, chunks, response)
    if violations:
        yield {"type": "refused", "violations": violations, "response": refuse_response(violations)}
        return
    yield {"type": "done", "response": response, "violations": []}
