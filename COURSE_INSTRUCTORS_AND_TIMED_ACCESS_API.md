# Course Instructors & Timed Access — API Reference

This document covers two additions to the Courses API:

1. **Multi-instructor credit** — a course can be credited to one or more named instructors, each optionally linked to a real user account (for filtering).
2. **Timed access** — a course can be `SELF_PACED` (default, unchanged behavior) or `SCHEDULED`, with a start/end date window. Viewing a `SCHEDULED` course outside its window is blocked.

Both are now part of the standard course payload and appear on **every** endpoint that returns a course. Base URL prefix for everything below: `/courses`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output (`response_model_exclude_none=True`). If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## 1. New/changed fields on every course object

Every course object (from list, detail, create, update, publish responses — public and manage) now includes:

| Field | Type | Notes |
|---|---|---|
| `instructors` | `CourseInstructorReadDTO[]` | Always present (empty array is impossible in practice — every course has at least one instructor). See §2. |
| `access_mode` | `"SELF_PACED" \| "SCHEDULED"` | Defaults to `SELF_PACED`. |
| `access_start_date` | `string (ISO 8601 datetime)  \| null` | Only meaningful when `access_mode = "SCHEDULED"`. |
| `access_end_date` | `string (ISO 8601 datetime) \| null` | Only meaningful when `access_mode = "SCHEDULED"`. |

These sit alongside the existing fields (`id`, `title`, `slug`, `description`, `level`, `category`, `price`, `is_published`, `instructor_id`, etc. — unchanged).

`CourseInstructorReadDTO`:

```json
{
  "user_id": "3f1b2c4a-....-....-....-............" ,   // string UUID, or null for a guest/unlinked instructor
  "name": "Jane Doe"
}
```

### Example course object (as returned in any list/detail response)

```json
{
  "id": "b6e2a1f0-1234-4a5b-8c9d-0e1f2a3b4c5d",
  "created_at": "2026-08-01T10:00:00Z",
  "title": "Intro to Trauma-Informed Care",
  "slug": "intro-to-trauma-informed-care",
  "description": "...",
  "level": "BEGINNER",
  "what_you_will_learn": ["..."],
  "category": "HEALTH_FITNESS",
  "material_includes": ["..."],
  "requirements": ["..."],
  "is_free": false,
  "price": 49.99,
  "thumbnail_url": "https://.../thumb.jpg",
  "instructor_id": "3f1b2c4a-....-....-....-............",
  "is_published": true,
  "is_exclusive": false,
  "is_featured": false,
  "average_rating": 4.5,
  "total_reviews": 12,
  "access_mode": "SCHEDULED",
  "access_start_date": "2026-09-01T00:00:00Z",
  "access_end_date": "2026-12-01T00:00:00Z",
  "instructors": [
    { "user_id": "3f1b2c4a-....-....-....-............", "name": "Jane Doe" },
    { "user_id": null, "name": "Dr. Guest Speaker" }
  ],
  "is_bookmarked": false,
  "progress_status": null
}
```

(`is_bookmarked` / `progress_status` are auth-dependent fields from a related feature — see the endpoint tables below for when they're populated. Not part of this doc's scope but included here since they appear on the same object.)

---

## 2. Instructors — how it works

- A course always has at least one instructor entry. If you don't send `instructors` on create, the API auto-credits the creating admin/instructor (`user_id` = their id, `name` = their full name).
- `user_id` is **optional per entry** — set it when crediting a real platform account (enables filtering by that instructor). Leave it `null` to credit a guest/unlinked instructor by name only (e.g. someone with no platform account).
- Sending `instructors` on **update (`PATCH /courses/{id}`)** fully **replaces** the existing instructor list — it's not a merge/append. Omit the field entirely to leave instructors unchanged.
- There's no separate "add one instructor" endpoint — always send the full desired list.

### `CourseInstructorInputDTO` (what you send on create/update)

```json
{
  "user_id": "3f1b2c4a-....-....-....-............",  // optional, UUID or omit/null
  "name": "Jane Doe"                                    // required, 1-255 chars
}
```

### Filtering by instructor

Available as query params on `GET /courses` and `GET /courses/manage`:

| Param | Type | Behavior |
|---|---|---|
| `instructor_id` | UUID | Matches courses where this user is the owner (`instructor_id`) OR a credited co-instructor. |
| `instructor_name` | string | Case-insensitive partial match against any credited instructor's `name` (owner or co-instructor). |

Also usable as `search` on `GET /courses/enrolled` — that param matches course title/description **or** any credited instructor name.

---

## 3. Timed access — how it works

`access_mode` on create/update:

- `"SELF_PACED"` (default) — no restrictions, behaves exactly like before this feature existed. `access_start_date`/`access_end_date` should be omitted or `null`.
- `"SCHEDULED"` — **requires both** `access_start_date` and `access_end_date`. `access_end_date` must be strictly after `access_start_date`. Validation runs on both create and update (a 422 is returned otherwise — see §5).

### Enforcement — "block viewing entirely"

When a course is `SCHEDULED` and the current time (UTC) is outside `[access_start_date, access_end_date]`:

- `GET /courses/{slug}` (the full course detail — metadata + curriculum) returns **`403 Forbidden`**.
- `GET /courses/{slug}/items/{item_id}/download` (document download URLs) also returns **`403 Forbidden`**.

Error body:

```json
{
  "success": false,
  "message": "This course has not started yet",
  "errors": null
}
```
or
```json
{
  "success": false,
  "message": "This course's access window has ended",
  "errors": null
}
```

**Bypass:** admins, the course's owning instructor, and any credited co-instructor (via `instructors[].user_id`) are never blocked — they can preview the course at any time through these same public endpoints, in addition to the dedicated `/courses/manage/*` endpoints.

**Not blocked:** course listings (`GET /courses`, `/featured`, `/recent`, `/manage`, `/enrolled`, `/bookmarked`) still include scheduled courses outside their window — so the frontend can still show "starts Sept 1" cards. Only *opening* the course (detail view / document download) is blocked. Build your UI to check `access_mode` + `access_start_date`/`access_end_date` client-side to decide whether to render an "opens on..." state instead of a "View course" button, then treat the 403 as a hard fallback/guard.

---

## 4. Endpoint reference

All endpoints below already existed; this section documents the instructor + timed-access additions on each. Auth: `Authorization: Bearer <token>` header where noted. "Optional auth" = works without a token, but returns extra per-user fields when authenticated.

### `POST /courses` — Create a draft course
**Auth:** admin or instructor

Request body adds:
```json
{
  "...": "...existing fields (title, description, level, category, etc.)",
  "instructors": [
    { "user_id": "3f1b2c4a-....", "name": "Jane Doe" }
  ],
  "access_mode": "SCHEDULED",
  "access_start_date": "2026-09-01T00:00:00Z",
  "access_end_date": "2026-12-01T00:00:00Z"
}
```
All three new fields are optional; omit for a normal self-paced course (`instructors` omitted → defaults to the creator).

Response: `ApiResponse<CourseReadDTO>` — includes `instructors`, `access_mode`, `access_start_date`, `access_end_date`.

---

### `PATCH /courses/{id}` — Update a course
**Auth:** admin or owning instructor

Same three fields, all optional (standard PATCH semantics — omit a field to leave it unchanged). Sending `instructors` replaces the full list. Sending `access_mode: "SCHEDULED"` without both dates → `422`.

Response: `ApiResponse<CourseReadDTO>`.

---

### `PATCH /courses/{id}/publish` — Publish/unpublish
No new inputs. Response now includes `instructors`/`access_mode`/dates like every other course response.

---

### `GET /courses` — Public course list
**Auth:** optional

New query params: `instructor_id`, `instructor_name` (see §2).

Response: `PaginatedResponse<PublicCourseReadDTO>`. Each item has `instructors`, `access_mode`, `access_start_date`, `access_end_date` populated. When authenticated, also `is_enrolled`, `has_access`, `is_bookmarked`, `progress_status`.

---

### `GET /courses/featured` — Featured courses
**Auth:** optional
Same additions as `GET /courses` (no filter params here, but instructor/access fields are populated).

---

### `GET /courses/recent` — Recently added courses
**Auth:** optional
Same additions as `GET /courses`.

---

### `GET /courses/enrolled` — Current user's enrolled courses
**Auth:** required

New query param: `search` — matches course title/description **or** instructor name.

Response: `PaginatedResponse<CourseReadDTO>` — includes `instructors`, `access_mode`, dates, `is_bookmarked`, `progress_status`.

---

### `GET /courses/bookmarked` — Current user's bookmarked courses
**Auth:** required
Same shape as `/enrolled` (instructors + access window fields included).

---

### `GET /courses/manage` — Manageable courses (own for instructors, all for admins)
**Auth:** admin or instructor

New query params: `instructor_id`, `instructor_name` (same semantics as the public listing, useful for an admin filtering "show me everything Jane teaches").

Response: `PaginatedResponse<CourseReadDTO>` with `instructors`/`access_mode`/dates.

---

### `GET /courses/manage/{id}` — Manage detail (includes drafts)
**Auth:** admin or owning instructor
Response: `ApiResponse<CourseManageDetailDTO>` — same course fields (instructors, access window) plus `sections` (full curriculum, unrestricted by timed access — this is the management view).

---

### `GET /courses/{slug}` — Public course detail
**Auth:** optional

⚠️ **This is the endpoint that enforces timed-access blocking** — see §3. On success:

Response: `ApiResponse<PublicCourseDetailDTO>` — course fields (instructors, access window) + `sections` (curriculum, gated by enrollment/preview as before — unrelated to this feature).

On a scheduled course outside its window (for non-privileged viewers): `403 Forbidden` as shown in §3.

---

### `GET /courses/{slug}/items/{item_id}/download` — Document download URL
**Auth:** optional (was previously unauthenticated only; now accepts an optional bearer token so admins/instructors can bypass the timed-access block)

Same 403 behavior as the detail endpoint when the parent course is a scheduled course outside its window.

---

## 5. Validation errors

Standard validation error shape (422), e.g. for `SCHEDULED` without dates:

```json
{
  "success": false,
  "message": "Validation error",
  "errors": [
    {
      "loc": ["body"],
      "msg": "Value error, access_start_date and access_end_date are required when access_mode is SCHEDULED",
      "type": "value_error"
    }
  ]
}
```

Same shape (different `msg`) if `access_end_date <= access_start_date`.

---

## 6. Quick checklist for frontend implementation

- [ ] Course create/edit form: add an "Instructors" repeatable field (name + optional linked-user picker), and an "Access" section with a `SELF_PACED` / `SCHEDULED` toggle that reveals start/end date pickers when `SCHEDULED` is selected. Enforce end > start client-side too.
- [ ] Everywhere a course card/list renders an instructor name, read `course.instructors` (array — decide how to display multiple, e.g. "Jane Doe +1").
- [ ] Course card/detail: if `access_mode === "SCHEDULED"`, show the window (e.g. "Available Sep 1 – Dec 1, 2026") and disable/relabel the "View course" action before `access_start_date` or after `access_end_date`.
- [ ] Handle `403` on `GET /courses/{slug}` and the document-download endpoint with a friendly "not available yet / access ended" state, using the `message` field from the error body.
- [ ] Add instructor filter UI wherever course browsing/management already has search — `instructor_id` (dropdown, if you have a known instructor) and/or `instructor_name` (free-text) as query params.
