from collections.abc import Generator, Sequence
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, Chunk, Model, Source
from ingest.product_docs import DOCUMENTS, IngestReport, chunk_pdf, run

REAL_DOCUMENTS = [doc for doc in DOCUMENTS if doc["document_path"].exists()]


class _FakeEmbedder:
    """Deterministic, dimension-correct stand-in for EmbeddingClient — no
    network call, so this test suite never needs an API key.
    """

    def embed(
        self, texts: Sequence[str], *, model: str = "text-embedding-3-small"
    ) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[0.0] * 1536 for _ in texts],
            model=model,
            input_tokens=0,
            cost_usd=0.0,
            latency_ms=0.0,
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


@pytest.mark.parametrize("doc", REAL_DOCUMENTS, ids=lambda d: d["document_title"])
def test_chunk_pdf_produces_section_aligned_chunks(doc: dict[str, object]) -> None:
    path = doc["document_path"]
    assert isinstance(path, Path)
    chunks = chunk_pdf(path)
    assert len(chunks) > 5
    assert all(chunk.text for chunk in chunks)
    assert all(chunk.page >= 1 for chunk in chunks)
    # every fact table has its own numbered section, so most chunks should
    # carry a section label — the only exception is the leading title block.
    labelled = [c for c in chunks if c.section is not None]
    assert len(labelled) >= len(chunks) - 1


def test_run_ingests_every_available_document(session: Session) -> None:
    reports = run(session, embedder=_FakeEmbedder())  # type: ignore[arg-type]

    by_title = {r.document_title: r for r in reports}
    for doc in DOCUMENTS:
        report = by_title[doc["document_title"]]
        if doc["document_path"].exists():
            assert report.error is None
            assert report.chunk_count > 0
        else:
            assert report.error is not None

    n_available = len(REAL_DOCUMENTS)
    assert session.query(Chunk).count() > 0
    assert session.query(Model).count() == len(
        {(d["brand"], d["model_name"]) for d in REAL_DOCUMENTS}
    )
    assert session.query(Source).filter(Source.kind == "product_document").count() == n_available


def test_run_reports_a_missing_file_without_raising(session: Session) -> None:
    reports = run(session, embedder=_FakeEmbedder())  # type: ignore[arg-type]
    missing = [d["document_title"] for d in DOCUMENTS if not d["document_path"].exists()]
    if not missing:
        pytest.skip("all five corpus documents are present")

    report = next(r for r in reports if r.document_title == missing[0])
    assert isinstance(report, IngestReport)
    assert report.chunk_count == 0
    assert report.error is not None


def test_every_chunk_carries_a_source(session: Session) -> None:
    run(session, embedder=_FakeEmbedder())  # type: ignore[arg-type]
    for chunk in session.query(Chunk).all():
        assert chunk.source_id is not None
