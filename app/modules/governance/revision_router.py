import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course.content_dto import CourseSectionManageReadDTO, CourseSectionReadDTO
from app.modules.course.content_service import CourseContentService
from app.modules.governance.approval_centre import ApprovalCentreService, ApprovalKindEnum, ApprovalViewEnum
from app.modules.governance.dependencies import require_permission
from app.modules.governance.diff import Change
from app.modules.governance.discussion_service import DiscussionService
from app.modules.governance.dto import (
    ApprovalCentreCountsDTO,
    ApprovalCentreRowDTO,
    AssignReviewerDTO,
    ChangeDTO,
    CourseGovernanceDTO,
    CourseVersionDetailDTO,
    CourseVersionReadDTO,
    EvidenceFinalizeDTO,
    EvidenceLinkCreateDTO,
    EvidenceUploadRequestDTO,
    EvidenceUploadResponseDTO,
    ForceApproveDTO,
    ReasonDTO,
    ReviewCommentCreateDTO,
    ReviewCommentReadDTO,
    ReviewDecisionCreateDTO,
    ReviewEvidenceReadDTO,
    RevisionDetailDTO,
    RevisionDiffDTO,
    RevisionSubmitDTO,
    RevisionSummaryDTO,
    RiskOverrideDTO,
)
from app.modules.governance.entity import CourseRevision
from app.modules.governance.enums import EDITABLE_STATUSES
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.presenter import detail_dto, summaries, version_dtos
from app.modules.governance.revision_service import RevisionService
from app.modules.governance.risk import change_risk, classify
from app.modules.governance.version_service import VersionService
from app.modules.user.entity import User

router = APIRouter(prefix="/governance", tags=["Governance - Reviews"], route_class=NoNullAPIRoute)
course_router = APIRouter(prefix="/courses", tags=["Governance - Course Versions"], route_class=NoNullAPIRoute)

_require_staff = require_permission(
    PermissionEnum.EDIT_DRAFT_CONTENT,
    PermissionEnum.SUBMIT_FOR_REVIEW,
    PermissionEnum.ACADEMIC_REVIEW,
    PermissionEnum.QA_REVIEW,
    PermissionEnum.MODERATE_ASSESSMENT,
    PermissionEnum.APPROVE_COURSE,
    PermissionEnum.FINAL_APPROVAL,
    PermissionEnum.PUBLISH_CONTENT,
    PermissionEnum.MARK_ASSESSMENT,
    PermissionEnum.APPROVE_RESULTS,
)


async def _detail(db: AsyncSession, revision: CourseRevision, user: User) -> RevisionDetailDTO:
    service = RevisionService(db)
    course = await service.get_course(revision.course_id)
    return await detail_dto(service, revision, course, user)


# ---------------------------------------------------------------------------
# Approval Centre
# ---------------------------------------------------------------------------


@router.get(
    "/approval-centre",
    response_model=PaginatedResponse[ApprovalCentreRowDTO],
    summary="Approval Centre inbox: awaiting_me, returned_to_me, overdue, ready_to_publish, "
    "recently_approved, recently_rejected or my_drafts - course revisions and essay marks together",
)
async def list_approval_centre(
    view: ApprovalViewEnum = Query(ApprovalViewEnum.AWAITING_ME),
    kind: ApprovalKindEnum | None = Query(None, description="Only course revisions or only essay marks"),
    course_id: uuid.UUID | None = Query(None),
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(_require_staff),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ApprovalCentreRowDTO]:
    rows, total = await ApprovalCentreService(db).list(view, current_user, pagination, kind, course_id)
    return PaginatedResponse.create(items=rows, total_items=total, params=pagination)


@router.get(
    "/approval-centre/counts",
    response_model=ApiResponse[ApprovalCentreCountsDTO],
    summary="Badge counts for the Approval Centre tabs",
)
async def approval_centre_counts(
    current_user: User = Depends(_require_staff), db: AsyncSession = Depends(get_db)
) -> ApiResponse[ApprovalCentreCountsDTO]:
    return ApiResponse(message="Counts retrieved successfully", data=await ApprovalCentreService(db).counts(current_user))


# ---------------------------------------------------------------------------
# Revisions - read
# ---------------------------------------------------------------------------


@router.get(
    "/revisions/{revision_id}",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="A revision with its stages, decision history, contributors, open conditions and the "
    "actions the caller may take",
)
async def get_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    service = RevisionService(db)
    revision = await service.get_revision(revision_id)
    course = await service.get_course(revision.course_id)
    await service.ensure_can_view(current_user, course)
    return ApiResponse(message="Revision retrieved successfully", data=await detail_dto(service, revision, course, current_user))


@router.get(
    "/revisions/{revision_id}/tree",
    response_model=ApiResponse[list[CourseSectionManageReadDTO]],
    summary="The revision's working copy in the manage (editor) format",
)
async def get_revision_tree(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[CourseSectionManageReadDTO]]:
    service = RevisionService(db)
    revision = await service.get_revision(revision_id)
    course = await service.get_course(revision.course_id)
    await service.ensure_can_view(current_user, course)
    layer = revision.id if service.drafts.is_cloned(revision) else None
    tree = await CourseContentService(db).build_tree(course.id, manage=True, revision_id=layer)
    return ApiResponse(message="Revision content retrieved successfully", data=tree)


@router.get(
    "/revisions/{revision_id}/preview",
    response_model=ApiResponse[list[CourseSectionReadDTO]],
    summary="The revision's working copy exactly as an enrolled learner would see it once published",
)
async def preview_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[CourseSectionReadDTO]]:
    service = RevisionService(db)
    revision = await service.get_revision(revision_id)
    course = await service.get_course(revision.course_id)
    await service.ensure_can_view(current_user, course)
    layer = revision.id if service.drafts.is_cloned(revision) else None
    tree = await CourseContentService(db).build_tree(course.id, manage=False, enrolled=True, revision_id=layer)
    return ApiResponse(message="Revision preview retrieved successfully", data=tree)


@router.get(
    "/revisions/{revision_id}/diff",
    response_model=ApiResponse[RevisionDiffDTO],
    summary="What the revision changes versus the live course, each change tagged with its risk",
)
async def get_revision_diff(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDiffDTO]:
    service = RevisionService(db)
    revision = await service.get_revision(revision_id)
    course = await service.get_course(revision.course_id)
    await service.ensure_can_view(current_user, course)

    live = revision.status in EDITABLE_STATUSES or revision.diff_snapshot is None
    if live:
        changes = await service.compute_changes(revision, course)
    else:
        changes = [Change(**{k: v for k, v in c.items() if k != "risk"}) for c in revision.diff_snapshot]
    risk = classify(changes, revision.kind)
    data = RevisionDiffDTO(
        revision_id=revision.id,
        computed_risk=risk.computed,
        touches_assessment=risk.touches_assessment,
        reasons=risk.reasons,
        changes=[ChangeDTO(**c.to_dict(), risk=change_risk(c)) for c in changes],
        is_live_computation=live,
    )
    return ApiResponse(message="Revision diff retrieved successfully", data=data)


# ---------------------------------------------------------------------------
# Revisions - author actions
# ---------------------------------------------------------------------------


@router.post(
    "/revisions/{revision_id}/submit",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Submit the working copy for review. Risk is computed from the changes (the submitter can "
    "raise it or add safeguarding/legal/certificate flags) and routes it to the required stages.",
)
async def submit_revision(
    revision_id: uuid.UUID,
    payload: RevisionSubmitDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).submit(revision_id, payload, current_user)
    return ApiResponse(message="Submitted for review", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/withdraw",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Pull a revision out of review back into an editable draft",
)
async def withdraw_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).withdraw(revision_id, current_user)
    return ApiResponse(message="Withdrawn from review", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/discard",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Abandon a draft working copy; the live course is untouched",
)
async def discard_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).discard(revision_id, current_user)
    return ApiResponse(message="Draft discarded", data=await _detail(db, revision, current_user))


# ---------------------------------------------------------------------------
# Revisions - reviewer actions
# ---------------------------------------------------------------------------


@router.post(
    "/revisions/{revision_id}/claim",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Take the current stage into review yourself",
)
async def claim_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).claim(revision_id, current_user)
    return ApiResponse(message="Stage claimed", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/assign",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Assign the current stage to a reviewer (Course Lead / Head of Learning), optionally with a due date",
)
async def assign_reviewer(
    revision_id: uuid.UUID,
    payload: AssignReviewerDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).assign(revision_id, payload, current_user)
    return ApiResponse(message="Reviewer assigned", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/decision",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Decide the current stage: approve, approve with minor changes, return for revision, "
    "reject, or escalate. Separation of duties is enforced.",
)
async def decide_revision(
    revision_id: uuid.UUID,
    payload: ReviewDecisionCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).decide(revision_id, payload, current_user)
    return ApiResponse(message="Decision recorded", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/force-approve",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Head of Learning: skip every remaining stage with a written justification (audited)",
)
async def force_approve_revision(
    revision_id: uuid.UUID,
    payload: ForceApproveDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).force_approve(revision_id, payload.justification, current_user)
    return ApiResponse(message="Force-approved", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/risk",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Head of Learning: set the risk level (re-routes the remaining stages; audited)",
)
async def override_revision_risk(
    revision_id: uuid.UUID,
    payload: RiskOverrideDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).override_risk(revision_id, payload, current_user)
    return ApiResponse(message="Risk updated", data=await _detail(db, revision, current_user))


@router.post(
    "/revisions/{revision_id}/publish",
    response_model=ApiResponse[RevisionDetailDTO],
    summary="Publish a READY_TO_PUBLISH revision (PUBLISH_CONTENT). Merges the working copy into the "
    "live course in place and records the new version.",
)
async def publish_revision(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).publish(revision_id, current_user)
    return ApiResponse(message=f"Published version {revision.proposed_version_label}", data=await _detail(db, revision, current_user))


# ---------------------------------------------------------------------------
# Comments & evidence
# ---------------------------------------------------------------------------


@router.get(
    "/revisions/{revision_id}/comments",
    response_model=ApiResponse[list[ReviewCommentReadDTO]],
    summary="Review discussion for a revision",
)
async def list_comments(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[ReviewCommentReadDTO]]:
    return ApiResponse(message="Comments retrieved successfully", data=await DiscussionService(db).list_comments(revision_id, current_user))


@router.post(
    "/revisions/{revision_id}/comments",
    response_model=ApiResponse[ReviewCommentReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Comment on a revision, optionally replying to a comment or anchoring it to a section/item/question",
)
async def add_comment(
    revision_id: uuid.UUID,
    payload: ReviewCommentCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewCommentReadDTO]:
    data = await DiscussionService(db).add_comment(revision_id, payload, current_user)
    return ApiResponse(message="Comment added", data=data)


@router.patch(
    "/comments/{comment_id}/resolve",
    response_model=ApiResponse[ReviewCommentReadDTO],
    summary="Mark a review comment as resolved",
)
async def resolve_comment(
    comment_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[ReviewCommentReadDTO]:
    return ApiResponse(message="Comment resolved", data=await DiscussionService(db).resolve_comment(comment_id, current_user))


@router.get(
    "/revisions/{revision_id}/evidence",
    response_model=ApiResponse[list[ReviewEvidenceReadDTO]],
    summary="Evidence attached to a revision",
)
async def list_evidence(
    revision_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[ReviewEvidenceReadDTO]]:
    return ApiResponse(message="Evidence retrieved successfully", data=await DiscussionService(db).list_evidence(revision_id, current_user))


@router.post(
    "/revisions/{revision_id}/evidence/upload-url",
    response_model=ApiResponse[EvidenceUploadResponseDTO],
    summary="Get a pre-signed URL to upload an evidence file, then call finalize",
)
async def request_evidence_upload(
    revision_id: uuid.UUID,
    payload: EvidenceUploadRequestDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EvidenceUploadResponseDTO]:
    data = await DiscussionService(db).request_upload(revision_id, payload, current_user)
    return ApiResponse(message="Upload URL generated", data=data)


@router.post(
    "/evidence/{evidence_id}/finalize",
    response_model=ApiResponse[ReviewEvidenceReadDTO],
    summary="Confirm an evidence file finished uploading",
)
async def finalize_evidence(
    evidence_id: uuid.UUID,
    payload: EvidenceFinalizeDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewEvidenceReadDTO]:
    return ApiResponse(message="Evidence saved", data=await DiscussionService(db).finalize_upload(evidence_id, payload, current_user))


@router.post(
    "/revisions/{revision_id}/evidence/link",
    response_model=ApiResponse[ReviewEvidenceReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Attach a link as evidence",
)
async def add_evidence_link(
    revision_id: uuid.UUID,
    payload: EvidenceLinkCreateDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ReviewEvidenceReadDTO]:
    return ApiResponse(message="Evidence saved", data=await DiscussionService(db).add_link(revision_id, payload, current_user))


# ---------------------------------------------------------------------------
# Per-course: working copy, versions, lifecycle
# ---------------------------------------------------------------------------


@course_router.get(
    "/{course_id}/governance",
    response_model=ApiResponse[CourseGovernanceDTO],
    summary="Governance state of a course: lifecycle, current version, open revision",
)
async def get_course_governance(
    course_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[CourseGovernanceDTO]:
    service = RevisionService(db)
    course = await service.get_course(course_id)
    await service.ensure_can_view(current_user, course)
    revision = await service.drafts.get_open_revision(course.id)
    open_dto = (await summaries(db, [revision], {course.id: course}))[0] if revision else None
    data = CourseGovernanceDTO(
        governance_enabled=settings.content_governance_enabled,
        lifecycle=course.governance_status,
        current_version_label=course.current_version_label,
        layer="draft" if service.drafts.is_cloned(revision) else "live",
        open_revision=open_dto,
    )
    return ApiResponse(message="Governance state retrieved successfully", data=data)


@course_router.post(
    "/{course_id}/revisions",
    response_model=ApiResponse[RevisionDetailDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Start (or return) the course's working copy. Editing a published course does this implicitly.",
)
async def open_revision(
    course_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).open_for_course(course_id, current_user)
    return ApiResponse(message="Working copy ready", data=await _detail(db, revision, current_user))


@course_router.get(
    "/{course_id}/revisions",
    response_model=ApiResponse[list[RevisionSummaryDTO]],
    summary="Every revision of a course, newest first (open, published, rejected, withdrawn)",
)
async def list_course_revisions(
    course_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[RevisionSummaryDTO]]:
    service = RevisionService(db)
    course = await service.get_course(course_id)
    await service.ensure_can_view(current_user, course)
    rows = (
        await db.execute(
            select(CourseRevision)
            .where(CourseRevision.course_id == course.id, CourseRevision.deleted_at.is_(None))
            .order_by(CourseRevision.created_at.desc())
        )
    ).scalars().all()
    return ApiResponse(message="Revisions retrieved successfully", data=await summaries(db, list(rows), {course.id: course}))


@course_router.get(
    "/{course_id}/versions",
    response_model=ApiResponse[list[CourseVersionReadDTO]],
    summary="Published version history (1.0, 1.1, 2.0...) with authors, reviewers and reasons",
)
async def list_course_versions(
    course_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[CourseVersionReadDTO]]:
    service = RevisionService(db)
    course = await service.get_course(course_id)
    await service.ensure_can_view(current_user, course)
    versions = await VersionService(db).list_versions(course.id)
    return ApiResponse(message="Versions retrieved successfully", data=await version_dtos(db, list(versions)))


@course_router.get(
    "/{course_id}/versions/{version_id}",
    response_model=ApiResponse[CourseVersionDetailDTO],
    summary="One published version including its full content snapshot",
)
async def get_course_version(
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseVersionDetailDTO]:
    service = RevisionService(db)
    course = await service.get_course(course_id)
    await service.ensure_can_view(current_user, course)
    version = await VersionService(db).get_version(course.id, version_id)
    return ApiResponse(message="Version retrieved successfully", data=(await version_dtos(db, [version], True))[0])


@course_router.post(
    "/{course_id}/versions/{version_id}/rollback",
    response_model=ApiResponse[RevisionDetailDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Start a rollback to an earlier version (Course Lead / Head of Learning). It needs final "
    "approval from someone else, then publishes as a new version.",
)
async def rollback_course(
    course_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ReasonDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).rollback(course_id, version_id, payload.reason, current_user)
    return ApiResponse(message="Rollback submitted for final approval", data=await _detail(db, revision, current_user))


@course_router.post(
    "/{course_id}/archive",
    response_model=ApiResponse[CourseGovernanceDTO],
    summary="Withdraw a published course from learners (ARCHIVE_CONTENT). Versions and history are kept.",
)
async def archive_course(
    course_id: uuid.UUID,
    payload: ReasonDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CourseGovernanceDTO]:
    course = await RevisionService(db).archive(course_id, payload.reason, current_user)
    data = CourseGovernanceDTO(
        governance_enabled=settings.content_governance_enabled,
        lifecycle=course.governance_status,
        current_version_label=course.current_version_label,
        layer="live",
    )
    return ApiResponse(message="Course archived", data=data)


@course_router.post(
    "/{course_id}/reinstate",
    response_model=ApiResponse[RevisionDetailDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Request reinstatement of an archived course - goes through quick approval, then publish",
)
async def reinstate_course(
    course_id: uuid.UUID,
    payload: ReasonDTO,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RevisionDetailDTO]:
    revision = await RevisionService(db).reinstate(course_id, payload.reason, current_user)
    return ApiResponse(message="Reinstatement submitted for approval", data=await _detail(db, revision, current_user))
