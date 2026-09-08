from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import Base, Chunk, Model, ServiceCentre, Source


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
def source(session: Session) -> Source:
    row = Source(
        kind="product_document",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60",
        document_title="Volvo XC60 product document",
        retrieved_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def model(session: Session) -> Model:
    row = Model(brand="Volvo", name="XC60", status="active")
    session.add(row)
    session.flush()
    return row


def test_chunk_requires_a_source(session: Session, model: Model) -> None:
    session.add(
        Chunk(document_id=model.id, text="Boot space is 709 litres.", embedding=[0.0] * 1536)
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_chunk_with_a_source_is_inserted(session: Session, source: Source, model: Model) -> None:
    session.add(
        Chunk(
            source_id=source.id,
            document_id=model.id,
            text="Boot space is 709 litres.",
            embedding=[0.0] * 1536,
        )
    )
    session.flush()

    stored = session.query(Chunk).one()
    assert stored.source_id == source.id


def test_service_centre_requires_a_source(session: Session) -> None:
    session.add(
        ServiceCentre(brand="Volvo", city="Bengaluru", state="Karnataka", address="Whitefield")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_service_centre_with_a_source_is_inserted(session: Session, source: Source) -> None:
    session.add(
        ServiceCentre(
            brand="Volvo",
            city="Bengaluru",
            state="Karnataka",
            address="Whitefield",
            source_id=source.id,
        )
    )
    session.flush()

    stored = session.query(ServiceCentre).one()
    assert stored.source_id == source.id
