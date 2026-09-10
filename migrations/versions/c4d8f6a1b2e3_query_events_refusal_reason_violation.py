"""query_events: add refusal_reason, first_attempt_had_violation

Supports the dashboard's hallucination-rate metrics (api/routers/admin.py):

- `refusal_reason` mirrors `AnswerResult.refusal_reason` (api/services/
  pipeline.py) — distinguishes "no_answer_outside_corpus" (nothing to
  generate from) from "grounding_violation" (generation ran twice and
  still couldn't produce a verifiably-cited answer). Nullable — every
  existing row (and every non-refused row going forward) gets NULL.
- `first_attempt_had_violation` records whether verify_grounding's first
  generation attempt had an uncited/wrong-chunk claim, independent of
  whether a second attempt then fixed it or the query was ultimately
  refused. By construction, an accepted response can never itself carry a
  violation, so this is the only place a real hallucination rate can be
  measured — nullable because no generation happens at all for a blocked,
  pre-retrieval-refused, or conceded query.

Revision ID: c4d8f6a1b2e3
Revises: b7e2f14a9c3d
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8f6a1b2e3"
down_revision: str | None = "b7e2f14a9c3d"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("query_events") as batch_op:
        batch_op.add_column(sa.Column("refusal_reason", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("first_attempt_had_violation", sa.Boolean(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("query_events") as batch_op:
        batch_op.drop_column("first_attempt_had_violation")
        batch_op.drop_column("refusal_reason")
