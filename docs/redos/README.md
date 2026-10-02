# Redos: endpoint changes from Learning Content Governance

The content approval and governance feature (Create → Review → Quality Check → Approve → Publish, plus essay moderation) changed how several existing endpoints behave and added new ones. This folder lists, per audience, exactly what a frontend has to redo.

| Doc | Read it if you build |
|---|---|
| [`ADMIN_ENDPOINT_CHANGES.md`](./ADMIN_ENDPOINT_CHANGES.md) | The admin dashboard (platform admins, plus the new reviewer roles such as Academic Reviewer, QA, Course Lead and Head of Learning) |
| [`INSTRUCTOR_ENDPOINT_CHANGES.md`](./INSTRUCTOR_ENDPOINT_CHANGES.md) | The instructor app (course authoring and essay marking) |
| [`STUDENT_ENDPOINT_CHANGES.md`](./STUDENT_ENDPOINT_CHANGES.md) | The student app |

The full reference for the new endpoints is in `docs/phase_3/`:
- [`CONTENT_GOVERNANCE_ADMIN_API.md`](../phase_3/CONTENT_GOVERNANCE_ADMIN_API.md)
- [`APPROVAL_CENTRE_API.md`](../phase_3/APPROVAL_CENTRE_API.md)
- [`ESSAY_MODERATION_API.md`](../phase_3/ESSAY_MODERATION_API.md)

---

## The one switch that matters

Everything is controlled by the server setting `CONTENT_GOVERNANCE_ENABLED`, which defaults to **`false`**.

| | Governance **off** (default) | Governance **on** |
|---|---|---|
| Publishing a course | Owner or admin toggles `PATCH /courses/{id}/publish`, as before | Only after every required review approval; the publisher needs `PUBLISH_CONTENT` |
| Editing a published course | Goes live immediately, as before | Goes into a hidden **working copy**; learners see it only once it is approved and published |
| Admins | Can do everything, as before | Can create, edit, publish, archive and manage roles, but **cannot** approve reviews or mark essays unless given a role |
| Essay grading | One step, as before (now with a history) | Moderated essays go Marker → Moderator → Approver |
| Version history | Recorded on every publish | Recorded on every publish |

Each doc marks changes as:
- **[always]** – applies whether or not the flag is on;
- **[governance on]** – only applies when the flag is on.

Call `GET /governance/me/permissions` to find out at runtime whether the flag is on (`governance_enabled`) and what the current user can do.

---

## Shared conventions

- Every endpoint needs `Authorization: Bearer <token>` unless stated otherwise.
- Responses use the usual `ApiResponse<T>` envelope (`{ success, message, data }`); paginated lists use `PaginatedResponse<T>`.
- Null fields are stripped from responses.
- New error meanings:
  - `403`: you lack the permission, or separation of duties blocks you. The `message` explains which, e.g. "You contributed to this revision, so you can't approve any stage of it".
  - `409`: the course or revision is in the wrong state for that action, e.g. it is under review, archived, or not yet approved.
