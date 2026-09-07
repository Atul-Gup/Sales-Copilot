"""evals/run_retrieval_eval.py — retrieval-only ablation (T4.2b).

Measures dense-only vs sparse-only vs hybrid (RRF) retrieval quality against
`evals/dataset/retrieval.jsonl`, a hand-labelled set of 24 objection-style
queries over Corpus B, each labelled with the (document_title, page) of the
one chunk that actually answers it and which retriever ("dense"/"sparse"/
"either") it's expected to favour.

This runs before any end-to-end objection-path number so a later failure can
be attributed to retrieval or generation rather than guessed at
(docs/RETRIEVAL.md, Layer 3: "measuring retrieval separately... without it
you're guessing").

Also runs the T4.2c reranking ablation: hybrid top-50 → LLM-based rerank
(`api/retrieval/rerank.py`) → top-5, reporting the same precision/recall
alongside the added latency, so reranking is a measured trade-off per
docs/RETRIEVAL.md ("this is a real decision, not a default") rather than a
default left on.

No live `OPENAI_API_KEY` is guaranteed in this sandbox (the same live-infra
gap this project has hit before — see T3.6, T4.2a): if it's unset, dense
retrieval falls back to `_HashEmbedder`, a deterministic feature-hashed
term-frequency vector, and reranking falls back to `_LexicalOverlapLLM`, a
deterministic token-overlap scorer wearing the same `LLMClient.complete()`
interface (both embeddings and reranking are OpenAI-backed as of T7.4, so one
key now gates both). Neither proxy is the real thing — they exercise the
ranking/fusion/parsing code honestly but are not measurements of real
embedding or LLM quality, and the results say so explicitly. Re-run with the
key set for numbers worth citing in the writeup.

Usage: `python -m evals.run_retrieval_eval` (writes
`evals/results/retrieval_baseline.json`).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from api.llm.client import CompletionResult, LLMClient, Message
from api.llm.embeddings import EmbeddingClient, EmbeddingResult
from api.models import Base, DocumentChunk
from api.retrieval.hybrid import dense_rank, reciprocal_rank_fusion, sparse_rank
from api.retrieval.rerank import rerank as rerank_fn
from ingest import documents as documents_ingest

DATASET_PATH = Path(__file__).parent / "dataset" / "retrieval.jsonl"
RESULTS_DIR = Path(__file__).parent / "results"

HASH_DIM = 256
_TOKEN_RE = re.compile(r"\w+")
_CANDIDATE_RE = re.compile(r"^id=(\d+): (.*)$", re.MULTILINE)
_QUERY_RE = re.compile(r"^Query: (.*)$", re.MULTILINE)
DEFAULT_K = 5


@dataclass
class _HashEmbedder:
    """Deterministic feature-hashed term-frequency stand-in for a real dense
    embedder — see the module docstring for why. Duck-types `EmbeddingClient`
    so `ingest.documents.run` and `hybrid_search`/`dense_rank` don't need to
    know which one they got.
    """

    def embed(self, texts: list[str], **_kwargs: Any) -> EmbeddingResult:
        vectors = [self._vector(t) for t in texts]
        return EmbeddingResult(
            vectors=vectors, model="hash-proxy", input_tokens=0, cost_usd=None, latency_ms=0.0
        )

    def _vector(self, text: str) -> list[float]:
        counts = Counter(_TOKEN_RE.findall(text.lower()))
        vector = [0.0] * HASH_DIM
        for token, count in counts.items():
            idx = int(hashlib.sha256(token.encode()).hexdigest(), 16) % HASH_DIM
            vector[idx] += float(count)
        return vector


@dataclass
class _LexicalOverlapLLM:
    """Deterministic stand-in for `LLMClient` when no `OPENAI_API_KEY` is
    set — the reranking equivalent of `_HashEmbedder` above. Parses the exact
    prompt format `rerank()`'s `_build_prompt` produces (`Query: ...` then
    `id=N: text` lines) and returns candidate ids ordered by shared-token
    count with the query, as the same JSON-array text a real completion
    would need to produce — so `rerank()`'s own parsing/fallback code is
    exercised for real, only the ranking judgment itself is a proxy.
    """

    def complete(self, messages: list[Message], **_kwargs: Any) -> CompletionResult:
        prompt = messages[0].content
        query_match = _QUERY_RE.search(prompt)
        query_tokens = (
            set(_TOKEN_RE.findall(query_match.group(1).lower())) if query_match else set()
        )
        candidates = [(int(m.group(1)), m.group(2)) for m in _CANDIDATE_RE.finditer(prompt)]
        ranked = sorted(
            candidates,
            key=lambda c: len(query_tokens & set(_TOKEN_RE.findall(c[1].lower()))),
            reverse=True,
        )
        return CompletionResult(
            text=json.dumps([doc_id for doc_id, _text in ranked]),
            model="lexical-overlap-proxy",
            input_tokens=0,
            output_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
            retries=0,
        )


def _load_dataset() -> list[dict[str, Any]]:
    with DATASET_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_corpus(embedder: EmbeddingClient | _HashEmbedder) -> Session:
    """An in-memory DB populated by the real Corpus B ingest — see
    evals/run_eval.py's `build_corpus_session` for the identical pattern
    against Corpus A.
    """
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    session = Session(engine)
    documents_ingest.run(session, embedder=embedder)  # type: ignore[arg-type]
    session.commit()
    return session


def _relevant_ids(chunks: list[DocumentChunk], entry: dict[str, Any]) -> set[int]:
    wanted = {(ref["document_title"], ref["page"]) for ref in entry["relevant"]}
    return {c.id for c in chunks if (c.document_title, c.page) in wanted}


def _precision_recall_at_k(
    ranked_ids: list[int], relevant_ids: set[int], k: int
) -> tuple[float, float]:
    hits = len(set(ranked_ids[:k]) & relevant_ids)
    precision = hits / k
    recall = hits / len(relevant_ids) if relevant_ids else 0.0
    return precision, recall


def run_ablation(k: int = DEFAULT_K) -> dict[str, Any]:
    have_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    embedder: EmbeddingClient | _HashEmbedder = (
        EmbeddingClient() if have_openai_key else _HashEmbedder()
    )
    llm: LLMClient | _LexicalOverlapLLM = LLMClient() if have_openai_key else _LexicalOverlapLLM()

    session = build_corpus(embedder)
    try:
        chunks = list(session.scalars(select(DocumentChunk)).all())
        chunks_by_id = {c.id: c for c in chunks}
        dataset = _load_dataset()

        totals: dict[str, list[float]] = {
            "dense_only": [0.0, 0.0],
            "sparse_only": [0.0, 0.0],
            "hybrid": [0.0, 0.0],
            "hybrid_then_rerank": [0.0, 0.0],
        }
        rerank_latencies_ms: list[float] = []

        for entry in dataset:
            query_vector = embedder.embed([entry["query"]]).vectors[0]
            dense_ids = dense_rank(query_vector, chunks, k=25)
            sparse_ids = sparse_rank(entry["query"], chunks, k=25)
            fused_ids = reciprocal_rank_fusion([dense_ids, sparse_ids], top_n=50)

            fused_chunks = [chunks_by_id[i] for i in fused_ids]
            start = time.perf_counter()
            rerank_result = rerank_fn(llm, entry["query"], fused_chunks, top_k=k)  # type: ignore[arg-type]
            rerank_latencies_ms.append((time.perf_counter() - start) * 1000)

            relevant_ids = _relevant_ids(chunks, entry)
            for label, ranked in (
                ("dense_only", dense_ids),
                ("sparse_only", sparse_ids),
                ("hybrid", fused_ids),
                ("hybrid_then_rerank", rerank_result.chunk_ids),
            ):
                precision, recall = _precision_recall_at_k(ranked, relevant_ids, k)
                totals[label][0] += precision
                totals[label][1] += recall

        n = len(dataset)
        return {
            "n_queries": n,
            "k": k,
            "dense_embedder": (
                "openai:text-embedding-3-small"
                if have_openai_key
                else "hash-proxy (OPENAI_API_KEY unset — NOT a measurement of real "
                "semantic embedding quality, see module docstring)"
            ),
            "reranker": (
                "openai:gpt-4o-mini"
                if have_openai_key
                else "lexical-overlap-proxy (OPENAI_API_KEY unset — NOT a measurement of "
                "real cross-encoder/LLM reranking quality, see module docstring)"
            ),
            "tracks": {
                label: {
                    "precision_at_k": totals[label][0] / n,
                    "recall_at_k": totals[label][1] / n,
                }
                for label in totals
            },
            "avg_rerank_latency_ms": sum(rerank_latencies_ms) / n,
        }
    finally:
        session.close()


def main() -> None:
    results = run_ablation()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "retrieval_baseline.json"
    out_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
