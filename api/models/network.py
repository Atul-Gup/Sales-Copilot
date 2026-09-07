from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class ServiceCentre(Base):
    __tablename__ = "service_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)


class CityAlias(Base):
    """Alternate spellings for a canonical city name (Bangalore -> Bengaluru,
    Gurgaon -> Gurugram, ...), so a lookup by whatever a consultant types
    still finds service_centres rows stored under the canonical spelling.
    """

    __tablename__ = "city_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    canonical_city: Mapped[str] = mapped_column(String, nullable=False)


class ResaleEstimate(Base):
    __tablename__ = "resale_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    years: Mapped[int] = mapped_column(nullable=False)
    retained_pct: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    methodology: Mapped[str | None] = mapped_column(String)
