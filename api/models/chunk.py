from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.models.base import Base
from api.models.vector_type import EmbeddingVector

# text-embedding-3-small's native dimensionality (api/llm/embeddings.py).
EMBEDDING_DIM = 1536


class DocumentChunk(Base):
    """One chunk of a Corpus B narrative document (warranty terms, a full
    Euro NCAP report) — see docs/RETRIEVAL.md's Corpus A/B split. Every row
    carries a `source_id`, the same rule ingest/*.py already applies to
    Corpus A fact rows: a chunk with no traceable source is not created.

    `section` is nullable because pypdf's text extraction does not reliably
    expose heading structure for these documents — recording a fabricated
    section label would be worse than recording none.
    """

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    document_title: Mapped[str] = mapped_column(String, nullable=False)
    section: Mapped[str | None] = mapped_column(String)
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(EMBEDDING_DIM), nullable=False)
