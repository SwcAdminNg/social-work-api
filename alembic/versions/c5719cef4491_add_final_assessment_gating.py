"""add final assessment gating (module/course redo-on-fail)

Revision ID: c5719cef4491
Revises: b4608bdef337
Create Date: 2026-08-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c5719cef4491'
down_revision: Union[str, None] = 'b4608bdef337'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'course_assessments',
        sa.Column('is_final_assessment', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'course_essay_settings',
        sa.Column('pass_mark_percentage', sa.Integer(), nullable=False, server_default='70'),
    )
    op.add_column('course_essay_settings', sa.Column('max_attempts', sa.Integer(), nullable=True))
    op.add_column(
        'essay_submissions',
        sa.Column('graded_attempts', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('essay_submissions', 'graded_attempts')
    op.drop_column('course_essay_settings', 'max_attempts')
    op.drop_column('course_essay_settings', 'pass_mark_percentage')
    op.drop_column('course_assessments', 'is_final_assessment')
