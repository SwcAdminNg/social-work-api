"""add instructor application flow

Revision ID: cd61a0bc6e89
Revises: ab95c874d52e
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'cd61a0bc6e89'
down_revision: Union[str, None] = 'ab95c874d52e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS 'NEW_INSTRUCTOR_APPLICATION'")

    op.create_table(
        'instructor_setup_tokens',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instructor_setup_tokens_token_hash'), 'instructor_setup_tokens', ['token_hash'], unique=True
    )
    op.create_index(
        op.f('ix_instructor_setup_tokens_user_id'), 'instructor_setup_tokens', ['user_id'], unique=False
    )

    instructor_application_status_enum = postgresql.ENUM(
        'PENDING', 'APPROVED', 'REJECTED', name='instructor_application_status_enum', create_type=False
    )
    instructor_application_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'instructor_applications',
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=False),
        sa.Column('cv_storage_key', sa.String(length=1000), nullable=False),
        sa.Column('cv_file_name', sa.String(length=255), nullable=False),
        sa.Column(
            'status', instructor_application_status_enum, server_default='PENDING', nullable=False
        ),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_instructor_applications_email'), 'instructor_applications', ['email'], unique=False
    )
    op.create_index(
        op.f('ix_instructor_applications_status'), 'instructor_applications', ['status'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_instructor_applications_status'), table_name='instructor_applications')
    op.drop_index(op.f('ix_instructor_applications_email'), table_name='instructor_applications')
    op.drop_table('instructor_applications')

    postgresql.ENUM(name='instructor_application_status_enum').drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f('ix_instructor_setup_tokens_user_id'), table_name='instructor_setup_tokens')
    op.drop_index(op.f('ix_instructor_setup_tokens_token_hash'), table_name='instructor_setup_tokens')
    op.drop_table('instructor_setup_tokens')

    # Note: 'NEW_INSTRUCTOR_APPLICATION' can't be cheaply removed from
    # notification_type_enum in Postgres (values can't be dropped without
    # recreating the type); left in place as an unused legacy value.
