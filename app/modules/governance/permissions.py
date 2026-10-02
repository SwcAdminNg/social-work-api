"""Permission codes and the staff roles that grant them.

Pure code (no DB): the SWCL governance framework says the platform should check
*permissions*, not job titles, while still letting one person hold several roles.
So roles live in `staff_role_assignments` (optionally scoped to one course) and
each role maps to a fixed set of permission codes here. Changing what a role may
do is a code change, reviewed like any other.
"""

import enum


class PermissionEnum(str, enum.Enum):
    # The twelve codes from the SWCL Learning Content Approval framework, section 6.
    CREATE_CONTENT = "CREATE_CONTENT"
    EDIT_DRAFT_CONTENT = "EDIT_DRAFT_CONTENT"
    SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"
    ACADEMIC_REVIEW = "ACADEMIC_REVIEW"
    QA_REVIEW = "QA_REVIEW"
    APPROVE_COURSE = "APPROVE_COURSE"
    FINAL_APPROVAL = "FINAL_APPROVAL"
    PUBLISH_CONTENT = "PUBLISH_CONTENT"
    MARK_ASSESSMENT = "MARK_ASSESSMENT"
    MODERATE_ASSESSMENT = "MODERATE_ASSESSMENT"
    APPROVE_RESULTS = "APPROVE_RESULTS"
    ARCHIVE_CONTENT = "ARCHIVE_CONTENT"
    # Internal additions.
    MANAGE_STAFF_ROLES = "MANAGE_STAFF_ROLES"
    # Skip remaining review stages with a written, audited justification.
    FORCE_APPROVE = "FORCE_APPROVE"


class StaffRoleEnum(str, enum.Enum):
    INSTRUCTOR = "INSTRUCTOR"
    CONTENT_DEVELOPER = "CONTENT_DEVELOPER"
    ACADEMIC_REVIEWER = "ACADEMIC_REVIEWER"
    ASSESSMENT_MODERATOR = "ASSESSMENT_MODERATOR"
    QA_REVIEWER = "QA_REVIEWER"
    COURSE_LEAD = "COURSE_LEAD"
    LEAD_ASSESSOR = "LEAD_ASSESSOR"
    HEAD_OF_LEARNING = "HEAD_OF_LEARNING"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"


P = PermissionEnum

ROLE_PERMISSIONS: dict[StaffRoleEnum, frozenset[PermissionEnum]] = {
    StaffRoleEnum.INSTRUCTOR: frozenset(
        {P.CREATE_CONTENT, P.EDIT_DRAFT_CONTENT, P.SUBMIT_FOR_REVIEW, P.MARK_ASSESSMENT}
    ),
    StaffRoleEnum.CONTENT_DEVELOPER: frozenset({P.CREATE_CONTENT, P.EDIT_DRAFT_CONTENT, P.SUBMIT_FOR_REVIEW}),
    StaffRoleEnum.ACADEMIC_REVIEWER: frozenset({P.ACADEMIC_REVIEW}),
    StaffRoleEnum.ASSESSMENT_MODERATOR: frozenset({P.MODERATE_ASSESSMENT}),
    StaffRoleEnum.QA_REVIEWER: frozenset({P.QA_REVIEW}),
    StaffRoleEnum.COURSE_LEAD: frozenset(
        {P.APPROVE_COURSE, P.APPROVE_RESULTS, P.EDIT_DRAFT_CONTENT, P.SUBMIT_FOR_REVIEW}
    ),
    StaffRoleEnum.LEAD_ASSESSOR: frozenset({P.APPROVE_RESULTS}),
    StaffRoleEnum.HEAD_OF_LEARNING: frozenset({P.FINAL_APPROVAL, P.FORCE_APPROVE, P.APPROVE_RESULTS}),
    # Publishes and archives, but makes no academic decisions (framework 2.7).
    # Draft editing is kept so admins can still fix content - editing makes them a
    # contributor to that revision, which separation of duties then bars from
    # approving it.
    StaffRoleEnum.PLATFORM_ADMIN: frozenset(
        {P.PUBLISH_CONTENT, P.ARCHIVE_CONTENT, P.MANAGE_STAFF_ROLES, P.CREATE_CONTENT, P.EDIT_DRAFT_CONTENT}
    ),
}

ALL_PERMISSIONS: frozenset[PermissionEnum] = frozenset(PermissionEnum)


def permissions_for_roles(roles) -> set[PermissionEnum]:
    result: set[PermissionEnum] = set()
    for role in roles:
        result |= ROLE_PERMISSIONS[StaffRoleEnum(role)]
    return result


def roles_granting(permission: PermissionEnum) -> list[StaffRoleEnum]:
    """Every role whose permission set includes `permission` - used to build
    "who can act on this stage" queries over `staff_role_assignments`."""
    return [role for role, perms in ROLE_PERMISSIONS.items() if permission in perms]
