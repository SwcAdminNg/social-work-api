"""add generic assessment system (quiz settings + essay)

Revision ID: d3e4f5a6b7c8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-14 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # -- new item type + assessment enums ------------------------------------
    op.execute("ALTER TYPE course_item_type_enum ADD VALUE IF NOT EXISTS 'ASSESSMENT'")
    # Postgres refuses to use a brand new enum value in the same transaction it
    # was added in ("unsafe use of new value"), and this migration needs to
    # UPDATE rows to 'ASSESSMENT' further down - commit here to close that
    # transaction before the value is used. env.py opens one transaction for
    # the whole `upgrade` run, so this is the only way to do both in one pass.
    op.execute("COMMIT")

    assessment_type_enum = postgresql.ENUM('QUIZ', 'ESSAY', name='assessment_type_enum', create_type=False)
    assessment_type_enum.create(bind, checkfirst=True)

    multi_answer_mode_enum = postgresql.ENUM('AND', 'OR', name='multi_answer_mode_enum', create_type=False)
    multi_answer_mode_enum.create(bind, checkfirst=True)

    essay_submission_mode_enum = postgresql.ENUM(
        'TEXT', 'DOCUMENT', name='essay_submission_mode_enum', create_type=False
    )
    essay_submission_mode_enum.create(bind, checkfirst=True)

    # -- course_assessments (replaces course_quizzes) ------------------------
    op.create_table(
        'course_assessments',
        sa.Column('course_item_id', sa.UUID(), nullable=False),
        sa.Column('assessment_type', assessment_type_enum, nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['course_item_id'], ['course_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_course_assessments_course_item_id'), 'course_assessments', ['course_item_id'], unique=True
    )

    op.create_table(
        'course_quiz_settings',
        sa.Column('assessment_id', sa.UUID(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('pass_mark_percentage', sa.Integer(), nullable=False),
        sa.Column('show_result_to_student', sa.Boolean(), nullable=False),
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
        op.f('ix_course_quiz_settings_assessment_id'), 'course_quiz_settings', ['assessment_id'], unique=True
    )

    op.create_table(
        'course_essay_settings',
        sa.Column('assessment_id', sa.UUID(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('submission_mode', essay_submission_mode_enum, nullable=False),
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
        op.f('ix_course_essay_settings_assessment_id'), 'course_essay_settings', ['assessment_id'], unique=True
    )

    # -- migrate existing quiz data (course_assessments reuses course_quizzes' PKs) --
    quizzes = bind.execute(
        sa.text("SELECT id, course_item_id, passing_score_percentage, created_at FROM course_quizzes")
    ).fetchall()
    for row in quizzes:
        bind.execute(
            sa.text(
                "INSERT INTO course_assessments (id, course_item_id, assessment_type, due_date, created_at) "
                "VALUES (:id, :course_item_id, 'QUIZ', NULL, :created_at)"
            ),
            {"id": row.id, "course_item_id": row.course_item_id, "created_at": row.created_at},
        )
        bind.execute(
            sa.text(
                "INSERT INTO course_quiz_settings "
                "(id, assessment_id, max_attempts, pass_mark_percentage, show_result_to_student, created_at) "
                "VALUES (:id, :assessment_id, NULL, :pass_mark, true, now())"
            ),
            {"id": uuid.uuid4(), "assessment_id": row.id, "pass_mark": row.passing_score_percentage},
        )
    bind.execute(sa.text("UPDATE course_items SET item_type = 'ASSESSMENT' WHERE item_type = 'QUIZ'"))

    # -- repoint course_quiz_questions from course_quizzes to course_assessments --
    op.alter_column('course_quiz_questions', 'quiz_id', new_column_name='assessment_id')
    op.drop_constraint('course_quiz_questions_quiz_id_fkey', 'course_quiz_questions', type_='foreignkey')
    op.create_foreign_key(
        'course_quiz_questions_assessment_id_fkey', 'course_quiz_questions', 'course_assessments',
        ['assessment_id'], ['id'],
    )
    op.drop_index('ix_course_quiz_questions_quiz_id', table_name='course_quiz_questions')
    op.create_index(
        op.f('ix_course_quiz_questions_assessment_id'), 'course_quiz_questions', ['assessment_id'], unique=False
    )
    op.add_column('course_quiz_questions', sa.Column('multi_answer_mode', multi_answer_mode_enum, nullable=True))

    # -- drop superseded table/column -----------------------------------------
    op.drop_index('ix_course_quizzes_course_item_id', table_name='course_quizzes')
    op.drop_table('course_quizzes')
    op.drop_column('course_items', 'passing_score')

    # -- essay submissions (learning module) -----------------------------------
    op.create_table(
        'essay_submissions',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('item_id', sa.UUID(), nullable=False),
        sa.Column('content_text', sa.Text(), nullable=True),
        sa.Column('document_storage_key', sa.String(length=1000), nullable=True),
        sa.Column('document_file_name', sa.String(length=255), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('graded_by', sa.UUID(), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint('user_id', 'item_id', name='uq_essay_submissions_user_item'),
    )
    op.create_index(op.f('ix_essay_submissions_item_id'), 'essay_submissions', ['item_id'], unique=False)
    op.create_index(op.f('ix_essay_submissions_user_id'), 'essay_submissions', ['user_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(op.f('ix_essay_submissions_user_id'), table_name='essay_submissions')
    op.drop_index(op.f('ix_essay_submissions_item_id'), table_name='essay_submissions')
    op.drop_table('essay_submissions')

    op.add_column('course_items', sa.Column('passing_score', sa.Integer(), nullable=True))

    op.create_table(
        'course_quizzes',
        sa.Column('course_item_id', sa.UUID(), nullable=False),
        sa.Column('passing_score_percentage', sa.Integer(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('updated_by', sa.UUID(), nullable=True),
        sa.Column('deleted_by', sa.UUID(), nullable=True),
        sa.Column('restored_by', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['course_item_id'], ['course_items.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_course_quizzes_course_item_id'), 'course_quizzes', ['course_item_id'], unique=True)

    quiz_assessments = bind.execute(
        sa.text(
            "SELECT a.id AS id, a.course_item_id AS course_item_id, "
            "COALESCE(s.pass_mark_percentage, 70) AS pass_mark_percentage, a.created_at AS created_at "
            "FROM course_assessments a "
            "LEFT JOIN course_quiz_settings s ON s.assessment_id = a.id "
            "WHERE a.assessment_type = 'QUIZ'"
        )
    ).fetchall()
    for row in quiz_assessments:
        bind.execute(
            sa.text(
                "INSERT INTO course_quizzes (id, course_item_id, passing_score_percentage, created_at) "
                "VALUES (:id, :course_item_id, :pass_mark_percentage, :created_at)"
            ),
            dict(row._mapping),
        )
    bind.execute(sa.text("UPDATE course_items SET item_type = 'QUIZ' WHERE item_type = 'ASSESSMENT'"))

    op.drop_column('course_quiz_questions', 'multi_answer_mode')
    op.drop_index(op.f('ix_course_quiz_questions_assessment_id'), table_name='course_quiz_questions')
    op.drop_constraint('course_quiz_questions_assessment_id_fkey', 'course_quiz_questions', type_='foreignkey')
    op.alter_column('course_quiz_questions', 'assessment_id', new_column_name='quiz_id')
    op.create_foreign_key(
        'course_quiz_questions_quiz_id_fkey', 'course_quiz_questions', 'course_quizzes',
        ['quiz_id'], ['id'],
    )
    op.create_index(op.f('ix_course_quiz_questions_quiz_id'), 'course_quiz_questions', ['quiz_id'], unique=False)

    op.drop_index(op.f('ix_course_essay_settings_assessment_id'), table_name='course_essay_settings')
    op.drop_table('course_essay_settings')
    op.drop_index(op.f('ix_course_quiz_settings_assessment_id'), table_name='course_quiz_settings')
    op.drop_table('course_quiz_settings')
    op.drop_index(op.f('ix_course_assessments_course_item_id'), table_name='course_assessments')
    op.drop_table('course_assessments')

    postgresql.ENUM(name='essay_submission_mode_enum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='multi_answer_mode_enum').drop(bind, checkfirst=True)
    postgresql.ENUM(name='assessment_type_enum').drop(bind, checkfirst=True)
    # Note: 'ASSESSMENT' cannot be cheaply removed from course_item_type_enum in
    # Postgres (values can't be dropped without recreating the type); left in
    # place as an unused legacy value, harmless since downgrade restores QUIZ usage.
