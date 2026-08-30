# Community (Group Chat) — Instructor/Admin API Reference

This document covers the **management** side of the new Community feature: a WhatsApp-style group-chat layer where every course automatically gets its own community, everyone who signs up is automatically in a platform-wide "General" chat and an open "Help" chat, and admins can additionally spin up ad-hoc custom communities. It's the companion to [`COMMUNITY_STUDENT_API.md`](./COMMUNITY_STUDENT_API.md), which covers the full chatting experience (messaging, replies, attachments, typing indicators, presence) from a member's point of view — instructors use those same endpoints to chat, so this document focuses on what's unique to managing the feature.

Base URL prefix for everything below: `/community`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: every endpoint requires `Authorization: Bearer <token>`. Endpoints under `/community/custom`, and adding/removing members, additionally require `ADMIN` (`get_current_admin_user`) — an instructor cannot create or manage custom communities, even for their own course.
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`. Paginated endpoints return `PaginatedResponse<T>` with a `meta` block. Note `GET /community` (the "list mine" endpoint) is **not** paginated — it returns a plain array, since it's meant to render a fixed sidebar of rooms, not a browsable list.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User story

*As a platform admin,* I want every course to automatically get its own group chat the moment it's created, so instructors and enrolled students can talk about coursework without me lifting a finger — and I want a General chat everyone's in and an open Help chat, without having to set either of those up myself either.

*As an admin running a cohort or initiative that doesn't map to a single course,* I want to spin up a one-off community (e.g. "March 2026 Cohort Leads"), drop in a specific list of people by hand, and/or copy in everyone currently enrolled in a particular course as a one-time snapshot — without needing to wire their course access up just to give them a chat room.

*As an instructor,* I want my course's chat to just exist the moment I publish the course — with my enrolled students already in it — and I want to be able to post a link to this week's curriculum resource straight into that chat, and see which of my students are online right now, the same way any other member of the room can.

---

## 1. The mental model

```
Community (type: COURSE | GENERAL | HELP | CUSTOM, name, description, is_active)
        │
        ├── membership is either DYNAMIC (COURSE/GENERAL/HELP) — always in sync
        │   with enrollment/signup, nothing to manage — or STORED (CUSTOM) —
        │   an explicit, admin-managed list of members
        │
        └── 1 : many
                ▼
        CommunityMessage (body, reply_to_message_id, attachment, resource_reference)
```

| Type | Created | Membership | Who manages it |
|---|---|---|---|
| `COURSE` | Automatically, the instant a course is created | Dynamic — every enrolled student (`UserCourseAccess`) plus the course's owning instructor and any credited co-instructors. Enroll/unenroll and it's reflected immediately, no action needed. | Nobody — there's no "manage members" step. |
| `GENERAL` | Automatically (a singleton, seeded once) | Dynamic — every active, non-suspended user on the platform. | Nobody. |
| `HELP` | Automatically (a singleton, seeded once) | Dynamic — same as `GENERAL`: every active, non-suspended user. Distinct from the private 1:1 support-ticket system — this is an open room everyone can post and read in. | Nobody. |
| `CUSTOM` | `POST /community/custom` | Stored — an explicit roster you build by adding users and/or course snapshots. | Admin only. |

**Admins have blanket access** to every community — they can read, post, and (for `CUSTOM`) manage membership in any room, without needing to be added — but that access is an authorization bypass, not membership: an admin who was never enrolled or explicitly added does **not** show up in a room's member list or count, and doesn't count toward "who's online in this room." This matters if you're building an admin moderation view — don't be surprised that an admin viewing a course's roster doesn't see themselves listed unless they're also enrolled/instructing.

---

## 2. Automatic communities — nothing to build

You don't call any endpoint to make these exist:

- **Course communities** are created in the same transaction as the course itself (`POST /course`, the regular course-creation endpoint) — by the time that call returns, `GET /community` for the course's instructor already includes it.
- **General** and **Help** are created lazily/defensively the first time anyone calls `GET /community` if they don't already exist (they're normally pre-seeded), so there's no environment where a user is missing either.

The only thing worth knowing operationally: if a course is renamed, its community's `name` is **not** kept in sync automatically — it was snapshotted from the course's `title` at creation time. There's currently no rename-community endpoint; flag this to product if course renames should propagate.

---

## 3. Custom communities

### 3.1 Create a custom community

**`POST /community/custom`** — Admin only.

```json
{
  "name": "March 2026 Cohort Leads",
  "description": "Optional description",
  "user_ids": ["3f1b2c4a-....", "72d94ca2-...."],
  "course_snapshot_ids": ["4f421cec-...."]
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string (1–255) | required |
| `description` | string \| null | optional |
| `user_ids` | UUID[] | specific users to add, tagged `added_via: "MANUAL"` |
| `course_snapshot_ids` | UUID[] | course ids whose **current** enrollees + instructors get copied in, tagged `added_via: "COURSE_SNAPSHOT"` |

You must supply at least one of `user_ids`/`course_snapshot_ids` — an empty community with no members is rejected with `422`.

⚠️ **Snapshot, not sync.** `course_snapshot_ids` copies in whoever is enrolled/instructing *at the moment you call this*. If a new student enrolls in that course tomorrow, they are **not** automatically added to this custom community — re-run `POST /community/{id}/members` with the same course id to pull in anyone new. This is intentional: a custom community's roster is meant to be a deliberate, stable list, not a live mirror of a course's enrollment.

Response: `ApiResponse<CommunityReadDTO>` (201), with `member_count` populated.

### 3.2 Add members to an existing custom community

**`POST /community/{community_id}/members`** — Admin only. `400` if the target community isn't `CUSTOM` (you can't manually add members to a `COURSE`/`GENERAL`/`HELP` room — their membership is derived, not stored).

```json
{
  "user_ids": ["8a3c1d2e-...."],
  "course_snapshot_id": "4f421cec-...."
}
```

Same rules as creation: at least one of `user_ids`/`course_snapshot_id` required (`422` otherwise), and `course_snapshot_id` is a one-time snapshot of that course's *current* members. Already-existing members are silently skipped (no duplicate rows, no error).

### 3.3 Remove a member

**`DELETE /community/{community_id}/members/{user_id}`** — Admin only. `400` if the community isn't `CUSTOM`. `404` if that user isn't currently a member.

### 3.4 List / search custom communities

**`GET /community/custom?page=1&page_size=20&search=cohort`** — Admin only.

Response: `PaginatedResponse<CommunityReadDTO>`, each with `member_count` populated. `search` matches on community name.

---

## 4. Viewing a community and its roster

### 4.1 List every community you belong to

**`GET /community`**

Returns General, Help, every course community you have access to (enrolled student, owning instructor, or co-instructor), and every custom community you're a member of. Admins get **everything** — every course community that exists and every custom community, in addition to General/Help.

```json
{
  "success": true,
  "message": "Communities retrieved successfully",
  "data": [
    { "id": "a1...", "type": "GENERAL", "name": "General", "is_active": true, "created_at": "2026-08-24T09:00:00Z" },
    { "id": "b2...", "type": "HELP", "name": "Help", "is_active": true, "created_at": "2026-08-24T09:00:00Z" },
    { "id": "c3...", "type": "COURSE", "course_id": "4f421cec-....", "name": "Intro to Social Work", "is_active": true, "created_at": "2026-08-25T14:00:00Z" }
  ]
}
```

`member_count` is **not** populated on this listing (it's meant to render a lightweight sidebar) — fetch `GET /community/{id}` for a single room's count.

### 4.2 Get one community

**`GET /community/{community_id}`** — you must be a member (or admin). `403` otherwise, `404` if the id doesn't exist.

Response includes `member_count` (computed live).

### 4.3 List a community's members

**`GET /community/{community_id}/members?page=1&page_size=20`** — member or admin.

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "user": { "id": "8a3c1d2e-....", "first_name": "Ada", "last_name": "Obi", "email": "ada@example.com", "...": "..." },
      "added_via": "COURSE_SNAPSHOT",
      "added_from_course_id": "4f421cec-....",
      "is_online": true
    },
    {
      "user": { "id": "72d94ca2-....", "first_name": "Femi", "...": "..." },
      "added_via": null,
      "added_from_course_id": null,
      "is_online": false
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

`added_via`/`added_from_course_id` are only meaningful for `CUSTOM` communities — they're `null` for `COURSE`/`GENERAL`/`HELP` members, since those rooms don't track *how* someone became a member (they just are one, by enrollment/signup). `is_online` reflects the shared platform-wide presence heartbeat — see the student doc §5 for how that's populated.

---

## 5. Messaging, attachments, curriculum references, typing & presence

Instructors and admins use the **exact same endpoints** as students to chat — there's no elevated "admin message" concept. Full protocol reference (REST message endpoints, the WebSocket connection/frame formats, quote-replies, attachments, sharing a curriculum/resource card, typing indicators, and presence) lives in [`COMMUNITY_STUDENT_API.md`](./COMMUNITY_STUDENT_API.md) §2–§5 — read that for the wire format.

One instructor-specific note: sharing a curriculum/material item in a course's chat is done via `resource_reference_id` on a message, which points at a `Resource` (see the Resources feature docs) — **not** a raw course curriculum item (`CourseItem`). If you want to share a specific lesson, publish it as (or link it to) a `Resource` first, the same way the course's own "Resources" tab works.

---

## 6. Endpoint reference

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /community` | Any authenticated user | List every community you belong to. Not paginated. |
| `GET /community/unread-count` | Any authenticated user | Aggregate unread count across your communities — see student doc §6. |
| `POST /community/custom` | Admin | Create a custom community. |
| `GET /community/custom` | Admin | List/search all custom communities. |
| `GET /community/{id}` | Member or admin | Get one community, with live `member_count`. |
| `GET /community/{id}/members` | Member or admin | Paginated roster, with online status. |
| `POST /community/{id}/members` | Admin | Add users/course-snapshot to a `CUSTOM` community. `400` if not `CUSTOM`. |
| `DELETE /community/{id}/members/{user_id}` | Admin | Remove a member from a `CUSTOM` community. `400` if not `CUSTOM`, `404` if not a member. |
| `GET /community/{id}/messages` | Member | Paginated history, most recent first — see student doc §2. |
| `POST /community/{id}/messages` | Member | Post a message (HTTP fallback) — see student doc §2. |
| `POST /community/{id}/attachments/upload-url` | Member | Presigned upload URL — see student doc §3. |
| `GET /community/{id}/online` | Member | Which members are currently online — see student doc §5. |
| `POST /community/{id}/read` | Member | Mark a community read up to now — see student doc §6. |
| `POST /community/presence/heartbeat` | Any authenticated user | Mark yourself online without an open socket. |
| `WS /community/{id}/ws?token=...` | Member (JWT as query param) | Live chat + typing — see student doc §4. |

---

## 7. Error responses you should handle

| Status | When |
|---|---|
| `400` | Adding/removing members on a `COURSE`/`GENERAL`/`HELP` community (only `CUSTOM` supports manual membership). |
| `403` | Not an admin on any `/community/custom` or membership-management endpoint. Not a member (and not an admin) on any member-only endpoint. |
| `404` | Community/user doesn't exist. Removing a user who isn't currently a member. |
| `422` | `POST /community/custom` or `POST /community/{id}/members` with no `user_ids` and no course snapshot. |

---

## 8. Frontend implementation checklist

- [ ] Admin console: a "Communities" section listing custom communities (`GET /community/custom`, with search), a create form (name/description, a user picker, and a course picker for snapshotting enrollees), and a member-management view (add/remove) per custom community.
- [ ] Make clear in the UI that a course snapshot is a **one-time copy**, not a live sync — e.g. a tooltip or helper text next to the "add course enrollees" action, and consider surfacing a "re-sync" button that just re-calls `POST /community/{id}/members` with the same `course_snapshot_id`.
- [ ] Course creation flow: no action needed — just know that the moment a course is created, its chat exists and is visible to the instructor immediately.
- [ ] Instructor course dashboard: surface the course's community (from `GET /community`, filtered to `type: "COURSE"` matching the course id) as a "Class Chat" tab or panel, reusing the same chat UI students see.
- [ ] Handle `400` on the membership endpoints gracefully — it means "this isn't a custom community," which should be caught by only showing add/remove-member UI on communities of `type: "CUSTOM"` in the first place.
