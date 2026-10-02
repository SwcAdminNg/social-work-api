import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.responses import ApiResponse
from app.core.database import get_db
from app.modules.governance.dependencies import require_permission
from app.modules.governance.dto import StaffRoleAssignmentReadDTO, StaffRoleGrantDTO, StaffRoleRevokeDTO
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum, StaffRoleEnum
from app.modules.governance.staff_role_service import StaffRoleService
from app.modules.user.entity import User

router = APIRouter(prefix="/admin/staff-roles", tags=["Governance - Staff Roles"], route_class=NoNullAPIRoute)

_require_manage_roles = require_permission(PermissionEnum.MANAGE_STAFF_ROLES)


@router.get(
    "",
    response_model=ApiResponse[list[StaffRoleAssignmentReadDTO]],
    summary="List staff role assignments, optionally filtered by user, role or course (MANAGE_STAFF_ROLES)",
)
async def list_staff_roles(
    user_id: uuid.UUID | None = Query(None),
    role: StaffRoleEnum | None = Query(None),
    course_id: uuid.UUID | None = Query(None),
    include_revoked: bool = Query(False, description="Include revoked grants (history)"),
    current_user: User = Depends(_require_manage_roles),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[StaffRoleAssignmentReadDTO]]:
    rows = await PermissionService(db).list_assignments(user_id, role, course_id, include_revoked)
    return ApiResponse(
        message="Staff roles retrieved successfully",
        data=[StaffRoleAssignmentReadDTO.model_validate(r) for r in rows],
    )


@router.post(
    "",
    response_model=ApiResponse[StaffRoleAssignmentReadDTO],
    status_code=status.HTTP_201_CREATED,
    summary="Grant a staff role, platform-wide or scoped to one course (MANAGE_STAFF_ROLES). Audited.",
)
async def grant_staff_role(
    payload: StaffRoleGrantDTO,
    current_user: User = Depends(_require_manage_roles),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StaffRoleAssignmentReadDTO]:
    assignment = await StaffRoleService(db).grant(payload, current_user)
    return ApiResponse(message="Role granted successfully", data=StaffRoleAssignmentReadDTO.model_validate(assignment))


@router.post(
    "/{assignment_id}/revoke",
    response_model=ApiResponse[StaffRoleAssignmentReadDTO],
    summary="Revoke a staff role grant; the row is kept as history (MANAGE_STAFF_ROLES). Audited.",
)
async def revoke_staff_role(
    assignment_id: uuid.UUID,
    payload: StaffRoleRevokeDTO,
    current_user: User = Depends(_require_manage_roles),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StaffRoleAssignmentReadDTO]:
    assignment = await StaffRoleService(db).revoke(assignment_id, payload.reason, current_user)
    return ApiResponse(message="Role revoked successfully", data=StaffRoleAssignmentReadDTO.model_validate(assignment))
