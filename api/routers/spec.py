"""`/spec` endpoint — thin HTTP wrapper over `api.services.spec_query`.

No LLM in this path (AGENTS.md rule 2). Query params, not a request body,
since this is a read-only lookup. The unfiltered spec lookup (no
`attribute` query param — the common case, and the one battle cards and
objection retrieval also make repeatedly for the same variant) goes through
`api.services.cache.SpecCache` (T6.2); a filtered lookup bypasses the cache
since it's a different, smaller query the cache doesn't key on.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.db import get_db
from api.services.cache import SpecCache
from api.services.spec_query import (
    CitedFeature,
    CitedSpec,
    VariantLabel,
    get_features_for_variant,
    get_specs_for_variant,
    list_variants,
)

router = APIRouter()

_SPEC_CACHE = SpecCache()


@router.get("/variants")
def variants(db: Session = Depends(get_db)) -> list[VariantLabel]:  # noqa: B008
    return list_variants(db)


@router.get("/spec")
def spec(
    variant_id: int,
    attribute: str | None = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[CitedSpec] | list[CitedFeature]]:
    if attribute is None:
        specs = _SPEC_CACHE.get(db, variant_id)
    else:
        specs = get_specs_for_variant(db, variant_id, attribute=attribute)
    features = get_features_for_variant(db, variant_id)
    if not specs and not features:
        raise HTTPException(status_code=404, detail="No specs or features found for variant")
    return {"specs": specs, "features": features}
