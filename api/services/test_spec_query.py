from collections.abc import Generator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base, Brand, CarModel, Feature, SafetyRating, Source, Spec, Variant
from api.services.spec_query import (
    CitedFeature,
    CitedSafetyRating,
    CitedSpec,
    find_variants,
    find_variants_with_feature,
    get_features_for_variant,
    get_safety_ratings_for_model,
    get_specs_for_variant,
    list_variants,
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
def source(session: Session) -> Source:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()
    return src


@pytest.fixture
def variant(session: Session, source: Source) -> Variant:
    brand = Brand(name="Volvo", segment="luxury")
    session.add(brand)
    session.flush()

    model = CarModel(brand_id=brand.id, name="XC60", body_type="suv", status="active")
    session.add(model)
    session.flush()

    v = Variant(
        model_id=model.id,
        name="XC60 B5 Inscription",
        powertrain="mild_hybrid_petrol",
        ex_showroom_paise=6_490_000_00,
        price_source_id=source.id,
    )
    session.add(v)
    session.flush()
    return v


def test_cited_spec_cannot_be_built_without_a_source() -> None:
    with pytest.raises(ValidationError):
        CitedSpec(
            variant_id=1,
            attribute="boot_space_litres",
            value_text=None,
            value_num=Decimal(709),
            unit="litres",
            verified=True,
            verified_at=None,
        )  # type: ignore[call-arg]


def test_cited_feature_cannot_be_built_without_a_source() -> None:
    with pytest.raises(ValidationError):
        CitedFeature(
            variant_id=1, feature_key="panoramic_roof", availability="standard", cost_paise=None
        )  # type: ignore[call-arg]


def test_cited_safety_rating_cannot_be_built_without_a_source() -> None:
    with pytest.raises(ValidationError):
        CitedSafetyRating(
            model_id=1,
            protocol="euro_ncap",
            year=2024,
            tested_variant="XC60 B5, LHD",
            status="current",
            adult_score=Decimal(34),
            child_score=Decimal(44),
            vru_score=Decimal(21),
            assist_score=Decimal(13),
        )  # type: ignore[call-arg]


def test_get_specs_for_variant_returns_cited_facts(session: Session, variant: Variant) -> None:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()
    session.add(
        Spec(
            variant_id=variant.id,
            attribute="boot_space_litres",
            value_num=709,
            unit="litres",
            source_id=src.id,
            verified=True,
        )
    )
    session.flush()

    results = get_specs_for_variant(session, variant.id)

    assert len(results) == 1
    assert results[0].attribute == "boot_space_litres"
    assert results[0].value_num == 709
    assert results[0].source.id == src.id
    assert results[0].source.url == src.url


def test_get_specs_for_variant_filters_by_attribute(session: Session, variant: Variant) -> None:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()
    session.add_all(
        [
            Spec(
                variant_id=variant.id,
                attribute="boot_space_litres",
                value_num=709,
                source_id=src.id,
            ),
            Spec(
                variant_id=variant.id,
                attribute="ground_clearance_mm",
                value_num=216,
                source_id=src.id,
            ),
        ]
    )
    session.flush()

    results = get_specs_for_variant(session, variant.id, attribute="boot_space_litres")

    assert len(results) == 1
    assert results[0].attribute == "boot_space_litres"


def test_get_features_for_variant_returns_cited_facts(session: Session, variant: Variant) -> None:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/features",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()
    session.add(
        Feature(
            variant_id=variant.id,
            feature_key="panoramic_roof",
            availability="standard",
            source_id=src.id,
        )
    )
    session.flush()

    results = get_features_for_variant(session, variant.id)

    assert len(results) == 1
    assert results[0].feature_key == "panoramic_roof"
    assert results[0].source.id == src.id


def test_get_safety_ratings_for_model_returns_cited_facts(
    session: Session, variant: Variant
) -> None:
    src = Source(
        kind="euro_ncap",
        publisher="Euro NCAP",
        url="https://www.euroncap.com/en/results/volvo/xc60",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()
    session.add(
        SafetyRating(
            model_id=variant.model_id,
            protocol="euro_ncap",
            year=2022,
            tested_variant="XC60 B5, LHD",
            status="current",
            adult_score=34,
            child_score=44,
            vru_score=21,
            assist_score=13,
            report_source_id=src.id,
        )
    )
    session.flush()

    results = get_safety_ratings_for_model(session, variant.model_id, protocol="euro_ncap")

    assert len(results) == 1
    assert results[0].protocol == "euro_ncap"
    assert results[0].source.id == src.id


def test_find_variants_with_feature_respects_price_cap(
    session: Session, variant: Variant, source: Source
) -> None:
    feature_src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/features",
        retrieved_at=datetime.now(UTC),
    )
    session.add(feature_src)
    session.flush()
    session.add(
        Feature(
            variant_id=variant.id,
            feature_key="panoramic_roof",
            availability="standard",
            source_id=feature_src.id,
        )
    )
    session.flush()

    under_cap = find_variants_with_feature(session, "panoramic_roof", max_price_paise=7_000_000_00)
    over_cap = find_variants_with_feature(session, "panoramic_roof", max_price_paise=1_000_000_00)

    assert len(under_cap) == 1
    assert len(over_cap) == 0


def test_find_variants_filters_by_model_and_brand(session: Session, variant: Variant) -> None:
    by_model = find_variants(session, model_name="XC60")
    by_brand = find_variants(session, brand_name="Volvo")
    by_wrong_model = find_variants(session, model_name="X3")

    assert len(by_model) == 1
    assert len(by_brand) == 1
    assert len(by_wrong_model) == 0


def test_list_variants_returns_brand_and_model_labels(session: Session, variant: Variant) -> None:
    labels = list_variants(session)

    assert len(labels) == 1
    assert labels[0].id == variant.id
    assert labels[0].brand == "Volvo"
    assert labels[0].model == "XC60"
    assert labels[0].variant_name == variant.name
