# Admin: endpoint changes

For the admin dashboard. This covers platform admins (`user_type = ADMIN`) and the new staff roles that work in the admin app:

- Academic Reviewer
- Assessment Moderator
- QA Reviewer
- Course Lead
- Lead Assessor
- Head of Learning

Labels used below:
- **[always]** applies regardless of the flag.
- **[governance on]** applies only when `CONTENT_GOVERNANCE_ENABLED=true`.

See [README](./README.md) for the flag.

---

## 1. What an admin can do now

**[governance on]** Admins are **Platform Administrators**, not academic approvers.

| Permission | Admin with governance off | Admin with governance on |
|---|---|---|
| Create / edit courses and content | ✅ | ✅ (edits to published courses go into a working copy) |
| Publish | ✅ any time | ✅ only revisions that are `READY_TO_PUBLISH` |
| Archive (unpublish) | ✅ | ✅ |
| Grant staff roles | ✅ | ✅ |
| Approve reviews (academic, QA, course lead, final) | n/a | ❌ unless granted a role |
| Mark, moderate or approve essay results | ✅ | ❌ unless granted a role (e.g. `INSTRUCTOR` or `COURSE_LEAD` for that course) |

> ⚠️ **[governance on]** If your admins currently grade essays from the admin dashboard, give them a role first. Otherwise `POST /courses/items/{item_id}/essay/submissions/{user_id}/grade` returns `403`.

Drive buttons from `GET /governance/me/permissions?course_id={optional}`. It returns `governance_enabled`, the user's `roles`, and the `permissions` codes.

---

## 2. Changed existing endpoints

### 2.1 `PATCH /courses/{id}/publish?is_published=…`

**[always]**
- The response's course object has two new fields (see §2.6).
- On a publish, the server also records a **course version** (1.0, 1.1, …).

**[governance on]** The endpoint is now a thin shortcut into the workflow:

| `is_published` | Before | Now |
|---|---|---|
| `true` | Publishes immediately | Publishes the course's open revision **only if it is `READY_TO_PUBLISH`**. Otherwise returns `409` with a message such as `Revision 7c0… is QA_REVIEW, waiting on QA_REVIEW - it can be published once every required approval is in`, or `Nothing to publish: submit the course for review first`. Needs `PUBLISH_CONTENT`. |
| `false` | Unpublishes | **Archives** the course (lifecycle `ARCHIVED`, `is_published=false`). Any revision in progress is withdrawn. Needs `ARCHIVE_CONTENT`. |

The new dedicated endpoints are `POST /governance/revisions/{id}/publish` and `POST /courses/{course_id}/archive` (§3).

### 2.2 `GET /courses/manage/{id}`

**[always]**
- **New query param `layer`**: `auto` (default), `live` or `draft`.
- **New response block `governance`**:
  ```json
  "governance": {
    "governance_enabled": true,
    "lifecycle": "PUBLISHED",
    "current_version_label": "1.0",
    "layer": "draft",
    "open_revision": { "id": "7c0…", "kind": "CHANGE", "status": "DRAFT", "round": 0, "is_editable": true }
  }
  ```
- The route now accepts any content-staff account, not just admin or instructor. Access is still checked per course: the caller needs `EDIT_DRAFT_CONTENT` on it.

**[governance on]** When a published course has a working copy:
- `sections` and the course's academic fields (title, description, learning outcomes and so on) show the **working copy** by default.
- Use `?layer=live` to see what learners see.
- `?layer=draft` returns `404` if there is no working copy.

### 2.3 Course and curriculum write endpoints

These endpoints are affected:
- `PATCH /courses/{id}`
- `POST /courses/{course_id}/sections`, `PATCH`/`DELETE /courses/{course_id}/sections/{section_id}`, `PATCH /courses/{course_id}/sections/reorder`
- `POST /courses/{course_id}/sections/{section_id}/items`, `PATCH`/`DELETE /courses/items/{item_id}`, `PATCH /courses/{course_id}/sections/{section_id}/items/reorder`
- `PATCH /courses/items/{item_id}/assessment`
- the quiz, quiz-group and option endpoints under `/courses/items/{item_id}/quiz…`, `/courses/quiz/…` and `/courses/quiz-group/…`
- `PATCH /certificates/courses/{course_id}/settings`

**[always]** Deleting a document item no longer deletes the file from storage. Version snapshots and rollback may still need it.

**[governance on]**, for a **published** course:
- **The first edit opens a hidden working copy.** Learners keep seeing the published content.
- **You can keep sending the ids you already have.** The server maps live ids onto the working copy.
- **Write responses return working-copy ids.** Re-fetch `GET /courses/manage/{id}` after a write instead of patching local state with the returned id.
- **These changes are held for review:**
  - academic course fields: `title`, `description`, `prerequisite`, `level`, `category`, `what_you_will_learn`, `material_includes`, `requirements`;
  - certificate settings (`certificate_enabled`, template).
- **These changes still apply immediately:**
  - `price`, `is_free`, `is_exclusive`, access dates, thumbnail, instructor credits;
  - live-session scheduling (time, duration, guest).
- **While the revision is under review, every write returns `409`.** Withdraw the revision to edit again.
- **An archived course can't be edited.** Writes return `409`; reinstate the course first.

For a **never-published** course, edits still apply directly, exactly as before. The first edit simply opens an `INITIAL` revision for it.

### 2.4 `POST /courses` (create course)

**[always]**
- The caller needs `CREATE_CONTENT`.
- Admins and instructors have it, so nothing changes for them.
- Accounts with a `CONTENT_DEVELOPER` role can now create courses too.

### 2.5 Essay grading endpoints

**`GET /courses/items/{item_id}/essay/submissions`**

**[always]**
- **Who can call it:** anyone with `MARK_ASSESSMENT`, `MODERATE_ASSESSMENT` or `APPROVE_RESULTS` on the course. The course-edit permission is no longer what grants access.
- **New fields on each row:**

| Field | Meaning |
|---|---|
| `result_status` | `DRAFT_MARK`, `AWAITING_MODERATION`, `RETURNED_TO_MARKER`, `MODERATED`, `APPROVED` or `PUBLISHED`; null if not marked yet |
| `current_mark_id` | The in-progress mark, if any |
| `working_score` | The latest in-progress score |

**`POST /courses/items/{item_id}/essay/submissions/{user_id}/grade`**

**[always]**
- **Who can call it:** needs `MARK_ASSESSMENT` on the course.
- **History is kept.** Every grade is recorded in the mark history instead of being overwritten in place.
- **New optional body fields:** `recommendation` (`PASS` or `FAIL`) and `submit_for_moderation` (bool).
- **The response `data` is now the mark record.** Previously it was empty.

**[governance on]**, for essays with `requires_moderation` (the default for final assessments):
- The call saves a **draft mark** only, and `is_published` is ignored.
- The learner sees nothing until the result is moderated, approved and published (§3.5).

### 2.6 Course objects everywhere

**[always]** Every course object has two new fields: `governance_status` (`DRAFT`, `PUBLISHED` or `ARCHIVED`) and `current_version_label` (e.g. `"1.1"`). This covers `CourseReadDTO`, which is used by the manage list, manage detail, create, update and publish responses.

### 2.7 Essay assessment settings

**[always]** Essay settings gain `requires_moderation` (bool):
- In `essay_settings` on item create (optional; defaults to `is_final_assessment`).
- In `PATCH /courses/items/{item_id}/assessment`.
- In the manage tree's essay detail.

---

## 3. New endpoints

Full request and response shapes are in the `docs/phase_3/` references linked from the [README](./README.md).

### 3.1 Staff roles (`MANAGE_STAFF_ROLES`; admins have it)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/admin/staff-roles?user_id=&role=&course_id=&include_revoked=` | List grants |
| `POST` | `/admin/staff-roles` | Grant a role: `{ user_id, role, course_id?, reason?, expires_at? }`. Omit `course_id` for a platform-wide grant. |
| `POST` | `/admin/staff-roles/{assignment_id}/revoke` | Revoke: `{ reason? }` |
| `GET` | `/governance/me/permissions?course_id=` | The caller's roles and permissions |

Available roles:
- `INSTRUCTOR`
- `CONTENT_DEVELOPER`
- `ACADEMIC_REVIEWER`
- `ASSESSMENT_MODERATOR`
- `QA_REVIEWER`
- `COURSE_LEAD`
- `LEAD_ASSESSOR`
- `HEAD_OF_LEARNING`
- `PLATFORM_ADMIN`

**Suggested UI:** a "Staff roles" screen with a user picker, a role dropdown and an optional course picker.

### 3.2 Approval Centre

| Method | Path |
|---|---|
| `GET` | `/governance/approval-centre?view=awaiting_me\|returned_to_me\|overdue\|ready_to_publish\|recently_approved\|recently_rejected\|my_drafts&kind=&course_id=` (paginated) |
| `GET` | `/governance/approval-centre/counts` – badge counts |

### 3.3 Reviewing a revision

| Method | Path | Who |
|---|---|---|
| `GET` | `/governance/revisions/{id}` | Anyone with access to the course. Includes `available_actions` and `blocked_reason` for the caller. |
| `GET` | `/governance/revisions/{id}/diff` | Same. Each change is tagged with a risk level. |
| `GET` | `/governance/revisions/{id}/preview` | Same. The learner view of the working copy. |
| `GET` | `/governance/revisions/{id}/tree` | Same. The editor view of the working copy. |
| `POST` | `/governance/revisions/{id}/claim` | An eligible reviewer |
| `POST` | `/governance/revisions/{id}/assign` | Course Lead or Head of Learning: `{ reviewer_id, due_at? }` |
| `POST` | `/governance/revisions/{id}/decision` | The stage reviewer: `{ decision, comment?, conditions?, escalate_to?, flags? }` |
| `POST` | `/governance/revisions/{id}/force-approve` | Head of Learning: `{ justification }` (20+ characters) |
| `POST` | `/governance/revisions/{id}/risk` | Head of Learning: `{ level, reason }` |
| `POST` | `/governance/revisions/{id}/publish` | Platform admin (`PUBLISH_CONTENT`) |
| `GET`/`POST` | `/governance/revisions/{id}/comments` | Discussion |
| `PATCH` | `/governance/comments/{comment_id}/resolve` | |
| `GET` | `/governance/revisions/{id}/evidence` | |
| `POST` | `/governance/revisions/{id}/evidence/upload-url`, then `POST /governance/evidence/{evidence_id}/finalize` | File evidence |
| `POST` | `/governance/revisions/{id}/evidence/link` | Link evidence |

`decision` is one of:
- `APPROVED`
- `APPROVED_WITH_MINOR_CHANGES` (requires `conditions`)
- `RETURNED_FOR_REVISION` (requires `comment`)
- `REJECTED` (requires `comment`)
- `ESCALATED` (requires `comment`)

### 3.4 Course lifecycle and versions

| Method | Path | Who |
|---|---|---|
| `GET` | `/courses/{course_id}/governance` | Course staff: lifecycle, current version, open revision |
| `POST` | `/courses/{course_id}/revisions` | Editors: open a working copy explicitly |
| `GET` | `/courses/{course_id}/revisions` | Course staff: revision history |
| `GET` | `/courses/{course_id}/versions` | Course staff: version history |
| `GET` | `/courses/{course_id}/versions/{version_id}` | Course staff: one version with its full content snapshot |
| `POST` | `/courses/{course_id}/versions/{version_id}/rollback` | Course Lead or Head of Learning: `{ reason? }` |
| `POST` | `/courses/{course_id}/archive` | Platform admin: `{ reason? }` |
| `POST` | `/courses/{course_id}/reinstate` | Platform admin: `{ reason? }`. Goes through quick approval, then publish. |

### 3.5 Essay moderation (Moderators, Course Leads, Lead Assessors)

| Method | Path |
|---|---|
| `GET` | `/essay-marks/{mark_id}` |
| `POST` | `/essay-marks/{mark_id}/moderate` – `{ action: APPROVE\|AMEND\|RETURN, score?, feedback?, note? }` |
| `POST` | `/essay-marks/{mark_id}/approve` – `{ final_score?, final_feedback?, note?, publish? }` |
| `POST` | `/courses/items/{item_id}/essay-marks/publish` – `{ mark_ids }` or `{ all_approved: true }` |
| `GET` | `/courses/items/{item_id}/essay-marks?status=` |
| `GET` | `/courses/items/{item_id}/essay/submissions/{user_id}/marks` |

Separation of duties for marks:
- The moderator can't be the marker.
- The approver can't be the marker or the moderator.

### 3.6 Audit log

`GET /governance/audit?course_id=&revision_id=&actor_id=&entity_type=&entity_id=&from=&to=` (paginated). Needs `FINAL_APPROVAL`, `PUBLISH_CONTENT` or `MANAGE_STAFF_ROLES`.

---

## 4. New in-app notification types

These arrive through the existing `/notifications` list and websocket. The `type` values are:

- Reviews: `REVIEW_REQUESTED`, `REVIEW_ASSIGNED`, `REVIEW_COMMENT_ADDED`
- Revision outcomes: `REVISION_STAGE_APPROVED`, `REVISION_RETURNED`, `REVISION_REJECTED`, `REVISION_ESCALATED`, `REVISION_READY_TO_PUBLISH`, `REVISION_PUBLISHED`, `REVISION_FORCE_APPROVED`
- Essay marks: `MARKS_AWAITING_MODERATION`, `MARKS_RETURNED`, `MARKS_DISPUTED`, `MARKS_AWAITING_APPROVAL`

Their `link` values point at `/dashboard/approval-centre/revisions/{id}` or `/dashboard/approval-centre/marks/{id}`, so add those routes to the admin app. Role changes reuse the existing `ROLE_CHANGED` type.

---

## 5. Redo checklist (admin app)

- [ ] Staff roles screen (§3.1).
- [ ] Approval Centre with tabs and badge counts (§3.2).
- [ ] Review screen: diff, preview, stage timeline, comments, evidence, and decision buttons driven by `available_actions` (§3.3).
- [ ] Course page:
  - [ ] show `governance_status`, `current_version_label` and the open revision;
  - [ ] add a live/draft toggle (§2.2);
  - [ ] add a version history tab with rollback (§3.4).
- [ ] Publish button:
  - [ ] use `POST /governance/revisions/{id}/publish`;
  - [ ] handle `409` from the old toggle (§2.1).
- [ ] Unpublish becomes **Archive**; add **Reinstate**.
- [ ] After any curriculum write, re-fetch the manage tree; handle `409` "under review" (§2.3).
- [ ] Essay grading: show `result_status`, the moderation queue, and approve/publish (§2.5, §3.5). Give admins who grade a marking role.
- [ ] Handle the new notification types and links (§4).
