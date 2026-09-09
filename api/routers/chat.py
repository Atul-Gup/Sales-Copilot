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

**T7.7 — structured citations and guardrail warnings.** The response shape
changed from a flat `{text, refused, conceded, intent, citations}` to
`{response, claims, warnings}`:

- `claims` is `api/services/verify.py::extract_claims`'s output, unchanged —
  this endpoint does not re-parse `[n]` markers itself. Each claim already
  carries its own `chunk_id`/`source`, which is the whole point: a citation
  is now scoped to the specific sentence it grounds, not the response as a
  whole (the old `citations` list, and its `_referenced_citations` filter
  below it, are gone — `extract_claims` only ever returns claims for
  markers that were actually offered to the model, so there's no
  offered-but-unused chunk to filter out here anymore).
- `warnings` replaces the old boolean `refused`/`conceded` fields with a
  typed list, populated from three sources: `AnswerResult.conceded`
  (`must_concede` fired), `AnswerResult.refusal_reason ==
  "no_answer_outside_corpus"` (the corpus had nothing to answer from), and
  any `disparagement` entry in `VerifiedGenerationResult.violations`. That
  third one can only ever appear alongside a `grounding_violation` refusal
  under the current verify_grounding design (`docs/RETRIEVAL.md`:
  "regenerate once, refuse on second failure" — an *accepted* response
  always has an empty `violations` list by construction, since acceptance
  requires zero violations), so a disparagement warning is really
  annotating *why* a refusal happened, not flagging a live disparaging
  sentence in the returned `response` text. Other refusal causes
  (`customer_facing` blocks, a `grounding_violation` refusal with no
  disparagement among its violations) intentionally produce no warning —
  out of scope for T7.7, which named exactly these three rules.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.db import get_db
from api.llm.client import LLMClient
from api.services.pipeline import AnswerResult
from api.services.pipeline import answer as pipeline_answer

router = APIRouter()

_MUST_CONCEDE_TEXT = (
    "This concedes a known Volvo weakness, verified from real data — not a deflection."
)
_NO_ANSWER_OUTSIDE_CORPUS_TEXT = (
    "Nothing in the sourced documents answers this — not something to relay as fact."
)


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    return LLMClient()


class ChatRequest(BaseModel):
    query: str


class Claim(BaseModel):
    text_span: str
    chunk_id: int
    source: str


class Warning(BaseModel):
    type: str
    text: str


class ChatResponse(BaseModel):
    response: str
    claims: list[Claim]
    warnings: list[Warning]


def _build_warnings(result: AnswerResult) -> list[Warning]:
    warnings: list[Warning] = []
    if result.conceded:
        warnings.append(Warning(type="must_concede", text=_MUST_CONCEDE_TEXT))
    if result.refusal_reason == "no_answer_outside_corpus":
        warnings.append(
            Warning(type="no_answer_outside_corpus", text=_NO_ANSWER_OUTSIDE_CORPUS_TEXT)
        )
    if result.verification is not None:
        for violation in result.verification.violations:
            if violation.reason.startswith("disparagement:"):
                warnings.append(
                    Warning(type="disparagement", text=violation.reason.split(":", 1)[1].strip())
                )
    return warnings


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest, db: Session = Depends(get_db), llm: LLMClient = Depends(get_llm)
) -> ChatResponse:
    result = pipeline_answer(payload.query, db, llm=llm)

    claims: list[Claim] = []
    if result.verification is not None:
        claims = [
            Claim(text_span=c.text_span, chunk_id=c.chunk_id, source=c.source)
            for c in result.verification.claims
        ]

    return ChatResponse(
        response=result.text,
        claims=claims,
        warnings=_build_warnings(result),
    )
