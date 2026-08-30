# Resources — Instructor/Admin API Reference

This document covers the **management** side of the new Resources feature: a general-purpose library of reference material (policies, templates, practice guides, webinar recordings, research, useful links) that lives independently of the course curriculum, but can optionally be tied to a specific course. It's the companion to [`RESOURCES_STUDENT_API.md`](./RESOURCES_STUDENT_API.md), which covers how the library and individual resources appear to students and the public.

Base URL prefix for everything below: `/resources`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint below requires `Authorization: Bearer <token>` for `ADMIN` or `INSTRUCTOR` (`get_current_admin_or_instructor`), plus a per-resource ownership check on anything that isn't a plain `POST /resources` — see §2.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`. List endpoints return `PaginatedResponse<T>` with a `meta` block.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User story

*As a program administrator building out the practice library,* I want to publish a "Safeguarding Policy" PDF that every visitor to the site can read — logged in or not — a set of referral templates that only registered users should see, and a set of session recordings that should only be available to students actually enrolled in a specific course. I want to build each of these once, attach one or more files/links/videos to it, categorize it so it shows up in the right shelf of the library, and not have to think about who's allowed to see it beyond picking one of three simple visibility levels when I create it.

*As an instructor,* I want to add a couple of extra reference documents to my own course — a client-intake template, a recommended-reading link — without needing an admin to do it for me, and without those files being buried inside the course's curriculum items (which are for lessons, not reference material).

---

## 1. The mental model

```
Resource (name, category, thumbnail, visibility, optional course_id, owner_id, is_published)
        │
        │ 1 : many
        ▼
ResourceAttachment (title, attachment_type: VIDEO | DOCUMENT | LINKS, order_index)
        │
        │ 1 : 1 (exactly one of these, matching attachment_type)
        ▼
ResourceVideo | ResourceDocument | ResourceLink
```

- A **Resource** is a container — a named, categorized library entry. It can hold **multiple attachments** (e.g. a "Module 3 Recording" resource could have both the video and its slide deck as two attachments), unlike a course curriculum item which is exactly one video/document/link.
- A resource can be **standalone** (`course_id: null`) — a site-wide library item — or **tied to a course** (`course_id` set) — still visible in the general library (subject to its own visibility), and also something the course's own page can surface by filtering on `course_id`.
- **Drafts**: a resource starts with `is_published: false` and is invisible to the public library/detail endpoints until you explicitly publish it (`PATCH /resources/{id}/publish`) — same convention as courses.

---

## 2. Who can manage a resource

`ADMIN` or `INSTRUCTOR`, with per-resource ownership:

| Rule | |
|---|---|
| Any `ADMIN` | can manage any resource. |
| The resource's `owner_id` (whoever created it) | can manage it. |
| The owning instructor of the tied course, if `course_id` is set | can manage it — even if they weren't the one who created it. |

Anyone else gets `403 Forbidden`. This applies to every endpoint below except the initial `POST /resources` (gated only by role) and the two public endpoints documented in the student doc.

**Tying a resource to a course**: on create or update, if you set `course_id` to a course you don't own (and you're not an admin), you get `403 Forbidden`. Admins can tie a resource to any course.

---

## 3. Visibility

Set via the `visibility` field — one of three tiers:

| Value | Meaning |
|---|---|
| `PUBLIC` | Anyone can see this resource's attachments, including anonymous visitors. **Default.** |
| `LOGGED_IN` | Any authenticated user (any role) can see it; anonymous visitors can't. |
| `COURSE_ENROLLED` | Only users with access to the tied course can see it (same access rule used to gate the course's own content — direct enrollment or an active non-exclusive subscription), plus admins and the course's owning instructor. **Requires `course_id` to be set** — you'll get a `422` if you try to set `COURSE_ENROLLED` without a `course_id`. |

Visibility only gates whether a viewer sees the resource's **attachments** — the resource's own metadata (name, category, thumbnail, description) is always visible to anyone browsing the public library, even for `LOGGED_IN`/`COURSE_ENROLLED` resources they can't unlock yet. See the student doc for exactly how that's surfaced (`can_access`/`access_reason`).

---

## 4. Managing resources

### 4.1 Create a resource

**`POST /resources`**

```json
{
  "name": "Client Intake Template",
  "category": "TEMPLATES_AND_FORMS",
  "description": "Standard intake form used across all casework modules.",
  "visibility": "PUBLIC",
  "course_id": null
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string (1–255) | required |
| `category` | enum, see §5 | required |
| `description` | string \| null | optional |
| `thumbnail_url` | string \| null (max 1000) | optional — set directly here, or via the upload flow in §4.4 |
| `visibility` | enum | default `PUBLIC` |
| `course_id` | UUID \| null | optional; required if `visibility = COURSE_ENROLLED` |

A unique `slug` is generated from `name` automatically (same `ensure_unique_slug` helper courses use — a collision gets `-2`, `-3`, etc. appended). `owner_id` is set to you automatically. New resources start as drafts (`is_published: false`).

Response: `ApiResponse<ResourceReadDTO>` (201).

### 4.2 Update a resource

**`PATCH /resources/{id}`** — partial update, any subset of the fields above.

```json
{ "visibility": "COURSE_ENROLLED", "course_id": "72d94ca2-...." }
```

⚠️ If you're changing `visibility` to `COURSE_ENROLLED`, include `course_id` in the **same** request — the validation only looks at what's actually in the payload together, same convention as the course module's `SCHEDULED` access-mode check. Changing just `visibility` alone when the resource has no existing `course_id` will `422`.

### 4.3 Delete / publish

**`DELETE /resources/{id}`** — soft delete.

**`PATCH /resources/{id}/publish?is_published=true`** — publish or unpublish. A draft (`is_published: false`) never appears in the public library or by direct slug lookup, no matter its visibility setting.

### 4.4 Thumbnail upload

**`POST /resources/{id}/thumbnail-upload-url`** — identical two-step flow to course thumbnails:

```json
{ "file_name": "template-cover.png", "content_type": "image/png" }
```
```json
{
  "success": true,
  "message": "Upload URL generated successfully",
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/....?X-Amz-Signature=...",
    "thumbnail_url": "https://pub-....r2.dev/resources/....png"
  }
}
```

`thumbnail_url` is saved on the resource immediately (optimistically) — next step (client-side): `PUT` the raw image bytes to `upload_url`. Uploading again replaces the thumbnail and deletes the old file from storage.

### 4.5 Listing your resources

**`GET /resources/manage?page=1&page_size=20`**

Instructors see their own resources (owned, or tied to a course they own); admins see everything. Filters: `category`, `course_id`, `search` (name/description), `is_published`.

Response: `PaginatedResponse<ResourceReadDTO>`.

### 4.6 Full manage detail

**`GET /resources/manage/{id}`** — everything, unfiltered, regardless of `visibility`/`is_published` — this is the editing view.

Response: `ApiResponse<ResourceManageDetailDTO>` — same fields as `ResourceReadDTO` plus `attachments: ResourceAttachmentManageReadDTO[]` (includes internal fields like `storage_key`/`bunny_video_guid`, hidden from the public/student-facing shapes).

---

## 5. Categories

Fixed set (`ResourceCategoryEnum`) — pick one per resource:

`COURSE_MATERIALS`, `PRACTICE_RESOURCES`, `POLICIES_AND_GUIDANCE`, `TEMPLATES_AND_FORMS`, `VIDEOS_AND_WEBINARS`, `RESEARCH_AND_PUBLICATIONS`, `CAREER_AND_CPD`, `USEFUL_LINKS`.

These are hardcoded (no admin CRUD for categories, same convention as course categories elsewhere in this API) — safe to hardcode the list client-side for a filter/dropdown.

---

## 6. Attachments

Each resource can hold any number of attachments — a mix of videos, documents, and links.

### 6.1 Add an attachment

**`POST /resources/{resource_id}/attachments`**

Video:
```json
{ "title": "Session Recording", "attachment_type": "VIDEO" }
```
Response includes `video_upload` (TUS credentials) — same Bunny Stream upload flow as course videos.

Document:
```json
{ "title": "Intake Form (PDF)", "attachment_type": "DOCUMENT", "file_name": "intake-form.pdf", "downloadable": true }
```
Response includes `document_upload: { upload_url, storage_key }` — `PUT` the file bytes to `upload_url`, then call §6.4 to finalize. `downloadable` defaults to `false` (view-only) — same `downloadable` concept as course documents.

Link:
```json
{ "title": "External Reading", "attachment_type": "LINKS", "url": "https://example.org/article", "label": "Trauma-Informed Practice: A Primer", "description": "A deeper dive into the concepts." }
```
No upload step — complete immediately.

| Field | Applies to | Notes |
|---|---|---|
| `title` | all | required, 1–255 chars |
| `attachment_type` | all | `VIDEO` \| `DOCUMENT` \| `LINKS` |
| `order_index` | all | default 0 |
| `file_name` | `DOCUMENT` | required for that type — `400` otherwise |
| `downloadable` | `DOCUMENT` | default `false` |
| `url` | `LINKS` | required for that type — `400` otherwise |
| `label`, `description` | `LINKS` | optional |

### 6.2 Update an attachment

**`PATCH /resources/attachments/{attachment_id}`**

- `title`/`order_index` — always settable.
- `downloadable` — only if the attachment is a `DOCUMENT`; `400` ("This attachment is not a document") otherwise.
- `url`/`label`/`description` — only if the attachment is `LINKS`; `400` ("This attachment is not a link") otherwise.

### 6.3 Delete / reorder

**`DELETE /resources/attachments/{attachment_id}`** — also deletes the underlying file from storage if it was a document.

**`PATCH /resources/{resource_id}/attachments/reorder`**
```json
{ "attachments": [ { "id": "att-1", "order_index": 0 }, { "id": "att-2", "order_index": 1 } ] }
```

### 6.4 Document finalize / video re-upload

**`POST /resources/attachments/{attachment_id}/document/finalize`** — confirm the R2 upload completed:
```json
{ "mime_type": "application/pdf", "file_size_bytes": 245000 }
```

**`POST /resources/attachments/{attachment_id}/video/refresh-upload`** — re-issue TUS credentials if the original upload session expired.

---

## 7. Endpoint reference

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /resources` | Admin/Instructor | Create. |
| `PATCH /resources/{id}` | Owner/admin/course-instructor | Update. |
| `DELETE /resources/{id}` | Owner/admin/course-instructor | Soft delete. |
| `PATCH /resources/{id}/publish` | Owner/admin/course-instructor | Publish/unpublish. |
| `POST /resources/{id}/thumbnail-upload-url` | Owner/admin/course-instructor | Presigned thumbnail upload. |
| `GET /resources/manage` | Admin/Instructor | Own resources (instructor) / all (admin). |
| `GET /resources/manage/{id}` | Owner/admin/course-instructor | Full unfiltered detail. |
| `POST /resources/{resource_id}/attachments` | Owner/admin/course-instructor | Add attachment. |
| `PATCH /resources/attachments/{attachment_id}` | Owner/admin/course-instructor | Update attachment. |
| `DELETE /resources/attachments/{attachment_id}` | Owner/admin/course-instructor | Delete attachment. |
| `PATCH /resources/{resource_id}/attachments/reorder` | Owner/admin/course-instructor | Reorder. |
| `POST /resources/attachments/{attachment_id}/document/finalize` | Owner/admin/course-instructor | Confirm upload. |
| `POST /resources/attachments/{attachment_id}/video/refresh-upload` | Owner/admin/course-instructor | Re-issue credentials. |
| `GET /resources/courses/{course_id}` | Public (optional auth) | Paginated, published resources tied to one course - see the student doc §2.1. Handy for previewing what a course's resources tab will show, though it only ever returns published resources (use `GET /resources/manage?course_id=...` to see drafts too). |

---

## 8. Error responses you should handle

| Status | When |
|---|---|
| `400` | `file_name` missing when creating a `DOCUMENT` attachment. `url` missing when creating a `LINKS` attachment. `downloadable` sent on a non-document attachment. `url`/`label`/`description` sent on a non-link attachment. `course_id` required but missing when the merged/final visibility is `COURSE_ENROLLED` (on update). |
| `403` | Not the resource's owner/admin/tied-course-instructor on any manage endpoint. Tying a resource (create or update) to a course you don't own and aren't admin for. |
| `404` | Resource/attachment/course id doesn't exist. |
| `422` | `course_id` missing when `visibility: "COURSE_ENROLLED"` is set on **create** (always validated together there). Standard FastAPI validation errors otherwise. |

---

## 9. Frontend implementation checklist

- [ ] Resource create/edit form: name, category (dropdown from the fixed list in §5), description, thumbnail (upload widget using §4.4's two-step flow), a visibility selector that reveals a course picker only when `COURSE_ENROLLED` is chosen.
- [ ] A "Publish" toggle, separate from the create/edit form, mirroring how course publishing works.
- [ ] An attachments panel on the resource edit screen: add video/document/link, drag-to-reorder (wired to §6.3's reorder endpoint), a downloadable toggle that only appears for document attachments.
- [ ] Course edit page: consider adding a "Resources" tab that creates resources pre-filled with `course_id` set to the current course, for the "tie a resource to my course" workflow.
- [ ] Handle `403` on any manage action with a clear "you don't manage this resource" message, since ownership here is slightly more nuanced than plain "is admin" (owner OR tied-course's instructor OR admin).
