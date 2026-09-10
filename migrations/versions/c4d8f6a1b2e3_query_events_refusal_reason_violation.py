"""query_events: create table if missing; add refusal_reason, first_attempt_had_violation

Real gap found live during this deploy: `query_events` (api/models/event.py,
T8.1/T8.2) was never part of the tracked alembic migration chain at all —
it only ever existed because `api/routers/admin.py`'s `/admin/ingest` and
`/admin/metrics` routes both call `Base.metadata.create_all(engine)` as a
belt-and-suspenders step, which silently created it out-of-band on every
database that happened to hit one of those routes before this migration
existed (dev.db included). `scripts/bootstrap_db.py`'s "alembic upgrade
head" is what production actually boots on — it never calls
`create_all`, so a from-scratch production schema (or one reset by that
same script's drop-schema fallback) has no `query_events` table at all,
and the original version of this migration's plain `ALTER TABLE
query_events ADD COLUMN ...` failed with `UndefinedTable` — which,
compounding the problem, is exactly the failure `bootstrap_db.py` reacts
to by dropping and recreating the *entire* schema and retrying, so this
bug was a crash-loop that reset the whole production database on every
boot until fixed here.

Checks whether the table exists first: creates it in full (matching
`QueryEvent`'s complete current column set, so a from-scratch database
never needs a second migration to catch up) if not, otherwise just adds
the two new columns to whatever already exists (dev.db and any other
database that reached this point via `create_all` before this migration
was written).

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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "query_events" not in inspector.get_table_names():
        op.create_table(
            "query_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("intent", sa.String(), nullable=True),
            sa.Column("refused", sa.Boolean(), nullable=False),
            sa.Column("conceded", sa.Boolean(), nullable=False),
            sa.Column("blocked_by_input_guardrail", sa.String(), nullable=True),
            sa.Column("top_score", sa.Float(), nullable=False),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("cost_usd", sa.Float(), nullable=True),
            sa.Column("refusal_reason", sa.String(), nullable=True),
            sa.Column("first_attempt_had_violation", sa.Boolean(), nullable=True),
        )
        op.create_index(
            "ix_query_events_created_at", "query_events", ["created_at"], unique=False
        )
        return

    existing_columns = {c["name"] for c in inspector.get_columns("query_events")}
    with op.batch_alter_table("query_events") as batch_op:
        if "refusal_reason" not in existing_columns:
            batch_op.add_column(sa.Column("refusal_reason", sa.String(), nullable=True))
        if "first_attempt_had_violation" not in existing_columns:
            batch_op.add_column(
                sa.Column("first_attempt_had_violation", sa.Boolean(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "query_events" not in inspector.get_table_names():
        return
    with op.batch_alter_table("query_events") as batch_op:
        batch_op.drop_column("first_attempt_had_violation")
        batch_op.drop_column("refusal_reason")
