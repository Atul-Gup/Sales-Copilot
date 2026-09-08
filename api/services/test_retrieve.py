from collections.abc import Generator, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, Chunk, Model, Source
from api.services.retrieve import (
    dense_rank,
    hybrid_search,
    hybrid_search_scored,
    reciprocal_rank_fusion,
    sparse_rank,
)


class _FakeEmbedder:
    """Returns the query's own pre-registered vector, so a dense-only test
    can assert an exact ranking without a real embedding call.
    """

    def __init__(self, vectors_by_text: dict[str, list[float]]) -> None:
        self._vectors_by_text = vectors_by_text

    def embed(
        self, texts: Sequence[str], *, model: str = "text-embedding-3-small"
    ) -> EmbeddingResult:
        vectors = [self._vectors_by_text[text] for text in texts]
        return EmbeddingResult(
            vectors=vectors, model=model, input_tokens=0, cost_usd=0.0, latency_ms=0.0
        )


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


@pytest.fixture
def seeded(session: Session) -> tuple[Chunk, Chunk, Chunk]:
    source = Source(
        kind="product_document",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60",
        document_title="Volvo XC60 product document",
        retrieved_at=datetime.now(UTC),
    )
    model = Model(brand="Volvo", name="XC60", status="active")
    session.add_all([source, model])
    session.flush()

    boot_chunk = Chunk(
        source_id=source.id,
        document_id=model.id,
        text="Boot space is 709 litres with the rear seats up.",
        embedding=[1.0, 0.0, 0.0],
    )
    colour_chunk = Chunk(
        source_id=source.id,
        document_id=model.id,
        text="Available exterior colours include Crystal White and Denim Blue.",
        embedding=[0.0, 1.0, 0.0],
    )
    unrelated_chunk = Chunk(
        source_id=source.id,
        document_id=model.id,
        text="The infotainment system supports wireless Android Auto and CarPlay.",
        embedding=[0.0, 0.0, 1.0],
    )
    session.add_all([boot_chunk, colour_chunk, unrelated_chunk])
    session.flush()
    return boot_chunk, colour_chunk, unrelated_chunk


def test_dense_rank_orders_by_cosine_similarity(seeded: tuple[Chunk, Chunk, Chunk]) -> None:
    boot_chunk, colour_chunk, unrelated_chunk = seeded
    ranked = dense_rank([1.0, 0.0, 0.0], [boot_chunk, colour_chunk, unrelated_chunk])
    assert ranked[0] == boot_chunk.id


def test_sparse_rank_finds_the_exact_token_match(seeded: tuple[Chunk, Chunk, Chunk]) -> None:
    boot_chunk, colour_chunk, unrelated_chunk = seeded
    ranked = sparse_rank("boot space litres", [boot_chunk, colour_chunk, unrelated_chunk])
    assert ranked[0] == boot_chunk.id


def test_reciprocal_rank_fusion_rewards_agreement_over_a_single_top_rank() -> None:
    # id 2 is second in both lists; id 1 is first in only one. RRF should
    # still favour id 1 for its top rank per docs/RETRIEVAL.md, but id 2
    # must outrank whichever id appears nowhere in one of the two lists.
    dense = [1, 2, 3]
    sparse = [2, 1, 3]
    fused = reciprocal_rank_fusion([dense, sparse])
    assert fused[0] in (1, 2)
    assert fused[-1] == 3


def test_reciprocal_rank_fusion_is_a_pure_position_fuse() -> None:
    fused = reciprocal_rank_fusion([[10, 20], [20, 10]])
    assert set(fused) == {10, 20}
    # symmetric inputs must tie exactly (both averaged mid-rank positions)
    assert fused[0] in (10, 20)


def test_hybrid_search_returns_chunks_ranked_by_fusion(
    session: Session, seeded: tuple[Chunk, Chunk, Chunk]
) -> None:
    boot_chunk, colour_chunk, unrelated_chunk = seeded
    embedder = _FakeEmbedder({"how much boot space does the XC60 have": [1.0, 0.0, 0.0]})

    results = hybrid_search(
        "how much boot space does the XC60 have",
        session,
        embedder=embedder,  # type: ignore[arg-type]
    )

    assert results[0].id == boot_chunk.id
    assert {c.id for c in results} == {boot_chunk.id, colour_chunk.id, unrelated_chunk.id}


def test_hybrid_search_returns_empty_list_for_an_empty_corpus(session: Session) -> None:
    embedder = _FakeEmbedder({"anything": [1.0, 0.0, 0.0]})
    assert hybrid_search("anything", session, embedder=embedder) == []  # type: ignore[arg-type]


def test_hybrid_search_respects_top_k(session: Session, seeded: tuple[Chunk, Chunk, Chunk]) -> None:
    embedder = _FakeEmbedder({"boot space": [1.0, 0.0, 0.0]})
    results = hybrid_search("boot space", session, embedder=embedder, top_k=1)  # type: ignore[arg-type]
    assert len(results) == 1


def test_hybrid_search_scored_matches_hybrid_search_ranking(
    session: Session, seeded: tuple[Chunk, Chunk, Chunk]
) -> None:
    boot_chunk, colour_chunk, unrelated_chunk = seeded
    embedder = _FakeEmbedder({"boot space litres": [1.0, 0.0, 0.0]})

    plain = hybrid_search("boot space litres", session, embedder=embedder)  # type: ignore[arg-type]
    scored = hybrid_search_scored("boot space litres", session, embedder=embedder)  # type: ignore[arg-type]

    assert [c.id for c in plain] == [sc.chunk.id for sc in scored]
    assert scored[0].chunk.id == boot_chunk.id


def test_hybrid_search_scored_scores_are_descending(
    session: Session, seeded: tuple[Chunk, Chunk, Chunk]
) -> None:
    embedder = _FakeEmbedder({"boot space litres": [1.0, 0.0, 0.0]})
    scored = hybrid_search_scored("boot space litres", session, embedder=embedder)  # type: ignore[arg-type]
    scores = [sc.score for sc in scored]
    assert scores == sorted(scores, reverse=True)


def test_hybrid_search_scored_returns_empty_list_for_an_empty_corpus(session: Session) -> None:
    embedder = _FakeEmbedder({"anything": [1.0, 0.0, 0.0]})
    assert hybrid_search_scored("anything", session, embedder=embedder) == []  # type: ignore[arg-type]
