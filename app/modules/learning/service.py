import random
import uuid
from datetime import datetime, timedelta, timezone

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
    QuizGroupActiveAttemptDTO,
    QuizGroupContentDTO,
    QuizGroupResultDTO,
    QuizGroupSectionAttemptDTO,
    QuizGroupSectionOverviewDTO,
    QuizGroupSectionResultDTO,
    QuizQuestionDTO,
    QuizResultDTO,
    UserAssessmentDTO,
    UserAssessmentStatusEnum,
)
from app.common.pagination import PaginationParams
from app.core.storage import get_r2_client
from app.modules.learning.repository import LearningRepository
from app.modules.payment.entity import UserSubscription
from app.modules.learning.entity import (
    EssaySubmission,
    QuizGroupAttempt,
    QuizGroupAttemptStatusEnum,
    UserItemProgress,
)
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
                elif assessment.assessment_type == AssessmentTypeEnum.QUIZ_GROUP:
                    dto.quiz_group = await self._build_quiz_group_content(user_id, item_id, assessment)

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
            q_options = [o for o in options if o.question_id == q.id]
            earned, correct_opts = self._score_question(q, q_options, set(answers.get(q.id, [])))
            correct_answers[q.id] = list(correct_opts)
            earned_points += earned

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

    @staticmethod
    def _score_question(question, question_options: list, user_ans: set) -> tuple[float, set]:
        """Shared by standalone-quiz and quiz-group scoring. Returns (earned_points,
        correct_option_ids) for one question: full credit for an exact-match single/
        AND-mode answer, partial credit for OR-mode multi-answer questions."""
        correct_opts = {o.id for o in question_options if o.is_correct}
        if question.allow_multiple_answers and question.multi_answer_mode == MultiAnswerModeEnum.OR:
            earned = min(len(user_ans & correct_opts) / len(correct_opts), 1.0) if correct_opts else 0.0
        else:
            earned = 1.0 if user_ans == correct_opts else 0.0
        return earned, correct_opts

    # -- quiz group (nested quizzes) ---------------------------------------------

    @staticmethod
    def _select_section_questions(pool: list, k: int, seen_ids: set) -> list:
        """Pick `k` questions from `pool`, preferring ones the student hasn't been
        asked before (across their past attempts on this item) so retakes don't
        keep repeating the same set. Once every question has been seen at least
        once, it wraps around and starts reusing them. Returned in `order_index`
        order for a stable answering sequence."""
        k = min(k, len(pool))
        unseen = [q for q in pool if q.id not in seen_ids]
        seen = [q for q in pool if q.id in seen_ids]
        random.shuffle(unseen)
        random.shuffle(seen)
        chosen = (unseen + seen)[:k]
        return sorted(chosen, key=lambda q: q.order_index)

    async def _authorize_quiz_group(self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID):
        access = await self.repo.get_user_course_access(user_id, course_id)
        if not access:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not enrolled")

        item = await self.content_repo.get_item(item_id)
        if not item or item.item_type != CourseItemTypeEnum.ASSESSMENT:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Item is not an assessment")

        assessment = await self.content_repo.get_assessment_by_item(item_id)
        if not assessment or assessment.assessment_type != AssessmentTypeEnum.QUIZ_GROUP:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Item is not a quiz group")

        return item, assessment

    async def _maybe_expire_quiz_group_attempt(self, attempt: QuizGroupAttempt, pass_mark_percentage: int) -> None:
        """Lazily auto-submits+scores an IN_PROGRESS attempt whose timer has run
        out, using whatever answers were last saved via `save_quiz_group_progress`
        (empty if the student never called it). Called before any read/write that
        touches an in-progress attempt, so an expired one never lingers."""
        if attempt.expires_at is None or datetime.now(timezone.utc) < attempt.expires_at:
            return
        await self._finalize_quiz_group_attempt(attempt, pass_mark_percentage, auto_submitted=True)

    async def _finalize_quiz_group_attempt(
        self, attempt: QuizGroupAttempt, pass_mark_percentage: int, auto_submitted: bool
    ) -> None:
        question_ids = [uuid.UUID(qid) for qids in attempt.selected_questions.values() for qid in qids]
        # Fetch only the persisted (drawn-for-this-attempt) questions, not the
        # whole pool, and their options.
        all_pool_questions = await self._load_questions_by_ids(question_ids)
        options = await self.content_repo.list_options_for_questions([q.id for q in all_pool_questions])

        saved_answers = attempt.answers or {}
        answers = {uuid.UUID(k): [uuid.UUID(v) for v in vs] for k, vs in saved_answers.items()}

        sections = await self.content_repo.list_sections_for_group(
            (await self.content_repo.get_assessment_by_item(attempt.item_id)).id
        )
        sections_by_id = {s.id: s for s in sections}
        questions_by_id = {q.id: q for q in all_pool_questions}

        section_scores = []
        total_earned = 0.0
        total_questions = 0
        for section_id_str, q_ids in attempt.selected_questions.items():
            section = sections_by_id.get(uuid.UUID(section_id_str))
            section_earned = 0.0
            for q_id_str in q_ids:
                question = questions_by_id.get(uuid.UUID(q_id_str))
                if question is None:
                    continue
                q_options = [o for o in options if o.question_id == question.id]
                earned, _ = self._score_question(question, q_options, set(answers.get(question.id, [])))
                section_earned += earned
            section_total = len(q_ids)
            total_earned += section_earned
            total_questions += section_total
            section_scores.append({
                "section_id": section_id_str,
                "title": section.title if section else "Unknown section",
                "earned_points": section_earned,
                "total_questions": section_total,
                "score_percent": (section_earned / section_total * 100) if section_total > 0 else 0,
            })

        score_percent = (total_earned / total_questions * 100) if total_questions > 0 else 0
        passed = score_percent >= pass_mark_percentage

        await self.repo.finalize_quiz_group_attempt(
            attempt, score_percent, passed, section_scores, saved_answers, auto_submitted
        )

    async def _load_questions_by_ids(self, question_ids: list[uuid.UUID]) -> list:
        if not question_ids:
            return []
        from sqlalchemy import select as sa_select
        from app.modules.course.content_entity import CourseQuizQuestion
        stmt = sa_select(CourseQuizQuestion).where(CourseQuizQuestion.id.in_(question_ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def _build_section_attempt_dtos(self, attempt: QuizGroupAttempt) -> list[QuizGroupSectionAttemptDTO]:
        question_ids = [uuid.UUID(qid) for qids in attempt.selected_questions.values() for qid in qids]
        questions = await self._load_questions_by_ids(question_ids)
        questions_by_id = {q.id: q for q in questions}
        options = await self.content_repo.list_options_for_questions(question_ids)

        assessment = await self.content_repo.get_assessment_by_item(attempt.item_id)
        sections = await self.content_repo.list_sections_for_group(assessment.id)
        sections_by_id = {s.id: s for s in sections}

        result = []
        for section_id_str, q_ids in attempt.selected_questions.items():
            section = sections_by_id.get(uuid.UUID(section_id_str))
            question_dtos = []
            for q_id_str in q_ids:
                question = questions_by_id.get(uuid.UUID(q_id_str))
                if question is None:
                    continue
                q_opts = [{"id": o.id, "text": o.text} for o in options if o.question_id == question.id]
                question_dtos.append(
                    QuizQuestionDTO(
                        id=question.id, text=question.text, allow_multiple_answers=question.allow_multiple_answers,
                        multi_answer_mode=question.multi_answer_mode, options=q_opts,
                    )
                )
            result.append(
                QuizGroupSectionAttemptDTO(
                    section_id=uuid.UUID(section_id_str),
                    title=section.title if section else "Unknown section",
                    questions=question_dtos,
                )
            )
        return result

    def _build_active_attempt_dto(self, attempt: QuizGroupAttempt, section_dtos) -> QuizGroupActiveAttemptDTO:
        saved_answers = {}
        if attempt.answers:
            for k, v in attempt.answers.items():
                saved_answers[uuid.UUID(k)] = [uuid.UUID(opt_id) for opt_id in v]
        return QuizGroupActiveAttemptDTO(
            attempt_id=attempt.id,
            started_at=attempt.started_at,
            expires_at=attempt.expires_at,
            sections=section_dtos,
            saved_answers=saved_answers,
        )

    def _build_group_result_dto(self, attempt: QuizGroupAttempt, show_result_to_student: bool) -> QuizGroupResultDTO:
        if not show_result_to_student:
            return QuizGroupResultDTO(
                attempt_id=attempt.id, score=None, passed=None, auto_submitted=attempt.auto_submitted,
                sections=None, correct_answers=None, result_visible=False,
            )
        section_dtos = [
            QuizGroupSectionResultDTO(
                section_id=uuid.UUID(s["section_id"]), title=s["title"], earned_points=s["earned_points"],
                total_questions=s["total_questions"], score_percent=s["score_percent"],
            )
            for s in (attempt.section_scores or [])
        ]
        return QuizGroupResultDTO(
            attempt_id=attempt.id,
            score=float(attempt.score) if attempt.score is not None else None,
            passed=attempt.passed,
            auto_submitted=attempt.auto_submitted,
            sections=section_dtos,
            correct_answers=None,
            result_visible=True,
        )

    async def _build_quiz_group_content(
        self, user_id: uuid.UUID, item_id: uuid.UUID, assessment
    ) -> QuizGroupContentDTO:
        settings = await self.content_repo.get_quiz_group_settings(assessment.id)
        pass_mark_percentage = settings.pass_mark_percentage if settings else 70
        show_result_to_student = settings.show_result_to_student if settings else True
        max_attempts = settings.max_attempts if settings else None
        time_limit_seconds = settings.time_limit_seconds if settings else None

        sections = await self.content_repo.list_sections_for_group(assessment.id)
        questions = await self.content_repo.list_questions_for_quizzes([assessment.id])
        pool_by_section: dict[uuid.UUID, list] = {}
        for q in questions:
            if q.section_id is not None:
                pool_by_section.setdefault(q.section_id, []).append(q)

        section_overview = [
            QuizGroupSectionOverviewDTO(
                id=sec.id, title=sec.title, order_index=sec.order_index,
                question_count=min(sec.questions_to_ask, len(pool_by_section.get(sec.id, []))) if sec.questions_to_ask
                else len(pool_by_section.get(sec.id, [])),
            )
            for sec in sections
        ]

        in_progress = await self.repo.get_in_progress_quiz_group_attempt(user_id, item_id)
        if in_progress is not None:
            await self._maybe_expire_quiz_group_attempt(in_progress, pass_mark_percentage)
            await self.session.commit()
            if in_progress.status == QuizGroupAttemptStatusEnum.IN_PROGRESS:
                section_dtos = await self._build_section_attempt_dtos(in_progress)
                active_attempt = self._build_active_attempt_dto(in_progress, section_dtos)
            else:
                active_attempt = None
        else:
            active_attempt = None

        attempts_used = await self.repo.count_quiz_group_attempts(user_id, item_id)
        latest_submitted = await self.repo.get_latest_submitted_quiz_group_attempt(user_id, item_id)
        previous_result = (
            self._build_group_result_dto(latest_submitted, show_result_to_student)
            if latest_submitted is not None else None
        )

        return QuizGroupContentDTO(
            max_attempts=max_attempts,
            attempts_used=attempts_used,
            attempts_remaining=None if max_attempts is None else max(max_attempts - attempts_used, 0),
            pass_mark_percentage=pass_mark_percentage,
            show_result_to_student=show_result_to_student,
            time_limit_seconds=time_limit_seconds,
            sections=section_overview,
            active_attempt=active_attempt,
            previous_result=previous_result,
        )

    async def start_quiz_group(
        self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID
    ) -> QuizGroupActiveAttemptDTO:
        item, assessment = await self._authorize_quiz_group(user_id, course_id, item_id)
        if assessment.due_date is not None and datetime.now(timezone.utc) > assessment.due_date:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The deadline for this quiz has passed")

        settings = await self.content_repo.get_quiz_group_settings(assessment.id)
        pass_mark_percentage = settings.pass_mark_percentage if settings else 70
        max_attempts = settings.max_attempts if settings else None
        time_limit_seconds = settings.time_limit_seconds if settings else None

        existing = await self.repo.get_in_progress_quiz_group_attempt(user_id, item_id)
        if existing is not None:
            await self._maybe_expire_quiz_group_attempt(existing, pass_mark_percentage)
            await self.session.commit()
            if existing.status == QuizGroupAttemptStatusEnum.IN_PROGRESS:
                section_dtos = await self._build_section_attempt_dtos(existing)
                return self._build_active_attempt_dto(existing, section_dtos)

        if max_attempts is not None:
            attempts_used = await self.repo.count_quiz_group_attempts(user_id, item_id)
            if attempts_used >= max_attempts:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"Maximum attempts ({max_attempts}) reached for this quiz"
                )

        sections = await self.content_repo.list_sections_for_group(assessment.id)
        if not sections:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This quiz group has no sections yet")

        questions = await self.content_repo.list_questions_for_quizzes([assessment.id])
        pool_by_section: dict[uuid.UUID, list] = {}
        for q in questions:
            if q.section_id is not None:
                pool_by_section.setdefault(q.section_id, []).append(q)

        past_attempts = await self.repo.list_quiz_group_attempts(user_id, item_id)
        seen_by_section: dict[uuid.UUID, set] = {}
        for past in past_attempts:
            for section_id_str, q_ids in past.selected_questions.items():
                sec_id = uuid.UUID(section_id_str)
                seen_by_section.setdefault(sec_id, set()).update(uuid.UUID(q) for q in q_ids)

        selected_questions: dict[str, list[str]] = {}
        for sec in sections:
            pool = pool_by_section.get(sec.id, [])
            if not pool:
                continue
            k = sec.questions_to_ask or len(pool)
            chosen = self._select_section_questions(pool, k, seen_by_section.get(sec.id, set()))
            selected_questions[str(sec.id)] = [str(q.id) for q in chosen]

        if not any(selected_questions.values()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This quiz group has no questions yet")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=time_limit_seconds) if time_limit_seconds else None
        attempt = await self.repo.create_quiz_group_attempt(user_id, item_id, now, expires_at, selected_questions)
        await self.session.commit()

        section_dtos = await self._build_section_attempt_dtos(attempt)
        return self._build_active_attempt_dto(attempt, section_dtos)

    async def _load_owned_attempt(
        self, user_id: uuid.UUID, course_id: uuid.UUID, item_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> tuple[QuizGroupAttempt, int]:
        _, assessment = await self._authorize_quiz_group(user_id, course_id, item_id)
        settings = await self.content_repo.get_quiz_group_settings(assessment.id)
        pass_mark_percentage = settings.pass_mark_percentage if settings else 70

        attempt = await self.repo.get_quiz_group_attempt(attempt_id)
        if attempt is None or attempt.user_id != user_id or attempt.item_id != item_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
        return attempt, pass_mark_percentage

    async def save_quiz_group_progress(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        item_id: uuid.UUID,
        attempt_id: uuid.UUID,
        answers: dict[uuid.UUID, list[uuid.UUID]],
    ) -> None:
        attempt, pass_mark_percentage = await self._load_owned_attempt(
            user_id, course_id, item_id, attempt_id
        )
        await self._maybe_expire_quiz_group_attempt(attempt, pass_mark_percentage)
        if attempt.status != QuizGroupAttemptStatusEnum.IN_PROGRESS:
            await self.session.commit()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Time is up - this attempt was submitted automatically")

        answers_str_keys = {str(k): [str(v) for v in val] for k, val in answers.items()}
        await self.repo.save_quiz_group_progress(attempt, answers_str_keys)
        await self.session.commit()

    async def submit_quiz_group(
        self,
        user_id: uuid.UUID,
        course_id: uuid.UUID,
        item_id: uuid.UUID,
        attempt_id: uuid.UUID,
        answers: dict[uuid.UUID, list[uuid.UUID]],
    ) -> QuizGroupResultDTO:
        attempt, pass_mark_percentage = await self._load_owned_attempt(
            user_id, course_id, item_id, attempt_id
        )
        settings = await self.content_repo.get_quiz_group_settings(
            (await self.content_repo.get_assessment_by_item(item_id)).id
        )
        show_result_to_student = settings.show_result_to_student if settings else True

        if attempt.status == QuizGroupAttemptStatusEnum.SUBMITTED:
            # Already finalized (e.g. auto-submitted by the timer just before this
            # call landed) - return the existing result instead of erroring, so a
            # racing client-side auto-submit doesn't dead-end the student.
            return self._build_group_result_dto(attempt, show_result_to_student)

        answers_str_keys = {str(k): [str(v) for v in val] for k, val in answers.items()}
        await self.repo.save_quiz_group_progress(attempt, answers_str_keys)
        now = datetime.now(timezone.utc)
        auto_submitted = attempt.expires_at is not None and now >= attempt.expires_at
        await self._finalize_quiz_group_attempt(attempt, pass_mark_percentage, auto_submitted)

        await self.repo.mark_item_completed(user_id, item_id)
        await self._recalculate_progress(user_id, course_id)

        course = await self.course_repo.get_by_id(course_id)
        item = await self.content_repo.get_item(item_id)
        await self.activity_service.log_activity(
            user_id,
            ActivityTypeEnum.QUIZ_GROUP_COMPLETED,
            {
                "course_id": str(course_id), "course_title": course.title if course else "Unknown",
                "item_id": str(item_id), "item_title": item.title if item else "Unknown",
                "passed": attempt.passed, "score": float(attempt.score) if attempt.score is not None else None,
            },
        )

        await self.session.commit()
        return self._build_group_result_dto(attempt, show_result_to_student)

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
        for (
            course_item, course, assessment, quiz_settings, latest_attempt, essay_submission, attempts_used,
            quiz_group_settings, latest_group_attempt, group_attempts_used,
        ) in rows:
            if assessment.assessment_type == AssessmentTypeEnum.QUIZ:
                dto = self._build_user_quiz_dto(
                    course_item, course, assessment, quiz_settings, latest_attempt, attempts_used
                )
            elif assessment.assessment_type == AssessmentTypeEnum.QUIZ_GROUP:
                dto = self._build_user_quiz_group_dto(
                    course_item, course, assessment, quiz_group_settings, latest_group_attempt, group_attempts_used
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
        if dto.assessment_type not in (AssessmentTypeEnum.QUIZ, AssessmentTypeEnum.QUIZ_GROUP):
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

    def _build_user_quiz_group_dto(
        self, course_item, course, assessment, quiz_group_settings, latest_attempt, attempts_used: int
    ) -> UserAssessmentDTO:
        show_result_to_student = quiz_group_settings.show_result_to_student if quiz_group_settings else True
        max_attempts = quiz_group_settings.max_attempts if quiz_group_settings else None
        pass_mark_percentage = quiz_group_settings.pass_mark_percentage if quiz_group_settings else 70

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
            assessment_type=AssessmentTypeEnum.QUIZ_GROUP,
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

