"""Normalized, JSON-safe snapshot of a course's content - one shape used for
version snapshots, the reviewer diff view and risk classification.

Every node carries a `key`: the live row's id, or for a draft-layer row the id
of the live row it shadows (`draft_of_id`). So a live tree and a draft tree of
the same course line up node-for-node and can be diffed directly.
"""

import enum
import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.content_entity import (
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
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.course.instructor_entity import CourseInstructor, CourseSectionInstructor

# Course-row fields that are academic content and therefore go through review.
# Everything else on the course (price, access window, thumbnail, featuring,
# instructor credits) is operational/commercial and is edited live.
ACADEMIC_COURSE_FIELDS = (
    "title",
    "description",
    "prerequisite",
    "level",
    "category",
    "what_you_will_learn",
    "material_includes",
    "requirements",
    "certificate_enabled",
    "certificate_template_id",
)

VIDEO_FIELDS = ("bunny_video_guid", "status", "playback_url", "thumbnail_url", "duration_seconds")
DOCUMENT_FIELDS = ("storage_key", "file_name", "mime_type", "file_size_bytes", "is_uploaded", "downloadable")
LINK_FIELDS = ("url", "label", "description")
QUIZ_SETTINGS_FIELDS = ("max_attempts", "pass_mark_percentage", "show_result_to_student")
ESSAY_SETTINGS_FIELDS = (
    "question", "description", "submission_mode", "pass_mark_percentage", "max_attempts", "requires_moderation",
)
GROUP_SETTINGS_FIELDS = ("max_attempts", "pass_mark_percentage", "show_result_to_student", "time_limit_seconds")


def to_json_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json_value(v) for k, v in value.items()}
    return str(value)


def _pick(row, fields) -> dict:
    return {f: to_json_value(getattr(row, f)) for f in fields}


def _key(row) -> str:
    draft_of = getattr(row, "draft_of_id", None)
    return str(draft_of or row.id)


def tree_hash(tree: dict) -> str:
    return hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def build_normalized_tree(
    session: AsyncSession,
    course: Course,
    revision_id: uuid.UUID | None = None,
    course_changes: dict | None = None,
) -> dict:
    """Snapshot the live content (`revision_id=None`) or one revision's draft
    working copy. `course_changes` overlays pending edits to the course row."""
    opts = {"include_drafts": True}
    layer = CourseSection.revision_id.is_(None) if revision_id is None else CourseSection.revision_id == revision_id

    course_data = _pick(course, ACADEMIC_COURSE_FIELDS)
    for field, value in (course_changes or {}).items():
        if field in ACADEMIC_COURSE_FIELDS:
            course_data[field] = to_json_value(value)

    sections = (
        await session.execute(
            select(CourseSection)
            .where(CourseSection.course_id == course.id, CourseSection.deleted_at.is_(None), layer)
            .order_by(CourseSection.order_index, CourseSection.created_at)
            .execution_options(**opts)
        )
    ).scalars().all()
    section_ids = [s.id for s in sections]

    items = []
    if section_ids:
        items = (
            await session.execute(
                select(CourseItem)
                .where(CourseItem.section_id.in_(section_ids), CourseItem.deleted_at.is_(None))
                .order_by(CourseItem.order_index, CourseItem.created_at)
                .execution_options(**opts)
            )
        ).scalars().all()
    item_ids = [i.id for i in items]

    async def by_item(model):
        if not item_ids:
            return {}
        rows = (await session.execute(select(model).where(model.course_item_id.in_(item_ids)))).scalars().all()
        return {r.course_item_id: r for r in rows}

    videos = await by_item(CourseVideo)
    documents = await by_item(CourseDocument)
    links = await by_item(CourseLink)
    assessments = await by_item(CourseAssessment)

    # A draft item reads its live session through draft_of_id - live sessions are
    # operational and never cloned into the working copy.
    live_session_item_ids = [i.draft_of_id or i.id for i in items]
    live_sessions = {}
    if live_session_item_ids:
        rows = (
            await session.execute(
                select(CourseLiveSession).where(CourseLiveSession.course_item_id.in_(live_session_item_ids))
            )
        ).scalars().all()
        live_sessions = {r.course_item_id: r for r in rows}

    guest_names: dict[uuid.UUID, list[str]] = {}
    if section_ids:
        rows = (
            await session.execute(
                select(CourseSectionInstructor.section_id, CourseInstructor.name)
                .join(CourseInstructor, CourseInstructor.id == CourseSectionInstructor.course_instructor_id)
                .where(
                    CourseSectionInstructor.section_id.in_(section_ids),
                    CourseSectionInstructor.deleted_at.is_(None),
                )
                .order_by(CourseSectionInstructor.order_index)
            )
        ).all()
        for section_id, name in rows:
            guest_names.setdefault(section_id, []).append(name)

    assessment_ids = [a.id for a in assessments.values()]

    async def by_assessment(model, ordered=False):
        if not assessment_ids:
            return []
        stmt = select(model).where(model.assessment_id.in_(assessment_ids))
        if hasattr(model, "deleted_at"):
            stmt = stmt.where(model.deleted_at.is_(None))
        if ordered:
            stmt = stmt.order_by(model.order_index, model.created_at)
        return (await session.execute(stmt)).scalars().all()

    quiz_settings = {s.assessment_id: s for s in await by_assessment(CourseQuizSettings)}
    essay_settings = {s.assessment_id: s for s in await by_assessment(CourseEssaySettings)}
    group_settings = {s.assessment_id: s for s in await by_assessment(CourseQuizGroupSettings)}
    group_sections = await by_assessment(CourseQuizGroupSection, ordered=True)
    questions = await by_assessment(CourseQuizQuestion, ordered=True)

    options = []
    if questions:
        options = (
            await session.execute(
                select(CourseQuizOption)
                .where(CourseQuizOption.question_id.in_([q.id for q in questions]), CourseQuizOption.deleted_at.is_(None))
                .order_by(CourseQuizOption.order_index, CourseQuizOption.created_at)
            )
        ).scalars().all()
    options_by_question: dict[uuid.UUID, list] = {}
    for o in options:
        options_by_question.setdefault(o.question_id, []).append(o)
    group_section_key = {gs.id: _key(gs) for gs in group_sections}

    def assessment_node(assessment: CourseAssessment) -> dict:
        if assessment.assessment_type.value == "QUIZ":
            settings = _pick(quiz_settings[assessment.id], QUIZ_SETTINGS_FIELDS) if assessment.id in quiz_settings else {}
        elif assessment.assessment_type.value == "ESSAY":
            settings = _pick(essay_settings[assessment.id], ESSAY_SETTINGS_FIELDS) if assessment.id in essay_settings else {}
        else:
            settings = _pick(group_settings[assessment.id], GROUP_SETTINGS_FIELDS) if assessment.id in group_settings else {}
        return {
            "id": str(assessment.id),
            "assessment_type": assessment.assessment_type.value,
            "due_date": to_json_value(assessment.due_date),
            "is_final_assessment": assessment.is_final_assessment,
            "settings": settings,
            "group_sections": [
                {
                    "key": _key(gs),
                    "title": gs.title,
                    "order_index": gs.order_index,
                    "questions_to_ask": gs.questions_to_ask,
                }
                for gs in group_sections
                if gs.assessment_id == assessment.id
            ],
            "questions": [
                {
                    "key": _key(q),
                    "section_key": group_section_key.get(q.section_id) if q.section_id else None,
                    "text": q.text,
                    "order_index": q.order_index,
                    "allow_multiple_answers": q.allow_multiple_answers,
                    "multi_answer_mode": to_json_value(q.multi_answer_mode),
                    "options": [
                        {"key": _key(o), "text": o.text, "is_correct": o.is_correct, "order_index": o.order_index}
                        for o in options_by_question.get(q.id, [])
                    ],
                }
                for q in questions
                if q.assessment_id == assessment.id
            ],
        }

    items_by_section: dict[uuid.UUID, list] = {}
    for item in items:
        items_by_section.setdefault(item.section_id, []).append(item)

    section_nodes = []
    for section in sections:
        item_nodes = []
        for item in items_by_section.get(section.id, []):
            live_session = live_sessions.get(item.draft_of_id or item.id)
            item_nodes.append(
                {
                    "key": _key(item),
                    "item_type": item.item_type.value,
                    "title": item.title,
                    "order_index": item.order_index,
                    "is_preview": item.is_preview,
                    "estimated_minutes": item.estimated_minutes,
                    "video": _pick(videos[item.id], VIDEO_FIELDS) if item.id in videos else None,
                    "document": _pick(documents[item.id], DOCUMENT_FIELDS) if item.id in documents else None,
                    "link": _pick(links[item.id], LINK_FIELDS) if item.id in links else None,
                    "live_session": (
                        {
                            "id": str(live_session.id),
                            "scheduled_start_at": to_json_value(live_session.scheduled_start_at),
                            "duration_minutes": live_session.duration_minutes,
                            "status": live_session.status.value,
                        }
                        if live_session is not None
                        else None
                    ),
                    "assessment": assessment_node(assessments[item.id]) if item.id in assessments else None,
                }
            )
        section_nodes.append(
            {
                "key": _key(section),
                "title": section.title,
                "order_index": section.order_index,
                "guest_instructors": guest_names.get(section.id, []),
                "items": item_nodes,
            }
        )

    return {"schema": 1, "course": course_data, "sections": section_nodes}
