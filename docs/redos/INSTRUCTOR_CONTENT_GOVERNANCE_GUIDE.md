# Instructor guide: content review, versions and essay moderation

**Audience:** the instructor frontend (and the AI building it). This is the complete reference for every governance feature an instructor touches. It covers the user stories, the screens and flows, every endpoint with request and response examples, the states, the errors and the UI rules. It builds on these existing course-authoring endpoints, which keep working:
- `/courses/{course_id}/sections…`
- `/courses/items/…`
- `/courses/quiz/…`

**Who counts as an "instructor" here:** a user with `user_type = INSTRUCTOR` (on the courses they own), or anyone with a `CONTENT_DEVELOPER` role (on any course) or a course-scoped `COURSE_LEAD` role. They all use this same UI. Read the user's `access` object (see [`USER_ACCESS_ON_LOGIN_AND_PROFILE.md`](./USER_ACCESS_ON_LOGIN_AND_PROFILE.md)) to know which of it they get.

---

## Contents

1. [The big picture](#1-the-big-picture)
2. [User stories](#2-user-stories)
3. [Concepts and states](#3-concepts-and-states)
4. [Screens and flows](#4-screens-and-flows)
5. [API reference](#5-api-reference)
6. [Errors and how to handle them](#6-errors-and-how-to-handle-them)
7. [Notifications](#7-notifications)
8. [When governance is switched off](#8-when-governance-is-switched-off)
9. [Implementation checklist](#9-implementation-checklist)

Conventions:
- Every call needs `Authorization: Bearer <token>`.
- Responses use the `ApiResponse<T>` envelope, i.e. `{ "success": true, "message": "…", "data": … }`.
- Null fields are omitted from responses.
- Ids are UUIDs.

---

## 1. The big picture

```
 Instructor builds or edits the course
          │
          ▼
   [ Submit for review ] ──► the system rates the risk and picks the reviewers
          │
          ▼
  Academic Review → (Assessment Moderation) → QA Review → Course Lead → (Head of Learning)
          │                     │
          │        a reviewer can return it with comments
          │                     ▼
          │         Instructor fixes it and resubmits (new round)
          ▼
   Ready to publish ──► a Platform Admin publishes ──► learners see the new version (v1.0, v1.1, v2.0…)
```

**Key ideas for the UI:**
- **Instructors don't publish.** They submit for review. A platform admin publishes once every required reviewer has approved.
- **Editing a live course is safe.** Changes go into a private **working copy**, and learners keep seeing the published version until the new one is approved and published.
- **Nobody approves their own work.** Even if the instructor also holds a reviewer role, they can't approve a revision they edited.
- **Learner progress is never lost** when a new version is published.

---

## 2. User stories

### Building a new course
1. *As an instructor*, I create a course, add modules, lessons and assessments, and preview it, without learners seeing anything.
2. *As an instructor*, when my course is ready I click **Submit for review**, write a short summary of what it is, and see who has to review it and how long it should take.
3. *As an instructor*, I can follow its progress (Academic review → QA → Course Lead → Head of Learning) and see who is reviewing it.
4. *As an instructor*, if a reviewer sends it back, I get notified, see their comments next to the exact lesson or question, make the fixes, and resubmit.
5. *As an instructor*, I'm notified when it's approved and when it goes live, and I can see "Version 1.0".

### Changing a live course
6. *As an instructor*, I can edit a published course whenever I want. A banner tells me I'm editing an **unpublished draft**, and learners still see the current version.
7. *As an instructor*, before submitting I can see **exactly what I changed** (added, removed, edited, moved) and preview the course as learners will see it.
8. *As an instructor*, small fixes (typos, broken links) get a quick single approval; bigger changes (new lessons, assessment changes) get a full review. The app tells me which, and why.
9. *As an instructor*, I can flag a change as safeguarding, legal or policy related so it gets senior review.
10. *As an instructor*, if I change my mind while it's under review, I can **withdraw** it and keep editing, or **discard** my draft entirely.
11. *As an instructor*, I can reschedule a live session or change the course price immediately, without a review.
12. *As an instructor*, I can see the course's **version history**: who changed what, who approved it, and when.

### Marking essays (final assessments)
13. *As an instructor*, when I mark a final-assessment essay, my mark is a **draft** that goes to a moderator. The learner doesn't see it yet.
14. *As an instructor*, I can send my mark to moderation, see the moderator's decision, re-mark if it's returned, or **dispute** an amended mark.
15. *As an instructor*, I can see the full marking history for a learner's essay.

### Inbox
16. *As an instructor*, one inbox shows my drafts, what was returned to me, and recent decisions on my work, each with a badge count.

---

## 3. Concepts and states

### 3.1 Course lifecycle (`governance_status` / `governance.lifecycle`)

| Value | Meaning | Instructor sees |
|---|---|---|
| `DRAFT` | Never published | "Not published" |
| `PUBLISHED` | Live for learners | "Live – v{current_version_label}" |
| `ARCHIVED` | Withdrawn by an admin | "Archived" (read-only; editing returns 409) |

### 3.2 Revision

A **revision** is one batch of changes going through review. A course has **at most one open revision**.

| `kind` | When it exists |
|---|---|
| `INITIAL` | A course that has never been published. The course content itself is the draft. |
| `CHANGE` | Edits to a published course, held in a working copy |
| `ROLLBACK` | Restoring an earlier version (started by a Course Lead or Head of Learning) |
| `REINSTATE` | Bringing back an archived course (started by an admin) |

### 3.3 Revision status (`status`)

| Status | Label to show | Instructor can… |
|---|---|---|
| `DRAFT` | Draft – not submitted | edit, submit, discard |
| `SUBMITTED_FOR_REVIEW` | Submitted – waiting for a reviewer | withdraw, comment |
| `ACADEMIC_REVIEW` | In academic review | withdraw, comment |
| `ACADEMICALLY_APPROVED` | Academically approved | withdraw, comment |
| `ASSESSMENT_MODERATION` | Assessments being moderated | withdraw, comment |
| `QA_REVIEW` | In quality review | withdraw, comment |
| `QA_APPROVED` | Quality approved – waiting for Course Lead | withdraw, comment |
| `COURSE_APPROVED` | Course Lead approved | withdraw, comment |
| `FINAL_APPROVAL_REQUIRED` | Waiting for Head of Learning | withdraw, comment |
| `READY_TO_PUBLISH` | Approved – waiting to be published | withdraw, comment |
| `RETURNED_FOR_REVISION` | **Returned – changes needed** | edit, resubmit, discard |
| `PUBLISHED` | Published as v{label} | view only |
| `REJECTED` | Rejected | view only; a new edit starts a new revision |
| `WITHDRAWN` | Discarded | view only |

`current_stage` names the stage waiting for a decision: `QUICK_APPROVAL`, `ACADEMIC_REVIEW`, `ASSESSMENT_MODERATION`, `QA_REVIEW`, `COURSE_LEAD_APPROVAL` or `FINAL_APPROVAL`.

**Always render buttons from `available_actions`** rather than from these tables. The server computes it for the current user.

### 3.4 Risk and routing (decided automatically on submit)

| Risk | Typical changes | Review path |
|---|---|---|
| `LOW` | Lesson or module title fixes, link fixes, reordering, preview flag, durations | **Quick approval** (one QA Reviewer or Course Lead) |
| `MEDIUM` | New or removed lesson or module, new video or document, question or essay wording, course description, moving a lesson to another module | Academic → QA → Course Lead |
| `HIGH` | A new course; adding or removing an assessment; pass mark, attempts or time limit; changing a correct answer; adding or removing questions; learning outcomes; certificate settings; **any flag** | Academic → QA → Course Lead → **Head of Learning** |

- If a MEDIUM or HIGH change touches an assessment, **Assessment Moderation** is added after Academic review.
- Instructors can *raise* the risk (`declared_risk`) or add `flags` (`SAFEGUARDING`, `LEGAL`, `POLICY`, `CERTIFICATE_RULE`, `CPD_RECOGNITION`). They can't lower it.
- Reviewers may **escalate** a revision to a higher risk, which adds stages.

### 3.5 Versions

Every publish creates a version.
- `1.0` is the first publish.
- LOW and MEDIUM changes add a minor version (`1.1`, `1.2`).
- HIGH changes add a major version (`2.0`).
- A rollback produces a new minor version (e.g. `2.1 – rollback to 1.3`).

The revision's `proposed_version_label` shows what the next version will be.

### 3.6 What goes through review, and what doesn't

| Goes through review (held in the working copy) | Applies immediately (no review) |
|---|---|
| Modules, lessons, documents, videos and links (add, edit, remove, reorder) | Price, free/paid, exclusive flag |
| Quizzes, quiz groups, questions and options, essay settings, pass marks and attempts | Access window (scheduled courses) |
| Course title, description, prerequisite, level, category | Thumbnail |
| Learning outcomes (`what_you_will_learn`), materials, requirements | Instructor credits |
| Certificate on/off and template | **Live session date, time, duration and guest** |

---

## 4. Screens and flows

### 4.0 On login
Read `data.access` from the session (or from `GET /users/me`):
- `capabilities.can_create_courses` → show the **New course** button.
- `capabilities.can_submit_for_review` → use the review workflow.
- `governance_enabled: false` → use the old Publish toggle (§8).
- `capabilities.can_access_approval_centre` → show the **Inbox** menu, with badges from `GET /governance/approval-centre/counts`.
- `capabilities.can_mark_essays` → show the **Marking** menu.

### 4.1 Flow A: create a course and submit it

1. Create the course with `POST /courses`, then add modules and items with the existing endpoints.
2. On the course page, call `GET /courses/{course_id}/governance`. The response has `lifecycle: "DRAFT"`, and `open_revision` (kind `INITIAL`, status `DRAFT`) once the first module or item exists. If `open_revision` is missing, call `POST /courses/{course_id}/revisions` when the user clicks Submit.
3. The user clicks **Submit for review**. Open a dialog with:
   - **What is this?** (`change_summary`, required, 5+ characters);
   - **Why?** (`reason`, optional);
   - checkboxes for the flags;
   - an optional "Mark as higher risk" choice.
4. Call `POST /governance/revisions/{revision_id}/submit`.
5. Show the result:
   - the risk badge;
   - `required_stages` as a stepper;
   - the due date (`stages[].due_at`);
   - the message "Submitted for review – version 1.0 will be published once approved".
6. **The course editor becomes read-only** while the revision is under review. Writes return `409`. Show a **Withdraw to edit** button instead.
7. Follow progress through `GET /governance/revisions/{revision_id}` and notifications (§7).
8. When `status` is `PUBLISHED`, show "Live – v1.0".

### 4.2 Flow B: edit a live course

1. The course page calls `GET /courses/manage/{course_id}`. When `governance.layer === "draft"`, show a banner: **"You're editing a draft (v{open_revision.proposed_version_label or next}). Learners still see v{current_version_label}."** Add a **View live version** toggle that calls `?layer=live`.
2. The user edits with the existing endpoints. The first edit opens the working copy automatically, and every write works with the ids on screen.
3. **After every write, re-fetch `GET /courses/manage/{course_id}`.** Write responses return working-copy ids, which can differ from the ids on screen.
4. **Review changes** button → `GET /governance/revisions/{revision_id}/diff`.
   - Render a grouped list, one row per change: `label`, an `op` badge (Added / Removed / Edited / Moved), `fields`, a before → after view, and a `risk` chip.
   - Show `computed_risk` and `reasons` at the top.
5. **Preview as learner** button → `GET /governance/revisions/{revision_id}/preview`.
6. Submit as in Flow A, step 3. Show "Version {proposed_version_label}".
7. **Discard draft** → `POST /governance/revisions/{revision_id}/discard` (confirm first). The live course is untouched.

### 4.3 Flow C: returned for revision

1. A notification arrives (`REVISION_RETURNED`), or the item appears in **Inbox → Returned to me**.
2. The revision page shows:
   - a red banner "Changes requested by {decisions[-1].actor.name}: {decisions[-1].comment}";
   - comments, with anchored ones pinned next to their lesson or question;
   - the editor, unlocked again (`is_editable: true`).
3. The instructor fixes things, replies in the comment threads and resolves the comments.
4. They resubmit through `POST …/submit`. `round` increases by 1, and the full history stays visible in the timeline.

### 4.4 Flow D: withdraw while in review

The **Withdraw** button (`available_actions` contains `WITHDRAW`) calls `POST /governance/revisions/{revision_id}/withdraw`. Status goes back to `DRAFT`, so the user can edit and submit again. The confirmation should say "Reviewers will need to start again".

### 4.5 Flow E: version history

The course page has a **History** tab:
1. `GET /courses/{course_id}/versions` lists each version: label, published date, author, reviewers, reason, and an `is_current` badge.
2. Clicking a version calls `GET /courses/{course_id}/versions/{version_id}` (it includes the content `snapshot`).
3. `GET /courses/{course_id}/revisions` lists every revision, including rejected and discarded ones.

### 4.6 Flow F: moderated essay marking

1. **Marking** screen → `GET /courses/items/{item_id}/essay/submissions`. Show `result_status` per learner:

   | `result_status` | Badge |
   |---|---|
   | — | Not marked |
   | `DRAFT_MARK` | Draft mark |
   | `AWAITING_MODERATION` | With moderator |
   | `RETURNED_TO_MARKER` | Returned to you |
   | `MODERATED` | Moderated |
   | `APPROVED` | Approved – awaiting release |
   | `PUBLISHED` | Released |

2. The marker enters a score and feedback, and optionally a Pass/Fail recommendation → `POST /courses/items/{item_id}/essay/submissions/{user_id}/grade`.
   - Offer a **Save draft** button and a **Save & send to moderation** button (`submit_for_moderation: true`).
   - For a non-moderated essay, this call grades and (optionally) releases in one step, as before.
3. **Send to moderation** later → `POST /essay-marks/{mark_id}/submit`.
4. When the moderator returns it (`MARKS_RETURNED`, status `RETURNED_TO_MARKER`), show `moderation_note`. The marker re-marks through the same grade call, then sends it again.
5. When the moderator amends it (status `MODERATED`, `moderated_score` ≠ `score`), offer **Dispute** → `POST /essay-marks/{mark_id}/dispute` with a note. A Course Lead or Lead Assessor settles it.
6. **History** → `GET /courses/items/{item_id}/essay/submissions/{user_id}/marks`.

### 4.7 Flow G: inbox

Tabs and calls:
- **My drafts:** `GET /governance/approval-centre?view=my_drafts`
- **Returned to me:** `?view=returned_to_me`
- **Recently approved:** `?view=recently_approved`
- **Recently rejected:** `?view=recently_rejected`
- **Awaiting me:** `?view=awaiting_me`, only if the user also holds a reviewer role (`capabilities.can_review_content` or `can_moderate_marks`).

Badges come from `GET /governance/approval-centre/counts`.

Clicking a row:
- `kind: "COURSE_REVISION"` → revision page (`GET /governance/revisions/{id}`)
- `kind: "ESSAY_MARK"` → mark page (`GET /essay-marks/{id}`)

---

## 5. API reference

### 5.1 Course governance state

#### `GET /courses/{course_id}/governance`

```json
{
  "data": {
    "governance_enabled": true,
    "lifecycle": "PUBLISHED",
    "current_version_label": "1.0",
    "layer": "draft",
    "open_revision": {
      "id": "7c0d…", "course_id": "4f42…", "course_title": "Child Protection Essentials",
      "kind": "CHANGE", "status": "DRAFT", "round": 0,
      "author": { "id": "5bf9…", "name": "Ike Okafor", "email": "ike@…" },
      "created_at": "2026-10-02T09:00:00Z", "is_editable": true
    }
  }
}
```
`open_revision` is omitted when there is none.

#### `GET /courses/manage/{course_id}?layer=auto|live|draft`

The existing manage endpoint. It now includes `governance_status`, `current_version_label` and a `governance` block with the same shape as above.
- `auto` (default) shows the working copy if one exists.
- `live` shows what learners see.
- `draft` returns `404` when there's no working copy.

#### `POST /courses/{course_id}/revisions`

Opens (or returns) the working copy without editing anything. Returns `201` with a revision detail (§5.2). Use it when the user clicks **Submit** on a course whose `open_revision` is missing.

### 5.2 Revision detail

#### `GET /governance/revisions/{revision_id}`

```json
{
  "data": {
    "id": "7c0d…",
    "course_id": "4f42…", "course_title": "Child Protection Essentials",
    "kind": "CHANGE",
    "status": "QA_REVIEW",
    "current_stage": "QA_REVIEW",
    "round": 1,
    "author": { "id": "5bf9…", "name": "Ike Okafor" },
    "effective_risk": "MEDIUM", "computed_risk": "MEDIUM",
    "risk_flags": [],
    "risk_reasons": [
      "MEDIUM · Module 2 › Case study: item added",
      "LOW · Module 1 › Read the guidance: title changed"
    ],
    "touches_assessment": false,
    "required_stages": ["ACADEMIC_REVIEW", "QA_REVIEW", "COURSE_LEAD_APPROVAL"],
    "proposed_version_label": "1.1",
    "change_summary": "2026 refresh",
    "reason": "New statutory guidance",
    "course_changes": { "description": "Safeguarding basics, updated" },
    "created_at": "2026-10-02T09:00:00Z",
    "submitted_at": "2026-10-02T10:00:00Z",
    "is_editable": false,
    "contributors": [{ "id": "5bf9…", "name": "Ike Okafor" }],
    "stages": [
      { "id": "…", "round": 1, "stage": "ACADEMIC_REVIEW", "sequence": 1, "status": "APPROVED",
        "assigned_reviewer": { "id": "…", "name": "Dr Amaka" }, "decided_by": { "id": "…", "name": "Dr Amaka" },
        "decided_at": "2026-10-03T08:00:00Z", "due_at": "2026-10-07T10:00:00Z", "conditions": [], "is_overdue": false },
      { "id": "…", "round": 1, "stage": "QA_REVIEW", "sequence": 2, "status": "IN_REVIEW",
        "assigned_reviewer": { "id": "…", "name": "Queen" }, "due_at": "2026-10-07T10:00:00Z", "conditions": [], "is_overdue": false },
      { "id": "…", "round": 1, "stage": "COURSE_LEAD_APPROVAL", "sequence": 3, "status": "PENDING",
        "due_at": "2026-10-07T10:00:00Z", "conditions": [], "is_overdue": false }
    ],
    "decisions": [
      { "id": "…", "created_at": "2026-10-03T08:00:00Z", "stage": "ACADEMIC_REVIEW", "round": 1,
        "decision": "APPROVED", "actor": { "id": "…", "name": "Dr Amaka" }, "comment": "Accurate",
        "conditions": [], "from_status": "ACADEMIC_REVIEW", "to_status": "ACADEMICALLY_APPROVED", "version_label": "1.1" }
    ],
    "open_conditions": [],
    "available_actions": ["WITHDRAW", "COMMENT", "ATTACH_EVIDENCE"]
  }
}
```

- **`stages`** contains every round. Filter by `round === revision.round` for the current stepper; earlier rounds are history.
- **Stage `status`** is one of `PENDING`, `IN_REVIEW`, `APPROVED`, `APPROVED_WITH_CONDITIONS`, `RETURNED`, `REJECTED`, `SKIPPED` (force-approved past or no longer required) or `SUPERSEDED` (replaced after an escalation or return).
- **`decision`** is one of `APPROVED`, `APPROVED_WITH_MINOR_CHANGES`, `RETURNED_FOR_REVISION`, `REJECTED`, `ESCALATED` or `FORCE_APPROVED`.
- **`available_actions` for an instructor** can be `EDIT`, `SUBMIT`, `DISCARD`, `WITHDRAW`, `COMMENT` and `ATTACH_EVIDENCE`. Reviewer actions also appear if the user holds a reviewer role, but never on their own work.
- **`blocked_reason`** explains why reviewer actions are missing, e.g. "You contributed to this revision, so you can't approve any stage of it".

#### `GET /governance/revisions/{revision_id}/diff`

```json
{
  "data": {
    "revision_id": "7c0d…",
    "computed_risk": "MEDIUM",
    "touches_assessment": false,
    "reasons": ["MEDIUM · Module 2 › Case study: item added"],
    "is_live_computation": true,
    "changes": [
      { "entity": "item", "key": "a1b2…", "op": "ADDED", "label": "Module 2 › Case study",
        "fields": ["title", "order_index", "is_preview", "estimated_minutes"],
        "after": { "title": "Case study", "order_index": 2, "is_preview": false }, "item_type": "LINKS", "risk": "MEDIUM" },
      { "entity": "item", "key": "c3d4…", "op": "MODIFIED", "label": "Module 1 › Read the 2026 guidance",
        "fields": ["title"], "before": { "title": "Read the guidance" }, "after": { "title": "Read the 2026 guidance" },
        "item_type": "LINKS", "risk": "LOW" },
      { "entity": "option", "key": "e5f6…", "op": "MODIFIED",
        "label": "Module 1 › Knowledge check › Q: Who is responsible… › Only managers",
        "fields": ["is_correct"], "before": { "is_correct": false }, "after": { "is_correct": true }, "risk": "HIGH" }
    ]
  }
}
```

- `entity` is one of `course`, `section`, `item`, `video`, `document`, `link`, `assessment`, `assessment_settings`, `group_section`, `question` or `option`.
- `op` is one of `ADDED`, `REMOVED`, `MODIFIED` or `MOVED`.
- `key` is the live id of the thing changed. Use it to anchor comments.
- While editable, the diff is computed live. After submission it shows the recorded diff (`is_live_computation: false`).

#### `GET /governance/revisions/{revision_id}/preview`

Returns `ApiResponse<Section[]>`: the working copy in the same shape as the **student** course detail sections. Render it with the learner course-detail component.

#### `GET /governance/revisions/{revision_id}/tree`

Returns `ApiResponse<Section[]>` in the **manage/editor** shape (the same as `GET /courses/manage/{id}` `sections`).

### 5.3 Author actions

#### `POST /governance/revisions/{revision_id}/submit`

Request:
```json
{
  "change_summary": "2026 statutory guidance refresh",
  "reason": "Working Together 2026 replaced the 2023 edition",
  "declared_risk": "HIGH",
  "flags": ["SAFEGUARDING"]
}
```

| Field | Required | Notes |
|---|---|---|
| `change_summary` | ✅ | 5–5000 characters; shown to reviewers |
| `reason` | | Why the change is needed |
| `declared_risk` | | `LOW`, `MEDIUM` or `HIGH`; only takes effect if higher than computed |
| `flags` | | Any flag forces `HIGH` |

Response: revision detail (§5.2), with `status` set to `SUBMITTED_FOR_REVIEW`.

Errors:
- `400` "There are no changes to submit";
- `400` "Course must have at least one curriculum item before review";
- `403` without `SUBMIT_FOR_REVIEW`;
- `409` if not a draft.

#### `POST /governance/revisions/{revision_id}/withdraw`

No body. Returns the revision detail with `status: "DRAFT"`. `409` if it isn't in review.

#### `POST /governance/revisions/{revision_id}/discard`

No body. Returns the revision detail with `status: "WITHDRAWN"`. Only allowed from `DRAFT` or `RETURNED_FOR_REVISION`; otherwise `409` "withdraw it from review first".

### 5.4 Comments and evidence

#### `GET /governance/revisions/{revision_id}/comments`

```json
{ "data": [
  { "id": "c1…", "created_at": "…", "revision_id": "7c0d…", "stage_id": "…",
    "author": { "id": "…", "name": "Dr Amaka" }, "body": "Please cite the 2026 code",
    "anchor_type": "item", "anchor_id": "c3d4…" },
  { "id": "c2…", "created_at": "…", "revision_id": "7c0d…", "parent_id": "c1…",
    "author": { "id": "5bf9…", "name": "Ike Okafor" }, "body": "Done", "resolved_at": "…" }
] }
```
Build threads from `parent_id`. Pin anchored comments next to the matching lesson or question: match `anchor_id` against the diff `key` or the live item id.

#### `POST /governance/revisions/{revision_id}/comments` → `201`

```json
{ "body": "Updated the citation", "parent_id": "c1…", "anchor_type": "item", "anchor_id": "c3d4…" }
```
`anchor_type` is one of `course`, `section`, `item` or `question`. `409` if the revision is closed.

#### `PATCH /governance/comments/{comment_id}/resolve`

Returns the comment with `resolved_at` set.

#### Evidence (optional for instructors)

| Call | Body |
|---|---|
| `GET /governance/revisions/{id}/evidence` | — |
| `POST /governance/revisions/{id}/evidence/upload-url` | `{ "title", "file_name", "content_type"? }` returns `{ evidence_id, upload_url, storage_key }`. `PUT` the file to `upload_url`, then call finalize. |
| `POST /governance/evidence/{evidence_id}/finalize` | `{ "mime_type"?, "file_size_bytes"? }` |
| `POST /governance/revisions/{id}/evidence/link` | `{ "title", "url" }` |

### 5.5 History

#### `GET /courses/{course_id}/versions`

```json
{ "data": [
  { "id": "v2…", "course_id": "4f42…", "label": "1.1", "major": 1, "minor": 1, "revision_id": "7c0d…",
    "author": { "id": "…", "name": "Ike Okafor" },
    "reviewers": [{ "id": "…", "name": "Dr Amaka" }, { "id": "…", "name": "Queen" }],
    "approved_at": "…", "published_at": "…", "published_by": { "id": "…", "name": "Ada (Admin)" },
    "reason": "New statutory guidance", "risk_level": "MEDIUM", "is_current": true, "has_snapshot": true },
  { "id": "v1…", "label": "1.0", "...": "...", "is_current": false }
] }
```

#### `GET /courses/{course_id}/versions/{version_id}`

The same fields, plus `snapshot`: the full course content as published, i.e. `{ course: {...}, sections: [{ key, title, items: [...] }] }`.

#### `GET /courses/{course_id}/revisions`

Revision summaries, newest first, with `id`, `kind`, `status`, `round`, `author`, `effective_risk`, `proposed_version_label`, `change_summary`, `created_at`, `submitted_at`, `published_at` and `is_editable`.

> Rollback (`POST /courses/{course_id}/versions/{version_id}/rollback`) needs `APPROVE_COURSE` or `FINAL_APPROVAL`, so it is for Course Leads and the Head of Learning. Show it only if the course's permissions include one of those (`GET /governance/me/permissions?course_id=`).

### 5.6 Inbox

#### `GET /governance/approval-centre?view={view}&kind={COURSE_REVISION|ESSAY_MARK}&course_id=&page=&page_size=`

Paginated. Views for instructors: `my_drafts`, `returned_to_me`, `recently_approved`, `recently_rejected`; plus `awaiting_me` and `overdue` if they hold reviewer roles.

```json
{
  "success": true,
  "data": [
    { "kind": "COURSE_REVISION", "id": "7c0d…", "item_title": "Module 2 › Case study", "item_type": "Lesson",
      "course_id": "4f42…", "course_title": "Child Protection Essentials",
      "submitted_by": { "id": "5bf9…", "name": "Ike Okafor" }, "status": "RETURNED_FOR_REVISION",
      "risk": "MEDIUM", "version_label": "1.1", "updated_at": "…", "available_actions": ["EDIT", "SUBMIT"] },
    { "kind": "ESSAY_MARK", "id": "m1…", "item_title": "Reflective essay - Lerato Test (attempt 1)",
      "item_type": "Essay mark", "course_id": "…", "course_title": "Reflective Practice",
      "submitted_by": { "id": "5bf9…", "name": "Ike Okafor" }, "current_stage": "MARKING",
      "status": "RETURNED_TO_MARKER", "reviewer": { "id": "…", "name": "Musa" },
      "available_actions": ["EDIT", "SUBMIT_FOR_MODERATION"] }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

- `item_type` is one of `Course`, `Lesson`, `Assessment`, `Course update`, `Rollback`, `Reinstatement`, `Essay mark` or `Essay mark (disputed)`.
- In `recently_*` views, `decision` holds the decision and `reviewer` the person who made it.

#### `GET /governance/approval-centre/counts`

```json
{ "data": { "awaiting_me": 0, "returned_to_me": 1, "overdue": 0, "ready_to_publish": 0 } }
```

### 5.7 Essay marking

#### `GET /courses/items/{item_id}/essay/submissions?page=&page_size=` (paginated)

Each row:
```json
{ "user_id": "…", "user_full_name": "Lerato Test", "user_email": "…", "content_text": "My reflection",
  "submitted_at": "…", "is_published": false,
  "result_status": "AWAITING_MODERATION", "current_mark_id": "m1…", "working_score": 55 }
```
`score` and `feedback` are the *released* result (absent until published). `working_score` is the in-progress mark.

#### `POST /courses/items/{item_id}/essay/submissions/{user_id}/grade`

```json
{ "score": 55, "feedback": "Good start; criterion 3 missing", "recommendation": "FAIL", "submit_for_moderation": true }
```

| Field | Notes |
|---|---|
| `score` | 0–100, required |
| `feedback` | Optional |
| `recommendation` | `PASS` or `FAIL`, optional |
| `submit_for_moderation` | Moderated essays: send straight to the moderator |
| `is_published` | **Non-moderated essays only**: release to the learner now |

The response `data` is the mark (§ below). Errors:
- `404` if the learner hasn't submitted;
- `409` "already in moderation";
- `403` if another marker owns the draft.

#### Mark object (`GET /essay-marks/{mark_id}`)

```json
{ "data": {
  "id": "m1…", "created_at": "…", "submission_id": "…", "item_id": "…", "course_id": "…",
  "learner": { "id": "…", "name": "Lerato Test" }, "attempt_no": 1,
  "status": "MODERATED",
  "marker": { "id": "5bf9…", "name": "Ike Okafor" }, "score": 55, "feedback": "Good start", "recommendation": "FAIL",
  "submitted_for_moderation_at": "…",
  "moderator": { "id": "…", "name": "Musa" }, "moderated_score": 65, "moderated_feedback": "Good start",
  "moderation_note": "Meets criteria 2 and 3", "moderated_at": "…",
  "disputed": false,
  "available_actions": ["DISPUTE"]
} }
```
Mark `available_actions` for a marker can be `EDIT`, `SUBMIT_FOR_MODERATION` and `DISPUTE`.

#### `POST /essay-marks/{mark_id}/submit`

No body. Moves `DRAFT_MARK` or `RETURNED_TO_MARKER` to `AWAITING_MODERATION`. Returns the mark.

#### `POST /essay-marks/{mark_id}/dispute`

`{ "note": "Criterion 3 isn't evidenced" }` (5+ characters). Only the marker can dispute, and only a `MODERATED` mark.

#### `GET /courses/items/{item_id}/essay-marks?status=AWAITING_MODERATION&status=MODERATED`

The marks on one essay, filterable by status.

#### `GET /courses/items/{item_id}/essay/submissions/{user_id}/marks`

One learner's full marking history, newest first.

#### Essay setting

`essay_settings.requires_moderation` (bool) is accepted on item create and on `PATCH /courses/items/{item_id}/assessment`. It defaults to on for final assessments. Show it as a toggle: "Results need moderation before learners see them".

### 5.8 Course and curriculum writes (existing endpoints, new behaviour)

There are no new parameters, but with governance on:

| Situation | Response |
|---|---|
| First edit of a published course | Normal success. The working copy is created silently. |
| Ids in responses | May be working-copy ids, so re-fetch the manage view |
| Revision under review | `409` "This course's changes are under review (QA_REVIEW) and can't be edited. Withdraw the revision from review to make further changes." |
| Course archived | `409` "This course is archived - reinstate it before editing" |
| Editing an item that was deleted in the draft | `404` "Item not found in the working copy (it may have been removed)" |
| `PATCH /courses/{id}/publish` | `409` (not approved yet) or `403` (instructors can't publish) |

---

## 6. Errors and how to handle them

| Status | Typical message | What the UI should do |
|---|---|---|
| `400` | "There are no changes to submit" | Show it inline in the submit dialog |
| `400` | "A comment explaining the decision is required" | (Reviewer actions) require the comment field |
| `403` | "You can't submit this course for review" | Hide Submit; refresh `access` |
| `403` | "You contributed to this revision, so you can't approve any stage of it" | Show as an info message; never show approve buttons on own work |
| `404` | "…not found in the working copy" | Re-fetch the manage tree |
| `409` | "…under review… Withdraw the revision…" | Show a read-only banner with a **Withdraw to edit** button |
| `409` | "This course is archived" | Show an archived banner; disable editing |
| `409` | "already in moderation" | Re-fetch the mark; show its status |
| `422` | Validation error (e.g. `change_summary` too short) | Show the field errors from `errors[]` |

Every error body has the shape `{ "success": false, "message": "…", "errors"?: [{ "loc": [...], "msg": "…" }] }`.

---

## 7. Notifications

These arrive through the existing notification list and websocket. Route the `link` value inside the instructor app.

| `type` | Title example | `link` | Action |
|---|---|---|---|
| `REVIEW_COMMENT_ADDED` | "New review comment: {course}" | `/dashboard/approval-centre/revisions/{id}` | Open the revision's comments |
| `REVISION_STAGE_APPROVED` | "Academic review approved: {course}" | same | Refresh the stepper |
| `REVISION_RETURNED` | "Returned for revision: {course}" | same | Open the revision; editing is unlocked |
| `REVISION_REJECTED` | "Rejected: {course}" | same | Show the reason |
| `REVISION_ESCALATED` | "Escalated to high risk: {course}" | same | Refresh the stages |
| `REVISION_FORCE_APPROVED` | "Force-approved: {course}" | same | — |
| `REVISION_PUBLISHED` | "Published: {course} v1.1" | same | Show the live version |
| `MARKS_RETURNED` | "Mark returned for re-marking: {essay}" | `/dashboard/approval-centre/marks/{id}` | Open the mark |
| `ROLE_CHANGED` | "You were given the Course Lead role" | `/dashboard/approval-centre` | Refresh `GET /users/me` |

`metadata_json` carries `revision_id`, `course_id` or `mark_id` as strings.

---

## 8. When governance is switched off

When `access.governance_enabled === false`:
- Show the classic **Publish / Unpublish** toggle (`PATCH /courses/{id}/publish?is_published=…`). It works for course owners as before.
- Edits go live immediately; there is no working copy (`governance.layer` is always `"live"`).
- Hide Submit for review, the review stepper and the inbox drafts/returned tabs.
- Essay grading is one step (`is_published` is honoured) and each grade is still recorded in the history.
- The **History** tab still works: each publish records a version.

---

## 9. Implementation checklist

- [ ] Store `access` from the login session; refresh it with `GET /users/me` (§4.0).
- [ ] Course page: lifecycle badge, `current_version_label`, open-revision status pill (§5.1).
- [ ] Draft banner and **View live version** toggle (`?layer=live`) (§4.2).
- [ ] Re-fetch the manage tree after every curriculum write (§4.2, §5.8).
- [ ] **Review changes** screen from the diff (§5.2).
- [ ] **Preview as learner** using the student course-detail component (§5.2).
- [ ] **Submit for review** dialog: summary, reason, flags, raise risk (§5.3).
- [ ] Review stepper from `stages` (current round) with due dates and reviewers (§5.2).
- [ ] Read-only editor while under review, with **Withdraw to edit** (§4.4).
- [ ] Returned-for-revision banner, anchored comments, reply and resolve (§4.3, §5.4).
- [ ] **Discard draft** with confirmation (§5.3).
- [ ] **History** tab: versions and revisions (§5.5).
- [ ] Inbox with tabs and badges (§5.6).
- [ ] Essay marking: status badges, Save draft / Send to moderation, Dispute, history, and the `requires_moderation` toggle (§5.7).
- [ ] Notification routing (§7).
- [ ] Classic publish mode when governance is off (§8).
- [ ] Error handling per §6.
