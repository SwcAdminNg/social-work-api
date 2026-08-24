# Certificates — Student/User API Reference

This document covers the **student-facing** side of the certificate system: viewing/downloading a
certificate you've earned, and publicly verifying one. It's the companion to
[`CERTIFICATES_INSTRUCTOR_ADMIN_API.md`](./CERTIFICATES_INSTRUCTOR_ADMIN_API.md), which covers how
admins/instructors design templates and assign them to courses.

Base URL prefix for everything below: `/certificates`.

## Conventions

- **Auth**: `GET /certificates/mine` and `GET /certificates/mine/{course_id}` require
  `Authorization: Bearer <token>` for any authenticated user (`get_current_user`) — no special role
  or enrollment check beyond having actually earned the certificate. The verify endpoint
  (`/certificates/verify/{code}`) is **public** — no auth required, by design (it's meant to be
  shared/clicked by anyone checking a certificate's authenticity).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
  `GET /certificates/mine` (list) returns `PaginatedResponse<T>` with a `meta` block.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## 1. The mental model

- A certificate is issued **automatically** the instant you complete a course — there is nothing
  you need to request or trigger. "Complete" means every curriculum item is done and, if the course
  has module gating, its final assessment(s) were passed (see the Assessments docs for exactly what
  counts as completion).
- **Exception — scheduled/cohort courses**: if the course has a defined end date (a "scheduled"
  course, as opposed to a self-paced one), finishing early doesn't get you the certificate right
  away. It's issued once the course's official end date arrives, same as everyone else in your
  cohort — even if you personally finished weeks ahead of it. `GET /certificates/mine/{course_id}`
  will keep 404ing until that date passes, then start working automatically with no action needed
  from you.
- One certificate per (you, course) — completing a course you already have a certificate for (e.g.
  after a module reset and redo, per the Assessments docs' §11) does **not** create a second one;
  the original certificate stands.
- If the course had certificates disabled, or no template was ever configured for it (and no global
  default exists either), completing it simply doesn't produce a certificate — nothing breaks, you
  just won't see one for that course.
- The certificate PDF isn't pre-generated at the moment you complete the course — it's rendered
  (and then cached) the **first time** you or anyone else actually asks for it (via either endpoint
  below, or by opening the public verify link). The first request for a given certificate may be a
  touch slower than subsequent ones; after that, `pdf_url` is a plain static file.

---

## 2. Getting your certificate

### 2.1 Get your certificate for one course

**`GET /certificates/mine/{course_id}`**

`404` if you haven't earned a certificate for this course yet (course not completed, certificates
disabled for it, or no template available) — the message explains why:
`"No certificate has been issued for this course yet - complete the course to earn one"`.

### Response — `CertificateReadDTO`

```json
{
  "success": true,
  "message": "Certificate retrieved successfully",
  "data": {
    "id": "c9203b1f-....",
    "course_id": "72d94ca2-....",
    "course_title": "Intro to Python: Zero to Hero!",
    "recipient_name": "Ronaldo Cristiano",
    "certificate_number": "SW-2026-F168EB87",
    "verification_code": "9YYjJGl6gACJ807mAktyow",
    "issued_at": "2026-08-23T00:00:00Z",
    "pdf_url": "https://pub-....r2.dev/certificates/72d94ca2-.../4f421cec-.../c9203b1f-....pdf",
    "verify_url": "https://<frontend>/certificates/verify/9YYjJGl6gACJ807mAktyow"
  }
}
```

| Field | Notes |
|---|---|
| `course_title` / `recipient_name` | Snapshotted **at the moment of issuance** — if the course is later renamed, or your account name changes, this certificate keeps showing what was true when you earned it. |
| `pdf_url` | A plain, publicly-accessible URL — download it directly (`GET` the URL itself, not this API), share it, embed it, whatever you like. It doesn't expire. |
| `verify_url` | A shareable link (e.g. for a resume or LinkedIn) that lets **anyone** — no login needed — confirm this certificate is genuine. See §3. |
| `certificate_number` | A human-readable reference, e.g. for support requests. Not secret. |
| `verification_code` | The opaque token embedded in `verify_url`. Also not secret by design — it's meant to be shared; it doesn't grant any account access. |

### 2.2 List everything you've earned

**`GET /certificates/mine?page=1&page_size=20`**

Every certificate you've earned across every course, most recently issued first. Same
`CertificateReadDTO` shape as §2.1, one entry per course.

```json
{
  "success": true,
  "message": "OK",
  "data": [
    { "id": "...", "course_title": "Intro to Python: Zero to Hero!", "pdf_url": "...", "...": "..." },
    { "id": "...", "course_title": "Foundations of Community Social Work Practice", "pdf_url": "...", "...": "..." }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

---

## 3. Public verification

**`GET /certificates/verify/{verification_code}`** — **no authentication required.**

Use this to let a third party (an employer, another platform) confirm a certificate is real just
from the code printed on it — the same code embedded in the certificate's own `verify_url`.

### Response — `PublicCertificateVerifyDTO`

Valid code:
```json
{
  "success": true,
  "message": "Certificate is valid",
  "data": {
    "valid": true,
    "recipient_name": "Ronaldo Cristiano",
    "course_title": "Intro to Python: Zero to Hero!",
    "certificate_number": "SW-2026-F168EB87",
    "issued_at": "2026-08-23T00:00:00Z",
    "pdf_url": "https://pub-....r2.dev/certificates/....pdf"
  }
}
```

Unknown/invalid code — note this is still a `200`, not a `404`; check the `valid` flag:
```json
{
  "success": true,
  "message": "Certificate could not be verified",
  "data": { "valid": false }
}
```

Nothing here requires being logged in, being the certificate's owner, or even being a platform
user — it's intentionally open, the same way scanning a QR code on a physical diploma would be.

---

## 4. Error responses you should handle

| Status | When |
|---|---|
| `401` | Missing/invalid bearer token on `GET /certificates/mine` or `GET /certificates/mine/{course_id}` (verify is exempt — it's public). |
| `404` | `GET /certificates/mine/{course_id}` for a course you haven't earned a certificate for. |

`GET /certificates/verify/{code}` never 404s for an unknown code — see §3, it returns `valid: false`
instead so a frontend can render a friendly "not found" state without special-casing an error
response.

---

## 5. Typical flow

```http
# Complete the course via the normal learning endpoints (see the Assessments/Learning docs) — no
# certificate-specific call needed here at all.

GET /certificates/mine/{course_id}
→ 200, data.pdf_url = "https://..../....pdf"
(open/download pdf_url directly, or share data.verify_url)

# Anyone, logged in or not:
GET /certificates/verify/{data.verification_code}
→ 200, data.valid = true
```
