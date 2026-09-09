"""chunks: nullable document_id, add external_id

Supports the objection-handling guide (`ingest/objection_guide.py`):

- `document_id` becomes nullable — that guide's 3 "General" items are
  cross-cutting consultant guidance, not a fact about one specific model,
  so forcing a `document_id` onto them would be a fabricated association.
  Every chunk from the original five product documents keeps a real
  `document_id`; this only widens what's *allowed*, it changes no existing
  row.
- `external_id` is added (nullable) to hold a pre-chunked source's own item
  ID (e.g. "EX30_001"). The original five documents were never pre-chunked
  with their own IDs, so every existing chunk gets `external_id = NULL`
  here — no existing chunk's content or association is touched.

Revision ID: b7e2f14a9c3d
Revises: a1b2c3d4e5f6
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2f14a9c3d"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.alter_column("document_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("external_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch_op:
        batch_op.drop_column("external_id")
        batch_op.alter_column("document_id", existing_type=sa.Integer(), nullable=False)
