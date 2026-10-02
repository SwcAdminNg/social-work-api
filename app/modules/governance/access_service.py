"""The caller's governance access, summarised for the frontend: returned on
login (AuthSessionDTO.access) and on GET/PATCH /users/me, so the UI can decide
which menus, screens and buttons to show without extra round trips.

Per-course detail (e.g. "can I approve *this* revision?") still comes from the
resource itself (`available_actions`) - this is the navigation-level picture.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.course.entity import Course
from app.modules.governance.dto import CourseAccessDTO, UserAccessDTO, UserCapabilitiesDTO
from app.modules.governance.permission_service import PermissionService
from app.modules.governance.permissions import ROLE_PERMISSIONS, PermissionEnum, StaffRoleEnum
from app.modules.user.entity import User, UserTypeEnum

P = PermissionEnum
_REVIEW = {P.ACADEMIC_REVIEW, P.QA_REVIEW, P.MODERATE_ASSESSMENT, P.APPROVE_COURSE, P.FINAL_APPROVAL}
_STAFF = _REVIEW | {
    P.EDIT_DRAFT_CONTENT, P.SUBMIT_FOR_REVIEW, P.PUBLISH_CONTENT, P.MARK_ASSESSMENT, P.APPROVE_RESULTS,
}


async def build_user_access(session: AsyncSession, user: User) -> UserAccessDTO:
    permissions = PermissionService(session)
    global_roles = [r for r in await permissions.effective_roles(user, None) if r.course_id is None]
    global_perms = await permissions.permissions(user, None)

    # Course-scoped grants, grouped per course.
    scoped: dict[uuid.UUID, list[StaffRoleEnum]] = {}
    for assignment in await permissions.list_assignments(user_id=user.id):
        if assignment.course_id is not None:
            scoped.setdefault(assignment.course_id, []).append(assignment.role)
    titles: dict[uuid.UUID, str] = {}
    if scoped:
        rows = (await session.execute(select(Course.id, Course.title).where(Course.id.in_(list(scoped))))).all()
        titles = {course_id: title for course_id, title in rows}

    course_access = [
        CourseAccessDTO(
            course_id=course_id,
            course_title=titles.get(course_id),
            roles=sorted(set(roles), key=lambda r: r.value),
            permissions=sorted(
                {p for role in roles for p in ROLE_PERMISSIONS[role]}, key=lambda p: p.value
            ),
        )
        for course_id, roles in scoped.items()
        if course_id in titles
    ]

    # Owned courses: instructors (and admins who created courses) hold the
    # INSTRUCTOR role on every course they own.
    owned_count = 0
    owned_perms: set[PermissionEnum] = set()
    if user.user_type in (UserTypeEnum.INSTRUCTOR, UserTypeEnum.ADMIN):
        owned_count = (
            await session.execute(
                select(func.count(Course.id)).where(Course.instructor_id == user.id, Course.deleted_at.is_(None))
            )
        ).scalar_one()
        if owned_count or user.user_type == UserTypeEnum.INSTRUCTOR:
            owned_perms = set(ROLE_PERMISSIONS[StaffRoleEnum.INSTRUCTOR])

    anywhere = set(global_perms) | owned_perms | {p for c in course_access for p in c.permissions}

    capabilities = UserCapabilitiesDTO(
        can_create_courses=P.CREATE_CONTENT in global_perms,
        can_edit_content=P.EDIT_DRAFT_CONTENT in anywhere,
        can_submit_for_review=P.SUBMIT_FOR_REVIEW in anywhere,
        can_review_content=bool(anywhere & _REVIEW),
        can_publish=P.PUBLISH_CONTENT in anywhere,
        can_archive=P.ARCHIVE_CONTENT in anywhere,
        can_mark_essays=P.MARK_ASSESSMENT in anywhere,
        can_moderate_marks=P.MODERATE_ASSESSMENT in anywhere,
        can_approve_results=P.APPROVE_RESULTS in anywhere,
        can_force_approve=P.FORCE_APPROVE in anywhere,
        can_manage_staff_roles=P.MANAGE_STAFF_ROLES in anywhere,
        can_view_audit_log=bool(anywhere & {P.FINAL_APPROVAL, P.PUBLISH_CONTENT, P.MANAGE_STAFF_ROLES}),
        can_access_approval_centre=bool(anywhere & _STAFF),
    )
    return UserAccessDTO(
        governance_enabled=settings.content_governance_enabled,
        roles=sorted({r.role for r in global_roles}, key=lambda r: r.value),
        permissions=sorted(global_perms, key=lambda p: p.value),
        owned_course_count=owned_count,
        owned_course_permissions=sorted(owned_perms, key=lambda p: p.value),
        course_access=course_access,
        capabilities=capabilities,
    )
