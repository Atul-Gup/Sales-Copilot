from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.llm.embeddings import EmbeddingResult
from api.models import Base, Brand, DocumentChunk, ServiceCentre, Source
from api.objection.retrieve import retrieve_chunks, retrieve_facts


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


def _source(session: Session) -> Source:
    source = Source(
        kind="service_locator",
        publisher="Test",
        url="https://example.com",
        document_title=None,
        retrieved_at=datetime(2026, 9, 4, tzinfo=UTC),
        verified_at=datetime(2026, 9, 4, tzinfo=UTC),
        checksum="deadbeef",
    )
    session.add(source)
    session.flush()
    return source


def test_service_network_facts_counts_centres_per_brand(session: Session) -> None:
    source = _source(session)
    volvo = Brand(name="Volvo Cars", segment="luxury")
    mercedes = Brand(name="Mercedes-Benz", segment="luxury")
    session.add_all([volvo, mercedes])
    session.flush()
    session.add_all(
        [
            ServiceCentre(
                brand_id=volvo.id, city="Mumbai", state="MH", address="x", source_id=source.id
            ),
            ServiceCentre(
                brand_id=mercedes.id, city="Mumbai", state="MH", address="x", source_id=source.id
            ),
            ServiceCentre(
                brand_id=mercedes.id, city="Pune", state="MH", address="x", source_id=source.id
            ),
        ]
    )
    session.flush()

    facts = retrieve_facts(
        session,
        "service_network",
        {"volvo_brand": "Volvo Cars", "competitor_brand": "Mercedes-Benz"},
    )

    claims = {f.claim for f in facts}
    assert any("Volvo Cars has 1" in c for c in claims)
    assert any("Mercedes-Benz has 2" in c for c in claims)


def test_service_network_facts_skips_brands_with_no_rows(session: Session) -> None:
    facts = retrieve_facts(session, "service_network", {"volvo_brand": "Volvo Cars"})
    assert facts == []


def test_ungrounded_categories_return_no_facts(session: Session) -> None:
    for category in ("price_positioning", "resale_value", "brand_prestige", "waiting_period"):
        assert retrieve_facts(session, category, {}) == []


@dataclass
class _FakeEmbedder:
    def embed(self, texts: list[str], **_kwargs: object) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=[[float(len(t)), 0.0] for t in texts],
            model="fake",
            input_tokens=0,
            cost_usd=None,
            latency_ms=0.0,
        )


def test_retrieve_chunks_returns_citable_chunks(session: Session) -> None:
    source = _source(session)
    chunk = DocumentChunk(
        source_id=source.id,
        document_title="Volvo Warranty (India)",
        section=None,
        page=1,
        text="warranty coverage terms",
        embedding=[1.0, 0.0],
    )
    session.add(chunk)
    session.flush()

    results = retrieve_chunks(session, _FakeEmbedder(), "warranty coverage", k=5)  # type: ignore[arg-type]

    assert len(results) == 1
    assert results[0].document_title == "Volvo Warranty (India)"
    assert results[0].source_id == source.id


def test_retrieve_chunks_empty_corpus_returns_empty(session: Session) -> None:
    results = retrieve_chunks(session, _FakeEmbedder(), "anything", k=5)  # type: ignore[arg-type]
    assert results == []
