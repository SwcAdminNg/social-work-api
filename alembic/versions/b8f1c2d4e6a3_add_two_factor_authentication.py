"""add two factor authentication

Revision ID: b8f1c2d4e6a3
Revises: ae3219dc6198
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8f1c2d4e6a3'
down_revision: Union[str, None] = 'ae3219dc6198'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    two_factor_method_enum = postgresql.ENUM('EMAIL', 'TOTP', name='two_factor_method_enum', create_type=False)
    two_factor_method_enum.create(op.get_bind(), checkfirst=True)

    two_factor_purpose_enum = postgresql.ENUM('LOGIN', 'SETUP', name='two_factor_purpose_enum', create_type=False)
    two_factor_purpose_enum.create(op.get_bind(), checkfirst=True)

    op.add_column('users', sa.Column('two_factor_method', two_factor_method_enum, nullable=True))
    op.add_column(
        'users',
        sa.Column('two_factor_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.add_column('users', sa.Column('totp_secret_encrypted', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('two_factor_confirmed_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'email_otp_tokens',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('purpose', two_factor_purpose_enum, nullable=False),
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
        op.f('ix_email_otp_tokens_code_hash'), 'email_otp_tokens', ['code_hash'], unique=False
    )
    op.create_index(
        op.f('ix_email_otp_tokens_user_id'), 'email_otp_tokens', ['user_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_email_otp_tokens_user_id'), table_name='email_otp_tokens')
    op.drop_index(op.f('ix_email_otp_tokens_code_hash'), table_name='email_otp_tokens')
    op.drop_table('email_otp_tokens')

    op.drop_column('users', 'two_factor_confirmed_at')
    op.drop_column('users', 'totp_secret_encrypted')
    op.drop_column('users', 'two_factor_enabled')
    op.drop_column('users', 'two_factor_method')

    bind = op.get_bind()
    postgresql.ENUM(name='two_factor_purpose_enum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='two_factor_method_enum').drop(bind, checkfirst=True)
