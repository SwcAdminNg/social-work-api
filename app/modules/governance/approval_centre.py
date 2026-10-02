"""The Approval Centre (framework section 7): one inbox for everyone with a
review or approval role.

Rows are assembled in Python rather than one SQL query: whether a stage is
"awaiting me" depends on per-course permissions *and* separation-of-duties
history, which the workflow rules already express. Open review work is small
(tens to low hundreds of rows), so this stays cheap - revisit with a SQL
pre-filter if it ever isn't.
"""

import enum
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.modules.course.entity import Course
from app.modules.governance.diff import Change
from app.modules.governance.dto import ApprovalCentreCountsDTO, ApprovalCentreRowDTO
from app.modules.governance.entity import CourseRevision, ReviewDecision, ReviewStage
from app.modules.governance.enums import (
    CLOSED_STATUSES,
    EDITABLE_STATUSES,
    ContentStatusEnum,
    ReviewDecisionEnum,
    RevisionKindEnum,
)
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.presenter import UserDirectory
from app.modules.governance.revision_service import RevisionService, stage_views
from app.modules.governance.workflow import (
    ASSIGNING_PERMISSIONS,
    GovernanceRuleError,
    check_can_decide,
    current_stage,
)
from app.modules.user.entity import User

RECENT_DAYS = 30
REVIEW_ACTIONS = ["APPROVE", "APPROVE_WITH_MINOR_CHANGES", "RETURN_FOR_REVISION", "REJECT", "ESCALATE"]


class ApprovalViewEnum(str, enum.Enum):
    AWAITING_ME = "awaiting_me"
    RETURNED_TO_ME = "returned_to_me"
    OVERDUE = "overdue"
    READY_TO_PUBLISH = "ready_to_publish"
    RECENTLY_APPROVED = "recently_approved"
    RECENTLY_REJECTED = "recently_rejected"
    MY_DRAFTS = "my_drafts"


class ApprovalKindEnum(str, enum.Enum):
    COURSE_REVISION = "COURSE_REVISION"
    ESSAY_MARK = "ESSAY_MARK"


def describe_item(revision: CourseRevision, course_title: str) -> tuple[str, str]:
    """(item_title, item_type) for the table's Item/Type columns."""
    if revision.kind == RevisionKindEnum.INITIAL:
        return course_title, "Course"
    if revision.kind == RevisionKindEnum.ROLLBACK:
        return course_title, "Rollback"
    if revision.kind == RevisionKindEnum.REINSTATE:
        return course_title, "Reinstatement"
    changes = [Change(**{k: v for k, v in c.items() if k != "risk"}) for c in (revision.diff_snapshot or [])]
    item_keys = {c.key for c in changes if c.entity != "course" and c.entity != "section"}
    if changes and all(c.in_assessment for c in changes):
        return (changes[0].label.split(" › Q:")[0] if len(item_keys) == 1 else course_title), "Assessment"
    if len(item_keys) == 1 and all(c.entity not in ("course", "section") for c in changes):
        return changes[0].label.split(" › Q:")[0], "Lesson"
    return course_title, "Course update"


class ApprovalCentreService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.revisions = RevisionService(session)
        self._perm_cache: dict[uuid.UUID, set[PermissionEnum]] = {}
        self._courses: dict[uuid.UUID, Course] = {}

    async def _perms(self, actor: User, course: Course) -> set[PermissionEnum]:
        if course.id not in self._perm_cache:
            self._perm_cache[course.id] = await self.revisions.permissions.permissions(actor, course)
        return self._perm_cache[course.id]

    async def _load_courses(self, ids) -> None:
        missing = {i for i in ids if i not in self._courses}
        if missing:
            rows = (await self.session.execute(select(Course).where(Course.id.in_(missing)))).scalars().all()
            self._courses.update({c.id: c for c in rows})

    async def _open_revisions(self, course_id: uuid.UUID | None) -> list[CourseRevision]:
        stmt = select(CourseRevision).where(
            CourseRevision.status.not_in(CLOSED_STATUSES), CourseRevision.deleted_at.is_(None)
        )
        if course_id is not None:
            stmt = stmt.where(CourseRevision.course_id == course_id)
        revisions = list((await self.session.execute(stmt)).scalars().all())
        await self._load_courses(r.course_id for r in revisions)
        return [r for r in revisions if r.course_id in self._courses and self._courses[r.course_id].deleted_at is None]

    async def _current_stages(self, revisions: list[CourseRevision]) -> dict[uuid.UUID, list[ReviewStage]]:
        if not revisions:
            return {}
        stmt = select(ReviewStage).where(ReviewStage.revision_id.in_([r.id for r in revisions]))
        rounds = {r.id: r.round for r in revisions}
        by_revision: dict[uuid.UUID, list[ReviewStage]] = {}
        for stage in (await self.session.execute(stmt)).scalars().all():
            if stage.round == rounds[stage.revision_id]:
                by_revision.setdefault(stage.revision_id, []).append(stage)
        return by_revision

    async def revision_rows(
        self, view: ApprovalViewEnum, actor: User, course_id: uuid.UUID | None = None
    ) -> list[ApprovalCentreRowDTO]:
        now = datetime.now(timezone.utc)
        if view in (ApprovalViewEnum.RECENTLY_APPROVED, ApprovalViewEnum.RECENTLY_REJECTED):
            return await self._recent_rows(view, actor, course_id, now)

        revisions = await self._open_revisions(course_id)
        stages_by_revision = await self._current_stages(revisions)
        users = UserDirectory(self.session)
        await users.load(
            [r.author_id for r in revisions]
            + [s.assigned_reviewer_id for stages in stages_by_revision.values() for s in stages]
        )

        rows: list[ApprovalCentreRowDTO] = []
        for revision in revisions:
            course = self._courses[revision.course_id]
            perms = await self._perms(actor, course)
            stages = stages_by_revision.get(revision.id, [])
            current = current_stage(stage_views(stages)) if revision.status not in EDITABLE_STATUSES else None
            current_row = next((s for s in stages if current and s.id == current.id), None)
            contributors = None

            async def is_contributor() -> bool:
                nonlocal contributors
                if contributors is None:
                    contributors = await self.revisions.contributor_ids(revision)
                return actor.id in contributors

            actions: list[str] = []
            include = False
            if view == ApprovalViewEnum.AWAITING_ME and current is not None:
                try:
                    check_can_decide(actor.id, perms, current, await self.revisions.decision_context(revision))
                    include = True
                    actions = (["CLAIM"] if current.assigned_reviewer_id is None else []) + REVIEW_ACTIONS
                    if perms & ASSIGNING_PERMISSIONS:
                        actions.append("ASSIGN_REVIEWER")
                except GovernanceRuleError:
                    include = False
            elif view == ApprovalViewEnum.RETURNED_TO_ME:
                include = revision.status == ContentStatusEnum.RETURNED_FOR_REVISION and await is_contributor()
                actions = ["EDIT", "SUBMIT"] if include else []
            elif view == ApprovalViewEnum.MY_DRAFTS:
                include = revision.status == ContentStatusEnum.DRAFT and await is_contributor()
                actions = ["EDIT", "SUBMIT", "DISCARD"] if include else []
            elif view == ApprovalViewEnum.READY_TO_PUBLISH:
                include = (
                    revision.status == ContentStatusEnum.READY_TO_PUBLISH
                    and PermissionEnum.PUBLISH_CONTENT in perms
                )
                actions = ["PUBLISH"] if include else []
            elif view == ApprovalViewEnum.OVERDUE and current_row is not None:
                overdue = current_row.due_at is not None and current_row.due_at < now
                if overdue:
                    try:
                        check_can_decide(actor.id, perms, current, await self.revisions.decision_context(revision))
                        include = True
                        actions = REVIEW_ACTIONS
                    except GovernanceRuleError:
                        # Leads see everything overdue on their courses, to chase it.
                        include = bool(perms & ASSIGNING_PERMISSIONS) or await is_contributor()
                        actions = ["ASSIGN_REVIEWER"] if perms & ASSIGNING_PERMISSIONS else []
            if not include:
                continue

            title, item_type = describe_item(revision, course.title)
            rows.append(
                ApprovalCentreRowDTO(
                    kind=ApprovalKindEnum.COURSE_REVISION.value,
                    id=revision.id,
                    item_title=title,
                    item_type=item_type,
                    course_id=course.id,
                    course_title=course.title,
                    submitted_by=users.get(revision.author_id),
                    current_stage=revision.current_stage.value if revision.current_stage else None,
                    status=revision.status.value,
                    reviewer=users.get(current_row.assigned_reviewer_id) if current_row else None,
                    due_at=current_row.due_at if current_row else None,
                    is_overdue=bool(current_row and current_row.due_at and current_row.due_at < now),
                    risk=revision.effective_risk,
                    version_label=revision.proposed_version_label,
                    updated_at=revision.updated_at or revision.submitted_at or revision.created_at,
                    available_actions=actions,
                )
            )
        return rows

    async def _recent_rows(
        self, view: ApprovalViewEnum, actor: User, course_id: uuid.UUID | None, now: datetime
    ) -> list[ApprovalCentreRowDTO]:
        decisions = (
            [ReviewDecisionEnum.APPROVED, ReviewDecisionEnum.APPROVED_WITH_MINOR_CHANGES, ReviewDecisionEnum.FORCE_APPROVED]
            if view == ApprovalViewEnum.RECENTLY_APPROVED
            else [ReviewDecisionEnum.REJECTED, ReviewDecisionEnum.RETURNED_FOR_REVISION]
        )
        stmt = (
            select(ReviewDecision, CourseRevision)
            .join(CourseRevision, CourseRevision.id == ReviewDecision.revision_id)
            .where(
                ReviewDecision.decision.in_(decisions),
                ReviewDecision.created_at >= now - timedelta(days=RECENT_DAYS),
                or_(ReviewDecision.actor_id == actor.id, CourseRevision.author_id == actor.id),
            )
            .order_by(ReviewDecision.created_at.desc())
        )
        if course_id is not None:
            stmt = stmt.where(CourseRevision.course_id == course_id)
        pairs = (await self.session.execute(stmt)).all()
        await self._load_courses(r.course_id for _, r in pairs)
        users = UserDirectory(self.session)
        await users.load([r.author_id for _, r in pairs] + [d.actor_id for d, _ in pairs])
        rows = []
        for decision, revision in pairs:
            course = self._courses.get(revision.course_id)
            if course is None:
                continue
            title, item_type = describe_item(revision, course.title)
            rows.append(
                ApprovalCentreRowDTO(
                    kind=ApprovalKindEnum.COURSE_REVISION.value,
                    id=revision.id,
                    item_title=title,
                    item_type=item_type,
                    course_id=course.id,
                    course_title=course.title,
                    submitted_by=users.get(revision.author_id),
                    current_stage=decision.stage.value if decision.stage else None,
                    status=revision.status.value,
                    reviewer=users.get(decision.actor_id),
                    risk=revision.effective_risk,
                    version_label=decision.version_label,
                    updated_at=decision.created_at,
                    decision=decision.decision.value,
                )
            )
        return rows

    async def list(
        self,
        view: ApprovalViewEnum,
        actor: User,
        pagination: PaginationParams,
        kind: ApprovalKindEnum | None = None,
        course_id: uuid.UUID | None = None,
    ) -> tuple[list[ApprovalCentreRowDTO], int]:
        rows: list[ApprovalCentreRowDTO] = []
        if kind in (None, ApprovalKindEnum.COURSE_REVISION):
            rows += await self.revision_rows(view, actor, course_id)
        if kind in (None, ApprovalKindEnum.ESSAY_MARK):
            from app.modules.marking.service import MarkingService

            rows += await MarkingService(self.session).approval_rows(view.value, actor, course_id)

        if view in (ApprovalViewEnum.RECENTLY_APPROVED, ApprovalViewEnum.RECENTLY_REJECTED):
            rows.sort(key=lambda r: r.updated_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        else:
            # Most urgent first: overdue, then soonest due, then oldest.
            far = datetime.max.replace(tzinfo=timezone.utc)
            rows.sort(key=lambda r: (not r.is_overdue, r.due_at or far))
        total = len(rows)
        return rows[pagination.offset : pagination.offset + pagination.limit], total

    async def counts(self, actor: User) -> ApprovalCentreCountsDTO:
        from app.modules.marking.service import MarkingService

        marking = MarkingService(self.session)

        async def count(view: ApprovalViewEnum) -> int:
            return len(await self.revision_rows(view, actor)) + len(await marking.approval_rows(view.value, actor, None))

        return ApprovalCentreCountsDTO(
            awaiting_me=await count(ApprovalViewEnum.AWAITING_ME),
            returned_to_me=await count(ApprovalViewEnum.RETURNED_TO_ME),
            overdue=await count(ApprovalViewEnum.OVERDUE),
            ready_to_publish=await count(ApprovalViewEnum.READY_TO_PUBLISH),
        )
