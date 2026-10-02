import uuid
from datetime import datetime

from pydantic import Field

from app.common.base_dto import AuditDTO, BaseDTO, CreateDTO
from app.modules.governance.enums import (
    ContentStatusEnum,
    CourseLifecycleEnum,
    ReviewDecisionEnum,
    ReviewStageEnum,
    ReviewStageStatusEnum,
    RevisionKindEnum,
    RiskFlagEnum,
    RiskLevelEnum,
)
from app.modules.governance.permissions import PermissionEnum, StaffRoleEnum

# -- staff roles -----------------------------------------------------------------


class StaffRoleGrantDTO(CreateDTO):
    user_id: uuid.UUID
    role: StaffRoleEnum
    course_id: uuid.UUID | None = Field(
        default=None, description="Scope the role to one course; omit for a platform-wide grant"
    )
    reason: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None


class StaffRoleRevokeDTO(BaseDTO):
    reason: str | None = Field(default=None, max_length=500)


class StaffRoleAssignmentReadDTO(AuditDTO):
    user_id: uuid.UUID
    role: StaffRoleEnum
    course_id: uuid.UUID | None = None
    granted_by: uuid.UUID | None = None
    reason: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: uuid.UUID | None = None
    revoke_reason: str | None = None


class EffectiveRoleDTO(BaseDTO):
    role: StaffRoleEnum
    course_id: uuid.UUID | None = None
    implicit: bool
    assignment_id: uuid.UUID | None = None


class CourseAccessDTO(BaseDTO):
    """Roles granted on one specific course (e.g. Course Lead of course X)."""

    course_id: uuid.UUID
    course_title: str | None = None
    roles: list[StaffRoleEnum]
    permissions: list[PermissionEnum]


class UserCapabilitiesDTO(BaseDTO):
    """Navigation-level yes/no flags: true when the user can do this on at least
    one course. Use them to show or hide menus and screens; per-item buttons
    still come from each resource's `available_actions`."""

    can_create_courses: bool = False
    can_edit_content: bool = False
    can_submit_for_review: bool = False
    can_review_content: bool = False
    can_publish: bool = False
    can_archive: bool = False
    can_mark_essays: bool = False
    can_moderate_marks: bool = False
    can_approve_results: bool = False
    can_force_approve: bool = False
    can_manage_staff_roles: bool = False
    can_view_audit_log: bool = False
    can_access_approval_centre: bool = False


class UserAccessDTO(BaseDTO):
    """The user's governance roles and permissions, returned on login and on
    GET/PATCH /users/me."""

    governance_enabled: bool = Field(description="Whether the content approval workflow is switched on")
    roles: list[StaffRoleEnum] = Field(description="Platform-wide roles (explicit grants and implicit ones)")
    permissions: list[PermissionEnum] = Field(description="Platform-wide permission codes")
    owned_course_count: int = Field(description="Courses this user owns (instructors)")
    owned_course_permissions: list[PermissionEnum] = Field(
        description="Permissions the user has on every course they own"
    )
    course_access: list[CourseAccessDTO] = Field(description="Roles granted on specific courses")
    capabilities: UserCapabilitiesDTO


class MyPermissionsDTO(BaseDTO):
    course_id: uuid.UUID | None = None
    governance_enabled: bool
    roles: list[EffectiveRoleDTO]
    permissions: list[PermissionEnum]


# -- audit ---------------------------------------------------------------------------


class AuditLogReadDTO(BaseDTO):
    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID | None = None
    actor_permissions: list[str] = []
    entity_type: str
    entity_id: uuid.UUID
    course_id: uuid.UUID | None = None
    revision_id: uuid.UUID | None = None
    version_label: str | None = None
    action: str
    from_status: str | None = None
    to_status: str | None = None
    comment: str | None = None
    metadata_json: dict | None = None


# -- revisions & review ------------------------------------------------------------


class UserSummaryDTO(BaseDTO):
    id: uuid.UUID
    name: str
    email: str | None = None


class RevisionSubmitDTO(BaseDTO):
    change_summary: str = Field(min_length=5, max_length=5000, description="What changed, for reviewers")
    reason: str | None = Field(default=None, max_length=5000, description="Why the change is needed")
    declared_risk: RiskLevelEnum | None = Field(
        default=None, description="Raise the risk above what the system computed (it can't be lowered here)"
    )
    flags: list[RiskFlagEnum] = Field(
        default_factory=list, description="Safeguarding/legal/policy/certificate flags - any flag means HIGH risk"
    )


class ReviewDecisionCreateDTO(BaseDTO):
    decision: ReviewDecisionEnum = Field(
        description="APPROVED, APPROVED_WITH_MINOR_CHANGES, RETURNED_FOR_REVISION, REJECTED or ESCALATED"
    )
    comment: str | None = Field(default=None, max_length=10000)
    conditions: list[str] = Field(
        default_factory=list, description="With APPROVED_WITH_MINOR_CHANGES: what the next stage must confirm"
    )
    escalate_to: RiskLevelEnum | None = Field(default=None, description="With ESCALATED: the new risk level")
    flags: list[RiskFlagEnum] = Field(default_factory=list, description="With ESCALATED: flags to add")


class AssignReviewerDTO(BaseDTO):
    reviewer_id: uuid.UUID
    due_at: datetime | None = None


class ForceApproveDTO(BaseDTO):
    justification: str = Field(min_length=20, max_length=5000)


class RiskOverrideDTO(BaseDTO):
    level: RiskLevelEnum
    reason: str = Field(min_length=10, max_length=5000)


class ReasonDTO(BaseDTO):
    reason: str | None = Field(default=None, max_length=5000)


class ReviewStageReadDTO(BaseDTO):
    id: uuid.UUID
    round: int
    stage: ReviewStageEnum
    sequence: int
    status: ReviewStageStatusEnum
    assigned_reviewer: UserSummaryDTO | None = None
    due_at: datetime | None = None
    decided_by: UserSummaryDTO | None = None
    decided_at: datetime | None = None
    conditions: list = []
    is_overdue: bool = False


class ReviewDecisionReadDTO(BaseDTO):
    id: uuid.UUID
    created_at: datetime
    stage: ReviewStageEnum | None = None
    round: int
    decision: ReviewDecisionEnum
    actor: UserSummaryDTO | None = None
    comment: str | None = None
    conditions: list = []
    from_status: ContentStatusEnum
    to_status: ContentStatusEnum
    version_label: str | None = None


class RevisionSummaryDTO(BaseDTO):
    id: uuid.UUID
    course_id: uuid.UUID
    course_title: str | None = None
    kind: RevisionKindEnum
    status: ContentStatusEnum
    current_stage: ReviewStageEnum | None = None
    round: int
    author: UserSummaryDTO | None = None
    effective_risk: RiskLevelEnum | None = None
    proposed_version_label: str | None = None
    change_summary: str | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    published_at: datetime | None = None
    is_editable: bool = False


class RevisionDetailDTO(RevisionSummaryDTO):
    computed_risk: RiskLevelEnum | None = None
    declared_risk: RiskLevelEnum | None = None
    risk_flags: list[str] = []
    risk_reasons: list[str] = []
    risk_override_reason: str | None = None
    touches_assessment: bool = False
    required_stages: list[str] = []
    reason: str | None = None
    course_changes: dict = {}
    base_version_id: uuid.UUID | None = None
    published_version_id: uuid.UUID | None = None
    rollback_to_version_id: uuid.UUID | None = None
    ready_at: datetime | None = None
    lock_version: int = 0
    contributors: list[UserSummaryDTO] = []
    stages: list[ReviewStageReadDTO] = []
    decisions: list[ReviewDecisionReadDTO] = []
    # Conditions from "approve with minor changes" still to be confirmed.
    open_conditions: list[dict] = []
    available_actions: list[str] = []
    # Why the caller can't decide the current stage, if they can't (e.g. OWN_WORK).
    blocked_reason: str | None = None


class ChangeDTO(BaseDTO):
    entity: str
    key: str
    op: str
    label: str
    fields: list[str] = []
    before: dict | None = None
    after: dict | None = None
    item_type: str | None = None
    risk: RiskLevelEnum


class RevisionDiffDTO(BaseDTO):
    revision_id: uuid.UUID
    computed_risk: RiskLevelEnum
    touches_assessment: bool
    reasons: list[str]
    changes: list[ChangeDTO]
    is_live_computation: bool = Field(
        description="True when computed from the working copy now; false when read from the submission-time record"
    )


class CourseVersionReadDTO(BaseDTO):
    id: uuid.UUID
    course_id: uuid.UUID
    label: str
    major: int
    minor: int
    revision_id: uuid.UUID | None = None
    author: UserSummaryDTO | None = None
    reviewers: list[UserSummaryDTO] = []
    approved_at: datetime | None = None
    published_at: datetime | None = None
    published_by: UserSummaryDTO | None = None
    reason: str | None = None
    risk_level: RiskLevelEnum | None = None
    is_current: bool = False
    has_snapshot: bool = False


class CourseVersionDetailDTO(CourseVersionReadDTO):
    snapshot: dict | None = None


class CourseGovernanceDTO(BaseDTO):
    """Governance state shown alongside a course in the manage views."""

    governance_enabled: bool
    lifecycle: CourseLifecycleEnum
    current_version_label: str | None = None
    layer: str = Field(description="'live' or 'draft' - which content the accompanying tree shows")
    open_revision: RevisionSummaryDTO | None = None


class ReviewCommentCreateDTO(BaseDTO):
    body: str = Field(min_length=1, max_length=10000)
    parent_id: uuid.UUID | None = None
    anchor_type: str | None = Field(default=None, description="course | section | item | question")
    anchor_id: uuid.UUID | None = None


class ReviewCommentReadDTO(BaseDTO):
    id: uuid.UUID
    created_at: datetime
    revision_id: uuid.UUID
    stage_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    author: UserSummaryDTO | None = None
    body: str
    anchor_type: str | None = None
    anchor_id: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolved_by: uuid.UUID | None = None


class EvidenceUploadRequestDTO(BaseDTO):
    title: str = Field(min_length=1, max_length=255)
    file_name: str = Field(min_length=1, max_length=255)
    content_type: str | None = None


class EvidenceUploadResponseDTO(BaseDTO):
    evidence_id: uuid.UUID
    upload_url: str
    storage_key: str


class EvidenceFinalizeDTO(BaseDTO):
    mime_type: str | None = None
    file_size_bytes: int | None = None


class EvidenceLinkCreateDTO(BaseDTO):
    title: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=2000)


class ReviewEvidenceReadDTO(BaseDTO):
    id: uuid.UUID
    created_at: datetime
    stage_id: uuid.UUID | None = None
    uploaded_by: UserSummaryDTO | None = None
    title: str
    url: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    is_uploaded: bool = False
    download_url: str | None = None


class ApprovalCentreRowDTO(BaseDTO):
    kind: str = Field(description="COURSE_REVISION or ESSAY_MARK")
    id: uuid.UUID
    item_title: str
    item_type: str = Field(description="Course, Lesson, Assessment, Course update, Essay mark")
    course_id: uuid.UUID | None = None
    course_title: str | None = None
    submitted_by: UserSummaryDTO | None = None
    current_stage: str | None = None
    status: str
    reviewer: UserSummaryDTO | None = None
    due_at: datetime | None = None
    is_overdue: bool = False
    risk: RiskLevelEnum | None = None
    version_label: str | None = None
    updated_at: datetime | None = None
    decision: str | None = None
    available_actions: list[str] = []


class ApprovalCentreCountsDTO(BaseDTO):
    awaiting_me: int
    returned_to_me: int
    overdue: int
    ready_to_publish: int
