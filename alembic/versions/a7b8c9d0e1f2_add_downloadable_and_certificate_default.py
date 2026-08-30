"""add downloadable to course documents and flip certificate_enabled default

Revision ID: a7b8c9d0e1f2
Revises: 5f7a9c0d1e2b
Create Date: 2026-08-30 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '5f7a9c0d1e2b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'course_documents',
        sa.Column('downloadable', sa.Boolean(), server_default='false', nullable=False),
    )
    # New courses default to certificate_enabled=false (a course with ongoing
    # content updates shouldn't hand out certificates for a moving target).
    # Existing rows keep whatever value they already have.
    op.alter_column('courses', 'certificate_enabled', server_default='false')


def downgrade() -> None:
    op.alter_column('courses', 'certificate_enabled', server_default='true')
    op.drop_column('course_documents', 'downloadable')
