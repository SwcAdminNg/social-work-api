import uuid

import pytest

from app.modules.governance.enums import (
    AssessmentDesignStatusEnum,
    ContentStatusEnum,
    ReviewStageEnum,
    ReviewStageStatusEnum,
)
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.workflow import (
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
    insert_stages,
)

St = ReviewStageEnum
SS = ReviewStageStatusEnum
P = PermissionEnum

AUTHOR = uuid.uuid4()
EDITOR = uuid.uuid4()
REVIEWER = uuid.uuid4()
OTHER = uuid.uuid4()


def stages(*pairs):
    return [StageView(stage, status, i + 1, id=uuid.uuid4()) for i, (stage, status) in enumerate(pairs)]


def ctx(**approvals):
    return DecisionContext(contributors={AUTHOR, EDITOR}, approvals_by_user=approvals.get("approvals", {}))


# -- status derivation -----------------------------------------------------------------


def test_freshly_submitted_is_submitted_for_review():
    s = stages((St.ACADEMIC_REVIEW, SS.PENDING), (St.QA_REVIEW, SS.PENDING), (St.COURSE_LEAD_APPROVAL, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.SUBMITTED_FOR_REVIEW
    assert current_stage(s).stage == St.ACADEMIC_REVIEW


def test_claimed_academic_stage_is_academic_review():
    s = stages((St.ACADEMIC_REVIEW, SS.IN_REVIEW), (St.QA_REVIEW, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.ACADEMIC_REVIEW


def test_milestones_follow_framework_labels():
    s = stages((St.ACADEMIC_REVIEW, SS.APPROVED), (St.QA_REVIEW, SS.PENDING), (St.COURSE_LEAD_APPROVAL, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.ACADEMICALLY_APPROVED
    s = stages((St.ACADEMIC_REVIEW, SS.APPROVED), (St.QA_REVIEW, SS.IN_REVIEW), (St.COURSE_LEAD_APPROVAL, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.QA_REVIEW
    s = stages((St.ACADEMIC_REVIEW, SS.APPROVED), (St.QA_REVIEW, SS.APPROVED), (St.COURSE_LEAD_APPROVAL, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.QA_APPROVED


def test_final_approval_required_then_ready():
    s = stages(
        (St.ACADEMIC_REVIEW, SS.APPROVED), (St.QA_REVIEW, SS.APPROVED),
        (St.COURSE_LEAD_APPROVAL, SS.APPROVED), (St.FINAL_APPROVAL, SS.PENDING),
    )
    assert derive_status(s) == ContentStatusEnum.FINAL_APPROVAL_REQUIRED
    s[-1].status = SS.APPROVED
    assert derive_status(s) == ContentStatusEnum.READY_TO_PUBLISH
    assert current_stage(s) is None


def test_quick_approval_goes_straight_to_ready():
    s = stages((St.QUICK_APPROVAL, SS.PENDING))
    assert derive_status(s) == ContentStatusEnum.SUBMITTED_FOR_REVIEW
    s[0].status = SS.APPROVED_WITH_CONDITIONS
    assert derive_status(s) == ContentStatusEnum.READY_TO_PUBLISH


def test_superseded_stages_are_ignored():
    s = stages((St.QUICK_APPROVAL, SS.SUPERSEDED), (St.ACADEMIC_REVIEW, SS.PENDING), (St.QA_REVIEW, SS.PENDING))
    assert current_stage(s).stage == St.ACADEMIC_REVIEW
    assert derive_status(s) == ContentStatusEnum.SUBMITTED_FOR_REVIEW


def test_skipped_stages_count_as_done():
    s = stages((St.ACADEMIC_REVIEW, SS.APPROVED), (St.QA_REVIEW, SS.SKIPPED), (St.COURSE_LEAD_APPROVAL, SS.SKIPPED))
    assert derive_status(s) == ContentStatusEnum.READY_TO_PUBLISH


def test_returned_round_has_no_current_stage():
    s = stages((St.ACADEMIC_REVIEW, SS.RETURNED), (St.QA_REVIEW, SS.SUPERSEDED))
    assert current_stage(s) is None
    with pytest.raises(GovernanceRuleError):
        derive_status(s)


def test_assessment_status_tracks_stage():
    s = stages((St.ACADEMIC_REVIEW, SS.APPROVED), (St.ASSESSMENT_MODERATION, SS.PENDING), (St.QA_REVIEW, SS.PENDING))
    assert assessment_status_for(s) == AssessmentDesignStatusEnum.MODERATION
    for stage in s:
        stage.status = SS.APPROVED
    assert assessment_status_for(s) == AssessmentDesignStatusEnum.APPROVED


# -- separation of duties ------------------------------------------------------------------


def test_reviewer_with_permission_can_decide():
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())


def test_missing_permission_is_rejected():
    stage = stages((St.QA_REVIEW, SS.PENDING))[0]
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())
    assert exc.value.code == "MISSING_PERMISSION"


@pytest.mark.parametrize("actor", [AUTHOR, EDITOR])
def test_contributors_cannot_approve_their_own_work(actor):
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_decide(actor, {P.ACADEMIC_REVIEW, P.FINAL_APPROVAL}, stage, ctx())
    assert exc.value.code == "OWN_WORK"


def test_one_person_cannot_sign_off_two_stages():
    stage = stages((St.QA_REVIEW, SS.PENDING))[0]
    context = ctx(approvals={REVIEWER: {St.ACADEMIC_REVIEW}})
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW, P.QA_REVIEW}, stage, context)
    assert exc.value.code == "SECOND_SIGNOFF"


def test_same_stage_in_a_later_round_is_allowed():
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    context = ctx(approvals={REVIEWER: {St.ACADEMIC_REVIEW}})
    check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, context)


def test_assigned_stage_only_for_assignee():
    stage = stages((St.ACADEMIC_REVIEW, SS.IN_REVIEW))[0]
    stage.assigned_reviewer_id = OTHER
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())
    assert exc.value.code == "ASSIGNED_TO_OTHER"
    check_can_decide(OTHER, {P.ACADEMIC_REVIEW}, stage, ctx())


def test_quick_approval_accepts_qa_or_course_lead():
    stage = stages((St.QUICK_APPROVAL, SS.PENDING))[0]
    check_can_decide(REVIEWER, {P.QA_REVIEW}, stage, ctx())
    check_can_decide(REVIEWER, {P.APPROVE_COURSE}, stage, ctx())
    with pytest.raises(GovernanceRuleError):
        check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())


def test_claim_rules_match_decide_rules():
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    check_can_claim(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())
    with pytest.raises(GovernanceRuleError):
        check_can_claim(AUTHOR, {P.ACADEMIC_REVIEW}, stage, ctx())


def test_only_leads_assign_others():
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    with pytest.raises(GovernanceRuleError):
        check_can_assign(REVIEWER, {P.ACADEMIC_REVIEW}, stage, OTHER, {P.ACADEMIC_REVIEW}, ctx())
    check_can_assign(REVIEWER, {P.APPROVE_COURSE}, stage, OTHER, {P.ACADEMIC_REVIEW}, ctx())


def test_cannot_assign_a_contributor():
    stage = stages((St.ACADEMIC_REVIEW, SS.PENDING))[0]
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_assign(REVIEWER, {P.APPROVE_COURSE}, stage, AUTHOR, {P.ACADEMIC_REVIEW}, ctx())
    assert exc.value.code == "OWN_WORK"


def test_force_approve_needs_permission_justification_and_independence():
    with pytest.raises(GovernanceRuleError):
        check_can_force_approve(REVIEWER, {P.FINAL_APPROVAL}, ctx(), "x" * 30)
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_force_approve(REVIEWER, {P.FORCE_APPROVE}, ctx(), "too short")
    assert exc.value.code == "JUSTIFICATION_REQUIRED"
    with pytest.raises(GovernanceRuleError):
        check_can_force_approve(AUTHOR, {P.FORCE_APPROVE}, ctx(), "x" * 30)
    check_can_force_approve(REVIEWER, {P.FORCE_APPROVE}, ctx(), "Urgent safeguarding correction approved by board")


def test_decisions_require_open_stage():
    stage = stages((St.ACADEMIC_REVIEW, SS.APPROVED))[0]
    with pytest.raises(GovernanceRuleError) as exc:
        check_can_decide(REVIEWER, {P.ACADEMIC_REVIEW}, stage, ctx())
    assert exc.value.code == "STAGE_NOT_OPEN"


def test_insert_stages_returns_missing_in_pipeline_order():
    added = insert_stages(
        [St.ACADEMIC_REVIEW, St.QA_REVIEW, St.COURSE_LEAD_APPROVAL],
        [St.ACADEMIC_REVIEW, St.ASSESSMENT_MODERATION, St.QA_REVIEW, St.COURSE_LEAD_APPROVAL, St.FINAL_APPROVAL],
    )
    assert added == [St.ASSESSMENT_MODERATION, St.FINAL_APPROVAL]
