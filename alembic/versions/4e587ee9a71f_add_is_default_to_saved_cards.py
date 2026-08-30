"""add is_default to saved_cards

Revision ID: a1b2c3d4e5f6
Revises: d0e1f2a3b4c5
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4e587ee9a71f'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'saved_cards',
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('saved_cards', 'is_default', server_default=None)


def downgrade() -> None:
    op.drop_column('saved_cards', 'is_default')
