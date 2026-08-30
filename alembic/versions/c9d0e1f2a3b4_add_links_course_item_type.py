"""add LINKS course item type and course_links table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-30 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE course_item_type_enum ADD VALUE IF NOT EXISTS 'LINKS'")

    op.create_table(
        'course_links',
        sa.Column('course_item_id', sa.UUID(), nullable=False),
        sa.Column('url', sa.String(length=2000), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['course_item_id'], ['course_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_links_course_item_id'), 'course_links', ['course_item_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_course_links_course_item_id'), table_name='course_links')
    op.drop_table('course_links')

    # Note: 'LINKS' can't be cheaply removed from course_item_type_enum in Postgres
    # (values can't be dropped without recreating the type); left in place as an
    # unused legacy value. Safe as long as no LINKS items were created before
    # downgrading - the course_links table that would hold their data is dropped above.
