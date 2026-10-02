"""The draft layer: a hidden, editable working copy of a published course.

Learners keep seeing the published (live) rows while staff edit a full clone of
the course's sections/items/content, tagged with the revision's id. On publish
the clone is merged back *in place* - live rows keep their ids, so learner
progress, quiz attempts (which store question/option ids), essay submissions
and certificates all stay attached to the same rows.

Row conventions (see CourseSection/CourseItem and the quiz entities):
- `revision_id` (sections, items): NULL = live, set = belongs to that working copy.
- `draft_of_id`: the live row a draft row shadows; NULL on a draft row = newly added.
- 1:1 children (video, document, link, assessment, settings) carry no layer
  columns of their own - they follow their item.
- Live sessions are operational (scheduling, rooms, reminders): never cloned. A
  draft item reaches its live session through `draft_of_id`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.course.content_entity import (
    AssessmentTypeEnum,
    CourseAssessment,
    CourseDocument,
    CourseEssaySettings,
    CourseLink,
    CourseLiveSession,
    CourseQuizGroupSection,
    CourseQuizGroupSettings,
    CourseQuizOption,
    CourseQuizQuestion,
    CourseQuizSettings,
    CourseVideo,
)
from app.modules.course.entity import Course, CourseItem, CourseItemTypeEnum, CourseSection
from app.modules.course.instructor_entity import CourseSectionInstructor
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.draft_scope import include_drafts
from app.modules.governance.entity import CourseRevision, CourseVersion, RevisionContributor
from app.modules.governance.enums import (
    CLOSED_STATUSES,
    EDITABLE_STATUSES,
    AssessmentDesignStatusEnum,
    ContentStatusEnum,
    CourseLifecycleEnum,
    RevisionKindEnum,
)
from app.modules.governance.tree import ACADEMIC_COURSE_FIELDS, build_normalized_tree, tree_hash
from app.modules.user.entity import User

_AUDIT_COLUMNS = frozenset(
    {"id", "created_at", "updated_at", "deleted_at", "restored_at", "created_by", "updated_by", "deleted_by", "restored_by"}
)
_SETTINGS_MODELS = (CourseQuizSettings, CourseEssaySettings, CourseQuizGroupSettings)
_ITEM_CHILD_MODELS = (CourseVideo, CourseDocument, CourseLink)


def _columns(model) -> list[str]:
    return [attr.key for attr in model.__mapper__.column_attrs]


def _clone(row, **overrides):
    model = type(row)
    data = {k: getattr(row, k) for k in _columns(model) if k not in _AUDIT_COLUMNS}
    data.update(overrides)
    return model(**data)


def _copy_onto(source, target, exclude: set[str] = frozenset()) -> None:
    for key in _columns(type(source)):
        if key in _AUDIT_COLUMNS or key in exclude:
            continue
        setattr(target, key, getattr(source, key))


def governance_active() -> bool:
    return settings.content_governance_enabled


@dataclass
class MergeResult:
    item_set_changed: bool = False
    # Items newly made live that carry a live session: notify enrolled learners
    # and schedule the reminder after the merge commits.
    promoted_live_session_item_ids: list[uuid.UUID] = field(default_factory=list)
    # Daily rooms of live sessions whose items were removed.
    removed_live_session_room_names: list[str] = field(default_factory=list)


class DraftService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- revision lookup ------------------------------------------------------------

    async def get_open_revision(self, course_id: uuid.UUID) -> CourseRevision | None:
        stmt = select(CourseRevision).where(
            CourseRevision.course_id == course_id,
            CourseRevision.status.not_in(CLOSED_STATUSES),
            CourseRevision.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _lock_course(self, course_id: uuid.UUID) -> Course:
        stmt = select(Course).where(Course.id == course_id).with_for_update().execution_options(populate_existing=True)
        course = (await self.session.execute(stmt)).scalar_one_or_none()
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        return course

    @staticmethod
    def is_cloned(revision: CourseRevision | None) -> bool:
        return revision is not None and revision.kind in (RevisionKindEnum.CHANGE, RevisionKindEnum.ROLLBACK)

    # -- opening a working copy ---------------------------------------------------

    async def prepare_write(self, course: Course, actor: User) -> CourseRevision | None:
        """Call before any content write. Returns the revision the write belongs
        to (creating it, and cloning the live tree for a published course, on
        first edit), or None when governance is off and writes go straight to the
        live rows as they always did. Rejects writes while content is under review."""
        if not governance_active():
            return None
        if course.governance_status == CourseLifecycleEnum.ARCHIVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "This course is archived - reinstate it before editing")

        revision = await self.get_open_revision(course.id)
        if revision is None:
            revision = await self._open_revision(course, actor)
        if revision.status not in EDITABLE_STATUSES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"This course's changes are under review ({revision.status.value}) and can't be edited. "
                "Withdraw the revision from review to make further changes.",
            )
        await self.record_contributor(revision, actor)
        return revision

    async def open_revision(self, course: Course, actor: User) -> CourseRevision:
        """Explicitly start (or return the existing) working copy."""
        revision = await self.get_open_revision(course.id)
        if revision is not None:
            return revision
        if course.governance_status == CourseLifecycleEnum.ARCHIVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "This course is archived - reinstate it before editing")
        return await self._open_revision(course, actor)

    async def _open_revision(self, course: Course, actor: User, kind: RevisionKindEnum | None = None) -> CourseRevision:
        course = await self._lock_course(course.id)
        existing = await self.get_open_revision(course.id)  # lost a race - reuse the winner's
        if existing is not None:
            return existing

        if kind is None:
            kind = (
                RevisionKindEnum.CHANGE
                if course.governance_status == CourseLifecycleEnum.PUBLISHED
                else RevisionKindEnum.INITIAL
            )
        revision = CourseRevision(
            course_id=course.id,
            kind=kind,
            author_id=actor.id,
            status=ContentStatusEnum.DRAFT,
            base_version_id=course.current_version_id,
            course_changes={},
            created_by=actor.id,
        )
        self.session.add(revision)
        await self.session.flush()
        AuditService(self.session).record(
            actor_id=actor.id,
            action="REVISION_OPENED",
            entity_type=AuditEntityTypeEnum.COURSE_REVISION,
            entity_id=revision.id,
            course_id=course.id,
            revision_id=revision.id,
            to_status=revision.status,
            metadata={"kind": kind.value, "base_version": course.current_version_label},
        )

        if kind in (RevisionKindEnum.CHANGE, RevisionKindEnum.ROLLBACK):
            await self.ensure_base_snapshot(course)
            await self._clone_live_tree(course, revision)
        return revision

    async def record_contributor(self, revision: CourseRevision, actor: User) -> None:
        now = datetime.now(timezone.utc)
        stmt = select(RevisionContributor).where(
            RevisionContributor.revision_id == revision.id, RevisionContributor.user_id == actor.id
        )
        contributor = (await self.session.execute(stmt)).scalar_one_or_none()
        if contributor is None:
            self.session.add(
                RevisionContributor(revision_id=revision.id, user_id=actor.id, first_edit_at=now, last_edit_at=now)
            )
        else:
            contributor.last_edit_at = now
        await self.session.flush()

    async def ensure_base_snapshot(self, course: Course) -> None:
        """Capture the live content into the current version's snapshot if it was
        never captured (pre-governance baseline) - before any edit can change it."""
        if course.current_version_id is None:
            return
        version = await self.session.get(CourseVersion, course.current_version_id)
        if version is not None and version.snapshot is None:
            with include_drafts(self.session):
                snapshot = await build_normalized_tree(self.session, course)
            version.snapshot = snapshot
            version.snapshot_hash = tree_hash(snapshot)
            await self.session.flush()

    async def _clone_live_tree(self, course: Course, revision: CourseRevision) -> None:
        with include_drafts(self.session):
            live_sections = (
                await self.session.execute(
                    select(CourseSection).where(
                        CourseSection.course_id == course.id,
                        CourseSection.revision_id.is_(None),
                        CourseSection.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            section_map: dict[uuid.UUID, uuid.UUID] = {}
            for section in live_sections:
                draft = _clone(section, revision_id=revision.id, draft_of_id=section.id)
                self.session.add(draft)
                await self.session.flush()
                section_map[section.id] = draft.id
                links = (
                    await self.session.execute(
                        select(CourseSectionInstructor).where(
                            CourseSectionInstructor.section_id == section.id,
                            CourseSectionInstructor.deleted_at.is_(None),
                        )
                    )
                ).scalars().all()
                for link in links:
                    self.session.add(_clone(link, section_id=draft.id))

            if not section_map:
                await self.session.flush()
                return
            live_items = (
                await self.session.execute(
                    select(CourseItem).where(
                        CourseItem.section_id.in_(list(section_map)), CourseItem.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            for item in live_items:
                draft_item = _clone(
                    item, section_id=section_map[item.section_id], revision_id=revision.id, draft_of_id=item.id
                )
                self.session.add(draft_item)
                await self.session.flush()
                await self._clone_item_children(item.id, draft_item.id)
            await self.session.flush()

    async def _clone_item_children(self, live_item_id: uuid.UUID, draft_item_id: uuid.UUID) -> None:
        for model in _ITEM_CHILD_MODELS:
            row = (await self.session.execute(select(model).where(model.course_item_id == live_item_id))).scalar_one_or_none()
            if row is not None:
                self.session.add(_clone(row, course_item_id=draft_item_id))

        assessment = (
            await self.session.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == live_item_id))
        ).scalar_one_or_none()
        if assessment is None:
            return
        draft_assessment = _clone(assessment, course_item_id=draft_item_id)
        self.session.add(draft_assessment)
        await self.session.flush()

        for model in _SETTINGS_MODELS:
            row = (await self.session.execute(select(model).where(model.assessment_id == assessment.id))).scalar_one_or_none()
            if row is not None:
                self.session.add(_clone(row, assessment_id=draft_assessment.id))

        group_map: dict[uuid.UUID, uuid.UUID] = {}
        group_sections = (
            await self.session.execute(
                select(CourseQuizGroupSection).where(
                    CourseQuizGroupSection.assessment_id == assessment.id, CourseQuizGroupSection.deleted_at.is_(None)
                )
            )
        ).scalars().all()
        for gs in group_sections:
            draft_gs = _clone(gs, assessment_id=draft_assessment.id, draft_of_id=gs.id)
            self.session.add(draft_gs)
            await self.session.flush()
            group_map[gs.id] = draft_gs.id

        questions = (
            await self.session.execute(
                select(CourseQuizQuestion).where(
                    CourseQuizQuestion.assessment_id == assessment.id, CourseQuizQuestion.deleted_at.is_(None)
                )
            )
        ).scalars().all()
        for question in questions:
            draft_q = _clone(
                question,
                assessment_id=draft_assessment.id,
                section_id=group_map.get(question.section_id) if question.section_id else None,
                draft_of_id=question.id,
            )
            self.session.add(draft_q)
            await self.session.flush()
            options = (
                await self.session.execute(
                    select(CourseQuizOption).where(
                        CourseQuizOption.question_id == question.id, CourseQuizOption.deleted_at.is_(None)
                    )
                )
            ).scalars().all()
            for option in options:
                self.session.add(_clone(option, question_id=draft_q.id, draft_of_id=option.id))

    # -- id translation (live id -> this revision's draft counterpart) -------------

    def _not_in_draft(self, what: str) -> HTTPException:
        return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found in the working copy (it may have been removed)")

    async def translate_section(self, section: CourseSection, revision: CourseRevision | None) -> CourseSection:
        if not self.is_cloned(revision):
            if section.revision_id is not None:
                raise self._not_in_draft("Section")
            return section
        if section.revision_id == revision.id:
            return section
        if section.revision_id is not None:
            raise self._not_in_draft("Section")
        with include_drafts(self.session):
            draft = (
                await self.session.execute(
                    select(CourseSection).where(
                        CourseSection.draft_of_id == section.id,
                        CourseSection.revision_id == revision.id,
                        CourseSection.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        if draft is None:
            raise self._not_in_draft("Section")
        return draft

    async def translate_item(self, item: CourseItem, revision: CourseRevision | None) -> CourseItem:
        if not self.is_cloned(revision):
            if item.revision_id is not None:
                raise self._not_in_draft("Item")
            return item
        if item.revision_id == revision.id:
            return item
        if item.revision_id is not None:
            raise self._not_in_draft("Item")
        with include_drafts(self.session):
            draft = (
                await self.session.execute(
                    select(CourseItem).where(
                        CourseItem.draft_of_id == item.id,
                        CourseItem.revision_id == revision.id,
                        CourseItem.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        if draft is None:
            raise self._not_in_draft("Item")
        return draft

    async def translate_assessment(
        self, assessment: CourseAssessment, revision: CourseRevision | None
    ) -> CourseAssessment:
        with include_drafts(self.session):
            item = await self.session.get(CourseItem, assessment.course_item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
        draft_item = await self.translate_item(item, revision)
        if draft_item.id == item.id:
            return assessment
        draft = (
            await self.session.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == draft_item.id))
        ).scalar_one_or_none()
        if draft is None:
            raise self._not_in_draft("Assessment")
        return draft

    async def _translate_quiz_row(self, model, row, parent_filter, revision: CourseRevision | None):
        """Shared by group sections / questions / options: a row already under the
        draft parent is returned as-is; a live row is mapped through draft_of_id."""
        stmt = select(model).where(model.draft_of_id == row.id, parent_filter, model.deleted_at.is_(None))
        draft = (await self.session.execute(stmt)).scalar_one_or_none()
        if draft is None:
            raise self._not_in_draft(model.__name__.replace("Course", ""))
        return draft

    async def translate_group_section(
        self, group_section: CourseQuizGroupSection, revision: CourseRevision | None
    ) -> CourseQuizGroupSection:
        assessment = await self.session.get(CourseAssessment, group_section.assessment_id)
        draft_assessment = await self.translate_assessment(assessment, revision)
        if draft_assessment.id == assessment.id:
            return group_section
        return await self._translate_quiz_row(
            CourseQuizGroupSection, group_section, CourseQuizGroupSection.assessment_id == draft_assessment.id, revision
        )

    async def translate_question(
        self, question: CourseQuizQuestion, revision: CourseRevision | None
    ) -> CourseQuizQuestion:
        assessment = await self.session.get(CourseAssessment, question.assessment_id)
        draft_assessment = await self.translate_assessment(assessment, revision)
        if draft_assessment.id == assessment.id:
            return question
        return await self._translate_quiz_row(
            CourseQuizQuestion, question, CourseQuizQuestion.assessment_id == draft_assessment.id, revision
        )

    async def translate_option(self, option: CourseQuizOption, revision: CourseRevision | None) -> CourseQuizOption:
        question = await self.session.get(CourseQuizQuestion, option.question_id)
        draft_question = await self.translate_question(question, revision)
        if draft_question.id == question.id:
            return option
        return await self._translate_quiz_row(
            CourseQuizOption, option, CourseQuizOption.question_id == draft_question.id, revision
        )

    async def to_live_item(self, item: CourseItem) -> CourseItem | None:
        """Draft item -> the live item it shadows (None for a newly added one).
        Marking/grading always operates on live items."""
        if item.revision_id is None:
            return item
        if item.draft_of_id is None:
            return None
        with include_drafts(self.session):
            return await self.session.get(CourseItem, item.draft_of_id)

    # -- course-row edits -------------------------------------------------------------

    async def stage_course_changes(self, course: Course, changes: dict, actor: User) -> CourseRevision | None:
        """Route edits to the course row's academic fields. While a published
        course has governance on, they are held in the working copy's overlay and
        applied on publish; otherwise they're written live as before."""
        academic = {k: v for k, v in changes.items() if k in ACADEMIC_COURSE_FIELDS}
        if not academic:
            return None
        revision = await self.prepare_write(course, actor)
        if not self.is_cloned(revision):
            for field_name, value in academic.items():
                setattr(course, field_name, value)
            return revision
        from app.modules.governance.tree import to_json_value

        merged = dict(revision.course_changes or {})
        for field_name, value in academic.items():
            if to_json_value(getattr(course, field_name)) == to_json_value(value):
                merged.pop(field_name, None)  # edited back to the live value
            else:
                merged[field_name] = to_json_value(value)
        revision.course_changes = merged
        await self.session.flush()
        return revision

    # -- merge on publish -------------------------------------------------------------

    async def merge(self, revision: CourseRevision, course: Course, actor: User) -> MergeResult:
        """Apply the working copy onto the live rows, in place. The caller holds
        the course lock and commits; everything here runs in its transaction."""
        result = MergeResult()
        self._apply_course_changes(course, revision.course_changes or {})
        if not self.is_cloned(revision):
            return result

        with include_drafts(self.session):
            await self._merge_tree(revision, course, actor, result)
            await self._purge_draft_rows(revision, hard=True)
        return result

    def _apply_course_changes(self, course: Course, changes: dict) -> None:
        for field_name, value in changes.items():
            if field_name not in ACADEMIC_COURSE_FIELDS:
                continue
            if field_name in ("level", "category") and value is not None:
                enum_cls = type(getattr(course, field_name))
                value = enum_cls(value)
            if field_name == "certificate_template_id" and value is not None:
                value = uuid.UUID(str(value))
            setattr(course, field_name, value)

    async def _merge_tree(self, revision: CourseRevision, course: Course, actor: User, result: MergeResult) -> None:
        s = self.session
        draft_sections = (
            await s.execute(
                select(CourseSection).where(CourseSection.revision_id == revision.id, CourseSection.deleted_at.is_(None))
            )
        ).scalars().all()
        live_sections = (
            await s.execute(
                select(CourseSection).where(
                    CourseSection.course_id == course.id,
                    CourseSection.revision_id.is_(None),
                    CourseSection.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        section_map: dict[uuid.UUID, uuid.UUID] = {}
        matched_sections: set[uuid.UUID] = set()
        for draft in draft_sections:
            if draft.draft_of_id is not None:
                live = await s.get(CourseSection, draft.draft_of_id)
                live.title = draft.title
                live.order_index = draft.order_index
                if live.deleted_at is not None:
                    live.mark_restored(actor.id)
                await self._replace_section_instructors(live.id, draft.id)
                section_map[draft.id] = live.id
                matched_sections.add(live.id)
            else:
                draft.revision_id = None  # promote: the new section becomes live as-is
                section_map[draft.id] = draft.id
        for live in live_sections:
            if live.id not in matched_sections:
                live.mark_deleted(actor.id)
                result.item_set_changed = True

        draft_items = []
        if draft_sections:
            draft_items = (
                await s.execute(
                    select(CourseItem).where(
                        CourseItem.revision_id == revision.id,
                        CourseItem.deleted_at.is_(None),
                        CourseItem.section_id.in_([d.id for d in draft_sections]),
                    )
                )
            ).scalars().all()
        live_items = (
            await s.execute(
                select(CourseItem)
                .join(CourseSection, CourseSection.id == CourseItem.section_id)
                .where(
                    CourseSection.course_id == course.id,
                    CourseSection.revision_id.is_(None),
                    CourseItem.revision_id.is_(None),
                    CourseItem.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        matched_items: set[uuid.UUID] = set()
        for draft in draft_items:
            target_section = section_map[draft.section_id]
            if draft.draft_of_id is not None:
                live = await s.get(CourseItem, draft.draft_of_id)
                if live.item_type != draft.item_type:
                    raise HTTPException(status.HTTP_409_CONFLICT, f"Item '{draft.title}' changed type; recreate it instead")
                live.title = draft.title
                live.order_index = draft.order_index
                live.is_preview = draft.is_preview
                live.estimated_minutes = draft.estimated_minutes
                live.section_id = target_section
                if live.deleted_at is not None:
                    live.mark_restored(actor.id)
                    result.item_set_changed = True
                await self._merge_item_children(live.id, draft.id, actor)
                matched_items.add(live.id)
            else:
                draft.revision_id = None
                draft.section_id = target_section
                result.item_set_changed = True
                await self._set_assessment_status(draft.id, AssessmentDesignStatusEnum.LIVE)
                if draft.item_type == CourseItemTypeEnum.LIVE_SESSION:
                    result.promoted_live_session_item_ids.append(draft.id)

        for live in live_items:
            if live.id in matched_items:
                continue
            live.mark_deleted(actor.id)
            result.item_set_changed = True
            await self._set_assessment_status(live.id, AssessmentDesignStatusEnum.WITHDRAWN)
            if live.item_type == CourseItemTypeEnum.LIVE_SESSION:
                session_row = (
                    await s.execute(select(CourseLiveSession).where(CourseLiveSession.course_item_id == live.id))
                ).scalar_one_or_none()
                if session_row is not None:
                    result.removed_live_session_room_names.append(session_row.daily_room_name)
        await s.flush()

    async def _replace_section_instructors(self, live_section_id: uuid.UUID, draft_section_id: uuid.UUID) -> None:
        await self.session.execute(
            CourseSectionInstructor.__table__.delete().where(CourseSectionInstructor.section_id == live_section_id)
        )
        await self.session.execute(
            CourseSectionInstructor.__table__.update()
            .where(CourseSectionInstructor.section_id == draft_section_id)
            .values(section_id=live_section_id)
        )

    async def _set_assessment_status(self, item_id: uuid.UUID, value: AssessmentDesignStatusEnum) -> None:
        assessment = (
            await self.session.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == item_id))
        ).scalar_one_or_none()
        if assessment is not None:
            assessment.design_status = value

    async def _merge_item_children(self, live_item_id: uuid.UUID, draft_item_id: uuid.UUID, actor: User) -> None:
        s = self.session
        for model in _ITEM_CHILD_MODELS:
            draft = (await s.execute(select(model).where(model.course_item_id == draft_item_id))).scalar_one_or_none()
            live = (await s.execute(select(model).where(model.course_item_id == live_item_id))).scalar_one_or_none()
            if draft is not None and live is not None:
                _copy_onto(draft, live, exclude={"course_item_id"})
                await s.delete(draft)
            elif draft is not None:
                draft.course_item_id = live_item_id
        await s.flush()

        draft_a = (
            await s.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == draft_item_id))
        ).scalar_one_or_none()
        live_a = (
            await s.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == live_item_id))
        ).scalar_one_or_none()
        if draft_a is None:
            return
        if live_a is None:
            draft_a.course_item_id = live_item_id
            draft_a.design_status = AssessmentDesignStatusEnum.LIVE
            return

        live_a.due_date = draft_a.due_date
        live_a.is_final_assessment = draft_a.is_final_assessment
        live_a.design_status = AssessmentDesignStatusEnum.LIVE

        for model in _SETTINGS_MODELS:
            d = (await s.execute(select(model).where(model.assessment_id == draft_a.id))).scalar_one_or_none()
            l = (await s.execute(select(model).where(model.assessment_id == live_a.id))).scalar_one_or_none()
            if d is not None and l is not None:
                _copy_onto(d, l, exclude={"assessment_id"})
                await s.delete(d)
            elif d is not None:
                d.assessment_id = live_a.id
        await s.flush()

        # Group sections, then questions, then options: matched rows copy onto
        # the live row (keeping its id); new rows are re-parented under the live
        # parent; live rows with no surviving draft counterpart are soft-deleted
        # - only after re-parenting, so nothing new is left under a deleted parent.
        gs_map = await self._merge_keyed(
            CourseQuizGroupSection, "assessment_id", draft_a.id, live_a.id, {}, actor,
            fields=("title", "order_index", "questions_to_ask"),
        )
        q_map = await self._merge_keyed(
            CourseQuizQuestion, "assessment_id", draft_a.id, live_a.id, gs_map, actor,
            fields=("text", "order_index", "allow_multiple_answers", "multi_answer_mode"),
        )
        for draft_q_id, live_q_id in q_map.items():
            await self._merge_keyed(
                CourseQuizOption, "question_id", draft_q_id, live_q_id, {}, actor,
                fields=("text", "is_correct", "order_index"),
            )
        await s.flush()

    async def _merge_keyed(
        self, model, parent_attr: str, draft_parent_id, live_parent_id, section_map: dict, actor: User, fields
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Returns {draft row id -> live row id} for the surviving rows."""
        s = self.session
        parent_col = getattr(model, parent_attr)
        drafts = (
            await s.execute(select(model).where(parent_col == draft_parent_id, model.deleted_at.is_(None)))
        ).scalars().all()
        lives = (
            await s.execute(select(model).where(parent_col == live_parent_id, model.deleted_at.is_(None)))
        ).scalars().all()
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        matched: set[uuid.UUID] = set()
        for draft in drafts:
            new_section_id = None
            if model is CourseQuizQuestion and draft.section_id is not None:
                if draft.section_id in section_map:
                    new_section_id = section_map[draft.section_id]
                else:
                    # Its group section was deleted in the working copy: point at
                    # the live section it shadowed (soft-deleted below), or drop
                    # the question if that section never went live.
                    removed = await s.get(CourseQuizGroupSection, draft.section_id)
                    new_section_id = removed.draft_of_id if removed is not None else None
                    if new_section_id is None:
                        draft.mark_deleted(actor.id)
                        continue
            if draft.draft_of_id is not None:
                live = await s.get(model, draft.draft_of_id)
                for f in fields:
                    setattr(live, f, getattr(draft, f))
                if model is CourseQuizQuestion:
                    live.section_id = new_section_id
                if live.deleted_at is not None:
                    live.mark_restored(actor.id)
                setattr(live, parent_attr, live_parent_id)
                mapping[draft.id] = live.id
                matched.add(live.id)
            else:
                setattr(draft, parent_attr, live_parent_id)
                if model is CourseQuizQuestion:
                    draft.section_id = new_section_id
                mapping[draft.id] = draft.id
        for live in lives:
            if live.id not in matched and live.id not in mapping.values():
                live.mark_deleted(actor.id)
        await s.flush()
        return mapping

    async def _purge_draft_rows(self, revision: CourseRevision, hard: bool) -> None:
        """Remove what's left of a working copy. `hard=True` after a merge (the
        surviving content now lives on the live rows); otherwise soft-delete, so a
        rejected/discarded revision's draft stays inspectable."""
        s = self.session
        draft_sections = (
            await s.execute(select(CourseSection).where(CourseSection.revision_id == revision.id))
        ).scalars().all()
        draft_items = (await s.execute(select(CourseItem).where(CourseItem.revision_id == revision.id))).scalars().all()

        if not hard:
            for row in [*draft_items, *draft_sections]:
                if row.deleted_at is None:
                    row.mark_deleted()
            await s.flush()
            return

        item_ids = [i.id for i in draft_items]
        if item_ids:
            assessments = (
                await s.execute(select(CourseAssessment).where(CourseAssessment.course_item_id.in_(item_ids)))
            ).scalars().all()
            assessment_ids = [a.id for a in assessments]
            if assessment_ids:
                question_ids = (
                    await s.execute(select(CourseQuizQuestion.id).where(CourseQuizQuestion.assessment_id.in_(assessment_ids)))
                ).scalars().all()
                if question_ids:
                    await s.execute(CourseQuizOption.__table__.delete().where(CourseQuizOption.question_id.in_(question_ids)))
                await s.execute(CourseQuizQuestion.__table__.delete().where(CourseQuizQuestion.assessment_id.in_(assessment_ids)))
                await s.execute(
                    CourseQuizGroupSection.__table__.delete().where(CourseQuizGroupSection.assessment_id.in_(assessment_ids))
                )
                for model in _SETTINGS_MODELS:
                    await s.execute(model.__table__.delete().where(model.assessment_id.in_(assessment_ids)))
                await s.execute(CourseAssessment.__table__.delete().where(CourseAssessment.id.in_(assessment_ids)))
            for model in _ITEM_CHILD_MODELS:
                await s.execute(model.__table__.delete().where(model.course_item_id.in_(item_ids)))
            # Live sessions created on a draft item that never went live.
            await s.execute(CourseLiveSession.__table__.delete().where(CourseLiveSession.course_item_id.in_(item_ids)))
            await s.execute(CourseItem.__table__.delete().where(CourseItem.id.in_(item_ids)))
        section_ids = [x.id for x in draft_sections]
        if section_ids:
            await s.execute(
                CourseSectionInstructor.__table__.delete().where(CourseSectionInstructor.section_id.in_(section_ids))
            )
            await s.execute(CourseSection.__table__.delete().where(CourseSection.id.in_(section_ids)))
        # Bulk deletes bypass the identity map - drop the stale objects from it.
        for obj in [*draft_items, *draft_sections]:
            if obj in s:
                s.expunge(obj)

    async def discard(self, revision: CourseRevision) -> None:
        if self.is_cloned(revision):
            with include_drafts(self.session):
                await self._purge_draft_rows(revision, hard=False)

    # -- rollback ---------------------------------------------------------------------

    async def open_rollback(self, course: Course, version: CourseVersion, actor: User) -> CourseRevision:
        """A ROLLBACK revision whose working copy is the live tree reshaped to match
        `version`'s snapshot. Rows the snapshot has but live no longer does (soft-
        deleted since) come back through draft_of_id, so merge restores the
        original rows - and with them any learner progress still attached."""
        if version.snapshot is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "That version has no content snapshot to restore")
        if await self.get_open_revision(course.id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "This course already has changes in progress - publish or discard them first"
            )
        revision = await self._open_revision(course, actor, kind=RevisionKindEnum.ROLLBACK)
        revision.rollback_to_version_id = version.id
        snapshot = version.snapshot
        with include_drafts(self.session):
            await self._apply_snapshot(revision, course, snapshot)
        revision.course_changes = {
            k: v
            for k, v in snapshot.get("course", {}).items()
            if k in ACADEMIC_COURSE_FIELDS and v != _json(getattr(course, k))
        }
        await self.record_contributor(revision, actor)
        await self.session.flush()
        return revision

    async def _apply_snapshot(self, revision: CourseRevision, course: Course, snapshot: dict) -> None:
        s = self.session
        drafts = (
            await s.execute(
                select(CourseSection).where(CourseSection.revision_id == revision.id, CourseSection.deleted_at.is_(None))
            )
        ).scalars().all()
        by_key = {str(d.draft_of_id): d for d in drafts}
        keep: set[uuid.UUID] = set()
        snapshot_item_keys = {
            item["key"] for section in snapshot.get("sections", []) for item in section.get("items", [])
        }

        for snap_section in snapshot.get("sections", []):
            draft = by_key.get(snap_section["key"])
            if draft is None:
                draft = CourseSection(
                    course_id=course.id,
                    title=snap_section["title"],
                    order_index=snap_section["order_index"],
                    revision_id=revision.id,
                    draft_of_id=await self._existing_id(CourseSection, snap_section["key"]),
                )
                s.add(draft)
                await s.flush()
            draft.title = snap_section["title"]
            draft.order_index = snap_section["order_index"]
            keep.add(draft.id)
            await self._apply_snapshot_items(revision, draft, snap_section.get("items", []))
        for draft in drafts:
            if draft.id not in keep:
                draft.mark_deleted()
        # Items the snapshot doesn't contain at all are dropped; items it moved
        # to another module were already re-parented section by section above.
        draft_items = (
            await s.execute(
                select(CourseItem).where(CourseItem.revision_id == revision.id, CourseItem.deleted_at.is_(None))
            )
        ).scalars().all()
        for item in draft_items:
            if str(item.draft_of_id or item.id) not in snapshot_item_keys:
                item.mark_deleted()
        await s.flush()

    async def _existing_id(self, model, key: str) -> uuid.UUID | None:
        """The live row for a snapshot key, if it still exists (even soft-deleted)."""
        try:
            row_id = uuid.UUID(key)
        except ValueError:
            return None
        row = await self.session.get(model, row_id)
        return row.id if row is not None else None

    async def _apply_snapshot_items(self, revision: CourseRevision, draft_section: CourseSection, snap_items: list) -> None:
        s = self.session
        existing = (
            await s.execute(
                select(CourseItem).where(CourseItem.revision_id == revision.id, CourseItem.deleted_at.is_(None))
            )
        ).scalars().all()
        by_key = {str(i.draft_of_id): i for i in existing if i.draft_of_id is not None}

        for snap in snap_items:
            draft = by_key.get(snap["key"])
            if draft is None:
                draft = CourseItem(
                    section_id=draft_section.id,
                    title=snap["title"],
                    item_type=CourseItemTypeEnum(snap["item_type"]),
                    order_index=snap["order_index"],
                    is_preview=snap["is_preview"],
                    estimated_minutes=snap["estimated_minutes"],
                    revision_id=revision.id,
                    draft_of_id=await self._existing_id(CourseItem, snap["key"]),
                )
                s.add(draft)
                await s.flush()
            draft.section_id = draft_section.id
            draft.title = snap["title"]
            draft.order_index = snap["order_index"]
            draft.is_preview = snap["is_preview"]
            draft.estimated_minutes = snap["estimated_minutes"]
            await self._apply_snapshot_children(draft, snap)
        await s.flush()

    async def _apply_snapshot_children(self, draft: CourseItem, snap: dict) -> None:
        s = self.session
        child_specs = ((CourseVideo, "video"), (CourseDocument, "document"), (CourseLink, "link"))
        for model, key in child_specs:
            data = snap.get(key)
            row = (await s.execute(select(model).where(model.course_item_id == draft.id))).scalar_one_or_none()
            if data is None:
                continue
            if row is None:
                row = model(course_item_id=draft.id, **_from_json(model, data))
                s.add(row)
            else:
                for k, v in _from_json(model, data).items():
                    setattr(row, k, v)

        snap_a = snap.get("assessment")
        if snap_a is None:
            return
        assessment = (
            await s.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == draft.id))
        ).scalar_one_or_none()
        if assessment is None:
            assessment = CourseAssessment(
                course_item_id=draft.id,
                assessment_type=AssessmentTypeEnum(snap_a["assessment_type"]),
                is_final_assessment=snap_a["is_final_assessment"],
            )
            s.add(assessment)
            await s.flush()
        assessment.due_date = _parse_dt(snap_a.get("due_date"))
        assessment.is_final_assessment = snap_a["is_final_assessment"]

        settings_model = {
            "QUIZ": CourseQuizSettings, "ESSAY": CourseEssaySettings, "QUIZ_GROUP": CourseQuizGroupSettings,
        }[snap_a["assessment_type"]]
        settings_row = (
            await s.execute(select(settings_model).where(settings_model.assessment_id == assessment.id))
        ).scalar_one_or_none()
        if snap_a.get("settings"):
            values = _from_json(settings_model, snap_a["settings"])
            if settings_row is None:
                s.add(settings_model(assessment_id=assessment.id, **values))
            else:
                for k, v in values.items():
                    setattr(settings_row, k, v)

        gs_rows = await self._apply_snapshot_rows(
            CourseQuizGroupSection, "assessment_id", assessment.id, snap_a.get("group_sections", []),
            lambda d: {"title": d["title"], "order_index": d["order_index"], "questions_to_ask": d["questions_to_ask"]},
        )
        gs_by_key = {k: row.id for k, row in gs_rows.items()}
        q_rows = await self._apply_snapshot_rows(
            CourseQuizQuestion, "assessment_id", assessment.id, snap_a.get("questions", []),
            lambda d: {
                "text": d["text"],
                "order_index": d["order_index"],
                "allow_multiple_answers": d["allow_multiple_answers"],
                "multi_answer_mode": d["multi_answer_mode"],
                "section_id": gs_by_key.get(d["section_key"]) if d.get("section_key") else None,
            },
        )
        for snap_q in snap_a.get("questions", []):
            await self._apply_snapshot_rows(
                CourseQuizOption, "question_id", q_rows[snap_q["key"]].id, snap_q.get("options", []),
                lambda d: {"text": d["text"], "is_correct": d["is_correct"], "order_index": d["order_index"]},
            )

    async def _apply_snapshot_rows(self, model, parent_attr: str, parent_id, snap_rows: list, values_of) -> dict:
        s = self.session
        parent_col = getattr(model, parent_attr)
        existing = (
            await s.execute(select(model).where(parent_col == parent_id, model.deleted_at.is_(None)))
        ).scalars().all()
        by_key = {str(r.draft_of_id or r.id): r for r in existing}
        result = {}
        for snap in snap_rows:
            row = by_key.get(snap["key"])
            if row is None:
                row = model(**{parent_attr: parent_id}, draft_of_id=await self._existing_id(model, snap["key"]), **values_of(snap))
                s.add(row)
                await s.flush()
            else:
                for k, v in values_of(snap).items():
                    setattr(row, k, v)
            result[snap["key"]] = row
        keep = {r.id for r in result.values()}
        for row in existing:
            if row.id not in keep:
                row.mark_deleted()
        await s.flush()
        return result


def _json(value):
    from app.modules.governance.tree import to_json_value

    return to_json_value(value)


def _parse_dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _from_json(model, data: dict) -> dict:
    """Snapshot values -> column values (enums/datetimes come back as strings)."""
    columns = set(_columns(model)) - _AUDIT_COLUMNS
    result = {}
    for key, value in data.items():
        if key not in columns:
            continue
        column_type = model.__table__.c[key].type
        enum_cls = getattr(column_type, "enum_class", None)
        if enum_cls is not None and value is not None:
            value = enum_cls(value)
        elif isinstance(value, str) and isinstance(column_type, DateTime):
            value = datetime.fromisoformat(value)
        result[key] = value
    return result
