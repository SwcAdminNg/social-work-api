"""add content_updated_at to courses

Revision ID: d8a3f6c1b2e7
Revises: c5719cef4491
Create Date: 2026-08-24 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8a3f6c1b2e7'
down_revision: Union[str, None] = 'c5719cef4491'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('courses', sa.Column('content_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('courses', 'content_updated_at')
