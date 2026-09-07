"""Structured spec lookups. Pure SQL against typed columns — no LLM in this path.

See AGENTS.md rule 1: a fact cannot reach a caller without its source attached.
That constraint lives in the response types below (`source` is a required field,
not `Source | None`), not in a docstring or a prompt.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Brand, CarModel, Feature, SafetyRating, Source, Spec, Variant


class SourceRef(BaseModel):
    """Enough of a source for a consultant to defend the fact it's attached to."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    publisher: str
    url: str
    document_title: str | None
    retrieved_at: datetime
    verified_at: datetime | None


class CitedSpec(BaseModel):
    """A spec fact. `source` is required — this type cannot represent an uncited fact."""

    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    attribute: str
    value_text: str | None
    value_num: Decimal | None
    unit: str | None
    verified: bool
    verified_at: datetime | None
    source: SourceRef


class CitedFeature(BaseModel):
    """A feature-availability fact. `source` is required, same as `CitedSpec`."""

    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    feature_key: str
    availability: str
    cost_paise: int | None
    source: SourceRef


class CitedSafetyRating(BaseModel):
    """A single-protocol safety rating fact. `source` is required, same as `CitedSpec`."""

    model_config = ConfigDict(from_attributes=True)

    model_id: int
    protocol: str
    year: int
    tested_variant: str
    status: str
    adult_score: Decimal
    child_score: Decimal
    vru_score: Decimal
    assist_score: Decimal
    source: SourceRef


def _cited_spec(spec: Spec, source: Source) -> CitedSpec:
    return CitedSpec(
        variant_id=spec.variant_id,
        attribute=spec.attribute,
        value_text=spec.value_text,
        value_num=spec.value_num,
        unit=spec.unit,
        verified=spec.verified,
        verified_at=spec.verified_at,
        source=SourceRef.model_validate(source),
    )


def _cited_feature(feature: Feature, source: Source) -> CitedFeature:
    return CitedFeature(
        variant_id=feature.variant_id,
        feature_key=feature.feature_key,
        availability=feature.availability,
        cost_paise=feature.cost_paise,
        source=SourceRef.model_validate(source),
    )


def _cited_safety_rating(rating: SafetyRating, source: Source) -> CitedSafetyRating:
    return CitedSafetyRating(
        model_id=rating.model_id,
        protocol=rating.protocol,
        year=rating.year,
        tested_variant=rating.tested_variant,
        status=rating.status,
        adult_score=rating.adult_score,
        child_score=rating.child_score,
        vru_score=rating.vru_score,
        assist_score=rating.assist_score,
        source=SourceRef.model_validate(source),
    )


def get_specs_for_variant(
    db: Session, variant_id: int, attribute: str | None = None
) -> list[CitedSpec]:
    """All spec facts for one variant, optionally filtered to a single attribute."""
    stmt = (
        select(Spec, Source)
        .join(Source, Spec.source_id == Source.id)
        .where(Spec.variant_id == variant_id)
    )
    if attribute is not None:
        stmt = stmt.where(Spec.attribute == attribute)
    rows = db.execute(stmt).all()
    return [_cited_spec(spec, source) for spec, source in rows]


def get_features_for_variant(
    db: Session, variant_id: int, availability: str | None = None
) -> list[CitedFeature]:
    """All feature-availability facts for one variant, optionally filtered by availability."""
    stmt = (
        select(Feature, Source)
        .join(Source, Feature.source_id == Source.id)
        .where(Feature.variant_id == variant_id)
    )
    if availability is not None:
        stmt = stmt.where(Feature.availability == availability)
    rows = db.execute(stmt).all()
    return [_cited_feature(feature, source) for feature, source in rows]


def get_safety_ratings_for_model(
    db: Session, model_id: int, protocol: str | None = None
) -> list[CitedSafetyRating]:
    """All safety-rating facts for one model, optionally filtered to a single protocol.

    Never compare rows across differing protocols — see AGENTS.md rule 4.
    """
    stmt = (
        select(SafetyRating, Source)
        .join(Source, SafetyRating.report_source_id == Source.id)
        .where(SafetyRating.model_id == model_id)
    )
    if protocol is not None:
        stmt = stmt.where(SafetyRating.protocol == protocol)
    rows = db.execute(stmt).all()
    return [_cited_safety_rating(rating, source) for rating, source in rows]


def find_variants_with_feature(
    db: Session,
    feature_key: str,
    availability: str = "standard",
    max_price_paise: int | None = None,
    model_name: str | None = None,
) -> list[CitedFeature]:
    """Variants with a given feature at a given availability, optionally capped by price
    and filtered to one model — e.g. "which variants have a panoramic roof under 70 lakh".
    """
    stmt = (
        select(Feature, Source)
        .join(Source, Feature.source_id == Source.id)
        .join(Variant, Feature.variant_id == Variant.id)
        .where(Feature.feature_key == feature_key, Feature.availability == availability)
    )
    if max_price_paise is not None:
        stmt = stmt.where(
            Variant.ex_showroom_paise.is_not(None), Variant.ex_showroom_paise <= max_price_paise
        )
    if model_name is not None:
        stmt = stmt.join(CarModel, Variant.model_id == CarModel.id).where(
            CarModel.name == model_name
        )
    rows = db.execute(stmt).all()
    return [_cited_feature(feature, source) for feature, source in rows]


class VariantLabel(BaseModel):
    """Enough to populate a variant picker (T7.2) — id plus a human label.
    Not a fact, same reasoning as `find_variants`: a variant's existence and
    name aren't cited claims, so no `source` field here.
    """

    id: int
    brand: str
    model: str
    variant_name: str


def list_variants(db: Session) -> list[VariantLabel]:
    """Every ingested variant with its brand/model name attached, for a
    comparison picker — T7.2 needs a way to choose two variants without
    the consultant typing raw variant ids.
    """
    stmt = (
        select(Variant, CarModel, Brand)
        .join(CarModel, Variant.model_id == CarModel.id)
        .join(Brand, CarModel.brand_id == Brand.id)
        .order_by(Brand.name, CarModel.name, Variant.name)
    )
    rows = db.execute(stmt).all()
    return [
        VariantLabel(id=variant.id, brand=brand.name, model=model.name, variant_name=variant.name)
        for variant, model, brand in rows
    ]


def find_variants(
    db: Session, model_name: str | None = None, brand_name: str | None = None
) -> list[Variant]:
    """Variant lookup by model and/or brand name. Not a fact — no source attached,
    since a variant's existence isn't itself a cited claim.
    """
    stmt = select(Variant).join(CarModel, Variant.model_id == CarModel.id)
    if model_name is not None:
        stmt = stmt.where(CarModel.name == model_name)
    if brand_name is not None:
        stmt = stmt.join(Brand, CarModel.brand_id == Brand.id).where(Brand.name == brand_name)
    return list(db.execute(stmt).scalars().all())
