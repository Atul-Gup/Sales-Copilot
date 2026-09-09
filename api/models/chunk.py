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

    `document_id` is nullable (added for the objection-handling guide,
    `ingest/objection_guide.py`): every one of the original five product
    documents is about exactly one model, but that guide's 3 "General"
    items (value framing, feature availability, missing-info guidance) are
    cross-cutting consultant guidance, not a fact about any single model —
    forcing them onto one model's `document_id` would be a fabricated
    association, worse than leaving it unset. Every other chunk still sets
    it; callers reading `document_id` (e.g. `pipeline.py::_model_labels`)
    must handle `None` rather than assume every chunk belongs to a model.

    `external_id` (also added for the objection-handling guide) is the
    pre-existing item ID the source document itself assigns (e.g.
    "EX30_001") — nullable because the five original documents were never
    pre-chunked with their own IDs; only content ingested from an
    already-chunked source sets this.
    """

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("models.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(EMBEDDING_DIM), nullable=False)
    section: Mapped[str | None] = mapped_column(String)
    page: Mapped[int | None] = mapped_column(Integer)
    external_id: Mapped[str | None] = mapped_column(String)
