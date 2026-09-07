from collections.abc import Generator
from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, DocumentChunk, Source
from ingest import audi, euroncap, mercedes, volvo
from ingest.documents import DOCUMENTS, chunk_pdf, run


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


@dataclass
class _FakeEmbedder:
    """Deterministic stand-in for EmbeddingClient — one 3-dim vector per
    text, keyed off the text's length, so no real API call is needed.
    """

    calls: int = 0

    def embed(self, texts: list[str], **_kwargs: object) -> EmbeddingResult:
        self.calls += 1
        vectors = [[float(len(t)), 0.0, 0.0] for t in texts]
        return EmbeddingResult(
            vectors=vectors,
            model="fake",
            input_tokens=sum(len(t) for t in texts),
            cost_usd=None,
            latency_ms=0.0,
        )


def test_chunk_pdf_stays_within_a_page_and_records_page_numbers() -> None:
    warranty_path = DOCUMENTS[0]["document_path"]
    chunks = chunk_pdf(warranty_path)
    assert chunks
    assert all(chunk.page >= 1 for chunk in chunks)
    assert all(chunk.text for chunk in chunks)


def test_run_creates_a_chunk_row_per_extracted_chunk_with_a_source(session: Session) -> None:
    embedder = _FakeEmbedder()
    run(session, embedder=embedder)  # type: ignore[arg-type]
    session.flush()

    chunks = session.scalars(select(DocumentChunk)).all()
    assert chunks
    assert embedder.calls == len([doc for doc in DOCUMENTS if doc["document_path"].exists()])
    for chunk in chunks:
        assert chunk.source_id is not None
        source = session.get(Source, chunk.source_id)
        assert source is not None
        assert len(chunk.embedding) == 3


def test_run_reuses_existing_euroncap_source_instead_of_duplicating(session: Session) -> None:
    volvo.run(session)
    mercedes.run(session)
    audi.run(session)
    euroncap.run(session)
    session.flush()
    sources_before = session.scalars(select(Source)).all()
    ncap_source_ids_before = {s.id for s in sources_before if s.kind == "euro_ncap_report"}
    assert ncap_source_ids_before

    run(session, embedder=_FakeEmbedder())  # type: ignore[arg-type]
    session.flush()

    sources_after = session.scalars(select(Source)).all()
    ncap_source_ids_after = {s.id for s in sources_after if s.kind == "euro_ncap_report"}
    assert ncap_source_ids_after == ncap_source_ids_before

    xc60_chunks = session.scalars(
        select(DocumentChunk).where(DocumentChunk.document_title == "Euro NCAP | XC60")
    ).all()
    assert xc60_chunks
    assert {c.source_id for c in xc60_chunks} == ncap_source_ids_before & {
        c.source_id for c in xc60_chunks
    }
