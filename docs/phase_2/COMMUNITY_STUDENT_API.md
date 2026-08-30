# Community (Group Chat) — Student API Reference

This document covers the **chatting** experience of the new Community feature: a WhatsApp-style group chat where you're automatically placed in a platform-wide "General" room and an open "Help" room the moment you sign up, and in your course's own chat the moment you enroll. It's the companion to [`COMMUNITY_INSTRUCTOR_ADMIN_API.md`](./COMMUNITY_INSTRUCTOR_ADMIN_API.md), which covers how admins create custom communities and manage membership.

Base URL prefix for everything below: `/community`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: everything in this document requires `Authorization: Bearer <token>` (or, for the WebSocket, the same JWT passed as a `?token=` query param — see §4).
- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`. `GET /community/{id}/messages` and `GET /community/{id}/members` return `PaginatedResponse<T>` with a `meta` block. `GET /community` (the "list mine" endpoint) returns a plain array — it's not paginated.
- **Null stripping**: absent/null fields are stripped from JSON responses.

---

## User story

*As a new user,* I want to land in a "General" chat with everyone else on the platform and an open "Help" chat where I can ask questions, without setting anything up myself.

*As a student who just enrolled in a course,* I want that course's group chat to appear immediately as somewhere I can talk to my instructor and classmates, post images and documents, and share a link to a specific curriculum resource — with no extra step on my end.

*As someone chatting day-to-day,* I want WhatsApp-level conveniences: reply to one specific earlier message so it's clear what I'm responding to, see a live "so-and-so is typing…" indicator, and know who's online right now.

---

## 1. The mental model

You're automatically a member of:

| Community | You're in it because... |
|---|---|
| **General** | You have an account. Every active user is in this one. |
| **Help** | Same — every active user. An open room for asking for help, distinct from any private support ticket you might also open. |
| **Course communities** | You're enrolled in that course, or you're its instructor. One per course, appears the moment you gain access — no separate opt-in. |
| **Custom communities** | An admin explicitly added you (see the admin doc) — e.g. a cohort-specific group. |

**`GET /community`** is your entry point — it lists every room above that applies to you, and is what you'd render as a chat sidebar/room list.

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

Fetch one room's live member count with **`GET /community/{community_id}`** (returns the same shape plus `member_count`).

---

## 2. Reading & sending messages (REST)

The WebSocket (§4) is the real-time path — messages you send over it, and messages other members send, arrive live. These REST endpoints exist for loading history and as a fallback for clients not holding a socket open.

### 2.1 Message history

**`GET /community/{community_id}/messages?page=1&page_size=20`**

Ordered **most recent first** — page 1 is the bottom of the chat. Load page 2, 3, ... as the user scrolls up (classic reverse-infinite-scroll), same idea as any messaging app.

```json
{
  "success": true,
  "message": "OK",
  "data": [
    {
      "id": "e5f6....",
      "community_id": "c3...",
      "sender_id": "8a3c1d2e-....",
      "sender": { "id": "8a3c1d2e-....", "first_name": "Ada", "last_name": "Obi", "profile_picture_url": "https://...", "...": "..." },
      "body": "Does anyone have notes from last week's session?",
      "created_at": "2026-08-30T10:15:00Z",
      "reply_to": null,
      "attachment_url": null,
      "resource_reference": null
    },
    {
      "id": "d4c5....",
      "community_id": "c3...",
      "sender_id": "72d94ca2-....",
      "sender": { "id": "72d94ca2-....", "first_name": "Femi", "...": "..." },
      "body": "Here you go!",
      "created_at": "2026-08-30T10:16:30Z",
      "reply_to": {
        "id": "e5f6....",
        "sender_id": "8a3c1d2e-....",
        "sender": { "id": "8a3c1d2e-....", "first_name": "Ada", "last_name": "Obi", "username": "ada.obi", "profile_picture_url": "https://...", "...": "..." },
        "body": "Does anyone have notes from last week's session?",
        "attachment_file_name": null
      },
      "attachment_url": "https://pub-....r2.dev/communities/....pdf",
      "attachment_file_name": "week-4-notes.pdf",
      "attachment_mime_type": "application/pdf",
      "attachment_file_size_bytes": 184320,
      "attachment_kind": "DOCUMENT",
      "resource_reference": null
    }
  ],
  "meta": { "page": 1, "page_size": 20, "total_items": 2, "total_pages": 1, "has_next": false, "has_previous": false }
}
```

- **`reply_to`** is a denormalized snippet of the message being replied to (`id`, `sender_id`, `sender`, `body`, `attachment_file_name`) — including the parent's full `sender` (username, name, profile picture, same shape as any other `UserReadDTO`), so you can render "Replying to Ada Obi" with an avatar with no second request. `null` if the message isn't a reply; `sender` itself can be `null` in the rare case the original sender's account was hard-deleted.
- **`attachment_kind`** is `"IMAGE"` or `"DOCUMENT"`, inferred from the MIME type — use it to decide whether to render an inline image preview or a file/download chip.
- **`resource_reference`** is populated when the message shares a curriculum/library item — see §3.3.

### 2.2 Send a message (HTTP fallback)

**`POST /community/{community_id}/messages`**

```json
{
  "body": "Here you go!",
  "reply_to_message_id": "e5f6....",
  "resource_reference_id": null,
  "attachment_storage_key": "communities/c3.../attachments/uuid-week-4-notes.pdf",
  "attachment_file_name": "week-4-notes.pdf",
  "attachment_mime_type": "application/pdf",
  "attachment_file_size_bytes": 184320
}
```

| Field | Notes |
|---|---|
| `body` | Can be an empty string **if** you're sending an attachment and/or a `resource_reference_id` — but at least one of the three must be present, or you get `422`. |
| `reply_to_message_id` | Optional. Must be a message in the **same community** — `400` otherwise. One level of quoting only (WhatsApp-style) — you can reply to a reply, but it always quotes its own direct parent, not the whole chain. |
| `resource_reference_id` | Optional — see §3.3. `400` if the resource doesn't exist. |
| `attachment_*` | Optional — see §3 for the upload flow. |

Response: `ApiResponse<CommunityMessageReadDTO>` (201) — same shape as §2.1's items.

Prefer sending messages over the **WebSocket** (§4) when you have one open — the REST endpoint exists mainly for environments that can't hold a socket open.

---

## 3. Attachments & sharing a curriculum resource

### 3.1 Upload an image/document

Same two-step presigned-upload flow used everywhere else in this API (course documents, resource attachments, support-ticket attachments):

**`POST /community/{community_id}/attachments/upload-url`**

```json
{ "file_name": "week-4-notes.pdf", "content_type": "application/pdf" }
```

```json
{
  "success": true,
  "message": "Upload URL generated successfully",
  "data": {
    "upload_url": "https://....r2.cloudflarestorage.com/....?X-Amz-Signature=...",
    "storage_key": "communities/c3.../attachments/9f2a-week-4-notes.pdf"
  }
}
```

1. `PUT` the raw file bytes to `upload_url` directly from the client (never proxied through this API).
2. Send your message (REST or WebSocket) with `attachment_storage_key` set to the returned `storage_key`, plus `attachment_file_name`/`attachment_mime_type`/`attachment_file_size_bytes` for display purposes.

The server resolves `attachment_storage_key` into a public `attachment_url` at read time — you don't need to construct that URL yourself.

### 3.2 Sending an image vs. a document

There's no separate "type" field to set — the server infers `attachment_kind` (`IMAGE` vs `DOCUMENT`) from `attachment_mime_type` (anything starting `image/` is treated as an image). Send whichever MIME type the file actually has and render based on the `attachment_kind` you get back.

### 3.3 Sharing a curriculum/material item

Set `resource_reference_id` on your message to the id of a published library item (a `Resource` — see the Resources feature docs) to share it as a clickable card instead of a raw link:

```json
{ "body": "", "resource_reference_id": "b6e2a1f0-...." }
```

The read DTO renders it as a compact card:

```json
"resource_reference": {
  "id": "b6e2a1f0-....",
  "name": "Client Intake Template",
  "slug": "client-intake-template",
  "category": "TEMPLATES_AND_FORMS",
  "thumbnail_url": "https://pub-....r2.dev/....png"
}
```

Tapping the card should route to that resource's detail page (`GET /resources/{slug}` — see the Resources student doc) the same way any other resource card in the app would.

---

## 4. Live chat over WebSocket

**`wss://<host>/community/{community_id}/ws?token=<your JWT access token>`**

The token goes in the query string (not a header) because browsers can't set custom headers on a WebSocket handshake. Use the same access token you'd send as `Authorization: Bearer <token>` elsewhere.

**Connection is refused (socket closes immediately) with one of:**

| Close code | Meaning |
|---|---|
| `4401` | Token missing/invalid/expired. |
| `4404` | The community doesn't exist. |
| `4403` | You're authenticated, but not a member of this community. |

### 4.1 Frames you send

All frames are JSON text frames.

**Keep-alive** — also refreshes your online presence (§5):
```json
{ "type": "ping" }
```

**Typing indicator** — ephemeral, never persisted, never appears in message history:
```json
{ "type": "typing", "is_typing": true }
```
Send `is_typing: false` when the user stops typing (or debounce and let it go stale — there's no server-side timeout on this, it's purely relayed).

**Send a message** — same fields as §2.2's REST body:
```json
{
  "type": "message",
  "body": "Here you go!",
  "reply_to_message_id": null,
  "resource_reference_id": null,
  "attachment_storage_key": null,
  "attachment_file_name": null,
  "attachment_mime_type": null,
  "attachment_file_size_bytes": null
}
```

### 4.2 Frames you receive

**A new message** (yours or anyone else's in the room, delivered only after it's persisted):
```json
{ "type": "message", "data": { "...": "same shape as §2.1's message objects" } }
```

**Someone is typing:**
```json
{ "type": "typing", "community_id": "c3...", "user_id": "8a3c1d2e-....", "is_typing": true }
```

**Something went wrong with a frame you sent** (validation error or an access issue) — the socket stays open, this isn't a disconnect:
```json
{ "type": "error", "detail": "A message needs a body, an attachment, or a shared reference" }
```

### 4.3 Practical notes

- Every connected member receives every `message`/`typing` event for that room, including your own messages echoed back — render off the WebSocket feed rather than optimistically appending your own send, to avoid duplicates.
- If the connection drops, reconnect and call `GET /community/{id}/messages?page=1` to catch up on anything sent while you were offline, then resume listening.
- Sending `ping` periodically (e.g. every 30s) keeps your presence heartbeat alive even during quiet stretches — see §5.

---

## 5. Presence — who's online

Presence is **platform-wide**, not per-room: a user is either online or not, based on a rolling heartbeat, regardless of which community they're currently viewing.

- Having any community WebSocket open keeps your presence alive automatically (every frame you send, including `ping`, refreshes it).
- Not holding a socket open? Call **`POST /community/presence/heartbeat`** periodically instead.
- A heartbeat is valid for 60 seconds — after that with no refresh, you're considered offline.

**`GET /community/{community_id}/online`**

```json
{
  "success": true,
  "message": "Online members retrieved successfully",
  "data": { "online_user_ids": ["8a3c1d2e-....", "72d94ca2-...."] }
}
```

Cross-reference these ids against `GET /community/{id}/members` (which also has a convenience `is_online` flag per member already computed for you) to render green dots / "online now" badges.

---

## 6. Endpoint reference

| Endpoint | What it does |
|---|---|
| `GET /community` | List every community you belong to. Not paginated. |
| `GET /community/{id}` | Get one community, with live `member_count`. |
| `GET /community/{id}/members` | Paginated roster, with `is_online` per member. |
| `GET /community/{id}/messages` | Paginated history, most recent first. |
| `POST /community/{id}/messages` | Send a message (HTTP fallback — prefer the WebSocket). |
| `POST /community/{id}/attachments/upload-url` | Presigned upload URL for an image/document. |
| `GET /community/{id}/online` | Which member ids are currently online. |
| `POST /community/presence/heartbeat` | Mark yourself online without an open socket. |
| `WS /community/{id}/ws?token=...` | Live chat: send/receive messages, typing indicators. |

---

## 7. Error responses you should handle

| Status | When |
|---|---|
| `400` | `reply_to_message_id` doesn't exist or points at a message from a **different** community. `resource_reference_id` doesn't exist. |
| `403` | You're not a member of the community (REST endpoints) — WebSocket connections instead just close with code `4403`. |
| `404` | The community itself doesn't exist. WebSocket: closes with `4404`. |
| `422` | A message with no `body`, no attachment, and no `resource_reference_id`. |

---

## 8. Frontend implementation checklist

- [ ] Room list screen: `GET /community` rendered as a sidebar/tab list (General, Help, your course rooms, any custom rooms), each opening the same chat UI.
- [ ] Chat screen: load the latest page of `GET /community/{id}/messages` on open, then connect the WebSocket and append live events; reverse-infinite-scroll to load older pages.
- [ ] Compose bar: text input, an attachment button wired to the §3.1 upload flow, and a "sharing a resource" affordance (e.g. from a resource's detail page, "Share to chat" deep-links back here with `resource_reference_id` pre-filled).
- [ ] Swipe/long-press-to-reply on a message, setting `reply_to_message_id` on the next send and rendering the quoted `reply_to` snippet above the compose bar while composing.
- [ ] Typing indicator: send `{"type":"typing","is_typing":true}` on keystroke (debounced) and `false` on send/blur; render incoming `typing` frames as a transient "X is typing…" line, expiring it client-side after a few seconds of silence.
- [ ] Online indicators: poll or refresh `GET /community/{id}/online` (or rely on `is_online` from the members endpoint) to show presence dots in the member list/header.
- [ ] Handle the WebSocket `error` frame by surfacing the `detail` inline (e.g. as a toast) rather than treating it as a fatal/disconnect event.
