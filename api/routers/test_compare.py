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
def variants(session: Session) -> tuple[Variant, Variant]:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    bmw_src = Source(
        kind="oem_site",
        publisher="BMW India",
        url="https://www.bmw.in/x3/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add_all([src, bmw_src])
    session.flush()

    volvo = Brand(name="Volvo", segment="luxury")
    bmw = Brand(name="BMW", segment="luxury")
    session.add_all([volvo, bmw])
    session.flush()

    xc60 = CarModel(brand_id=volvo.id, name="XC60", body_type="suv", status="active")
    x3 = CarModel(brand_id=bmw.id, name="X3", body_type="suv", status="active")
    session.add_all([xc60, x3])
    session.flush()

    v_a = Variant(
        model_id=xc60.id,
        name="XC60 B5 Inscription",
        powertrain="mild_hybrid_petrol",
        ex_showroom_paise=6_490_000_00,
        price_source_id=src.id,
    )
    v_b = Variant(
        model_id=x3.id,
        name="X3 xDrive20d",
        powertrain="diesel",
        ex_showroom_paise=6_590_000_00,
        price_source_id=bmw_src.id,
    )
    session.add_all([v_a, v_b])
    session.flush()

    session.add_all(
        [
            Spec(
                variant_id=v_a.id,
                attribute="boot_space_litres",
                value_num=709,
                unit="litres",
                source_id=src.id,
                verified=True,
            ),
            Spec(
                variant_id=v_b.id,
                attribute="boot_space_litres",
                value_num=550,
                unit="litres",
                source_id=bmw_src.id,
                verified=True,
            ),
            # Volvo-only attribute — should still produce a row, with variant_b null.
            Spec(
                variant_id=v_a.id,
                attribute="ground_clearance_mm",
                value_num=216,
                unit="mm",
                source_id=src.id,
                verified=True,
            ),
        ]
    )
    session.flush()

    session.add_all(
        [
            # Standard on Volvo, optional (with a sourced cost) on BMW — matchable.
            Feature(
                variant_id=v_a.id,
                feature_key="panoramic_roof",
                availability="standard",
                source_id=src.id,
            ),
            Feature(
                variant_id=v_b.id,
                feature_key="panoramic_roof",
                availability="optional",
                cost_paise=1_20_000_00,
                source_id=bmw_src.id,
            ),
            # Standard on Volvo, optional on BMW but with no sourced cost — unmatchable.
            Feature(
                variant_id=v_a.id,
                feature_key="heated_seats",
                availability="standard",
                source_id=src.id,
            ),
            Feature(
                variant_id=v_b.id,
                feature_key="heated_seats",
                availability="optional",
                cost_paise=None,
                source_id=bmw_src.id,
            ),
            # Standard on Volvo, simply not offered on BMW — unmatchable.
            Feature(
                variant_id=v_a.id,
                feature_key="air_suspension",
                availability="standard",
                source_id=src.id,
            ),
            # Standard on both — no added cost.
            Feature(
                variant_id=v_a.id,
                feature_key="adaptive_cruise_control",
                availability="standard",
                source_id=src.id,
            ),
            Feature(
                variant_id=v_b.id,
                feature_key="adaptive_cruise_control",
                availability="standard",
                source_id=bmw_src.id,
            ),
        ]
    )
    session.flush()
    return v_a, v_b


@pytest.fixture
def client(session: Session) -> Generator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_compare_returns_diff_rows_with_sources(
    client: TestClient, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    response = client.get("/compare", params={"variant_a_id": v_a.id, "variant_b_id": v_b.id})
    assert response.status_code == 200
    rows = {row["attribute"]: row for row in response.json()}

    boot = rows["boot_space_litres"]
    assert float(boot["variant_a"]["value_num"]) == 709
    assert boot["variant_a"]["source"]["publisher"] == "Volvo Cars India"
    assert float(boot["variant_b"]["value_num"]) == 550
    assert boot["variant_b"]["source"]["publisher"] == "BMW India"

    clearance = rows["ground_clearance_mm"]
    assert float(clearance["variant_a"]["value_num"]) == 216
    assert clearance["variant_b"] is None


def test_compare_serves_from_a_cached_battle_card_when_one_exists(
    client: TestClient, session: Session, variants: tuple[Variant, Variant]
) -> None:
    from api.services.battle_card import generate_battle_cards

    v_a, v_b = variants
    generate_battle_cards(session)

    response = client.get("/compare", params={"variant_a_id": v_a.id, "variant_b_id": v_b.id})
    assert response.status_code == 200
    rows = {row["attribute"]: row for row in response.json()}
    assert float(rows["boot_space_litres"]["variant_a"]["value_num"]) == 709


def test_equipped_price_serves_from_a_cached_battle_card_when_one_exists(
    client: TestClient, session: Session, variants: tuple[Variant, Variant]
) -> None:
    from api.services.battle_card import generate_battle_cards

    v_a, v_b = variants
    generate_battle_cards(session)

    response = client.get(
        "/compare/equipped-price",
        params={"base_variant_id": v_a.id, "competitor_variant_id": v_b.id},
    )
    assert response.status_code == 200
    assert response.json()["competitor_equipped_price_paise"] == 6_590_000_00 + 1_20_000_00


def test_compare_404s_when_neither_variant_has_specs(client: TestClient) -> None:
    response = client.get("/compare", params={"variant_a_id": 998, "variant_b_id": 999})
    assert response.status_code == 404


def test_equipped_price_sums_optional_costs_for_standard_kit(
    client: TestClient, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    response = client.get(
        "/compare/equipped-price",
        params={"base_variant_id": v_a.id, "competitor_variant_id": v_b.id},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["base_price_paise"] == 6_490_000_00
    assert body["competitor_base_price_paise"] == 6_590_000_00
    assert body["added_cost_paise"] == 1_20_000_00
    assert body["competitor_equipped_price_paise"] == 6_590_000_00 + 1_20_000_00

    included = {item["feature_key"]: item for item in body["included_items"]}
    assert included.keys() == {"panoramic_roof"}
    assert included["panoramic_roof"]["cost_paise"] == 1_20_000_00
    assert included["panoramic_roof"]["source"]["publisher"] == "BMW India"

    unmatchable = {item["feature_key"]: item["reason"] for item in body["unmatchable_items"]}
    assert unmatchable == {
        "heated_seats": "cost_not_sourced",
        "air_suspension": "not_offered",
    }
