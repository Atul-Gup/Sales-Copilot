from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class ServiceCentre(Base):
    """Structured, separate from the chunked corpus — queried by direct
    city lookup, not retrieval (docs/ARCHITECTURE.md).
    """

    __tablename__ = "service_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String, nullable=False)
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
