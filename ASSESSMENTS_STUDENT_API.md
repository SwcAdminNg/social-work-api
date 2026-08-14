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
  List endpoints (`/quizzes/me`) use `PaginatedResponse<T>` with a `meta` block (`page`,
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
  "is_completed": true
}
```
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

## 5. "My quizzes" summary list

**`GET /learning/quizzes/me?status=PASSED&course_id=...&page=1&page_size=20`**

Lists every quiz assessment across courses the student has access to, with their latest status.
Both query params are optional filters.

| Param | Type | Notes |
|---|---|---|
| `status` | `"PASSED" \| "FAILED" \| "NOT_STARTED"` | Case-insensitive. |
| `course_id` | UUID | Restrict to one course. |

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
      "status": "PASSED",
      "score": 66.7,
      "attempted_at": "2026-08-10T14:00:00Z"
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 1, "total_pages": 1, "has_next": false, "has_previous": false }
}
```
`score`/`attempted_at` are `null` when `status: "NOT_STARTED"`.

There's no essay equivalent of this list endpoint yet — check individual essay items via §2.3 for
now.

---

## 6. Marking non-assessment items complete (for contrast)

**`POST /learning/courses/{course_id}/items/{item_id}/complete`** — only valid for `VIDEO`/`DOCUMENT`
items. Calling it on an `ASSESSMENT` item returns `400 "Cannot manually complete an assessment
item"` — completion for quizzes/essays happens automatically on submit instead.

---

## 7. Quick reference — endpoint list

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
| GET | `/learning/quizzes/me` | List all quizzes + status for the current user |
