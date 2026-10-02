# Instructor: endpoint changes

For the instructor app. This covers instructors (`user_type = INSTRUCTOR`), who hold the `INSTRUCTOR` role on courses they own, and accounts given a `CONTENT_DEVELOPER` or course-scoped `COURSE_LEAD` role.

Labels used below:
- **[always]** applies regardless of the flag.
- **[governance on]** applies only when `CONTENT_GOVERNANCE_ENABLED=true`.

See [README](./README.md) for the flag.

---

## 1. What changes for an instructor, in one paragraph

**[governance on]**
- An instructor still builds and edits courses with the same endpoints.
- They **can no longer publish or unpublish** a course themselves. Instead they **submit it for review**; reviewers approve it and a platform admin publishes it.
- Edits to a course that is already live go into a **hidden working copy**. Learners see the old version until the changes are approved and published.
- For final-assessment essays, an instructor's grade becomes a **draft mark** that a moderator checks before learners see it.

Instructors' permissions: `CREATE_CONTENT`, `EDIT_DRAFT_CONTENT`, `SUBMIT_FOR_REVIEW` and `MARK_ASSESSMENT`, all on their own courses. Check them with `GET /governance/me/permissions?course_id=…`.

---

## 2. Changed existing endpoints

### 2.1 `PATCH /courses/{id}/publish?is_published=…`

**[always]**
- The response's course object has `governance_status` and `current_version_label`.
- On a publish, the server also records a version.

**[governance on]** Instructors don't hold `PUBLISH_CONTENT` or `ARCHIVE_CONTENT`, so:

| Call | Result |
|---|---|
| `is_published=true` | `409` (`Nothing to publish: submit the course for review first`, or the revision isn't approved yet). Once it is `READY_TO_PUBLISH`, it returns `403`: only a platform admin publishes. |
| `is_published=false` | `403`. Only a platform admin archives. |

👉 Replace the instructor's **Publish** button with **Submit for review** (§3.2) and show the review status.

### 2.2 `GET /courses/manage/{id}`

**[always]**
- New `?layer=auto|live|draft` query param.
- New `governance` block in the response:
  ```json
  "governance": {
    "governance_enabled": true, "lifecycle": "PUBLISHED", "current_version_label": "1.0", "layer": "draft",
    "open_revision": { "id": "7c0…", "kind": "CHANGE", "status": "DRAFT", "round": 0, "is_editable": true }
  }
  ```

**[governance on]**
- By default, the response shows the **working copy**: its sections, plus pending changes to title, description, learning outcomes and so on.
- `?layer=live` shows what learners currently see.
- Show a banner such as *"Draft v1.1 – unpublished changes"* when `governance.layer == "draft"`.

### 2.3 `GET /courses/manage`

**[always]** Instructors still see the courses they own. Users with a **course-scoped** editing role (e.g. a Course Lead on course X) now also see those courses in the list.

### 2.4 Editing endpoints

These endpoints are affected:
- **Course:** `PATCH /courses/{id}`
- **Sections:** create, update, delete and reorder
- **Items:** create, update, delete and reorder
- **Content:** document finalize, video refresh-upload
- **Assessments:** `PATCH /courses/items/{item_id}/assessment`, quiz and quiz-group questions and options, AI quiz generation
- **Certificates:** `PATCH /certificates/courses/{course_id}/settings`

**[always]**
- Deleting a document item no longer removes the file from storage.
- These routes now also accept users who hold a content staff role on a plain user account, e.g. a Content Developer.

**[governance on]**

| Situation | Behaviour |
|---|---|
| Course never published | Edits apply directly, as before. The first edit opens the course's `INITIAL` revision. |
| Course published, first edit | Opens a working copy automatically. Learners are unaffected. |
| Ids you send | Live ids or working-copy ids both work. |
| Ids you get back | Working-copy ids. **Re-fetch the manage tree after each write.** |
| Course details (title, description, prerequisite, level, category, learning outcomes, materials, requirements) | Held in the working copy until published |
| Certificate settings | Held in the working copy (high risk: needs Head of Learning approval) |
| Price, access dates, thumbnail, instructor credits | Apply immediately, as before |
| Live session time, duration or guest | Apply immediately, as before, including the reschedule emails. A live session *added* in the working copy only sends invites once it is published. |
| Revision submitted, under review | Every write returns `409`. Withdraw it first (§3.2). |
| Course archived | Every write returns `409` |

### 2.5 Essay grading

**`GET /courses/items/{item_id}/essay/submissions`**

**[always]** Each row gains:
- `result_status`
- `current_mark_id`
- `working_score`

**`POST /courses/items/{item_id}/essay/submissions/{user_id}/grade`**

**[always]**
- **New optional body fields:** `recommendation` (`PASS` or `FAIL`) and `submit_for_moderation`.
- **The response `data` is now the mark record.**
- **History is kept.** Re-grading never erases an earlier grade.

**[governance on]**, essay with `requires_moderation` (the default for **final** assessments):
- **What the call does:** it saves a draft mark, and `is_published` is ignored.
- **Editing the draft:** call it again to update your draft while it is still yours (`DRAFT_MARK` or `RETURNED_TO_MARKER`).
- **Once in moderation:** a further call returns `409`, because the mark is with the moderator.
- **The student** sees "submitted, awaiting result" until the result is published.

Essays without `requires_moderation` grade in one step, exactly as before.

### 2.6 Essay settings

**[always]** `essay_settings.requires_moderation` (bool) is accepted on item create and on `PATCH /courses/items/{item_id}/assessment`, and is returned in the manage tree. It defaults to `is_final_assessment`.

---

## 3. New endpoints for instructors

### 3.1 Course governance state and versions

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/courses/{course_id}/governance` | Lifecycle, current version, open revision |
| `POST` | `/courses/{course_id}/revisions` | Start a working copy without editing anything yet |
| `GET` | `/courses/{course_id}/revisions` | Revision history |
| `GET` | `/courses/{course_id}/versions` | Version history: who wrote, reviewed and published each version, and why |
| `GET` | `/courses/{course_id}/versions/{version_id}` | One version with its content snapshot |

### 3.2 Working on your revision

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/governance/revisions/{id}` | Status, stages, reviewer decisions, comments, `available_actions` |
| `GET` | `/governance/revisions/{id}/diff` | What you changed against the live course, with a risk level per change. Show it before submitting. |
| `GET` | `/governance/revisions/{id}/preview` | Your changes exactly as learners will see them |
| `POST` | `/governance/revisions/{id}/submit` | `{ change_summary (5+ chars), reason?, declared_risk?, flags? }` |
| `POST` | `/governance/revisions/{id}/withdraw` | Pull it back out of review to keep editing |
| `POST` | `/governance/revisions/{id}/discard` | Throw the draft away; the live course is untouched |
| `GET`/`POST` | `/governance/revisions/{id}/comments` | Reply to reviewers: `{ body, parent_id?, anchor_type?, anchor_id? }` |
| `PATCH` | `/governance/comments/{comment_id}/resolve` | Mark a reviewer comment as done |

**How submission works:**
- **Routing.** On submit, the server rates the risk and routes the revision:
  - *Low* (typo or link fixes) → quick approval.
  - *Medium* (new lesson or reading) → Academic → QA → Course Lead.
  - *High* (new course, assessment, pass mark or answer changes, learning outcomes, certificate settings) → the same path plus Head of Learning.
- **Flags.** Instructors can tick flags (`SAFEGUARDING`, `LEGAL`, `POLICY`, `CERTIFICATE_RULE`, `CPD_RECOGNITION`) to force the high-risk path. They can't lower the risk.
- **Returned work.** If a reviewer returns the work, `status` becomes `RETURNED_FOR_REVISION`. The instructor edits again and resubmits, which starts a new review round. Earlier comments and decisions stay visible.
- **Self-approval.** An instructor can never approve their own revision, even if they also hold a reviewer role.

### 3.3 Inbox

`GET /governance/approval-centre?view=returned_to_me|my_drafts|recently_approved|recently_rejected` (paginated) shows the instructor's work coming back from review, plus their essay marks that were returned or are still drafts. Use `GET /governance/approval-centre/counts` for badges.

### 3.4 Essay marks (as the marker)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/essay-marks/{mark_id}/submit` | Send your draft (or returned) mark to the moderator |
| `POST` | `/essay-marks/{mark_id}/dispute` | `{ note }`: contest the moderator's amendment. A Course Lead or Lead Assessor settles it. |
| `GET` | `/essay-marks/{mark_id}` | The mark with moderator notes and `available_actions` |
| `GET` | `/courses/items/{item_id}/essay-marks?status=` | Marks on one essay |
| `GET` | `/courses/items/{item_id}/essay/submissions/{user_id}/marks` | One learner's full marking history |

An instructor who is also given a `COURSE_LEAD` role can approve and publish results (`/essay-marks/{id}/approve`, `/courses/items/{item_id}/essay-marks/publish`), but never for marks they made or moderated themselves.

---

## 4. New notifications an instructor may receive

| Type | When |
|---|---|
| `REVISION_STAGE_APPROVED` | A reviewer approved a stage |
| `REVISION_RETURNED` | Returned for revision (the reviewer's comment is in `body`) |
| `REVISION_REJECTED` | Rejected |
| `REVISION_ESCALATED` | Escalated to a higher risk level |
| `REVISION_FORCE_APPROVED` | Force-approved by the Head of Learning |
| `REVISION_PUBLISHED` | Published as a new version |
| `REVIEW_COMMENT_ADDED` | New comment on the revision |
| `MARKS_RETURNED` | The moderator returned or amended a mark |
| `ROLE_CHANGED` (existing type) | They were given or lost a role |

Their `link` values point at `/dashboard/approval-centre/revisions/{id}` or `/dashboard/approval-centre/marks/{id}`.

---

## 5. Redo checklist (instructor app)

- [ ] Replace **Publish/Unpublish** with **Submit for review**, **Withdraw** and **Discard**, driven by `available_actions` (§2.1, §3.2).
- [ ] Course editor:
  - [ ] draft banner and live/draft toggle (§2.2);
  - [ ] re-fetch the manage tree after every write;
  - [ ] handle `409` while under review or archived (§2.4).
- [ ] Before submitting, show a "What changed" screen using the diff and preview (§3.2).
- [ ] Review status panel: stage timeline, reviewer comments with replies, and the returned-for-revision state (§3.2).
- [ ] Version history tab (§3.1).
- [ ] Inbox: returned to me and my drafts (§3.3).
- [ ] Essay grading:
  - [ ] show `result_status`;
  - [ ] add "Send to moderation" and "Dispute";
  - [ ] show marking history (§2.5, §3.4);
  - [ ] add the `requires_moderation` toggle on essay settings (§2.6).
- [ ] Handle the new notification types and links (§4).
