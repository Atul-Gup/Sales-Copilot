"""api/services/cache.py — read-time caches for battle cards and frequent
spec queries, invalidated by `verified_at` rather than a TTL alone (T6.2).

docs/ARCHITECTURE.md: "Comparisons for known pairs are generated offline and
served from cache." `api/services/battle_card.py` already builds that offline
half (`generate_battle_cards`); this module is the read-time half its own
docstring left for T6.2 — "not yet wired into `/compare` as a read-time
cache... left for when latency work (T6.2) needs it."

Two independent caches, both invalidated the same way: a `stale_after`
timestamp check first (cheap, no query), then a `max(verified_at)` check
against every relevant `Spec` row (a card or cached result can't be trusted
once the fact it was built from has been re-verified, even if `stale_after`
hasn't hit yet — that's what "invalidate on verified_at change" means: a
verified fact changing invalidates the cache immediately, not on the next
30-day cycle). A cache miss on either check falls back to the live
`compare.py` functions, never to stale data.

- `get_cached_battle_card` / `cached_compare_variants` /
  `cached_equipped_price_comparison` — the offline battle-card cache.
  `equipped_price_comparison` is directional (base vs. competitor), so a
  request in the opposite order than the card was generated in is treated
  as a miss rather than silently answering the wrong direction;
  `compare_variants`'s diff rows are symmetric and get their `variant_a`/
  `variant_b` swapped to match the requested order instead.
- `SpecCache` — an in-memory per-process cache for
  `spec_query.get_specs_for_variant`'s unfiltered (whole-variant) case, the
  "frequent spec queries" half of this task. Checking `max(verified_at)` is
  one indexed aggregate query — far cheaper than re-fetching and
  re-serializing every spec row — so a cache hit still costs a query, just a
  much smaller one, in exchange for a correctness guarantee a TTL alone
  can't give.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import BattleCard, Spec
from api.services.compare import EquippedPriceComparison, SpecDiffRow
from api.services.spec_query import CitedSpec, get_specs_for_variant


def _ensure_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _max_verified_at(db: Session, variant_id: int) -> datetime | None:
    return db.execute(
        select(func.max(Spec.verified_at)).where(Spec.variant_id == variant_id)
    ).scalar_one_or_none()


def _find_battle_card(
    db: Session, variant_a_id: int, variant_b_id: int
) -> tuple[BattleCard, bool] | None:
    """Look up a card in either stored order. Returns `(card, reversed)`,
    `reversed` being True when the caller's order is the opposite of how the
    card was generated (`generate_battle_cards` always stores
    `(volvo_variant, competitor_variant)`).
    """
    card = db.scalar(
        select(BattleCard).where(
            BattleCard.variant_a == variant_a_id, BattleCard.variant_b == variant_b_id
        )
    )
    if card is not None:
        return card, False
    card = db.scalar(
        select(BattleCard).where(
            BattleCard.variant_a == variant_b_id, BattleCard.variant_b == variant_a_id
        )
    )
    if card is not None:
        return card, True
    return None


def get_cached_battle_card(
    db: Session, variant_a_id: int, variant_b_id: int, *, now: datetime | None = None
) -> tuple[BattleCard, bool] | None:
    """A card for this pair, only if it exists, hasn't hit `stale_after`, and
    no spec backing either variant has been re-verified since it was
    generated. Returns `(card, reversed_order)`, or `None` on any miss — the
    caller should fall back to computing live.
    """
    found = _find_battle_card(db, variant_a_id, variant_b_id)
    if found is None:
        return None
    card, reversed_order = found

    # SQLite (used by every in-memory test fixture and by this module's own
    # docstring examples) doesn't preserve tzinfo on round-trip even for a
    # `DateTime(timezone=True)` column — normalize to aware-UTC before
    # comparing, the same fix `test_battle_card.py` already applies at the
    # call site for `generated_at`.
    reference = now if now is not None else datetime.now(UTC)
    stale_after = _ensure_aware(card.stale_after)
    generated_at = _ensure_aware(card.generated_at)
    if reference > stale_after:
        return None

    for variant_id in (variant_a_id, variant_b_id):
        latest_verified_at = _max_verified_at(db, variant_id)
        if latest_verified_at is not None and _ensure_aware(latest_verified_at) > generated_at:
            return None

    return card, reversed_order


def cached_compare_variants(
    db: Session, variant_a_id: int, variant_b_id: int, *, now: datetime | None = None
) -> list[SpecDiffRow] | None:
    found = get_cached_battle_card(db, variant_a_id, variant_b_id, now=now)
    if found is None:
        return None
    card, reversed_order = found
    spec_diff = cast(list[dict[str, Any]], card.content_json["spec_diff"])
    rows = [SpecDiffRow.model_validate(row) for row in spec_diff]
    if not reversed_order:
        return rows
    return [
        SpecDiffRow(
            attribute=r.attribute, unit=r.unit, variant_a=r.variant_b, variant_b=r.variant_a
        )
        for r in rows
    ]


def cached_equipped_price_comparison(
    db: Session, base_variant_id: int, competitor_variant_id: int, *, now: datetime | None = None
) -> EquippedPriceComparison | None:
    found = get_cached_battle_card(db, base_variant_id, competitor_variant_id, now=now)
    if found is None:
        return None
    card, reversed_order = found
    if reversed_order:
        # Directional: the card was generated the other way around, so it
        # can't answer this request — a miss, not a wrong-direction answer.
        return None
    return EquippedPriceComparison.model_validate(card.content_json["equipped_price"])


class SpecCache:
    """In-memory per-process cache for `spec_query.get_specs_for_variant`'s
    unfiltered case. Keyed by `(database identity, variant id)` — not just
    variant id — so that two different databases sharing the same
    autoincrement id space (every test module's in-memory SQLite fixture
    starts variant ids at 1) can never serve one another's cached rows; in
    production, where one engine backs the whole process, this reduces to
    exactly "keyed by variant id." A cached entry is served only while
    `max(verified_at)` for that variant's specs is unchanged from
    cache-write time, so a re-verified spec is visible on the very next call
    rather than after some fixed TTL.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[int, int], tuple[datetime | None, list[CitedSpec]]] = {}

    def _key(self, db: Session, variant_id: int) -> tuple[int, int]:
        return (id(db.get_bind()), variant_id)

    def get(self, db: Session, variant_id: int) -> list[CitedSpec]:
        key = self._key(db, variant_id)
        latest_verified_at = _max_verified_at(db, variant_id)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == latest_verified_at:
            return cached[1]
        specs = get_specs_for_variant(db, variant_id)
        self._cache[key] = (latest_verified_at, specs)
        return specs

    def invalidate(self, db: Session | None = None, variant_id: int | None = None) -> None:
        if db is None:
            self._cache.clear()
        elif variant_id is None:
            engine_id = id(db.get_bind())
            for key in [k for k in self._cache if k[0] == engine_id]:
                del self._cache[key]
        else:
            self._cache.pop(self._key(db, variant_id), None)
