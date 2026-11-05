"""passkeys: WebAuthn credentials for fingerprint, face or device PIN sign-in

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-05 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'passkey_credentials',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('credential_id', sa.String(length=1024), nullable=False),
        sa.Column('public_key', sa.LargeBinary(), nullable=False),
        sa.Column('sign_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('transports', postgresql.ARRAY(sa.String(length=32)), nullable=True),
        sa.Column('aaguid', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('device_type', sa.String(length=32), nullable=True),
        sa.Column('backed_up', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('rp_id', sa.String(length=255), nullable=False),
        sa.Column('created_user_agent', sa.String(length=400), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_user_agent', sa.String(length=400), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index('ix_passkey_credentials_user_id', 'passkey_credentials', ['user_id'])
    op.create_index('ix_passkey_credentials_credential_id', 'passkey_credentials', ['credential_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_passkey_credentials_credential_id', table_name='passkey_credentials')
    op.drop_index('ix_passkey_credentials_user_id', table_name='passkey_credentials')
    op.drop_table('passkey_credentials')
