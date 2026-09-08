from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base
from api.models.vector_type import EmbeddingVector

# text-embedding-3-small's native dimensionality (api/llm/embeddings.py).
EMBEDDING_DIM = 1536


class Chunk(Base):
    """One chunk of a product document — every fact traces to a chunk
    instead of to a structured row (docs/ARCHITECTURE.md).

    `text` is stored alongside the vector so retrieval can cite and render
    the actual passage, not just locate it. `section` is nullable since not
    every extractable passage sits under a detectable heading.
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    document_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(EMBEDDING_DIM), nullable=False)
    section: Mapped[str | None] = mapped_column(String)
    page: Mapped[int | None] = mapped_column(Integer)
