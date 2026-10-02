"""Builds governance read DTOs, including the per-viewer `available_actions`
that let a frontend show exactly the buttons the caller may use."""

import uuid
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.course.entity import Course
from app.modules.governance.dto import (
    CourseVersionDetailDTO,
    CourseVersionReadDTO,
    ReviewDecisionReadDTO,
    ReviewStageReadDTO,
    RevisionDetailDTO,
    RevisionSummaryDTO,
    UserSummaryDTO,
)
from app.modules.governance.entity import CourseRevision, CourseVersion, ReviewDecision, ReviewStage
from app.modules.governance.enums import (
    CLOSED_STATUSES,
    EDITABLE_STATUSES,
    STAGE_DONE_STATUSES,
    STAGE_OPEN_STATUSES,
    ContentStatusEnum,
    ReviewStageStatusEnum,
)
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.revision_service import RevisionService, stage_views
from app.modules.governance.workflow import (
    ASSIGNING_PERMISSIONS,
    GovernanceRuleError,
    check_can_decide,
    current_stage,
)
from app.modules.user.entity import User


class UserDirectory:
    """Batch-loads user display names for DTOs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._cache: dict[uuid.UUID, UserSummaryDTO] = {}

    async def load(self, ids: Iterable[uuid.UUID | None]) -> None:
        missing = {i for i in ids if i is not None and i not in self._cache}
        if not missing:
            return
        rows = (await self.session.execute(select(User).where(User.id.in_(missing)))).scalars().all()
        for user in rows:
            self._cache[user.id] = UserSummaryDTO(
                id=user.id, name=f"{user.first_name} {user.last_name}".strip(), email=user.email
            )

    def get(self, user_id: uuid.UUID | None) -> UserSummaryDTO | None:
        return self._cache.get(user_id) if user_id else None


def summary_dto(revision: CourseRevision, users: UserDirectory, course: Course | None = None) -> RevisionSummaryDTO:
    return RevisionSummaryDTO(
        id=revision.id,
        course_id=revision.course_id,
        course_title=course.title if course else None,
        kind=revision.kind,
        status=revision.status,
        current_stage=revision.current_stage,
        round=revision.round,
        author=users.get(revision.author_id),
        effective_risk=revision.effective_risk,
        proposed_version_label=revision.proposed_version_label,
        change_summary=revision.change_summary,
        created_at=revision.created_at,
        submitted_at=revision.submitted_at,
        published_at=revision.published_at,
        is_editable=revision.status in EDITABLE_STATUSES,
    )


async def summaries(
    session: AsyncSession, revisions: list[CourseRevision], courses: dict[uuid.UUID, Course] | None = None
) -> list[RevisionSummaryDTO]:
    users = UserDirectory(session)
    await users.load(r.author_id for r in revisions)
    return [summary_dto(r, users, (courses or {}).get(r.course_id)) for r in revisions]


async def detail_dto(
    service: RevisionService, revision: CourseRevision, course: Course, viewer: User
) -> RevisionDetailDTO:
    session = service.session
    stages = await service.all_stages(revision)
    decisions = (
        await session.execute(
            select(ReviewDecision)
            .where(ReviewDecision.revision_id == revision.id)
            .order_by(ReviewDecision.created_at)
        )
    ).scalars().all()
    contributors = await service.contributor_ids(revision)

    users = UserDirectory(session)
    await users.load(
        [
            revision.author_id,
            *contributors,
            *(s.assigned_reviewer_id for s in stages),
            *(s.decided_by for s in stages),
            *(d.actor_id for d in decisions),
        ]
    )
    now = datetime.now(timezone.utc)
    round_stages = [s for s in stages if s.round == revision.round]

    stage_dtos = [
        ReviewStageReadDTO(
            id=s.id,
            round=s.round,
            stage=s.stage,
            sequence=s.sequence,
            status=s.status,
            assigned_reviewer=users.get(s.assigned_reviewer_id),
            due_at=s.due_at,
            decided_by=users.get(s.decided_by),
            decided_at=s.decided_at,
            conditions=s.conditions or [],
            is_overdue=bool(s.due_at and s.due_at < now and s.status in STAGE_OPEN_STATUSES),
        )
        for s in stages
    ]
    decision_dtos = [
        ReviewDecisionReadDTO(
            id=d.id,
            created_at=d.created_at,
            stage=d.stage,
            round=d.round,
            decision=d.decision,
            actor=users.get(d.actor_id),
            comment=d.comment,
            conditions=d.conditions or [],
            from_status=d.from_status,
            to_status=d.to_status,
            version_label=d.version_label,
        )
        for d in decisions
    ]

    # Conditions set by an approval in this round that no later stage has
    # signed off yet - the next reviewer must confirm them.
    open_conditions: list[dict] = []
    ordered = sorted(round_stages, key=lambda s: s.sequence)
    for index, stage in enumerate(ordered):
        if stage.status == ReviewStageStatusEnum.APPROVED_WITH_CONDITIONS:
            later_done = any(
                later.status in STAGE_DONE_STATUSES for later in ordered[index + 1:]
            )
            if not later_done:
                open_conditions += stage.conditions or []

    actions, blocked = await available_actions(service, revision, course, viewer, round_stages, contributors)
    base = summary_dto(revision, users, course)
    return RevisionDetailDTO(
        **base.model_dump(),
        computed_risk=revision.computed_risk,
        declared_risk=revision.declared_risk,
        risk_flags=revision.risk_flags or [],
        risk_reasons=revision.risk_reasons or [],
        risk_override_reason=revision.risk_override_reason,
        touches_assessment=revision.touches_assessment,
        required_stages=revision.required_stages or [],
        reason=revision.reason,
        course_changes=revision.course_changes or {},
        base_version_id=revision.base_version_id,
        published_version_id=revision.published_version_id,
        rollback_to_version_id=revision.rollback_to_version_id,
        ready_at=revision.ready_at,
        lock_version=revision.lock_version,
        contributors=[users.get(c) for c in contributors if users.get(c) is not None],
        stages=stage_dtos,
        decisions=decision_dtos,
        open_conditions=open_conditions,
        available_actions=actions,
        blocked_reason=blocked,
    )


async def available_actions(
    service: RevisionService,
    revision: CourseRevision,
    course: Course,
    viewer: User,
    round_stages: list[ReviewStage],
    contributors: set[uuid.UUID],
) -> tuple[list[str], str | None]:
    perms = await service.permissions.permissions(viewer, course)
    actions: list[str] = []
    blocked: str | None = None
    is_contributor = viewer.id in contributors

    if revision.status in EDITABLE_STATUSES:
        if PermissionEnum.EDIT_DRAFT_CONTENT in perms:
            actions += ["EDIT", "DISCARD"]
        if PermissionEnum.SUBMIT_FOR_REVIEW in perms:
            actions.append("SUBMIT")
    elif revision.status not in CLOSED_STATUSES:
        if is_contributor or PermissionEnum.SUBMIT_FOR_REVIEW in perms:
            actions.append("WITHDRAW")
        current = current_stage(stage_views(round_stages))
        if current is not None:
            context = await service.decision_context(revision)
            try:
                check_can_decide(viewer.id, perms, current, context)
                if current.assigned_reviewer_id is None:
                    actions.append("CLAIM")
                actions += ["APPROVE", "APPROVE_WITH_MINOR_CHANGES", "RETURN_FOR_REVISION", "REJECT", "ESCALATE"]
            except GovernanceRuleError as exc:
                blocked = exc.message
            if perms & ASSIGNING_PERMISSIONS:
                actions.append("ASSIGN_REVIEWER")
            if PermissionEnum.FORCE_APPROVE in perms and not is_contributor:
                actions += ["FORCE_APPROVE", "OVERRIDE_RISK"]
        if revision.status == ContentStatusEnum.READY_TO_PUBLISH and PermissionEnum.PUBLISH_CONTENT in perms:
            actions.append("PUBLISH")
    if revision.status not in CLOSED_STATUSES:
        actions += ["COMMENT", "ATTACH_EVIDENCE"]
    return actions, blocked


async def version_dtos(
    session: AsyncSession, versions: list[CourseVersion], with_snapshot: bool = False
) -> list[CourseVersionReadDTO]:
    users = UserDirectory(session)
    ids: list = []
    for v in versions:
        ids += [v.author_id, v.published_by, *(v.reviewer_ids or [])]
    await users.load(ids)
    result = []
    for v in versions:
        data = dict(
            id=v.id,
            course_id=v.course_id,
            label=v.label,
            major=v.major,
            minor=v.minor,
            revision_id=v.revision_id,
            author=users.get(v.author_id),
            reviewers=[users.get(r) for r in (v.reviewer_ids or []) if users.get(r) is not None],
            approved_at=v.approved_at,
            published_at=v.published_at,
            published_by=users.get(v.published_by),
            reason=v.reason,
            risk_level=v.risk_level,
            is_current=v.is_current,
            has_snapshot=v.snapshot is not None,
        )
        result.append(CourseVersionDetailDTO(**data, snapshot=v.snapshot) if with_snapshot else CourseVersionReadDTO(**data))
    return result
