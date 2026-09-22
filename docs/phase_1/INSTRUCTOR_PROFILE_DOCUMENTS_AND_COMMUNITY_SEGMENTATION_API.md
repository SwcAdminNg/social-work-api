# Instructor Profile Documents & Community Segmentation — API Reference

Covers two related changes:

1. **Instructor profile documents** — instructors can now maintain a CV and any number of
   named supporting documents (e.g. `License`, `Certification`) directly from their profile,
   independent of the one-time CV submitted with their original `InstructorApplication`.
2. **Community segmentation by user type** — the `General` community is now scoped to
   students (`UserTypeEnum.USER`) only. Two new singleton communities, `Instructor Community`
   and `Admin Community`, give instructors and admins their own equivalent space. `Help`
   remains open to every active user, and admins can see/access every community.

Also: the support-email footer address changed from `support@socialworknigeria.com` to
`support@socialworknigeria.org` (`Settings.company_support_email`) — no API shape change.

## Conventions

- **Auth**: `Authorization: Bearer <token>`.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for lists.
- **File upload pattern**: every upload endpoint below follows the same two-step flow used
  elsewhere in the API (profile pictures, community attachments, instructor application CVs):
  1. Call the endpoint to get a **pre-signed URL**; the file bytes never pass through this API.
  2. `PUT` the raw file bytes directly to `upload_url` (set the `Content-Type` header to match
     the `content_type` you sent, if you sent one).
  Uploaded files are private (not publicly readable) — retrieval always goes through a
  pre-signed **download** URL that expires after `settings.presigned_url_expire_seconds`.

---

## 1. Instructor CV

Base URL prefix: `/users`. All endpoints require an `INSTRUCTOR` user (`get_current_instructor_user`) — `403` otherwise.

| Method | Path | Description |
|---|---|---|
| POST | `/users/me/cv-upload-url` | Get a pre-signed URL to upload/replace the current instructor's CV. Body: `{ "file_name": str, "content_type"?: str }`. Deletes the previous CV object (if any) and updates `User.cv_file_name` immediately — the upload URL is one-time-use and short-lived, so treat the field as "the CV I intend to have," not "the CV that's already uploaded," until the `PUT` succeeds. |
| GET | `/users/me/cv-download-url` | Get a pre-signed download URL for the current instructor's CV. `404` if none has been uploaded. |

`UserReadDTO` (returned from `GET /users/me`, etc.) now also includes:

```jsonc
{
  "cv_file_name": "resume.pdf"  // null if no CV has been uploaded
}
```

### Example

```bash
# 1. Request an upload URL
curl -X POST https://api.example.com/users/me/cv-upload-url \
  -H "Authorization: Bearer $INSTRUCTOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_name": "resume.pdf", "content_type": "application/pdf"}'
# => { "data": { "upload_url": "https://...", "cv_file_name": "resume.pdf" } }

# 2. Upload the file bytes directly to R2
curl -X PUT "<upload_url>" -H "Content-Type: application/pdf" --data-binary @resume.pdf

# 3. Later, to download it
curl https://api.example.com/users/me/cv-download-url -H "Authorization: Bearer $INSTRUCTOR_TOKEN"
```

---

## 2. Instructor additional documents

Base URL prefix: `/users`. All endpoints require an `INSTRUCTOR` user — `403` otherwise. Each
document is its own row (table `instructor_documents`), scoped to the requesting instructor —
one instructor can never see or modify another's documents (`404`, not `403`, if a
`document_id` belongs to someone else, to avoid leaking existence).

| Method | Path | Description |
|---|---|---|
| GET | `/users/me/documents` | List the current instructor's documents, each with a fresh pre-signed `download_url`. |
| POST | `/users/me/documents` | Create a new named document and get a pre-signed upload URL for it. Body: `{ "name": str, "file_name": str, "content_type"?: str }`. `201`. |
| POST | `/users/me/documents/{document_id}/upload-url` | Replace an existing document's file (and its name/content type) — deletes the old file object and returns a fresh pre-signed upload URL for the new one. Same body shape as create. |
| PATCH | `/users/me/documents/{document_id}` | Rename a document only. Body: `{ "name": str }`. |
| DELETE | `/users/me/documents/{document_id}` | Soft-delete a document (and its storage object). |

`InstructorDocumentReadDTO`:

```jsonc
{
  "id": "uuid",
  "name": "License",
  "file_name": "swc-license-2026.pdf",
  "mime_type": "application/pdf",
  "file_size_bytes": null,   // not currently populated by the upload flow; reserved for future use
  "download_url": "https://...",
  "created_at": "...",
  "updated_at": "..."
}
```

### Example: adding a "License" document

```bash
curl -X POST https://api.example.com/users/me/documents \
  -H "Authorization: Bearer $INSTRUCTOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "License", "file_name": "swc-license-2026.pdf", "content_type": "application/pdf"}'
# => { "data": { "document_id": "<uuid>", "upload_url": "https://..." } }

curl -X PUT "<upload_url>" -H "Content-Type: application/pdf" --data-binary @swc-license-2026.pdf
```

### Example: replacing that document's file next year

```bash
curl -X POST https://api.example.com/users/me/documents/<document_id>/upload-url \
  -H "Authorization: Bearer $INSTRUCTOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "License", "file_name": "swc-license-2027.pdf", "content_type": "application/pdf"}'
```

---

## 3. Community segmentation by user type

Base URL prefix: `/community`. No endpoint shape changed — `GET /community` (and every other
existing community endpoint) behaves exactly as before from a client's perspective. What
changed is **which communities a user is a member of**.

`CommunityTypeEnum` gained two values: `INSTRUCTOR_GENERAL` and `ADMIN_GENERAL`, alongside the
existing `COURSE`, `GENERAL`, `HELP`, `CUSTOM`.

| Type | Who's a member | Notes |
|---|---|---|
| `GENERAL` ("General") | Active, non-suspended `USER` (student) accounts only | **Changed** — previously every active user, now students only |
| `INSTRUCTOR_GENERAL` ("Instructor Community") | Active, non-suspended `INSTRUCTOR` accounts only | **New** singleton, seeded by migration `7079783845bf` |
| `ADMIN_GENERAL` ("Admin Community") | Active, non-suspended `ADMIN` accounts only | **New** singleton, seeded by migration `7079783845bf` |
| `HELP` ("Help") | Every active, non-suspended user, any type | Unchanged |
| `COURSE` | A course's current enrollees + owning/co-instructors | Unchanged |
| `CUSTOM` | Explicit `CommunityMembership` rows, managed by an admin | Unchanged |

`ADMIN` users continue to have blanket read/post access to **every** community (unchanged
authorization bypass documented in `membership.is_member`), and `GET /community` for an admin
now additionally lists `General`, `Instructor Community` and `Admin Community` all at once (in
addition to every `COURSE` and `CUSTOM` community) — an admin sees everything.

For a `USER`/student, `GET /community` returns `General` + `Help` + their course communities +
any custom communities they belong to. For an `INSTRUCTOR`, it returns `Instructor Community` +
`Help` + their course communities + any custom communities — they no longer see `General`.

### Migration notes

- `e9525e3adde2` adds the two new enum values to the Postgres `community_type_enum` type (its
  own migration/transaction, since Postgres won't let a just-added enum value be referenced in
  the same transaction it was added in).
- `7079783845bf` seeds the `Instructor Community` and `Admin Community` singleton rows
  (idempotent — safe to re-run), mirroring how `General`/`Help` were originally seeded in
  `b1c2d3e4f5a6_add_community_module`.
- No backfill of existing `GENERAL` membership was needed since `GENERAL`'s membership was
  (and still is) computed dynamically at read time, never stored.
