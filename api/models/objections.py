from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Objection(Base):
    __tablename__ = "objections"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)


class ObjectionFact(Base):
    """Links an objection to exactly one supporting fact row."""

    __tablename__ = "objection_facts"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN spec_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN feature_id IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN rating_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="objection_facts_exactly_one_fact",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    objection_id: Mapped[int] = mapped_column(ForeignKey("objections.id"), nullable=False)
    spec_id: Mapped[int | None] = mapped_column(ForeignKey("specs.id"))
    feature_id: Mapped[int | None] = mapped_column(ForeignKey("features.id"))
    rating_id: Mapped[int | None] = mapped_column(ForeignKey("safety_ratings.id"))
