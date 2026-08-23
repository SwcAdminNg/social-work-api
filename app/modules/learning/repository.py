import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.common.pagination import PaginationParams

from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.learning.entity import (
    EssaySubmission,
    QuizAttempt,
    QuizGroupAttempt,
    QuizGroupAttemptStatusEnum,
    UserCourseProgress,
    UserItemProgress,
)
from app.modules.user.entity import User


class LearningRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_user_course_progress(self, user_id: uuid.UUID, course_id: uuid.UUID) -> UserCourseProgress | None:
        stmt = select(UserCourseProgress).where(
            UserCourseProgress.user_id == user_id,
            UserCourseProgress.course_id == course_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_user_course_progress(self, user_id: uuid.UUID, course_id: uuid.UUID) -> UserCourseProgress:
        progress = UserCourseProgress(user_id=user_id, course_id=course_id)
        self.session.add(progress)
        await self.session.flush()
        return progress

    async def update_user_course_progress(
        self, progress: UserCourseProgress, percent: int, is_completed: bool
    ) -> None:
        progress.progress_percent = percent
        progress.is_completed = is_completed
        progress.last_accessed_at = datetime.now(timezone.utc)
        self.session.add(progress)
        await self.session.flush()

    async def get_user_item_progress(self, user_id: uuid.UUID, item_id: uuid.UUID) -> UserItemProgress | None:
        stmt = select(UserItemProgress).where(
            UserItemProgress.user_id == user_id,
            UserItemProgress.item_id == item_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def mark_item_completed(self, user_id: uuid.UUID, item_id: uuid.UUID) -> UserItemProgress:
        progress = await self.get_user_item_progress(user_id, item_id)
        if not progress:
            progress = UserItemProgress(
                user_id=user_id, item_id=item_id, is_completed=True, completed_at=datetime.now(timezone.utc)
            )
            self.session.add(progress)
        elif not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = datetime.now(timezone.utc)
            self.session.add(progress)
        await self.session.flush()
        return progress

    async def save_quiz_attempt(
        self, user_id: uuid.UUID, item_id: uuid.UUID, score: float, passed: bool, answers: dict
    ) -> QuizAttempt:
        attempt = QuizAttempt(user_id=user_id, item_id=item_id, score=score, passed=passed, answers=answers)
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def get_latest_quiz_attempt(self, user_id: uuid.UUID, item_id: uuid.UUID) -> QuizAttempt | None:
        stmt = (
            select(QuizAttempt)
            .where(QuizAttempt.user_id == user_id, QuizAttempt.item_id == item_id)
            .order_by(QuizAttempt.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def count_quiz_attempts(self, user_id: uuid.UUID, item_id: uuid.UUID) -> int:
        stmt = select(func.count(QuizAttempt.id)).where(
            QuizAttempt.user_id == user_id, QuizAttempt.item_id == item_id
        )
        return (await self.session.execute(stmt)).scalar() or 0

    # -- quiz group attempts -----------------------------------------------------

    async def get_in_progress_quiz_group_attempt(
        self, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> QuizGroupAttempt | None:
        stmt = select(QuizGroupAttempt).where(
            QuizGroupAttempt.user_id == user_id,
            QuizGroupAttempt.item_id == item_id,
            QuizGroupAttempt.status == QuizGroupAttemptStatusEnum.IN_PROGRESS,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_quiz_group_attempt(self, attempt_id: uuid.UUID) -> QuizGroupAttempt | None:
        stmt = select(QuizGroupAttempt).where(QuizGroupAttempt.id == attempt_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_quiz_group_attempt(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        started_at: datetime,
        expires_at: datetime | None,
        selected_questions: dict,
    ) -> QuizGroupAttempt:
        attempt = QuizGroupAttempt(
            user_id=user_id,
            item_id=item_id,
            started_at=started_at,
            expires_at=expires_at,
            selected_questions=selected_questions,
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt

    async def save_quiz_group_progress(self, attempt: QuizGroupAttempt, answers: dict) -> QuizGroupAttempt:
        attempt.answers = answers
        await self.session.flush()
        return attempt

    async def finalize_quiz_group_attempt(
        self,
        attempt: QuizGroupAttempt,
        score: float,
        passed: bool,
        section_scores: list,
        answers: dict,
        auto_submitted: bool,
    ) -> QuizGroupAttempt:
        attempt.status = QuizGroupAttemptStatusEnum.SUBMITTED
        attempt.score = score
        attempt.passed = passed
        attempt.section_scores = section_scores
        attempt.answers = answers
        attempt.auto_submitted = auto_submitted
        attempt.submitted_at = datetime.now(timezone.utc)
        await self.session.flush()
        return attempt

    async def count_quiz_group_attempts(self, user_id: uuid.UUID, item_id: uuid.UUID) -> int:
        stmt = select(func.count(QuizGroupAttempt.id)).where(
            QuizGroupAttempt.user_id == user_id,
            QuizGroupAttempt.item_id == item_id,
            QuizGroupAttempt.status == QuizGroupAttemptStatusEnum.SUBMITTED,
        )
        return (await self.session.execute(stmt)).scalar() or 0

    async def list_quiz_group_attempts(
        self, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> Sequence[QuizGroupAttempt]:
        """All attempts (any status), oldest first - used to figure out which
        questions the student has already been shown so a new attempt can favor
        ones they haven't seen yet."""
        stmt = (
            select(QuizGroupAttempt)
            .where(QuizGroupAttempt.user_id == user_id, QuizGroupAttempt.item_id == item_id)
            .order_by(QuizGroupAttempt.created_at.asc())
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_latest_submitted_quiz_group_attempt(
        self, user_id: uuid.UUID, item_id: uuid.UUID
    ) -> QuizGroupAttempt | None:
        stmt = (
            select(QuizGroupAttempt)
            .where(
                QuizGroupAttempt.user_id == user_id,
                QuizGroupAttempt.item_id == item_id,
                QuizGroupAttempt.status == QuizGroupAttemptStatusEnum.SUBMITTED,
            )
            .order_by(QuizGroupAttempt.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    # -- essay submissions -----------------------------------------------------

    async def get_essay_submission(self, user_id: uuid.UUID, item_id: uuid.UUID) -> EssaySubmission | None:
        stmt = select(EssaySubmission).where(
            EssaySubmission.user_id == user_id, EssaySubmission.item_id == item_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert_essay_submission(
        self,
        user_id: uuid.UUID,
        item_id: uuid.UUID,
        content_text: str | None = None,
        document_storage_key: str | None = None,
        document_file_name: str | None = None,
    ) -> EssaySubmission:
        submission = await self.get_essay_submission(user_id, item_id)
        now = datetime.now(timezone.utc)
        if submission is None:
            submission = EssaySubmission(
                user_id=user_id,
                item_id=item_id,
                content_text=content_text,
                document_storage_key=document_storage_key,
                document_file_name=document_file_name,
                submitted_at=now,
            )
            self.session.add(submission)
        else:
            if content_text is not None:
                submission.content_text = content_text
                submission.document_storage_key = None
                submission.document_file_name = None
            if document_storage_key is not None:
                submission.document_storage_key = document_storage_key
                submission.document_file_name = document_file_name
                submission.content_text = None
            submission.submitted_at = now
        await self.session.flush()
        return submission

    async def list_essay_submissions_for_item(
        self, item_id: uuid.UUID, pagination: PaginationParams
    ) -> tuple[list[tuple[EssaySubmission, User]], int]:
        stmt = (
            select(EssaySubmission, User)
            .join(User, User.id == EssaySubmission.user_id)
            .where(EssaySubmission.item_id == item_id)
        )
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar_one()

        stmt = stmt.order_by(EssaySubmission.submitted_at.desc()).limit(pagination.limit).offset(pagination.offset)
        result = await self.session.execute(stmt)
        return result.all(), total

    async def grade_essay_submission(
        self,
        submission: EssaySubmission,
        score: float,
        feedback: str | None,
        is_published: bool,
        graded_by: uuid.UUID,
    ) -> EssaySubmission:
        submission.score = score
        submission.feedback = feedback
        submission.is_published = is_published
        submission.graded_by = graded_by
        submission.graded_at = datetime.now(timezone.utc)
        await self.session.flush()
        return submission

    async def count_course_items(self, course_id: uuid.UUID) -> int:
        stmt = (
            select(func.count(CourseItem.id))
            .join(CourseSection, CourseItem.section_id == CourseSection.id)
            .where(CourseSection.course_id == course_id, CourseItem.deleted_at.is_(None), CourseSection.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def count_completed_items(self, user_id: uuid.UUID, course_id: uuid.UUID) -> int:
        stmt = (
            select(func.count(UserItemProgress.id))
            .join(CourseItem, UserItemProgress.item_id == CourseItem.id)
            .join(CourseSection, CourseItem.section_id == CourseSection.id)
            .where(
                UserItemProgress.user_id == user_id,
                CourseSection.course_id == course_id,
                UserItemProgress.is_completed.is_(True),
                CourseItem.deleted_at.is_(None),
                CourseSection.deleted_at.is_(None)
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def get_enrolled_courses_with_progress(self, user_id: uuid.UUID, pagination: "PaginationParams") -> tuple[list[tuple[Course, UserCourseProgress]], int]:
        stmt = (
            select(Course, UserCourseProgress)
            .join(UserCourseProgress, Course.id == UserCourseProgress.course_id)
            .join(UserCourseAccess, Course.id == UserCourseAccess.course_id)
            .where(
                UserCourseAccess.user_id == user_id,
                UserCourseProgress.user_id == user_id,
                Course.deleted_at.is_(None)
            )
        )
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(total_stmt)).scalar_one()

        stmt = stmt.order_by(UserCourseProgress.last_accessed_at.desc().nullslast())
        stmt = stmt.limit(pagination.limit).offset(pagination.offset)
        result = await self.session.execute(stmt)
        return result.all(), total

    async def get_user_course_access(self, user_id: uuid.UUID, course_id: uuid.UUID) -> UserCourseAccess | None:
        stmt = select(UserCourseAccess).where(
            UserCourseAccess.user_id == user_id,
            UserCourseAccess.course_id == course_id,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def grant_course_access(self, user_id: uuid.UUID, course_id: uuid.UUID, granted_via: str) -> UserCourseAccess:
        access = UserCourseAccess(user_id=user_id, course_id=course_id, granted_via=granted_via)
        self.session.add(access)
        await self.session.flush()
        return access

    async def list_user_assessments(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID | None = None,
        assessment_type: str | None = None,
    ):
        """All ASSESSMENT items (quiz or essay) the user has course access to, with
        their latest quiz attempt / essay submission joined in. No pagination or
        status filtering here - status depends on per-assessment visibility rules
        (show_result_to_student / is_published) that only the service layer knows
        how to apply, so the service paginates/filters the mapped DTOs instead."""
        from app.modules.course.entity import Course, CourseSection, CourseItem, CourseItemTypeEnum
        from app.modules.course.access_entity import UserCourseAccess
        from app.modules.course.content_entity import CourseAssessment, CourseQuizGroupSettings, CourseQuizSettings
        from sqlalchemy.orm import aliased

        subq = (
            select(
                QuizAttempt.item_id,
                func.max(QuizAttempt.created_at).label("latest_attempt_at")
            )
            .where(QuizAttempt.user_id == user_id)
            .group_by(QuizAttempt.item_id)
            .subquery()
        )

        latest_attempt = aliased(QuizAttempt)

        attempt_count = (
            select(func.count(QuizAttempt.id))
            .where(QuizAttempt.item_id == CourseItem.id, QuizAttempt.user_id == user_id)
            .correlate(CourseItem)
            .scalar_subquery()
        )

        group_subq = (
            select(
                QuizGroupAttempt.item_id,
                func.max(QuizGroupAttempt.created_at).label("latest_attempt_at"),
            )
            .where(
                QuizGroupAttempt.user_id == user_id,
                QuizGroupAttempt.status == QuizGroupAttemptStatusEnum.SUBMITTED,
            )
            .group_by(QuizGroupAttempt.item_id)
            .subquery()
        )

        latest_group_attempt = aliased(QuizGroupAttempt)

        group_attempt_count = (
            select(func.count(QuizGroupAttempt.id))
            .where(
                QuizGroupAttempt.item_id == CourseItem.id,
                QuizGroupAttempt.user_id == user_id,
                QuizGroupAttempt.status == QuizGroupAttemptStatusEnum.SUBMITTED,
            )
            .correlate(CourseItem)
            .scalar_subquery()
        )

        stmt = (
            select(
                CourseItem, Course, CourseAssessment, CourseQuizSettings, latest_attempt, EssaySubmission,
                attempt_count, CourseQuizGroupSettings, latest_group_attempt, group_attempt_count,
            )
            .join(CourseSection, CourseItem.section_id == CourseSection.id)
            .join(Course, CourseSection.course_id == Course.id)
            .join(UserCourseAccess, UserCourseAccess.course_id == Course.id)
            .join(CourseAssessment, CourseAssessment.course_item_id == CourseItem.id)
            .outerjoin(CourseQuizSettings, CourseQuizSettings.assessment_id == CourseAssessment.id)
            .outerjoin(
                subq,
                CourseItem.id == subq.c.item_id
            )
            .outerjoin(
                latest_attempt,
                (latest_attempt.item_id == CourseItem.id) &
                (latest_attempt.user_id == user_id) &
                (latest_attempt.created_at == subq.c.latest_attempt_at)
            )
            .outerjoin(
                EssaySubmission,
                (EssaySubmission.item_id == CourseItem.id) & (EssaySubmission.user_id == user_id)
            )
            .outerjoin(CourseQuizGroupSettings, CourseQuizGroupSettings.assessment_id == CourseAssessment.id)
            .outerjoin(group_subq, CourseItem.id == group_subq.c.item_id)
            .outerjoin(
                latest_group_attempt,
                (latest_group_attempt.item_id == CourseItem.id) &
                (latest_group_attempt.user_id == user_id) &
                (latest_group_attempt.created_at == group_subq.c.latest_attempt_at)
            )
            .where(
                UserCourseAccess.user_id == user_id,
                CourseItem.item_type == CourseItemTypeEnum.ASSESSMENT,
                CourseItem.deleted_at.is_(None),
                CourseSection.deleted_at.is_(None),
                Course.deleted_at.is_(None)
            )
        )

        if course_id:
            stmt = stmt.where(Course.id == course_id)

        if assessment_type:
            stmt = stmt.where(CourseAssessment.assessment_type == assessment_type)

        stmt = stmt.order_by(CourseItem.created_at.desc())
        result = await self.session.execute(stmt)
        return result.all()
