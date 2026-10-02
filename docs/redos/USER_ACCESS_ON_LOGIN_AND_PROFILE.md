# User access on login and profile

The login session and the profile endpoint now tell the frontend **what the signed-in user may see and do**. This covers their governance roles, their permission codes and a set of ready-made yes/no capability flags. Use it to build menus, routes and screens right after login, without extra calls.

Applies to every user type (student, instructor, admin and the reviewer roles). The change is additive: no existing field changed.

---

## User stories

- *As any user*, I only see the menus and screens I can actually use. I'm never shown an "Approval Centre" or "Publish" button that would fail with a 403.
- *As an instructor*, right after login my dashboard shows "Submit for review" instead of "Publish", plus my review inbox if I've been given a reviewer role.
- *As a staff member who was just given a role* (e.g. Course Lead), the new screens appear the next time my profile is fetched. I don't have to log out.

---

## 1. Where `access` appears

| Endpoint | Where |
|---|---|
| `POST /auth/2fa/login/verify` | `data.access` (alongside `data.user` and `data.tokens`) |
| `POST /auth/2fa/setup/totp/confirm` | `data.access` |
| `POST /auth/2fa/setup/email/confirm` | `data.access` |
| `GET /users/me` | `data.access` (alongside the existing profile fields) |
| `PATCH /users/me` | `data.access` |

> `POST /auth/login` and `POST /auth/signup` don't return a session; they return a 2FA challenge. That's unchanged. The session, with `access` in it, arrives when the 2FA step completes (the three `/auth/2fa/...` endpoints above). `POST /auth/refresh-token` still returns tokens only, so call `GET /users/me` if you need to refresh access.

---

## 2. Shape

```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "user": { "id": "5bf9…", "first_name": "Ike", "user_type": "INSTRUCTOR", "...": "..." },
    "tokens": { "access_token": "…", "refresh_token": "…", "token_type": "bearer", "expires_in": 1800 },
    "access": {
      "governance_enabled": true,
      "roles": [],
      "permissions": ["CREATE_CONTENT"],
      "owned_course_count": 3,
      "owned_course_permissions": ["CREATE_CONTENT", "EDIT_DRAFT_CONTENT", "MARK_ASSESSMENT", "SUBMIT_FOR_REVIEW"],
      "course_access": [
        {
          "course_id": "4f42…",
          "course_title": "Child Protection Essentials",
          "roles": ["COURSE_LEAD"],
          "permissions": ["APPROVE_COURSE", "APPROVE_RESULTS", "EDIT_DRAFT_CONTENT", "SUBMIT_FOR_REVIEW"]
        }
      ],
      "capabilities": {
        "can_create_courses": true,
        "can_edit_content": true,
        "can_submit_for_review": true,
        "can_review_content": true,
        "can_publish": false,
        "can_archive": false,
        "can_mark_essays": true,
        "can_moderate_marks": false,
        "can_approve_results": true,
        "can_force_approve": false,
        "can_manage_staff_roles": false,
        "can_view_audit_log": false,
        "can_access_approval_centre": true
      }
    }
  }
}
```

### 2.1 Fields

| Field | Meaning |
|---|---|
| `governance_enabled` | Whether the content approval workflow is switched on for this environment. When `false`, publishing works the old way (see §4). |
| `roles` | **Platform-wide** roles. Includes implicit ones: every admin is `PLATFORM_ADMIN`. Values: `INSTRUCTOR`, `CONTENT_DEVELOPER`, `ACADEMIC_REVIEWER`, `ASSESSMENT_MODERATOR`, `QA_REVIEWER`, `COURSE_LEAD`, `LEAD_ASSESSOR`, `HEAD_OF_LEARNING`, `PLATFORM_ADMIN`. |
| `permissions` | **Platform-wide** permission codes (see §3). |
| `owned_course_count` | How many courses this user owns (instructors; also admins who created courses). |
| `owned_course_permissions` | Permissions the user has on **each course they own**. For instructors these are `CREATE_CONTENT`, `EDIT_DRAFT_CONTENT`, `SUBMIT_FOR_REVIEW` and `MARK_ASSESSMENT`. |
| `course_access` | Roles granted on **specific courses** (e.g. Course Lead of one course), with that course's permissions. |
| `capabilities` | Yes/no flags, each true when the user can do the thing on **at least one** course. Use them for navigation. |

### 2.2 Capability flags → UI

| Flag | Show |
|---|---|
| `can_create_courses` | "Create course" button |
| `can_edit_content` | Course editor / "My courses" |
| `can_submit_for_review` | "Submit for review" on courses being edited |
| `can_review_content` | Review screens (academic / QA / moderation / course lead / final approval) |
| `can_publish` | "Publish" on approved revisions; the "Ready to publish" tab |
| `can_archive` | "Archive" / "Reinstate" |
| `can_mark_essays` | Essay marking screens |
| `can_moderate_marks` | Moderation queue |
| `can_approve_results` | Result approval and release |
| `can_force_approve` | "Force approve" and "Change risk" (Head of Learning) |
| `can_manage_staff_roles` | Staff roles admin screen |
| `can_view_audit_log` | Audit log screen |
| `can_access_approval_centre` | The Approval Centre menu item |

### 2.3 Examples by user type

| User | Typical `capabilities` that are true |
|---|---|
| Student | none (every flag false) |
| Instructor | `can_create_courses`, `can_edit_content`, `can_submit_for_review`, `can_mark_essays`, `can_access_approval_centre` |
| Admin, governance **on** | `can_create_courses`, `can_edit_content`, `can_publish`, `can_archive`, `can_manage_staff_roles`, `can_view_audit_log`, `can_access_approval_centre` |
| Admin, governance **off** | every flag (admins keep full access, as before) |
| Academic Reviewer (plain user account) | `can_review_content`, `can_access_approval_centre` |
| Head of Learning | `can_review_content`, `can_approve_results`, `can_force_approve`, `can_view_audit_log`, `can_access_approval_centre` |

---

## 3. Permission codes

| Code | Allows |
|---|---|
| `CREATE_CONTENT` | Create courses |
| `EDIT_DRAFT_CONTENT` | Edit draft / working-copy content |
| `SUBMIT_FOR_REVIEW` | Submit a revision for review |
| `ACADEMIC_REVIEW` | Decide the Academic Review stage |
| `QA_REVIEW` | Decide the QA Review stage (and quick approvals) |
| `MODERATE_ASSESSMENT` | Decide the Assessment Moderation stage; moderate essay marks |
| `APPROVE_COURSE` | Decide the Course Lead stage (and quick approvals); assign reviewers; start rollbacks |
| `FINAL_APPROVAL` | Decide the Final Approval stage; start rollbacks |
| `FORCE_APPROVE` | Skip remaining stages with a written justification; change risk |
| `PUBLISH_CONTENT` | Publish approved revisions |
| `ARCHIVE_CONTENT` | Archive and reinstate courses |
| `MARK_ASSESSMENT` | Mark essays |
| `APPROVE_RESULTS` | Approve and release moderated essay results |
| `MANAGE_STAFF_ROLES` | Grant and revoke staff roles |

---

## 4. Rules for the frontend

1. **Use `capabilities` for navigation; use `available_actions` for buttons on one item.**
   - `capabilities` says the user can do something *somewhere*.
   - Whether they can act on *this* revision or mark comes from that resource's `available_actions` (e.g. `GET /governance/revisions/{id}`, `GET /essay-marks/{id}`).
   - The two differ because separation of duties is per item: a reviewer can never approve their own work.
2. **Store `access` with the session** and refresh it by calling `GET /users/me`:
   - after the app regains focus;
   - after a `403` from a governance endpoint;
   - when a `ROLE_CHANGED` notification arrives.
3. **`governance_enabled: false`** means the old flow:
   - show "Publish/Unpublish" for course owners and admins;
   - hide the review workflow (submit, Approval Centre, versions rollback).
4. **For one specific course**, `GET /governance/me/permissions?course_id={id}` returns that course's exact roles and permissions.
