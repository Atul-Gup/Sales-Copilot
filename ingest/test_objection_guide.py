from collections.abc import Generator, Sequence

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, Chunk, Model, Source
from ingest.objection_guide import DOCUMENT_PATH, parse_objection_guide, run

_DOCUMENT_AVAILABLE = DOCUMENT_PATH.exists()


class _FakeEmbedder:
    """Deterministic, dimension-correct stand-in for EmbeddingClient — no
    network call, so this test suite never needs an API key."""

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
        # objection_guide.run() looks up existing XC60/EX30 Model rows
        # rather than creating them (docs/CORPUS.md: this file is ingested
        # after the five product documents, not standalone) — seed them.
        db.add(Model(brand="Volvo", name="XC60", status="active"))
        db.add(Model(brand="Volvo", name="EX30", status="active"))
        db.flush()
        yield db


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_parse_objection_guide_finds_28_items_with_no_malformed_ids() -> None:
    report = parse_objection_guide(DOCUMENT_PATH)
    assert len(report.items) == 28
    assert report.malformed_external_ids == []


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_parse_objection_guide_skips_the_removed_item_9() -> None:
    report = parse_objection_guide(DOCUMENT_PATH)
    external_ids = [item.external_id for item in report.items]
    assert "EX30_009" not in external_ids
    assert external_ids[:8] == [f"EX30_00{n}" for n in range(1, 9)]


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_parse_objection_guide_assigns_brand_by_section_not_content() -> None:
    report = parse_objection_guide(DOCUMENT_PATH)
    by_id = {item.external_id: item for item in report.items}
    assert by_id["EX30_001"].brand == "EX30"
    assert by_id["XC60_010"].brand == "XC60"
    # A competitor-comparison item still belongs to XC60 (the section it's
    # under), not to whichever competitor it names in its text.
    assert by_id["XC60_020"].brand == "XC60"
    assert by_id["GENERAL_027"].brand is None


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_supporting_source_is_kept_inside_the_chunk_text_not_split_out() -> None:
    report = parse_objection_guide(DOCUMENT_PATH)
    item = next(i for i in report.items if i.external_id == "EX30_001")
    assert "Powertrain" in item.supporting_source


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_run_ingests_28_chunks_with_correct_document_id_and_external_id(
    session: Session,
) -> None:
    report = run(session, embedder=_FakeEmbedder())  # type: ignore[arg-type]

    assert report.chunk_count == 28
    assert report.malformed_external_ids == []
    assert len(report.chunk_ids) == 28

    chunks = session.query(Chunk).filter(Chunk.id.in_(report.chunk_ids)).all()
    by_external_id = {c.external_id: c for c in chunks}

    xc60 = session.query(Model).filter_by(brand="Volvo", name="XC60").one()
    ex30 = session.query(Model).filter_by(brand="Volvo", name="EX30").one()

    assert by_external_id["EX30_001"].document_id == ex30.id
    assert by_external_id["XC60_010"].document_id == xc60.id
    # The 3 General items get no single model — nullable document_id
    # (migration b7e2f14a9c3d), not a fabricated association.
    assert by_external_id["GENERAL_027"].document_id is None
    assert by_external_id["GENERAL_028"].document_id is None
    assert by_external_id["GENERAL_029"].document_id is None

    # One shared source row for the whole file, not one per item.
    source_ids = {c.source_id for c in chunks}
    assert len(source_ids) == 1
    source = session.get(Source, source_ids.pop())
    assert source is not None
    assert source.document_title == "Volvo Objection Handling Guide"


@pytest.mark.skipif(not _DOCUMENT_AVAILABLE, reason="objection-handling.docx not present")
def test_run_raises_a_clear_error_if_product_docs_were_never_ingested() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as empty_session:
        with pytest.raises(ValueError, match="no existing Model row"):
            run(empty_session, embedder=_FakeEmbedder())  # type: ignore[arg-type]
