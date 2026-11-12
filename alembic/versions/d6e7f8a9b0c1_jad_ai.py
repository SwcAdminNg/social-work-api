"""JAD AI study assistant: conversations, messages, lesson text and the answer cache

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-12 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        'jad_conversations',
        *_base_columns(),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('course_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('course_items.id', ondelete='CASCADE'), nullable=False),
        sa.UniqueConstraint('user_id', 'item_id', name='uq_jad_conversations_user_item'),
    )
    op.create_index('ix_jad_conversations_user_id', 'jad_conversations', ['user_id'])
    op.create_index('ix_jad_conversations_item_id', 'jad_conversations', ['item_id'])

    op.create_table(
        'jad_messages',
        *_base_columns(),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('jad_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('suggestions', postgresql.JSONB(), nullable=True),
        sa.Column('question_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('cached', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('cache_entry_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('blocked', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('model', sa.String(length=100), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('cached_prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('feedback', sa.SmallInteger(), nullable=True),
    )
    op.create_index('ix_jad_messages_conversation_id', 'jad_messages', ['conversation_id'])
    op.create_index('ix_jad_messages_user_created', 'jad_messages', ['user_id', 'created_at'])

    op.create_table(
        'jad_item_contexts',
        *_base_columns(),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('course_items.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('source_key', sa.String(length=1000), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('material', sa.Text(), nullable=False, server_default=''),
        sa.Column('suggestions', postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        'jad_cache_entries',
        *_base_columns(),
        sa.Column('item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('course_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('context_key', sa.String(length=64), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('question_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding_kind', sa.String(length=80), nullable=False),
        sa.Column('embedding', sa.LargeBinary(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('suggestions', postgresql.JSONB(), nullable=True),
        sa.Column('hit_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_hit_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_jad_cache_lookup', 'jad_cache_entries', ['item_id', 'context_key', 'embedding_kind'])


def downgrade() -> None:
    op.drop_index('ix_jad_cache_lookup', table_name='jad_cache_entries')
    op.drop_table('jad_cache_entries')
    op.drop_table('jad_item_contexts')
    op.drop_index('ix_jad_messages_user_created', table_name='jad_messages')
    op.drop_index('ix_jad_messages_conversation_id', table_name='jad_messages')
    op.drop_table('jad_messages')
    op.drop_index('ix_jad_conversations_item_id', table_name='jad_conversations')
    op.drop_index('ix_jad_conversations_user_id', table_name='jad_conversations')
    op.drop_table('jad_conversations')
