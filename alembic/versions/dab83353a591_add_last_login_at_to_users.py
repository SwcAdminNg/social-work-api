"""add last login at to users

Revision ID: dab83353a591
Revises: b352c1c8b108
Create Date: 2026-06-27 20:09:12.951333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dab83353a591'
down_revision: Union[str, None] = 'b352c1c8b108'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
