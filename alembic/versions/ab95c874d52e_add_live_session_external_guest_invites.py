"""add live session external guest invites

Revision ID: ab95c874d52e
Revises: 763689c068c4
Create Date: 2026-09-17 18:05:58.746116

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ab95c874d52e'
down_revision: Union[str, None] = '763689c068c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('live_session_external_invites',
    sa.Column('live_session_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('invited_by_id', sa.UUID(), nullable=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_joined_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('join_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('updated_by', sa.UUID(), nullable=True),
    sa.Column('deleted_by', sa.UUID(), nullable=True),
    sa.Column('restored_by', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['live_session_id'], ['course_live_sessions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('live_session_id', 'email', name='uq_live_session_external_invite_session_email')
    )
    op.create_index(op.f('ix_live_session_external_invites_live_session_id'), 'live_session_external_invites', ['live_session_id'], unique=False)
    op.create_index(op.f('ix_live_session_external_invites_token_hash'), 'live_session_external_invites', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_live_session_external_invites_token_hash'), table_name='live_session_external_invites')
    op.drop_index(op.f('ix_live_session_external_invites_live_session_id'), table_name='live_session_external_invites')
    op.drop_table('live_session_external_invites')
