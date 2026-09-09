"""api/services/retrieve.py — T2.1: hybrid retrieval over `chunks`.

Dense (pgvector cosine similarity) catches paraphrase and synonymy; BM25
catches the exact-match tokens this corpus is full of — trim names, engine
codes, model years (docs/RETRIEVAL.md). The two rank lists are fused by
reciprocal rank fusion, which combines on rank *position* rather than raw
score, so no cross-method score normalisation is needed.

The corpus is five documents' worth of chunks (docs/CORPUS.md) — small
enough to fetch and rank in Python rather than push the dense/sparse
scoring into SQL, which is also what keeps this module testable against
SQLite without a live pgvector index.

Reranking (T2.2, dropped) and the `in_corpus?` gate itself (wired up in
T4.5) are not part of this module — but `hybrid_search_scored` exposes the
fused RRF score alongside each chunk, since that score is what T3.6
calibrates the gate's threshold against in the absence of a reranker score.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass

import structlog
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingClient
from api.models import Chunk

logger = structlog.get_logger(__name__)

# Conventional RRF constant — de-emphasises differences deep in a rank list
# while still rewarding a top position; not tuned against this corpus yet.
RRF_K = 60

# T3.6's calibration finding: this is the best point on a poorly-separated
# curve, not a well-calibrated threshold — the fused RRF score doesn't
# separate in-corpus from out-of-corpus smoothly without a reranker (see
# docs/RETRIEVAL.md's "T3.6 finding" and evals/results/threshold_calibration
# .md). Revisit if reranking (T2.2) is ever revisited.
#
# Recalibrated after live testing against a 90-question real-world product
# test set (docs/CORPUS.md's objection-handling guide ingestion added 28
# chunks to the corpus after T3.6's original calibration ran — that shifted
# score distributions enough that the old 0.031778 value now only clears
# 84% of qa.jsonl's own ground truth, rescored against the current corpus,
# not the 100% it was chosen for). 0.031099 is the lowest qa.jsonl score
# found, live, against the current corpus — the same "100% in-corpus
# recall, best available refusal rate" philosophy T3.6 used, just rerun
# against today's corpus shape. Still not a clean separation (a reranker,
# T2.2, dropped, would be the real fix) — some genuine product questions
# can still score below this and get a false refusal; this only closes the
# gap that live testing actually found, not the underlying score-overlap
# problem itself.
IN_CORPUS_THRESHOLD = 0.031099

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def dense_rank(query_embedding: list[float], chunks: list[Chunk]) -> list[int]:
    """Chunk ids ranked by cosine similarity to `query_embedding`, best first."""
    scored = [(chunk.id, _cosine_similarity(query_embedding, chunk.embedding)) for chunk in chunks]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [chunk_id for chunk_id, _ in scored]


def sparse_rank(query: str, chunks: list[Chunk]) -> list[int]:
    """Chunk ids ranked by BM25 score against `query`, best first."""
    if not chunks:
        return []
    corpus_tokens = [_tokenize(chunk.text) for chunk in chunks]
    bm25 = BM25Okapi(corpus_tokens)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(
        zip((chunk.id for chunk in chunks), scores, strict=True),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [chunk_id for chunk_id, _ in ranked]


def _reciprocal_rank_fusion_scores(
    rank_lists: list[list[int]], *, k: int = RRF_K
) -> dict[int, float]:
    scores: dict[int, float] = {}
    for ranks in rank_lists:
        for position, item_id in enumerate(ranks):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + position + 1)
    return scores


def reciprocal_rank_fusion(rank_lists: list[list[int]], *, k: int = RRF_K) -> list[int]:
    """Fuse rank lists (each best-first) by rank position, per
    docs/RETRIEVAL.md: "fused with reciprocal rank fusion (no score
    normalisation needed, fuses on rank position)".
    """
    scores = _reciprocal_rank_fusion_scores(rank_lists, k=k)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)


def hybrid_search(
    query: str,
    session: Session,
    *,
    embedder: EmbeddingClient | None = None,
    top_k: int = 50,
) -> list[Chunk]:
    """Hybrid dense+BM25 retrieval over every chunk in the corpus, fused by
    reciprocal rank fusion. Returns up to `top_k` chunks, best first.
    """
    chunks = session.query(Chunk).all()
    if not chunks:
        return []

    embedder = embedder if embedder is not None else EmbeddingClient()
    query_embedding = embedder.embed([query]).vectors[0]

    dense = dense_rank(query_embedding, chunks)
    sparse = sparse_rank(query, chunks)
    fused_ids = reciprocal_rank_fusion([dense, sparse])

    by_id = {chunk.id: chunk for chunk in chunks}
    return [by_id[chunk_id] for chunk_id in fused_ids[:top_k]]


def hybrid_search_scored(
    query: str,
    session: Session,
    *,
    embedder: EmbeddingClient | None = None,
    top_k: int = 50,
) -> list[ScoredChunk]:
    """Same ranking as `hybrid_search`, but pairs each chunk with its fused
    RRF score — the confidence signal the `in_corpus?` gate thresholds
    against (docs/RETRIEVAL.md), since T2.2 dropped the cross-encoder
    reranker that would otherwise have supplied one.
    """
    start = time.perf_counter()
    chunks = session.query(Chunk).all()
    if not chunks:
        logger.info(
            "retrieval",
            corpus_size=0,
            top_score=0.0,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return []

    embedder = embedder if embedder is not None else EmbeddingClient()
    query_embedding = embedder.embed([query]).vectors[0]

    dense = dense_rank(query_embedding, chunks)
    sparse = sparse_rank(query, chunks)
    scores = _reciprocal_rank_fusion_scores([dense, sparse])

    by_id = {chunk.id: chunk for chunk in chunks}
    ranked_ids = sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
    results = [ScoredChunk(chunk=by_id[cid], score=scores[cid]) for cid in ranked_ids[:top_k]]

    logger.info(
        "retrieval",
        corpus_size=len(chunks),
        result_count=len(results),
        top_score=results[0].score if results else 0.0,
        latency_ms=(time.perf_counter() - start) * 1000,
    )
    return results
