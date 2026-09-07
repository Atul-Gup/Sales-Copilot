"""Offline battle card generation for the main Volvo-versus-German pairs.

Per docs/ARCHITECTURE.md: "Comparisons for known pairs are generated offline
and served from cache" — the comparison path never runs `compare_variants`/
`equipped_price_comparison` live. This module is the offline half: it runs
those same pure-SQL functions once, per pair, and freezes the result as
`content_json` on a `battle_cards` row with a `stale_after` timestamp.

A pair is a curated (Volvo model, competitor model) entry in `MODEL_PAIRS`
below, not an inferred one — `body_type` alone is not a reliable "same
segment" signal (EX30 and X3 are both `body_type='suv'` but a compact EV
and a mid-size ICE SUV are not the comparison a consultant needs). Per
T1.5, XC60 has all three German competitors ingested; EX30 has none yet
(the corpus's BMW iX1 source turned out to be the X1 LWB, not the iX1 EV),
so it is deliberately absent from `MODEL_PAIRS` rather than paired wrong.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import BattleCard, CarModel, Variant
from api.services.compare import compare_variants, equipped_price_comparison

STALE_AFTER = timedelta(days=30)
"""How long a generated card is trusted before it needs regenerating.

No corpus-mandated figure exists for this; 30 days matches the general
"re-verify periodically" cadence implied by `verified_at` elsewhere in the
schema. Revisit if ingested facts turn out to change faster than that."""

MODEL_PAIRS: list[tuple[str, str]] = [
    ("XC60", "X3"),
    ("XC60", "GLC"),
    ("XC60", "Q5"),
]
"""(Volvo model name, competitor model name). Update this list, not the
matching logic, as new competitors get ingested (T1.5) or new Volvo models
join the lineup."""


def _variants_by_model_name(db: Session, model_name: str) -> list[Variant]:
    return list(
        db.execute(
            select(Variant)
            .join(CarModel, Variant.model_id == CarModel.id)
            .where(CarModel.name == model_name)
        )
        .scalars()
        .all()
    )


def _volvo_vs_competitor_pairs(db: Session) -> list[tuple[Variant, Variant]]:
    """Every (Volvo variant, competitor variant) pair for the curated `MODEL_PAIRS`.

    A model absent from the database (not yet ingested) simply contributes no
    variants and therefore no pairs — not an error, since T1.5 already
    documents which competitors aren't in yet.
    """
    pairs: list[tuple[Variant, Variant]] = []
    for volvo_model_name, competitor_model_name in MODEL_PAIRS:
        volvo_variants = _variants_by_model_name(db, volvo_model_name)
        competitor_variants = _variants_by_model_name(db, competitor_model_name)
        pairs.extend(
            (volvo, competitor) for volvo in volvo_variants for competitor in competitor_variants
        )
    return pairs


def build_battle_card_content(
    db: Session, variant_a_id: int, variant_b_id: int
) -> dict[str, object]:
    """The precomputed payload: spec diff and equipped-price comparison, both
    already-cited per `compare.py` — a battle card can't misplace a source
    because it's frozen output of functions that can't produce uncited rows.
    """
    spec_diff = compare_variants(db, variant_a_id, variant_b_id)
    equipped_price = equipped_price_comparison(db, variant_a_id, variant_b_id)
    return {
        "spec_diff": [row.model_dump(mode="json") for row in spec_diff],
        "equipped_price": equipped_price.model_dump(mode="json"),
    }


def generate_battle_cards(
    db: Session, now: datetime | None = None, stale_after: timedelta = STALE_AFTER
) -> list[BattleCard]:
    """Generate (or refresh) a battle card for every Volvo-vs-competitor pair.

    Idempotent: a pair that already has a card gets that row's content and
    timestamps overwritten in place rather than a duplicate inserted.
    """
    generated_at = now if now is not None else datetime.now(UTC)
    cards = []

    for volvo_variant, competitor_variant in _volvo_vs_competitor_pairs(db):
        content = build_battle_card_content(db, volvo_variant.id, competitor_variant.id)
        card = db.scalar(
            select(BattleCard).where(
                BattleCard.variant_a == volvo_variant.id,
                BattleCard.variant_b == competitor_variant.id,
            )
        )
        if card is None:
            card = BattleCard(variant_a=volvo_variant.id, variant_b=competitor_variant.id)
            db.add(card)
        card.content_json = content
        card.generated_at = generated_at
        card.stale_after = generated_at + stale_after
        cards.append(card)

    return cards


def main() -> None:
    from api.db import SessionLocal

    with SessionLocal() as session:
        cards = generate_battle_cards(session)
        session.commit()
        print(f"Generated {len(cards)} battle card(s).")  # noqa: T201


if __name__ == "__main__":
    main()
