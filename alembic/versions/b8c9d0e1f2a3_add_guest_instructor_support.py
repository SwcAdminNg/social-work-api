"""add guest instructor support (is_guest flag + section instructor links)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-30 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'course_instructors',
        sa.Column('is_guest', sa.Boolean(), server_default='false', nullable=False),
    )

    op.create_table(
        'course_section_instructors',
        sa.Column('section_id', sa.UUID(), nullable=False),
        sa.Column('course_instructor_id', sa.UUID(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['section_id'], ['course_sections.id'], ),
        sa.ForeignKeyConstraint(['course_instructor_id'], ['course_instructors.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_section_instructors_section_id'), 'course_section_instructors',
        ['section_id'], unique=False,
    )
    op.create_index(
        op.f('ix_course_section_instructors_course_instructor_id'), 'course_section_instructors',
        ['course_instructor_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_course_section_instructors_course_instructor_id'), table_name='course_section_instructors'
    )
    op.drop_index(op.f('ix_course_section_instructors_section_id'), table_name='course_section_instructors')
    op.drop_table('course_section_instructors')
    op.drop_column('course_instructors', 'is_guest')
