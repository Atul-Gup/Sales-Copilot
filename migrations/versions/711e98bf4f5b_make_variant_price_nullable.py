"""make variant price nullable

Revision ID: 711e98bf4f5b
Revises: 0fb7dd02278d
Create Date: 2026-09-04 14:59:54.106495

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '711e98bf4f5b'
down_revision: str | Sequence[str] | None = '0fb7dd02278d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("variants") as batch_op:
        batch_op.alter_column(
            "ex_showroom_paise", existing_type=sa.BIGINT(), nullable=True
        )
        batch_op.alter_column(
            "price_source_id", existing_type=sa.INTEGER(), nullable=True
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("variants") as batch_op:
        batch_op.alter_column(
            "price_source_id", existing_type=sa.INTEGER(), nullable=False
        )
        batch_op.alter_column(
            "ex_showroom_paise", existing_type=sa.BIGINT(), nullable=False
        )
