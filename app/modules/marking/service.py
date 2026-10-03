"""Learner marking hierarchy (framework 5.2): Marker -> Moderator -> Lead
Assessor / Course Lead, with every mark kept as history.

Essays marked "requires moderation" (and only while content governance is on)
take the full path; others keep the original single-step grading, now also
recorded in essay_marks so every grade has a history either way.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.course.content_entity import CourseAssessment, CourseEssaySettings
from app.modules.course.entity import Course, CourseItem, CourseSection
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.dto import ApprovalCentreRowDTO
from app.modules.governance.notifier import GovernanceNotifier
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.presenter import UserDirectory
from app.modules.learning.entity import EssaySubmission
from app.modules.marking.dto import (
    ApproveMarkDTO,
    EssayMarkReadDTO,
    ModerateMarkDTO,
    ModerationActionEnum,
    PublishMarksResultDTO,
)
from app.modules.marking.entity import (
    IN_PROGRESS_STATUSES,
    EssayMark,
    LearnerResultStatusEnum,
)
from app.modules.notification.entity import NotificationTypeEnum
from app.modules.user.activity_entity import ActivityTypeEnum
from app.modules.user.activity_service import ActivityService
from app.modules.user.entity import User

S = LearnerResultStatusEnum
MARKING_PERMISSIONS = frozenset(
    {PermissionEnum.MARK_ASSESSMENT, PermissionEnum.MODERATE_ASSESSMENT, PermissionEnum.APPROVE_RESULTS}
)


def moderation_required(essay_settings: CourseEssaySettings | None) -> bool:
    return bool(settings.content_governance_enabled and essay_settings and essay_settings.requires_moderation)


class MarkingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.permissions = PermissionService(session)
        self.audit = AuditService(session)
        self.notifier = GovernanceNotifier(session)

    # -- loading -----------------------------------------------------------------------

    async def _context(self, mark: EssayMark):
        course = await self.session.get(Course, mark.course_id)
        item = await self.session.get(CourseItem, mark.item_id)
        submission = await self.session.get(EssaySubmission, mark.submission_id)
        return course, item, submission

    async def get_mark(self, mark_id: uuid.UUID, lock: bool = False) -> EssayMark:
        stmt = select(EssayMark).where(EssayMark.id == mark_id, EssayMark.deleted_at.is_(None))
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        mark = (await self.session.execute(stmt)).scalar_one_or_none()
        if mark is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Mark not found")
        return mark

    async def active_mark(self, submission: EssaySubmission) -> EssayMark | None:
        stmt = (
            select(EssayMark)
            .where(
                EssayMark.submission_id == submission.id,
                EssayMark.status.in_(IN_PROGRESS_STATUSES),
                EssayMark.deleted_at.is_(None),
            )
            .order_by(EssayMark.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _perms(self, actor: User, course: Course) -> set[PermissionEnum]:
        return await self.permissions.permissions(actor, course)

    def _audit(self, mark: EssayMark, actor: User, action: str, from_status, perms, comment=None, **metadata) -> None:
        self.audit.record(
            actor_id=actor.id,
            action=action,
            entity_type=AuditEntityTypeEnum.ESSAY_MARK,
            entity_id=mark.id,
            course_id=mark.course_id,
            from_status=from_status,
            to_status=mark.status,
            comment=comment,
            actor_permissions=perms,
            metadata={
                "learner_id": str(mark.learner_id),
                "item_id": str(mark.item_id),
                "attempt_no": mark.attempt_no,
                **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in metadata.items()},
            },
        )

    async def _pool(self, permission: PermissionEnum, course: Course, exclude: set) -> list[uuid.UUID]:
        return [u for u in await self.permissions.user_ids_with_permission(permission, course) if u not in exclude]

    async def _commit(self) -> None:
        await self.session.commit()
        await self.notifier.flush()

    # -- marker ------------------------------------------------------------------------

    async def grade(
        self,
        course: Course,
        section: CourseSection,
        item: CourseItem,
        assessment: CourseAssessment,
        learner_id: uuid.UUID,
        score: float,
        feedback: str | None,
        is_published: bool,
        recommendation,
        submit_for_moderation: bool,
        actor: User,
    ) -> EssayMark:
        perms = await self._perms(actor, course)
        if PermissionEnum.MARK_ASSESSMENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't mark this course's assessments")
        submission = (
            await self.session.execute(
                select(EssaySubmission).where(
                    EssaySubmission.user_id == learner_id,
                    EssaySubmission.item_id == item.id,
                    EssaySubmission.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if submission is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This student has not submitted this essay")
        essay_settings = (
            await self.session.execute(
                select(CourseEssaySettings).where(CourseEssaySettings.assessment_id == assessment.id)
            )
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if not moderation_required(essay_settings):
            return await self._grade_directly(
                course, section, item, assessment, essay_settings, submission, score, feedback, is_published,
                recommendation, actor, perms, now,
            )

        active = await self.active_mark(submission)
        if active is not None and active.status not in (S.DRAFT_MARK, S.RETURNED_TO_MARKER):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"This attempt is already in moderation ({active.status.value})"
            )
        if active is not None and active.marker_id != actor.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Another marker is marking this attempt")

        from_status = active.status if active else None
        if active is None:
            active = EssayMark(
                submission_id=submission.id, item_id=item.id, course_id=course.id, learner_id=learner_id,
                attempt_no=submission.graded_attempts + 1, status=S.DRAFT_MARK, marker_id=actor.id,
                score=score, feedback=feedback, recommendation=recommendation, created_by=actor.id,
            )
            self.session.add(active)
        else:
            active.score = score
            active.feedback = feedback
            active.recommendation = recommendation
            active.status = S.DRAFT_MARK
        await self.session.flush()
        self._audit(active, actor, "MARK_SAVED", from_status, perms, score=score)
        if submit_for_moderation:
            await self._send_to_moderation(active, course, item, actor, perms, now)
        submission.result_status = active.status
        await self._commit()
        return active

    async def _grade_directly(
        self, course, section, item, assessment, essay_settings, submission, score, feedback, is_published,
        recommendation, actor, perms, now,
    ) -> EssayMark:
        """No moderation: the original single-step grade, plus a history row."""
        from app.modules.learning.repository import LearningRepository

        await self._supersede_previous(submission)
        submission = await LearningRepository(self.session).grade_essay_submission(
            submission, score=score, feedback=feedback, is_published=is_published, graded_by=actor.id
        )
        mark = EssayMark(
            submission_id=submission.id, item_id=item.id, course_id=course.id, learner_id=submission.user_id,
            attempt_no=submission.graded_attempts, status=S.PUBLISHED if is_published else S.APPROVED,
            marker_id=actor.id, score=score, feedback=feedback, recommendation=recommendation,
            final_score=score, final_feedback=feedback, approved_by=actor.id, approved_at=now,
            published_by=actor.id if is_published else None, published_at=now if is_published else None,
            created_by=actor.id,
        )
        self.session.add(mark)
        await self.session.flush()
        submission.result_status = mark.status
        self._audit(mark, actor, "GRADED_WITHOUT_MODERATION", None, perms, score=score, published=is_published)
        await self._apply_final_outcome(course, section, item, assessment, essay_settings, submission, score)
        await self._commit()
        return mark

    async def submit(self, mark_id: uuid.UUID, actor: User) -> EssayMark:
        mark = await self.get_mark(mark_id, lock=True)
        course, item, submission = await self._context(mark)
        perms = await self._perms(actor, course)
        if mark.marker_id != actor.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the marker can submit this mark")
        if mark.status not in (S.DRAFT_MARK, S.RETURNED_TO_MARKER):
            raise HTTPException(status.HTTP_409_CONFLICT, f"This mark is {mark.status.value}")
        await self._send_to_moderation(mark, course, item, actor, perms, datetime.now(timezone.utc))
        submission.result_status = mark.status
        await self._commit()
        return mark

    async def _send_to_moderation(self, mark, course, item, actor, perms, now) -> None:
        from_status = mark.status
        mark.status = S.AWAITING_MODERATION
        mark.submitted_for_moderation_at = now
        self._audit(mark, actor, "SENT_TO_MODERATION", from_status, perms)
        self.notifier.queue(
            await self._pool(PermissionEnum.MODERATE_ASSESSMENT, course, {mark.marker_id}),
            NotificationTypeEnum.MARKS_AWAITING_MODERATION,
            f"Mark awaiting moderation: {item.title}", course.title, _link(mark), mark_id=mark.id,
        )

    async def dispute(self, mark_id: uuid.UUID, note: str, actor: User) -> EssayMark:
        mark = await self.get_mark(mark_id, lock=True)
        course, item, _ = await self._context(mark)
        perms = await self._perms(actor, course)
        if mark.marker_id != actor.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the original marker can dispute a moderation")
        if mark.status != S.MODERATED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a moderated mark can be disputed")
        mark.disputed = True
        mark.dispute_note = note
        self._audit(mark, actor, "MODERATION_DISPUTED", S.MODERATED, perms, note)
        self.notifier.queue(
            await self._pool(PermissionEnum.APPROVE_RESULTS, course, {mark.marker_id, mark.moderator_id}),
            NotificationTypeEnum.MARKS_DISPUTED, f"Disputed mark: {item.title}", note, _link(mark), mark_id=mark.id,
        )
        await self._commit()
        return mark

    # -- moderator -----------------------------------------------------------------------

    async def moderate(self, mark_id: uuid.UUID, payload: ModerateMarkDTO, actor: User) -> EssayMark:
        mark = await self.get_mark(mark_id, lock=True)
        course, item, submission = await self._context(mark)
        perms = await self._perms(actor, course)
        if PermissionEnum.MODERATE_ASSESSMENT not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Moderation requires MODERATE_ASSESSMENT")
        if actor.id == mark.marker_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You marked this attempt, so you can't moderate it")
        if mark.status != S.AWAITING_MODERATION:
            raise HTTPException(status.HTTP_409_CONFLICT, f"This mark is {mark.status.value}, not awaiting moderation")
        if payload.action in (ModerationActionEnum.RETURN, ModerationActionEnum.AMEND) and not payload.note:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Explain the return or amendment in a note")
        if payload.action == ModerationActionEnum.AMEND and payload.score is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An amendment needs the moderated score")

        now = datetime.now(timezone.utc)
        from_status = mark.status
        mark.moderator_id = actor.id
        mark.moderated_at = now
        mark.moderation_note = payload.note
        if payload.action == ModerationActionEnum.RETURN:
            mark.status = S.RETURNED_TO_MARKER
            mark.returned_at = now
            self.notifier.queue(
                [mark.marker_id], NotificationTypeEnum.MARKS_RETURNED,
                f"Mark returned for re-marking: {item.title}", payload.note, _link(mark), mark_id=mark.id,
            )
        else:
            mark.status = S.MODERATED
            if payload.action == ModerationActionEnum.APPROVE:
                mark.moderated_score = mark.score
                mark.moderated_feedback = mark.feedback
            else:
                mark.moderated_score = payload.score
                mark.moderated_feedback = payload.feedback if payload.feedback is not None else mark.feedback
            self.notifier.queue(
                await self._pool(PermissionEnum.APPROVE_RESULTS, course, {mark.marker_id, actor.id}),
                NotificationTypeEnum.MARKS_AWAITING_APPROVAL,
                f"Moderated mark awaiting approval: {item.title}", course.title, _link(mark), mark_id=mark.id,
            )
            if payload.action == ModerationActionEnum.AMEND:
                self.notifier.queue(
                    [mark.marker_id], NotificationTypeEnum.MARKS_RETURNED,
                    f"Your mark was amended in moderation: {item.title}", payload.note, _link(mark), mark_id=mark.id,
                )
        submission.result_status = mark.status
        self._audit(
            mark, actor, f"MODERATION_{payload.action.value}", from_status, perms, payload.note,
            marker_score=float(mark.score), moderated_score=payload.score,
        )
        await self._commit()
        return mark

    # -- approver / publisher --------------------------------------------------------------

    async def approve(self, mark_id: uuid.UUID, payload: ApproveMarkDTO, actor: User) -> EssayMark:
        mark = await self.get_mark(mark_id, lock=True)
        course, item, submission = await self._context(mark)
        perms = await self._perms(actor, course)
        if PermissionEnum.APPROVE_RESULTS not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Approving results requires APPROVE_RESULTS")
        if actor.id in (mark.marker_id, mark.moderator_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You marked or moderated this attempt, so you can't approve it")
        if mark.status != S.MODERATED:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Only a moderated mark can be approved (this is {mark.status.value})")
        if mark.disputed and payload.final_score is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This mark is disputed - set final_score to settle it")

        now = datetime.now(timezone.utc)
        from_status = mark.status
        mark.status = S.APPROVED
        mark.approved_by = actor.id
        mark.approved_at = now
        mark.final_score = payload.final_score if payload.final_score is not None else mark.moderated_score
        mark.final_feedback = payload.final_feedback if payload.final_feedback is not None else mark.moderated_feedback
        mark.approval_note = payload.note
        submission.result_status = mark.status
        self._audit(mark, actor, "RESULT_APPROVED", from_status, perms, payload.note, final_score=float(mark.final_score))
        if payload.publish:
            await self._publish(mark, course, item, submission, actor, perms)
        await self._commit()
        return mark

    async def publish_for_item(
        self, course: Course, item: CourseItem, mark_ids: list[uuid.UUID], all_approved: bool, actor: User
    ) -> PublishMarksResultDTO:
        perms = await self._perms(actor, course)
        if PermissionEnum.APPROVE_RESULTS not in perms:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Publishing results requires APPROVE_RESULTS")
        stmt = select(EssayMark).where(
            EssayMark.item_id == item.id, EssayMark.status == S.APPROVED, EssayMark.deleted_at.is_(None)
        )
        if not all_approved:
            if not mark_ids:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass mark_ids or all_approved=true")
            stmt = stmt.where(EssayMark.id.in_(mark_ids))
        marks = list((await self.session.execute(stmt.with_for_update())).scalars().all())
        published_ids = set()
        for mark in marks:
            submission = await self.session.get(EssaySubmission, mark.submission_id)
            if submission is None or submission.deleted_at is not None:
                continue
            await self._publish(mark, course, item, submission, actor, perms)
            published_ids.add(mark.id)
        await self._commit()
        skipped = [m for m in mark_ids if m not in published_ids] if not all_approved else []
        return PublishMarksResultDTO(published=len(published_ids), skipped=skipped)

    async def _publish(self, mark, course, item, submission, actor, perms) -> None:
        """Release an approved result: only now does the learner see it, and only
        now can it unlock (or, out of retries, reset) a module."""
        from app.modules.learning.repository import LearningRepository

        await self._supersede_previous(submission, keep=mark.id)
        await LearningRepository(self.session).grade_essay_submission(
            submission, score=float(mark.final_score), feedback=mark.final_feedback, is_published=True,
            graded_by=mark.marker_id,
        )
        now = datetime.now(timezone.utc)
        from_status = mark.status
        mark.status = S.PUBLISHED
        mark.published_by = actor.id
        mark.published_at = now
        submission.result_status = S.PUBLISHED
        self._audit(mark, actor, "RESULT_PUBLISHED", from_status, perms, final_score=float(mark.final_score))

        section = await self.session.get(CourseSection, item.section_id)
        assessment = (
            await self.session.execute(select(CourseAssessment).where(CourseAssessment.course_item_id == item.id))
        ).scalar_one_or_none()
        essay_settings = (
            await self.session.execute(
                select(CourseEssaySettings).where(CourseEssaySettings.assessment_id == assessment.id)
            )
        ).scalar_one_or_none() if assessment else None
        await self._apply_final_outcome(
            course, section, item, assessment, essay_settings, submission, float(mark.final_score)
        )
        await ActivityService(self.session).log_activity(
            submission.user_id,
            ActivityTypeEnum.ESSAY_GRADED,
            {"course_id": str(course.id), "course_title": course.title, "item_id": str(item.id),
             "item_title": item.title, "score": float(mark.final_score)},
        )

    async def _supersede_previous(self, submission: EssaySubmission, keep: uuid.UUID | None = None) -> None:
        stmt = select(EssayMark).where(
            EssayMark.submission_id == submission.id,
            EssayMark.status.in_([S.PUBLISHED, S.APPROVED]),
            EssayMark.deleted_at.is_(None),
        )
        for previous in (await self.session.execute(stmt)).scalars().all():
            if previous.id != keep:
                previous.status = S.SUPERSEDED

    async def _apply_final_outcome(self, course, section, item, assessment, essay_settings, submission, score) -> None:
        """Same module/course reset mechanics as before, triggered by publication."""
        from app.modules.learning.service import LearningService

        if assessment is None or not assessment.is_final_assessment:
            # A regular essay was already marked complete on submission, but its
            # released grade may be what settles the course result - re-run
            # progress so a certificate held back pending this grade gets issued.
            if submission.is_published:
                await LearningService(self.session)._recalculate_progress(
                    submission.user_id, course.id, touch_last_accessed=False
                )
            return
        pass_mark = essay_settings.pass_mark_percentage if essay_settings else 70
        max_attempts = essay_settings.max_attempts if essay_settings else None
        passed = score >= pass_mark
        attempts_remaining = None if max_attempts is None else max(max_attempts - submission.graded_attempts, 0)
        await LearningService(self.session)._handle_final_assessment_outcome(
            submission.user_id, course.id, section.id, item.id, passed, attempts_remaining
        )

    # -- reads ------------------------------------------------------------------------------

    async def history(self, item: CourseItem, learner_id: uuid.UUID, actor: User, course: Course) -> list[EssayMarkReadDTO]:
        perms = await self._perms(actor, course)
        stmt = (
            select(EssayMark)
            .where(EssayMark.item_id == item.id, EssayMark.learner_id == learner_id, EssayMark.deleted_at.is_(None))
            .order_by(EssayMark.created_at.desc())
        )
        return await self.to_dtos(list((await self.session.execute(stmt)).scalars().all()), actor, perms)

    async def list_for_item(
        self, item: CourseItem, statuses: list[LearnerResultStatusEnum] | None, actor: User, course: Course
    ) -> list[EssayMarkReadDTO]:
        perms = await self._perms(actor, course)
        stmt = select(EssayMark).where(EssayMark.item_id == item.id, EssayMark.deleted_at.is_(None))
        if statuses:
            stmt = stmt.where(EssayMark.status.in_(statuses))
        stmt = stmt.order_by(EssayMark.created_at.desc())
        return await self.to_dtos(list((await self.session.execute(stmt)).scalars().all()), actor, perms)

    async def get_dto(self, mark: EssayMark, actor: User) -> EssayMarkReadDTO:
        course = await self.session.get(Course, mark.course_id)
        perms = await self._perms(actor, course)
        if not perms & MARKING_PERMISSIONS:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't view this course's marks")
        return (await self.to_dtos([mark], actor, perms))[0]

    async def to_dtos(self, marks: list[EssayMark], actor: User, perms: set[PermissionEnum]) -> list[EssayMarkReadDTO]:
        users = UserDirectory(self.session)
        ids = []
        for m in marks:
            ids += [m.learner_id, m.marker_id, m.moderator_id, m.approved_by]
        await users.load(ids)
        return [
            EssayMarkReadDTO(
                id=m.id, created_at=m.created_at, submission_id=m.submission_id, item_id=m.item_id,
                course_id=m.course_id, learner=users.get(m.learner_id), attempt_no=m.attempt_no, status=m.status,
                marker=users.get(m.marker_id), score=float(m.score), feedback=m.feedback,
                recommendation=m.recommendation, submitted_for_moderation_at=m.submitted_for_moderation_at,
                moderator=users.get(m.moderator_id),
                moderated_score=float(m.moderated_score) if m.moderated_score is not None else None,
                moderated_feedback=m.moderated_feedback, moderation_note=m.moderation_note,
                moderated_at=m.moderated_at, disputed=m.disputed, dispute_note=m.dispute_note,
                approved_by=users.get(m.approved_by), approved_at=m.approved_at,
                final_score=float(m.final_score) if m.final_score is not None else None,
                final_feedback=m.final_feedback, approval_note=m.approval_note, published_at=m.published_at,
                available_actions=mark_actions(m, actor, perms),
            )
            for m in marks
        ]

    # -- Approval Centre rows -------------------------------------------------------------

    async def approval_rows(self, view: str, actor: User, course_id: uuid.UUID | None) -> list[ApprovalCentreRowDTO]:
        now = datetime.now(timezone.utc)
        sla = timedelta(days=settings.review_sla_days)
        if view == "awaiting_me" or view == "overdue":
            statuses = [S.AWAITING_MODERATION, S.MODERATED]
        elif view == "returned_to_me":
            statuses = [S.RETURNED_TO_MARKER]
        elif view == "ready_to_publish":
            statuses = [S.APPROVED]
        elif view == "my_drafts":
            statuses = [S.DRAFT_MARK]
        elif view == "recently_approved":
            statuses = [S.APPROVED, S.PUBLISHED]
        elif view == "recently_rejected":
            statuses = None  # returned-to-marker events, by returned_at
        else:
            return []

        stmt = select(EssayMark).where(EssayMark.deleted_at.is_(None))
        if statuses is not None:
            stmt = stmt.where(EssayMark.status.in_(statuses))
        if view in ("recently_approved", "recently_rejected"):
            since = now - timedelta(days=30)
            column = EssayMark.approved_at if view == "recently_approved" else EssayMark.returned_at
            stmt = stmt.where(
                column >= since,
                or_(EssayMark.marker_id == actor.id, EssayMark.moderator_id == actor.id, EssayMark.approved_by == actor.id),
            )
        if view in ("returned_to_me", "my_drafts"):
            stmt = stmt.where(EssayMark.marker_id == actor.id)
        if course_id is not None:
            stmt = stmt.where(EssayMark.course_id == course_id)
        marks = list((await self.session.execute(stmt)).scalars().all())
        if not marks:
            return []

        courses = {c.id: c for c in (await self.session.execute(select(Course).where(Course.id.in_({m.course_id for m in marks})))).scalars().all()}
        items = {i.id: i for i in (await self.session.execute(select(CourseItem).where(CourseItem.id.in_({m.item_id for m in marks})))).scalars().all()}
        users = UserDirectory(self.session)
        await users.load([m.learner_id for m in marks] + [m.marker_id for m in marks] + [m.moderator_id for m in marks])
        perm_cache: dict[uuid.UUID, set] = {}

        rows = []
        for m in marks:
            course = courses.get(m.course_id)
            if course is None:
                continue
            if m.course_id not in perm_cache:
                perm_cache[m.course_id] = await self._perms(actor, course)
            perms = perm_cache[m.course_id]
            actions = mark_actions(m, actor, perms)
            due_from = m.submitted_for_moderation_at if m.status == S.AWAITING_MODERATION else m.moderated_at
            due_at = due_from + sla if due_from and m.status in (S.AWAITING_MODERATION, S.MODERATED) else None
            overdue = bool(due_at and due_at < now)

            if view == "awaiting_me" and not ({"MODERATE", "APPROVE"} & set(actions)):
                continue
            if view == "overdue" and not (overdue and ({"MODERATE", "APPROVE"} & set(actions))):
                continue
            if view == "ready_to_publish" and "PUBLISH" not in actions:
                continue

            item = items.get(m.item_id)
            learner = users.get(m.learner_id)
            stage = {
                S.AWAITING_MODERATION: "MODERATION",
                S.MODERATED: "RESULT_APPROVAL",
                S.RETURNED_TO_MARKER: "MARKING",
                S.DRAFT_MARK: "MARKING",
                S.APPROVED: "PUBLICATION",
            }.get(m.status)
            rows.append(
                ApprovalCentreRowDTO(
                    kind="ESSAY_MARK",
                    id=m.id,
                    item_title=f"{item.title if item else 'Essay'} - {learner.name if learner else 'learner'} (attempt {m.attempt_no})",
                    item_type="Essay mark" + (" (disputed)" if m.disputed else ""),
                    course_id=course.id,
                    course_title=course.title,
                    submitted_by=users.get(m.marker_id),
                    current_stage=stage,
                    status=m.status.value,
                    reviewer=users.get(m.moderator_id),
                    due_at=due_at,
                    is_overdue=overdue,
                    updated_at=m.updated_at or m.created_at,
                    available_actions=actions,
                )
            )
        return rows


def mark_actions(mark: EssayMark, actor: User, perms: set[PermissionEnum]) -> list[str]:
    """Actions `actor` may take on `mark` - separation of duties included."""
    actions = []
    is_marker = mark.marker_id == actor.id
    if mark.status in (S.DRAFT_MARK, S.RETURNED_TO_MARKER) and is_marker:
        actions += ["EDIT", "SUBMIT_FOR_MODERATION"]
    if mark.status == S.AWAITING_MODERATION and PermissionEnum.MODERATE_ASSESSMENT in perms and not is_marker:
        actions.append("MODERATE")
    if mark.status == S.MODERATED:
        if is_marker and not mark.disputed:
            actions.append("DISPUTE")
        if PermissionEnum.APPROVE_RESULTS in perms and actor.id not in (mark.marker_id, mark.moderator_id):
            actions.append("APPROVE")
    if mark.status == S.APPROVED and PermissionEnum.APPROVE_RESULTS in perms:
        actions.append("PUBLISH")
    return actions


def _link(mark: EssayMark) -> str:
    return f"/dashboard/approval-centre/marks/{mark.id}"
