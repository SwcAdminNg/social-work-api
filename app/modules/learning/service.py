import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.access_entity import CourseAccessGrantedViaEnum
from app.modules.course.entity import CourseItemTypeEnum
from app.modules.course.content_entity import AssessmentTypeEnum, EssaySubmissionModeEnum, MultiAnswerModeEnum
from app.modules.course.content_repository import CourseContentRepository
from app.modules.course.repository import CourseRepository
from app.modules.learning.dto import (
    AssessmentStatsDTO,
    CourseCurriculumDTO,
    EnrolledCourseDTO,
    EssaySubmissionDTO,
    EssayUploadUrlResponseDTO,
    LearningItemContentDTO,
    LearningItemDTO,
    LearningSectionDTO,
    QuizAttemptDTO,
    QuizQuestionDTO,
    QuizResultDTO,
    UserAssessmentDTO,
    UserAssessmentStatusEnum,
)
from app.common.pagination import PaginationParams
from app.core.storage import get_r2_client
from app.modules.learning.repository import LearningRepository
from app.modules.payment.entity import UserSubscription
from app.modules.learning.entity import EssaySubmission, UserItemProgress
from app.modules.user.activity_entity import ActivityTypeEnum
from app.modules.user.activity_service import ActivityService


class LearningService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LearningRepository(session)
        self.course_repo = CourseRepository(session)
        self.content_repo = CourseContentRepository(session)
        self.activity_service = ActivityService(session)
        self._r2 = None

    @property
    def r2(self):
        if self._r2 is None:
            self._r2 = get_r2_client()
        return self._r2

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
        course = await self.course_repo.get_by_id(course_id)
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
        
        await self.activity_service.log_activity(
            user_id,
            ActivityTypeEnum.COURSE_ENROLLED,
            {"course_id": str(course_id), "course_title": course.title}
        )
        
        await self.session.commit()

        return {"message": "Successfully enrolled"}

    async def list_enrolled_courses(self, user_id: uuid.UUID, pagination: PaginationParams) -> tuple[list[EnrolledCourseDTO], int]:
        records, total = await self.repo.get_enrolled_courses_with_progress(user_id, pagination)
        result = []
        for course, progress in records:
            dto = EnrolledCourseDTO(
                **course.__dict__,
                progress_percent=progress.progress_percent,
                is_completed=progress.is_completed,
                is_enrolled=True
            )
            result.append(dto)
        return result, total

    async def get_curriculum(self, user_id: uuid.UUID, course_id: uuid.UUID) -> CourseCurriculumDTO:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        progress = await self.repo.get_user_course_progress(user_id, course_id)
        if not progress:
            progress = await self.repo.create_user_course_progress(user_id, course_id)
            await self.session.commit()

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
                    id=i.id, title=i.title, item_type=i.item_type, is_completed=i.id in completed_item_ids,
                    estimated_minutes=i.estimated_minutes,
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
            id=item.id, title=item.title, item_type=item.item_type, is_completed=is_completed,
            estimated_minutes=item.estimated_minutes,
        )

        if item.item_type == CourseItemTypeEnum.VIDEO:
            video = await self.content_repo.get_video_by_item(item_id)
            if video:
                from app.core.bunny import get_bunny_client
                bunny = get_bunny_client()
                dto.video_url = bunny.build_playback_url(video.bunny_video_guid)
        elif item.item_type == CourseItemTypeEnum.DOCUMENT:
            doc = await self.content_repo.get_document_by_item(item_id)
            if doc:
                dto.document_url = self.r2.generate_download_url(doc.storage_key)
        elif item.item_type == CourseItemTypeEnum.ASSESSMENT:
            assessment = await self.content_repo.get_assessment_by_item(item_id)
            if assessment:
                dto.assessment_type = assessment.assessment_type
                dto.due_date = assessment.due_date

                if assessment.assessment_type == AssessmentTypeEnum.QUIZ:
                    await self._fill_quiz_content(dto, user_id, item_id, assessment)
                elif assessment.assessment_type == AssessmentTypeEnum.ESSAY:
                    await self._fill_essay_content(dto, user_id, item_id, assessment)

        return dto

    async def _fill_quiz_content(self, dto: LearningItemContentDTO, user_id: uuid.UUID, item_id: uuid.UUID, assessment) -> None:
        settings = await self.content_repo.get_quiz_settings(assessment.id)
        pass_mark_percentage = settings.pass_mark_percentage if settings else 70
        show_result_to_student = settings.show_result_to_student if settings else True
        max_attempts = settings.max_attempts if settings else None

        questions = await self.content_repo.list_questions_for_quizzes([assessment.id])
        q_ids = [q.id for q in questions]
        options = await self.content_repo.list_options_for_questions(q_ids)

        dto.questions = []
        for q in questions:
            q_opts = [{"id": o.id, "text": o.text} for o in options if o.question_id == q.id]
            dto.questions.append(
                QuizQuestionDTO(
                    id=q.id, text=q.text, allow_multiple_answers=q.allow_multiple_answers,
                    multi_answer_mode=q.multi_answer_mode, options=q_opts,
                )
            )

        attempts_used = await self.repo.count_quiz_attempts(user_id, item_id)
        dto.max_attempts = max_attempts
        dto.attempts_used = attempts_used
        dto.attempts_remaining = None if max_attempts is None else max(max_attempts - attempts_used, 0)
        dto.pass_mark_percentage = pass_mark_percentage
        dto.show_result_to_student = show_result_to_student

        attempt = await self.repo.get_latest_quiz_attempt(user_id, item_id)
        if attempt:
            answers_dict = {}
            if attempt.answers:
                for k, v in attempt.answers.items():
                    answers_dict[uuid.UUID(k)] = [uuid.UUID(opt_id) for opt_id in v]

            dto.previous_attempt = QuizAttemptDTO(
                score=float(attempt.score) if show_result_to_student else None,
                passed=attempt.passed if show_result_to_student else None,
                answers=(answers_dict if attempt.answers else None) if show_result_to_student else None,
                result_visible=show_result_to_student,
            )

    async def _fill_essay_content(self, dto: LearningItemContentDTO, user_id: uuid.UUID, item_id: uuid.UUID, assessment) -> None:
        essay_settings = await self.content_repo.get_essay_settings(assessment.id)
        if essay_settings:
            dto.essay_question = essay_settings.question
            dto.essay_description = essay_settings.description
            dto.essay_submission_mode = essay_settings.submission_mode

        submission = await self.repo.get_essay_submission(user_id, item_id)
        if submission:
            dto.essay_submission = self._build_essay_submission_dto(submission)

    def _build_essay_submission_dto(self, submission: EssaySubmission) -> EssaySubmissionDTO:
        document_download_url = None
        if submission.document_storage_key:
            document_download_url = self.r2.generate_download_url(submission.document_storage_key)
        is_graded = submission.score is not None
        return EssaySubmissionDTO(
            content_text=submission.content_text,
            document_file_name=submission.document_file_name,
            document_download_url=document_download_url,
            submitted_at=submission.submitted_at,
            is_graded=is_graded,
            is_published=submission.is_published,
            score=float(submission.score) if submission.is_published and submission.score is not None else None,
            feedback=submission.feedback if submission.is_published else None,
        )

    async def mark_item_completed(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID) -> dict:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type == CourseItemTypeEnum.ASSESSMENT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot manually complete an assessment item")

        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)
        await self.session.commit()
        return {"message": "Item marked as completed"}

    async def submit_quiz(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, answers: dict[uuid.UUID, list[uuid.UUID]]) -> QuizResultDTO:
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type != CourseItemTypeEnum.ASSESSMENT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not an assessment")

        assessment = await self.content_repo.get_assessment_by_item(item_id)
        if not assessment or assessment.assessment_type != AssessmentTypeEnum.QUIZ:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not a quiz")

        if assessment.due_date is not None and datetime.now(timezone.utc) > assessment.due_date:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The deadline for this quiz has passed")

        settings = await self.content_repo.get_quiz_settings(assessment.id)
        pass_mark_percentage = settings.pass_mark_percentage if settings else 70
        show_result_to_student = settings.show_result_to_student if settings else True
        max_attempts = settings.max_attempts if settings else None

        if max_attempts is not None:
            attempts_used = await self.repo.count_quiz_attempts(user_id, item_id)
            if attempts_used >= max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Maximum attempts ({max_attempts}) reached for this quiz",
                )

        questions = await self.content_repo.list_questions_for_quizzes([assessment.id])
        q_ids = [q.id for q in questions]
        options = await self.content_repo.list_options_for_questions(q_ids)

        correct_answers = {}
        total_questions = len(questions)
        earned_points = 0.0

        for q in questions:
            correct_opts = {o.id for o in options if o.question_id == q.id and o.is_correct}
            correct_answers[q.id] = list(correct_opts)

            user_ans = set(answers.get(q.id, []))

            if q.allow_multiple_answers and q.multi_answer_mode == MultiAnswerModeEnum.OR:
                if correct_opts:
                    earned_points += min(len(user_ans & correct_opts) / len(correct_opts), 1.0)
            else:
                if user_ans == correct_opts:
                    earned_points += 1.0

        score_percent = (earned_points / total_questions * 100) if total_questions > 0 else 0
        passed = score_percent >= pass_mark_percentage

        # Convert UUID keys to strings for JSONB serialization
        answers_str_keys = {str(k): [str(v) for v in val] for k, val in answers.items()}
        await self.repo.save_quiz_attempt(user_id, item_id, score_percent, passed, answers_str_keys)

        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)

        course = await self.course_repo.get_by_id(course_id)
        await self.activity_service.log_activity(
            user_id,
            ActivityTypeEnum.QUIZ_COMPLETED,
            {"course_id": str(course_id), "course_title": course.title if course else "Unknown", "item_id": str(item_id), "item_title": item.title, "passed": passed, "score": score_percent}
        )

        await self.session.commit()

        return QuizResultDTO(
            score=score_percent if show_result_to_student else None,
            passed=passed if show_result_to_student else None,
            correct_answers=correct_answers if show_result_to_student else None,
            result_visible=show_result_to_student,
        )

    async def submit_essay_text(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, content_text: str) -> EssaySubmissionDTO:
        assessment, essay_settings = await self._authorize_essay_submission(
            user_id, course_id, item_id, EssaySubmissionModeEnum.TEXT
        )
        submission = await self.repo.upsert_essay_submission(user_id, item_id, content_text=content_text)
        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)
        await self._log_essay_submitted(user_id, course_id, item_id)
        await self.session.commit()
        return self._build_essay_submission_dto(submission)

    async def request_essay_upload_url(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, file_name: str) -> EssayUploadUrlResponseDTO:
        await self._authorize_essay_submission(user_id, course_id, item_id, EssaySubmissionModeEnum.DOCUMENT)
        storage_key = self.r2.build_essay_document_key(item_id, user_id, file_name)
        return EssayUploadUrlResponseDTO(
            upload_url=self.r2.generate_upload_url(storage_key), storage_key=storage_key
        )

    async def finalize_essay_document(
        self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, storage_key: str, file_name: str
    ) -> EssaySubmissionDTO:
        await self._authorize_essay_submission(user_id, course_id, item_id, EssaySubmissionModeEnum.DOCUMENT)
        submission = await self.repo.upsert_essay_submission(
            user_id, item_id, document_storage_key=storage_key, document_file_name=file_name
        )
        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)
        await self._log_essay_submitted(user_id, course_id, item_id)
        await self.session.commit()
        return self._build_essay_submission_dto(submission)

    async def _authorize_essay_submission(
        self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, expected_mode: EssaySubmissionModeEnum
    ):
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type != CourseItemTypeEnum.ASSESSMENT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not an assessment")

        assessment = await self.content_repo.get_assessment_by_item(item_id)
        if not assessment or assessment.assessment_type != AssessmentTypeEnum.ESSAY:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Item is not an essay")

        essay_settings = await self.content_repo.get_essay_settings(assessment.id)
        if not essay_settings:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Essay not found")

        if essay_settings.submission_mode != expected_mode:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This essay only accepts {essay_settings.submission_mode.value.lower()} submissions",
            )

        if assessment.due_date is not None and datetime.now(timezone.utc) > assessment.due_date:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The deadline for this essay has passed")

        existing = await self.repo.get_essay_submission(user_id, item_id)
        if existing is not None and existing.score is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="This essay has already been graded and can no longer be resubmitted"
            )

        return assessment, essay_settings

    async def _log_essay_submitted(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID) -> None:
        course = await self.course_repo.get_by_id(course_id)
        item = await self.content_repo.get_item(item_id)
        await self.activity_service.log_activity(
            user_id,
            ActivityTypeEnum.ESSAY_SUBMITTED,
            {
                "course_id": str(course_id),
                "course_title": course.title if course else "Unknown",
                "item_id": str(item_id),
                "item_title": item.title if item else "Unknown",
            },
        )

    async def _list_all_user_assessment_dtos(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID | None = None,
        assessment_type_filter: str | None = None,
    ) -> list[UserAssessmentDTO]:
        rows = await self.repo.list_user_assessments(
            user_id, course_id, assessment_type_filter.upper() if assessment_type_filter else None
        )

        result = []
        for course_item, course, assessment, quiz_settings, latest_attempt, essay_submission, attempts_used in rows:
            if assessment.assessment_type == AssessmentTypeEnum.QUIZ:
                dto = self._build_user_quiz_dto(
                    course_item, course, assessment, quiz_settings, latest_attempt, attempts_used
                )
            else:
                dto = self._build_user_essay_dto(course_item, course, assessment, essay_submission)
            result.append(dto)
        return result

    @staticmethod
    def _in_date_range(due_date: datetime | None, start_date: datetime | None, end_date: datetime | None) -> bool:
        """Date-range scoping is based on `due_date` for both the list and stats
        endpoints. An assessment with no due date is only included when no range
        is given (lifetime) - there's nothing to compare it against otherwise."""
        if start_date is None and end_date is None:
            return True
        if due_date is None:
            return False
        if start_date is not None and due_date < start_date:
            return False
        if end_date is not None and due_date > end_date:
            return False
        return True

    @staticmethod
    def _has_retake_available(dto: UserAssessmentDTO, now: datetime) -> bool:
        if dto.assessment_type != AssessmentTypeEnum.QUIZ:
            return False
        if not dto.attempts_used:
            return False
        if dto.due_date is not None and dto.due_date <= now:
            return False  # can't submit past the deadline, so no retake is actually usable
        return dto.attempts_remaining is None or dto.attempts_remaining > 0

    async def list_user_assessments(
        self,
        user_id: uuid.UUID,
        pagination: PaginationParams,
        status_filter: str | None = None,
        course_id: uuid.UUID | None = None,
        assessment_type_filter: str | None = None,
        upcoming: bool = False,
        completed: bool = False,
        retakes: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[UserAssessmentDTO], int]:
        result = await self._list_all_user_assessment_dtos(user_id, course_id, assessment_type_filter)
        result = [dto for dto in result if self._in_date_range(dto.due_date, start_date, end_date)]

        if status_filter:
            status_filter = status_filter.upper()
            result = [dto for dto in result if dto.status.value == status_filter]

        now = datetime.now(timezone.utc)

        if upcoming:
            result = [
                dto for dto in result
                if dto.due_date is not None and dto.due_date > now and dto.status == UserAssessmentStatusEnum.NOT_STARTED
            ]

        if completed:
            result = [dto for dto in result if dto.status != UserAssessmentStatusEnum.NOT_STARTED]

        if retakes:
            result = [dto for dto in result if self._has_retake_available(dto, now)]

        total = len(result)
        start = pagination.offset
        end = start + pagination.limit
        return result[start:end], total

    async def get_assessment_stats(
        self, user_id: uuid.UUID, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> AssessmentStatsDTO:
        dtos = await self._list_all_user_assessment_dtos(user_id)
        dtos = [dto for dto in dtos if self._in_date_range(dto.due_date, start_date, end_date)]

        now = datetime.now(timezone.utc)

        upcoming_count = sum(
            1 for dto in dtos
            if dto.due_date is not None and dto.due_date > now and dto.status == UserAssessmentStatusEnum.NOT_STARTED
        )
        completed_count = sum(1 for dto in dtos if dto.status != UserAssessmentStatusEnum.NOT_STARTED)
        scores = [dto.score for dto in dtos if dto.score is not None]
        average_score_percentage = sum(scores) / len(scores) if scores else None
        retakes_available_count = sum(1 for dto in dtos if self._has_retake_available(dto, now))

        return AssessmentStatsDTO(
            upcoming_count=upcoming_count,
            completed_count=completed_count,
            average_score_percentage=average_score_percentage,
            retakes_available_count=retakes_available_count,
        )

    def _build_user_quiz_dto(
        self, course_item, course, assessment, quiz_settings, latest_attempt, attempts_used: int
    ) -> UserAssessmentDTO:
        show_result_to_student = quiz_settings.show_result_to_student if quiz_settings else True
        max_attempts = quiz_settings.max_attempts if quiz_settings else None
        pass_mark_percentage = quiz_settings.pass_mark_percentage if quiz_settings else 70

        if latest_attempt:
            if show_result_to_student:
                status = UserAssessmentStatusEnum.PASSED if latest_attempt.passed else UserAssessmentStatusEnum.FAILED
                score = float(latest_attempt.score) if latest_attempt.score is not None else None
            else:
                status = UserAssessmentStatusEnum.SUBMITTED
                score = None
            last_activity_at = latest_attempt.created_at
        else:
            status = UserAssessmentStatusEnum.NOT_STARTED
            score = None
            last_activity_at = None

        attempts_remaining = None if max_attempts is None else max(max_attempts - attempts_used, 0)

        return UserAssessmentDTO(
            item_id=course_item.id,
            title=course_item.title,
            course_id=course.id,
            course_title=course.title,
            assessment_type=AssessmentTypeEnum.QUIZ,
            due_date=assessment.due_date,
            status=status,
            score=score,
            last_activity_at=last_activity_at,
            max_attempts=max_attempts,
            attempts_used=attempts_used,
            attempts_remaining=attempts_remaining,
            pass_mark_percentage=pass_mark_percentage,
        )

    def _build_user_essay_dto(self, course_item, course, assessment, essay_submission) -> UserAssessmentDTO:
        if essay_submission is None:
            status = UserAssessmentStatusEnum.NOT_STARTED
            score = None
            last_activity_at = None
            is_graded = None
            is_published = None
        else:
            is_graded = essay_submission.score is not None
            is_published = essay_submission.is_published
            status = UserAssessmentStatusEnum.GRADED if is_graded else UserAssessmentStatusEnum.SUBMITTED
            score = float(essay_submission.score) if is_published and essay_submission.score is not None else None
            last_activity_at = essay_submission.submitted_at

        return UserAssessmentDTO(
            item_id=course_item.id,
            title=course_item.title,
            course_id=course.id,
            course_title=course.title,
            assessment_type=AssessmentTypeEnum.ESSAY,
            due_date=assessment.due_date,
            status=status,
            score=score,
            last_activity_at=last_activity_at,
            is_graded=is_graded,
            is_published=is_published,
        )

