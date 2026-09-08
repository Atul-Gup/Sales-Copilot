from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base


class Model(Base):
    """One car model this system can answer about — e.g. Volvo XC60, BMW X3.

    No separate variant/spec tables (docs/ARCHITECTURE.md): facts about a
    model live in the chunks of its product document, not in structured
    columns here.
    """

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
