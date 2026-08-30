"""add resources module (library, attachments, video/document/link)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    resource_category_enum = postgresql.ENUM(
        'COURSE_MATERIALS', 'PRACTICE_RESOURCES', 'POLICIES_AND_GUIDANCE', 'TEMPLATES_AND_FORMS',
        'VIDEOS_AND_WEBINARS', 'RESEARCH_AND_PUBLICATIONS', 'CAREER_AND_CPD', 'USEFUL_LINKS',
        name='resource_category_enum', create_type=False,
    )
    resource_category_enum.create(op.get_bind(), checkfirst=True)

    resource_visibility_enum = postgresql.ENUM(
        'PUBLIC', 'LOGGED_IN', 'COURSE_ENROLLED', name='resource_visibility_enum', create_type=False,
    )
    resource_visibility_enum.create(op.get_bind(), checkfirst=True)

    resource_attachment_type_enum = postgresql.ENUM(
        'VIDEO', 'DOCUMENT', 'LINKS', name='resource_attachment_type_enum', create_type=False,
    )
    resource_attachment_type_enum.create(op.get_bind(), checkfirst=True)

    # -- resources ---------------------------------------------------------------
    op.create_table(
        'resources',
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=280), nullable=False),
        sa.Column('category', resource_category_enum, nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=1000), nullable=True),
        sa.Column('visibility', resource_visibility_enum, server_default='PUBLIC', nullable=False),
        sa.Column('course_id', sa.UUID(), nullable=True),
        sa.Column('owner_id', sa.UUID(), nullable=False),
        sa.Column('is_published', sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_resources_slug'), 'resources', ['slug'], unique=True)
    op.create_index(op.f('ix_resources_course_id'), 'resources', ['course_id'], unique=False)
    op.create_index(op.f('ix_resources_owner_id'), 'resources', ['owner_id'], unique=False)

    # -- resource_attachments ------------------------------------------------
    op.create_table(
        'resource_attachments',
        sa.Column('resource_id', sa.UUID(), nullable=False),
        sa.Column('attachment_type', resource_attachment_type_enum, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_resource_attachments_resource_id'), 'resource_attachments', ['resource_id'], unique=False
    )

    # -- resource_videos - reuses the existing video_provider_enum/video_status_enum --
    # -- native types (course module) rather than creating duplicates -----------
    video_provider_enum = postgresql.ENUM(
        'BUNNY', name='video_provider_enum', create_type=False
    )
    video_status_enum = postgresql.ENUM(
        'PENDING', 'PROCESSING', 'READY', 'FAILED', name='video_status_enum', create_type=False
    )
    op.create_table(
        'resource_videos',
        sa.Column('attachment_id', sa.UUID(), nullable=False),
        sa.Column('provider', video_provider_enum, server_default='BUNNY', nullable=False),
        sa.Column('bunny_video_guid', sa.String(length=100), nullable=False),
        sa.Column('status', video_status_enum, server_default='PENDING', nullable=False),
        sa.Column('playback_url', sa.String(length=1000), nullable=True),
        sa.Column('thumbnail_url', sa.String(length=1000), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['attachment_id'], ['resource_attachments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_resource_videos_attachment_id'), 'resource_videos', ['attachment_id'], unique=True
    )

    # -- resource_documents --------------------------------------------------
    op.create_table(
        'resource_documents',
        sa.Column('attachment_id', sa.UUID(), nullable=False),
        sa.Column('storage_key', sa.String(length=1000), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('is_uploaded', sa.Boolean(), nullable=False),
        sa.Column('downloadable', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['attachment_id'], ['resource_attachments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_resource_documents_attachment_id'), 'resource_documents', ['attachment_id'], unique=True
    )

    # -- resource_links -------------------------------------------------------
    op.create_table(
        'resource_links',
        sa.Column('attachment_id', sa.UUID(), nullable=False),
        sa.Column('url', sa.String(length=2000), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['attachment_id'], ['resource_attachments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_resource_links_attachment_id'), 'resource_links', ['attachment_id'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_resource_links_attachment_id'), table_name='resource_links')
    op.drop_table('resource_links')

    op.drop_index(op.f('ix_resource_documents_attachment_id'), table_name='resource_documents')
    op.drop_table('resource_documents')

    op.drop_index(op.f('ix_resource_videos_attachment_id'), table_name='resource_videos')
    op.drop_table('resource_videos')
    # Note: video_provider_enum/video_status_enum are NOT dropped here - they're
    # owned by the course module's migrations (course_videos still uses them).

    op.drop_index(op.f('ix_resource_attachments_resource_id'), table_name='resource_attachments')
    op.drop_table('resource_attachments')

    op.drop_index(op.f('ix_resources_owner_id'), table_name='resources')
    op.drop_index(op.f('ix_resources_course_id'), table_name='resources')
    op.drop_index(op.f('ix_resources_slug'), table_name='resources')
    op.drop_table('resources')

    bind = op.get_bind()
    sa.Enum(name='resource_attachment_type_enum').drop(bind, checkfirst=True)
    sa.Enum(name='resource_visibility_enum').drop(bind, checkfirst=True)
    sa.Enum(name='resource_category_enum').drop(bind, checkfirst=True)
