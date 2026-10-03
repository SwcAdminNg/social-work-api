"""add certificate_pass_mark_percentage to courses

Revision ID: d1f2a3b4c5e6
Revises: c9e3a4b5d6f7
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1f2a3b4c5e6'
down_revision: Union[str, None] = 'c9e3a4b5d6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Overall score a student must reach (average of their best score on every
    # assessment in the course) to earn the course certificate.
    op.add_column(
        'courses',
        sa.Column('certificate_pass_mark_percentage', sa.Integer(), server_default='70', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('courses', 'certificate_pass_mark_percentage')
