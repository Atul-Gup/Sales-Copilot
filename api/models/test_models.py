from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import Base, Brand, CarModel, Feature, SafetyRating, Source, Spec, Variant


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
def variant(session: Session) -> Variant:
    source = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in",
        retrieved_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()

    brand = Brand(name="Volvo", segment="luxury")
    session.add(brand)
    session.flush()

    model = CarModel(brand_id=brand.id, name="XC60", body_type="suv", status="active")
    session.add(model)
    session.flush()

    variant = Variant(
        model_id=model.id,
        name="XC60 B5 Inscription",
        powertrain="mild_hybrid_petrol",
        ex_showroom_paise=6_490_000_00,
        price_source_id=source.id,
    )
    session.add(variant)
    session.flush()
    return variant


def test_spec_requires_a_source(session: Session, variant: Variant) -> None:
    session.add(Spec(variant_id=variant.id, attribute="boot_space_litres", value_num=709))
    with pytest.raises(IntegrityError):
        session.flush()


def test_feature_requires_a_source(session: Session, variant: Variant) -> None:
    session.add(
        Feature(variant_id=variant.id, feature_key="panoramic_roof", availability="standard")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_safety_rating_requires_a_source(session: Session, variant: Variant) -> None:
    session.add(
        SafetyRating(
            model_id=variant.model_id,
            protocol="euro_ncap",
            year=2024,
            tested_variant="XC60 D4 AWD, LHD",
            status="expired",
            adult_score=34,
            child_score=44,
            vru_score=21,
            assist_score=13,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_spec_with_a_source_is_inserted(session: Session, variant: Variant) -> None:
    source = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(source)
    session.flush()

    session.add(
        Spec(
            variant_id=variant.id,
            attribute="boot_space_litres",
            value_num=709,
            source_id=source.id,
        )
    )
    session.flush()

    stored = session.query(Spec).one()
    assert stored.source_id == source.id
