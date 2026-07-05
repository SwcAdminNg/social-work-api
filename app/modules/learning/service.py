import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.access_entity import CourseAccessGrantedViaEnum
from app.modules.course.entity import CourseItemTypeEnum
from app.modules.course.content_repository import CourseContentRepository
from app.modules.course.repository import CourseRepository
from app.modules.learning.dto import (
    CourseCurriculumDTO,
    EnrolledCourseDTO,
    LearningItemContentDTO,
    LearningItemDTO,
    LearningSectionDTO,
    QuizQuestionDTO,
    QuizResultDTO,
)
from app.modules.learning.repository import LearningRepository
from app.modules.payment.entity import UserSubscription
from app.modules.learning.entity import UserItemProgress


class LearningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LearningRepository(session)
        self.course_repo = CourseRepository(session)
        self.content_repo = CourseContentRepository(session)

    async def _has_active_subscription(self, user_id: uuid.UUID) -> bool:
        stmt = select(UserSubscription).where(
            UserSubscription.user_id == user_id,
            UserSubscription.is_active.is_(True),
            UserSubscription.end_date > datetime.now(timezone.utc)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def _recalculate_progress(self, user_id: uuid.UUID, course_id: uuid.UUID) -> None:
        total_items = await self.repo.count_course_items(course_id)
        if total_items == 0:
            return

        completed_items = await self.repo.count_completed_items(user_id, course_id)
        percent = int((completed_items / total_items) * 100)
        is_completed = completed_items == total_items

        progress = await self.repo.get_user_course_progress(user_id, course_id)
        if progress:
            await self.repo.update_user_course_progress(progress, percent, is_completed)

    async def enroll_course(self, user_id: uuid.UUID, course_id: uuid.UUID) -> dict:
        course = await self.course_repo.get(course_id)
        if not course:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

        access = await self.repo.get_user_course_access(user_id, course_id)
        if access:
            # Already enrolled
            progress = await self.repo.get_user_course_progress(user_id, course_id)
            if not progress:
                await self.repo.create_user_course_progress(user_id, course_id)
            return {"message": "Already enrolled"}

        # Check access logic
        granted_via = None
        if course.is_free:
            granted_via = CourseAccessGrantedViaEnum.FREE.value
        elif not course.is_exclusive and await self._has_active_subscription(user_id):
            granted_via = CourseAccessGrantedViaEnum.SUBSCRIPTION.value
        else:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Payment required to enroll in this course"
            )

        await self.repo.grant_course_access(user_id, course_id, granted_via)
        await self.repo.create_user_course_progress(user_id, course_id)

        return {"message": "Successfully enrolled"}

    async def list_enrolled_courses(self, user_id: uuid.UUID) -> list[EnrolledCourseDTO]:
        records = await self.repo.get_enrolled_courses_with_progress(user_id)
        result = []
        for course, progress in records:
            dto = EnrolledCourseDTO(
                **course.__dict__,
                progress_percent=progress.progress_percent,
                is_completed=progress.is_completed
            )
            result.append(dto)
        return result

    async def get_curriculum(self, user_id: uuid.UUID, course_id: uuid.UUID) -> CourseCurriculumDTO:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        progress = await self.repo.get_user_course_progress(user_id, course_id)
        if not progress:
            progress = await self.repo.create_user_course_progress(user_id, course_id)

        sections = await self.content_repo.list_sections(course_id)
        section_ids = [s.id for s in sections]
        items = await self.content_repo.list_items_for_sections(section_ids)

        # Get all completed items for this user
        stmt = select(UserItemProgress.item_id).where(
            UserItemProgress.user_id == user_id, UserItemProgress.is_completed.is_(True)
        )
        completed_item_ids = set((await self.session.execute(stmt)).scalars().all())

        section_dtos = []
        for section in sections:
            section_items = [i for i in items if i.section_id == section.id]
            item_dtos = [
                LearningItemDTO(
                    id=i.id, title=i.title, item_type=i.item_type, is_completed=i.id in completed_item_ids
                )
                for i in section_items
            ]
            section_dtos.append(LearningSectionDTO(id=section.id, title=section.title, items=item_dtos))

        return CourseCurriculumDTO(
            course_id=course_id,
            progress_percent=progress.progress_percent,
            is_completed=progress.is_completed,
            sections=section_dtos
        )

    async def get_item_content(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID) -> LearningItemContentDTO:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.section_id not in [s.id for s in await self.content_repo.list_sections(course_id)]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

        item_progress = await self.repo.get_user_item_progress(user_id, item_id)
        is_completed = item_progress.is_completed if item_progress else False

        dto = LearningItemContentDTO(
            id=item.id, title=item.title, item_type=item.item_type, is_completed=is_completed
        )

        if item.item_type == CourseItemTypeEnum.VIDEO:
            video = await self.content_repo.get_video_by_item(item_id)
            if video:
                dto.video_url = video.hls_url or video.mp4_url
        elif item.item_type == CourseItemTypeEnum.DOCUMENT:
            doc = await self.content_repo.get_document_by_item(item_id)
            if doc:
                dto.document_url = f"/api/v1/courses/items/{item_id}/download" # Assume this endpoint exists
        elif item.item_type == CourseItemTypeEnum.QUIZ:
            quiz = await self.content_repo.get_quiz_by_item(item_id)
            if quiz:
                questions = await self.content_repo.list_questions_for_quizzes([quiz.id])
                q_ids = [q.id for q in questions]
                options = await self.content_repo.list_options_for_questions(q_ids)
                
                dto.questions = []
                for q in questions:
                    q_opts = [{"id": o.id, "text": o.text} for o in options if o.question_id == q.id]
                    dto.questions.append(
                        QuizQuestionDTO(id=q.id, text=q.text, allow_multiple_answers=q.allow_multiple_answers, options=q_opts)
                    )

        return dto

    async def mark_item_completed(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID) -> dict:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type == CourseItemTypeEnum.QUIZ:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot manually complete a quiz item")

        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)
        return {"message": "Item marked as completed"}

    async def submit_quiz(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, answers: dict[uuid.UUID, list[uuid.UUID]]) -> QuizResultDTO:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type != CourseItemTypeEnum.QUIZ:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not a quiz")

        quiz = await self.content_repo.get_quiz_by_item(item_id)
        if not quiz:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")

        questions = await self.content_repo.list_questions_for_quizzes([quiz.id])
        q_ids = [q.id for q in questions]
        options = await self.content_repo.list_options_for_questions(q_ids)

        correct_answers = {}
        total_questions = len(questions)
        correct_count = 0

        for q in questions:
            correct_opts = [o.id for o in options if o.question_id == q.id and o.is_correct]
            correct_answers[q.id] = correct_opts
            
            user_ans = answers.get(q.id, [])
            if set(user_ans) == set(correct_opts):
                correct_count += 1

        score_percent = (correct_count / total_questions * 100) if total_questions > 0 else 0
        passing_score = item.passing_score if item.passing_score is not None else 70
        passed = score_percent >= passing_score

        # Convert UUID keys to strings for JSONB serialization
        answers_str_keys = {str(k): [str(v) for v in val] for k, val in answers.items()}
        await self.repo.save_quiz_attempt(user_id, item_id, score_percent, passed, answers_str_keys)

        if passed:
            await self.repo.mark_item_completed(user_id, item_id)
            await self._recalculate_progress(user_id, course_id)

        return QuizResultDTO(
            score=score_percent,
            passed=passed,
            correct_answers=correct_answers
        )
