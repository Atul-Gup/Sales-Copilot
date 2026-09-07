"""api/retrieval/hybrid.py — hybrid retrieval over Corpus B (T4.2b).

Dense embeddings alone miss the exact-match tokens this corpus is full of
(variant names, engine codes, protocol years); BM25 alone misses paraphrase.
Reciprocal rank fusion (RRF) combines both rankings by rank position, so no
score normalisation between a cosine similarity and a BM25 score is needed —
see docs/RETRIEVAL.md's "Hybrid retrieval (Corpus B)" section.

Both rankers run in plain Python rather than as a single SQL query: this
corpus (a few dozen chunks today) is small enough that loading every
embedding/text costs nothing, and it lets the exact same ranking code run
against a real Postgres/pgvector column or the SQLite JSON fallback
(api/models/vector_type.py) with no dialect-specific branch here. A real ANN
index only starts to matter at a corpus size this project doesn't have.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingClient
from api.models import DocumentChunk

_TOKEN_RE = re.compile(r"\w+")

# The standard RRF damping constant — see Cormack, Clarke & Buettcher (2009).
DEFAULT_RRF_K = 60


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def dense_rank(query_vector: list[float], chunks: list[DocumentChunk], *, k: int = 25) -> list[int]:
    """Chunk ids ranked by cosine similarity to `query_vector`, best first."""
    scored = sorted(chunks, key=lambda c: _cosine(query_vector, c.embedding), reverse=True)
    return [c.id for c in scored[:k]]


def sparse_rank(query: str, chunks: list[DocumentChunk], *, k: int = 25) -> list[int]:
    """Chunk ids ranked by BM25 relevance to `query`, best first."""
    if not chunks:
        return []
    corpus_tokens = [_tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus_tokens)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [c.id for c, _score in ranked[:k]]


def reciprocal_rank_fusion(
    rankings: list[list[int]], *, k: int = DEFAULT_RRF_K, top_n: int = 50
) -> list[int]:
    """Merge rank-ordered id lists: score(id) = sum of 1/(k + rank), rank
    1-indexed per input ranking. Ids absent from a ranking simply don't
    contribute a term for it — no penalty beyond not being there.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [doc_id for doc_id, _score in ranked[:top_n]]


@dataclass(frozen=True)
class HybridResult:
    chunk_ids: list[int]
    dense_ids: list[int]
    sparse_ids: list[int]


def hybrid_search(
    session: Session,
    embedder: EmbeddingClient,
    query: str,
    *,
    k_each: int = 25,
    top_n: int = 50,
) -> HybridResult:
    """Dense + sparse retrieval over every indexed chunk, fused by RRF.

    Loads the whole `document_chunks` table rather than filtering first —
    T4.2c's reranker (and a real corpus large enough to need it) is where
    pre-filtering would start to matter.
    """
    chunks = list(session.scalars(select(DocumentChunk)).all())
    query_vector = embedder.embed([query]).vectors[0]
    dense_ids = dense_rank(query_vector, chunks, k=k_each)
    sparse_ids = sparse_rank(query, chunks, k=k_each)
    fused = reciprocal_rank_fusion([dense_ids, sparse_ids], top_n=top_n)
    return HybridResult(chunk_ids=fused, dense_ids=dense_ids, sparse_ids=sparse_ids)
