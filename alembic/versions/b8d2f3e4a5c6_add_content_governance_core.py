"""add content governance core: revisions, review stages, versions, draft layer

Revision ID: b8d2f3e4a5c6
Revises: a7c1e2d3f4b5
Create Date: 2026-10-02 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b8d2f3e4a5c6'
down_revision: Union[str, None] = 'a7c1e2d3f4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_NOTIFICATION_TYPES = [
    'REVIEW_REQUESTED',
    'REVIEW_ASSIGNED',
    'REVISION_STAGE_APPROVED',
    'REVISION_RETURNED',
    'REVISION_REJECTED',
    'REVISION_ESCALATED',
    'REVISION_READY_TO_PUBLISH',
    'REVISION_PUBLISHED',
    'REVIEW_COMMENT_ADDED',
    'REVISION_FORCE_APPROVED',
    'MARKS_AWAITING_MODERATION',
    'MARKS_RETURNED',
    'MARKS_DISPUTED',
    'MARKS_AWAITING_APPROVAL',
]


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


def _enum(name: str, *values: str) -> postgresql.ENUM:
    e = postgresql.ENUM(*values, name=name, create_type=False)
    e.create(op.get_bind(), checkfirst=True)
    return e


def upgrade() -> None:
    bind = op.get_bind()

    # Enum values can't be added and used in the same transaction, so the new
    # notification types land here but nothing below uses them.
    for value in _NEW_NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notification_type_enum ADD VALUE IF NOT EXISTS '{value}'")

    lifecycle = _enum('course_lifecycle_enum', 'DRAFT', 'PUBLISHED', 'ARCHIVED')
    kind = _enum('revision_kind_enum', 'INITIAL', 'CHANGE', 'ROLLBACK', 'REINSTATE')
    content_status = _enum(
        'content_status_enum',
        'DRAFT', 'SUBMITTED_FOR_REVIEW', 'ACADEMIC_REVIEW', 'RETURNED_FOR_REVISION', 'ACADEMICALLY_APPROVED',
        'ASSESSMENT_MODERATION', 'QA_REVIEW', 'QA_APPROVED', 'COURSE_APPROVED', 'FINAL_APPROVAL_REQUIRED',
        'READY_TO_PUBLISH', 'PUBLISHED', 'ARCHIVED', 'REJECTED', 'WITHDRAWN',
    )
    stage = _enum(
        'review_stage_enum',
        'QUICK_APPROVAL', 'ACADEMIC_REVIEW', 'ASSESSMENT_MODERATION', 'QA_REVIEW', 'COURSE_LEAD_APPROVAL',
        'FINAL_APPROVAL',
    )
    stage_status = _enum(
        'review_stage_status_enum',
        'PENDING', 'IN_REVIEW', 'APPROVED', 'APPROVED_WITH_CONDITIONS', 'RETURNED', 'REJECTED', 'SKIPPED',
        'SUPERSEDED',
    )
    decision = _enum(
        'review_decision_enum',
        'APPROVED', 'APPROVED_WITH_MINOR_CHANGES', 'RETURNED_FOR_REVISION', 'REJECTED', 'ESCALATED',
        'FORCE_APPROVED',
    )
    risk = _enum('risk_level_enum', 'LOW', 'MEDIUM', 'HIGH')
    design_status = _enum(
        'assessment_design_status_enum',
        'DRAFT', 'ACADEMIC_REVIEW', 'MODERATION', 'QA_REVIEW', 'APPROVED', 'LIVE', 'WITHDRAWN',
    )

    uuid_t = postgresql.UUID(as_uuid=True)

    op.create_table(
        'course_revisions',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('course_id', uuid_t, sa.ForeignKey('courses.id'), nullable=False),
        sa.Column('kind', kind, nullable=False),
        sa.Column('author_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('status', content_status, nullable=False),
        sa.Column('current_stage', stage, nullable=True),
        sa.Column('round', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('computed_risk', risk, nullable=True),
        sa.Column('declared_risk', risk, nullable=True),
        sa.Column('effective_risk', risk, nullable=True),
        sa.Column('risk_flags', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
        sa.Column('risk_reasons', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
        sa.Column('risk_override_by', uuid_t, nullable=True),
        sa.Column('risk_override_reason', sa.Text(), nullable=True),
        sa.Column('touches_assessment', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('required_stages', postgresql.ARRAY(sa.String()), nullable=False, server_default='{}'),
        sa.Column('base_version_id', uuid_t, nullable=True),
        sa.Column('proposed_version_label', sa.String(20), nullable=True),
        sa.Column('published_version_id', uuid_t, nullable=True),
        sa.Column('rollback_to_version_id', uuid_t, nullable=True),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('course_changes', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('diff_snapshot', postgresql.JSONB(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', uuid_t, nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lock_version', sa.Integer(), nullable=False, server_default='0'),
        *_base_entity_columns(),
    )
    op.create_index('ix_course_revisions_course_id', 'course_revisions', ['course_id'])
    op.create_index('ix_course_revisions_status', 'course_revisions', ['status'])
    op.execute(
        "CREATE UNIQUE INDEX uq_course_open_revision ON course_revisions (course_id) "
        "WHERE status NOT IN ('PUBLISHED','ARCHIVED','REJECTED','WITHDRAWN') AND deleted_at IS NULL"
    )

    op.create_table(
        'revision_contributors',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('first_edit_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_edit_at', sa.DateTime(timezone=True), nullable=False),
        *_base_entity_columns(),
        sa.UniqueConstraint('revision_id', 'user_id', name='uq_revision_contributor'),
    )
    op.create_index('ix_revision_contributors_revision_id', 'revision_contributors', ['revision_id'])
    op.create_index('ix_revision_contributors_user_id', 'revision_contributors', ['user_id'])

    op.create_table(
        'review_stages',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('stage', stage, nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('status', stage_status, nullable=False),
        sa.Column('assigned_reviewer_id', uuid_t, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('assigned_by', uuid_t, nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decided_by', uuid_t, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('conditions', postgresql.JSONB(), nullable=False, server_default='[]'),
        *_base_entity_columns(),
        sa.UniqueConstraint('revision_id', 'round', 'stage', name='uq_review_stage_round'),
    )
    op.create_index('ix_review_stages_revision_id', 'review_stages', ['revision_id'])
    op.create_index('ix_review_stages_assigned_reviewer_id', 'review_stages', ['assigned_reviewer_id'])
    op.create_index('ix_review_stages_open', 'review_stages', ['status', 'stage'])

    op.create_table(
        'review_decisions',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', uuid_t, sa.ForeignKey('review_stages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('stage', stage, nullable=True),
        sa.Column('round', sa.Integer(), nullable=False),
        sa.Column('decision', decision, nullable=False),
        sa.Column('actor_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('conditions', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('from_status', content_status, nullable=False),
        sa.Column('to_status', content_status, nullable=False),
        sa.Column('version_label', sa.String(20), nullable=True),
        *_base_entity_columns(),
    )
    op.create_index('ix_review_decisions_revision_id', 'review_decisions', ['revision_id'])
    op.create_index('ix_review_decisions_actor_created', 'review_decisions', ['actor_id', 'created_at'])

    op.create_table(
        'review_comments',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', uuid_t, sa.ForeignKey('review_stages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('parent_id', uuid_t, sa.ForeignKey('review_comments.id', ondelete='CASCADE'), nullable=True),
        sa.Column('author_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('anchor_type', sa.String(30), nullable=True),
        sa.Column('anchor_id', uuid_t, nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by', uuid_t, nullable=True),
        *_base_entity_columns(),
    )
    op.create_index('ix_review_comments_revision_id', 'review_comments', ['revision_id'])

    op.create_table(
        'review_evidence',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('stage_id', uuid_t, sa.ForeignKey('review_stages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('uploaded_by', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('storage_key', sa.String(1000), nullable=True),
        sa.Column('url', sa.String(2000), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('mime_type', sa.String(255), nullable=True),
        sa.Column('file_size_bytes', sa.Integer(), nullable=True),
        sa.Column('is_uploaded', sa.Boolean(), nullable=False, server_default='false'),
        *_base_entity_columns(),
    )
    op.create_index('ix_review_evidence_revision_id', 'review_evidence', ['revision_id'])

    op.create_table(
        'course_versions',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('course_id', uuid_t, sa.ForeignKey('courses.id'), nullable=False),
        sa.Column('major', sa.Integer(), nullable=False),
        sa.Column('minor', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(20), nullable=False),
        sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id'), nullable=True),
        sa.Column('snapshot', postgresql.JSONB(), nullable=True),
        sa.Column('snapshot_hash', sa.String(64), nullable=True),
        sa.Column('author_id', uuid_t, nullable=True),
        sa.Column('reviewer_ids', postgresql.ARRAY(uuid_t), nullable=False, server_default='{}'),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_by', uuid_t, nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('risk_level', risk, nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='false'),
        *_base_entity_columns(),
        sa.UniqueConstraint('course_id', 'major', 'minor', name='uq_course_version'),
    )
    op.create_index('ix_course_versions_course_id', 'course_versions', ['course_id'])

    # -- columns on existing tables ------------------------------------------------
    op.add_column('courses', sa.Column('governance_status', lifecycle, nullable=False, server_default='DRAFT'))
    op.add_column('courses', sa.Column('current_version_id', uuid_t, nullable=True))
    op.add_column('courses', sa.Column('current_version_label', sa.String(20), nullable=True))

    for table in ('course_sections', 'course_items'):
        op.add_column(table, sa.Column('revision_id', uuid_t, sa.ForeignKey('course_revisions.id'), nullable=True))
        op.add_column(table, sa.Column('draft_of_id', uuid_t, sa.ForeignKey(f'{table}.id'), nullable=True))
        op.create_index(f'ix_{table}_revision_id', table, ['revision_id'])
        op.create_index(f'ix_{table}_draft_of_id', table, ['draft_of_id'])

    for table in ('course_quiz_group_sections', 'course_quiz_questions', 'course_quiz_options'):
        op.add_column(table, sa.Column('draft_of_id', uuid_t, sa.ForeignKey(f'{table}.id'), nullable=True))

    op.add_column(
        'course_assessments', sa.Column('design_status', design_status, nullable=False, server_default='DRAFT')
    )

    # -- backfill --------------------------------------------------------------------
    # Every course published before governance becomes version 1.0, backed by a
    # synthetic INITIAL revision so the version has a revision to point at. The
    # 1.0 snapshot is left NULL here (building the content tree in SQL would be
    # fragile) - app/scripts/backfill_course_snapshots.py fills it, and the first
    # working copy of a course captures it lazily otherwise.
    op.execute(
        "UPDATE courses SET governance_status = "
        "(CASE WHEN is_published THEN 'PUBLISHED' ELSE 'DRAFT' END)::course_lifecycle_enum"
    )
    op.execute(
        """
        WITH baseline AS (
            SELECT id AS course_id, instructor_id, coalesce(updated_at, created_at) AS published_at,
                   gen_random_uuid() AS revision_id, gen_random_uuid() AS version_id
            FROM courses
            WHERE is_published AND deleted_at IS NULL
        ), revs AS (
            INSERT INTO course_revisions (
                id, course_id, kind, author_id, status, round, effective_risk, change_summary, reason,
                proposed_version_label, published_version_id, published_at, closed_at, created_at
            )
            SELECT revision_id, course_id, 'INITIAL', instructor_id, 'PUBLISHED', 0, 'HIGH',
                   'Imported baseline (published before content governance)', 'Baseline (pre-governance)',
                   '1.0', version_id, published_at, published_at, now()
            FROM baseline
            RETURNING id
        ), vers AS (
            INSERT INTO course_versions (
                id, course_id, major, minor, label, revision_id, author_id, published_at, approved_at,
                reason, risk_level, is_current, created_at
            )
            SELECT version_id, course_id, 1, 0, '1.0', revision_id, instructor_id, published_at, published_at,
                   'Baseline (pre-governance)', 'HIGH', true, now()
            FROM baseline
            RETURNING id
        ), audit AS (
            INSERT INTO governance_audit_log (
                id, occurred_at, actor_id, actor_permissions, entity_type, entity_id, course_id, revision_id,
                version_label, action, to_status, comment
            )
            SELECT gen_random_uuid(), now(), NULL, '{}', 'COURSE_VERSION', version_id, course_id, revision_id,
                   '1.0', 'BASELINE_IMPORTED', 'PUBLISHED', 'Published before content governance was introduced'
            FROM baseline
            RETURNING id
        )
        UPDATE courses c
        SET current_version_id = b.version_id, current_version_label = '1.0'
        FROM baseline b
        WHERE c.id = b.course_id
        """
    )
    op.execute(
        """
        UPDATE course_assessments a
        SET design_status = 'LIVE'
        FROM course_items i
        JOIN course_sections s ON s.id = i.section_id
        JOIN courses c ON c.id = s.course_id
        WHERE a.course_item_id = i.id AND c.is_published
        """
    )


def downgrade() -> None:
    op.drop_column('course_assessments', 'design_status')
    for table in ('course_quiz_group_sections', 'course_quiz_questions', 'course_quiz_options'):
        op.drop_column(table, 'draft_of_id')
    for table in ('course_sections', 'course_items'):
        op.drop_index(f'ix_{table}_draft_of_id', table_name=table)
        op.drop_index(f'ix_{table}_revision_id', table_name=table)
        op.drop_column(table, 'draft_of_id')
        op.drop_column(table, 'revision_id')
    op.drop_column('courses', 'current_version_label')
    op.drop_column('courses', 'current_version_id')
    op.drop_column('courses', 'governance_status')

    op.drop_table('course_versions')
    op.drop_table('review_evidence')
    op.drop_table('review_comments')
    op.drop_table('review_decisions')
    op.drop_table('review_stages')
    op.drop_table('revision_contributors')
    op.drop_table('course_revisions')

    bind = op.get_bind()
    for name in (
        'assessment_design_status_enum', 'risk_level_enum', 'review_decision_enum', 'review_stage_status_enum',
        'review_stage_enum', 'content_status_enum', 'revision_kind_enum', 'course_lifecycle_enum',
    ):
        sa.Enum(name=name).drop(bind, checkfirst=True)
    # The notification_type_enum values added in upgrade() can't be removed from
    # a Postgres enum; they are harmless when unused.
    # Note: audit rows written by the backfill stay (the audit log is append-only).
