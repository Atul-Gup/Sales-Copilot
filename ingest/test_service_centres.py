from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base, CityAlias, ServiceCentre, Source
from ingest.service_centres import CITY_ALIASES, EXCLUDED_ROWS, SHEET_PATH, run

pytestmark = pytest.mark.skipif(
    not SHEET_PATH.exists(), reason="service centre spreadsheet not present in this checkout"
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
        db.rollback()


def test_every_centre_carries_a_source(session: Session) -> None:
    run(session)
    session.flush()
    for centre in session.query(ServiceCentre).all():
        assert centre.source_id is not None


def test_excluded_rows_are_not_ingested(session: Session) -> None:
    run(session)
    session.flush()
    ingested = {(sc.brand, sc.address) for sc in session.query(ServiceCentre).all()}
    for brand, centre_name in EXCLUDED_ROWS:
        assert not any(centre_name in address for b, address in ingested if b == brand)


def test_city_aliases_are_populated(session: Session) -> None:
    run(session)
    session.flush()
    aliases = {a.alias: a.canonical_city for a in session.query(CityAlias).all()}
    assert aliases == CITY_ALIASES


def test_aliased_cities_are_normalised(session: Session) -> None:
    run(session)
    session.flush()
    cities = {sc.city for sc in session.query(ServiceCentre).all()}
    assert not cities & set(CITY_ALIASES.keys())


def test_one_source_per_brand(session: Session) -> None:
    run(session)
    session.flush()
    brands_with_centres = {sc.brand for sc in session.query(ServiceCentre).all()}
    sources = session.query(Source).filter(Source.kind == "service_locator").all()
    assert len(sources) == len(brands_with_centres)
