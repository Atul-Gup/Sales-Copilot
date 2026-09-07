from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from api.models import Base, BattleCard, Brand, CarModel, Feature, Source, Spec, Variant
from api.services.battle_card import generate_battle_cards


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
def catalog(session: Session) -> dict[str, Variant]:
    src = Source(
        kind="oem_site",
        publisher="Volvo Cars India",
        url="https://www.volvocars.com/in/xc60/specs",
        retrieved_at=datetime.now(UTC),
    )
    session.add(src)
    session.flush()

    volvo = Brand(name="Volvo", segment="luxury")
    bmw = Brand(name="BMW", segment="luxury")
    audi = Brand(name="Audi", segment="luxury")
    session.add_all([volvo, bmw, audi])
    session.flush()

    xc60 = CarModel(brand_id=volvo.id, name="XC60", body_type="suv", status="active")
    ex30 = CarModel(brand_id=volvo.id, name="EX30", body_type="suv", status="active")
    x3 = CarModel(brand_id=bmw.id, name="X3", body_type="suv", status="active")
    a4 = CarModel(brand_id=audi.id, name="A4", body_type="sedan", status="active")
    session.add_all([xc60, ex30, x3, a4])
    session.flush()

    xc60_variant = Variant(
        model_id=xc60.id,
        name="XC60 B5 Inscription",
        powertrain="mild_hybrid_petrol",
        ex_showroom_paise=6_490_000_00,
        price_source_id=src.id,
    )
    ex30_variant = Variant(
        model_id=ex30.id,
        name="EX30 Pure Electric",
        powertrain="electric",
    )
    x3_variant = Variant(
        model_id=x3.id,
        name="X3 xDrive20d",
        powertrain="diesel",
        ex_showroom_paise=6_590_000_00,
        price_source_id=src.id,
    )
    # Different body type (sedan) — should never pair with an SUV.
    a4_variant = Variant(model_id=a4.id, name="A4 Premium Plus", powertrain="petrol")
    session.add_all([xc60_variant, ex30_variant, x3_variant, a4_variant])
    session.flush()

    session.add_all(
        [
            Spec(
                variant_id=xc60_variant.id,
                attribute="boot_space_litres",
                value_num=709,
                unit="litres",
                source_id=src.id,
            ),
            Spec(
                variant_id=x3_variant.id,
                attribute="boot_space_litres",
                value_num=550,
                unit="litres",
                source_id=src.id,
            ),
        ]
    )
    session.add_all(
        [
            Feature(
                variant_id=xc60_variant.id,
                feature_key="panoramic_roof",
                availability="standard",
                source_id=src.id,
            ),
            Feature(
                variant_id=x3_variant.id,
                feature_key="panoramic_roof",
                availability="optional",
                cost_paise=1_20_000_00,
                source_id=src.id,
            ),
        ]
    )
    session.flush()

    return {"xc60": xc60_variant, "ex30": ex30_variant, "x3": x3_variant, "a4": a4_variant}


def test_generates_only_same_body_type_volvo_vs_competitor_pairs(
    session: Session, catalog: dict[str, Variant]
) -> None:
    cards = generate_battle_cards(session, now=datetime(2026, 9, 4, tzinfo=UTC))
    session.flush()

    pairs = {(card.variant_a, card.variant_b) for card in cards}
    assert pairs == {(catalog["xc60"].id, catalog["x3"].id)}


def test_battle_card_content_matches_live_compare_output(
    session: Session, catalog: dict[str, Variant]
) -> None:
    cards = generate_battle_cards(session, now=datetime(2026, 9, 4, tzinfo=UTC))
    session.flush()
    content: dict[str, Any] = cards[0].content_json

    spec_diff = content["spec_diff"]
    boot_row = next(row for row in spec_diff if row["attribute"] == "boot_space_litres")
    assert float(boot_row["variant_a"]["value_num"]) == 709
    assert float(boot_row["variant_b"]["value_num"]) == 550

    equipped_price = content["equipped_price"]
    assert equipped_price["added_cost_paise"] == 1_20_000_00
    assert equipped_price["competitor_equipped_price_paise"] == 6_590_000_00 + 1_20_000_00


def test_generate_sets_generated_at_and_stale_after(
    session: Session, catalog: dict[str, Variant]
) -> None:
    now = datetime(2026, 9, 4, tzinfo=UTC)
    cards = generate_battle_cards(session, now=now)

    assert cards[0].generated_at == now
    assert cards[0].stale_after == now + timedelta(days=30)


def test_regenerating_updates_the_existing_row_instead_of_duplicating(
    session: Session, catalog: dict[str, Variant]
) -> None:
    first_run = datetime(2026, 9, 4, tzinfo=UTC)
    second_run = datetime(2026, 10, 4, tzinfo=UTC)

    generate_battle_cards(session, now=first_run)
    session.commit()
    generate_battle_cards(session, now=second_run)
    session.commit()

    rows = session.execute(select(BattleCard)).scalars().all()
    assert len(rows) == 1
    assert rows[0].generated_at.replace(tzinfo=UTC) == second_run
