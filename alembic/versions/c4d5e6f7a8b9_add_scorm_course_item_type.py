"""add SCORM course item type, packages and learner runtime progress

Revision ID: c4d5e6f7a8b9
Revises: b7d2e4f6a8c1
Create Date: 2026-10-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b7d2e4f6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE course_item_type_enum ADD VALUE IF NOT EXISTS 'SCORM'")

    op.create_table(
        'course_scorm_packages',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('course_item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('storage_key', sa.String(length=1000), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column(
            'status',
            postgresql.ENUM('PENDING', 'PROCESSING', 'READY', 'FAILED', name='video_status_enum', create_type=False),
            nullable=False,
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('extracted_prefix', sa.String(length=1000), nullable=True),
        sa.Column('launch_path', sa.String(length=1000), nullable=True),
        sa.Column('scorm_version', sa.String(length=20), nullable=True),
        sa.Column('manifest_identifier', sa.String(length=255), nullable=True),
        sa.Column('manifest_title', sa.String(length=500), nullable=True),
        sa.Column('file_count', sa.Integer(), nullable=True),
        sa.Column('total_size_bytes', sa.Integer(), nullable=True),
        sa.Column('completion_from_package', sa.Boolean(), server_default='true', nullable=False),
        sa.ForeignKeyConstraint(['course_item_id'], ['course_items.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('course_item_id'),
    )
    op.create_index(
        op.f('ix_course_scorm_packages_course_item_id'), 'course_scorm_packages', ['course_item_id'], unique=True
    )

    op.create_table(
        'user_scorm_progress',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('lesson_status', sa.String(length=50), nullable=True),
        sa.Column('success_status', sa.String(length=50), nullable=True),
        sa.Column('lesson_location', sa.Text(), nullable=True),
        sa.Column('suspend_data', sa.Text(), nullable=True),
        sa.Column('score_raw', sa.Numeric(10, 2), nullable=True),
        sa.Column('score_min', sa.Numeric(10, 2), nullable=True),
        sa.Column('score_max', sa.Numeric(10, 2), nullable=True),
        sa.Column('total_time_seconds', sa.Integer(), server_default='0', nullable=False),
        sa.Column('active_session_id', sa.String(length=64), nullable=True),
        sa.Column('active_session_base_seconds', sa.Integer(), server_default='0', nullable=False),
        sa.Column('launch_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cmi_data', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('last_committed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['course_items.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'item_id', name='uq_user_scorm_progress'),
    )
    op.create_index(op.f('ix_user_scorm_progress_item_id'), 'user_scorm_progress', ['item_id'], unique=False)
    op.create_index(op.f('ix_user_scorm_progress_user_id'), 'user_scorm_progress', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_scorm_progress_user_id'), table_name='user_scorm_progress')
    op.drop_index(op.f('ix_user_scorm_progress_item_id'), table_name='user_scorm_progress')
    op.drop_table('user_scorm_progress')
    op.drop_index(op.f('ix_course_scorm_packages_course_item_id'), table_name='course_scorm_packages')
    op.drop_table('course_scorm_packages')
    # Postgres can't drop a single enum value; 'SCORM' stays on course_item_type_enum.
