"""add tax_rate and tax_amount to transactions

Revision ID: b3c4d5e6f7a8
Revises: aedb27de7a73
Create Date: 2026-09-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'aedb27de7a73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('tax_rate', sa.Numeric(5, 4), server_default='0', nullable=False))
    op.add_column('transactions', sa.Column('tax_amount', sa.Numeric(10, 2), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('transactions', 'tax_amount')
    op.drop_column('transactions', 'tax_rate')
