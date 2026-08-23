"""add nested quiz group assessment type

Revision ID: b4608bdef337
Revises: f5a6b7c8d9e0
Create Date: 2026-08-23 16:04:44.600186

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4608bdef337'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE assessment_type_enum ADD VALUE IF NOT EXISTS 'QUIZ_GROUP'")
    op.execute("ALTER TYPE activity_type_enum ADD VALUE IF NOT EXISTS 'QUIZ_GROUP_COMPLETED'")

    quiz_group_attempt_status_enum = postgresql.ENUM(
        'IN_PROGRESS', 'SUBMITTED', name='quiz_group_attempt_status_enum', create_type=False
    )
    quiz_group_attempt_status_enum.create(op.get_bind(), checkfirst=True)

    # -- course_quiz_group_settings (settings table for a QUIZ_GROUP assessment) --
    op.create_table(
        'course_quiz_group_settings',
        sa.Column('assessment_id', sa.UUID(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('pass_mark_percentage', sa.Integer(), nullable=False),
        sa.Column('show_result_to_student', sa.Boolean(), nullable=False),
        sa.Column('time_limit_seconds', sa.Integer(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['assessment_id'], ['course_assessments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_quiz_group_settings_assessment_id'), 'course_quiz_group_settings',
        ['assessment_id'], unique=True,
    )

    # -- course_quiz_group_sections (the nested quizzes - named question pools) --
    op.create_table(
        'course_quiz_group_sections',
        sa.Column('assessment_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False),
        sa.Column('questions_to_ask', sa.Integer(), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['assessment_id'], ['course_assessments.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_quiz_group_sections_assessment_id'), 'course_quiz_group_sections',
        ['assessment_id'], unique=False,
    )

    # -- course_quiz_questions grows an optional section_id, for questions that --
    # -- belong to a quiz-group section's pool instead of a standalone quiz ------
    op.add_column('course_quiz_questions', sa.Column('section_id', sa.UUID(), nullable=True))
    op.create_index(
        op.f('ix_course_quiz_questions_section_id'), 'course_quiz_questions', ['section_id'], unique=False
    )
    op.create_foreign_key(
        'course_quiz_questions_section_id_fkey', 'course_quiz_questions', 'course_quiz_group_sections',
        ['section_id'], ['id'],
    )

    # -- quiz_group_attempts (learning module - one row per started attempt) -----
    op.create_table(
        'quiz_group_attempts',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('status', quiz_group_attempt_status_enum, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('auto_submitted', sa.Boolean(), nullable=False),
        sa.Column('selected_questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=True),
        sa.Column('section_scores', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['item_id'], ['course_items.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_quiz_group_attempts_item_id'), 'quiz_group_attempts', ['item_id'], unique=False)
    op.create_index(op.f('ix_quiz_group_attempts_user_id'), 'quiz_group_attempts', ['user_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(op.f('ix_quiz_group_attempts_user_id'), table_name='quiz_group_attempts')
    op.drop_index(op.f('ix_quiz_group_attempts_item_id'), table_name='quiz_group_attempts')
    op.drop_table('quiz_group_attempts')

    op.drop_constraint('course_quiz_questions_section_id_fkey', 'course_quiz_questions', type_='foreignkey')
    op.drop_index(op.f('ix_course_quiz_questions_section_id'), table_name='course_quiz_questions')
    op.drop_column('course_quiz_questions', 'section_id')

    op.drop_index(op.f('ix_course_quiz_group_sections_assessment_id'), table_name='course_quiz_group_sections')
    op.drop_table('course_quiz_group_sections')

    op.drop_index(op.f('ix_course_quiz_group_settings_assessment_id'), table_name='course_quiz_group_settings')
    op.drop_table('course_quiz_group_settings')

    postgresql.ENUM(name='quiz_group_attempt_status_enum').drop(bind, checkfirst=True)

    # Note: 'QUIZ_GROUP'/'QUIZ_GROUP_COMPLETED' can't be cheaply removed from
    # assessment_type_enum/activity_type_enum in Postgres (values can't be dropped
    # without recreating the type); left in place as unused legacy values. Safe as
    # long as no QUIZ_GROUP assessments were created before downgrading - the
    # tables that would hold their data (course_quiz_group_settings/sections,
    # quiz_group_attempts) are dropped above.
