# Instructor Course Authoring & Approval Workflow — Complete API Reference

**Audience:** the instructor frontend and the reviewer/approver screens (and the AI building them).

This is the single reference for the whole journey of a course:

> **Become an instructor → create a course → build the curriculum (full CRUD) → submit for review → reviewers decide (role by role) → an admin publishes → learners see it → later edits, versions, rollback and archive.**

It covers every endpoint involved, with request and response examples, the user stories for every role, the states, the errors and the UI rules. It consolidates and extends:

| Existing doc | What this doc adds |
|---|---|
| [`../phase_3/CONTENT_GOVERNANCE_ADMIN_API.md`](../phase_3/CONTENT_GOVERNANCE_ADMIN_API.md) | The same pipeline, told end-to-end from the instructor's chair, with every authoring payload |
| [`../phase_3/APPROVAL_CENTRE_API.md`](../phase_3/APPROVAL_CENTRE_API.md) | Per-role reviewer workflows and screens |
| [`../phase_3/ESSAY_MODERATION_API.md`](../phase_3/ESSAY_MODERATION_API.md) | Essay marking is summarised in §11 only |
| [`../redos/INSTRUCTOR_CONTENT_GOVERNANCE_GUIDE.md`](../redos/INSTRUCTOR_CONTENT_GOVERNANCE_GUIDE.md) | Adds the full create/read/update/delete reference for courses, modules and every item type |

---

## Contents

1. [Conventions](#1-conventions)
2. [User stories](#2-user-stories)
3. [The mental model](#3-the-mental-model)
4. [Bootstrapping the app: identity, roles and capabilities](#4-bootstrapping-the-app-identity-roles-and-capabilities)
5. [Course CRUD](#5-course-crud)
6. [Curriculum CRUD](#6-curriculum-crud)
7. [Instructor review workflow](#7-instructor-review-workflow)
8. [Reviewer and approver workflows, role by role](#8-reviewer-and-approver-workflows-role-by-role)
9. [End-to-end scenarios](#9-end-to-end-scenarios)
10. [After publishing: versions, rollback, archive, reinstate](#10-after-publishing-versions-rollback-archive-reinstate)
11. [Essay marking (summary)](#11-essay-marking-summary)
12. [Notifications](#12-notifications)
13. [Errors](#13-errors)
14. [When governance is switched off](#14-when-governance-is-switched-off)
15. [Screens and implementation checklist](#15-screens-and-implementation-checklist)
16. [Appendix: enums and endpoint index](#16-appendix-enums-and-endpoint-index)

---

## 1. Conventions

- **Base URL:** the API root. Paths below are relative to it.
- **Auth:** every endpoint in this doc needs `Authorization: Bearer <access_token>`, except the two applicant endpoints in §4.1.
- **Envelope:** `ApiResponse<T>` is `{ "success": true, "message": "…", "data": … }`. Paginated lists return `{ "success": true, "message": "OK", "data": [...], "meta": { page, page_size, total_items, total_pages, has_next, has_previous } }`. Pagination params: `page` (default 1) and `page_size` (default 20, max 100).
- **Errors:** `{ "success": false, "message": "…", "errors"?: [{ "loc": [...], "msg": "…" }] }`. See §13.
- **Null stripping:** the API removes null/absent fields from JSON. Treat a missing field as `null`.
- **Ids** are UUIDs. **Timestamps** are ISO-8601 UTC.
- **Feature flag:** the approval workflow is active only when the server setting `CONTENT_GOVERNANCE_ENABLED=true`. The frontend reads it from `access.governance_enabled` (§4.2). When it is `false` see §14. **Everything in §7–§10 assumes it is `true`.**
- **Render buttons from the server.** Governance resources return `available_actions`. Show a button only if its action is in that list. Never infer buttons from role names or statuses.

---

## 2. User stories

### 2.1 Instructor (course author)

**Getting started**
1. *As a candidate*, I apply to become an instructor, and once approved I set up my account and log in. (Handled by the instructor application flow, §4.1.)
2. *As an instructor*, when I log in I immediately know what I'm allowed to do (create courses, submit for review, mark essays), so I only see relevant menus.

**Creating a course**
3. *As an instructor*, I create a course with a title, description, level, category, learning outcomes, requirements, price and thumbnail. Nothing is visible to learners yet.
4. *As an instructor*, I organise the course into modules (sections), and add videos, documents, links, live sessions, quizzes, essays and nested quiz groups to them.
5. *As an instructor*, I can edit, reorder and delete anything in my course while it is a draft, and I can see exactly how it will look to a learner.
6. *As an instructor*, I can upload large videos directly to the video host and large documents directly to storage, and see when a video has finished processing.
7. *As an instructor*, I can generate quiz questions with AI from a topic or from an uploaded PDF/DOCX, then edit them.
8. *As an instructor*, I mark one assessment per module as the **final assessment** that gates the next module.

**Getting it approved**
9. *As an instructor*, when my course is ready I click **Submit for review**, say what it is, and optionally flag it as safeguarding/legal/policy related.
10. *As an instructor*, I see which reviewers are involved, which stage the course is at, who has it, and when it is due.
11. *As an instructor*, I can't edit while it is under review, but I can **withdraw** it to edit again, and I'm told when I do that reviewers must start again.
12. *As an instructor*, if a reviewer returns it, I'm notified, see their comment, and see comments pinned to the exact module/lesson/question. I fix it and resubmit.
13. *As an instructor*, if it is rejected I see why. My content is not lost, and I can improve it and submit again.
14. *As an instructor*, I'm notified when it is approved and when it goes live, and I see **Version 1.0** on the course.

**After it is live**
15. *As an instructor*, I can keep improving a live course. Learners keep seeing the published version until my changes are approved.
16. *As an instructor*, before submitting I can see **what changed** (added, removed, edited, moved), each with a risk rating, and preview it as a learner.
17. *As an instructor*, small fixes (typos, links) get a quick approval; bigger ones get a fuller review; and the app tells me which and why.
18. *As an instructor*, I can change the price, access window, thumbnail, instructor credits and live-session times immediately, with no review.
19. *As an instructor*, I can see a course's **version history**: who changed what, who approved it and when.
20. *As an instructor*, one inbox shows my drafts, anything returned to me, and recent decisions on my work.

### 2.2 Reviewers and approvers

21. *As an Academic Reviewer*, I see revisions waiting for academic review, what changed, a learner preview, and I approve, approve with minor changes, return, reject or escalate. I never review my own work.
22. *As an Assessment Moderator*, I see revisions that change assessments, check the questions, answers, pass marks and attempts, and decide. (I also moderate essay marks, §11.)
23. *As a QA Reviewer*, I check quality and consistency and decide. I can alone approve LOW-risk quick changes.
24. *As a Course Lead*, I give the course-level approval, assign reviewers to stages, see what is overdue on my courses, and can start a rollback.
25. *As the Head of Learning*, I give final approval to high-risk changes, can re-rate risk, and can force-approve with a written, audited justification.
26. *As a Platform Administrator*, I publish only what has every required approval, and I can archive and reinstate courses. I make no academic decisions.
27. *As any reviewer*, the system guarantees I can't approve something I contributed to, and that nobody supplies two independent sign-offs on the same revision.

### 2.3 Management and learners

28. *As SWCL management*, every decision is traceable: who acted, on which version, when, why and with what result.
29. *As a learner*, I only see approved, published content, and my progress, quiz attempts and certificates survive every new version.

---

## 3. The mental model

### 3.1 Two separate things: the course and the revision

- The **course** has a **lifecycle**: `DRAFT` (never published) → `PUBLISHED` ⇄ `ARCHIVED`. Field: `governance_status`.
- A **revision** is one batch of changes travelling through review. It has a **status** and a **kind**. A course has **at most one open revision**.

| `kind` | When | Where the edits live |
|---|---|---|
| `INITIAL` | A never-published course | The course's own rows *are* the draft. Learners can't see them anyway. |
| `CHANGE` | Any edit to a published course | A hidden **working copy** (a full clone). Learners keep seeing the published version. |
| `ROLLBACK` | Restoring an earlier version | A working copy matching that version |
| `REINSTATE` | Bringing back an archived course | None |

### 3.2 The big picture

```
 Instructor builds the course (or edits a live one)
        │  every write is held privately; learners see nothing new
        ▼
 [ Submit for review ]  → the system rates risk (LOW / MEDIUM / HIGH) and picks the stages
        ▼
 QUICK_APPROVAL                                   (LOW)
 ACADEMIC_REVIEW → (ASSESSMENT_MODERATION) → QA_REVIEW → COURSE_LEAD_APPROVAL   (MEDIUM)
 … → FINAL_APPROVAL (Head of Learning)            (HIGH, and every new course)
        │              ▲
        │   a reviewer can RETURN it → instructor edits → resubmits (new round)
        ▼
 READY_TO_PUBLISH → Platform Admin publishes → Version 1.0 / 1.1 / 2.0 … is live
```

**Rules the UI must respect**
- **Instructors do not publish.** They submit. A Platform Admin publishes once every required stage is approved.
- **A new course is always HIGH risk**, so it goes through every stage including the Head of Learning.
- **Nobody approves their own work.** Anyone who edited the revision is a *contributor* and can't approve any stage of it. This holds even if they also hold a reviewer role.
- **One person can't sign off two different stages** of the same revision.
- **Under review = read-only.** Writes to the course return `409` until the instructor withdraws, or the revision is returned.

### 3.3 Revision statuses (`status`)

| Status | Meaning | Editable? |
|---|---|---|
| `DRAFT` | Not submitted | ✅ |
| `SUBMITTED_FOR_REVIEW` | Waiting for the first reviewer | ❌ |
| `ACADEMIC_REVIEW` | A reviewer has claimed academic review | ❌ |
| `ACADEMICALLY_APPROVED` | Academic review done | ❌ |
| `ASSESSMENT_MODERATION` | A moderator has claimed the assessment check | ❌ |
| `QA_REVIEW` | A reviewer has claimed QA | ❌ |
| `QA_APPROVED` | QA done | ❌ |
| `COURSE_APPROVED` | Course Lead done | ❌ |
| `FINAL_APPROVAL_REQUIRED` | Waiting for the Head of Learning | ❌ |
| `READY_TO_PUBLISH` | Every stage approved | ❌ |
| `RETURNED_FOR_REVISION` | Sent back to the author | ✅ |
| `PUBLISHED` | Live | closed |
| `REJECTED` | Declined | closed |
| `WITHDRAWN` | Discarded (or withdrawn by an archive) | closed |

Notes:
- The `*_REVIEW` / `ASSESSMENT_MODERATION` labels appear while a reviewer has **claimed** or been **assigned** the stage. Until then the status shows the last milestone reached (or `SUBMITTED_FOR_REVIEW`).
- `current_stage` always names the stage awaiting a decision: `QUICK_APPROVAL`, `ACADEMIC_REVIEW`, `ASSESSMENT_MODERATION`, `QA_REVIEW`, `COURSE_LEAD_APPROVAL` or `FINAL_APPROVAL`.
- `is_editable` on the revision summary is `true` exactly for `DRAFT` and `RETURNED_FOR_REVISION`.
- Each resubmission after a return starts a new `round` from the first stage.

### 3.4 Risk and routing (decided automatically on submit)

| Risk | Typical changes | Stages |
|---|---|---|
| **LOW** | Title/typo fixes, link fixes, reordering, preview flag, durations | `QUICK_APPROVAL` (one QA Reviewer **or** one Course Lead) |
| **MEDIUM** | New/removed module or lesson, new video or document, question or essay wording, description / prerequisite / requirements / level / category, moving a lesson to another module | `ACADEMIC_REVIEW → QA_REVIEW → COURSE_LEAD_APPROVAL` |
| **HIGH** | **A new course**; assessment added/removed; pass mark, attempts or time limit; a correct answer changed; questions/options added or removed; learning outcomes; certificate settings; final-assessment flag; **any flag** | `… → FINAL_APPROVAL` (Head of Learning) |

- **Assessment moderation:** if any MEDIUM or HIGH change is inside an assessment, `ASSESSMENT_MODERATION` is inserted after academic review.
- **Raising risk:** the submitter can raise risk with `declared_risk` or `flags` (`SAFEGUARDING`, `LEGAL`, `POLICY`, `CERTIFICATE_RULE`, `CPD_RECOGNITION`; any flag forces HIGH) but can never lower it. Only the Head of Learning can lower it.
- **Rollback** → `FINAL_APPROVAL` only. **Reinstate** → `QUICK_APPROVAL`.
- **Version label** is proposed at submission: first publish = `1.0`; HIGH = major bump (`1.4 → 2.0`); otherwise minor (`1.0 → 1.1`).
- **Due dates:** each stage's `due_at` = when it started + `REVIEW_SLA_DAYS` (default 5 days).

### 3.5 What goes through review, and what is live immediately (for a published course)

| Held for review (working copy) | Applies immediately (no review) |
|---|---|
| Modules, lessons, videos, documents, links (add / edit / remove / reorder) | Price, `is_free`, `is_exclusive` |
| Quizzes, quiz groups, questions, options, essay settings, pass marks, attempts | Access mode and access window |
| Course **title, description, prerequisite, level, category** | Thumbnail |
| **`what_you_will_learn`, `material_includes`, `requirements`** | Instructor credits (`instructors`) |
| **`certificate_enabled`** | **Live-session date, time, duration and guest** |

For a **never-published** course (`INITIAL`) nothing is visible to learners, so everything is simply a draft.

### 3.6 Who can do what, at a glance

| Role | Permissions | Does |
|---|---|---|
| `INSTRUCTOR` | CREATE_CONTENT, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW, MARK_ASSESSMENT | Authors, submits, withdraws, discards, marks essays |
| `CONTENT_DEVELOPER` | CREATE_CONTENT, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW | Same authoring rights without being the owner |
| `ACADEMIC_REVIEWER` | ACADEMIC_REVIEW | Decides `ACADEMIC_REVIEW` |
| `ASSESSMENT_MODERATOR` | MODERATE_ASSESSMENT | Decides `ASSESSMENT_MODERATION`; moderates essay marks |
| `QA_REVIEWER` | QA_REVIEW | Decides `QA_REVIEW` and `QUICK_APPROVAL` |
| `COURSE_LEAD` | APPROVE_COURSE, APPROVE_RESULTS, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW | Decides `COURSE_LEAD_APPROVAL` and `QUICK_APPROVAL`; assigns reviewers; starts rollbacks |
| `LEAD_ASSESSOR` | APPROVE_RESULTS | Approves and releases essay results |
| `HEAD_OF_LEARNING` | FINAL_APPROVAL, FORCE_APPROVE, APPROVE_RESULTS | Decides `FINAL_APPROVAL`; force-approves; re-rates risk; starts rollbacks |
| `PLATFORM_ADMIN` | PUBLISH_CONTENT, ARCHIVE_CONTENT, MANAGE_STAFF_ROLES, CREATE_CONTENT, EDIT_DRAFT_CONTENT | Publishes, archives, reinstates, grants roles. Makes no academic decisions. |

**Implicit roles (no setup):** every `ADMIN` account is a `PLATFORM_ADMIN` everywhere; every `INSTRUCTOR` account holds `INSTRUCTOR` on the courses **it owns** (`course.instructor_id`). All other roles are granted by an admin, platform-wide or **scoped to one course** (§8.7).

---

## 4. Bootstrapping the app: identity, roles and capabilities

### 4.1 Becoming an instructor (summary)

Instructors can't self-register through `/auth/signup`. The flow is:

1. `POST /instructor-applications` (public): the candidate applies with details and a CV.
2. An admin approves it, and the candidate gets an emailed 7-day link to the instructor app: `/complete-setup?token=…`.
3. `POST /instructor-applications/complete-setup` (public): choose a username and password. The response is the same `two_factor_setup_required` shape as signup.
4. Forced 2FA setup, then normal `POST /auth/login`.

Full detail: [`../phase_1/INSTRUCTOR_APPLICATION_APPLICANT_API.md`](../phase_1/INSTRUCTOR_APPLICATION_APPLICANT_API.md), [`../phase_1/INSTRUCTOR_APPLICATION_ADMIN_API.md`](../phase_1/INSTRUCTOR_APPLICATION_ADMIN_API.md), [`../phase_1/TWO_FACTOR_AUTH_API.md`](../phase_1/TWO_FACTOR_AUTH_API.md).

### 4.2 The `access` object (login + `GET /users/me`)

Login, token refresh, 2FA completion and `GET /users/me` (and `PATCH /users/me`) all return an `access` object. **Store it and drive navigation from it.** Refresh it with `GET /users/me` after a `ROLE_CHANGED` notification.

```json
{
  "access": {
    "governance_enabled": true,
    "roles": ["PLATFORM_ADMIN"],
    "permissions": ["ARCHIVE_CONTENT", "CREATE_CONTENT", "EDIT_DRAFT_CONTENT", "MANAGE_STAFF_ROLES", "PUBLISH_CONTENT"],
    "owned_course_count": 3,
    "owned_course_permissions": ["CREATE_CONTENT", "EDIT_DRAFT_CONTENT", "MARK_ASSESSMENT", "SUBMIT_FOR_REVIEW"],
    "course_access": [
      { "course_id": "4f42…", "course_title": "Child Protection Essentials",
        "roles": ["COURSE_LEAD"], "permissions": ["APPROVE_COURSE", "APPROVE_RESULTS", "EDIT_DRAFT_CONTENT", "SUBMIT_FOR_REVIEW"] }
    ],
    "capabilities": {
      "can_create_courses": true, "can_edit_content": true, "can_submit_for_review": true,
      "can_review_content": false, "can_publish": false, "can_archive": false,
      "can_mark_essays": true, "can_moderate_marks": false, "can_approve_results": false,
      "can_force_approve": false, "can_manage_staff_roles": false, "can_view_audit_log": false,
      "can_access_approval_centre": true
    }
  }
}
```

- `roles` / `permissions` are **platform-wide**. `owned_course_*` describes courses the user owns. `course_access` lists **course-scoped** roles.
- `capabilities` are navigation-level booleans ("can do this on at least one course"):

| Flag | Use it to show |
|---|---|
| `can_create_courses` | **New course** button |
| `can_edit_content` | Course editor / My courses |
| `can_submit_for_review` | The submit-for-review workflow |
| `can_review_content` | Reviewer menus and **Awaiting me** tab |
| `can_publish`, `can_archive` | Publish / archive screens |
| `can_mark_essays`, `can_moderate_marks`, `can_approve_results` | Marking / moderation / results menus |
| `can_force_approve` | Head-of-Learning override tools |
| `can_manage_staff_roles` | Staff role admin |
| `can_view_audit_log` | Audit trail |
| `can_access_approval_centre` | **Inbox** menu, with badges (§8.1) |

Per-item buttons never come from `capabilities`; they come from each resource's `available_actions`.

### 4.3 Permissions for one course

`GET /governance/me/permissions?course_id={optional}`

```json
{
  "data": {
    "course_id": "4f42…",
    "governance_enabled": true,
    "roles": [
      { "role": "INSTRUCTOR", "course_id": "4f42…", "implicit": true },
      { "role": "QA_REVIEWER", "implicit": false, "assignment_id": "9a1…" }
    ],
    "permissions": ["CREATE_CONTENT", "EDIT_DRAFT_CONTENT", "MARK_ASSESSMENT", "QA_REVIEW", "SUBMIT_FOR_REVIEW"]
  }
}
```

Use it on a course page to decide course-specific controls (for example, show **Rollback** only if `APPROVE_COURSE` or `FINAL_APPROVAL` is present).

---

## 5. Course CRUD

A course belongs to the user who creates it (`instructor_id`). An instructor sees and edits **their own** courses; admins and holders of a platform-wide edit role see all; a course-scoped role (e.g. `CONTENT_DEVELOPER` on course X) grants access to that course.

### 5.1 Create — `POST /courses` → `201`

Requires `CREATE_CONTENT` (instructors, admins, and anyone with a platform-wide `CONTENT_DEVELOPER` grant).

```json
{
  "title": "Child Protection Essentials",
  "description": "A practical introduction to safeguarding children in social work.",
  "prerequisite": "None",
  "level": "BEGINNER",
  "category": "TEACHING_ACADEMICS",
  "what_you_will_learn": ["Recognise signs of abuse", "Apply the referral process"],
  "material_includes": ["Video lessons", "Downloadable templates"],
  "requirements": ["A laptop", "Internet access"],
  "is_free": false,
  "price": 25000,
  "thumbnail_url": null,
  "is_exclusive": false,
  "instructors": [
    { "user_id": "5bf9…", "name": "Ike Okafor" },
    { "name": "Dr Guest Speaker" }
  ],
  "access_mode": "SELF_PACED",
  "access_start_date": null,
  "access_end_date": null,
  "certificate_enabled": false
}
```

| Field | Required | Notes |
|---|---|---|
| `title` | ✅ | 1–255 chars. The URL **slug** is generated from it (made unique) and **does not change** on later title edits. |
| `description` | ✅ | Non-empty |
| `level` | ✅ | `BEGINNER` \| `INTERMEDIATE` \| `ADVANCED` |
| `category` | ✅ | See §16.1 |
| `prerequisite` | | Free text |
| `what_you_will_learn`, `material_includes`, `requirements` | | Arrays of strings, default `[]` |
| `is_free` | | Default `true`. Send `price` when `false`. |
| `price` | | `>= 0` |
| `thumbnail_url` | | Normally set via the upload flow (§5.4) |
| `is_exclusive` | | Default `false` |
| `instructors` | | Credits shown on the course. `user_id` is optional (omit for external people). **Defaults to the creator** when omitted. |
| `access_mode` | | `SELF_PACED` (default) or `SCHEDULED`. `SCHEDULED` **requires** `access_start_date` and `access_end_date` (end after start), otherwise `422`. |
| `certificate_enabled` | | Default `false` |

Response (`ApiResponse<CourseReadDTO>`):

```json
{
  "success": true,
  "message": "Course created successfully",
  "data": {
    "id": "4f42…", "created_at": "2026-10-03T09:00:00Z",
    "title": "Child Protection Essentials", "slug": "child-protection-essentials",
    "description": "…", "level": "BEGINNER", "category": "TEACHING_ACADEMICS",
    "what_you_will_learn": ["…"], "material_includes": ["…"], "requirements": ["…"],
    "is_free": false, "price": 25000, "instructor_id": "5bf9…",
    "is_published": false, "is_exclusive": false, "is_featured": false,
    "average_rating": 0, "total_reviews": 0,
    "access_mode": "SELF_PACED", "certificate_enabled": false,
    "governance_status": "DRAFT",
    "instructors": [{ "user_id": "5bf9…", "name": "Ike Okafor", "profile_picture_url": "…", "is_guest": false }],
    "is_bookmarked": false, "is_enrolled": false, "is_completed": false, "has_new_content": false
  }
}
```

A discussion community for the course is created automatically.

> **Right after creating a course (governance on), call `POST /courses/{course_id}/revisions`** (§7.1). It returns the open revision (kind `INITIAL`, status `DRAFT`) so you have its `id` from the start for submit/diff/preview. It is idempotent. Otherwise the revision only appears after the first academic or curriculum write.

### 5.2 List — `GET /courses/manage?…` (paginated)

Instructors get their own courses (plus any with a course-scoped editing role); admins get all.

| Query | Notes |
|---|---|
| `page`, `page_size` | Pagination |
| `search` | Title/description |
| `category`, `level`, `is_free` | Filters |
| `is_published` | `true` / `false` |
| `instructor_id`, `instructor_name` | Owner or credited instructor |

Each row is a `CourseReadDTO` (as above) plus `estimated_total_minutes` / `estimated_duration`. **Governance fields on each row:**
- `governance_status`: `DRAFT` \| `PUBLISHED` \| `ARCHIVED`;
- `current_version_label`: e.g. `"1.1"`; absent before the first publish.

The list does **not** include the open revision's status. To badge "In review / Returned" on a card either:
- load the inbox once (`GET /governance/approval-centre?view=my_drafts`, `…returned_to_me`; rows carry `course_id`, `status`), or
- call `GET /courses/{course_id}/governance` lazily per visible card (§7.1).

### 5.3 Read — `GET /courses/manage/{id}?layer=auto|live|draft`

Returns the course, its full curriculum in **editor** format, and a `governance` block. Allowed for anyone who can edit the course.

| `layer` | Shows |
|---|---|
| `auto` (default) | The working copy if one exists, else live |
| `live` | Exactly what learners see |
| `draft` | The working copy; `404` if none |

```json
{
  "success": true,
  "message": "Course retrieved successfully",
  "data": {
    "id": "4f42…", "title": "Child Protection Essentials (2026)", "governance_status": "PUBLISHED",
    "current_version_label": "1.0", "is_published": true,
    "sections": [ /* see §6.7 */ ],
    "governance": {
      "governance_enabled": true, "lifecycle": "PUBLISHED", "current_version_label": "1.0", "layer": "draft",
      "open_revision": { "id": "7c0d…", "kind": "CHANGE", "status": "DRAFT", "round": 0, "is_editable": true }
    }
  }
}
```

- While a published course has a working copy, pending edits to **academic fields** (title, description, outcomes, …) are overlaid in place on this response, so the editor shows what the instructor typed.
- `governance.layer === "draft"` means `sections` is the working copy. Show a banner (§7.4).
- Same governance block on its own: `GET /courses/{course_id}/governance`.

### 5.4 Update — `PATCH /courses/{id}`

Send only the fields you want to change (partial update). Same field rules as create. Requires edit permission on the course.

```json
{ "title": "Child Protection Essentials (2026)", "what_you_will_learn": ["Recognise signs of abuse", "Escalate a concern"], "price": 30000 }
```

**Behaviour (governance on):**

| Course state | Academic fields (title, description, prerequisite, level, category, outcomes, materials, requirements, `certificate_enabled`) | Operational fields (price, `is_free`, `is_exclusive`, access, thumbnail, `instructors`) |
|---|---|---|
| Never published (`DRAFT`) | Saved on the course (it's the draft). Opens the `INITIAL` revision if none is open. | Saved immediately |
| Published | **Held in the working copy** for review; the first held edit opens it. The `PATCH` response still shows the **live (old)** academic values. Re-fetch `GET /courses/manage/{id}` to see the pending ones. | **Live immediately**, no review |
| Under review | `409` (withdraw first) | Still applies (it never needed review) |
| Archived | `409` "reinstate it before editing" | Applies |

> Note: if a request mixes both kinds while the revision is under review, the academic part triggers the `409` for the whole request. Send operational edits on their own when a course is locked.

### 5.5 Thumbnail — `POST /courses/manage/{course_id}/thumbnail-upload-url`

```json
{ "file_name": "cover.png", "content_type": "image/png" }
```

→ `{ "upload_url": "https://…signed…", "thumbnail_url": "https://cdn…/cover.png" }`

1. `PUT` the raw image bytes to `upload_url` (set the same `Content-Type`).
2. The course's `thumbnail_url` is **already updated** to the returned `thumbnail_url` (and any previous thumbnail is deleted). This is an operational change, so it is **live immediately**, even on a published course.

### 5.6 Delete — `DELETE /courses/{id}`

Soft-deletes the course (removed from lists, learners and caches). No body.

> ⚠️ This is **not** governed: it does not go through review, and it works on a published course. The UI should only offer **Delete** for courses with `governance_status === "DRAFT"`, behind a confirm dialog. To take a live course away from learners, an admin should **archive** it (§10.3) so history and versions are kept.

### 5.7 Instructor credits

Credits are the `instructors` array on create/update. Sending it on update **replaces the full list**. Names listed without a `user_id` are external. Guest lecturers added on a module (§6.1) are automatically credited as `is_guest: true`. Credits are operational (live immediately).

---

## 6. Curriculum CRUD

A course contains **sections** (modules); a section contains **items** of five types:

| `item_type` | What it is |
|---|---|
| `VIDEO` | Hosted video (resumable upload direct to the video host) |
| `DOCUMENT` | A file (direct upload to storage) |
| `LINKS` | An external link |
| `LIVE_SESSION` | A scheduled live class |
| `ASSESSMENT` | `QUIZ`, `ESSAY` or `QUIZ_GROUP` (nested quizzes) |

> **Ids (published courses):** the first edit of a published course clones it. You can keep sending the ids you already have: the API maps them onto the working copy. But **responses return working-copy ids**, so **re-fetch `GET /courses/manage/{id}` after every write** instead of patching local state with returned ids.

All endpoints below need edit permission on the course (owner, admin, or an editing role) and return `409` when the course is under review or archived (§13).

### 6.1 Sections (modules)

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/courses/{course_id}/sections` | `{ "title", "order_index"?, "guest_instructors"? }` | `201` section |
| `PATCH` | `/courses/{course_id}/sections/{section_id}` | any of `title`, `order_index`, `guest_instructors` | section |
| `DELETE` | `/courses/{course_id}/sections/{section_id}` | | `200` |
| `PATCH` | `/courses/{course_id}/sections/reorder` | `{ "sections": [{ "id", "order_index" }] }` | `200` |

```json
{ "title": "Module 1: Foundations", "order_index": 0, "guest_instructors": ["Dr Guest Speaker"] }
```

- `title`: 1–255 chars. `order_index` defaults to 0.
- `guest_instructors`: names of guest lecturers for this module. On update it **replaces the full set**. Each name is added to the course's credits as a guest (not duplicated on re-save). Omit to leave unchanged.
- Response data: `{ id, created_at, course_id, title, order_index, items: [] }`. Guest names are resolved in the manage tree, not here.
- Deleting a section removes its items; on a live (non-working-copy) course it also recalculates enrolled learners' progress.

### 6.2 Items — create

`POST /courses/{course_id}/sections/{section_id}/items` → `201`

Common fields:

| Field | Required | Notes |
|---|---|---|
| `title` | ✅ | 1–255 |
| `item_type` | ✅ | `VIDEO` \| `DOCUMENT` \| `LINKS` \| `LIVE_SESSION` \| `ASSESSMENT` |
| `order_index` | | Default 0 |
| `is_preview` | | Free-preview flag, default `false` |
| `estimated_minutes` | | `>= 0`. Summed into the course's estimated duration. |

Response (`ItemCreateResponseDTO`): `{ id, created_at, section_id, title, item_type, order_index, is_preview, estimated_minutes, video_upload?, document_upload? }`. It does **not** include the sub-content; re-fetch the manage tree.

#### VIDEO

```json
{ "title": "Welcome", "item_type": "VIDEO", "order_index": 0, "estimated_minutes": 8 }
```

The response includes `video_upload` (credentials for a **resumable TUS upload direct to the video host**; no file bytes pass through this API):

```json
{ "video_upload": {
    "tus_endpoint": "https://video.bunnycdn.com/tusupload",
    "library_id": "123456", "video_id": "b1f2…",
    "authorization_signature": "9c1…", "authorization_expire": 1790000000 } }
```

Upload with any TUS client (for example `tus-js-client`) using headers `AuthorizationSignature`, `AuthorizationExpire`, `VideoId`, `LibraryId` taken from those fields, and metadata `filetype`/`title`. Then:
- The item's `video.status` moves `PENDING → PROCESSING → READY` (or `FAILED`) as the host's webhook arrives. Poll `GET /courses/manage/{id}` for it, or show "Processing…".
- If the credentials expire or the upload is interrupted, call `POST /courses/items/{item_id}/video/refresh-upload` → fresh credentials (same shape).

#### DOCUMENT

```json
{ "title": "Referral template", "item_type": "DOCUMENT", "file_name": "referral-template.docx", "downloadable": false }
```

- `file_name` is **required**. `downloadable` defaults to `false` (view/stream only).
- The response includes `document_upload: { "upload_url", "storage_key" }`.
- Flow: `PUT` the raw file bytes to `upload_url` → then `POST /courses/items/{item_id}/document/finalize` with `{ "mime_type"?, "file_size_bytes"? }` → the document's `is_uploaded` becomes `true`.
- Show items with `is_uploaded: false` as "Upload incomplete".

#### LINKS

```json
{ "title": "Statutory guidance", "item_type": "LINKS", "url": "https://example.org/guidance", "label": "Read online", "description": "The 2026 edition" }
```

`url` is **required** (≤ 2000 chars). `label` and `description` are optional.

#### LIVE_SESSION

```json
{ "title": "Case discussion", "item_type": "LIVE_SESSION", "scheduled_start_at": "2026-11-05T14:00:00Z",
  "duration_minutes": 90, "guest_name": "Dr Guest Speaker", "guest_title": "Child Psychologist" }
```

- `scheduled_start_at` is **required** and must be in the future. `duration_minutes` is 5–600 (default 60).
- A video room is created automatically. For a published course, the session is created in the working copy and **learners are invited and a reminder scheduled only when the revision is published**.
- Guest/external attendee invites, joining and recordings: [`../phase_2/LIVE_SESSION_INSTRUCTOR_ADMIN_API.md`](../phase_2/LIVE_SESSION_INSTRUCTOR_ADMIN_API.md). Endpoints: `POST|GET /courses/items/{item_id}/live-session/guests`, `DELETE …/guests/{invite_id}`.

#### ASSESSMENT

Always send `assessment_type`: `QUIZ`, `ESSAY` or `QUIZ_GROUP`.

**Quiz**

```json
{
  "title": "Knowledge check", "item_type": "ASSESSMENT", "assessment_type": "QUIZ",
  "due_date": null,
  "quiz_settings": { "max_attempts": 3, "pass_mark_percentage": 70, "show_result_to_student": true },
  "is_final_assessment": false
}
```

`quiz_settings` is optional: defaults are unlimited attempts, pass mark 70, results shown. Add questions afterwards (§6.5).

**Essay**

```json
{
  "title": "Reflective essay", "item_type": "ASSESSMENT", "assessment_type": "ESSAY",
  "essay_settings": {
    "question": "Reflect on a safeguarding concern you handled.",
    "description": "800–1000 words. Use the Gibbs cycle.",
    "submission_mode": "TEXT", "pass_mark_percentage": 70, "max_attempts": 2, "requires_moderation": true
  },
  "is_final_assessment": true
}
```

- `essay_settings` is **required** (`400` otherwise); `question` and `description` are required in it.
- `submission_mode`: `TEXT` or `DOCUMENT`.
- `requires_moderation` routes marks through moderation and approval before learners see them. It **defaults to on for final assessments** and off otherwise (§11).

**Quiz group** (nested quizzes with random draws)

```json
{
  "title": "End-of-module exam", "item_type": "ASSESSMENT", "assessment_type": "QUIZ_GROUP",
  "quiz_group_settings": { "max_attempts": 2, "pass_mark_percentage": 70, "show_result_to_student": true, "time_limit_seconds": 1800 },
  "is_final_assessment": true
}
```

`time_limit_seconds` (≥ 30) is optional; `null` = untimed. Add group sections and questions afterwards (§6.6).

**Final assessment (`is_final_assessment: true`)**
- At most **one per section** (`400` "This section already has a final assessment").
- A learner must pass it to unlock the next section; exhausting retries resets the section (or the whole course, if it is the last section).
- If `max_attempts` is left unset it defaults to `1` (an explicit `null` means unlimited).
- Changing it later is treated as a HIGH-risk change.

### 6.3 Items — update, delete, reorder

| Method | Path | Notes |
|---|---|---|
| `PATCH` | `/courses/items/{item_id}` | Partial update (below) |
| `DELETE` | `/courses/items/{item_id}` | Removes the item. A document's stored file is deliberately kept (versions/rollback may reference it). Deleting a live session on a live course also closes its room. |
| `PATCH` | `/courses/{course_id}/sections/{section_id}/items/reorder` | `{ "items": [{ "id", "order_index" }] }` |

`PATCH /courses/items/{item_id}` fields:

| Field | Applies to | Notes |
|---|---|---|
| `title`, `order_index`, `is_preview`, `estimated_minutes` | all items | |
| `downloadable` | `DOCUMENT` | `400` "This item is not a document" otherwise |
| `url`, `label`, `description` | `LINKS` | `400` "This item is not a link" otherwise |
| `scheduled_start_at`, `duration_minutes`, `guest_name`, `guest_title` | `LIVE_SESSION` | Only while the session is `SCHEDULED`; the new start must be in the future. **Applies live immediately** (no review), reschedules the room and notifies enrolled learners. |

Limits to design around:
- **An item can't be moved to another section** through the API. Delete and recreate it, which the reviewer sees as removed + added.
- The item **type** can't change. Recreate it instead.
- To replace a video or document file, delete the item and create a new one (or call `refresh-upload` for a failed video).
- The API does not require uploads to be finished before submitting. The UI should warn on items that are `PROCESSING`/`FAILED` (video) or `is_uploaded: false` (document) before **Submit**.

### 6.4 Assessment settings — `PATCH /courses/items/{item_id}/assessment`

```json
{
  "due_date": "2026-12-01T23:59:00Z",
  "is_final_assessment": true,
  "quiz_settings": { "max_attempts": 2, "pass_mark_percentage": 75, "show_result_to_student": true },
  "essay_settings": { "question": "…", "description": "…", "submission_mode": "DOCUMENT", "pass_mark_percentage": 70, "max_attempts": 2, "requires_moderation": true },
  "quiz_group_settings": { "max_attempts": 2, "pass_mark_percentage": 70, "show_result_to_student": true, "time_limit_seconds": 1200 }
}
```

- Send only the block matching the assessment's type (sending the wrong one is `400` "This is not a quiz/essay/quiz group assessment").
- All fields optional. An explicit `"due_date": null` clears the date; omitting it leaves it untouched.
- Risk: pass mark, `max_attempts`, `time_limit_seconds`, `submission_mode` and `is_final_assessment` changes are **HIGH**; `show_result_to_student`, `requires_moderation`, `question`, `description` and `due_date` are **MEDIUM**.

### 6.5 Quiz questions and options

Questions belong to a `QUIZ` item. Updates and deletes use the question/option id directly (they work for standalone quizzes and quiz-group sections alike).

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/courses/items/{item_id}/quiz/questions` | question (below) | `201` question |
| `PATCH` | `/courses/quiz/questions/{question_id}` | `text`, `order_index`, `allow_multiple_answers`, `multi_answer_mode` | `200` |
| `DELETE` | `/courses/quiz/questions/{question_id}` | | `200` |
| `POST` | `/courses/quiz/questions/{question_id}/options` | option | `201` option |
| `PATCH` | `/courses/quiz/options/{option_id}` | `text`, `is_correct`, `order_index` | `200` |
| `DELETE` | `/courses/quiz/options/{option_id}` | | `200` |

```json
{
  "text": "Who is responsible for safeguarding in your organisation?",
  "order_index": 0,
  "allow_multiple_answers": false,
  "multi_answer_mode": null,
  "options": [
    { "text": "Everyone", "is_correct": true, "order_index": 0 },
    { "text": "Only managers", "is_correct": false, "order_index": 1 }
  ]
}
```

- `options[].text` 1–500 chars; `is_correct` defaults `false`.
- `multi_answer_mode` (`AND` all-or-nothing, `OR` partial credit) is only allowed when `allow_multiple_answers` is `true` (defaults to `OR`); sending it otherwise is `400`.
- The API does not enforce "at least one correct option", so validate that in the UI.

Response question: `{ id, text, order_index, allow_multiple_answers, multi_answer_mode, options: [{ id, text, order_index, is_correct }] }`.

**AI help (optional)**

| Endpoint | Input | Output |
|---|---|---|
| `POST /courses/items/{item_id}/quiz/ai-generate` | JSON `{ "prompt", "question_count"?: 1–50 (10), "options_per_question"?: 2–6 (4), "persist"?: true, "provider"?: "GEMINI"\|"OPENAI"\|"DEEPSEEK", "model"? }` | `{ prompt, provider, model, persisted, generated_questions, created_questions }` |
| `POST /courses/items/{item_id}/quiz/ai-autocomplete` | `multipart/form-data`: `file` (PDF/DOCX), plus the same form fields | `{ source_file_name, extracted_text_preview, provider, model, persisted, generated_questions, created_questions }` |

With `persist: true` the questions are saved (they appear in `created_questions` with ids). With `persist: false` they are returned in `generated_questions` for the instructor to review and then save one by one via the create endpoint. Group-section variants are in §6.6.

### 6.6 Quiz group sections

For an `ASSESSMENT` item of type `QUIZ_GROUP`:

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/courses/items/{item_id}/quiz-group/sections` | `{ "title", "order_index"?, "questions_to_ask"? }` | `201` `{ id, title, order_index, questions_to_ask, questions: [] }` |
| `PATCH` | `/courses/quiz-group/sections/{section_id}` | same fields, all optional | `200` |
| `DELETE` | `/courses/quiz-group/sections/{section_id}` | | `200` |
| `POST` | `/courses/quiz-group/sections/{section_id}/questions` | question (as §6.5) | `201` question |
| `POST` | `/courses/quiz-group/sections/{section_id}/ai-generate` | as §6.5 | |
| `POST` | `/courses/quiz-group/sections/{section_id}/ai-autocomplete` | as §6.5 (multipart) | |

- `questions_to_ask` = how many questions to draw at random from the section's pool per attempt. `null` = ask every question.
- Update/delete questions and options with the §6.5 endpoints.
- Learners never see the pool in advance; only the count.

### 6.7 Reading the whole tree

`GET /courses/manage/{id}` returns `sections[]` in editor format (includes answers):

```json
{
  "id": "s1…", "course_id": "4f42…", "title": "Module 1", "order_index": 0,
  "guest_instructors": [{ "name": "Dr Guest Speaker", "is_guest": true, "profile_picture_url": "…" }],
  "items": [
    { "id": "i1…", "section_id": "s1…", "title": "Welcome", "item_type": "VIDEO", "order_index": 0,
      "is_preview": true, "estimated_minutes": 8,
      "video": { "status": "READY", "bunny_video_guid": "b1f2…", "playback_url": "…", "thumbnail_url": "…", "duration_seconds": 480 } },
    { "id": "i2…", "title": "Referral template", "item_type": "DOCUMENT", "order_index": 1,
      "document": { "file_name": "referral-template.docx", "storage_key": "…", "mime_type": "…", "file_size_bytes": 20480, "is_uploaded": true, "downloadable": false } },
    { "id": "i3…", "title": "Statutory guidance", "item_type": "LINKS", "order_index": 2,
      "link": { "url": "https://example.org/guidance", "label": "Read online", "description": "…" } },
    { "id": "i4…", "title": "Case discussion", "item_type": "LIVE_SESSION", "order_index": 3,
      "live_session": { "scheduled_start_at": "2026-11-05T14:00:00Z", "duration_minutes": 90, "guest_name": "Dr Guest Speaker", "status": "SCHEDULED" } },
    { "id": "i5…", "title": "Knowledge check", "item_type": "ASSESSMENT", "order_index": 4,
      "assessment": { "id": "a1…", "assessment_type": "QUIZ", "due_date": null, "is_final_assessment": false,
        "quiz": { "max_attempts": 3, "pass_mark_percentage": 70, "show_result_to_student": true,
          "questions": [ { "id": "q1…", "text": "…", "order_index": 0, "allow_multiple_answers": false,
            "options": [ { "id": "o1…", "text": "Everyone", "order_index": 0, "is_correct": true } ] } ] } } }
  ]
}
```

- `essay` assessments have `essay: { question, description, submission_mode, pass_mark_percentage, max_attempts, requires_moderation }`; quiz groups have `quiz_group: { …settings, time_limit_seconds, sections: [{ id, title, order_index, questions_to_ask, questions: [...] }] }`.
- A **learner-format** rendering of the same content (no answers) is `GET /governance/revisions/{id}/preview` (§7.3).

---

## 7. Instructor review workflow

### 7.1 Find or open the revision

| Call | Purpose |
|---|---|
| `GET /courses/{course_id}/governance` | Lifecycle, current version, layer, and the `open_revision` summary (if any) |
| `POST /courses/{course_id}/revisions` → `201` | Open (or return) the working copy / initial draft **without editing anything**. Idempotent. `409` if governance is off. |
| `GET /courses/{course_id}/revisions` | Every revision of the course, newest first (open, published, rejected, withdrawn) |
| `GET /governance/revisions/{revision_id}` | Full detail (§7.2) |

Revision summary (also the shape of `open_revision`):

```json
{ "id": "7c0d…", "course_id": "4f42…", "course_title": "Child Protection Essentials", "kind": "INITIAL",
  "status": "DRAFT", "round": 0, "author": { "id": "5bf9…", "name": "Ike Okafor" },
  "created_at": "…", "is_editable": true }
```

When does `open_revision` exist?
- **Published course:** after the first academic edit or curriculum write (or `POST …/revisions`).
- **Never-published course:** after the first curriculum write or academic edit (or `POST …/revisions`).

### 7.2 Revision detail — `GET /governance/revisions/{revision_id}`

```json
{
  "data": {
    "id": "7c0d…", "course_id": "4f42…", "course_title": "Child Protection Essentials",
    "kind": "INITIAL", "status": "QA_REVIEW", "current_stage": "QA_REVIEW", "round": 1,
    "author": { "id": "5bf9…", "name": "Ike Okafor" },
    "computed_risk": "HIGH", "effective_risk": "HIGH", "declared_risk": "HIGH",
    "risk_flags": ["SAFEGUARDING"],
    "risk_reasons": ["HIGH · New course", "HIGH · Flagged safeguarding", "MEDIUM · Module 1: section added"],
    "touches_assessment": true,
    "required_stages": ["ACADEMIC_REVIEW", "ASSESSMENT_MODERATION", "QA_REVIEW", "COURSE_LEAD_APPROVAL", "FINAL_APPROVAL"],
    "proposed_version_label": "1.0",
    "change_summary": "First release of the safeguarding course", "reason": "Required for 2026 intake",
    "submitted_at": "…", "is_editable": false,
    "contributors": [{ "id": "5bf9…", "name": "Ike Okafor" }],
    "stages": [
      { "id": "…", "round": 1, "stage": "ACADEMIC_REVIEW", "sequence": 1, "status": "APPROVED",
        "assigned_reviewer": { "id": "…", "name": "Dr Amaka" }, "decided_by": { "id": "…", "name": "Dr Amaka" },
        "decided_at": "…", "due_at": "…", "conditions": [], "is_overdue": false },
      { "id": "…", "round": 1, "stage": "ASSESSMENT_MODERATION", "sequence": 2, "status": "APPROVED_WITH_CONDITIONS",
        "conditions": [{ "text": "Add feedback to Q3", "stage": "ASSESSMENT_MODERATION", "by": "…", "at": "…" }], "is_overdue": false },
      { "id": "…", "round": 1, "stage": "QA_REVIEW", "sequence": 3, "status": "IN_REVIEW", "assigned_reviewer": { "id": "…", "name": "Queen" }, "is_overdue": false },
      { "id": "…", "round": 1, "stage": "COURSE_LEAD_APPROVAL", "sequence": 4, "status": "PENDING", "is_overdue": false },
      { "id": "…", "round": 1, "stage": "FINAL_APPROVAL", "sequence": 5, "status": "PENDING", "is_overdue": false }
    ],
    "decisions": [
      { "id": "…", "created_at": "…", "stage": "ACADEMIC_REVIEW", "round": 1, "decision": "APPROVED",
        "actor": { "id": "…", "name": "Dr Amaka" }, "comment": "Accurate", "conditions": [],
        "from_status": "SUBMITTED_FOR_REVIEW", "to_status": "ACADEMICALLY_APPROVED", "version_label": "1.0" }
    ],
    "open_conditions": [{ "text": "Add feedback to Q3", "stage": "ASSESSMENT_MODERATION" }],
    "available_actions": ["WITHDRAW", "COMMENT", "ATTACH_EVIDENCE"],
    "blocked_reason": null
  }
}
```

How to read it:
- **`stages` includes every round.** For the current stepper filter `round === revision.round`; earlier rounds are history.
- **Stage `status`:** `PENDING`, `IN_REVIEW` (claimed or assigned), `APPROVED`, `APPROVED_WITH_CONDITIONS`, `RETURNED`, `REJECTED`, `SKIPPED` (force-approved past, or no longer required), `SUPERSEDED` (replaced after a return or escalation). Don't draw `SUPERSEDED` stages in the current stepper.
- **`decision`:** `APPROVED`, `APPROVED_WITH_MINOR_CHANGES`, `RETURNED_FOR_REVISION`, `REJECTED`, `ESCALATED`, `FORCE_APPROVED`.
- **`open_conditions`:** minor changes from an earlier "approve with minor changes" that no later stage has signed off yet. The next reviewer must confirm them.
- **`available_actions`** is computed for the caller. Possible values: `EDIT`, `DISCARD`, `SUBMIT`, `WITHDRAW`, `CLAIM`, `APPROVE`, `APPROVE_WITH_MINOR_CHANGES`, `RETURN_FOR_REVISION`, `REJECT`, `ESCALATE`, `ASSIGN_REVIEWER`, `FORCE_APPROVE`, `OVERRIDE_RISK`, `PUBLISH`, `COMMENT`, `ATTACH_EVIDENCE`.
  - For the **author**: `EDIT`, `DISCARD`, `SUBMIT` while editable; `WITHDRAW` while in review; `COMMENT`, `ATTACH_EVIDENCE` while open.
- **`blocked_reason`** explains why decision actions are missing, e.g. *"You contributed to this revision, so you can't approve any stage of it"*.

### 7.3 Review the work before submitting

All allowed for anyone who can edit or review the course.

| Call | Returns |
|---|---|
| `GET /governance/revisions/{id}/diff` | Every change vs the live course (a new course: everything is `ADDED`), each tagged with its risk |
| `GET /governance/revisions/{id}/preview` | The working copy in **learner format** (no answers), the same shape as a learner's course detail sections. Render it with the learner course-detail component. |
| `GET /governance/revisions/{id}/tree` | The working copy in **editor format** (same shape as `sections` in §6.7) |

Diff:

```json
{ "data": {
  "revision_id": "7c0d…", "computed_risk": "MEDIUM", "touches_assessment": false,
  "reasons": ["MEDIUM · Module 2 › Case study: item added"], "is_live_computation": true,
  "changes": [
    { "entity": "item", "key": "a1b2…", "op": "ADDED", "label": "Module 2 › Case study",
      "fields": ["title", "order_index"], "after": { "title": "Case study", "order_index": 2 }, "item_type": "LINKS", "risk": "MEDIUM" },
    { "entity": "option", "key": "e5f6…", "op": "MODIFIED",
      "label": "Module 1 › Knowledge check › Q: Who is responsible… › Only managers",
      "fields": ["is_correct"], "before": { "is_correct": false }, "after": { "is_correct": true }, "risk": "HIGH" }
  ] } }
```

- `entity`: `course`, `section`, `item`, `video`, `document`, `link`, `assessment`, `assessment_settings`, `group_section`, `question`, `option`.
- `op`: `ADDED`, `REMOVED`, `MODIFIED`, `MOVED`. `label` is a readable path.
- `key` is the **live id** of the thing changed; use it to anchor comments (§7.7).
- While the revision is editable the diff is computed live (`is_live_computation: true`); after submission it shows the recorded diff.
- Render grouped by `label`, an `op` badge, a before → after view, and a `risk` chip. Show `computed_risk` and `reasons` at the top so the instructor sees why a review will be heavier.

### 7.4 Editing UI rules

- If `governance.layer === "draft"` (published course with a working copy) show: **"You're editing a draft (v{proposed_version_label}). Learners still see v{current_version_label}."** with a **View live version** toggle (`?layer=live`).
- If the revision is not editable (`is_editable: false`) make the whole editor read-only and show **Withdraw to edit**.
- Lock the editor on `409` responses, show the API message, and offer **Withdraw to edit**.

### 7.5 Submit — `POST /governance/revisions/{revision_id}/submit`

Requires `SUBMIT_FOR_REVIEW`. Allowed from `DRAFT` or `RETURNED_FOR_REVISION`.

```json
{
  "change_summary": "First release of the safeguarding course",
  "reason": "Required for the 2026 intake",
  "declared_risk": "HIGH",
  "flags": ["SAFEGUARDING"]
}
```

| Field | Required | Notes |
|---|---|---|
| `change_summary` | ✅ | 5–5000 chars; shown to reviewers |
| `reason` | | Why the change is needed (≤ 5000) |
| `declared_risk` | | `LOW`/`MEDIUM`/`HIGH`; only takes effect if higher than the computed risk |
| `flags` | | Any of `SAFEGUARDING`, `LEGAL`, `POLICY`, `CERTIFICATE_RULE`, `CPD_RECOGNITION`; any flag means HIGH |

**Submit dialog:** What is this? (summary) · Why? (reason) · flag checkboxes · optional "Treat as higher risk".

Response: revision detail (§7.2) with `status: "SUBMITTED_FOR_REVIEW"` (or a later status for a LOW quick approval that a reviewer claims), `round` increased by one, `required_stages`, `proposed_version_label`, and each stage's `due_at`.

After submit, show:
- the risk badge and `risk_reasons`;
- the stage stepper;
- "Submitted for review. Version {proposed_version_label} will be published once approved."

Validation errors:
- `400` "Course must have at least one curriculum item before review" (new courses);
- `400` "There are no changes to submit" (published courses);
- `403` "You can't submit this course for review";
- `409` "This revision is {status}, not a draft";
- `409` "This course is not published" (a `CHANGE` revision whose course isn't published);
- `422` (summary too short).

### 7.6 While it's in review

| Call | Effect |
|---|---|
| `GET /governance/revisions/{id}` | Poll or open from a notification to refresh the stepper |
| `POST /governance/revisions/{id}/withdraw` | Pull it out of review back to `DRAFT` (editable again). Open stages are marked `SUPERSEDED`, so **reviewers start again** on resubmission. Allowed for contributors and anyone with `SUBMIT_FOR_REVIEW`. `409` if it isn't in review. |
| `POST /governance/revisions/{id}/discard` | Abandon the draft (`WITHDRAWN`). A published course's live content is untouched. Only from `DRAFT` / `RETURNED_FOR_REVISION` (otherwise `409` "withdraw it from review first"). Requires edit permission. Confirm first. |

For a never-published course, discarding the revision does **not** delete the course's content (it is the course); the next edit opens a new `INITIAL` revision.

### 7.7 Comments and evidence

Reviewers and the author discuss a revision here. Comments are visible to everyone involved and are allowed while the revision is open.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/governance/revisions/{id}/comments` | Flat list; build threads from `parent_id` |
| `POST` | `/governance/revisions/{id}/comments` → `201` | `{ "body", "parent_id"?, "anchor_type"?: "course"\|"section"\|"item"\|"question", "anchor_id"? }` |
| `PATCH` | `/governance/comments/{comment_id}/resolve` | Marks resolved |
| `GET` | `/governance/revisions/{id}/evidence` | Files carry a short-lived `download_url` |
| `POST` | `/governance/revisions/{id}/evidence/upload-url` | `{ "title", "file_name", "content_type"? }` → `{ evidence_id, upload_url, storage_key }`; `PUT` the file to `upload_url` |
| `POST` | `/governance/evidence/{evidence_id}/finalize` | `{ "mime_type"?, "file_size_bytes"? }` |
| `POST` | `/governance/revisions/{id}/evidence/link` → `201` | `{ "title", "url" }` |

Comment:

```json
{ "id": "c1…", "created_at": "…", "revision_id": "7c0d…", "stage_id": "…", "parent_id": null,
  "author": { "id": "…", "name": "Dr Amaka" }, "body": "Please cite the 2026 code",
  "anchor_type": "item", "anchor_id": "c3d4…", "resolved_at": null }
```

Pin an anchored comment next to the matching module, lesson or question by matching `anchor_id` to the live id (the diff `key`).

### 7.8 Returned for revision

1. The author gets a `REVISION_RETURNED` notification, and the revision appears in **Inbox → Returned to me**.
2. The revision has `status: "RETURNED_FOR_REVISION"`, `is_editable: true`, and `decisions[last].comment` holding the reviewer's reason. Show a banner: *"Changes requested by {actor.name}: {comment}"*, with anchored comments beside their targets.
3. The editor unlocks (no `409`). The instructor fixes things, replies and resolves comments.
4. Resubmit with `POST …/submit`. `round` increments, and all stages restart from the first one. Earlier rounds remain visible as history.

### 7.9 Rejected

`status: "REJECTED"` is terminal for that revision. The reviewer's comment is in `decisions[last].comment`, and the author gets `REVISION_REJECTED`. For a **new** course the content stays on the course, so the instructor can improve it and a new `INITIAL` revision opens on the next edit. For a **published** course the working copy is discarded and the live version is untouched; a new edit starts a fresh working copy.

### 7.10 Published

On publish (§8.6) the instructor gets `REVISION_PUBLISHED`; `status` is `PUBLISHED`, the course shows `governance_status: "PUBLISHED"` and `current_version_label` (for example `1.0`), and learners can see and enroll in it.

---

## 8. Reviewer and approver workflows, role by role

### 8.1 Common to all reviewers: the Approval Centre

`GET /governance/approval-centre?view={view}&kind={COURSE_REVISION|ESSAY_MARK}&course_id=&page=&page_size=` (paginated). Available to anyone with a content, review, marking or publishing permission.

| `view` | Shows |
|---|---|
| `awaiting_me` (default) | Stages you can decide now (you hold the permission, it's unassigned or assigned to you, and separation of duties allows it) |
| `returned_to_me` | Revisions returned to you as a contributor |
| `overdue` | Past-due stages you can decide, plus (Course Lead / Head of Learning) everything overdue on courses they lead |
| `ready_to_publish` | Fully approved revisions (needs `PUBLISH_CONTENT`) |
| `recently_approved` / `recently_rejected` | Last 30 days, on your decisions or your work (`decision` and `reviewer` identify who decided) |
| `my_drafts` | Your open drafts |

Row:

```json
{ "kind": "COURSE_REVISION", "id": "7c0d…", "item_title": "Child Protection Essentials", "item_type": "Course",
  "course_id": "4f42…", "course_title": "Child Protection Essentials",
  "submitted_by": { "id": "5bf9…", "name": "Ike Okafor" },
  "current_stage": "ACADEMIC_REVIEW", "status": "SUBMITTED_FOR_REVIEW",
  "reviewer": { "id": "…", "name": "Dr Amaka" }, "due_at": "2026-10-08T09:00:00Z", "is_overdue": false,
  "risk": "HIGH", "version_label": "1.0",
  "available_actions": ["CLAIM", "APPROVE", "APPROVE_WITH_MINOR_CHANGES", "RETURN_FOR_REVISION", "REJECT", "ESCALATE"] }
```

- `item_type`: `Course` (a new course), `Lesson`, `Assessment`, `Course update`, `Rollback`, `Reinstatement`, `Essay mark`, `Essay mark (disputed)`.
- Open views are sorted overdue first, then by soonest due date.
- Open a `COURSE_REVISION` row with `GET /governance/revisions/{id}`; open an `ESSAY_MARK` row with `GET /essay-marks/{id}`.
- Tab badges: `GET /governance/approval-centre/counts` → `{ awaiting_me, returned_to_me, overdue, ready_to_publish }`.

### 8.2 The review screen (all reviewers)

Recommended layout, using the calls in §7:
1. **Header:** `GET /governance/revisions/{id}`: title, `status`, `current_stage`, risk with `risk_reasons`, `proposed_version_label`, `change_summary` / `reason`, and the stage timeline from `stages` (with `is_overdue` and who decided each).
2. **What changed:** `GET …/diff`, grouped by `label` with risk chips. A new course shows everything as `ADDED`.
3. **Preview:** `GET …/preview` (learner view). Use `GET …/tree` when you need to see correct answers.
4. **Conditions:** show `open_conditions` for this reviewer to confirm.
5. **Discussion:** comments (anchored) and evidence.
6. **Decision bar:** buttons from `available_actions`; if no decision actions are present show `blocked_reason`.

Reviewers do **not** need edit rights to open these; they're allowed by their review permission for that course.

| Button | Call |
|---|---|
| Claim | `POST /governance/revisions/{id}/claim` |
| Approve / Approve with minor changes / Return / Reject / Escalate | `POST /governance/revisions/{id}/decision` |
| Assign reviewer | `POST /governance/revisions/{id}/assign` |
| Force approve | `POST /governance/revisions/{id}/force-approve` |
| Re-rate risk | `POST /governance/revisions/{id}/risk` |
| Publish | `POST /governance/revisions/{id}/publish` |

Every action returns the updated revision detail; re-render from the response.

### 8.3 Claim, assign and decide (the core actions)

**Claim** — `POST /governance/revisions/{id}/claim` (no body). Takes the current unassigned stage into review (status becomes the matching `*_REVIEW` label). The same rules as deciding apply, so nobody can claim what they couldn't approve. `403` if assigned to someone else.

**Assign** — `POST /governance/revisions/{id}/assign`

```json
{ "reviewer_id": "…", "due_at": "2026-10-10T09:00:00Z" }
```

- A **Course Lead** or **Head of Learning** can assign any eligible, active user to the current stage; anyone else may only assign **themselves** (that is a claim).
- The assignee must be able to decide the stage (permission + separation of duties); otherwise `403`/`400`.
- `due_at` is optional and overrides the SLA due date. The assignee gets `REVIEW_ASSIGNED`.
- Once assigned, **only the assignee** can decide the stage.

**Decide** — `POST /governance/revisions/{id}/decision`

```json
{ "decision": "APPROVED_WITH_MINOR_CHANGES", "comment": "Fine overall", "conditions": ["Add feedback to Q3"], "escalate_to": null, "flags": [] }
```

| `decision` | Required | Effect |
|---|---|---|
| `APPROVED` | | Advances to the next stage |
| `APPROVED_WITH_MINOR_CHANGES` | `conditions` (non-empty list) | Advances; the conditions show in `open_conditions` for the next reviewer to confirm |
| `RETURNED_FOR_REVISION` | `comment` | Back to the author for fixes; the round ends |
| `REJECTED` | `comment` | Terminal. A published course's working copy is discarded. |
| `ESCALATED` | `comment`, plus `escalate_to` (a higher level) and/or `flags` | Raises the risk and inserts the extra stages (a quick approval becomes the full path); the version label is recalculated. `400` if it neither raises the level nor adds a flag. |

`FORCE_APPROVED` is rejected here (`400`); use the force-approve endpoint.

**Separation of duties (enforced on claim, assign and decide; the reason comes back as a `403` message and in `blocked_reason`):**
1. You must hold the stage's permission **for that course** (platform-wide or course-scoped).
2. You must not be a **contributor** (the author, or anyone who edited the working copy).
3. You must not have approved a **different** stage of the same revision (across all rounds).
4. If the stage is assigned, you must be the assignee.

When the last required stage is approved the status becomes `READY_TO_PUBLISH` and publishers are notified.

### 8.4 Role by role

#### Academic Reviewer (`ACADEMIC_REVIEW`)
- **Decides:** the `ACADEMIC_REVIEW` stage (first stage on every MEDIUM/HIGH revision).
- **Looks for:** accuracy, learning outcomes, relevance and appropriateness of content.
- **Typical flow:** Inbox → *Awaiting me* → open → diff + preview → *Claim* → comment on specific lessons → *Approve* / *Approve with minor changes* / *Return* / *Reject* / *Escalate* (for example, raise to HIGH and flag `SAFEGUARDING`).
- **Cannot:** review something they edited, or also approve a second stage of the same revision.

#### Assessment Moderator (`MODERATE_ASSESSMENT`)
- **Decides:** the `ASSESSMENT_MODERATION` stage, which is present only when a MEDIUM/HIGH change touches an assessment.
- **Looks for:** question quality, correct answers (use `GET …/tree` to see `is_correct`), pass mark, attempts and time limits, essay prompt and `requires_moderation` setting.
- **Also:** moderates essay marks (§11). Needs no content-editing rights.

#### QA Reviewer (`QA_REVIEW`)
- **Decides:** the `QA_REVIEW` stage, and the single `QUICK_APPROVAL` stage for LOW-risk changes and reinstatements.
- **Looks for:** structure, consistency, broken links, missing uploads (documents `is_uploaded`, videos `READY`), formatting and previews.
- **Quick approval:** approving it makes the revision `READY_TO_PUBLISH` immediately.

#### Course Lead (`APPROVE_COURSE`; platform-wide or scoped to specific courses)
- **Decides:** `COURSE_LEAD_APPROVAL`, and may also decide `QUICK_APPROVAL`.
- **Also can:** assign reviewers and set due dates (§8.3); see everything overdue on their courses (`view=overdue`); **start a rollback** (§10.2); approve essay results.
- A Course Lead who also edited the course cannot approve it.

#### Head of Learning (`FINAL_APPROVAL`, `FORCE_APPROVE`)
- **Decides:** `FINAL_APPROVAL`, required for HIGH-risk revisions (all new courses, assessment/outcome/certificate changes, flagged changes).
- **Force approve:** `POST /governance/revisions/{id}/force-approve` with `{ "justification": "…" }` (≥ 20 characters). Every remaining open stage becomes `SKIPPED`, and the revision goes to `READY_TO_PUBLISH`. Audited, and contributors are notified. Not allowed on one's own work.
- **Re-rate risk:** `POST /governance/revisions/{id}/risk` with `{ "level": "MEDIUM", "reason": "…" }` (reason ≥ 10). Stages no longer needed are `SKIPPED`; added ones are `PENDING`; the version label is recalculated. A flagged revision must stay `HIGH` (`400`). Not allowed on one's own work.
- **Also can:** assign reviewers, start a rollback.

#### Platform Administrator (`PUBLISH_CONTENT`, `ARCHIVE_CONTENT`, `MANAGE_STAFF_ROLES`)
- **Publishes** (§8.6), **archives/reinstates** (§10.3), **grants staff roles** (§8.7), and reads the audit trail (§8.8).
- **Makes no academic decisions:** an Admin holds none of the review permissions unless they are explicitly granted a reviewer role. If an admin edits a course, they become a contributor to that revision and can't approve it.

### 8.5 Which role decides which stage

| Stage | Who can decide (permission) | Role(s) |
|---|---|---|
| `QUICK_APPROVAL` | `QA_REVIEW` **or** `APPROVE_COURSE` | QA Reviewer, Course Lead |
| `ACADEMIC_REVIEW` | `ACADEMIC_REVIEW` | Academic Reviewer |
| `ASSESSMENT_MODERATION` | `MODERATE_ASSESSMENT` | Assessment Moderator |
| `QA_REVIEW` | `QA_REVIEW` | QA Reviewer |
| `COURSE_LEAD_APPROVAL` | `APPROVE_COURSE` | Course Lead |
| `FINAL_APPROVAL` | `FINAL_APPROVAL` | Head of Learning |
| *Publish* | `PUBLISH_CONTENT` | Platform Admin |

Reviewer notifications go to everyone eligible for the next stage, excluding contributors and anyone who already signed off a different stage.

### 8.6 Publish — `POST /governance/revisions/{id}/publish`

Requires `PUBLISH_CONTENT`. Succeeds only from `READY_TO_PUBLISH` (`409` otherwise, naming the actual status). It:
- **merges the working copy into the live course in place.** Module, lesson, question and option ids do not change, so learner progress, quiz attempts, essay submissions and certificates stay attached;
- applies any held course-field edits;
- sets `is_published: true`, `governance_status: PUBLISHED` and `current_version_label`;
- records a new **version** with a full content snapshot, author, reviewers, approval date and reason;
- clears caches, recalculates enrolled learners' progress if the set of lessons changed (a new lesson un-completes a finished learner; a removed one can complete them), and sends invitations for newly published live sessions.

Response: revision detail with `status: "PUBLISHED"`, `published_at`, `published_version_id`. The message reads *"Published version 1.0"*.

**Legacy toggle:** `PATCH /courses/{id}/publish?is_published=true` still works for a publisher. It publishes the open revision only if it's `READY_TO_PUBLISH`, otherwise `409` naming the stage it's waiting on. `is_published=false` archives the course. Prefer the explicit publish and archive endpoints.

### 8.7 Granting roles (Platform Admin, `MANAGE_STAFF_ROLES`)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/admin/staff-roles?user_id=&role=&course_id=&include_revoked=` | List grants |
| `POST` | `/admin/staff-roles` | `{ "user_id", "role", "course_id"?, "reason"?, "expires_at"? }`. Omit `course_id` for a platform-wide grant. `409` if the user already holds that role in that scope. |
| `POST` | `/admin/staff-roles/{assignment_id}/revoke` | `{ "reason"? }`. The row is kept as history. |

`role` is one of `INSTRUCTOR`, `CONTENT_DEVELOPER`, `ACADEMIC_REVIEWER`, `ASSESSMENT_MODERATOR`, `QA_REVIEWER`, `COURSE_LEAD`, `LEAD_ASSESSOR`, `HEAD_OF_LEARNING`, `PLATFORM_ADMIN`. Grants and revocations are audited and send the user a `ROLE_CHANGED` notification; the user's `access` should be refreshed (`GET /users/me`). For each revision to be reviewable, at least one eligible, non-contributor user must hold each required role (platform-wide or on that course).

### 8.8 Audit trail

`GET /governance/audit?course_id=&revision_id=&actor_id=&entity_type=&entity_id=&from=&to=` (paginated; requires `FINAL_APPROVAL`, `PUBLISH_CONTENT` or `MANAGE_STAFF_ROLES`). Each row: `occurred_at`, `actor_id`, `actor_permissions`, `entity_type`, `entity_id`, `course_id`, `revision_id`, `version_label`, `action` (for example `SUBMITTED`, `DECISION_APPROVED`, `FORCE_APPROVED`, `PUBLISHED`, `COURSE_ARCHIVED`, `STAFF_ROLE_GRANTED`), `from_status`, `to_status`, `comment`, `metadata_json`. Append-only.

---

## 9. End-to-end scenarios

### Scenario A — A brand-new course (HIGH risk, full path)

| # | Who | Action | Call |
|---|---|---|---|
| 1 | Instructor | Creates the course | `POST /courses` |
| 2 | Instructor | Opens the draft revision (idempotent) | `POST /courses/{id}/revisions` → `kind: INITIAL`, `DRAFT` |
| 3 | Instructor | Adds modules, items, quizzes, uploads media | §6 |
| 4 | Instructor | Reviews and previews | `GET …/diff`, `GET …/preview` |
| 5 | Instructor | Submits | `POST …/submit` → stages: Academic → (Moderation) → QA → Course Lead → Final |
| 6 | Academic Reviewer | Claims, approves | `POST …/claim`, `POST …/decision {APPROVED}` |
| 7 | Assessment Moderator | (if any assessment) approves | `POST …/decision` |
| 8 | QA Reviewer | Approves | `POST …/decision` |
| 9 | Course Lead | Approves | `POST …/decision` |
| 10 | Head of Learning | Final approval → `READY_TO_PUBLISH` | `POST …/decision` |
| 11 | Platform Admin | Publishes | `POST …/publish` → v1.0, course live |

### Scenario B — A small fix to a live course (LOW risk)

1. Instructor edits a lesson title: `PATCH /courses/items/{item_id}`. The working copy opens silently.
2. Instructor opens the diff (LOW) and submits with a short summary.
3. One QA Reviewer **or** Course Lead approves `QUICK_APPROVAL` → `READY_TO_PUBLISH`.
4. Platform Admin publishes → v1.1.

### Scenario C — Returned and resubmitted

1. A reviewer decides `RETURNED_FOR_REVISION` with a comment.
2. The instructor gets `REVISION_RETURNED`, opens the revision, sees the comment and anchored threads.
3. The editor is unlocked; the instructor fixes things and resubmits. `round` becomes 2 and all stages restart.

### Scenario D — An assessment change

1. Instructor changes a correct option or a pass mark: HIGH, touches an assessment.
2. Stages: Academic → **Assessment Moderation** → QA → Course Lead → Final Approval. The proposed version is a **major** bump (for example `2.0`).

### Scenario E — Reviewer escalates

1. An Academic Reviewer on a MEDIUM revision spots a safeguarding issue and decides `ESCALATED` with `escalate_to: "HIGH"`, `flags: ["SAFEGUARDING"]` and a comment.
2. `FINAL_APPROVAL` is inserted; contributors get `REVISION_ESCALATED`; the version label is recalculated.

### Scenario F — Head of Learning shortcuts

- **Override risk down:** an over-cautious HIGH on a trivial change is re-rated to LOW or MEDIUM with a reason; no-longer-needed stages are `SKIPPED`.
- **Force approve:** in an emergency, with a ≥ 20-character justification; all open stages `SKIPPED`; status `READY_TO_PUBLISH`; audited.

### Scenario G — Instructor changes their mind

- Withdraw while in review → back to `DRAFT`, edit, resubmit (reviewers restart).
- Discard a draft → the working copy is deleted and the live course is unaffected.

---

## 10. After publishing: versions, rollback, archive, reinstate

### 10.1 Versions

| Method | Path | Returns |
|---|---|---|
| `GET` | `/courses/{course_id}/versions` | `1.0, 1.1, 2.0…`, newest first |
| `GET` | `/courses/{course_id}/versions/{version_id}` | The same, plus the full content `snapshot` |
| `GET` | `/courses/{course_id}/revisions` | Every revision (including rejected and discarded) |

```json
{ "id": "v2…", "course_id": "4f42…", "label": "1.1", "major": 1, "minor": 1, "revision_id": "7c0d…",
  "author": { "id": "…", "name": "Ike Okafor" },
  "reviewers": [{ "id": "…", "name": "Dr Amaka" }, { "id": "…", "name": "Queen" }],
  "approved_at": "…", "published_at": "…", "published_by": { "id": "…", "name": "Ada (Admin)" },
  "reason": "New statutory guidance", "risk_level": "MEDIUM", "is_current": true, "has_snapshot": true }
```

Use these for a **History** tab on the course. Courses published before governance existed start at `1.0 (baseline)`; their snapshot is captured the first time they're edited.

### 10.2 Rollback (Course Lead / Head of Learning)

`POST /courses/{course_id}/versions/{version_id}/rollback` with `{ "reason"?: "…" }` → `201` revision detail (`kind: ROLLBACK`).
- Needs `APPROVE_COURSE` or `FINAL_APPROVAL` on the course; the course must be `PUBLISHED`.
- `400` if the target is already the current version, or the live content already matches it.
- Builds a working copy matching that version's snapshot, restoring removed lessons **with their ids** (and learner progress).
- The only stage is `FINAL_APPROVAL`, from someone other than whoever started it. Publishing creates a **new** minor version (for example `2.1`), not a rewrite of history.

### 10.3 Archive and reinstate (Platform Admin, `ARCHIVE_CONTENT`)

| Method | Path | Body | Effect |
|---|---|---|---|
| `POST` | `/courses/{course_id}/archive` | `{ "reason"? }` | Hides the course from learners (`is_published: false`, lifecycle `ARCHIVED`). Any open revision is withdrawn. Versions and history are kept. Only a `PUBLISHED` course (`409` otherwise). |
| `POST` | `/courses/{course_id}/reinstate` | `{ "reason"? }` | Creates a LOW-risk `REINSTATE` revision: quick approval, then publish. Only an `ARCHIVED` course. |

An archived course is read-only for instructors: writes return `409` "This course is archived - reinstate it before editing".

---

## 11. Essay marking (summary)

Final-assessment essays use a marker → moderator → approver path so learners only ever see approved results. Full reference: [`../phase_3/ESSAY_MODERATION_API.md`](../phase_3/ESSAY_MODERATION_API.md).

| Who | Call |
|---|---|
| Instructor (marker) lists submissions | `GET /courses/items/{item_id}/essay/submissions` (adds `result_status`, `current_mark_id`, `working_score`) |
| Marker saves a draft / sends to moderation | `POST /courses/items/{item_id}/essay/submissions/{user_id}/grade` `{ score, feedback?, recommendation?: "PASS"\|"FAIL", submit_for_moderation? }` |
| Marker sends a saved draft | `POST /essay-marks/{mark_id}/submit` |
| Moderator | `POST /essay-marks/{mark_id}/moderate` `{ action: "APPROVE"\|"AMEND"\|"RETURN", score?, feedback?, note? }` |
| Marker contests an amendment | `POST /essay-marks/{mark_id}/dispute` `{ note }` |
| Approver (Course Lead / Lead Assessor / Head of Learning) | `POST /essay-marks/{mark_id}/approve`, `POST /courses/items/{item_id}/essay-marks/publish` |
| Anyone involved | `GET /essay-marks/{mark_id}`, `GET /courses/items/{item_id}/essay-marks`, `GET /courses/items/{item_id}/essay/submissions/{user_id}/marks` |

Statuses: `DRAFT_MARK → AWAITING_MODERATION → MODERATED → APPROVED → PUBLISHED` (plus `RETURNED_TO_MARKER`, `SUPERSEDED`). A moderated essay needs `requires_moderation: true` (default for final assessments). The **setting itself** is course content and goes through content review like any other assessment setting. Rows from both flows appear together in the Approval Centre (`kind=ESSAY_MARK`).

---

## 12. Notifications

Delivered through the existing notification list and websocket ([`../phase_3/NOTIFICATIONS_ADMIN_API.md`](../phase_3/NOTIFICATIONS_ADMIN_API.md)). Links are `/dashboard/approval-centre/revisions/{id}` (or `/marks/{id}`); route them inside the app. `metadata_json` carries `revision_id`, `course_id` or `mark_id` as strings.

| `type` | Recipients | Instructor action |
|---|---|---|
| `REVIEW_REQUESTED` | Reviewer pool for the next stage (excluding contributors and prior sign-offs), or just the assignee | (reviewer) open the revision |
| `REVIEW_ASSIGNED` | The assignee | (reviewer) open the revision |
| `REVISION_STAGE_APPROVED` | Contributors | Refresh the stepper |
| `REVISION_RETURNED` | Contributors | Open the revision; editing is unlocked |
| `REVISION_REJECTED` | Contributors | Show the reason |
| `REVISION_ESCALATED` | Contributors | Refresh the stages |
| `REVISION_FORCE_APPROVED` | Contributors | Refresh |
| `REVISION_READY_TO_PUBLISH` | Publishers | (admin) open the revision and publish |
| `REVISION_PUBLISHED` | Contributors and reviewers (not the publisher) | Show the live version |
| `REVIEW_COMMENT_ADDED` | Everyone involved | Open the comments |
| `ROLE_CHANGED` | The user | Refresh `GET /users/me` |
| `MARKS_AWAITING_MODERATION`, `MARKS_RETURNED`, `MARKS_AWAITING_APPROVAL`, `MARKS_DISPUTED` | Moderators / marker / approvers | Open the mark |

---

## 13. Errors

| Status | Typical message | What the UI should do |
|---|---|---|
| `400` | "There are no changes to submit" / "Course must have at least one curriculum item before review" | Inline in the submit dialog |
| `400` | "A comment explaining the decision is required" / "List the minor changes the next stage must confirm" / "Escalate to a higher risk level or add a flag" | Make the field required |
| `400` | "file_name is required for document items", "url is required for link items", "scheduled_start_at is required for live session items", "scheduled_start_at must be in the future", "assessment_type is required for assessment items", "essay_settings is required for essay assessments" | Field-level errors on the item form |
| `400` | "This section already has a final assessment" | Offer to unset the other one |
| `400` | "multi_answer_mode can only be set when allow_multiple_answers is true" | Hide the control for single-answer questions |
| `400` | "This live session can no longer be edited" | Disable the form once the session has started |
| `403` | "You can't submit this course for review" / "Missing permission …" | Hide the control; refresh `access` |
| `403` | "You contributed to this revision, so you can't approve any stage of it" | Info message; never show approve buttons on own work |
| `403` | "You already approved another stage of this revision (…); an independent reviewer must decide this one" | Info message |
| `403` | "This stage is assigned to another reviewer" | Show the assignee |
| `403` | "Publishing requires PUBLISH_CONTENT" | Hide Publish |
| `404` | "…not found in the working copy (it may have been removed)" | Re-fetch the manage tree |
| `409` | "This course's changes are under review (…) and can't be edited. Withdraw the revision from review…" | Read-only banner with **Withdraw to edit** |
| `409` | "This course is archived - reinstate it before editing" | Archived banner; disable editing |
| `409` | "This revision is … not a draft" / "This revision is not in review" / "Only a revision that is READY_TO_PUBLISH can be published" | Re-fetch the revision and re-render |
| `409` | "Content governance is not enabled" | Fall back to classic mode (§14) |
| `422` | Validation error (for example `change_summary` too short, `SCHEDULED` access without dates) | Show `errors[]` per field |

Every action returns the up-to-date state on success, so on any `409` or `403` after an action, **re-fetch the revision** and re-render rather than guessing.

---

## 14. When governance is switched off

When `access.governance_enabled === false`:
- Instructors publish and unpublish with `PATCH /courses/{id}/publish?is_published=true|false`. Publishing needs at least one curriculum item (`400` otherwise).
- Edits go live immediately. There is no working copy (`governance.layer` is always `"live"`), no submit/review/stepper, and `POST /courses/{id}/revisions` returns `409`.
- Admins keep every permission.
- Each publish still records a **version**, so the History tab works.
- Essay grading is one step (`is_published` is honoured).

Build both modes: read the flag from `access` and switch.

---

## 15. Screens and implementation checklist

### 15.1 Screens

**Instructor app**
1. Login → store `access`; build navigation from `capabilities`.
2. **My courses** (`GET /courses/manage`): cards with lifecycle, version, and review badges.
3. **Course editor** with tabs:
   - *Details* (§5.1, §5.4);
   - *Curriculum* (§6): modules, items, uploads, quizzes;
   - *Pricing & access* (live immediately);
   - *Certificate*;
   - *Review & history*.
4. **Review changes** (diff) and **Preview as learner**.
5. **Submit for review** dialog.
6. **Review status**: stepper, reviewers, due dates, comments, **Withdraw**, **Discard**.
7. **Inbox**: *My drafts*, *Returned to me*, *Recently approved/rejected* (and *Awaiting me* for reviewers).
8. **History**: versions and revisions.
9. **Marking** (§11).

**Reviewer / admin screens**
10. **Approval Centre** with tabs and badges (§8.1).
11. **Review screen** (§8.2) with the decision bar.
12. **Ready to publish** list with a Publish button.
13. **Course lifecycle**: archive, reinstate, rollback.
14. **Staff roles** and **Audit trail**.

### 15.2 Checklist

- [ ] Store `access` from login; refresh with `GET /users/me` (§4.2).
- [ ] Branch on `governance_enabled` (§14).
- [ ] Course create/edit form with all fields and `SCHEDULED` access validation (§5).
- [ ] Call `POST /courses/{id}/revisions` right after creating a course (§5.1).
- [ ] Thumbnail upload flow (§5.5).
- [ ] Delete only for `DRAFT` courses, with confirmation (§5.6).
- [ ] Section CRUD with guest lecturers and drag-to-reorder (§6.1).
- [ ] Item forms for all five types, with the correct required fields (§6.2).
- [ ] Resumable video upload (TUS) with `refresh-upload` and processing status (§6.2).
- [ ] Document upload: PUT, then `finalize`, and show incomplete uploads (§6.2).
- [ ] Quiz, essay and quiz-group builders: questions, options, settings, final-assessment rule, AI helpers (§6.2–§6.6).
- [ ] **Re-fetch the manage tree after every write** (§6).
- [ ] Draft banner and **View live version** toggle; read-only editor under review (§7.4).
- [ ] Diff screen and learner preview (§7.3).
- [ ] Submit dialog with summary, reason, flags and raise-risk (§7.5).
- [ ] Stage stepper for the current `round`, with reviewers and due dates (§7.2).
- [ ] Withdraw and discard with confirmations (§7.6).
- [ ] Comments (threaded, anchored, resolvable) and evidence (§7.7).
- [ ] Returned/rejected/published banners (§7.8–§7.10).
- [ ] Approval Centre, counts and the review screen (§8.1–§8.2).
- [ ] Decision bar built only from `available_actions`, with `blocked_reason` (§8.2).
- [ ] Claim, assign, decide, force-approve, re-rate and publish actions with their required fields (§8.3–§8.6).
- [ ] History tab, rollback (permission-gated), archive/reinstate (§10).
- [ ] Notification routing (§12).
- [ ] Error handling per §13.

---

## 16. Appendix: enums and endpoint index

### 16.1 Enums

| Name | Values |
|---|---|
| `level` | `BEGINNER`, `INTERMEDIATE`, `ADVANCED` |
| `category` | `DEVELOPMENT`, `BUSINESS`, `FINANCE_ACCOUNTING`, `IT_SOFTWARE`, `OFFICE_PRODUCTIVITY`, `PERSONAL_DEVELOPMENT`, `DESIGN`, `MARKETING`, `HEALTH_FITNESS`, `MUSIC`, `TEACHING_ACADEMICS`, `PHOTOGRAPHY_VIDEO`, `LIFESTYLE`, `LANGUAGE` |
| `access_mode` | `SELF_PACED`, `SCHEDULED` |
| `item_type` | `ASSESSMENT`, `DOCUMENT`, `VIDEO`, `LINKS`, `LIVE_SESSION` |
| `assessment_type` | `QUIZ`, `ESSAY`, `QUIZ_GROUP` |
| `submission_mode` | `TEXT`, `DOCUMENT` |
| `multi_answer_mode` | `AND`, `OR` |
| `video.status` | `PENDING`, `PROCESSING`, `READY`, `FAILED` |
| `live_session.status` | `SCHEDULED`, `LIVE`, `ENDED`, `CANCELLED` |
| `governance_status` | `DRAFT`, `PUBLISHED`, `ARCHIVED` |
| revision `kind` | `INITIAL`, `CHANGE`, `ROLLBACK`, `REINSTATE` |
| revision `status` | §3.3 |
| `stage` | `QUICK_APPROVAL`, `ACADEMIC_REVIEW`, `ASSESSMENT_MODERATION`, `QA_REVIEW`, `COURSE_LEAD_APPROVAL`, `FINAL_APPROVAL` |
| stage `status` | `PENDING`, `IN_REVIEW`, `APPROVED`, `APPROVED_WITH_CONDITIONS`, `RETURNED`, `REJECTED`, `SKIPPED`, `SUPERSEDED` |
| `decision` | `APPROVED`, `APPROVED_WITH_MINOR_CHANGES`, `RETURNED_FOR_REVISION`, `REJECTED`, `ESCALATED`, `FORCE_APPROVED` |
| risk | `LOW`, `MEDIUM`, `HIGH` |
| risk flags | `SAFEGUARDING`, `LEGAL`, `POLICY`, `CERTIFICATE_RULE`, `CPD_RECOGNITION` |
| AI `provider` | `GEMINI`, `OPENAI`, `DEEPSEEK` |
| permissions | `CREATE_CONTENT`, `EDIT_DRAFT_CONTENT`, `SUBMIT_FOR_REVIEW`, `ACADEMIC_REVIEW`, `QA_REVIEW`, `APPROVE_COURSE`, `FINAL_APPROVAL`, `PUBLISH_CONTENT`, `MARK_ASSESSMENT`, `MODERATE_ASSESSMENT`, `APPROVE_RESULTS`, `ARCHIVE_CONTENT`, `MANAGE_STAFF_ROLES`, `FORCE_APPROVE` |

### 16.2 Endpoint index

**Course**

| Method | Path | § |
|---|---|---|
| `POST` | `/courses` | 5.1 |
| `GET` | `/courses/manage` | 5.2 |
| `GET` | `/courses/manage/{id}` | 5.3 |
| `PATCH` | `/courses/{id}` | 5.4 |
| `POST` | `/courses/manage/{course_id}/thumbnail-upload-url` | 5.5 |
| `DELETE` | `/courses/{id}` | 5.6 |
| `PATCH` | `/courses/{id}/publish?is_published=` | 8.6, 14 |

**Sections and items**

| Method | Path | § |
|---|---|---|
| `POST` | `/courses/{course_id}/sections` | 6.1 |
| `PATCH` | `/courses/{course_id}/sections/{section_id}` | 6.1 |
| `DELETE` | `/courses/{course_id}/sections/{section_id}` | 6.1 |
| `PATCH` | `/courses/{course_id}/sections/reorder` | 6.1 |
| `POST` | `/courses/{course_id}/sections/{section_id}/items` | 6.2 |
| `PATCH` | `/courses/items/{item_id}` | 6.3 |
| `DELETE` | `/courses/items/{item_id}` | 6.3 |
| `PATCH` | `/courses/{course_id}/sections/{section_id}/items/reorder` | 6.3 |
| `POST` | `/courses/items/{item_id}/document/finalize` | 6.2 |
| `POST` | `/courses/items/{item_id}/video/refresh-upload` | 6.2 |
| `PATCH` | `/courses/items/{item_id}/assessment` | 6.4 |

**Quiz**

| Method | Path | § |
|---|---|---|
| `POST` | `/courses/items/{item_id}/quiz/questions` | 6.5 |
| `POST` | `/courses/items/{item_id}/quiz/ai-generate` | 6.5 |
| `POST` | `/courses/items/{item_id}/quiz/ai-autocomplete` | 6.5 |
| `PATCH`, `DELETE` | `/courses/quiz/questions/{question_id}` | 6.5 |
| `POST` | `/courses/quiz/questions/{question_id}/options` | 6.5 |
| `PATCH`, `DELETE` | `/courses/quiz/options/{option_id}` | 6.5 |
| `POST` | `/courses/items/{item_id}/quiz-group/sections` | 6.6 |
| `PATCH`, `DELETE` | `/courses/quiz-group/sections/{section_id}` | 6.6 |
| `POST` | `/courses/quiz-group/sections/{section_id}/questions` | 6.6 |
| `POST` | `/courses/quiz-group/sections/{section_id}/ai-generate` | 6.6 |
| `POST` | `/courses/quiz-group/sections/{section_id}/ai-autocomplete` | 6.6 |

**Governance: author**

| Method | Path | § |
|---|---|---|
| `GET` | `/courses/{course_id}/governance` | 7.1 |
| `POST` | `/courses/{course_id}/revisions` | 7.1 |
| `GET` | `/courses/{course_id}/revisions` | 7.1, 10.1 |
| `GET` | `/governance/revisions/{id}` | 7.2 |
| `GET` | `/governance/revisions/{id}/diff` | 7.3 |
| `GET` | `/governance/revisions/{id}/preview` | 7.3 |
| `GET` | `/governance/revisions/{id}/tree` | 7.3 |
| `POST` | `/governance/revisions/{id}/submit` | 7.5 |
| `POST` | `/governance/revisions/{id}/withdraw` | 7.6 |
| `POST` | `/governance/revisions/{id}/discard` | 7.6 |
| `GET`, `POST` | `/governance/revisions/{id}/comments` | 7.7 |
| `PATCH` | `/governance/comments/{comment_id}/resolve` | 7.7 |
| `GET` | `/governance/revisions/{id}/evidence` | 7.7 |
| `POST` | `/governance/revisions/{id}/evidence/upload-url` | 7.7 |
| `POST` | `/governance/evidence/{evidence_id}/finalize` | 7.7 |
| `POST` | `/governance/revisions/{id}/evidence/link` | 7.7 |

**Governance: reviewers, approvers and admins**

| Method | Path | § |
|---|---|---|
| `GET` | `/governance/me/permissions` | 4.3 |
| `GET` | `/governance/approval-centre` | 8.1 |
| `GET` | `/governance/approval-centre/counts` | 8.1 |
| `POST` | `/governance/revisions/{id}/claim` | 8.3 |
| `POST` | `/governance/revisions/{id}/assign` | 8.3 |
| `POST` | `/governance/revisions/{id}/decision` | 8.3 |
| `POST` | `/governance/revisions/{id}/force-approve` | 8.4 |
| `POST` | `/governance/revisions/{id}/risk` | 8.4 |
| `POST` | `/governance/revisions/{id}/publish` | 8.6 |
| `GET`, `POST` | `/admin/staff-roles` | 8.7 |
| `POST` | `/admin/staff-roles/{assignment_id}/revoke` | 8.7 |
| `GET` | `/governance/audit` | 8.8 |
| `GET` | `/courses/{course_id}/versions` | 10.1 |
| `GET` | `/courses/{course_id}/versions/{version_id}` | 10.1 |
| `POST` | `/courses/{course_id}/versions/{version_id}/rollback` | 10.2 |
| `POST` | `/courses/{course_id}/archive` | 10.3 |
| `POST` | `/courses/{course_id}/reinstate` | 10.3 |

**Identity**

| Method | Path | § |
|---|---|---|
| `POST` | `/instructor-applications` | 4.1 |
| `POST` | `/instructor-applications/complete-setup` | 4.1 |
| `GET` | `/users/me` | 4.2 |
