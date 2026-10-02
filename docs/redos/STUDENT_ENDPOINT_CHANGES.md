# Student: endpoint changes

For the student app. **No student endpoint was added or removed, and no request body changed.** A few responses gain fields, and some behaviour changes when content governance is on.

Labels used below:
- **[always]** applies regardless of the flag.
- **[governance on]** applies only when `CONTENT_GOVERNANCE_ENABLED=true`.

See [README](./README.md) for the flag.

---

## 1. Changed responses

### 1.1 Course objects gain two fields **[always]**

These endpoints return course objects:
- `GET /courses`, `/courses/featured`, `/courses/recent`, `/courses/{slug}`
- `GET /courses/enrolled`, `/courses/bookmarked`
- `GET /learning/courses`

Their course objects now include:

| Field | Values | Use |
|---|---|---|
| `governance_status` | `DRAFT`, `PUBLISHED`, `ARCHIVED` | Students only ever see `PUBLISHED` in public listings; it's safe to ignore |
| `current_version_label` | e.g. `"1.0"`, `"2.1"` | Optional: show "Version 2.1" or "Updated" on the course page |

Both are optional for the UI. Nothing breaks if they're ignored.

### 1.2 Essay results **[governance on]**

This applies to `GET /learning/courses/{course_id}/items/{item_id}` (the `essay_submission` block) and `GET /learning/assessments/me`.

For essays that need moderation (usually **final** assessments), the result goes through Marker → Moderator → Approver. Until it is released:
- `essay_submission.is_graded` is `false` and `score` and `feedback` are absent, even if the instructor has already marked it;
- in `/learning/assessments/me` the status stays `SUBMITTED`, not `GRADED`.

👉 Show "Submitted – awaiting result" rather than "Not graded yet". Results can take longer than before because they're checked by a second person.

When the result is released, it behaves exactly as before:
- `score`, `feedback` and `passed` appear;
- passing unlocks the next module;
- running out of retries resets the module or course.

---

## 2. Changed behaviour

### 2.1 Enrolling in an unpublished course **[always]**

`POST /learning/courses/{course_id}/enroll` now returns **`404 Course not found`** for a course that isn't published, including draft and archived courses. Before, a free unpublished course could be enrolled in by id. Learners who are already enrolled are unaffected.

### 2.2 Resubmitting an essay while it's being marked **[governance on]**

`POST /learning/courses/{course_id}/items/{item_id}/essay/submit-text` and `.../essay/submit-document` now return **`400 "This essay is being marked and can't be changed until the result is released"`** once a marker has started marking a moderated essay.

👉 Disable the edit/resubmit button and show that message. Resubmission after a *released* failed result (when retries remain) works as before.

### 2.3 Course content changes appear all at once **[governance on]**

Instructors' edits to a course a student is taking no longer appear piece by piece. They appear together when the new version is published. No API change is involved; it's just worth knowing when testing.

When a new version adds lessons:
- the course's `has_new_content` flag turns on, as before;
- a student who had **completed** the course may go back to *in progress* until they complete the new lessons, as already happened when lessons were added.

Student progress, quiz attempts, essay submissions and certificates **stay attached** across new versions. Lesson ids don't change when a course is updated.

### 2.4 Archived courses **[governance on]**

An archived course disappears from public listings and `GET /courses/{slug}`, exactly like an unpublished course did before. Enrolled students keep their history.

### 2.5 Activity feed **[always]**

When an essay result is released, the student's activity feed (`GET /users/me/dashboard/activity` and the dashboard overview) now gets an `ESSAY_GRADED` entry. The `metadata` holds `course_id`, `course_title`, `item_id`, `item_title` and `score`.

---

## 3. Unchanged

These work exactly as before:
- quizzes and quiz groups (start, save progress, submit);
- marking items complete;
- curriculum, item content and module locking;
- live sessions;
- certificates;
- cart, payments and subscriptions;
- bookmarks and reviews.

## 4. Redo checklist (student app)

- [ ] Essay item: show "Submitted – awaiting result" while `is_graded` is false (§1.2).
- [ ] Essay item: handle the `400` "being marked" error on resubmit (§2.2).
- [ ] Course enrol button: handle `404` for courses that are no longer published (§2.1).
- [ ] Optional: show `current_version_label` on the course page (§1.1).
- [ ] Optional: render the `ESSAY_GRADED` activity entry (§2.5).
