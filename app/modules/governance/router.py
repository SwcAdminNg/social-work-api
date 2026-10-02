import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course.repository import CourseRepository
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.dependencies import require_permission
from app.modules.governance.dto import AuditLogReadDTO, EffectiveRoleDTO, MyPermissionsDTO
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.user.entity import User

router = APIRouter(prefix="/governance", tags=["Governance"], route_class=NoNullAPIRoute)


@router.get(
    "/me/permissions",
    response_model=ApiResponse[MyPermissionsDTO],
    summary="The caller's effective roles and permission codes, platform-wide or for one course. "
    "Frontends use this to decide which governance actions to show.",
)
async def get_my_permissions(
    course_id: uuid.UUID | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[MyPermissionsDTO]:
    course = None
    if course_id is not None:
        course = await CourseRepository(db).get_by_id(course_id)
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    service = PermissionService(db)
    roles = await service.effective_roles(current_user, course)
    perms = await service.permissions(current_user, course)
    data = MyPermissionsDTO(
        course_id=course_id,
        governance_enabled=settings.content_governance_enabled,
        roles=[EffectiveRoleDTO(**r.__dict__) for r in roles],
        permissions=sorted(perms, key=lambda p: p.value),
    )
    return ApiResponse(message="Permissions retrieved successfully", data=data)


@router.get(
    "/audit",
    response_model=PaginatedResponse[AuditLogReadDTO],
    summary="Governance audit trail - every role change, review decision, publish, archive and "
    "rollback (FINAL_APPROVAL, PUBLISH_CONTENT or MANAGE_STAFF_ROLES)",
)
async def list_audit_log(
    pagination: PaginationParams = Depends(),
    course_id: uuid.UUID | None = Query(None),
    revision_id: uuid.UUID | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    entity_type: AuditEntityTypeEnum | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    current_user: User = Depends(
        require_permission(
            PermissionEnum.FINAL_APPROVAL, PermissionEnum.PUBLISH_CONTENT, PermissionEnum.MANAGE_STAFF_ROLES
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AuditLogReadDTO]:
    rows, total = await AuditService(db).list(
        pagination, course_id, revision_id, actor_id, entity_type, entity_id, date_from, date_to
    )
    return PaginatedResponse.create(
        items=[AuditLogReadDTO.model_validate(r) for r in rows], total_items=total, params=pagination
    )
