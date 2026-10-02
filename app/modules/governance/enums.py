import enum


class CourseLifecycleEnum(str, enum.Enum):
    """Where the *live* course stands. Separate from a revision's review status:
    a PUBLISHED course can have an open revision working through review."""

    DRAFT = "DRAFT"  # never published
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"  # withdrawn from learners, kept for history


class RevisionKindEnum(str, enum.Enum):
    INITIAL = "INITIAL"  # a course's first publication
    CHANGE = "CHANGE"  # edits to a published course (draft working copy)
    ROLLBACK = "ROLLBACK"  # restore an earlier version's content
    REINSTATE = "REINSTATE"  # bring an archived course back


class ContentStatusEnum(str, enum.Enum):
    """The framework's content statuses (section 12) plus three the workflow
    needs: ASSESSMENT_MODERATION (the assessment design path's moderator stage),
    REJECTED and WITHDRAWN (terminal states)."""

    DRAFT = "DRAFT"
    SUBMITTED_FOR_REVIEW = "SUBMITTED_FOR_REVIEW"
    ACADEMIC_REVIEW = "ACADEMIC_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    ACADEMICALLY_APPROVED = "ACADEMICALLY_APPROVED"
    ASSESSMENT_MODERATION = "ASSESSMENT_MODERATION"
    QA_REVIEW = "QA_REVIEW"
    QA_APPROVED = "QA_APPROVED"
    COURSE_APPROVED = "COURSE_APPROVED"
    FINAL_APPROVAL_REQUIRED = "FINAL_APPROVAL_REQUIRED"
    READY_TO_PUBLISH = "READY_TO_PUBLISH"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# A revision in one of these is finished - no more edits or decisions.
CLOSED_STATUSES = frozenset(
    {
        ContentStatusEnum.PUBLISHED,
        ContentStatusEnum.ARCHIVED,
        ContentStatusEnum.REJECTED,
        ContentStatusEnum.WITHDRAWN,
    }
)
# Only these let contributors edit the draft; anything else is frozen for review.
EDITABLE_STATUSES = frozenset({ContentStatusEnum.DRAFT, ContentStatusEnum.RETURNED_FOR_REVISION})


class ReviewStageEnum(str, enum.Enum):
    # LOW-risk changes only: one approver holding QA_REVIEW *or* APPROVE_COURSE.
    QUICK_APPROVAL = "QUICK_APPROVAL"
    ACADEMIC_REVIEW = "ACADEMIC_REVIEW"
    ASSESSMENT_MODERATION = "ASSESSMENT_MODERATION"
    QA_REVIEW = "QA_REVIEW"
    COURSE_LEAD_APPROVAL = "COURSE_LEAD_APPROVAL"
    FINAL_APPROVAL = "FINAL_APPROVAL"


class ReviewStageStatusEnum(str, enum.Enum):
    PENDING = "PENDING"  # queued, nobody has picked it up
    IN_REVIEW = "IN_REVIEW"  # claimed by / assigned to a reviewer
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    RETURNED = "RETURNED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"  # force-approved past by the Head of Learning
    SUPERSEDED = "SUPERSEDED"  # its round ended in a return; a new round replaced it


STAGE_DONE_STATUSES = frozenset(
    {
        ReviewStageStatusEnum.APPROVED,
        ReviewStageStatusEnum.APPROVED_WITH_CONDITIONS,
        ReviewStageStatusEnum.SKIPPED,
    }
)
STAGE_OPEN_STATUSES = frozenset({ReviewStageStatusEnum.PENDING, ReviewStageStatusEnum.IN_REVIEW})


class ReviewDecisionEnum(str, enum.Enum):
    """Framework section 12's review decisions, plus FORCE_APPROVED."""

    APPROVED = "APPROVED"
    APPROVED_WITH_MINOR_CHANGES = "APPROVED_WITH_MINOR_CHANGES"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    FORCE_APPROVED = "FORCE_APPROVED"


class RiskLevelEnum(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


RISK_ORDER = {RiskLevelEnum.LOW: 0, RiskLevelEnum.MEDIUM: 1, RiskLevelEnum.HIGH: 2}


def max_risk(*levels: "RiskLevelEnum | None") -> RiskLevelEnum:
    present = [lvl for lvl in levels if lvl is not None]
    if not present:
        return RiskLevelEnum.LOW
    return max(present, key=lambda lvl: RISK_ORDER[lvl])


class RiskFlagEnum(str, enum.Enum):
    """Declared by the submitter (or added by an escalating reviewer). Any flag
    forces the HIGH-risk path - framework section 4 lists safeguarding/legal
    content and certificate rules as high risk."""

    SAFEGUARDING = "SAFEGUARDING"
    LEGAL = "LEGAL"
    POLICY = "POLICY"
    CERTIFICATE_RULE = "CERTIFICATE_RULE"
    CPD_RECOGNITION = "CPD_RECOGNITION"


class AssessmentDesignStatusEnum(str, enum.Enum):
    """Framework section 12's assessment statuses."""

    DRAFT = "DRAFT"
    ACADEMIC_REVIEW = "ACADEMIC_REVIEW"
    MODERATION = "MODERATION"
    QA_REVIEW = "QA_REVIEW"
    APPROVED = "APPROVED"
    LIVE = "LIVE"
    WITHDRAWN = "WITHDRAWN"
