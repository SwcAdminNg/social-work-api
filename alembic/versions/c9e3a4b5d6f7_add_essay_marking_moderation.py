"""add essay marking moderation: essay_marks history, result status, moderation flag

Revision ID: c9e3a4b5d6f7
Revises: b8d2f3e4a5c6
Create Date: 2026-10-02 00:00:03.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c9e3a4b5d6f7'
down_revision: Union[str, None] = 'b8d2f3e4a5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    result_status = postgresql.ENUM(
        'DRAFT_MARK', 'AWAITING_MODERATION', 'RETURNED_TO_MARKER', 'MODERATED', 'APPROVED', 'PUBLISHED',
        'SUPERSEDED', 'UNDER_APPEAL',
        name='learner_result_status_enum', create_type=False,
    )
    result_status.create(bind, checkfirst=True)
    recommendation = postgresql.ENUM('PASS', 'FAIL', name='mark_recommendation_enum', create_type=False)
    recommendation.create(bind, checkfirst=True)

    uuid_t = postgresql.UUID(as_uuid=True)
    op.create_table(
        'essay_marks',
        sa.Column('id', uuid_t, primary_key=True),
        sa.Column('submission_id', uuid_t, sa.ForeignKey('essay_submissions.id'), nullable=False),
        sa.Column('item_id', uuid_t, sa.ForeignKey('course_items.id'), nullable=False),
        sa.Column('course_id', uuid_t, sa.ForeignKey('courses.id'), nullable=False),
        sa.Column('learner_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('attempt_no', sa.Integer(), nullable=False),
        sa.Column('status', result_status, nullable=False),
        sa.Column('marker_id', uuid_t, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('score', sa.Numeric(5, 2), nullable=False),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('recommendation', recommendation, nullable=True),
        sa.Column('submitted_for_moderation_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('moderator_id', uuid_t, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('moderated_score', sa.Numeric(5, 2), nullable=True),
        sa.Column('moderated_feedback', sa.Text(), nullable=True),
        sa.Column('moderation_note', sa.Text(), nullable=True),
        sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('disputed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('dispute_note', sa.Text(), nullable=True),
        sa.Column('approved_by', uuid_t, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('final_score', sa.Numeric(5, 2), nullable=True),
        sa.Column('final_feedback', sa.Text(), nullable=True),
        sa.Column('approval_note', sa.String(2000), nullable=True),
        sa.Column('published_by', uuid_t, nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', uuid_t, nullable=True),
        sa.Column('updated_by', uuid_t, nullable=True),
        sa.Column('deleted_by', uuid_t, nullable=True),
        sa.Column('restored_by', uuid_t, nullable=True),
    )
    for column in ('submission_id', 'item_id', 'course_id', 'learner_id'):
        op.create_index(f'ix_essay_marks_{column}', 'essay_marks', [column])
    op.create_index('ix_essay_marks_status_course', 'essay_marks', ['status', 'course_id'])

    op.add_column('essay_submissions', sa.Column('result_status', result_status, nullable=True))
    op.add_column(
        'course_essay_settings',
        sa.Column('requires_moderation', sa.Boolean(), nullable=False, server_default='false'),
    )

    # Final-assessment essays gate modules and certificates, so they start out
    # moderated (only takes effect once content governance is switched on).
    op.execute(
        """
        UPDATE course_essay_settings s
        SET requires_moderation = true
        FROM course_assessments a
        WHERE s.assessment_id = a.id AND a.is_final_assessment
        """
    )

    # Every existing grade becomes the first entry of its essay's mark history.
    op.execute(
        """
        INSERT INTO essay_marks (
            id, submission_id, item_id, course_id, learner_id, attempt_no, status, marker_id, score, feedback,
            final_score, final_feedback, approved_by, approved_at, published_by, published_at, created_at
        )
        SELECT gen_random_uuid(), e.id, e.item_id, sec.course_id, e.user_id, GREATEST(e.graded_attempts, 1),
               (CASE WHEN e.is_published THEN 'PUBLISHED' ELSE 'APPROVED' END)::learner_result_status_enum,
               e.graded_by, e.score, e.feedback, e.score, e.feedback, e.graded_by, e.graded_at,
               CASE WHEN e.is_published THEN e.graded_by END, CASE WHEN e.is_published THEN e.graded_at END,
               coalesce(e.graded_at, now())
        FROM essay_submissions e
        JOIN course_items i ON i.id = e.item_id
        JOIN course_sections sec ON sec.id = i.section_id
        WHERE e.score IS NOT NULL AND e.graded_by IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE essay_submissions
        SET result_status = (CASE WHEN is_published THEN 'PUBLISHED' ELSE 'APPROVED' END)::learner_result_status_enum
        WHERE score IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('course_essay_settings', 'requires_moderation')
    op.drop_column('essay_submissions', 'result_status')
    op.drop_table('essay_marks')
    bind = op.get_bind()
    sa.Enum(name='mark_recommendation_enum').drop(bind, checkfirst=True)
    sa.Enum(name='learner_result_status_enum').drop(bind, checkfirst=True)
