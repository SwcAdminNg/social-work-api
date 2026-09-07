"""add LIVE_SESSION course item type and course_live_sessions table

Revision ID: d1e2f3a4b5c6
Revises: b3c4d5e6f7a8
Create Date: 2026-09-08 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE course_item_type_enum ADD VALUE IF NOT EXISTS 'LIVE_SESSION'")

    op.create_table(
        'course_live_sessions',
        sa.Column('course_item_id', sa.UUID(), nullable=False),
        sa.Column('scheduled_start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('guest_name', sa.String(length=255), nullable=True),
        sa.Column('guest_title', sa.String(length=255), nullable=True),
        sa.Column('daily_room_name', sa.String(length=255), nullable=False),
        sa.Column('daily_room_url', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.Enum('SCHEDULED', 'LIVE', 'ENDED', 'CANCELLED', name='live_session_status_enum'), nullable=False),
        sa.Column('recording_status', postgresql.ENUM('PENDING', 'PROCESSING', 'READY', 'FAILED', name='video_status_enum', create_type=False), nullable=True),
        sa.Column('recording_playback_url', sa.String(length=1000), nullable=True),
        sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('invite_sent_at', sa.DateTime(timezone=True), nullable=True),
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
        op.f('ix_course_live_sessions_course_item_id'), 'course_live_sessions', ['course_item_id'], unique=True
    )
    op.create_unique_constraint(
        'uq_course_live_sessions_daily_room_name', 'course_live_sessions', ['daily_room_name']
    )


def downgrade() -> None:
    op.drop_constraint('uq_course_live_sessions_daily_room_name', 'course_live_sessions', type_='unique')
    op.drop_index(op.f('ix_course_live_sessions_course_item_id'), table_name='course_live_sessions')
    op.drop_table('course_live_sessions')

    sa.Enum(name='live_session_status_enum').drop(op.get_bind(), checkfirst=True)

    # Note: 'LIVE_SESSION' can't be cheaply removed from course_item_type_enum in
    # Postgres (values can't be dropped without recreating the type); left in place
    # as an unused legacy value, matching the LINKS migration's approach.
