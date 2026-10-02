"""add staff role assignments and the governance audit log

Revision ID: a7c1e2d3f4b5
Revises: f3a4b5c6d7e8
Create Date: 2026-10-02 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7c1e2d3f4b5'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _base_entity_columns() -> list[sa.Column]:
    """The audit/soft-delete columns every BaseEntity table carries."""
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('deleted_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('restored_by', postgresql.UUID(as_uuid=True), nullable=True),
    ]


def upgrade() -> None:
    staff_role_enum = postgresql.ENUM(
        'INSTRUCTOR', 'CONTENT_DEVELOPER', 'ACADEMIC_REVIEWER', 'ASSESSMENT_MODERATOR', 'QA_REVIEWER',
        'COURSE_LEAD', 'LEAD_ASSESSOR', 'HEAD_OF_LEARNING', 'PLATFORM_ADMIN',
        name='staff_role_enum', create_type=False,
    )
    staff_role_enum.create(op.get_bind(), checkfirst=True)

    # No data backfill: existing ADMIN and INSTRUCTOR accounts get their
    # permissions implicitly (see PermissionService). Reviewer roles (Academic,
    # QA, Course Lead, Head of Learning) are granted explicitly by an admin.
    op.create_table(
        'staff_role_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', staff_role_enum, nullable=False),
        sa.Column('course_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=True),
        sa.Column('granted_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('revoke_reason', sa.String(500), nullable=True),
        *_base_entity_columns(),
    )
    op.create_index('ix_staff_role_assignments_user_id', 'staff_role_assignments', ['user_id'])
    op.create_index('ix_staff_role_assignments_course_id', 'staff_role_assignments', ['course_id'])
    op.create_index('ix_staff_role_assignments_role_course', 'staff_role_assignments', ['role', 'course_id'])
    op.execute(
        "CREATE UNIQUE INDEX uq_staff_role_assignment_active ON staff_role_assignments "
        "(user_id, role, coalesce(course_id, '00000000-0000-0000-0000-000000000000'::uuid)) "
        "WHERE revoked_at IS NULL AND deleted_at IS NULL"
    )

    op.create_table(
        'governance_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('actor_permissions', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
        sa.Column('entity_type', sa.String(40), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('course_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('revision_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('version_label', sa.String(20), nullable=True),
        sa.Column('action', sa.String(60), nullable=False),
        sa.Column('from_status', sa.String(60), nullable=True),
        sa.Column('to_status', sa.String(60), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('metadata_json', postgresql.JSONB(), nullable=True),
    )
    op.create_index('ix_governance_audit_log_occurred_at', 'governance_audit_log', ['occurred_at'])
    op.create_index('ix_governance_audit_log_actor_id', 'governance_audit_log', ['actor_id'])
    op.create_index('ix_governance_audit_log_revision_id', 'governance_audit_log', ['revision_id'])
    op.create_index('ix_governance_audit_log_course_occurred', 'governance_audit_log', ['course_id', 'occurred_at'])
    op.create_index('ix_governance_audit_log_entity', 'governance_audit_log', ['entity_type', 'entity_id'])

    # The audit log is append-only: reject any UPDATE or DELETE at the database
    # level, so not even a buggy code path or a manual query can rewrite history.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION governance_audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'governance_audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_governance_audit_log_immutable BEFORE UPDATE OR DELETE ON governance_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION governance_audit_log_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_governance_audit_log_immutable ON governance_audit_log")
    op.execute("DROP FUNCTION IF EXISTS governance_audit_log_immutable()")
    op.drop_table('governance_audit_log')
    op.drop_table('staff_role_assignments')

    bind = op.get_bind()
    sa.Enum(name='staff_role_enum').drop(bind, checkfirst=True)
