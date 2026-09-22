"""add instructor cv fields to users and instructor_documents table

Revision ID: 8c89897f198b
Revises: cd61a0bc6e89
Create Date: 2026-09-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8c89897f198b'
down_revision: Union[str, None] = 'cd61a0bc6e89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('cv_storage_key', sa.String(length=1000), nullable=True))
    op.add_column('users', sa.Column('cv_file_name', sa.String(length=255), nullable=True))

    op.create_table(
        'instructor_documents',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=1000), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_instructor_documents_user_id'), 'instructor_documents', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_instructor_documents_user_id'), table_name='instructor_documents')
    op.drop_table('instructor_documents')

    op.drop_column('users', 'cv_file_name')
    op.drop_column('users', 'cv_storage_key')
