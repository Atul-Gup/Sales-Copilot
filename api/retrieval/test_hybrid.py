from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, DocumentChunk, Source
from api.retrieval.hybrid import dense_rank, hybrid_search, reciprocal_rank_fusion, sparse_rank


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine("sqlite:///:memory:")

    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _make_chunk(
    session: Session, source: Source, *, text: str, embedding: list[float]
) -> DocumentChunk:
    chunk = DocumentChunk(
        source_id=source.id,
        document_title="Test Doc",
        section=None,
        page=1,
        text=text,
        embedding=embedding,
    )
    session.add(chunk)
    session.flush()
    return chunk


def _source(session: Session) -> Source:
    source = Source(
        kind="oem_site",
        publisher="Test",
        url="https://example.com",
        document_title="Test Doc",
        retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
        verified_at=datetime(2026, 9, 4, tzinfo=UTC),
        checksum="deadbeef",
    )
    session.add(source)
    session.flush()
    return source


def test_dense_rank_orders_by_cosine_similarity(session: Session) -> None:
    source = _source(session)
    close = _make_chunk(session, source, text="a", embedding=[1.0, 0.0])
    far = _make_chunk(session, source, text="b", embedding=[0.0, 1.0])
    ranked = dense_rank([1.0, 0.0], [far, close], k=2)
    assert ranked == [close.id, far.id]


def test_dense_rank_respects_k(session: Session) -> None:
    source = _source(session)
    chunks = [
        _make_chunk(session, source, text=str(i), embedding=[float(i), 0.0]) for i in range(5)
    ]
    ranked = dense_rank([4.0, 0.0], chunks, k=2)
    assert len(ranked) == 2


def test_sparse_rank_favours_exact_token_match(session: Session) -> None:
    source = _source(session)
    exact = _make_chunk(session, source, text="xDrive20i engine specifications", embedding=[0.0])
    unrelated = _make_chunk(session, source, text="warranty coverage terms", embedding=[0.0])
    ranked = sparse_rank("xDrive20i", [exact, unrelated], k=2)
    assert ranked[0] == exact.id


def test_sparse_rank_empty_corpus_returns_empty() -> None:
    assert sparse_rank("anything", [], k=5) == []


def test_reciprocal_rank_fusion_rewards_agreement() -> None:
    dense = [1, 2, 3]
    sparse = [2, 1, 4]
    fused = reciprocal_rank_fusion([dense, sparse], top_n=10)
    # 1 and 2 appear near the top of both rankings, so they should fuse ahead
    # of 3 and 4, which each appear in only one ranking.
    assert set(fused[:2]) == {1, 2}
    assert set(fused) == {1, 2, 3, 4}


def test_reciprocal_rank_fusion_respects_top_n() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3, 4, 5]], top_n=2)
    assert fused == [1, 2]


@dataclass
class _FakeEmbedder:
    vector: list[float]

    def embed(self, texts: list[str], **_kwargs: object) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[self.vector for _ in texts],
            model="fake",
            input_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
        )


def test_hybrid_search_merges_both_rankings(session: Session) -> None:
    source = _source(session)
    matching = _make_chunk(session, source, text="xDrive20i specifications", embedding=[1.0, 0.0])
    other = _make_chunk(session, source, text="unrelated warranty text", embedding=[0.0, 1.0])

    embedder = _FakeEmbedder(vector=[1.0, 0.0])
    result = hybrid_search(session, embedder, "xDrive20i", k_each=5, top_n=5)  # type: ignore[arg-type]

    assert result.chunk_ids[0] == matching.id
    assert other.id in result.chunk_ids
    assert result.dense_ids[0] == matching.id
    assert result.sparse_ids[0] == matching.id
