"""Structured spec diff between two variants. Pure SQL, no LLM — same rule as
`spec_query.py`. Every row that carries a value carries that value's source;
a row where only one side has data leaves the other side `None` rather than
inventing or omitting the fact.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from api.models import Variant
from api.services.spec_query import (
    CitedSpec,
    SourceRef,
    get_features_for_variant,
    get_specs_for_variant,
)


class DiffValue(BaseModel):
    """One side of a comparison row. `source` is required, same as `CitedSpec`."""

    model_config = ConfigDict(from_attributes=True)

    value_text: str | None
    value_num: Decimal | None
    source: SourceRef


class SpecDiffRow(BaseModel):
    """One attribute, both variants' values (either may be absent), unit shared."""

    attribute: str
    unit: str | None
    variant_a: DiffValue | None
    variant_b: DiffValue | None


def _diff_value(spec: CitedSpec) -> DiffValue:
    return DiffValue(value_text=spec.value_text, value_num=spec.value_num, source=spec.source)


def compare_variants(db: Session, variant_a_id: int, variant_b_id: int) -> list[SpecDiffRow]:
    """Attribute-by-attribute diff of two variants' cited specs.

    Attributes present on only one side still get a row, with the other side
    `None` — that absence is itself information a consultant needs, not a
    reason to drop the row.
    """
    specs_a = {s.attribute: s for s in get_specs_for_variant(db, variant_a_id)}
    specs_b = {s.attribute: s for s in get_specs_for_variant(db, variant_b_id)}

    rows = []
    for attribute in sorted(set(specs_a) | set(specs_b)):
        spec_a = specs_a.get(attribute)
        spec_b = specs_b.get(attribute)
        unit = spec_a.unit if spec_a is not None else (spec_b.unit if spec_b is not None else None)
        rows.append(
            SpecDiffRow(
                attribute=attribute,
                unit=unit,
                variant_a=_diff_value(spec_a) if spec_a is not None else None,
                variant_b=_diff_value(spec_b) if spec_b is not None else None,
            )
        )
    return rows


class IncludedItem(BaseModel):
    """A feature standard on the base variant that costs extra on the competitor."""

    feature_key: str
    cost_paise: int
    source: SourceRef


class UnmatchableItem(BaseModel):
    """A feature standard on the base variant that the competitor can't be brought
    up to — no listed cost, or not offered at all. Reported, never silently dropped:
    an equipped price that omits these would understate the gap it's meant to show.
    """

    feature_key: str
    reason: Literal["not_offered", "cost_not_sourced"]


class EquippedPriceComparison(BaseModel):
    """Competitor's ex-showroom price plus the cost of matching the base variant's
    standard kit, so the two prices are for equivalent equipment rather than
    whatever trim level each brand happens to call its headline number.
    """

    base_variant_id: int
    competitor_variant_id: int
    base_price_paise: int | None
    competitor_base_price_paise: int | None
    added_cost_paise: int
    competitor_equipped_price_paise: int | None
    included_items: list[IncludedItem]
    unmatchable_items: list[UnmatchableItem]


def equipped_price_comparison(
    db: Session, base_variant_id: int, competitor_variant_id: int
) -> EquippedPriceComparison:
    """Price the competitor variant up to the base variant's standard equipment level.

    For every feature standard on `base_variant_id`, look at the same feature on
    `competitor_variant_id`: standard there costs nothing extra; optional there
    adds its `cost_paise` (and is reported as an `IncludedItem`); anything
    unavailable, or optional with no sourced cost, can't be matched at any known
    price and is reported as `UnmatchableItem` instead of being ignored.
    """
    base_features = {f.feature_key: f for f in get_features_for_variant(db, base_variant_id)}
    base_standard_keys = [key for key, f in base_features.items() if f.availability == "standard"]
    competitor_features = {
        f.feature_key: f for f in get_features_for_variant(db, competitor_variant_id)
    }

    included: list[IncludedItem] = []
    unmatchable: list[UnmatchableItem] = []
    added_cost_paise = 0

    for key in sorted(base_standard_keys):
        competitor_feature = competitor_features.get(key)
        if competitor_feature is None or competitor_feature.availability == "unavailable":
            unmatchable.append(UnmatchableItem(feature_key=key, reason="not_offered"))
        elif competitor_feature.availability == "standard":
            continue
        elif competitor_feature.cost_paise is None:
            unmatchable.append(UnmatchableItem(feature_key=key, reason="cost_not_sourced"))
        else:
            added_cost_paise += competitor_feature.cost_paise
            included.append(
                IncludedItem(
                    feature_key=key,
                    cost_paise=competitor_feature.cost_paise,
                    source=competitor_feature.source,
                )
            )

    base_variant = db.get(Variant, base_variant_id)
    competitor_variant = db.get(Variant, competitor_variant_id)
    base_price_paise = base_variant.ex_showroom_paise if base_variant is not None else None
    competitor_base_price_paise = (
        competitor_variant.ex_showroom_paise if competitor_variant is not None else None
    )
    competitor_equipped_price_paise = (
        competitor_base_price_paise + added_cost_paise
        if competitor_base_price_paise is not None
        else None
    )

    return EquippedPriceComparison(
        base_variant_id=base_variant_id,
        competitor_variant_id=competitor_variant_id,
        base_price_paise=base_price_paise,
        competitor_base_price_paise=competitor_base_price_paise,
        added_cost_paise=added_cost_paise,
        competitor_equipped_price_paise=competitor_equipped_price_paise,
        included_items=included,
        unmatchable_items=unmatchable,
    )
