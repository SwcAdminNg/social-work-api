# Assessments (Quiz & Essay) — Student/User API Reference

This document covers the **student-facing** side of the generic Assessment system: taking a quiz,
submitting an essay, and checking results. It's the companion to
[`ASSESSMENTS_INSTRUCTOR_ADMIN_API.md`](./ASSESSMENTS_INSTRUCTOR_ADMIN_API.md), which covers how
instructors configure these.

Base URL prefix for everything below: `/learning`.

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>` for any authenticated
  user (`get_current_user`) — no special role needed, but the user must be **enrolled in the
  course** (`403 Forbidden, "Not enrolled"` otherwise).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  List endpoints (`/assessments/me`) use `PaginatedResponse<T>` with a `meta` block (`page`,
  `page_size`, `total_items`, `total_pages`, `has_next`, `has_previous`).
- **Null stripping**: absent/null fields are stripped from JSON responses — treat a missing field
  as `null`.
- **UUID-keyed JSON objects**: `QuizQuestionDTO`/answer maps use question and option **UUIDs as
  JSON object keys**. JSON forces object keys to be strings, so send/expect them as string UUIDs,
  e.g. `{"3f1b2c4a-....": ["opt-1-uuid", "opt-2-uuid"]}` — not an array of `{id, values}` pairs.

---

## 1. The mental model (recap)

A curriculum item you fetch via the curriculum/item-content endpoints can be `VIDEO`, `DOCUMENT`,
or `ASSESSMENT`. When it's `ASSESSMENT`, check `assessment_type` (`"QUIZ"` or `"ESSAY"`) to know
which set of fields/actions apply. `due_date` (if set) applies to both.

---

## 2. Getting to an assessment item

### 2.1 Enroll in a course (prerequisite for everything else)

**`POST /learning/courses/{course_id}/enroll`**

No body. Enrolls the current user if the course is free, or if it's covered by their active
subscription. Returns `402 Payment Required` if neither applies.

### 2.2 Curriculum overview

**`GET /learning/courses/{course_id}/curriculum`**

Returns section/item titles + completion flags (`is_completed`) for the whole course — use this to
build the sidebar/outline. Assessment items appear like any other item here:
```json
{
  "id": "item-uuid",
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "is_completed": true,
  "estimated_minutes": 15
}
```
`estimated_minutes` is an optional, instructor-entered estimate of how long the item takes to
complete (in minutes) — a display hint only, not enforced or tracked against actual time spent.
Applies to every item type (`VIDEO`/`DOCUMENT`/`ASSESSMENT`); omitted/absent when the instructor
hasn't set one, same as any other null-stripped field.

This endpoint does **not** include quiz questions or essay prompts — fetch the item itself for
that (next).

### 2.3 Get one item's full content

**`GET /learning/courses/{course_id}/items/{item_id}`**

This is the main endpoint for actually rendering an assessment. Shape is `LearningItemContentDTO`;
fields present depend on `item_type`/`assessment_type`.

#### Quiz item response

```json
{
  "id": "item-uuid",
  "title": "Module 1 Quiz",
  "item_type": "ASSESSMENT",
  "is_completed": true,
  "estimated_minutes": 15,
  "assessment_type": "QUIZ",
  "due_date": "2026-09-01T23:59:00Z",
  "max_attempts": 3,
  "attempts_used": 1,
  "attempts_remaining": 2,
  "pass_mark_percentage": 40,
  "show_result_to_student": true,
  "questions": [
    {
      "id": "question-uuid",
      "text": "Which of these are core principles of trauma-informed care?",
      "allow_multiple_answers": true,
      "multi_answer_mode": "OR",
      "options": [
        { "id": "opt-1", "text": "Safety" },
        { "id": "opt-2", "text": "Trustworthiness" },
        { "id": "opt-3", "text": "Punishment" }
      ]
    }
  ],
  "previous_attempt": {
    "score": 66.7,
    "passed": true,
    "answers": { "question-uuid": ["opt-1", "opt-2"] },
    "result_visible": true
  }
}
```

Notes:
- `options[].text` never includes which answer is correct — that's revealed (per-question) via
  `previous_attempt.answers`/the submit response's `correct_answers`, and only when
  `result_visible: true`.
- `max_attempts`/`attempts_remaining` are `null` when the instructor set unlimited attempts.
- `previous_attempt` reflects the **most recent** attempt, or is absent entirely if the student
  hasn't attempted yet.
- If `show_result_to_student` is `false`, `previous_attempt` still appears (so you know they
  attempted) but `score`, `passed`, and `answers` inside it are `null`, and `result_visible: false`
  — render something like "Submitted — results are not available for this quiz" rather than a
  score.

#### Essay item response

```json
{
  "id": "item-uuid",
  "title": "Reflective Essay",
  "item_type": "ASSESSMENT",
  "is_completed": false,
  "estimated_minutes": 45,
  "assessment_type": "ESSAY",
  "due_date": null,
  "essay_question": "Describe a trauma-informed intervention you would use.",
  "essay_description": "Write 500-800 words. Reference at least one framework covered in this module.",
  "essay_submission_mode": "TEXT",
  "essay_submission": {
    "content_text": "My draft answer...",
    "document_file_name": null,
    "document_download_url": null,
    "submitted_at": "2026-08-10T14:00:00Z",
    "is_graded": false,
    "is_published": false,
    "score": null,
    "feedback": null
  }
}
```

- `essay_submission` is absent if the student hasn't submitted anything yet.
- `is_graded` = an instructor has scored it (`score` was set server-side) — **once true, you can no
  longer resubmit** (see §4).
- `score`/`feedback` are only ever non-null when `is_published: true` — even if `is_graded: true`,
  a not-yet-published grade shows `score: null, feedback: null`. Show something like "Your
  instructor is reviewing this" for `is_graded && !is_published`, vs "Submitted, awaiting review"
  for `!is_graded`.
- `document_download_url` (when `submission_mode = DOCUMENT`) is a freshly generated, short-lived
  presigned URL each time you call this endpoint.

---

## 3. Taking a quiz

### 3.1 Submit answers

**`POST /learning/courses/{course_id}/items/{item_id}/quiz/submit`**

```json
{
  "answers": {
    "question-1-uuid": ["opt-2-uuid"],
    "question-2-uuid": ["opt-1-uuid", "opt-3-uuid"]
  }
}
```

- Include an entry per question you answered; a question you skip is scored as 0 correct.
- For multi-answer questions, send **all** option IDs you're selecting for that question in the
  array.

Response (`QuizResultDTO`):
```json
{
  "success": true,
  "message": "Quiz passed successfully",
  "data": {
    "score": 66.7,
    "passed": true,
    "correct_answers": { "question-1-uuid": ["opt-2-uuid"], "question-2-uuid": ["opt-1-uuid", "opt-3-uuid"] },
    "result_visible": true
  }
}
```

- `message` is one of `"Quiz passed successfully"`, `"Quiz failed, please try again"`, or
  `"Quiz submitted successfully"` (when `result_visible: false` — score is withheld, don't infer
  pass/fail from the message in that case, there's nothing to infer).
- When `result_visible: false`, `score`/`passed`/`correct_answers` are all `null` — the submission
  is still recorded and counted against `attempts_used`, the student just doesn't get shown how
  they did.
- **Every submit counts as an attempt**, even a repeat/practice one, and re-scores from scratch —
  there's no "save draft" concept for quizzes.

### 3.2 Scoring, so you can explain results in the UI

- Single-answer question: correct only if you selected exactly the right option.
- Multi-answer, `multi_answer_mode: "AND"`: correct only if you selected **exactly** the full
  correct set (nothing missing, nothing extra) — all or nothing.
- Multi-answer, `multi_answer_mode: "OR"`: **partial credit** — you get credit for
  `(number of correct options you ticked) / (total correct options for that question)`. Ticking
  extra wrong options doesn't subtract, but doesn't help either.
- Every question is worth 1 point regardless of option count. Final `score` = average of
  per-question points × 100, compared against `pass_mark_percentage` to produce `passed`.

### 3.3 Error responses

| Status | When |
|---|---|
| `403` | Not enrolled in the course. |
| `400` | Item isn't a quiz assessment; `due_date` has passed (`"The deadline for this quiz has passed"`); `max_attempts` reached (`"Maximum attempts (N) reached for this quiz"`). |
| `404` | Item/course not found. |

Check `attempts_remaining` from §2.3 before showing the "Submit" button/re-attempt option so you
can disable it proactively instead of relying on the 400.

---

## 4. Submitting an essay

Which endpoint you use depends on the essay's `essay_submission_mode` (from §2.3) — `TEXT` uses
one call, `DOCUMENT` uses a two-step upload-then-finalize flow (same pattern as course document
uploads elsewhere in this API).

**You can resubmit/overwrite your answer as many times as you like — as long as `is_graded` is
still `false` and (if set) `due_date` hasn't passed.** Once an instructor scores it, further
submit calls return `400`. There's currently no way to reopen a graded essay from the student side.

### 4.1 Text essay

**`POST /learning/courses/{course_id}/items/{item_id}/essay/submit-text`**
```json
{ "content_text": "My essay answer, 500-800 words..." }
```
Response (`EssaySubmissionDTO`, same shape as `essay_submission` in §2.3):
```json
{
  "success": true,
  "message": "Essay submitted successfully",
  "data": {
    "content_text": "My essay answer, 500-800 words...",
    "document_file_name": null,
    "document_download_url": null,
    "submitted_at": "2026-08-14T10:00:00Z",
    "is_graded": false,
    "is_published": false,
    "score": null,
    "feedback": null
  }
}
```

### 4.2 Document essay (two steps)

**Step 1 — get an upload URL:**

**`POST /learning/courses/{course_id}/items/{item_id}/essay/upload-url`**
```json
{ "file_name": "my-essay.pdf" }
```
```json
{
  "success": true,
  "message": "Upload URL generated successfully",
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/...",
    "storage_key": "essays/{item_id}/{user_id}/....-my-essay.pdf"
  }
}
```
`upload_url` is a presigned R2 `PUT` URL — upload the raw file bytes directly to it from the
client (`PUT {upload_url}` with the file as the body). The API server never sees the file.

**Step 2 — confirm the upload:**

**`POST /learning/courses/{course_id}/items/{item_id}/essay/submit-document`**
```json
{ "storage_key": "essays/{item_id}/{user_id}/....-my-essay.pdf", "file_name": "my-essay.pdf" }
```
(`mime_type` is also accepted, optional.) Response shape is the same `EssaySubmissionDTO` as §4.1,
with `document_file_name`/`document_download_url` populated instead of `content_text`.

Requesting a new `upload-url` and calling `submit-document` again is exactly how you'd resubmit a
document essay.

### 4.3 Error responses

| Status | When |
|---|---|
| `403` | Not enrolled in the course. |
| `400` | Item isn't an essay assessment; you called `submit-text` on a `DOCUMENT`-mode essay (or vice versa) — `"This essay only accepts text/document submissions"`; `due_date` has passed — `"The deadline for this essay has passed"`; already graded — `"This essay has already been graded and can no longer be resubmitted"`. |
| `404` | Item/course not found, or the essay itself isn't configured. |

---

## 5. "My assessments" summary list

**`GET /learning/assessments/me?status=PASSED&course_id=...&assessment_type=QUIZ&page=1&page_size=20`**

Lists **every assessment — quiz and essay — across courses the student has access to**, with its
latest status, in one feed. All query params are optional filters. This replaces the old
quiz-only `/learning/quizzes/me` endpoint (renamed and broadened).

| Param | Type | Notes |
|---|---|---|
| `status` | `"NOT_STARTED" \| "PASSED" \| "FAILED" \| "SUBMITTED" \| "GRADED"` | Case-insensitive. See status meanings below. |
| `course_id` | UUID | Restrict to one course. |
| `assessment_type` | `"QUIZ" \| "ESSAY"` | Restrict to one assessment type. Case-insensitive. |

### Status values

| Status | Applies to | Meaning |
|---|---|---|
| `NOT_STARTED` | quiz & essay | No attempt/submission yet. |
| `PASSED` | quiz only | Latest attempt scored ≥ `pass_mark_percentage`, and results are visible. |
| `FAILED` | quiz only | Latest attempt scored below the pass mark, and results are visible. |
| `SUBMITTED` | quiz & essay | Quiz: attempted, but `show_result_to_student` is off so pass/fail is withheld. Essay: submitted, not yet graded by the instructor. |
| `GRADED` | essay only | An instructor has scored the essay (regardless of whether the score is published yet — check `is_published`/`score` for that). |

### Response shape (`UserAssessmentDTO`)

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "item_id": "item-uuid",
      "title": "Module 1 Quiz",
      "course_id": "course-uuid",
      "course_title": "Intro to Trauma-Informed Care",
      "assessment_type": "QUIZ",
      "due_date": "2026-09-01T23:59:00Z",
      "status": "PASSED",
      "score": 66.7,
      "last_activity_at": "2026-08-10T14:00:00Z",
      "max_attempts": 3,
      "attempts_used": 1,
      "attempts_remaining": 2,
      "pass_mark_percentage": 40
    },
    {
      "item_id": "item-uuid-2",
      "title": "Reflective Essay",
      "course_id": "course-uuid",
      "course_title": "Intro to Trauma-Informed Care",
      "assessment_type": "ESSAY",
      "due_date": null,
      "status": "SUBMITTED",
      "score": null,
      "last_activity_at": "2026-08-11T09:00:00Z",
      "is_graded": false,
      "is_published": false
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

Field notes:
- `max_attempts`/`attempts_used`/`attempts_remaining`/`pass_mark_percentage` are only meaningful
  (non-`null`) for `assessment_type: "QUIZ"` rows — `null` on essay rows.
- `is_graded`/`is_published` are only meaningful for `assessment_type: "ESSAY"` rows — `null` on
  quiz rows.
- `score` follows the same visibility rules as everywhere else: `null` for a quiz whose
  `show_result_to_student` is off, and `null` for an essay that isn't `is_published` yet — even if
  it's already `is_graded`.
- `last_activity_at` is the latest quiz-attempt timestamp or the essay's `submitted_at`, whichever
  applies — use it as a generic "last touched" timestamp for sorting/display.

### 5.1 Shortcut filters: upcoming / completed / retakes

Three extra boolean query params, all default `false`, all combine with each other and with
`status`/`course_id`/`assessment_type` as **AND** (so don't set two that contradict each other,
e.g. `upcoming=true&completed=true` will just return nothing):

| Param | Meaning |
|---|---|
| `upcoming=true` | Has a `due_date` in the future **and** hasn't been started yet (`status: NOT_STARTED`). This is a to-do/deadline view, not "everything with a future due date" — something you've already submitted with a future due date doesn't count as "upcoming". |
| `completed=true` | Shorthand for "`status` is not `NOT_STARTED`" — i.e. attempted/submitted at least once, regardless of pass/fail/graded state. |
| `retakes=true` | Quiz items only, where you've used at least one attempt, the deadline (if any) hasn't passed, and either attempts are unlimited or `attempts_remaining > 0`. Essays never appear here — there's no "retake" concept for essays (see §4's resubmit-until-graded rule instead). |

### 5.2 Date-range filtering

`GET /learning/assessments/me?start_date=2026-08-01T00:00:00Z&end_date=2026-08-31T23:59:59Z`

Both `start_date` and `end_date` are optional ISO 8601 datetimes. **The range filters by
`due_date`.** Omit both for lifetime data (the default). Important consequence: if a date range is
given, any assessment with **no `due_date` set** is excluded from the results (there's nothing to
compare it against) — only assessments with `due_date` set at all are affected by this. With no
range given, everything is included regardless of `due_date`.

---

## 6. Assessment stats

**`GET /learning/assessments/stats`**

One call for a dashboard summary card. Same optional `start_date`/`end_date` params as §5.2, same
`due_date`-based range semantics, same lifetime-by-default behavior.

```http
GET /learning/assessments/stats
GET /learning/assessments/stats?start_date=2026-08-01T00:00:00Z&end_date=2026-08-31T23:59:59Z
```

Response (`AssessmentStatsDTO`):
```json
{
  "success": true,
  "message": "Assessment stats retrieved successfully",
  "data": {
    "upcoming_count": 2,
    "completed_count": 9,
    "average_score_percentage": 68.75,
    "retakes_available_count": 6
  }
}
```

| Field | Definition |
|---|---|
| `upcoming_count` | Count of assessments (quiz + essay) matching the `upcoming=true` rule from §5.1: future `due_date`, not yet started. |
| `completed_count` | Count of assessments matching the `completed=true` rule from §5.1: `status != NOT_STARTED`. |
| `average_score_percentage` | Mean of `score` across **all** assessments in scope that currently have a visible score (a quiz with `show_result_to_student=false` or an essay that isn't `is_published` yet doesn't contribute — its score is unknown to the student, so it's excluded, not counted as 0). `null` if nothing in scope has a visible score yet. |
| `retakes_available_count` | Count of assessments matching the `retakes=true` rule from §5.1. |

---

## 7. Marking non-assessment items complete (for contrast)

**`POST /learning/courses/{course_id}/items/{item_id}/complete`** — only valid for `VIDEO`/`DOCUMENT`
items. Calling it on an `ASSESSMENT` item returns `400 "Cannot manually complete an assessment
item"` — completion for quizzes/essays happens automatically on submit instead.

---

## 8. Quick reference — endpoint list

| Method | Path | Purpose |
|---|---|---|
| POST | `/learning/courses/{course_id}/enroll` | Enroll in a course |
| GET | `/learning/courses/{course_id}/curriculum` | Section/item outline |
| GET | `/learning/courses/{course_id}/items/{item_id}` | Full item content (quiz/essay/video/document) |
| POST | `/learning/courses/{course_id}/items/{item_id}/complete` | Complete a video/document item |
| POST | `/learning/courses/{course_id}/items/{item_id}/quiz/submit` | Submit quiz answers |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/submit-text` | Submit/resubmit a TEXT essay |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/upload-url` | Get presigned upload URL (DOCUMENT essay) |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/submit-document` | Finalize a DOCUMENT essay submission |
| GET | `/learning/assessments/me` | List all quizzes + essays, with filters (§5) |
| GET | `/learning/assessments/stats` | Dashboard summary stats (§6) |
