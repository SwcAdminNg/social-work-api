"""add community module (group chat)

Revision ID: b1c2d3e4f5a6
Revises: 4e587ee9a71f
Create Date: 2026-08-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '4e587ee9a71f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    community_type_enum = postgresql.ENUM(
        'COURSE', 'GENERAL', 'HELP', 'CUSTOM', name='community_type_enum', create_type=False,
    )
    community_type_enum.create(op.get_bind(), checkfirst=True)

    community_membership_added_via_enum = postgresql.ENUM(
        'MANUAL', 'COURSE_SNAPSHOT', name='community_membership_added_via_enum', create_type=False,
    )
    community_membership_added_via_enum.create(op.get_bind(), checkfirst=True)

    # -- communities ---------------------------------------------------------
    op.create_table(
        'communities',
        sa.Column('type', community_type_enum, nullable=False),
        sa.Column('course_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_communities_type'), 'communities', ['type'], unique=False)
    op.create_index(op.f('ix_communities_course_id'), 'communities', ['course_id'], unique=False)
    # One COURSE community per course - course_id is NULL for every other type, so
    # this is scoped to type='COURSE' rather than a plain unique constraint.
    op.create_index(
        'uq_communities_course_id_when_course_type',
        'communities',
        ['course_id'],
        unique=True,
        postgresql_where=sa.text("type = 'COURSE'"),
    )

    # -- community_memberships (CUSTOM communities only) ----------------------
    op.create_table(
        'community_memberships',
        sa.Column('community_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('added_via', community_membership_added_via_enum, nullable=False),
        sa.Column('added_from_course_id', sa.UUID(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['community_id'], ['communities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['added_from_course_id'], ['courses.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('community_id', 'user_id', name='uq_community_memberships_community_user'),
    )
    op.create_index(
        op.f('ix_community_memberships_community_id'), 'community_memberships', ['community_id'], unique=False
    )
    op.create_index(op.f('ix_community_memberships_user_id'), 'community_memberships', ['user_id'], unique=False)

    # -- community_messages ---------------------------------------------------
    op.create_table(
        'community_messages',
        sa.Column('community_id', sa.UUID(), nullable=False),
        sa.Column('sender_id', sa.UUID(), nullable=False),
        sa.Column('body', sa.Text(), server_default='', nullable=False),
        sa.Column('reply_to_message_id', sa.UUID(), nullable=True),
        sa.Column('attachment_storage_key', sa.String(length=1000), nullable=True),
        sa.Column('attachment_file_name', sa.String(length=255), nullable=True),
        sa.Column('attachment_mime_type', sa.String(length=255), nullable=True),
        sa.Column('attachment_file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('resource_reference_id', sa.UUID(), nullable=True),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['community_id'], ['communities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['reply_to_message_id'], ['community_messages.id'], ),
        sa.ForeignKeyConstraint(['resource_reference_id'], ['resources.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_community_messages_community_id'), 'community_messages', ['community_id'], unique=False
    )
    op.create_index(op.f('ix_community_messages_sender_id'), 'community_messages', ['sender_id'], unique=False)
    op.create_index(
        op.f('ix_community_messages_reply_to_message_id'),
        'community_messages',
        ['reply_to_message_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_community_messages_resource_reference_id'),
        'community_messages',
        ['resource_reference_id'],
        unique=False,
    )

    # -- data backfill ---------------------------------------------------------
    # Singleton GENERAL/HELP communities for every existing (and future-seeded)
    # environment, plus one COURSE community per pre-existing course.
    op.execute(
        """
        INSERT INTO communities (id, type, name, is_active, created_at)
        SELECT gen_random_uuid(), 'GENERAL', 'General', true, now()
        WHERE NOT EXISTS (SELECT 1 FROM communities WHERE type = 'GENERAL')
        """
    )
    op.execute(
        """
        INSERT INTO communities (id, type, name, is_active, created_at)
        SELECT gen_random_uuid(), 'HELP', 'Help', true, now()
        WHERE NOT EXISTS (SELECT 1 FROM communities WHERE type = 'HELP')
        """
    )
    op.execute(
        """
        INSERT INTO communities (id, type, course_id, name, is_active, created_at)
        SELECT gen_random_uuid(), 'COURSE', courses.id, courses.title, true, now()
        FROM courses
        WHERE courses.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM communities
              WHERE communities.type = 'COURSE' AND communities.course_id = courses.id
          )
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_community_messages_resource_reference_id'), table_name='community_messages')
    op.drop_index(op.f('ix_community_messages_reply_to_message_id'), table_name='community_messages')
    op.drop_index(op.f('ix_community_messages_sender_id'), table_name='community_messages')
    op.drop_index(op.f('ix_community_messages_community_id'), table_name='community_messages')
    op.drop_table('community_messages')

    op.drop_index(op.f('ix_community_memberships_user_id'), table_name='community_memberships')
    op.drop_index(op.f('ix_community_memberships_community_id'), table_name='community_memberships')
    op.drop_table('community_memberships')

    op.drop_index('uq_communities_course_id_when_course_type', table_name='communities')
    op.drop_index(op.f('ix_communities_course_id'), table_name='communities')
    op.drop_index(op.f('ix_communities_type'), table_name='communities')
    op.drop_table('communities')

    bind = op.get_bind()
    sa.Enum(name='community_membership_added_via_enum').drop(bind, checkfirst=True)
    sa.Enum(name='community_type_enum').drop(bind, checkfirst=True)
