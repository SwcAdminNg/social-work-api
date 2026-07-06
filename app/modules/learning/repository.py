import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.course.access_entity import UserCourseAccess
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.learning.entity import QuizAttempt, UserCourseProgress, UserItemProgress


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

    async def get_enrolled_courses_with_progress(self, user_id: uuid.UUID) -> list[tuple[Course, UserCourseProgress]]:
        stmt = (
            select(Course, UserCourseProgress)
            .join(UserCourseProgress, Course.id == UserCourseProgress.course_id)
            .join(UserCourseAccess, Course.id == UserCourseAccess.course_id)
            .where(
                UserCourseAccess.user_id == user_id,
                UserCourseProgress.user_id == user_id,
                Course.deleted_at.is_(None)
            )
            .order_by(UserCourseProgress.last_accessed_at.desc().nullslast())
        )
        result = await self.session.execute(stmt)
        return result.all()  # type: ignore

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
