# Assessments (Quiz, Essay & Quiz Group) — Student/User API Reference

This document covers the **student-facing** side of the generic Assessment system: taking a quiz,
submitting an essay, taking a quiz group (nested quizzes), and checking results. It's the
companion to [`ASSESSMENTS_INSTRUCTOR_ADMIN_API.md`](./ASSESSMENTS_INSTRUCTOR_ADMIN_API.md), which
covers how instructors configure these.

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
or `ASSESSMENT`. When it's `ASSESSMENT`, check `assessment_type` (`"QUIZ"`, `"ESSAY"`, or
`"QUIZ_GROUP"`) to know which set of fields/actions apply. `due_date` (if set) applies to all three.

`QUIZ_GROUP` ("nested quizzes") is a set of named sections, each its own mini quiz, answered
together in one sitting for a single overall score — with an optional countdown timer that
auto-submits and scores whatever was answered if time runs out. See §3b.

**Module gating**: a course's sections ("modules") can be sequential — some assessments are marked
as a section's *final assessment*, and you must pass one to unlock the next section. Fail one out
of retries and that section (or, if it's the last one, the *entire course*) resets and has to be
redone. See §7.

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

Each **section** also carries an `is_locked` flag (`LearningSectionDTO`) — see §7 for the full
module-gating flow:
```json
{ "id": "section-uuid", "title": "Module 2", "items": [ /* ... */ ], "is_locked": true }
```
Render locked sections/items greyed out and non-clickable — the item-content and submit endpoints
all 403 on a locked item anyway, but checking `is_locked` here lets you disable them proactively.
`estimated_minutes` is an optional, instructor-entered estimate of how long the item takes to
complete (in minutes) — a display hint only, not enforced or tracked against actual time spent.
Applies to every item type (`VIDEO`/`DOCUMENT`/`ASSESSMENT`); omitted/absent when the instructor
hasn't set one, same as any other null-stripped field.

This endpoint does **not** include quiz questions or essay prompts — fetch the item itself for
that (next).

### 2.3 Get one item's full content

**`GET /learning/courses/{course_id}/items/{item_id}`**

This is the main endpoint for actually rendering an assessment. Shape is `LearningItemContentDTO`;
fields present depend on `item_type`/`assessment_type`. `403` if the item's section is locked (§7)
- check `is_locked` from the curriculum endpoint before navigating here to avoid relying on the 403.

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
  "is_final_assessment": true,
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
- `is_final_assessment: true` means passing this unlocks the next module (or, if this is the
  course's last module, completes the course) - and running out of attempts without passing resets
  a module (or the whole course) - see §7. Render some kind of "this is a required final
  assessment, you have N attempts" banner when this is true.
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
  "is_final_assessment": false,
  "essay_question": "Describe a trauma-informed intervention you would use.",
  "essay_description": "Write 500-800 words. Reference at least one framework covered in this module.",
  "essay_submission_mode": "TEXT",
  "essay_pass_mark_percentage": 70,
  "essay_max_attempts": null,
  "essay_attempts_used": 0,
  "essay_attempts_remaining": null,
  "essay_submission": {
    "content_text": "My draft answer...",
    "document_file_name": null,
    "document_download_url": null,
    "submitted_at": "2026-08-10T14:00:00Z",
    "is_graded": false,
    "is_published": false,
    "score": null,
    "feedback": null,
    "passed": null
  }
}
```

- `essay_submission` is absent if the student hasn't submitted anything yet.
- `is_graded` = an instructor has scored it (`score` was set server-side). For a **regular** essay
  (`is_final_assessment: false` on the parent, same as before this feature), once graded you can no
  longer resubmit — full stop. For a **final** essay assessment, a *failed* grade instead re-opens
  it for another submission (as long as `essay_attempts_remaining` isn't `0`) — see §4.4.
- `essay_pass_mark_percentage`/`essay_max_attempts`/`essay_attempts_used`/`essay_attempts_remaining`
  are only meaningfully *enforced* when `is_final_assessment: true`, but are always present so you
  can show them either way. `essay_attempts_used` counts graded cycles (how many times an instructor
  has scored this submission), not raw resubmissions.
- `score`/`feedback`/`passed` are only ever non-null when `is_published: true` — even if
  `is_graded: true`, a not-yet-published grade shows them all `null`. Show something like "Your
  instructor is reviewing this" for `is_graded && !is_published`, vs "Submitted, awaiting review"
  for `!is_graded`. `passed` is `score >= essay_pass_mark_percentage` - only meaningful for a final
  essay assessment (always `null` on a regular essay, since there's nothing to pass/fail there).
- `document_download_url` (when `submission_mode = DOCUMENT`) is a freshly generated, short-lived
  presigned URL each time you call this endpoint.

#### Quiz group item response

```json
{
  "id": "item-uuid",
  "title": "Module 1 Final",
  "item_type": "ASSESSMENT",
  "is_completed": false,
  "assessment_type": "QUIZ_GROUP",
  "due_date": "2026-09-01T23:59:00Z",
  "quiz_group": {
    "max_attempts": 2,
    "attempts_used": 0,
    "attempts_remaining": 2,
    "pass_mark_percentage": 60,
    "show_result_to_student": true,
    "time_limit_seconds": 1800,
    "sections": [
      { "id": "section-1", "title": "Safety Principles", "order_index": 0, "question_count": 5 },
      { "id": "section-2", "title": "De-escalation", "order_index": 1, "question_count": 5 }
    ]
  }
}
```

Notes:
- **No questions here.** `sections[].question_count` only tells you how many questions each
  section will ask — the actual questions are only revealed once you start an attempt (§3b.1),
  since they're drawn at random each time (see §3b.3).
- If the student has an **in-progress** attempt (started but not yet submitted), `quiz_group` also
  includes `active_attempt` — see §3b.1, "resuming".
- If the student has a **submitted** attempt, `quiz_group` also includes `previous_result` — same
  shape as the submit response (§3b.2), reflecting the most recent submitted attempt.

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
    "result_visible": true,
    "section_reset": false,
    "course_reset": false
  }
}
```

- `message` is one of `"Quiz passed successfully"`, `"Quiz failed, please try again"`,
  `"Quiz submitted successfully"` (when `result_visible: false`), or — only when this quiz is a
  *final assessment* and this failed attempt was the last one allowed — `"Quiz failed - out of
  retries, this module has been reset"` / `"...the entire course has been reset"`.
- `section_reset`/`course_reset` are `true` exactly when the corresponding message above fires —
  see §7.2 for what to do when either is `true` (refresh the curriculum, redirect to the top of the
  reset module/course, everything the student had done there is gone).
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
| `403` | Not enrolled in the course, or the item's section is locked (§7). |
| `400` | Item isn't a quiz assessment; `due_date` has passed (`"The deadline for this quiz has passed"`); `max_attempts` reached (`"Maximum attempts (N) reached for this quiz"`). |
| `404` | Item/course not found. |

Check `attempts_remaining` from §2.3 before showing the "Submit" button/re-attempt option so you
can disable it proactively instead of relying on the 400.

---

## 3b. Taking a quiz group (nested quizzes)

Unlike a standalone quiz (one-shot: answer + submit in a single call), a quiz group attempt is
**stateful** — you start it, optionally autosave progress as the student answers, then submit. This
is what makes the timer/auto-submit and no-repeat-questions behavior possible.

### 3b.1 Start (or resume) an attempt

**`POST /learning/courses/{course_id}/items/{item_id}/quiz-group/start`**

No body. Call this when the student clicks "Start" on a quiz group.

```json
{
  "success": true,
  "message": "Quiz group attempt started",
  "data": {
    "attempt_id": "attempt-uuid",
    "started_at": "2026-08-23T10:00:00Z",
    "expires_at": "2026-08-23T10:30:00Z",
    "sections": [
      {
        "section_id": "section-1",
        "title": "Safety Principles",
        "questions": [
          {
            "id": "question-uuid",
            "text": "What is the first priority in a trauma-informed response?",
            "allow_multiple_answers": false,
            "multi_answer_mode": null,
            "options": [
              { "id": "opt-1", "text": "Establishing safety" },
              { "id": "opt-2", "text": "Documenting the incident" }
            ]
          }
        ]
      },
      { "section_id": "section-2", "title": "De-escalation", "questions": [ /* ... */ ] }
    ],
    "saved_answers": {}
  }
}
```

- `expires_at` is `null` if the group is untimed. Otherwise, run your countdown UI off it (not off
  `time_limit_seconds` + a client clock) so it stays correct even if the app was backgrounded.
- **Resuming**: if the student already has an in-progress attempt (e.g. they closed the tab and
  came back), calling `start` again returns **that same attempt** — same `attempt_id`, same drawn
  questions, same `expires_at`, plus whatever was last saved in `saved_answers` — instead of
  starting a new one. Always call `start` when the student opens the quiz group screen; don't try
  to cache attempt state client-side across sessions.
- If the previous attempt's timer had already run out by the time you call `start`, it gets
  auto-submitted first (see §3b.4) and this call then starts a **new** attempt (attempt-count
  permitting) with a fresh draw of questions.
- `400` if `max_attempts` is already reached, the group has no sections/questions configured yet,
  or the deadline (`due_date`) has passed.

### 3b.2 Submit the attempt

**`POST /learning/courses/{course_id}/items/{item_id}/quiz-group/submit`**

```json
{
  "attempt_id": "attempt-uuid",
  "answers": {
    "question-1-uuid": ["opt-1-uuid"],
    "question-2-uuid": ["opt-2-uuid", "opt-3-uuid"]
  }
}
```

Send **every** answer the student has given across **all** sections in one call — same
UUID-keyed-object convention as a standalone quiz (§3.1). A skipped question scores 0.

Response (`QuizGroupResultDTO`):
```json
{
  "success": true,
  "message": "Quiz group passed successfully",
  "data": {
    "attempt_id": "attempt-uuid",
    "score": 80.0,
    "passed": true,
    "auto_submitted": false,
    "sections": [
      { "section_id": "section-1", "title": "Safety Principles", "earned_points": 4.0, "total_questions": 5, "score_percent": 80.0 },
      { "section_id": "section-2", "title": "De-escalation", "earned_points": 4.0, "total_questions": 5, "score_percent": 80.0 }
    ],
    "correct_answers": null,
    "result_visible": true,
    "section_reset": false,
    "course_reset": false
  }
}
```

- `score`/`passed` are the **overall** result across every section combined (not per-section pass/
  fail — there's only one pass mark, at the group level).
- `sections[]` gives the per-section breakdown so you can show "4/5 on Safety Principles, 4/5 on
  De-escalation" alongside the overall score.
- `correct_answers` is intentionally always `null` here (unlike the standalone-quiz submit
  response) — since each attempt only sees a subset of a larger pool, showing the answer key would
  leak pool questions the student hasn't been tested on yet. Use `previous_result` from §2.3/§3b
  content if you need to review what was asked, or don't rely on a correct-answer key for quiz
  groups.
- `auto_submitted: true` means this call landed after the timer had already run out — same result
  shape either way, just a different `message` (`"Time's up - your quiz group was submitted
  automatically"`).
- `section_reset`/`course_reset` — same module-gating semantics as a standalone quiz's result (see
  §3.1/§7): `true` when this quiz group is a final assessment and this failed attempt was the last
  one allowed, with the message text changed to match (`"Quiz group failed - out of retries, this
  module has been reset"` etc.).
- `result_visible: false` (when the instructor set `show_result_to_student: false`) nulls out
  `score`/`passed`/`sections` the same way a standalone quiz does — the submission still counts.
- **Idempotent**: calling `submit` again with the same `attempt_id` after it's already been
  submitted (by you, or auto-submitted by the timer racing your call) just returns the existing
  result instead of erroring — safe to retry on a flaky connection.

### 3b.3 No repeated questions across retakes

Each section draws `questions_to_ask` questions from its pool at random, favoring ones the student
hasn't seen in any previous attempt on this item. You don't need to do anything for this — it's
automatic on `start`. Just don't assume attempt 2 will show the same questions as attempt 1 (it
usually won't, pool size permitting) — always render whatever `sections[].questions` the `start`/
resume response gives you, never a cached set from an earlier attempt.

### 3b.4 The timer and auto-submit

If the group has `time_limit_seconds` configured (§2.3), the attempt has a hard deadline
(`expires_at`). Two things you should implement:

1. **Client-side countdown + auto-submit-on-zero**: run a timer off `expires_at`, and when it hits
   zero, call the submit endpoint (§3b.2) automatically with whatever the student has answered so
   far — exactly the same call a manual "Submit" click makes. This is the primary way timeouts get
   scored promptly.
2. **Periodic autosave**, so a submission still happens (with a real score, not zero) even if the
   student's client crashes/loses connection before the auto-submit fires:

   **`POST /learning/courses/{course_id}/items/{item_id}/quiz-group/progress`**
   ```json
   { "attempt_id": "attempt-uuid", "answers": { "question-1-uuid": ["opt-1-uuid"] } }
   ```
   ```json
   { "success": true, "message": "Progress saved" }
   ```
   Call this periodically (e.g. every 10-30s, or on every answer change) while the student is
   working. It overwrites the attempt's saved answers each time — always send the **full** current
   answer set, not a diff. `400` (`"Time is up - this attempt was submitted automatically"`) if the
   timer had already run out by the time this call lands — treat that the same as a submit
   response: refresh the item content (§2.3) to show `previous_result`.

If the student never calls submit and the client never gets the chance to auto-submit (app closed,
etc.), the attempt isn't silently lost — the **next** time anything touches it (the student
reopening the item, or their next `start` call) it's lazily finalized server-side using whatever
was last saved via the progress endpoint, exactly as described above. There's no background job you
need to poll for this; it just resolves itself on next access.

---

## 4. Submitting an essay

Which endpoint you use depends on the essay's `essay_submission_mode` (from §2.3) — `TEXT` uses
one call, `DOCUMENT` uses a two-step upload-then-finalize flow (same pattern as course document
uploads elsewhere in this API).

**You can resubmit/overwrite your answer as many times as you like — as long as `is_graded` is
still `false` and (if set) `due_date` hasn't passed.** Once an instructor scores it, further submit
calls return `400` — **unless** this essay is a *final assessment* (§2.3/§7) and the grade was a
*failing* one with `essay_attempts_remaining` still above `0`, in which case your next submit call
succeeds and re-opens it (see §4.4). Passing always locks it, same as before.

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
| `403` | Not enrolled in the course, or the item's section is locked (§7). |
| `400` | Item isn't an essay assessment; you called `submit-text` on a `DOCUMENT`-mode essay (or vice versa) — `"This essay only accepts text/document submissions"`; `due_date` has passed — `"The deadline for this essay has passed"`; already graded and not eligible for a retry — `"This essay has already been graded and can no longer be resubmitted"`. |
| `404` | Item/course not found, or the essay itself isn't configured. |

### 4.4 Resubmitting after a failed final-assessment grade

Only relevant when `is_final_assessment: true` (§2.3). When the instructor grades it below
`essay_pass_mark_percentage` and `essay_attempts_remaining > 0`, the submission goes back to an
un-graded state as soon as you call `submit-text`/`submit-document` again — same request shape as
your first submission, nothing special to send. The response's `is_graded`/`score`/`feedback` all
reset to their "pending" values, and `essay_attempts_used` (from §2.3) stays at whatever it was —
it only increments when an instructor grades it, not when you resubmit. If `essay_attempts_remaining`
hits `0` on a failing grade, the module/course reset described in §7 fires instead, and your
essay submission is wiped along with everything else in the reset scope.

---

## 5. "My assessments" summary list

**`GET /learning/assessments/me?status=PASSED&course_id=...&assessment_type=QUIZ&page=1&page_size=20`**

Lists **every assessment — quiz, essay, and quiz group — across courses the student has access
to**, with its latest status, in one feed. All query params are optional filters. This replaces
the old quiz-only `/learning/quizzes/me` endpoint (renamed and broadened).

| Param | Type | Notes |
|---|---|---|
| `status` | `"NOT_STARTED" \| "PASSED" \| "FAILED" \| "SUBMITTED" \| "GRADED"` | Case-insensitive. See status meanings below. |
| `course_id` | UUID | Restrict to one course. |
| `assessment_type` | `"QUIZ" \| "ESSAY" \| "QUIZ_GROUP"` | Restrict to one assessment type. Case-insensitive. |

### Status values

| Status | Applies to | Meaning |
|---|---|---|
| `NOT_STARTED` | quiz, essay & quiz group | No attempt/submission yet. |
| `PASSED` | quiz & quiz group | Latest attempt scored ≥ `pass_mark_percentage`, and results are visible. |
| `FAILED` | quiz & quiz group | Latest attempt scored below the pass mark, and results are visible. |
| `SUBMITTED` | quiz, essay & quiz group | Quiz/quiz group: attempted, but `show_result_to_student` is off so pass/fail is withheld. Essay: submitted, not yet graded by the instructor. |
| `GRADED` | essay only | An instructor has scored the essay (regardless of whether the score is published yet — check `is_published`/`score` for that). |

A quiz group row uses the exact same `max_attempts`/`attempts_used`/`attempts_remaining`/
`pass_mark_percentage` fields as a quiz row (an in-progress, not-yet-submitted attempt doesn't
count toward `attempts_used` — only submitted ones do, same as `max_attempts` enforcement in §3b.1).

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
| `retakes=true` | Quiz and quiz-group items only, where you've used at least one attempt, the deadline (if any) hasn't passed, and either attempts are unlimited or `attempts_remaining > 0`. Essays never appear here — there's no "retake" concept for essays (see §4's resubmit-until-graded rule instead). |

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

## 7. Module gating and the redo-on-fail flow

A course's sections ("modules") can be sequential: some assessments are marked by the instructor
as their section's **final assessment** (`is_final_assessment: true`, visible per-assessment in
§2.3). You must **pass** a section's final assessment to unlock the **next** section. A section
with no final assessment configured just needs every item in it completed to unlock the next one —
no pass/fail involved there.

The final assessment on the course's **last** section doubles as the course final exam — passing it
completes the course.

### 7.1 Checking what's locked

**`GET /learning/courses/{course_id}/curriculum`** (§2.2) - each section has `is_locked`:
```json
{ "id": "section-uuid", "title": "Module 2", "items": [ /* ... */ ], "is_locked": true }
```
Use this to grey out locked modules in your sidebar/outline before the student even tries to open
one. If they navigate to a locked item directly anyway, `GET .../items/{item_id}` (§2.3) and every
submit/complete endpoint for that item **403s**: `"This module is locked - pass the previous
module's final assessment first"`.

### 7.2 What happens on a fail

Every final assessment has a retry cap (`max_attempts` for quiz/quiz-group, same field name on
essays now too — see `essay_max_attempts` in §2.3). If the student **fails and has no attempts
left**, one of two things happens automatically, as part of that submit/grade call:

- **Not the last section**: that whole module resets - every video/document/assessment in it goes
  back to not-completed, and every attempt/submission on its assessments is wiped (fresh attempt
  counters). The student has to redo the entire module, not just the final assessment.
- **The last section** (the course final exam): the **entire course** resets the same way, from
  module 1 onward.

You'll see this in the result of whatever action triggered it:
- Quiz submit (§3.1) / quiz group submit (§3b.2): `section_reset`/`course_reset` on the result, plus
  a matching `message`.
- A final essay (§4) being graded doesn't return a result to the student synchronously (grading is
  an instructor action) - the student finds out the next time they load the curriculum (§2.2, the
  module they were on is `is_locked` again / back to not-completed) or the item content (§2.3, their
  essay submission is simply gone - `essay_submission` absent again).

If the student still has retries left after a fail, nothing resets - they just retry the final
assessment itself, same as any other quiz retry.

### 7.3 What to do in the UI when a reset happens

Treat `section_reset`/`course_reset: true` (or noticing a module went from unlocked/completed back
to locked/not-completed on your next curriculum fetch) as a hard redirect: re-fetch the curriculum
(§2.2) and send the student back to the top of whatever got reset (the module, or module 1 if the
whole course reset). Don't try to preserve any in-progress local state for that scope — it no
longer matches the server, which has genuinely wiped it.

---

## 8. Marking non-assessment items complete (for contrast)

**`POST /learning/courses/{course_id}/items/{item_id}/complete`** — only valid for `VIDEO`/`DOCUMENT`
items. Calling it on an `ASSESSMENT` item returns `400 "Cannot manually complete an assessment
item"` — completion for quizzes/essays happens automatically on submit instead.

---

## 9. Quick reference — endpoint list

| Method | Path | Purpose |
|---|---|---|
| POST | `/learning/courses/{course_id}/enroll` | Enroll in a course |
| GET | `/learning/courses/{course_id}/curriculum` | Section/item outline |
| GET | `/learning/courses/{course_id}/items/{item_id}` | Full item content (quiz/essay/video/document) |
| POST | `/learning/courses/{course_id}/items/{item_id}/complete` | Complete a video/document item |
| POST | `/learning/courses/{course_id}/items/{item_id}/quiz/submit` | Submit quiz answers |
| POST | `/learning/courses/{course_id}/items/{item_id}/quiz-group/start` | Start/resume a quiz group attempt (§3b.1) |
| POST | `/learning/courses/{course_id}/items/{item_id}/quiz-group/progress` | Autosave in-progress quiz group answers (§3b.4) |
| POST | `/learning/courses/{course_id}/items/{item_id}/quiz-group/submit` | Submit a quiz group attempt (§3b.2) |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/submit-text` | Submit/resubmit a TEXT essay |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/upload-url` | Get presigned upload URL (DOCUMENT essay) |
| POST | `/learning/courses/{course_id}/items/{item_id}/essay/submit-document` | Finalize a DOCUMENT essay submission |
| GET | `/learning/assessments/me` | List all quizzes + essays + quiz groups, with filters (§5) |
| GET | `/learning/assessments/stats` | Dashboard summary stats (§6) |
