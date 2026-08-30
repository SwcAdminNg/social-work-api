import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.content_entity import (
    CourseAssessment,
    CourseDocument,
    CourseEssaySettings,
    CourseLink,
    CourseQuizGroupSection,
    CourseQuizGroupSettings,
    CourseQuizOption,
    CourseQuizQuestion,
    CourseQuizSettings,
    CourseVideo,
)
from app.modules.course.entity import CourseItem, CourseSection
from app.modules.course.instructor_entity import CourseInstructor, CourseSectionInstructor


class CourseContentRepository:
    """Read/write helpers for the curriculum tree (sections -> items -> video/
    document/quiz). Kept as plain queries (no ORM `relationship()` mappings
    exist on these entities, matching the rest of the codebase) and assembled
    in Python by `CourseContentService`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- sections ----------------------------------------------------------

    async def list_sections(self, course_id: uuid.UUID) -> Sequence[CourseSection]:
        stmt = (
            select(CourseSection)
            .where(CourseSection.course_id == course_id, CourseSection.deleted_at.is_(None))
            .order_by(CourseSection.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_section(self, id: uuid.UUID) -> CourseSection | None:
        stmt = select(CourseSection).where(CourseSection.id == id, CourseSection.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- items ---------------------------------------------------------------

    async def list_items_for_sections(self, section_ids: Sequence[uuid.UUID]) -> Sequence[CourseItem]:
        if not section_ids:
            return []
        stmt = (
            select(CourseItem)
            .where(CourseItem.section_id.in_(section_ids), CourseItem.deleted_at.is_(None))
            .order_by(CourseItem.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_item(self, id: uuid.UUID) -> CourseItem | None:
        stmt = select(CourseItem).where(CourseItem.id == id, CourseItem.deleted_at.is_(None))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- video ---------------------------------------------------------------

    async def get_video_by_item(self, item_id: uuid.UUID) -> CourseVideo | None:
        stmt = select(CourseVideo).where(CourseVideo.course_item_id == item_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_videos_for_items(self, item_ids: Sequence[uuid.UUID]) -> Sequence[CourseVideo]:
        if not item_ids:
            return []
        stmt = select(CourseVideo).where(CourseVideo.course_item_id.in_(item_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- document --------------------------------------------------------------

    async def get_document_by_item(self, item_id: uuid.UUID) -> CourseDocument | None:
        stmt = select(CourseDocument).where(CourseDocument.course_item_id == item_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_documents_for_items(self, item_ids: Sequence[uuid.UUID]) -> Sequence[CourseDocument]:
        if not item_ids:
            return []
        stmt = select(CourseDocument).where(CourseDocument.course_item_id.in_(item_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- link ------------------------------------------------------------------

    async def get_link_by_item(self, item_id: uuid.UUID) -> CourseLink | None:
        stmt = select(CourseLink).where(CourseLink.course_item_id == item_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_links_for_items(self, item_ids: Sequence[uuid.UUID]) -> Sequence[CourseLink]:
        if not item_ids:
            return []
        stmt = select(CourseLink).where(CourseLink.course_item_id.in_(item_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- section guest instructors ----------------------------------------------

    async def list_section_instructors(
        self, section_ids: Sequence[uuid.UUID]
    ) -> Sequence[tuple[CourseSectionInstructor, CourseInstructor]]:
        if not section_ids:
            return []
        stmt = (
            select(CourseSectionInstructor, CourseInstructor)
            .join(CourseInstructor, CourseInstructor.id == CourseSectionInstructor.course_instructor_id)
            .where(
                CourseSectionInstructor.section_id.in_(section_ids),
                CourseSectionInstructor.deleted_at.is_(None),
            )
            .order_by(CourseSectionInstructor.order_index)
        )
        return (await self.session.execute(stmt)).all()

    # -- assessment ---------------------------------------------------------------

    async def get_assessment_by_item(self, item_id: uuid.UUID) -> CourseAssessment | None:
        stmt = select(CourseAssessment).where(CourseAssessment.course_item_id == item_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_assessment(self, assessment_id: uuid.UUID) -> CourseAssessment | None:
        stmt = select(CourseAssessment).where(CourseAssessment.id == assessment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_assessments_for_items(self, item_ids: Sequence[uuid.UUID]) -> Sequence[CourseAssessment]:
        if not item_ids:
            return []
        stmt = select(CourseAssessment).where(CourseAssessment.course_item_id.in_(item_ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def get_quiz_settings(self, assessment_id: uuid.UUID) -> CourseQuizSettings | None:
        stmt = select(CourseQuizSettings).where(CourseQuizSettings.assessment_id == assessment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_quiz_settings(self, assessment_ids: Sequence[uuid.UUID]) -> Sequence[CourseQuizSettings]:
        if not assessment_ids:
            return []
        stmt = select(CourseQuizSettings).where(CourseQuizSettings.assessment_id.in_(assessment_ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def get_essay_settings(self, assessment_id: uuid.UUID) -> CourseEssaySettings | None:
        stmt = select(CourseEssaySettings).where(CourseEssaySettings.assessment_id == assessment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_essay_settings(self, assessment_ids: Sequence[uuid.UUID]) -> Sequence[CourseEssaySettings]:
        if not assessment_ids:
            return []
        stmt = select(CourseEssaySettings).where(CourseEssaySettings.assessment_id.in_(assessment_ids))
        return (await self.session.execute(stmt)).scalars().all()

    # -- quiz group (nested quizzes) ------------------------------------------

    async def get_quiz_group_settings(self, assessment_id: uuid.UUID) -> CourseQuizGroupSettings | None:
        stmt = select(CourseQuizGroupSettings).where(CourseQuizGroupSettings.assessment_id == assessment_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_quiz_group_settings(
        self, assessment_ids: Sequence[uuid.UUID]
    ) -> Sequence[CourseQuizGroupSettings]:
        if not assessment_ids:
            return []
        stmt = select(CourseQuizGroupSettings).where(CourseQuizGroupSettings.assessment_id.in_(assessment_ids))
        return (await self.session.execute(stmt)).scalars().all()

    async def get_quiz_group_section(self, id: uuid.UUID) -> CourseQuizGroupSection | None:
        stmt = select(CourseQuizGroupSection).where(
            CourseQuizGroupSection.id == id, CourseQuizGroupSection.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_sections_for_group(self, assessment_id: uuid.UUID) -> Sequence[CourseQuizGroupSection]:
        stmt = (
            select(CourseQuizGroupSection)
            .where(
                CourseQuizGroupSection.assessment_id == assessment_id,
                CourseQuizGroupSection.deleted_at.is_(None),
            )
            .order_by(CourseQuizGroupSection.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_sections_for_groups(
        self, assessment_ids: Sequence[uuid.UUID]
    ) -> Sequence[CourseQuizGroupSection]:
        if not assessment_ids:
            return []
        stmt = (
            select(CourseQuizGroupSection)
            .where(
                CourseQuizGroupSection.assessment_id.in_(assessment_ids),
                CourseQuizGroupSection.deleted_at.is_(None),
            )
            .order_by(CourseQuizGroupSection.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_questions_for_quizzes(self, assessment_ids: Sequence[uuid.UUID]) -> Sequence[CourseQuizQuestion]:
        if not assessment_ids:
            return []
        stmt = (
            select(CourseQuizQuestion)
            .where(CourseQuizQuestion.assessment_id.in_(assessment_ids), CourseQuizQuestion.deleted_at.is_(None))
            .order_by(CourseQuizQuestion.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_question(self, id: uuid.UUID) -> CourseQuizQuestion | None:
        stmt = select(CourseQuizQuestion).where(
            CourseQuizQuestion.id == id, CourseQuizQuestion.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_options_for_questions(self, question_ids: Sequence[uuid.UUID]) -> Sequence[CourseQuizOption]:
        if not question_ids:
            return []
        stmt = (
            select(CourseQuizOption)
            .where(CourseQuizOption.question_id.in_(question_ids), CourseQuizOption.deleted_at.is_(None))
            .order_by(CourseQuizOption.order_index)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_option(self, id: uuid.UUID) -> CourseQuizOption | None:
        stmt = select(CourseQuizOption).where(
            CourseQuizOption.id == id, CourseQuizOption.deleted_at.is_(None)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
