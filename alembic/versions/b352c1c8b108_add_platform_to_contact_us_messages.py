"""add platform to contact us messages

Revision ID: b352c1c8b108
Revises: eed4cb8711dd
Create Date: 2026-06-27 20:06:51.516649

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b352c1c8b108'
down_revision: Union[str, None] = 'eed4cb8711dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

platform_enum = postgresql.ENUM('NG', 'COM', name='platform_enum', create_type=False)


def upgrade() -> None:
    op.add_column(
        'contact_us_messages',
        sa.Column('platform', platform_enum, nullable=False, server_default='NG'),
    )
    op.alter_column('contact_us_messages', 'platform', server_default=None)


def downgrade() -> None:
    op.drop_column('contact_us_messages', 'platform')
