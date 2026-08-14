"""add course instructors, bookmarks, and timed access

Revision ID: a1b2c3d4e5f6
Revises: c6a7fdf176c4
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c6a7fdf176c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('course_instructors',
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
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
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_course_instructors_course_id'), 'course_instructors', ['course_id'], unique=False)
    op.create_index(op.f('ix_course_instructors_user_id'), 'course_instructors', ['user_id'], unique=False)

    op.create_table('course_bookmarks',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('restored_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'course_id', name='uq_course_bookmark')
    )
    op.create_index(op.f('ix_course_bookmarks_course_id'), 'course_bookmarks', ['course_id'], unique=False)
    op.create_index(op.f('ix_course_bookmarks_user_id'), 'course_bookmarks', ['user_id'], unique=False)

    access_mode_enum = sa.Enum('SELF_PACED', 'SCHEDULED', name='course_access_mode_enum')
    access_mode_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'courses',
        sa.Column(
            'access_mode',
            access_mode_enum,
            server_default='SELF_PACED',
            nullable=False,
        ),
    )
    op.add_column('courses', sa.Column('access_start_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('courses', sa.Column('access_end_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('courses', 'access_end_date')
    op.drop_column('courses', 'access_start_date')
    op.drop_column('courses', 'access_mode')
    sa.Enum(name='course_access_mode_enum').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_course_bookmarks_user_id'), table_name='course_bookmarks')
    op.drop_index(op.f('ix_course_bookmarks_course_id'), table_name='course_bookmarks')
    op.drop_table('course_bookmarks')

    op.drop_index(op.f('ix_course_instructors_user_id'), table_name='course_instructors')
    op.drop_index(op.f('ix_course_instructors_course_id'), table_name='course_instructors')
    op.drop_table('course_instructors')
