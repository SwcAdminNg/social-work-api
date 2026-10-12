import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.api_route import NoNullAPIRoute
from app.common.pagination import PaginatedResponse, PaginationParams
from app.common.responses import ApiResponse
from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course.entity import Course
from app.modules.course.repository import CourseRepository
from app.modules.governance.audit_service import AuditEntityTypeEnum, AuditService
from app.modules.governance.dependencies import require_permission
from app.modules.governance.dto import AuditLogReadDTO, EffectiveRoleDTO, MyPermissionsDTO
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import PermissionEnum
from app.modules.governance.presenter import UserDirectory
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
    action: str | None = Query(None, max_length=60, description="Exact action code, e.g. DECISION_RETURNED_FOR_REVISION"),
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
        pagination, course_id, revision_id, actor_id, entity_type, entity_id, action, date_from, date_to
    )
    users = UserDirectory(db)
    await users.load(r.actor_id for r in rows)
    course_ids = {r.course_id for r in rows if r.course_id is not None}
    titles: dict[uuid.UUID, str] = {}
    if course_ids:
        found = await db.execute(select(Course.id, Course.title).where(Course.id.in_(course_ids)))
        titles = {cid: title for cid, title in found.all()}
    items = []
    for row in rows:
        dto = AuditLogReadDTO.model_validate(row)
        dto.actor = users.get(row.actor_id)
        dto.course_title = titles.get(row.course_id) if row.course_id else None
        items.append(dto)
    return PaginatedResponse.create(items=items, total_items=total, params=pagination)
