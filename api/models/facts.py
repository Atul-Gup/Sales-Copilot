from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base

FeatureAvailability = Enum(
    "standard", "optional", "unavailable", name="feature_availability", native_enum=True
)
SafetyProtocol = Enum(
    "euro_ncap", "bharat_ncap", "global_ncap", name="safety_protocol", native_enum=True
)
RatingStatus = Enum("current", "expired", name="rating_status", native_enum=True)


class Spec(Base):
    """A verifiable fact about a variant. Every row must cite a source — see AGENTS.md rule 1."""

    __tablename__ = "specs"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)
    attribute: Mapped[str] = mapped_column(String, nullable=False)
    value_text: Mapped[str | None] = mapped_column(String)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_page: Mapped[int | None] = mapped_column()
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feature(Base):
    """Standard/optional/unavailable status for a variant. Every row must cite a source."""

    __tablename__ = "features"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)
    feature_key: Mapped[str] = mapped_column(String, nullable=False)
    availability: Mapped[str] = mapped_column(FeatureAvailability, nullable=False)
    cost_paise: Mapped[int | None] = mapped_column(BigInteger)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_page: Mapped[int | None] = mapped_column()


class SafetyRating(Base):
    """A single-protocol safety score. Never compare rows across differing protocols
    or across differing years/tested variants within the same protocol — see
    docs/CORPUS.md's cross_protocol_safety extension.
    """

    __tablename__ = "safety_ratings"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    protocol: Mapped[str] = mapped_column(SafetyProtocol, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    tested_variant: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(RatingStatus, nullable=False)
    adult_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    child_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    vru_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    assist_score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    report_source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
