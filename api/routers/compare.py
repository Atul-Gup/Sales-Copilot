"""`/compare` endpoint — thin HTTP wrapper over `api.services.compare`.

Checks the offline battle-card cache first (T6.2, `api.services.cache`) and
falls back to a live `compare.py` call on any cache miss — an uncached pair,
a stale card, or a card whose underlying specs were re-verified since it was
generated. The response shape is identical either way, since the cache
stores the exact same Pydantic models this router already returns.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db import get_db
from api.services.cache import cached_compare_variants, cached_equipped_price_comparison
from api.services.compare import (
    EquippedPriceComparison,
    SpecDiffRow,
    compare_variants,
    equipped_price_comparison,
)

router = APIRouter()


@router.get("/compare")
def compare(
    variant_a_id: int,
    variant_b_id: int,
    db: Session = Depends(get_db),  # noqa: B008
) -> list[SpecDiffRow]:
    rows = cached_compare_variants(db, variant_a_id, variant_b_id)
    if rows is None:
        rows = compare_variants(db, variant_a_id, variant_b_id)
    if not rows:
        raise HTTPException(status_code=404, detail="No specs found for either variant")
    return rows


@router.get("/compare/equipped-price")
def equipped_price(
    base_variant_id: int,
    competitor_variant_id: int,
    db: Session = Depends(get_db),  # noqa: B008
) -> EquippedPriceComparison:
    cached = cached_equipped_price_comparison(db, base_variant_id, competitor_variant_id)
    if cached is not None:
        return cached
    return equipped_price_comparison(db, base_variant_id, competitor_variant_id)
