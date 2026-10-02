# Learning Content Governance — Staff API Reference

This document covers how course content moves from **Create → Review → Quality Check → Approve → Publish**, implementing the *SWCL Learning Content Approval Hierarchy v1.0*. It is for the admin and instructor frontends.

Companion docs:
- [`APPROVAL_CENTRE_API.md`](./APPROVAL_CENTRE_API.md): the reviewer inbox and review screen.
- [`ESSAY_MODERATION_API.md`](./ESSAY_MODERATION_API.md): the marker → moderator → approver flow for essays.

> ℹ️ The API strips null/absent fields from JSON output. Treat a missing field as `null`/unset.

---

## Conventions

- **Auth**: every endpoint here needs `Authorization: Bearer <token>`.
- **Envelope**: `ApiResponse<T>`, i.e. `{ "success": true, "message": "...", "data": {...} }`. Lists marked *paginated* return `PaginatedResponse<T>` with a `meta` block.
- **Errors**:
  - `403` means you lack the permission, or separation of duties blocks you. The `message` says which, e.g. *"You contributed to this revision, so you can't approve any stage of it"*.
  - `409` means the revision or course is in the wrong state for that action, e.g. *"under review"*.
- **Feature flag**: everything below is active only when the server setting `CONTENT_GOVERNANCE_ENABLED=true`. While it is `false`:
  - Publishing works exactly as before: the owner or an admin toggles `PATCH /courses/{id}/publish`.
  - Edits go live immediately.
  - Every publish still records a **course version**, so history accrues from day one.

---

## User stories

- *As a Content Developer*, I edit a published course without learners seeing half-finished changes. I submit it for review, and I get it back with comments if something needs fixing.
- *As an Academic Reviewer / QA Reviewer / Course Lead / Head of Learning*, I see what changed, decide on my stage, and I'm never asked to approve my own work.
- *As a Platform Administrator*, I publish only what has every required approval, and I can archive or reinstate courses. I make no academic decisions.
- *As SWCL management*, every decision is traceable: who acted, on what version, when, why and with what result. Any earlier approved version can be restored.

---

## 1. Roles and permissions

Permissions, not job titles, gate every action. A person can hold several roles, each platform-wide or **scoped to one course**.

| Role | Permissions |
|---|---|
| `INSTRUCTOR` | CREATE_CONTENT, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW, MARK_ASSESSMENT |
| `CONTENT_DEVELOPER` | CREATE_CONTENT, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW |
| `ACADEMIC_REVIEWER` | ACADEMIC_REVIEW |
| `ASSESSMENT_MODERATOR` | MODERATE_ASSESSMENT |
| `QA_REVIEWER` | QA_REVIEW |
| `COURSE_LEAD` | APPROVE_COURSE, APPROVE_RESULTS, EDIT_DRAFT_CONTENT, SUBMIT_FOR_REVIEW |
| `LEAD_ASSESSOR` | APPROVE_RESULTS |
| `HEAD_OF_LEARNING` | FINAL_APPROVAL, FORCE_APPROVE, APPROVE_RESULTS |
| `PLATFORM_ADMIN` | PUBLISH_CONTENT, ARCHIVE_CONTENT, MANAGE_STAFF_ROLES, CREATE_CONTENT, EDIT_DRAFT_CONTENT |

**Implicit roles** need no setup:
- Every `ADMIN` account is a `PLATFORM_ADMIN`.
- Every `INSTRUCTOR` account holds `INSTRUCTOR` on the courses it owns.
- While the governance flag is **off**, admins also keep every permission (the old behaviour).

### 1.1 What can I do? (drive the UI from this)

`GET /governance/me/permissions?course_id={optional}`

```json
{
  "data": {
    "course_id": "4f42...",
    "governance_enabled": true,
    "roles": [
      { "role": "INSTRUCTOR", "course_id": "4f42...", "implicit": true },
      { "role": "QA_REVIEWER", "implicit": false, "assignment_id": "9a1..." }
    ],
    "permissions": ["CREATE_CONTENT", "EDIT_DRAFT_CONTENT", "MARK_ASSESSMENT", "QA_REVIEW", "SUBMIT_FOR_REVIEW"]
  }
}
```

### 1.2 Granting roles (MANAGE_STAFF_ROLES)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/admin/staff-roles?user_id=&role=&course_id=&include_revoked=` | List grants |
| `POST` | `/admin/staff-roles` | Body: `{ "user_id", "role", "course_id"?, "reason"?, "expires_at"? }`. Omit `course_id` for a platform-wide grant. `409` if the user already holds that role in that scope. |
| `POST` | `/admin/staff-roles/{assignment_id}/revoke` | Body: `{ "reason"? }`. The row is kept as history. |

Grants and revocations are audited, and the user gets a `ROLE_CHANGED` notification.

Bootstrapping from a deploy shell: `python -m app.scripts.bootstrap_governance HEAD_OF_LEARNING director@example.org`.

---

## 2. Revisions: the unit of review

A **revision** is one proposed change to one course, and it is what travels through review. A course has at most one open revision at a time.

| `kind` | When |
|---|---|
| `INITIAL` | A never-published course. Its own content *is* the draft. |
| `CHANGE` | Any edit to a published course. |
| `ROLLBACK` | Restoring an earlier version (§6). |
| `REINSTATE` | Bringing back an archived course (§7). |

### 2.1 Editing a published course: the working copy

You don't need any new endpoints to edit. **Keep using the existing course and curriculum endpoints** (`PATCH /courses/{id}`, sections, items, quiz questions and options, assessment settings, certificate settings). With governance on, for a **published** course:

1. **The first edit opens a hidden working copy automatically**, a full clone of the course. Learners keep seeing the published version, unchanged.
2. **Live ids keep working.** Send the ids you already have and the API maps them onto the working copy. Responses return *working-copy* ids, so **re-fetch the manage tree after a write** rather than patching local state with the returned id.
3. **These changes are held for review:**
   - the course's own academic fields: title, description, prerequisite, level, category, learning outcomes (`what_you_will_learn`), materials, requirements;
   - certificate settings.
4. **These changes still apply live immediately**, because they are operational:
   - price, free/exclusive flags, access dates, thumbnail, instructor credits;
   - **live-session scheduling** (time, duration, guest).
5. **While the revision is under review, editing returns `409`.** Withdraw it (§3) to make more changes.

**What the manage view shows:**
- `GET /courses/manage/{id}` now shows the working copy by default (`?layer=auto`) and includes a `governance` block.
- Use `?layer=live` to see what learners see, or `?layer=draft` to force the working copy.

```json
{
  "data": {
    "id": "4f42...", "title": "Child Protection Essentials (2026)", "governance_status": "PUBLISHED",
    "current_version_label": "1.0",
    "sections": [ /* working-copy content */ ],
    "governance": {
      "governance_enabled": true, "lifecycle": "PUBLISHED", "current_version_label": "1.0", "layer": "draft",
      "open_revision": { "id": "7c0...", "kind": "CHANGE", "status": "DRAFT", "round": 0, "is_editable": true }
    }
  }
}
```

The same block is available on its own at `GET /courses/{course_id}/governance`. To start a working copy without editing anything, call `POST /courses/{course_id}/revisions`.

### 2.2 Reading a revision

| Method | Path | Returns |
|---|---|---|
| `GET` | `/governance/revisions/{id}` | Full detail: stages (every round), decision history, contributors, open conditions, `available_actions` and `blocked_reason` for *you* |
| `GET` | `/governance/revisions/{id}/tree` | The working copy in the editor (manage) format |
| `GET` | `/governance/revisions/{id}/preview` | The working copy exactly as an enrolled learner will see it |
| `GET` | `/governance/revisions/{id}/diff` | Every change against the live course, each tagged with its risk |
| `GET` | `/courses/{course_id}/revisions` | All revisions of a course, newest first |

**Rendering actions:** render buttons from `available_actions`. Possible values are `EDIT`, `DISCARD`, `SUBMIT`, `WITHDRAW`, `CLAIM`, `APPROVE`, `APPROVE_WITH_MINOR_CHANGES`, `RETURN_FOR_REVISION`, `REJECT`, `ESCALATE`, `ASSIGN_REVIEWER`, `FORCE_APPROVE`, `OVERRIDE_RISK`, `PUBLISH`, `COMMENT` and `ATTACH_EVIDENCE`. When you can't decide the current stage, show `blocked_reason`.

**Diff format:** each change is `{ entity, key, op, label, fields, before, after, item_type, risk }`.
- `entity` is one of `course`, `section`, `item`, `video`, `document`, `link`, `assessment`, `assessment_settings`, `group_section`, `question` or `option`.
- `op` is one of `ADDED`, `REMOVED`, `MODIFIED` or `MOVED`.
- `label` is a readable path, e.g. *"Module 2 › Knowledge check › Q: Who is responsible…"*.

---

## 3. Submitting and the review pipeline

### 3.1 Submit

`POST /governance/revisions/{id}/submit` (requires SUBMIT_FOR_REVIEW)

```json
{
  "change_summary": "Updated to the 2026 statutory guidance",
  "reason": "Working Together 2026 replaced the 2023 edition",
  "declared_risk": "HIGH",
  "flags": ["SAFEGUARDING"]
}
```

**Risk** is computed from the changes:

| Risk | Examples | Stages |
|---|---|---|
| **LOW** | Title/typo fixes, link fixes, reordering, preview flag, durations | `QUICK_APPROVAL` (one QA Reviewer *or* Course Lead) |
| **MEDIUM** | New/removed lesson or module, new video or reading, question or essay wording, description changes, moving a lesson between modules | `ACADEMIC_REVIEW → QA_REVIEW → COURSE_LEAD_APPROVAL` |
| **HIGH** | New course; assessment added or removed; pass mark, attempts or time limit; a correct answer changed; questions added or removed; learning outcomes; certificate settings; any **flag** (SAFEGUARDING, LEGAL, POLICY, CERTIFICATE_RULE, CPD_RECOGNITION) | `… → FINAL_APPROVAL` (Head of Learning) |

Additional rules:
- **Assessment moderation:** any MEDIUM or HIGH change inside an assessment also adds `ASSESSMENT_MODERATION` after academic review. This is the framework's assessment design path.
- **Raising risk:** a submitter can raise the risk (`declared_risk`, `flags`) but never lower it. Only the Head of Learning can lower it (§3.4).
- **Version label:** `proposed_version_label` is set at submission. HIGH risk gives a major bump (1.x → 2.0); anything else a minor bump (1.0 → 1.1).

### 3.2 Statuses

A revision's `status` uses the framework's labels:

`DRAFT → SUBMITTED_FOR_REVIEW → ACADEMIC_REVIEW → ACADEMICALLY_APPROVED → (ASSESSMENT_MODERATION) → QA_REVIEW → QA_APPROVED → COURSE_APPROVED → FINAL_APPROVAL_REQUIRED → READY_TO_PUBLISH → PUBLISHED`

Off-path statuses:
- `RETURNED_FOR_REVISION` returns the revision to the author. Resubmitting starts a **new round** from the first stage.
- `REJECTED` and `WITHDRAWN` are terminal.

The `*_REVIEW` labels show while a reviewer has *claimed* that stage. `current_stage` always names the stage awaiting a decision.

### 3.3 Author actions

| Method | Path | Effect |
|---|---|---|
| `POST` | `/governance/revisions/{id}/withdraw` | Pull it out of review back to `DRAFT`, editable again |
| `POST` | `/governance/revisions/{id}/discard` | Abandon a draft (status `WITHDRAWN`). Live content is untouched. |

### 3.4 Reviewer actions

| Method | Path | Body | Who |
|---|---|---|---|
| `POST` | `/governance/revisions/{id}/claim` | — | An eligible reviewer takes the stage |
| `POST` | `/governance/revisions/{id}/assign` | `{ "reviewer_id", "due_at"? }` | Course Lead / Head of Learning assign anyone eligible; a reviewer may assign themselves |
| `POST` | `/governance/revisions/{id}/decision` | see below | The stage's reviewer |
| `POST` | `/governance/revisions/{id}/force-approve` | `{ "justification" }` (20+ chars) | Head of Learning: every remaining stage becomes `SKIPPED` |
| `POST` | `/governance/revisions/{id}/risk` | `{ "level", "reason" }` | Head of Learning re-rates risk; stages no longer needed are `SKIPPED` |

Decision body:

```json
{ "decision": "APPROVED_WITH_MINOR_CHANGES", "comment": "Fine overall", "conditions": ["Add feedback to Q3"] }
```

| `decision` | Effect |
|---|---|
| `APPROVED` | Advance to the next stage |
| `APPROVED_WITH_MINOR_CHANGES` | Advance. `conditions` are listed in `open_conditions` for the next reviewer to confirm. |
| `RETURNED_FOR_REVISION` | Back to the author. `comment` is required. |
| `REJECTED` | Closed. `comment` is required. |
| `ESCALATED` | Raise the risk (`escalate_to`) and/or add `flags`. The extra stages are inserted (e.g. a quick approval becomes the full path). `comment` is required. |

**Separation of duties** is enforced on every decision:
- Contributors (the author and anyone who edited the working copy) can't approve any stage.
- One person can't approve two different stages of the same revision.
- An assigned stage can only be decided by its assignee.
- Force-approval still can't be used on your own work.

### 3.5 Publishing (PUBLISH_CONTENT)

`POST /governance/revisions/{id}/publish` succeeds only from `READY_TO_PUBLISH`. Publishing does the following:
- It merges the working copy into the live course **in place**. Lesson, question and option ids don't change, so learner progress, quiz attempts, essay submissions and certificates stay attached.
- It records the new **version**, with a full content snapshot, the author, the reviewers, the approval date and the reason.
- If the set of lessons changed, it recalculates enrolled learners' progress. A new lesson un-completes a finished learner; a removed one can complete them.
- It sends the invitations for any newly published live sessions.

The legacy `PATCH /courses/{id}/publish?is_published=true` still works with governance on. It publishes the open revision only when it's `READY_TO_PUBLISH`, and otherwise returns `409` naming the stage it's waiting on. `is_published=false` archives the course.

---

## 4. Comments and evidence

| Method | Path | Notes |
|---|---|---|
| `GET` | `/governance/revisions/{id}/comments` | Threaded via `parent_id` |
| `POST` | `/governance/revisions/{id}/comments` | `{ "body", "parent_id"?, "anchor_type"?: "course"\|"section"\|"item"\|"question", "anchor_id"? }`. Anchor with the live id shown in the diff (`key`). |
| `PATCH` | `/governance/comments/{comment_id}/resolve` | |
| `GET` | `/governance/revisions/{id}/evidence` | Files include a short-lived `download_url` |
| `POST` | `/governance/revisions/{id}/evidence/upload-url` | `{ "title", "file_name", "content_type"? }` returns `{ evidence_id, upload_url }`. `PUT` the file, then call finalize. |
| `POST` | `/governance/evidence/{evidence_id}/finalize` | `{ "mime_type"?, "file_size_bytes"? }` |
| `POST` | `/governance/revisions/{id}/evidence/link` | `{ "title", "url" }` |

---

## 5. Versions

| Method | Path | Notes |
|---|---|---|
| `GET` | `/courses/{course_id}/versions` | `1.0, 1.1, 2.0…`, newest first. Each version has `author`, `reviewers`, `approved_at`, `published_at`, `published_by`, `reason`, `risk_level`, `is_current` and `has_snapshot`. |
| `GET` | `/courses/{course_id}/versions/{version_id}` | Includes the full `snapshot` |

Courses published before governance existed start at **1.0 (baseline)**. Run `python -m app.scripts.backfill_course_snapshots` once after deploying to capture their content; otherwise each baseline is captured the first time its course is edited.

---

## 6. Rollback (APPROVE_COURSE or FINAL_APPROVAL)

`POST /courses/{course_id}/versions/{version_id}/rollback` with body `{ "reason" }`:
- It builds a `ROLLBACK` revision whose working copy matches that version's snapshot.
- Lessons removed since then are *restored*, keeping their ids, along with any learner progress still attached.
- It requires **Final Approval from someone other than the person who started it**.
- Publishing it creates a *new* version (e.g. `2.1`) rather than rewriting history.

## 7. Archive and reinstate (ARCHIVE_CONTENT)

| Method | Path | Effect |
|---|---|---|
| `POST` | `/courses/{course_id}/archive` | `{ "reason"? }`. Hidden from learners (`is_published=false`, lifecycle `ARCHIVED`). Any open revision is withdrawn. |
| `POST` | `/courses/{course_id}/reinstate` | `{ "reason"? }`. Creates a LOW-risk `REINSTATE` revision, which goes through quick approval, then publish. |

## 8. Audit trail

`GET /governance/audit?course_id=&revision_id=&actor_id=&entity_type=&entity_id=&from=&to=` (*paginated*; requires FINAL_APPROVAL, PUBLISH_CONTENT or MANAGE_STAFF_ROLES)

Each row records:
- `actor_id` and the actor's permission codes at that moment;
- the entity, course, revision and version label;
- `action` (e.g. `SUBMITTED`, `DECISION_APPROVED`, `FORCE_APPROVED`, `PUBLISHED`, `COURSE_ARCHIVED`, `STAFF_ROLE_GRANTED`, `RESULT_PUBLISHED`);
- `from_status` → `to_status`, `comment` and `metadata_json`.

The table is append-only: the database itself rejects updates and deletes.

## 9. Notifications (in-app)

| Type | Recipients |
|---|---|
| `REVIEW_REQUESTED` | The reviewer pool for the next stage (excluding contributors and anyone already signed off), or just the assignee |
| `REVIEW_ASSIGNED` | The assignee |
| `REVISION_STAGE_APPROVED`, `REVISION_RETURNED`, `REVISION_REJECTED`, `REVISION_ESCALATED`, `REVISION_FORCE_APPROVED` | Contributors |
| `REVISION_READY_TO_PUBLISH` | Publishers |
| `REVISION_PUBLISHED` | Contributors and reviewers |
| `REVIEW_COMMENT_ADDED` | Everyone involved |

Links point to `/dashboard/approval-centre/revisions/{id}`.

## 10. Rolling out

1. Deploy, then run `alembic upgrade head` and `python -m app.scripts.backfill_course_snapshots`.
2. Grant reviewer roles: Academic Reviewer, QA Reviewer, Course Lead, Head of Learning, and Assessment Moderator if you'll use moderation.
3. Set `CONTENT_GOVERNANCE_ENABLED=true` for the environment.

Switching the flag back off returns to the old behaviour. **Publish or discard open revisions first**: a working copy left open while the flag is off is ignored, because edits go to the live course.
