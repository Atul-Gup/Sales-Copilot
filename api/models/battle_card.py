from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class BattleCard(Base):
    __tablename__ = "battle_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_a: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)
    variant_b: Mapped[int] = mapped_column(ForeignKey("variants.id"), nullable=False)
    content_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
