from app.modules.governance.permissions import (
    ROLE_PERMISSIONS,
    PermissionEnum,
    StaffRoleEnum,
    permissions_for_roles,
    roles_granting,
)

P = PermissionEnum
R = StaffRoleEnum


def test_every_role_is_mapped():
    assert set(ROLE_PERMISSIONS) == set(StaffRoleEnum)


def test_platform_admin_makes_no_academic_decisions():
    academic = {P.ACADEMIC_REVIEW, P.QA_REVIEW, P.APPROVE_COURSE, P.FINAL_APPROVAL, P.MODERATE_ASSESSMENT}
    assert not ROLE_PERMISSIONS[R.PLATFORM_ADMIN] & academic
    assert P.PUBLISH_CONTENT in ROLE_PERMISSIONS[R.PLATFORM_ADMIN]


def test_content_developers_cannot_publish_or_approve():
    perms = ROLE_PERMISSIONS[R.CONTENT_DEVELOPER]
    assert P.PUBLISH_CONTENT not in perms
    assert not perms & {P.ACADEMIC_REVIEW, P.QA_REVIEW, P.APPROVE_COURSE, P.FINAL_APPROVAL}


def test_only_head_of_learning_gives_final_approval():
    assert roles_granting(P.FINAL_APPROVAL) == [R.HEAD_OF_LEARNING]
    assert roles_granting(P.FORCE_APPROVE) == [R.HEAD_OF_LEARNING]


def test_multiple_roles_union():
    perms = permissions_for_roles([R.ACADEMIC_REVIEWER, R.QA_REVIEWER])
    assert perms == {P.ACADEMIC_REVIEW, P.QA_REVIEW}
