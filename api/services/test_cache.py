"""api/services/test_cache.py — battle-card and spec-query caches (T6.2)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from api.models import Base, Brand, CarModel, Feature, Source, Spec, Variant
from api.services.battle_card import generate_battle_cards
from api.services.cache import (
    SpecCache,
    cached_compare_variants,
    cached_equipped_price_comparison,
    get_cached_battle_card,
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
                verified_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            Spec(
                variant_id=v_b.id,
                attribute="boot_space_litres",
                value_num=550,
                unit="litres",
                source_id=bmw_src.id,
                verified=True,
                verified_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
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
        ]
    )
    session.flush()
    return v_a, v_b


def test_get_cached_battle_card_hits_after_generation(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    generate_battle_cards(session)

    found = get_cached_battle_card(session, v_a.id, v_b.id)
    assert found is not None
    card, reversed_order = found
    assert card.variant_a == v_a.id
    assert reversed_order is False


def test_get_cached_battle_card_misses_for_uncached_pair(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, _v_b = variants
    assert get_cached_battle_card(session, v_a.id, 999) is None


def test_get_cached_battle_card_misses_once_stale_after_has_passed(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    now = datetime(2026, 1, 1, tzinfo=UTC)
    generate_battle_cards(session, now=now, stale_after=timedelta(days=1))

    assert get_cached_battle_card(session, v_a.id, v_b.id, now=now + timedelta(hours=1)) is not None
    assert get_cached_battle_card(session, v_a.id, v_b.id, now=now + timedelta(days=2)) is None


def test_get_cached_battle_card_misses_once_a_spec_is_reverified(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    generation_time = datetime(2026, 1, 1, tzinfo=UTC)
    generate_battle_cards(session, now=generation_time)
    session.commit()

    assert get_cached_battle_card(session, v_a.id, v_b.id, now=generation_time) is not None

    spec = session.query(Spec).filter(Spec.variant_id == v_a.id).first()
    assert spec is not None
    spec.verified_at = generation_time + timedelta(days=1)
    session.flush()

    assert get_cached_battle_card(session, v_a.id, v_b.id, now=generation_time) is None


def test_cached_compare_variants_swaps_rows_for_reversed_order(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    generate_battle_cards(session)

    forward = cached_compare_variants(session, v_a.id, v_b.id)
    reversed_rows = cached_compare_variants(session, v_b.id, v_a.id)
    assert forward is not None
    assert reversed_rows is not None

    forward_row = next(r for r in forward if r.attribute == "boot_space_litres")
    reversed_row = next(r for r in reversed_rows if r.attribute == "boot_space_litres")
    assert forward_row.variant_a is not None
    assert reversed_row.variant_a is not None
    assert forward_row.variant_a.value_num == reversed_row.variant_b.value_num  # type: ignore[union-attr]
    assert forward_row.variant_b.value_num == reversed_row.variant_a.value_num  # type: ignore[union-attr]


def test_cached_equipped_price_comparison_misses_for_reversed_order(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, v_b = variants
    generate_battle_cards(session)

    assert cached_equipped_price_comparison(session, v_a.id, v_b.id) is not None
    assert cached_equipped_price_comparison(session, v_b.id, v_a.id) is None


def test_spec_cache_returns_cached_result_until_verified_at_changes(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, _v_b = variants
    cache = SpecCache()

    first = cache.get(session, v_a.id)
    assert len(first) == 1

    spec = session.query(Spec).filter(Spec.variant_id == v_a.id).first()
    assert spec is not None
    session.add(
        Spec(
            variant_id=v_a.id,
            attribute="ground_clearance_mm",
            value_num=216,
            unit="mm",
            source_id=spec.source_id,
            verified=True,
        )
    )
    session.flush()

    # verified_at unchanged (new row has no verified_at) -> still cached, 1 row.
    assert len(cache.get(session, v_a.id)) == 1

    spec.verified_at = datetime(2027, 1, 1, tzinfo=UTC)
    session.flush()

    # verified_at changed -> cache miss, both rows now returned.
    assert len(cache.get(session, v_a.id)) == 2


def test_spec_cache_does_not_leak_across_different_databases(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, _v_b = variants
    cache = SpecCache()
    cache.get(session, v_a.id)

    other_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(other_engine)
    with Session(other_engine) as other_db:
        # Same variant id, completely different (empty) database.
        assert cache.get(other_db, v_a.id) == []


def test_spec_cache_invalidate_clears_entries(
    session: Session, variants: tuple[Variant, Variant]
) -> None:
    v_a, _v_b = variants
    cache = SpecCache()
    cache.get(session, v_a.id)
    cache.invalidate(session, v_a.id)
    assert cache._cache == {}
