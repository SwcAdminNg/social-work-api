"""quiz attempts: store the version each student saw (AI-paraphrased on retries)

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ATTEMPT_TABLES = ('quiz_attempts', 'quiz_group_attempts')


def upgrade() -> None:
    for table in ATTEMPT_TABLES:
        op.add_column(table, sa.Column('presented_questions', postgresql.JSONB(), nullable=True))
        op.add_column(table, sa.Column('paraphrased', sa.Boolean(), nullable=False, server_default=sa.false()))
        op.add_column(table, sa.Column('paraphrase_model', sa.String(length=100), nullable=True))

    op.create_table(
        'pending_quiz_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('course_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('presented_questions', postgresql.JSONB(), nullable=False),
        sa.Column('paraphrased', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('paraphrase_model', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint('user_id', 'item_id', name='uq_pending_quiz_versions_user_item'),
    )
    op.create_index('ix_pending_quiz_versions_user_id', 'pending_quiz_versions', ['user_id'])
    op.create_index('ix_pending_quiz_versions_item_id', 'pending_quiz_versions', ['item_id'])


def downgrade() -> None:
    op.drop_index('ix_pending_quiz_versions_item_id', table_name='pending_quiz_versions')
    op.drop_index('ix_pending_quiz_versions_user_id', table_name='pending_quiz_versions')
    op.drop_table('pending_quiz_versions')
    for table in ATTEMPT_TABLES:
        op.drop_column(table, 'paraphrase_model')
        op.drop_column(table, 'paraphrased')
        op.drop_column(table, 'presented_questions')
