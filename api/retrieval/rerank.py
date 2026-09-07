"""api/retrieval/rerank.py — reranking the fused top-N down to top-k (T4.2c).

docs/RETRIEVAL.md's tooling table lists the reranker as "cross-encoder
(hosted or local)". This project already has exactly one LLM vendor surface
(`api/llm/client.py`, T4.1) and one embedding vendor surface
(`api/llm/embeddings.py`, T4.2a) — adding a third vendor SDK (a hosted
reranker) or the heaviest dependency this project has seen by far (a local
`sentence-transformers` + `torch` cross-encoder, ~2GB) for one node in one
path was a deliberate, asked-and-answered call: reuse the existing
`LLMClient` with a structured ranking prompt instead. It won't match a
purpose-built cross-encoder's precision or latency, and this module's own
ablation (`evals/run_retrieval_eval.py`) measures exactly how much it costs
and gains, per docs/RETRIEVAL.md's "this is a real decision, not a default."

Fails open: an LLM error or an unparseable response falls back to the
incoming (fused) order truncated to `top_k`, rather than raising. A stale
ranking is a precision regression the ablation can catch, not the kind of
unsupported claim `verify_grounding` (T4.4) exists to stop — a reranker
hiccup shouldn't take down the whole objection path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog

from api.llm.client import LLMClient, LLMError, Message
from api.models import DocumentChunk

logger = structlog.get_logger(__name__)

RERANK_MODEL = "gpt-4o-mini"
MAX_CANDIDATE_CHARS = 500


@dataclass(frozen=True)
class RerankResult:
    chunk_ids: list[int]
    latency_ms: float
    fell_back: bool


def _build_prompt(query: str, chunks: list[DocumentChunk], top_k: int) -> str:
    lines = [
        f"Query: {query}",
        "",
        f"Rank the following {len(chunks)} candidate passages by relevance to the query.",
        f"Respond with ONLY a JSON array of the {top_k} most relevant candidate ids, "
        "most relevant first — no other text.",
        "",
    ]
    for chunk in chunks:
        snippet = chunk.text[:MAX_CANDIDATE_CHARS].replace("\n", " ")
        lines.append(f"id={chunk.id}: {snippet}")
    return "\n".join(lines)


def _parse_ids(text: str, valid_ids: set[int]) -> list[int] | None:
    match = re.search(r"\[[^\]]*\]", text, re.DOTALL)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    ids: list[int] = []
    for item in parsed:
        if isinstance(item, int) and item in valid_ids and item not in ids:
            ids.append(item)
    return ids or None


def rerank(
    llm: LLMClient, query: str, chunks: list[DocumentChunk], *, top_k: int = 5
) -> RerankResult:
    if not chunks:
        return RerankResult(chunk_ids=[], latency_ms=0.0, fell_back=False)

    fallback_ids = [c.id for c in chunks[:top_k]]
    valid_ids = {c.id for c in chunks}
    prompt = _build_prompt(query, chunks, top_k)

    try:
        completion = llm.complete(
            [Message(role="user", content=prompt)], model=RERANK_MODEL, max_tokens=200
        )
    except LLMError as exc:
        logger.warning("rerank_call_failed_falling_back", error=str(exc))
        return RerankResult(chunk_ids=fallback_ids, latency_ms=0.0, fell_back=True)

    ids = _parse_ids(completion.text, valid_ids)
    if ids is None:
        logger.warning("rerank_response_unparseable_falling_back", response=completion.text)
        return RerankResult(
            chunk_ids=fallback_ids, latency_ms=completion.latency_ms, fell_back=True
        )

    if len(ids) < top_k:
        for chunk in chunks:
            if chunk.id not in ids:
                ids.append(chunk.id)
            if len(ids) == top_k:
                break

    return RerankResult(chunk_ids=ids[:top_k], latency_ms=completion.latency_ms, fell_back=False)
