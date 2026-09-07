from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.db import get_db
from api.main import app
from api.models import Base, Brand, CarModel, Feature, Source, Spec, Variant


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

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
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()

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
        price_source_id=src.id,
    )
    session.add(v)
    session.flush()

    session.add(
        Spec(
            variant_id=v.id,
            attribute="boot_space_litres",
            value_num=709,
            unit="litres",
            source_id=src.id,
            verified=True,
        )
    )
    session.add(
        Feature(
            variant_id=v.id,
            feature_key="panoramic_roof",
            availability="standard",
            source_id=src.id,
        )
    )
    session.flush()
    return v


@pytest.fixture
def client(session: Session) -> Generator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_variants_returns_brand_and_model_labels(client: TestClient, variant: Variant) -> None:
    response = client.get("/variants")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == variant.id
    assert body[0]["brand"] == "Volvo"
    assert body[0]["model"] == "XC60"


def test_spec_returns_cited_specs_and_features(client: TestClient, variant: Variant) -> None:
    response = client.get("/spec", params={"variant_id": variant.id})
    assert response.status_code == 200
    body = response.json()
    assert len(body["specs"]) == 1
    assert body["specs"][0]["attribute"] == "boot_space_litres"
    assert body["specs"][0]["source"]["url"] == "https://www.volvocars.com/in/xc60/specs"
    assert len(body["features"]) == 1
    assert body["features"][0]["feature_key"] == "panoramic_roof"


def test_spec_filters_by_attribute(client: TestClient, variant: Variant) -> None:
    response = client.get(
        "/spec", params={"variant_id": variant.id, "attribute": "boot_space_litres"}
    )
    assert response.status_code == 200
    assert len(response.json()["specs"]) == 1


def test_spec_404s_for_unknown_variant(client: TestClient) -> None:
    response = client.get("/spec", params={"variant_id": 999})
    assert response.status_code == 404
