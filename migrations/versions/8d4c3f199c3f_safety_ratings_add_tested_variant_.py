"""safety_ratings: add tested_variant, status, vru_score; drop max_score

Revision ID: 8d4c3f199c3f
Revises: 2d728ae4098f
Create Date: 2026-09-04 15:28:58.038526

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8d4c3f199c3f'
down_revision: str | Sequence[str] | None = '2d728ae4098f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("safety_ratings") as batch_op:
        batch_op.add_column(sa.Column("tested_variant", sa.String(), nullable=False))
        batch_op.add_column(
            sa.Column(
                "status", sa.Enum("current", "expired", name="rating_status"), nullable=False
            )
        )
        batch_op.add_column(sa.Column("vru_score", sa.Numeric(), nullable=False))
        batch_op.drop_column("max_score")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("safety_ratings") as batch_op:
        batch_op.add_column(sa.Column("max_score", sa.NUMERIC(), nullable=False))
        batch_op.drop_column("vru_score")
        batch_op.drop_column("status")
        batch_op.drop_column("tested_variant")
