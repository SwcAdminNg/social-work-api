import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.bunny import get_bunny_client
from app.core.storage import get_r2_client
from app.modules.course.content_dto import (
    CourseDocumentManageDTO,
    CourseDocumentPublicDTO,
    CourseItemCreateDTO,
    CourseItemManageReadDTO,
    CourseItemReadDTO,
    CourseItemReorderDTO,
    CourseItemUpdateDTO,
    CourseQuizManageDTO,
    CourseQuizOptionManageDTO,
    CourseQuizOptionPublicDTO,
    CourseQuizPublicDTO,
    CourseQuizQuestionManageDTO,
    CourseQuizQuestionPublicDTO,
    CourseSectionCreateDTO,
    CourseSectionManageReadDTO,
    CourseSectionReadDTO,
    CourseSectionReorderDTO,
    CourseSectionUpdateDTO,
    CourseVideoManageDTO,
    CourseVideoPublicDTO,
    DocumentFinalizeDTO,
    DocumentUploadCredentialsDTO,
    QuizOptionCreateDTO,
    QuizOptionUpdateDTO,
    QuizQuestionCreateDTO,
    QuizQuestionUpdateDTO,
    VideoUploadCredentialsDTO,
)
from app.modules.course.content_entity import (
    CourseDocument,
    CourseQuiz,
    CourseQuizOption,
    CourseQuizQuestion,
    CourseVideo,
    VideoStatusEnum,
)
from app.modules.course.content_repository import CourseContentRepository
from app.modules.course.entity import Course, CourseItem, CourseItemTypeEnum, CourseSection
from app.modules.course.repository import CourseRepository
from app.modules.user.entity import User, UserTypeEnum


class CourseContentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CourseContentRepository(session)
        self.course_repo = CourseRepository(session)
        self._r2 = None
        self._bunny = None

    @property
    def r2(self):
        # Built lazily so endpoints that never touch storage (sections, quiz
        # CRUD, etc.) don't require R2 credentials to be configured.
        if self._r2 is None:
            self._r2 = get_r2_client()
        return self._r2

    @property
    def bunny(self):
        if self._bunny is None:
            self._bunny = get_bunny_client()
        return self._bunny

    # -- authorization helpers ----------------------------------------------

    def _ensure_can_manage(self, course: Course, user: User) -> None:
        if user.user_type != UserTypeEnum.ADMIN and course.instructor_id != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this course")

    async def _authorize_course(self, course_id: uuid.UUID, user: User) -> Course:
        course = await self.course_repo.get_by_id(course_id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        self._ensure_can_manage(course, user)
        return course

    async def _authorize_section(
        self, course_id: uuid.UUID, section_id: uuid.UUID, user: User
    ) -> tuple[Course, CourseSection]:
        course = await self._authorize_course(course_id, user)
        section = await self.repo.get_section(section_id)
        if section is None or section.course_id != course.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
        return course, section

    async def _authorize_item(
        self, item_id: uuid.UUID, user: User
    ) -> tuple[Course, CourseSection, CourseItem]:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        section = await self.repo.get_section(item.section_id)
        if section is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        course = await self.course_repo.get_by_id(section.course_id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        self._ensure_can_manage(course, user)
        return course, section, item

    # -- sections --------------------------------------------------------------

    async def create_section(
        self, course_id: uuid.UUID, payload: CourseSectionCreateDTO, current_user: User
    ) -> CourseSection:
        course = await self._authorize_course(course_id, current_user)
        section = CourseSection(course_id=course.id, **payload.model_dump())
        self.session.add(section)
        await self.session.flush()
        await self.session.commit()
        return section

    async def update_section(
        self,
        course_id: uuid.UUID,
        section_id: uuid.UUID,
        payload: CourseSectionUpdateDTO,
        current_user: User,
    ) -> CourseSection:
        _, section = await self._authorize_section(course_id, section_id, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(section, field, value)
        await self.session.flush()
        await self.session.commit()
        return section

    async def delete_section(
        self, course_id: uuid.UUID, section_id: uuid.UUID, current_user: User
    ) -> None:
        _, section = await self._authorize_section(course_id, section_id, current_user)
        section.mark_deleted(current_user.id)
        await self.session.commit()

    async def reorder_sections(
        self, course_id: uuid.UUID, payload: CourseSectionReorderDTO, current_user: User
    ) -> None:
        await self._authorize_course(course_id, current_user)
        for entry in payload.sections:
            section = await self.repo.get_section(entry.id)
            if section is not None and section.course_id == course_id:
                section.order_index = entry.order_index
        await self.session.commit()

    # -- items -----------------------------------------------------------------

    async def create_item(
        self,
        course_id: uuid.UUID,
        section_id: uuid.UUID,
        payload: CourseItemCreateDTO,
        current_user: User,
    ) -> tuple[CourseItem, VideoUploadCredentialsDTO | None, DocumentUploadCredentialsDTO | None]:
        course, section = await self._authorize_section(course_id, section_id, current_user)

        item = CourseItem(
            section_id=section.id,
            title=payload.title,
            item_type=payload.item_type,
            order_index=payload.order_index,
            is_preview=payload.is_preview,
        )
        self.session.add(item)
        await self.session.flush()

        video_credentials: VideoUploadCredentialsDTO | None = None
        document_credentials: DocumentUploadCredentialsDTO | None = None

        if payload.item_type == CourseItemTypeEnum.VIDEO:
            guid = await self.bunny.create_video(payload.title)
            self.session.add(CourseVideo(course_item_id=item.id, bunny_video_guid=guid))
            video_credentials = VideoUploadCredentialsDTO(**self.bunny.build_tus_credentials(guid))
        elif payload.item_type == CourseItemTypeEnum.DOCUMENT:
            if not payload.file_name:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "file_name is required for document items")
            storage_key = self.r2.build_document_key(course.id, payload.file_name)
            self.session.add(
                CourseDocument(course_item_id=item.id, storage_key=storage_key, file_name=payload.file_name)
            )
            document_credentials = DocumentUploadCredentialsDTO(
                upload_url=self.r2.generate_upload_url(storage_key), storage_key=storage_key
            )
        elif payload.item_type == CourseItemTypeEnum.QUIZ:
            self.session.add(CourseQuiz(course_item_id=item.id))

        await self.session.commit()
        return item, video_credentials, document_credentials

    async def update_item(
        self, item_id: uuid.UUID, payload: CourseItemUpdateDTO, current_user: User
    ) -> CourseItem:
        _, _, item = await self._authorize_item(item_id, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        await self.session.flush()
        await self.session.commit()
        return item

    async def delete_item(self, item_id: uuid.UUID, current_user: User) -> None:
        _, _, item = await self._authorize_item(item_id, current_user)

        if item.item_type == CourseItemTypeEnum.DOCUMENT:
            document = await self.repo.get_document_by_item(item.id)
            if document:
                self.r2.delete_object(document.storage_key)

        item.mark_deleted(current_user.id)
        await self.session.commit()

    async def reorder_items(
        self,
        course_id: uuid.UUID,
        section_id: uuid.UUID,
        payload: CourseItemReorderDTO,
        current_user: User,
    ) -> None:
        await self._authorize_section(course_id, section_id, current_user)
        for entry in payload.items:
            item = await self.repo.get_item(entry.id)
            if item is not None and item.section_id == section_id:
                item.order_index = entry.order_index
        await self.session.commit()

    # -- document --------------------------------------------------------------

    async def finalize_document(
        self, item_id: uuid.UUID, payload: DocumentFinalizeDTO, current_user: User
    ) -> CourseDocument:
        _, _, item = await self._authorize_item(item_id, current_user)
        document = await self.repo.get_document_by_item(item.id)
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found for this item")
        document.is_uploaded = True
        if payload.mime_type is not None:
            document.mime_type = payload.mime_type
        if payload.file_size_bytes is not None:
            document.file_size_bytes = payload.file_size_bytes
        await self.session.flush()
        await self.session.commit()
        return document

    async def get_document_download_url(self, slug: str, item_id: uuid.UUID) -> str:
        course = await self.course_repo.get_by_slug(slug)
        if course is None or not course.is_published:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        item = await self.repo.get_item(item_id)
        section = await self.repo.get_section(item.section_id) if item else None
        if item is None or section is None or section.course_id != course.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        document = await self.repo.get_document_by_item(item.id)
        if document is None or not document.is_uploaded:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not available")
        return self.r2.generate_download_url(document.storage_key)

    # -- video -------------------------------------------------------------------

    async def refresh_video_upload(self, item_id: uuid.UUID, current_user: User) -> VideoUploadCredentialsDTO:
        _, _, item = await self._authorize_item(item_id, current_user)
        video = await self.repo.get_video_by_item(item.id)
        if video is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found for this item")
        return VideoUploadCredentialsDTO(**self.bunny.build_tus_credentials(video.bunny_video_guid))

    async def handle_bunny_webhook(self, video_guid: str, bunny_status: int) -> None:
        stmt = select(CourseVideo).where(CourseVideo.bunny_video_guid == video_guid)
        video = (await self.session.execute(stmt)).scalar_one_or_none()
        if video is None:
            return

        # Bunny Stream status codes: 3=Finished/Ready, 5/6=error states.
        if bunny_status == 3:
            video.status = VideoStatusEnum.READY
            video.playback_url = self.bunny.build_playback_url(video_guid)
            video.thumbnail_url = self.bunny.build_thumbnail_url(video_guid)
        elif bunny_status in (5, 6):
            video.status = VideoStatusEnum.FAILED
        else:
            video.status = VideoStatusEnum.PROCESSING
        await self.session.commit()

    # -- quiz ----------------------------------------------------------------

    async def create_question(
        self, item_id: uuid.UUID, payload: QuizQuestionCreateDTO, current_user: User
    ) -> tuple[CourseQuizQuestion, list[CourseQuizOption]]:
        _, _, item = await self._authorize_item(item_id, current_user)
        quiz = await self.repo.get_quiz_by_item(item.id)
        if quiz is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found for this item")

        question = CourseQuizQuestion(
            quiz_id=quiz.id,
            text=payload.text,
            order_index=payload.order_index,
            allow_multiple_answers=payload.allow_multiple_answers,
        )
        self.session.add(question)
        await self.session.flush()

        options = [
            CourseQuizOption(question_id=question.id, **option_payload.model_dump())
            for option_payload in payload.options
        ]
        for option in options:
            self.session.add(option)
        await self.session.flush()

        await self.session.commit()
        return question, options

    async def _course_for_quiz(self, quiz_id: uuid.UUID, current_user: User) -> None:
        item_stmt = select(CourseItem).join(CourseQuiz, CourseQuiz.course_item_id == CourseItem.id).where(
            CourseQuiz.id == quiz_id
        )
        item = (await self.session.execute(item_stmt)).scalar_one_or_none()
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
        section = await self.repo.get_section(item.section_id)
        course = await self.course_repo.get_by_id(section.course_id) if section else None
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Quiz not found")
        self._ensure_can_manage(course, current_user)

    async def update_question(
        self, question_id: uuid.UUID, payload: QuizQuestionUpdateDTO, current_user: User
    ) -> CourseQuizQuestion:
        question = await self.repo.get_question(question_id)
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        await self._course_for_quiz(question.quiz_id, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(question, field, value)
        await self.session.flush()
        await self.session.commit()
        return question

    async def delete_question(self, question_id: uuid.UUID, current_user: User) -> None:
        question = await self.repo.get_question(question_id)
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        await self._course_for_quiz(question.quiz_id, current_user)
        question.mark_deleted(current_user.id)
        await self.session.commit()

    async def create_option(
        self, question_id: uuid.UUID, payload: QuizOptionCreateDTO, current_user: User
    ) -> CourseQuizOption:
        question = await self.repo.get_question(question_id)
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        await self._course_for_quiz(question.quiz_id, current_user)
        option = CourseQuizOption(question_id=question.id, **payload.model_dump())
        self.session.add(option)
        await self.session.flush()
        await self.session.commit()
        return option

    async def _course_for_option(self, option: CourseQuizOption, current_user: User) -> None:
        question = await self.repo.get_question(option.question_id)
        if question is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
        await self._course_for_quiz(question.quiz_id, current_user)

    async def update_option(
        self, option_id: uuid.UUID, payload: QuizOptionUpdateDTO, current_user: User
    ) -> CourseQuizOption:
        option = await self.repo.get_option(option_id)
        if option is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Option not found")
        await self._course_for_option(option, current_user)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(option, field, value)
        await self.session.flush()
        await self.session.commit()
        return option

    async def delete_option(self, option_id: uuid.UUID, current_user: User) -> None:
        option = await self.repo.get_option(option_id)
        if option is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Option not found")
        await self._course_for_option(option, current_user)
        option.mark_deleted(current_user.id)
        await self.session.commit()

    # -- tree assembly for course detail endpoints ------------------------------

    async def build_tree(self, course_id: uuid.UUID, manage: bool, enrolled: bool = False) -> list:
        sections = await self.repo.list_sections(course_id)
        section_ids = [s.id for s in sections]
        items = await self.repo.list_items_for_sections(section_ids)
        item_ids = [i.id for i in items]

        videos = {v.course_item_id: v for v in await self.repo.list_videos_for_items(item_ids)}
        documents = {d.course_item_id: d for d in await self.repo.list_documents_for_items(item_ids)}
        quizzes = {q.course_item_id: q for q in await self.repo.list_quizzes_for_items(item_ids)}

        quiz_ids = [q.id for q in quizzes.values()]
        questions = await self.repo.list_questions_for_quizzes(quiz_ids)
        questions_by_quiz: dict[uuid.UUID, list[CourseQuizQuestion]] = {}
        for q in questions:
            questions_by_quiz.setdefault(q.quiz_id, []).append(q)

        question_ids = [q.id for q in questions]
        options = await self.repo.list_options_for_questions(question_ids)
        options_by_question: dict[uuid.UUID, list[CourseQuizOption]] = {}
        for o in options:
            options_by_question.setdefault(o.question_id, []).append(o)

        items_by_section: dict[uuid.UUID, list[CourseItem]] = {}
        for i in items:
            items_by_section.setdefault(i.section_id, []).append(i)

        result_sections = []
        for section in sections:
            item_dtos = [
                self._map_item(item, videos.get(item.id), documents.get(item.id), quizzes.get(item.id),
                               questions_by_quiz, options_by_question, manage, enrolled)
                for item in items_by_section.get(section.id, [])
            ]
            section_cls = CourseSectionManageReadDTO if manage else CourseSectionReadDTO
            result_sections.append(
                section_cls(
                    id=section.id,
                    created_at=section.created_at,
                    course_id=section.course_id,
                    title=section.title,
                    order_index=section.order_index,
                    items=item_dtos,
                )
            )
        return result_sections

    def _map_item(
        self,
        item: CourseItem,
        video: CourseVideo | None,
        document: CourseDocument | None,
        quiz: CourseQuiz | None,
        questions_by_quiz: dict,
        options_by_question: dict,
        manage: bool,
        enrolled: bool,
    ):
        if not manage and not enrolled and not item.is_preview:
            video = None
            document = None
            quiz = None

        video_dto = None
        if video is not None:
            video_cls = CourseVideoManageDTO if manage else CourseVideoPublicDTO
            playback_url = self.bunny.build_playback_url(video.bunny_video_guid) if video.status == VideoStatusEnum.READY else None
            extra = {"bunny_video_guid": video.bunny_video_guid} if manage else {}
            video_dto = video_cls(
                status=video.status,
                playback_url=playback_url,
                thumbnail_url=video.thumbnail_url if video.status == VideoStatusEnum.READY else None,
                duration_seconds=video.duration_seconds,
                **extra,
            )

        document_dto = None
        if document is not None:
            document_cls = CourseDocumentManageDTO if manage else CourseDocumentPublicDTO
            extra = {"storage_key": document.storage_key} if manage else {}
            document_dto = document_cls(
                file_name=document.file_name,
                mime_type=document.mime_type,
                file_size_bytes=document.file_size_bytes,
                is_uploaded=document.is_uploaded,
                **extra,
            )

        quiz_dto = None
        if quiz is not None:
            question_dtos = []
            for question in sorted(questions_by_quiz.get(quiz.id, []), key=lambda q: q.order_index):
                option_dtos = []
                for option in sorted(options_by_question.get(question.id, []), key=lambda o: o.order_index):
                    if manage:
                        option_dtos.append(
                            CourseQuizOptionManageDTO(
                                id=option.id, text=option.text, order_index=option.order_index,
                                is_correct=option.is_correct,
                            )
                        )
                    else:
                        option_dtos.append(
                            CourseQuizOptionPublicDTO(
                                id=option.id, text=option.text, order_index=option.order_index
                            )
                        )
                question_cls = CourseQuizQuestionManageDTO if manage else CourseQuizQuestionPublicDTO
                question_dtos.append(
                    question_cls(
                        id=question.id,
                        text=question.text,
                        order_index=question.order_index,
                        allow_multiple_answers=question.allow_multiple_answers,
                        options=option_dtos,
                    )
                )
            quiz_cls = CourseQuizManageDTO if manage else CourseQuizPublicDTO
            quiz_dto = quiz_cls(
                id=quiz.id, passing_score_percentage=quiz.passing_score_percentage, questions=question_dtos
            )

        item_cls = CourseItemManageReadDTO if manage else CourseItemReadDTO
        return item_cls(
            id=item.id,
            created_at=item.created_at,
            section_id=item.section_id,
            title=item.title,
            item_type=item.item_type,
            order_index=item.order_index,
            is_preview=item.is_preview,
            video=video_dto,
            document=document_dto,
            quiz=quiz_dto,
        )
