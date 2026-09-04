from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)


class CarModel(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    body_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    powertrain: Mapped[str] = mapped_column(String, nullable=False)
    # Nullable: official India spec/brochure PDFs frequently omit ex-showroom
    # price entirely (dealer-quoted, not published). A variant is real even
    # when its price is not yet sourced; a null price must never be displayed
    # or treated as zero by downstream code.
    ex_showroom_paise: Mapped[int | None] = mapped_column(BigInteger)
    price_source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    launched_on: Mapped[date | None] = mapped_column(Date)
