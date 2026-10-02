"""Orchestrates the content approval workflow - the only writer of revision
status. Every transition follows one sequence: lock the revision, run the pure
rules (workflow.py), mutate stage/decision/revision rows, write the audit row in
the same transaction, commit, then send notifications.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import delete_cache
from app.core.config import settings
from app.modules.course.content_entity import CourseAssessment
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.diff import Change, diff_trees
from app.modules.governance.draft_scope import include_drafts
from app.modules.governance.draft_service import DraftService
from app.modules.governance.dto import (
    AssignReviewerDTO,
    ReviewDecisionCreateDTO,
    RevisionSubmitDTO,
    RiskOverrideDTO,
)
from app.modules.governance.entity import (
    CourseRevision,
    CourseVersion,
    ReviewDecision,
    ReviewStage,
    RevisionContributor,
)
from app.modules.governance.enums import (
    CLOSED_STATUSES,
    EDITABLE_STATUSES,
    RISK_ORDER,
    STAGE_DONE_STATUSES,
    STAGE_OPEN_STATUSES,
    AssessmentDesignStatusEnum,
    ContentStatusEnum,
    CourseLifecycleEnum,
    ReviewDecisionEnum,
    ReviewStageEnum,
    ReviewStageStatusEnum,
    RevisionKindEnum,
    RiskFlagEnum,
    RiskLevelEnum,
    max_risk,
)
from app.modules.governance.notifier import GovernanceNotifier
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.risk import change_risk, classify, next_version, resolve_required_stages
from app.modules.governance.tree import build_normalized_tree, tree_hash
from app.modules.governance.workflow import (
    STAGE_PERMISSIONS,
    DecisionContext,
    GovernanceRuleError,
    StageView,
    assessment_status_for,
    check_can_assign,
    check_can_claim,
    check_can_decide,
    check_can_force_approve,
    current_stage,
    derive_status,
)
from app.modules.notification.entity import NotificationTypeEnum
from app.modules.user.entity import User

logger = logging.getLogger(__name__)

# Anyone holding one of these for a course may open its revisions and versions.
VIEW_PERMISSIONS = frozenset(
    {
        PermissionEnum.EDIT_DRAFT_CONTENT,
        PermissionEnum.SUBMIT_FOR_REVIEW,
        PermissionEnum.ACADEMIC_REVIEW,
        PermissionEnum.QA_REVIEW,
        PermissionEnum.MODERATE_ASSESSMENT,
        PermissionEnum.APPROVE_COURSE,
        PermissionEnum.FINAL_APPROVAL,
        PermissionEnum.PUBLISH_CONTENT,
        PermissionEnum.ARCHIVE_CONTENT,
    }
)

_STAGE_ORDER = list(ReviewStageEnum)


def _rule_error(exc: GovernanceRuleError) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, exc.message)


def stage_views(stages: list[ReviewStage]) -> list[StageView]:
    return [StageView(s.stage, s.status, s.sequence, s.assigned_reviewer_id, s.decided_by, s.id) for s in stages]


class RevisionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.permissions = PermissionService(session)
        self.drafts = DraftService(session)
        self.audit = AuditService(session)
        self.notifier = GovernanceNotifier(session)

    # -- loading ------------------------------------------------------------------------

    async def get_revision(self, revision_id: uuid.UUID, lock: bool = False) -> CourseRevision:
        stmt = select(CourseRevision).where(CourseRevision.id == revision_id, CourseRevision.deleted_at.is_(None))
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        revision = (await self.session.execute(stmt)).scalar_one_or_none()
        if revision is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        return revision

    async def get_course(self, course_id: uuid.UUID) -> Course:
        course = await self.session.get(Course, course_id)
        if course is None or course.deleted_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
        return course

    async def ensure_can_view(self, actor: User, course: Course) -> set[PermissionEnum]:
        perms = await self.permissions.permissions(actor, course)
        if not perms & VIEW_PERMISSIONS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't have access to this course's reviews")
        return perms

    async def round_stages(self, revision: CourseRevision, round_: int | None = None) -> list[ReviewStage]:
        stmt = (
            select(ReviewStage)
            .where(ReviewStage.revision_id == revision.id, ReviewStage.round == (round_ or revision.round))
            .order_by(ReviewStage.sequence)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def all_stages(self, revision: CourseRevision) -> list[ReviewStage]:
        stmt = (
            select(ReviewStage)
            .where(ReviewStage.revision_id == revision.id)
            .order_by(ReviewStage.round, ReviewStage.sequence)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def contributor_ids(self, revision: CourseRevision) -> set[uuid.UUID]:
        stmt = select(RevisionContributor.user_id).where(RevisionContributor.revision_id == revision.id)
        ids = set((await self.session.execute(stmt)).scalars().all())
        ids.add(revision.author_id)
        return ids

    async def decision_context(self, revision: CourseRevision) -> DecisionContext:
        approvals: dict[uuid.UUID, set[ReviewStageEnum]] = {}
        for stage in await self.all_stages(revision):
            if stage.decided_by is not None and stage.status in (
                ReviewStageStatusEnum.APPROVED, ReviewStageStatusEnum.APPROVED_WITH_CONDITIONS
            ):
                approvals.setdefault(stage.decided_by, set()).add(stage.stage)
        return DecisionContext(contributors=await self.contributor_ids(revision), approvals_by_user=approvals)

    async def current_version(self, course: Course) -> CourseVersion | None:
        if course.current_version_id is None:
            return None
        return await self.session.get(CourseVersion, course.current_version_id)

    # -- helpers ------------------------------------------------------------------------

    def _refresh_status(self, revision: CourseRevision, stages: list[ReviewStage]) -> None:
        views = stage_views(stages)
        revision.status = derive_status(views)
        current = current_stage(views)
        revision.current_stage = current.stage if current else None
        if revision.status == ContentStatusEnum.READY_TO_PUBLISH and revision.ready_at is None:
            revision.ready_at = datetime.now(timezone.utc)

    @staticmethod
    def _due_at() -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=settings.review_sla_days)

    def _record(
        self,
        revision: CourseRevision,
        actor: User,
        action: str,
        from_status: ContentStatusEnum | None,
        perms: set[PermissionEnum],
        comment: str | None = None,
        **metadata,
    ) -> None:
        self.audit.record(
            actor_id=actor.id,
            action=action,
            entity_type=AuditEntityTypeEnum.COURSE_REVISION,
            entity_id=revision.id,
            course_id=revision.course_id,
            revision_id=revision.id,
            version_label=revision.proposed_version_label,
            from_status=from_status,
            to_status=revision.status,
            comment=comment,
            actor_permissions=perms,
            metadata={k: _jsonable(v) for k, v in metadata.items()} or None,
        )

    def _decision(
        self,
        revision: CourseRevision,
        stage: ReviewStage | None,
        decision: ReviewDecisionEnum,
        actor: User,
        from_status: ContentStatusEnum,
        comment: str | None,
        conditions: list | None = None,
    ) -> None:
        self.session.add(
            ReviewDecision(
                revision_id=revision.id,
                stage_id=stage.id if stage else None,
                stage=stage.stage if stage else None,
                round=revision.round,
                decision=decision,
                actor_id=actor.id,
                comment=comment,
                conditions=conditions or [],
                from_status=from_status,
                to_status=revision.status,
                version_label=revision.proposed_version_label,
                created_by=actor.id,
            )
        )

    async def _commit(self, revision: CourseRevision) -> None:
        revision.lock_version += 1
        await self.session.commit()
        await self.notifier.flush()

    async def _trees(self, revision: CourseRevision, course: Course) -> tuple[dict | None, dict]:
        """(before, after) content trees for diffing this revision."""
        with include_drafts(self.session):
            if revision.kind == RevisionKindEnum.INITIAL:
                version = await self.current_version(course)
                before = version.snapshot if version is not None else None
                after = await build_normalized_tree(self.session, course)
                return before, after
            before = await build_normalized_tree(self.session, course)
            if self.drafts.is_cloned(revision):
                after = await build_normalized_tree(self.session, course, revision.id, revision.course_changes)
            else:
                after = before
            return before, after

    async def compute_changes(self, revision: CourseRevision, course: Course) -> list[Change]:
        before, after = await self._trees(revision, course)
        return diff_trees(before, after)

    async def _assessments_in_scope(self, revision: CourseRevision, course: Course, changes: list[Change]) -> list[CourseAssessment]:
        """Assessments whose design status moves with this revision: all of the
        course's for a new course, otherwise the ones the changes touch."""
        with include_drafts(self.session):
            if revision.kind == RevisionKindEnum.INITIAL:
                stmt = (
                    select(CourseAssessment)
                    .join(CourseItem, CourseItem.id == CourseAssessment.course_item_id)
                    .join(CourseSection, CourseSection.id == CourseItem.section_id)
                    .where(
                        CourseSection.course_id == course.id,
                        CourseSection.revision_id.is_(None),
                        CourseItem.deleted_at.is_(None),
                    )
                )
                return list((await self.session.execute(stmt)).scalars().all())
            if not self.drafts.is_cloned(revision):
                return []
            keys = {uuid.UUID(c.key) for c in changes if c.in_assessment and c.key != "course"}
            if not keys:
                return []
            stmt = (
                select(CourseAssessment)
                .join(CourseItem, CourseItem.id == CourseAssessment.course_item_id)
                .where(
                    CourseItem.revision_id == revision.id,
                    (CourseItem.draft_of_id.in_(keys)) | (CourseItem.id.in_(keys)),
                )
            )
            return list((await self.session.execute(stmt)).scalars().all())

    async def _sync_assessments(self, revision: CourseRevision, course: Course, value: AssessmentDesignStatusEnum) -> None:
        for assessment in await self._assessments_in_scope(revision, course, self._snapshot_changes(revision)):
            assessment.design_status = value

    async def _stage_pool(self, revision: CourseRevision, course: Course, stage: ReviewStage) -> list[uuid.UUID]:
        if stage.assigned_reviewer_id is not None:
            return [stage.assigned_reviewer_id]
        context = await self.decision_context(revision)
        pool: list[uuid.UUID] = []
        for permission in STAGE_PERMISSIONS[stage.stage]:
            pool += await self.permissions.user_ids_with_permission(permission, course)
        excluded = context.contributors | {
            uid for uid, stages in context.approvals_by_user.items() if stages - {stage.stage}
        }
        return [uid for uid in dict.fromkeys(pool) if uid not in excluded]

    async def _queue_next_stage_notification(self, revision: CourseRevision, course: Course, stages: list[ReviewStage]) -> None:
        current = current_stage(stage_views(stages))
        if current is None:
            if revision.status == ContentStatusEnum.READY_TO_PUBLISH:
                publishers = await self.permissions.user_ids_with_permission(PermissionEnum.PUBLISH_CONTENT, course)
                self.notifier.queue(
                    publishers, NotificationTypeEnum.REVISION_READY_TO_PUBLISH,
                    f"Ready to publish: {course.title}",
                    f"All required approvals are in for version {revision.proposed_version_label}.",
                    _link(revision), revision_id=revision.id, course_id=course.id,
                )
            return
        stage_row = next(s for s in stages if s.id == current.id)
        pool = await self._stage_pool(revision, course, stage_row)
        self.notifier.queue(
            pool, NotificationTypeEnum.REVIEW_REQUESTED,
            f"Review requested: {course.title}",
            f"{_stage_label(stage_row.stage)} is waiting for a decision ({revision.effective_risk.value.lower()} risk).",
            _link(revision), revision_id=revision.id, course_id=course.id, stage=stage_row.stage.value,
        )

    async def _create_stages(self, revision: CourseRevision, required: list[ReviewStageEnum]) -> list[ReviewStage]:
        due_at = self._due_at()
        rows = []
        for sequence, stage in enumerate(required, start=1):
            row = ReviewStage(
                revision_id=revision.id,
                round=revision.round,
                stage=stage,
                sequence=sequence,
                status=ReviewStageStatusEnum.PENDING,
                due_at=due_at,
                conditions=[],
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        return rows

    async def _reconcile_stages(
        self,
        revision: CourseRevision,
        stages: list[ReviewStage],
        required: list[ReviewStageEnum],
        actor: User,
        drop_status: ReviewStageStatusEnum,
    ) -> tuple[list[ReviewStage], list[ReviewStageEnum], list[ReviewStageEnum]]:
        """Bring the round's stages in line with `required`: open stages no longer
        required get `drop_status`; missing ones are added (or reopened). Returns
        (stages, added, dropped) re-sequenced in pipeline order."""
        by_stage = {s.stage: s for s in stages}
        added, dropped = [], []
        now = datetime.now(timezone.utc)
        for stage in stages:
            if stage.stage not in required and stage.status in STAGE_OPEN_STATUSES:
                stage.status = drop_status
                stage.decided_by = actor.id
                stage.decided_at = now
                dropped.append(stage.stage)
        for stage_enum in required:
            existing = by_stage.get(stage_enum)
            if existing is None:
                row = ReviewStage(
                    revision_id=revision.id, round=revision.round, stage=stage_enum, sequence=0,
                    status=ReviewStageStatusEnum.PENDING, due_at=self._due_at(), conditions=[],
                )
                self.session.add(row)
                stages.append(row)
                added.append(stage_enum)
            elif existing.status in (ReviewStageStatusEnum.SUPERSEDED, ReviewStageStatusEnum.SKIPPED):
                existing.status = ReviewStageStatusEnum.PENDING
                existing.decided_by = None
                existing.decided_at = None
                existing.due_at = self._due_at()
                added.append(stage_enum)
        stages.sort(key=lambda s: _STAGE_ORDER.index(s.stage))
        for sequence, stage in enumerate(stages, start=1):
            stage.sequence = sequence
        revision.required_stages = [s.stage.value for s in stages if s.status != ReviewStageStatusEnum.SUPERSEDED]
        await self.session.flush()
        return stages, added, dropped

    # -- author actions -----------------------------------------------------------------

    async def open_for_course(self, course_id: uuid.UUID, actor: User) -> CourseRevision:
        course = await self.get_course(course_id)
        await self.permissions.ensure(actor, PermissionEnum.EDIT_DRAFT_CONTENT, course, "You do not manage this course")
        if not settings.content_governance_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "Content governance is not enabled")
        existing = await self.drafts.get_open_revision(course.id)
        if existing is not None:
            return existing
        revision = await self.drafts.open_revision(course, actor)
        await self.drafts.record_contributor(revision, actor)
        await self.session.commit()
        return revision

    async def submit(self, revision_id: uuid.UUID, payload: RevisionSubmitDTO, actor: User) -> CourseRevision:
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.SUBMIT_FOR_REVIEW not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't submit this course for review")
        await self._submit(revision, course, payload, actor, perms)
        await self._commit(revision)
        return revision

    async def _submit(
        self,
        revision: CourseRevision,
        course: Course,
        payload: RevisionSubmitDTO,
        actor: User,
        perms: set[PermissionEnum],
    ) -> None:
        if revision.status not in EDITABLE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, f"This revision is {revision.status.value}, not a draft")
        if revision.kind == RevisionKindEnum.CHANGE and course.governance_status != CourseLifecycleEnum.PUBLISHED:
            raise HTTPException(status.HTTP_409_CONFLICT, "This course is not published")

        changes = await self.compute_changes(revision, course)
        if revision.kind == RevisionKindEnum.CHANGE and not changes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "There are no changes to submit")
        if revision.kind == RevisionKindEnum.INITIAL:
            count_stmt = (
                select(func.count(CourseItem.id))
                .join(CourseSection, CourseItem.section_id == CourseSection.id)
                .where(
                    CourseSection.course_id == course.id,
                    CourseSection.revision_id.is_(None),
                    CourseSection.deleted_at.is_(None),
                    CourseItem.deleted_at.is_(None),
                )
            )
            if (await self.session.execute(count_stmt)).scalar_one() == 0:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Course must have at least one curriculum item before review"
                )

        risk = classify(changes, revision.kind, payload.flags, payload.declared_risk)
        required = resolve_required_stages(risk.effective, risk.touches_assessment, revision.kind)

        from_status = revision.status
        revision.round += 1
        stages = await self._create_stages(revision, required)

        revision.computed_risk = risk.computed
        revision.declared_risk = payload.declared_risk
        revision.effective_risk = risk.effective
        revision.risk_flags = [RiskFlagEnum(f).value for f in payload.flags]
        revision.risk_reasons = risk.reasons
        revision.touches_assessment = risk.touches_assessment
        revision.required_stages = [s.value for s in required]
        revision.change_summary = payload.change_summary
        revision.reason = payload.reason
        revision.submitted_at = datetime.now(timezone.utc)
        revision.ready_at = None
        revision.risk_override_by = None
        revision.risk_override_reason = None
        revision.diff_snapshot = [{**c.to_dict(), "risk": change_risk(c).value} for c in changes]

        version = await self.current_version(course)
        major, minor = next_version(
            version.major if version else None, version.minor if version else None, risk.effective, revision.kind
        )
        revision.proposed_version_label = f"{major}.{minor}"

        self._refresh_status(revision, stages)
        for assessment in await self._assessments_in_scope(revision, course, changes):
            assessment.design_status = assessment_status_for(stage_views(stages))

        self._record(
            revision, actor, "SUBMITTED", from_status, perms, payload.change_summary,
            round=revision.round, risk=risk.effective.value, stages=[s.value for s in required],
            flags=revision.risk_flags, change_count=len(changes),
        )
        await self._queue_next_stage_notification(revision, course, stages)

    async def withdraw(self, revision_id: uuid.UUID, actor: User) -> CourseRevision:
        """Pull a revision back out of review into an editable draft."""
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        if actor.id not in await self.contributor_ids(revision) and PermissionEnum.SUBMIT_FOR_REVIEW not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a contributor can withdraw this revision")
        if revision.status in EDITABLE_STATUSES or revision.status in CLOSED_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "This revision is not in review")

        from_status = revision.status
        for stage in await self.round_stages(revision):
            if stage.status in STAGE_OPEN_STATUSES:
                stage.status = ReviewStageStatusEnum.SUPERSEDED
        revision.status = ContentStatusEnum.DRAFT
        revision.current_stage = None
        revision.ready_at = None
        await self._sync_assessments(revision, course, AssessmentDesignStatusEnum.DRAFT)
        self._record(revision, actor, "WITHDRAWN_FROM_REVIEW", from_status, perms)
        await self._commit(revision)
        return revision

    async def discard(self, revision_id: uuid.UUID, actor: User) -> CourseRevision:
        """Abandon a draft. A published course keeps its live content untouched."""
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.EDIT_DRAFT_CONTENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not manage this course")
        if revision.status not in EDITABLE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a draft can be discarded - withdraw it from review first")

        from_status = revision.status
        revision.status = ContentStatusEnum.WITHDRAWN
        revision.current_stage = None
        revision.closed_at = datetime.now(timezone.utc)
        await self.drafts.discard(revision)
        self._record(revision, actor, "DISCARDED", from_status, perms)
        await self._commit(revision)
        return revision

    # -- reviewer actions -----------------------------------------------------------------

    async def _open_stage(self, revision: CourseRevision) -> tuple[list[ReviewStage], ReviewStage]:
        if revision.status in CLOSED_STATUSES or revision.status in EDITABLE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, "This revision is not in review")
        stages = await self.round_stages(revision)
        current = current_stage(stage_views(stages))
        if current is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Every stage is approved - this revision is awaiting publication")
        return stages, next(s for s in stages if s.id == current.id)

    async def claim(self, revision_id: uuid.UUID, actor: User) -> CourseRevision:
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        stages, stage = await self._open_stage(revision)
        try:
            check_can_claim(actor.id, perms, stage_views([stage])[0], await self.decision_context(revision))
        except GovernanceRuleError as exc:
            raise _rule_error(exc)

        from_status = revision.status
        now = datetime.now(timezone.utc)
        stage.assigned_reviewer_id = actor.id
        stage.assigned_by = actor.id
        stage.assigned_at = now
        stage.status = ReviewStageStatusEnum.IN_REVIEW
        self._refresh_status(revision, stages)
        self._record(revision, actor, "STAGE_CLAIMED", from_status, perms, stage=stage.stage.value)
        await self._commit(revision)
        return revision

    async def assign(self, revision_id: uuid.UUID, payload: AssignReviewerDTO, actor: User) -> CourseRevision:
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        stages, stage = await self._open_stage(revision)
        assignee = await self.session.get(User, payload.reviewer_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Reviewer not found")
        assignee_perms = await self.permissions.permissions(assignee, course)
        try:
            check_can_assign(
                actor.id, perms, stage_views([stage])[0], assignee.id, assignee_perms, await self.decision_context(revision)
            )
        except GovernanceRuleError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST if exc.code != "MISSING_PERMISSION" else 403, exc.message)

        from_status = revision.status
        previous = stage.assigned_reviewer_id
        stage.assigned_reviewer_id = assignee.id
        stage.assigned_by = actor.id
        stage.assigned_at = datetime.now(timezone.utc)
        stage.status = ReviewStageStatusEnum.IN_REVIEW
        if payload.due_at is not None:
            stage.due_at = payload.due_at
        self._refresh_status(revision, stages)
        self._record(
            revision, actor, "REVIEWER_ASSIGNED", from_status, perms,
            stage=stage.stage.value, reviewer_id=assignee.id, previous_reviewer_id=previous, due_at=stage.due_at,
        )
        if assignee.id != actor.id:
            self.notifier.queue(
                [assignee.id], NotificationTypeEnum.REVIEW_ASSIGNED,
                f"You've been assigned a review: {course.title}",
                f"{_stage_label(stage.stage)}" + (f", due {stage.due_at:%d %b %Y}" if stage.due_at else ""),
                _link(revision), revision_id=revision.id, course_id=course.id,
            )
        await self._commit(revision)
        return revision

    async def decide(self, revision_id: uuid.UUID, payload: ReviewDecisionCreateDTO, actor: User) -> CourseRevision:
        decision = payload.decision
        if decision == ReviewDecisionEnum.FORCE_APPROVED:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the force-approve action for that")
        comment = (payload.comment or "").strip() or None
        if decision in (
            ReviewDecisionEnum.RETURNED_FOR_REVISION, ReviewDecisionEnum.REJECTED, ReviewDecisionEnum.ESCALATED
        ) and not comment:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A comment explaining the decision is required")
        if decision == ReviewDecisionEnum.APPROVED_WITH_MINOR_CHANGES and not payload.conditions:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "List the minor changes the next stage must confirm")

        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        stages, stage = await self._open_stage(revision)
        context = await self.decision_context(revision)
        try:
            check_can_decide(actor.id, perms, stage_views([stage])[0], context)
        except GovernanceRuleError as exc:
            raise _rule_error(exc)

        from_status = revision.status
        now = datetime.now(timezone.utc)
        conditions = [
            {"text": c, "stage": stage.stage.value, "by": str(actor.id), "at": now.isoformat()} for c in payload.conditions
        ]

        if decision in (ReviewDecisionEnum.APPROVED, ReviewDecisionEnum.APPROVED_WITH_MINOR_CHANGES):
            stage.status = (
                ReviewStageStatusEnum.APPROVED
                if decision == ReviewDecisionEnum.APPROVED
                else ReviewStageStatusEnum.APPROVED_WITH_CONDITIONS
            )
            stage.decided_by = actor.id
            stage.decided_at = now
            stage.conditions = conditions
            if stage.assigned_reviewer_id is None:
                stage.assigned_reviewer_id = actor.id
            self._refresh_status(revision, stages)
            for assessment in await self._assessments_in_scope(revision, course, self._snapshot_changes(revision)):
                assessment.design_status = assessment_status_for(stage_views(stages))
            self.notifier.queue(
                await self.contributor_ids(revision), NotificationTypeEnum.REVISION_STAGE_APPROVED,
                f"{_stage_label(stage.stage)} approved: {course.title}",
                comment or (f"Approved with {len(conditions)} minor change(s) to confirm." if conditions else None),
                _link(revision), revision_id=revision.id, course_id=course.id,
            )
            await self._queue_next_stage_notification(revision, course, stages)

        elif decision == ReviewDecisionEnum.RETURNED_FOR_REVISION:
            self._close_round(stages, stage, ReviewStageStatusEnum.RETURNED, actor, now)
            revision.status = ContentStatusEnum.RETURNED_FOR_REVISION
            revision.current_stage = None
            revision.ready_at = None
            await self._sync_assessments(revision, course, AssessmentDesignStatusEnum.DRAFT)
            self.notifier.queue(
                await self.contributor_ids(revision), NotificationTypeEnum.REVISION_RETURNED,
                f"Returned for revision: {course.title}", comment, _link(revision),
                revision_id=revision.id, course_id=course.id, stage=stage.stage.value,
            )

        elif decision == ReviewDecisionEnum.REJECTED:
            self._close_round(stages, stage, ReviewStageStatusEnum.REJECTED, actor, now)
            revision.status = ContentStatusEnum.REJECTED
            revision.current_stage = None
            revision.closed_at = now
            if revision.kind == RevisionKindEnum.INITIAL:
                await self._sync_assessments(revision, course, AssessmentDesignStatusEnum.DRAFT)
            await self.drafts.discard(revision)
            self.notifier.queue(
                await self.contributor_ids(revision), NotificationTypeEnum.REVISION_REJECTED,
                f"Rejected: {course.title}", comment, _link(revision), revision_id=revision.id, course_id=course.id,
            )

        else:  # ESCALATED
            new_level = max_risk(revision.effective_risk, payload.escalate_to, RiskLevelEnum.HIGH if payload.flags else None)
            new_flags = sorted(set(revision.risk_flags or []) | {RiskFlagEnum(f).value for f in payload.flags})
            if RISK_ORDER[new_level] <= RISK_ORDER[revision.effective_risk] and new_flags == sorted(revision.risk_flags or []):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escalate to a higher risk level or add a flag")
            revision.effective_risk = new_level
            revision.risk_flags = new_flags
            revision.risk_reasons = [*(revision.risk_reasons or []), f"{new_level.value} · Escalated by reviewer: {comment}"]
            required = resolve_required_stages(new_level, revision.touches_assessment, revision.kind)
            stages, added, _ = await self._reconcile_stages(
                revision, stages, required, actor, ReviewStageStatusEnum.SUPERSEDED
            )
            version = await self.current_version(course)
            major, minor = next_version(version.major if version else None, version.minor if version else None, new_level, revision.kind)
            revision.proposed_version_label = f"{major}.{minor}"
            self._refresh_status(revision, stages)
            self.notifier.queue(
                await self.contributor_ids(revision), NotificationTypeEnum.REVISION_ESCALATED,
                f"Escalated to {new_level.value.lower()} risk: {course.title}",
                f"Added stages: {', '.join(_stage_label(s) for s in added) or 'none'}. {comment}",
                _link(revision), revision_id=revision.id, course_id=course.id,
            )
            await self._queue_next_stage_notification(revision, course, stages)

        self._decision(revision, stage, decision, actor, from_status, comment, conditions)
        self._record(
            revision, actor, f"DECISION_{decision.value}", from_status, perms, comment,
            stage=stage.stage.value, round=revision.round, conditions=payload.conditions,
        )
        await self._commit(revision)
        return revision

    @staticmethod
    def _close_round(
        stages: list[ReviewStage], stage: ReviewStage, outcome: ReviewStageStatusEnum, actor: User, now: datetime
    ) -> None:
        stage.status = outcome
        stage.decided_by = actor.id
        stage.decided_at = now
        for other in stages:
            if other.id != stage.id and other.status in STAGE_OPEN_STATUSES:
                other.status = ReviewStageStatusEnum.SUPERSEDED

    @staticmethod
    def _snapshot_changes(revision: CourseRevision) -> list[Change]:
        return [Change(**{k: v for k, v in c.items() if k != "risk"}) for c in (revision.diff_snapshot or [])]

    async def force_approve(self, revision_id: uuid.UUID, justification: str, actor: User) -> CourseRevision:
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        stages, _ = await self._open_stage(revision)
        try:
            check_can_force_approve(actor.id, perms, await self.decision_context(revision), justification)
        except GovernanceRuleError as exc:
            raise _rule_error(exc)

        from_status = revision.status
        now = datetime.now(timezone.utc)
        skipped = []
        for stage in stages:
            if stage.status in STAGE_OPEN_STATUSES:
                stage.status = ReviewStageStatusEnum.SKIPPED
                stage.decided_by = actor.id
                stage.decided_at = now
                skipped.append(stage.stage.value)
        self._refresh_status(revision, stages)
        for assessment in await self._assessments_in_scope(revision, course, self._snapshot_changes(revision)):
            assessment.design_status = AssessmentDesignStatusEnum.APPROVED
        self._decision(revision, None, ReviewDecisionEnum.FORCE_APPROVED, actor, from_status, justification)
        self._record(revision, actor, "FORCE_APPROVED", from_status, perms, justification, skipped_stages=skipped)
        self.notifier.queue(
            await self.contributor_ids(revision), NotificationTypeEnum.REVISION_FORCE_APPROVED,
            f"Force-approved: {course.title}", justification, _link(revision),
            revision_id=revision.id, course_id=course.id,
        )
        await self._queue_next_stage_notification(revision, course, stages)
        await self._commit(revision)
        return revision

    async def override_risk(self, revision_id: uuid.UUID, payload: RiskOverrideDTO, actor: User) -> CourseRevision:
        """Head of Learning sets the risk level (typically lowering an over-cautious
        computed level). Stages no longer required are marked SKIPPED by them."""
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.get_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.FORCE_APPROVE not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the Head of Learning can override risk")
        if actor.id in await self.contributor_ids(revision):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You contributed to this revision")
        if revision.risk_flags and payload.level != RiskLevelEnum.HIGH:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A flagged revision must stay HIGH risk")
        stages, _ = await self._open_stage(revision)

        from_status = revision.status
        previous = revision.effective_risk
        revision.effective_risk = payload.level
        revision.risk_override_by = actor.id
        revision.risk_override_reason = payload.reason
        required = resolve_required_stages(payload.level, revision.touches_assessment, revision.kind)
        stages, added, dropped = await self._reconcile_stages(
            revision, stages, required, actor, ReviewStageStatusEnum.SKIPPED
        )
        version = await self.current_version(course)
        major, minor = next_version(version.major if version else None, version.minor if version else None, payload.level, revision.kind)
        revision.proposed_version_label = f"{major}.{minor}"
        self._refresh_status(revision, stages)
        self._record(
            revision, actor, "RISK_OVERRIDDEN", from_status, perms, payload.reason,
            from_risk=previous.value if previous else None, to_risk=payload.level.value,
            added_stages=[s.value for s in added], skipped_stages=[s.value for s in dropped],
        )
        await self._queue_next_stage_notification(revision, course, stages)
        await self._commit(revision)
        return revision

    # -- publication ------------------------------------------------------------------------

    async def publish(self, revision_id: uuid.UUID, actor: User) -> CourseRevision:
        revision = await self.get_revision(revision_id, lock=True)
        course = await self.drafts._lock_course(revision.course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.PUBLISH_CONTENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Publishing requires PUBLISH_CONTENT")
        if revision.status != ContentStatusEnum.READY_TO_PUBLISH:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Only a revision that is READY_TO_PUBLISH can be published (this one is {revision.status.value})",
            )
        stages = await self.round_stages(revision)
        active = [s for s in stages if s.status != ReviewStageStatusEnum.SUPERSEDED]
        if not active or any(s.status not in STAGE_DONE_STATUSES for s in active):
            raise HTTPException(status.HTTP_409_CONFLICT, "Required approvals are missing")
        if any(s.status == ReviewStageStatusEnum.SKIPPED for s in active):
            forced = (
                await self.session.execute(
                    select(func.count(ReviewDecision.id)).where(
                        ReviewDecision.revision_id == revision.id,
                        ReviewDecision.round == revision.round,
                        ReviewDecision.decision == ReviewDecisionEnum.FORCE_APPROVED,
                    )
                )
            ).scalar_one()
            if not forced and revision.risk_override_by is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "Skipped stages without a recorded override")
        if course.governance_status == CourseLifecycleEnum.ARCHIVED and revision.kind != RevisionKindEnum.REINSTATE:
            raise HTTPException(status.HTTP_409_CONFLICT, "This course is archived")

        from_status = revision.status
        now = datetime.now(timezone.utc)
        merge = await self.drafts.merge(revision, course, actor)

        version = await self.current_version(course)
        major, minor = next_version(
            version.major if version else None, version.minor if version else None, revision.effective_risk, revision.kind
        )
        with include_drafts(self.session):
            snapshot = await build_normalized_tree(self.session, course)
        reviewer_ids = list(
            dict.fromkeys(
                s.decided_by for s in await self.all_stages(revision)
                if s.decided_by is not None and s.status in STAGE_DONE_STATUSES
            )
        )
        new_version = CourseVersion(
            course_id=course.id,
            major=major,
            minor=minor,
            label=f"{major}.{minor}",
            revision_id=revision.id,
            snapshot=snapshot,
            snapshot_hash=tree_hash(snapshot),
            author_id=revision.author_id,
            reviewer_ids=reviewer_ids,
            approved_at=revision.ready_at or now,
            published_at=now,
            published_by=actor.id,
            reason=revision.reason or revision.change_summary,
            risk_level=revision.effective_risk,
            is_current=True,
            created_by=actor.id,
        )
        if version is not None:
            version.is_current = False
        self.session.add(new_version)
        await self.session.flush()

        course.current_version_id = new_version.id
        course.current_version_label = new_version.label
        course.governance_status = CourseLifecycleEnum.PUBLISHED
        course.is_published = True
        if merge.item_set_changed:
            course.content_updated_at = now
        if revision.kind == RevisionKindEnum.INITIAL:
            for assessment in await self._assessments_in_scope(revision, course, []):
                assessment.design_status = AssessmentDesignStatusEnum.LIVE

        revision.status = ContentStatusEnum.PUBLISHED
        revision.current_stage = None
        revision.published_at = now
        revision.published_by = actor.id
        revision.published_version_id = new_version.id
        revision.proposed_version_label = new_version.label
        revision.closed_at = now
        self._record(
            revision, actor, "PUBLISHED", from_status, perms,
            version=new_version.label, item_set_changed=merge.item_set_changed,
        )
        self.notifier.queue(
            [*await self.contributor_ids(revision), *reviewer_ids], NotificationTypeEnum.REVISION_PUBLISHED,
            f"Published: {course.title} v{new_version.label}", revision.change_summary, _link(revision),
            exclude={actor.id}, revision_id=revision.id, course_id=course.id,
        )
        revision.lock_version += 1
        await self.session.commit()

        await self._after_publish(course, merge)
        await self.notifier.flush()
        return revision

    async def _after_publish(self, course: Course, merge) -> None:
        """Side effects that must not run inside (or roll back) the publish
        transaction: cache, learner progress, live-session invites, room cleanup."""
        await invalidate_course_cache(course)

        if merge.item_set_changed:
            try:
                from app.modules.learning.service import LearningService

                await LearningService(self.session).recalculate_progress_for_enrolled_users(course.id)
                await self.session.commit()
            except Exception as exc:
                logger.exception("Progress recalculation after publishing course %s failed: %s", course.id, exc)
                await self.session.rollback()

        if merge.promoted_live_session_item_ids:
            from app.modules.course.content_repository import CourseContentRepository
            from app.modules.course.live_session_service import LiveSessionService

            repo = CourseContentRepository(self.session)
            live_sessions = LiveSessionService(self.session)
            for item_id in merge.promoted_live_session_item_ids:
                try:
                    item = await repo.get_item(item_id)
                    live_session = await repo.get_live_session_by_item(item_id)
                    if item is None or live_session is None:
                        continue
                    if live_session.scheduled_start_at > datetime.now(timezone.utc):
                        await live_sessions.notify_enrolled_students(course, item, live_session, kind="scheduled")
                        await live_sessions.schedule_reminder(live_session.id, live_session.scheduled_start_at)
                    await self.session.commit()
                except Exception as exc:
                    logger.warning("Live session follow-up for item %s failed: %s", item_id, exc)
                    await self.session.rollback()

        if merge.removed_live_session_room_names:
            from app.core.daily import get_daily_client

            for room_name in merge.removed_live_session_room_names:
                try:
                    await get_daily_client().delete_room(room_name)
                except Exception as exc:
                    logger.warning("Failed to delete Daily room %s: %s", room_name, exc)

    # -- course lifecycle -------------------------------------------------------------------

    async def archive(self, course_id: uuid.UUID, reason: str | None, actor: User) -> Course:
        course = await self.drafts._lock_course(course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.ARCHIVE_CONTENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Archiving requires ARCHIVE_CONTENT")
        if course.governance_status != CourseLifecycleEnum.PUBLISHED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a published course can be archived")

        open_revision = await self.drafts.get_open_revision(course.id)
        if open_revision is not None:
            from_status = open_revision.status
            for stage in await self.round_stages(open_revision):
                if stage.status in STAGE_OPEN_STATUSES:
                    stage.status = ReviewStageStatusEnum.SUPERSEDED
            open_revision.status = ContentStatusEnum.WITHDRAWN
            open_revision.current_stage = None
            open_revision.closed_at = datetime.now(timezone.utc)
            await self.drafts.discard(open_revision)
            self._record(open_revision, actor, "WITHDRAWN_BY_ARCHIVE", from_status, perms, reason)

        course.governance_status = CourseLifecycleEnum.ARCHIVED
        course.is_published = False
        self.audit.record(
            actor_id=actor.id, action="COURSE_ARCHIVED", entity_type=AuditEntityTypeEnum.COURSE,
            entity_id=course.id, course_id=course.id, version_label=course.current_version_label,
            from_status=CourseLifecycleEnum.PUBLISHED, to_status=CourseLifecycleEnum.ARCHIVED,
            comment=reason, actor_permissions=perms,
        )
        await self.session.commit()
        await invalidate_course_cache(course)
        return course

    async def reinstate(self, course_id: uuid.UUID, reason: str | None, actor: User) -> CourseRevision:
        """Bringing an archived course back is a LOW-risk change: it goes through
        the quick-approval path, then a publisher republishes it."""
        course = await self.get_course(course_id)
        perms = await self.permissions.permissions(actor, course)
        if PermissionEnum.ARCHIVE_CONTENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Reinstating requires ARCHIVE_CONTENT")
        if course.governance_status != CourseLifecycleEnum.ARCHIVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only an archived course can be reinstated")
        revision = await self.drafts._open_revision(course, actor, kind=RevisionKindEnum.REINSTATE)
        if revision.kind != RevisionKindEnum.REINSTATE:
            raise HTTPException(status.HTTP_409_CONFLICT, "This course already has a revision in progress")
        await self.drafts.record_contributor(revision, actor)
        await self._submit(
            revision, course, RevisionSubmitDTO(change_summary="Reinstate archived course", reason=reason), actor, perms
        )
        await self._commit(revision)
        return revision

    async def rollback(self, course_id: uuid.UUID, version_id: uuid.UUID, reason: str | None, actor: User) -> CourseRevision:
        course = await self.get_course(course_id)
        perms = await self.permissions.permissions(actor, course)
        if not perms & {PermissionEnum.APPROVE_COURSE, PermissionEnum.FINAL_APPROVAL}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Rollback requires APPROVE_COURSE or FINAL_APPROVAL")
        if not settings.content_governance_enabled:
            raise HTTPException(status.HTTP_409_CONFLICT, "Content governance is not enabled")
        if course.governance_status != CourseLifecycleEnum.PUBLISHED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a published course can be rolled back")
        version = await self.session.get(CourseVersion, version_id)
        if version is None or version.course_id != course.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
        if version.id == course.current_version_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That is already the current version")

        revision = await self.drafts.open_rollback(course, version, actor)
        changes = await self.compute_changes(revision, course)
        if not changes and not revision.course_changes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"The live content already matches version {version.label}")
        await self._submit(
            revision, course,
            RevisionSubmitDTO(change_summary=f"Rollback to version {version.label}", reason=reason),
            actor, perms,
        )
        await self._commit(revision)
        return revision


async def invalidate_course_cache(course: Course) -> None:
    await delete_cache(f"course:slug:{course.slug}")
    await delete_cache("courses:*")
    await delete_cache("course_catalogs:public")
    await delete_cache("home:stats")


def _link(revision: CourseRevision) -> str:
    return f"/dashboard/approval-centre/revisions/{revision.id}"


def _stage_label(stage: ReviewStageEnum) -> str:
    return {
        ReviewStageEnum.QUICK_APPROVAL: "Quick approval",
        ReviewStageEnum.ACADEMIC_REVIEW: "Academic review",
        ReviewStageEnum.ASSESSMENT_MODERATION: "Assessment moderation",
        ReviewStageEnum.QA_REVIEW: "QA review",
        ReviewStageEnum.COURSE_LEAD_APPROVAL: "Course Lead approval",
        ReviewStageEnum.FINAL_APPROVAL: "Final approval",
    }[stage]


def _jsonable(value):
    from app.modules.governance.tree import to_json_value

    return to_json_value(value)
