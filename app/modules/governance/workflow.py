"""The review state machine and separation-of-duties rules. Pure functions on
plain dataclasses - no ORM, no DB - so every rule is unit-testable on its own.
RevisionService (revision_service.py) is the only caller that persists results.
"""

import uuid
from dataclasses import dataclass, field

from app.modules.governance.enums import (
    STAGE_DONE_STATUSES,
    STAGE_OPEN_STATUSES,
    AssessmentDesignStatusEnum,
    ContentStatusEnum,
    ReviewStageEnum,
    ReviewStageStatusEnum,
)
from app.modules.governance.permissions import PermissionEnum

# Which permission(s) let someone decide each stage. QUICK_APPROVAL is the
# framework's low-risk path: "QA or Course Lead".
STAGE_PERMISSIONS: dict[ReviewStageEnum, frozenset[PermissionEnum]] = {
    ReviewStageEnum.QUICK_APPROVAL: frozenset({PermissionEnum.QA_REVIEW, PermissionEnum.APPROVE_COURSE}),
    ReviewStageEnum.ACADEMIC_REVIEW: frozenset({PermissionEnum.ACADEMIC_REVIEW}),
    ReviewStageEnum.ASSESSMENT_MODERATION: frozenset({PermissionEnum.MODERATE_ASSESSMENT}),
    ReviewStageEnum.QA_REVIEW: frozenset({PermissionEnum.QA_REVIEW}),
    ReviewStageEnum.COURSE_LEAD_APPROVAL: frozenset({PermissionEnum.APPROVE_COURSE}),
    ReviewStageEnum.FINAL_APPROVAL: frozenset({PermissionEnum.FINAL_APPROVAL}),
}

# Permissions senior enough to (re)assign a stage that is assigned to someone else.
ASSIGNING_PERMISSIONS = frozenset({PermissionEnum.APPROVE_COURSE, PermissionEnum.FINAL_APPROVAL})

# Revision status while a stage is being actively reviewed (claimed/assigned).
_IN_REVIEW_STATUS: dict[ReviewStageEnum, ContentStatusEnum] = {
    ReviewStageEnum.ACADEMIC_REVIEW: ContentStatusEnum.ACADEMIC_REVIEW,
    ReviewStageEnum.ASSESSMENT_MODERATION: ContentStatusEnum.ASSESSMENT_MODERATION,
    ReviewStageEnum.QA_REVIEW: ContentStatusEnum.QA_REVIEW,
}
# Milestone reached once each stage approves.
_APPROVED_MILESTONE: dict[ReviewStageEnum, ContentStatusEnum] = {
    ReviewStageEnum.QUICK_APPROVAL: ContentStatusEnum.READY_TO_PUBLISH,
    ReviewStageEnum.ACADEMIC_REVIEW: ContentStatusEnum.ACADEMICALLY_APPROVED,
    ReviewStageEnum.ASSESSMENT_MODERATION: ContentStatusEnum.ACADEMICALLY_APPROVED,
    ReviewStageEnum.QA_REVIEW: ContentStatusEnum.QA_APPROVED,
    ReviewStageEnum.COURSE_LEAD_APPROVAL: ContentStatusEnum.COURSE_APPROVED,
    ReviewStageEnum.FINAL_APPROVAL: ContentStatusEnum.READY_TO_PUBLISH,
}
# Assessment design status (framework 12) while each stage is current.
_ASSESSMENT_STATUS: dict[ReviewStageEnum, AssessmentDesignStatusEnum] = {
    ReviewStageEnum.QUICK_APPROVAL: AssessmentDesignStatusEnum.QA_REVIEW,
    ReviewStageEnum.ACADEMIC_REVIEW: AssessmentDesignStatusEnum.ACADEMIC_REVIEW,
    ReviewStageEnum.ASSESSMENT_MODERATION: AssessmentDesignStatusEnum.MODERATION,
    ReviewStageEnum.QA_REVIEW: AssessmentDesignStatusEnum.QA_REVIEW,
    ReviewStageEnum.COURSE_LEAD_APPROVAL: AssessmentDesignStatusEnum.QA_REVIEW,
    ReviewStageEnum.FINAL_APPROVAL: AssessmentDesignStatusEnum.APPROVED,
}


class GovernanceRuleError(Exception):
    """A workflow or separation-of-duties rule was violated. `code` is stable
    for clients; the message is human-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StageView:
    stage: ReviewStageEnum
    status: ReviewStageStatusEnum
    sequence: int
    assigned_reviewer_id: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None
    id: uuid.UUID | None = None


@dataclass
class DecisionContext:
    """Everything the separation-of-duties guard needs about a revision."""

    contributors: set[uuid.UUID]  # author + every editor of the working copy
    # user id -> stages they approved on this revision, across all rounds
    approvals_by_user: dict[uuid.UUID, set[ReviewStageEnum]] = field(default_factory=dict)


def current_stage(stages: list[StageView]) -> StageView | None:
    """First stage (by sequence) still awaiting a decision, or None when every
    stage is done. SUPERSEDED stages (replaced when a reviewer escalated a
    quick approval into the full path) are ignored."""
    for stage in sorted(stages, key=lambda s: s.sequence):
        if stage.status == ReviewStageStatusEnum.SUPERSEDED:
            continue
        if stage.status in STAGE_OPEN_STATUSES:
            return stage
        if stage.status not in STAGE_DONE_STATUSES:
            return None  # returned/rejected/superseded - the round is over
    return None


def _active(stages: list[StageView]) -> list[StageView]:
    return [s for s in stages if s.status != ReviewStageStatusEnum.SUPERSEDED]


def all_done(stages: list[StageView]) -> bool:
    active = _active(stages)
    return bool(active) and all(s.status in STAGE_DONE_STATUSES for s in active)


def derive_status(stages: list[StageView]) -> ContentStatusEnum:
    """Revision status for a round in progress, using the framework's labels:
    the in-review label while a reviewer holds the stage, otherwise the last
    milestone reached (or SUBMITTED_FOR_REVIEW before any approval)."""
    if all_done(stages):
        return ContentStatusEnum.READY_TO_PUBLISH
    ordered = sorted(_active(stages), key=lambda s: s.sequence)
    current = current_stage(ordered)
    if current is None:
        raise GovernanceRuleError("ROUND_CLOSED", "This review round has no open stage")

    if current.stage == ReviewStageEnum.FINAL_APPROVAL:
        return ContentStatusEnum.FINAL_APPROVAL_REQUIRED
    if current.status == ReviewStageStatusEnum.IN_REVIEW and current.stage in _IN_REVIEW_STATUS:
        return _IN_REVIEW_STATUS[current.stage]

    approved_before = [s for s in ordered if s.sequence < current.sequence and s.status in STAGE_DONE_STATUSES]
    if not approved_before:
        return ContentStatusEnum.SUBMITTED_FOR_REVIEW
    return _APPROVED_MILESTONE[approved_before[-1].stage]


def assessment_status_for(stages: list[StageView]) -> AssessmentDesignStatusEnum:
    if all_done(stages):
        return AssessmentDesignStatusEnum.APPROVED
    current = current_stage(stages)
    if current is None:
        return AssessmentDesignStatusEnum.DRAFT
    return _ASSESSMENT_STATUS[current.stage]


def check_can_decide(
    actor_id: uuid.UUID,
    actor_permissions: set[PermissionEnum],
    stage: StageView,
    context: DecisionContext,
) -> None:
    """Raises GovernanceRuleError unless `actor_id` may decide `stage`.

    1. Holds the stage's permission for this course.
    2. Is not a contributor (author or editor) to the revision.
    3. Has not approved a *different* stage of this revision (in any round) -
       one person can't supply two independent sign-offs.
    4. If the stage is assigned, is the assignee.
    """
    if stage.status not in STAGE_OPEN_STATUSES:
        raise GovernanceRuleError("STAGE_NOT_OPEN", "This stage is not awaiting a decision")
    if not (STAGE_PERMISSIONS[stage.stage] & actor_permissions):
        raise GovernanceRuleError(
            "MISSING_PERMISSION",
            f"Deciding {stage.stage.value} requires "
            + " or ".join(p.value for p in sorted(STAGE_PERMISSIONS[stage.stage], key=lambda p: p.value)),
        )
    if actor_id in context.contributors:
        raise GovernanceRuleError(
            "OWN_WORK", "You contributed to this revision, so you can't approve any stage of it"
        )
    other_stages = context.approvals_by_user.get(actor_id, set()) - {stage.stage}
    if other_stages:
        raise GovernanceRuleError(
            "SECOND_SIGNOFF",
            "You already approved another stage of this revision ("
            + ", ".join(sorted(s.value for s in other_stages))
            + "); an independent reviewer must decide this one",
        )
    if stage.assigned_reviewer_id is not None and stage.assigned_reviewer_id != actor_id:
        raise GovernanceRuleError("ASSIGNED_TO_OTHER", "This stage is assigned to another reviewer")


def check_can_claim(
    actor_id: uuid.UUID,
    actor_permissions: set[PermissionEnum],
    stage: StageView,
    context: DecisionContext,
) -> None:
    """Claiming = taking an unassigned stage into review. Same rules as deciding,
    so nobody can claim work they would not be allowed to approve."""
    if stage.assigned_reviewer_id is not None and stage.assigned_reviewer_id != actor_id:
        raise GovernanceRuleError("ASSIGNED_TO_OTHER", "This stage is already assigned to another reviewer")
    check_can_decide(actor_id, actor_permissions, stage, context)


def check_can_assign(
    actor_id: uuid.UUID,
    actor_permissions: set[PermissionEnum],
    stage: StageView,
    assignee_id: uuid.UUID,
    assignee_permissions: set[PermissionEnum],
    context: DecisionContext,
) -> None:
    """Course Leads and the Head of Learning may assign any open stage; an
    eligible reviewer may assign an unassigned stage to themselves (= claim).
    The assignee must be able to decide the stage."""
    if stage.status not in STAGE_OPEN_STATUSES:
        raise GovernanceRuleError("STAGE_NOT_OPEN", "This stage is not awaiting a decision")
    senior = bool(actor_permissions & ASSIGNING_PERMISSIONS)
    if not senior and assignee_id != actor_id:
        raise GovernanceRuleError(
            "MISSING_PERMISSION", "Only a Course Lead or the Head of Learning can assign reviewers"
        )
    unassigned = StageView(stage.stage, stage.status, stage.sequence, None, None, stage.id)
    check_can_decide(assignee_id, assignee_permissions, unassigned, context)


def check_can_force_approve(
    actor_id: uuid.UUID, actor_permissions: set[PermissionEnum], context: DecisionContext, justification: str | None
) -> None:
    if PermissionEnum.FORCE_APPROVE not in actor_permissions:
        raise GovernanceRuleError("MISSING_PERMISSION", "Force approval requires FORCE_APPROVE (Head of Learning)")
    if actor_id in context.contributors:
        raise GovernanceRuleError("OWN_WORK", "You contributed to this revision, so you can't force-approve it")
    if not justification or len(justification.strip()) < 20:
        raise GovernanceRuleError(
            "JUSTIFICATION_REQUIRED", "Force approval needs a written justification of at least 20 characters"
        )


def insert_stages(
    existing: list[ReviewStageEnum], required: list[ReviewStageEnum]
) -> list[ReviewStageEnum]:
    """Stages from `required` that `existing` lacks, used when a reviewer
    escalates mid-review. Returned in canonical pipeline order."""
    order = list(ReviewStageEnum)
    return sorted((s for s in required if s not in existing), key=order.index)
