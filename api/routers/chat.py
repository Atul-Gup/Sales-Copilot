"""api/routers/chat.py — POST /chat, the single generation endpoint (T7.1).

One endpoint for every intent class (SPEC, COMPARISON, OBJECTION) — no
separate `/compare` or `/objection` routes, per docs/TASKS.md's T7.1: "No
separate comparison/objection/spec screens." The frontend sends one query,
gets one response; `api/services/pipeline.py::answer()` is where the intent
classification, retrieval, concession, and generation actually happen.

`get_llm` constructs its `LLMClient` lazily and caches it, rather than at
import time — importing this module (e.g. from a test that never calls
`/chat`) must not require a real `OPENAI_API_KEY` to be set, and a FastAPI
dependency is also what lets tests override it with a fake client via
`app.dependency_overrides`, the same pattern `get_db` already uses.

`GenerationResult.citations` (api/services/generate.py) intentionally lists
every chunk *offered* to the model, in marker order — not just the ones it
ended up using — so T4.4's verify_grounding can check a `[n]` reference
against real chunk text without a second retrieval call. That's the right
shape for verification but the wrong shape for a chat UI: with up to 50
chunks offered per query, rendering all of them made the citation list
dwarf the answer (real user report). This endpoint filters down to only the
markers the response text actually cites before returning — the raw list
stays internal to generation/verification.
"""

from __future__ import annotations

import re
from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_db
from api.llm.client import LLMClient
from api.services.generate import Citation
from api.services.pipeline import answer as pipeline_answer

router = APIRouter()

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


def _referenced_citations(text: str, citations: list[Citation]) -> list[Citation]:
    """Only the chunks the response text actually cites with a `[n]`
    marker, in the order those markers first appear in the text."""
    referenced_markers = [int(m) for m in _CITATION_MARKER_RE.findall(text)]
    seen: set[int] = set()
    ordered_markers = []
    for marker in referenced_markers:
        if marker not in seen:
            seen.add(marker)
            ordered_markers.append(marker)

    by_marker = {c.marker: c for c in citations}
    return [by_marker[m] for m in ordered_markers if m in by_marker]


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    return LLMClient()


class ChatRequest(BaseModel):
    query: str


class ChatCitation(BaseModel):
    marker: int
    section: str | None
    text: str


class ChatResponse(BaseModel):
    text: str
    refused: bool
    conceded: bool
    intent: str | None
    citations: list[ChatCitation]


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest, db: Session = Depends(get_db), llm: LLMClient = Depends(get_llm)
) -> ChatResponse:
    result = pipeline_answer(payload.query, db, llm=llm)

    citations: list[ChatCitation] = []
    if result.verification is not None and result.verification.generation is not None:
        referenced = _referenced_citations(result.text, result.verification.generation.citations)
        citations = [
            ChatCitation(marker=c.marker, section=c.section, text=c.text) for c in referenced
        ]

    return ChatResponse(
        text=result.text,
        refused=result.refused,
        conceded=result.conceded,
        intent=result.intent.value if result.intent is not None else None,
        citations=citations,
    )
