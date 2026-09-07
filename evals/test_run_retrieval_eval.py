from api.llm.client import Message
from evals.run_retrieval_eval import _HashEmbedder, _LexicalOverlapLLM, build_corpus, run_ablation


def test_hash_embedder_is_deterministic() -> None:
    embedder = _HashEmbedder()
    a = embedder.embed(["xDrive20i specifications"]).vectors[0]
    b = embedder.embed(["xDrive20i specifications"]).vectors[0]
    assert a == b


def test_hash_embedder_differs_for_different_text() -> None:
    embedder = _HashEmbedder()
    a = embedder.embed(["warranty coverage"]).vectors[0]
    b = embedder.embed(["Euro NCAP crash test"]).vectors[0]
    assert a != b


def test_build_corpus_populates_document_chunks() -> None:
    from sqlalchemy import select

    from api.models import DocumentChunk

    session = build_corpus(_HashEmbedder())
    try:
        chunks = session.scalars(select(DocumentChunk)).all()
        assert chunks
    finally:
        session.close()


def test_run_ablation_reports_all_four_tracks_within_bounds() -> None:
    results = run_ablation(k=5)
    assert results["n_queries"] == 24
    assert set(results["tracks"]) == {
        "dense_only",
        "sparse_only",
        "hybrid",
        "hybrid_then_rerank",
    }
    for track in results["tracks"].values():
        assert 0.0 <= track["precision_at_k"] <= 1.0
        assert 0.0 <= track["recall_at_k"] <= 1.0
    assert results["avg_rerank_latency_ms"] >= 0.0


def test_run_ablation_notes_the_proxies_when_no_api_keys_are_set() -> None:
    import os

    if "OPENAI_API_KEY" in os.environ:
        return  # can't force this branch without also faking a real key elsewhere
    results = run_ablation(k=5)
    assert "hash-proxy" in results["dense_embedder"]
    assert "lexical-overlap-proxy" in results["reranker"]


def test_lexical_overlap_llm_ranks_by_shared_tokens() -> None:
    llm = _LexicalOverlapLLM()
    prompt = (
        "Query: xDrive20i specifications\n\n"
        "Rank the following 2 candidate passages by relevance to the query.\n\n"
        "id=1: warranty coverage terms\n"
        "id=2: xDrive20i engine specifications\n"
    )
    result = llm.complete([Message(role="user", content=prompt)], model="x", max_tokens=10)
    assert result.text == "[2, 1]"
