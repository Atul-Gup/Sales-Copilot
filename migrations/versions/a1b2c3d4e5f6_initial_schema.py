"""initial schema — sources, models, chunks, service_centres, city_aliases

Per docs/ARCHITECTURE.md: no specs/features/safety_ratings/battle_card/
resale_estimate tables. Every fact traces to a chunk (source_id NOT NULL)
instead of to a structured row.

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-09-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("document_title", sa.String(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checksum", sa.String(), nullable=True),
    )

    op.create_table(
        "models",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("models.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
    )

    op.create_table(
        "service_centres",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand", sa.String(), nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
    )

    op.create_table(
        "city_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(), nullable=False, unique=True),
        sa.Column("canonical_city", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("city_aliases")
    op.drop_table("service_centres")
    op.drop_table("chunks")
    op.drop_table("models")
    op.drop_table("sources")
