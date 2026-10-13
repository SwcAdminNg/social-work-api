"""add item_description to course_items

Revision ID: b7d2e4f6a8c1
Revises: e7a8b9c0d1f2
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f6a8c1'
down_revision: Union[str, None] = 'e7a8b9c0d1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('course_items', sa.Column('item_description', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('course_items', 'item_description')
