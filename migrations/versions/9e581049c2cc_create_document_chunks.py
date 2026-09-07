"""create document_chunks

Revision ID: 9e581049c2cc
Revises: 1810e815db56
Create Date: 2026-09-06 13:20:00.000000

This table backs `api.models.chunk.DocumentChunk` (Corpus B narrative
documents — warranty terms, Euro NCAP reports — per docs/RETRIEVAL.md's
Corpus A/B split) and has existed in `api/models/` since T4.2a, but no
migration ever created it: every local test seeds its schema with
`Base.metadata.create_all(engine)` directly against SQLite (bypassing
Alembic entirely), so this gap was invisible until T7.4's first real
`alembic upgrade head` against live Postgres — the same class of bug as the
`rating_status` enum migration fixed alongside it.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from api.models.vector_type import EmbeddingVector

# revision identifiers, used by Alembic.
revision: str = '9e581049c2cc'
down_revision: str | Sequence[str] | None = '1810e815db56'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("document_title", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", EmbeddingVector(EMBEDDING_DIM), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("document_chunks")
