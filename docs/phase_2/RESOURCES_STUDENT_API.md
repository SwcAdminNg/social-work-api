# Resources — Student API Reference

This document covers the **public/student-facing** side of the new Resources feature: a browsable library of reference material (policies, templates, practice guides, webinar recordings, research, useful links) that sits alongside — but separate from — the course curriculum. It's the companion to [`RESOURCES_INSTRUCTOR_ADMIN_API.md`](./RESOURCES_INSTRUCTOR_ADMIN_API.md), which covers how admins/instructors build and manage resources.

Base URL prefix for everything below: `/resources`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint here works with **optional auth** (`Authorization: Bearer <token>` if you have one, omitted entirely if you don't) — nothing in this document requires being logged in to call, though what you get back can depend on whether you are.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`. The list endpoint returns `PaginatedResponse<T>` with a `meta` block.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User story

*As a visitor browsing the site before signing up,* I want to see that there's a real, substantial resource library here — policy documents I can read right now, plus a preview of the templates and recordings I'd get access to once I create an account or enroll — so I have a reason to sign up beyond "buy a course."

*As a logged-in user who isn't enrolled in anything yet,* I want to unlock the "logged-in only" resources immediately, and see clearly which remaining resources need an enrollment, without hitting confusing errors.

*As a student enrolled in a course,* I want to find that course's specific supplementary resources — the templates, the extra readings — either from the course page itself or from the general library, and have them unlock automatically the moment I'm enrolled, with no extra step on my end.

---

## 1. The mental model

A **Resource** is a library entry with a name, category, thumbnail, and one or more **attachments** (a video, a document, and/or a link — a single resource can have several). Every resource has one of three visibility levels, set by whoever created it:

| Visibility | Who can see the attachments |
|---|---|
| `PUBLIC` | Anyone — logged in or not. |
| `LOGGED_IN` | Any authenticated user. |
| `COURSE_ENROLLED` | Only users with access to the resource's tied course. |

**Important distinction**: visibility only gates the **attachments** (the actual video/document/link payload). A resource's basic card info — name, category, thumbnail, description — is always visible to everyone browsing the library, even for resources you can't unlock yet. This is intentional: the library is meant to read as a real catalog, and a locked card is a reason to log in or enroll, not something to hide entirely.

---

## 2. Browsing the library

**`GET /resources?page=1&page_size=20`**

Optional filters: `category` (see §4 for the fixed list), `course_id`, `search` (matches name/description).

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "id": "b6e2a1f0-....",
      "name": "Client Intake Template",
      "slug": "client-intake-template",
      "category": "TEMPLATES_AND_FORMS",
      "description": "Standard intake form used across all casework modules.",
      "thumbnail_url": "https://pub-....r2.dev/....png",
      "visibility": "PUBLIC",
      "course_id": null,
      "owner_id": "3f1b2c4a-....",
      "is_published": true,
      "can_access": true,
      "access_reason": null
    },
    {
      "id": "72d94ca2-....",
      "name": "Module 3 Session Recording",
      "category": "VIDEOS_AND_WEBINARS",
      "visibility": "COURSE_ENROLLED",
      "course_id": "4f421cec-....",
      "can_access": false,
      "access_reason": "ENROLLMENT_REQUIRED",
      "...": "..."
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

| Field | Notes |
|---|---|
| `can_access` | `true` if you (the current caller — possibly anonymous) can see this resource's attachments right now. |
| `access_reason` | Set only when `can_access` is `false`: `"LOGIN_REQUIRED"` or `"ENROLLMENT_REQUIRED"`. |

**Suggested UI treatment**: render every card returned, but visually lock the ones with `can_access: false` — e.g. a lock icon and "Log in to unlock" / "Enroll to unlock" based on `access_reason`, rather than a "View" action.

**Finding a course's tied resources**: there's a dedicated endpoint for this — see §2.1. (You can also pass `course_id` as a filter on the general `GET /resources` listing above; both return the same shape, the dedicated one is just a cleaner path for "give me this course's resources.")

### 2.1 A specific course's resources

**`GET /resources/courses/{course_id}?page=1&page_size=20`**

Same response shape as §2 (`PaginatedResponse<ResourceReadDTO>`, with `can_access`/`access_reason` per item), scoped to resources tied to that course. Use this on a course's own detail page to render a "Resources" section alongside its curriculum.

---

## 3. Viewing a single resource

**`GET /resources/{slug}`**

```json
{
  "success": true,
  "message": "Resource retrieved successfully",
  "data": {
    "id": "b6e2a1f0-....",
    "name": "Client Intake Template",
    "slug": "client-intake-template",
    "category": "TEMPLATES_AND_FORMS",
    "description": "Standard intake form used across all casework modules.",
    "thumbnail_url": "https://pub-....r2.dev/....png",
    "visibility": "PUBLIC",
    "course_id": null,
    "owner_id": "3f1b2c4a-....",
    "is_published": true,
    "can_access": true,
    "access_reason": null,
    "attachments": [
      {
        "id": "att-1",
        "resource_id": "b6e2a1f0-....",
        "title": "Intake Form (PDF)",
        "attachment_type": "DOCUMENT",
        "order_index": 0,
        "document": {
          "file_name": "intake-form.pdf",
          "mime_type": "application/pdf",
          "file_size_bytes": 245000,
          "is_uploaded": true,
          "downloadable": true
        }
      }
    ]
  }
}
```

- **When `can_access` is `true`**: `attachments` is fully populated — one entry per video/document/link on the resource, in `order_index` order. Each entry has exactly one of `video`/`document`/`link` set, matching its `attachment_type`.
- **When `can_access` is `false`**: `attachments` is an empty array `[]`, and `access_reason` tells you why (`"LOGIN_REQUIRED"` or `"ENROLLMENT_REQUIRED"`). Render a locked state with the appropriate call-to-action (a login prompt or an "Enroll in {course}" link) instead of an empty list.

### Attachment shapes

| `attachment_type` | Populated field | Fields |
|---|---|---|
| `VIDEO` | `video` | `status` (`PENDING`/`PROCESSING`/`READY`/`FAILED`), `playback_url` (only once `READY`), `thumbnail_url`, `duration_seconds` |
| `DOCUMENT` | `document` | `file_name`, `mime_type`, `file_size_bytes`, `is_uploaded`, `downloadable` |
| `LINKS` | `link` | `url`, `label`, `description` |

Treat `video`/`document`/`link` the same way you'd treat a course item's equivalent fields — render based on whichever one is non-null.

---

## 4. Categories

Fixed set, safe to hardcode as filter chips/tabs:

`COURSE_MATERIALS`, `PRACTICE_RESOURCES`, `POLICIES_AND_GUIDANCE`, `TEMPLATES_AND_FORMS`, `VIDEOS_AND_WEBINARS`, `RESEARCH_AND_PUBLICATIONS`, `CAREER_AND_CPD`, `USEFUL_LINKS`.

---

## 5. Downloading a document attachment

**`GET /resources/{slug}/attachments/{attachment_id}/download`**

Same pattern as course document downloads:

- Works for anyone who can access the resource **and** the document has `downloadable: true`.
- Returns `{ "download_url": "..." }` — a fresh, short-lived link.
- `403 Forbidden` if the document isn't marked downloadable (unless you're the resource's owner or an admin).
- `403 Forbidden` if you don't have access to the resource at all (e.g. it's `COURSE_ENROLLED` and you're not enrolled) — you shouldn't normally hit this if you're only showing the download button when `can_access: true` **and** `document.downloadable: true` in the first place.

**Recommended UI pattern**: only render a "Download" button on a `DOCUMENT` attachment when both `can_access` (on the parent resource) and `document.downloadable` are `true`.

---

## 6. Endpoint reference

| Endpoint | Auth | What it returns |
|---|---|---|
| `GET /resources` | Optional | Paginated library cards, `can_access`/`access_reason` per item, no attachments. |
| `GET /resources/courses/{course_id}` | Optional | Paginated resources tied to one course - same shape as above. |
| `GET /resources/{slug}` | Optional | Full resource detail; `attachments` populated only if `can_access`. |
| `GET /resources/{slug}/attachments/{attachment_id}/download` | Optional | A short-lived download URL for one document attachment. |

---

## 7. Error responses you should handle

| Status | When |
|---|---|
| `403` | Calling the download endpoint for a document that isn't downloadable, or for a resource you don't have access to. |
| `404` | Resource slug or attachment id doesn't exist, or the resource isn't published. |

---

## 8. Frontend implementation checklist

- [ ] Build a "Resource Library" page: a filterable grid/list (`GET /resources`, filters by `category`/`search`), rendering every card — including locked ones with a clear lock state based on `can_access`/`access_reason`.
- [ ] Resource detail page: render `attachments` when present; when `can_access: false`, show a locked state with a login CTA (`LOGIN_REQUIRED`) or an enroll CTA linking to the tied course (`ENROLLMENT_REQUIRED`) instead of an empty attachments section.
- [ ] Course detail page: call `GET /resources/courses/{id}` to show that course's tied resources in a "Resources" section alongside the curriculum.
- [ ] Attachment rendering: branch on `attachment_type` (`VIDEO`/`DOCUMENT`/`LINKS`) the same way you already do for course curriculum items — video player, document viewer, or an external-link card respectively.
- [ ] Only show a document's "Download" button when both the resource's `can_access` and the attachment's `document.downloadable` are `true`.
