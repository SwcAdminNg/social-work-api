# Help & Support — Admin API Reference

The staff side of the help center: managing FAQ content and the support ticket queue. A separate doc
covers the end-user side (browsing FAQ, opening/chatting on a ticket, rating) —
[`HELP_SUPPORT_USER_API.md`](./HELP_SUPPORT_USER_API.md).

Base URL prefix: `/support`.

## Conventions

- **Auth — who counts as "staff"**: `GET /support/tickets` (queue), `POST /tickets/{id}/assign`, and
  `PATCH /tickets/{id}/status` require the caller to be **staff** — either an `ADMIN` user, or any
  user (e.g. an `INSTRUCTOR`) who is an active member of the **"Support Desk"** group (see
  [`GROUPS_ADMIN_API.md`](./GROUPS_ADMIN_API.md)). This is `get_current_support_staff` /
  `is_support_staff` in code. FAQ management endpoints remain `ADMIN`-only. `GET /support/tickets/{id}`
  and `GET /support/tickets/{id}/messages` are open to the ticket's owner in addition to staff.
- **Instructors as staff**: an instructor gets ticket access, the ticket queue, and the chat
  WebSocket the moment they're added to "Support Desk" — nothing else needs to change on their
  account. Removing them from the group revokes it immediately.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for lists.

## 1. FAQ management

| Method | Path | Description |
|---|---|---|
| POST | `/support/faq/categories` | Create a category. Body: `{ "name": str, "order"?: int }`. |
| PATCH | `/support/faq/categories/{id}` | Partial update. |
| DELETE | `/support/faq/categories/{id}` | Soft-delete. Its items are cascade-deleted at the DB level if the category row is ever hard-deleted, but soft-delete leaves items in place (they just stop appearing once their category is gone from `GET /support/faq`, since that endpoint only returns items whose category still resolves). |
| GET | `/support/faq/items` | Paginated list of **every** item, published or not (unlike the public `GET /support/faq`, which only returns published items grouped by category). |
| POST | `/support/faq/items` | Create an item. Body: `{ "category_id": uuid, "question": str, "answer": str, "order"?: int, "is_published"?: bool }`. `404` if the category doesn't exist. |
| PATCH | `/support/faq/items/{id}` | Partial update — including toggling `is_published` to hide/show it on the public FAQ. |
| DELETE | `/support/faq/items/{id}` | Soft-delete. |

## 2. Ticket queue

```
GET /support/tickets?status=OPEN&assigned_admin_id=<uuid>&search=ada&start_date=2026-08-01&end_date=2026-08-31&page=1&page_size=20
```

All filters are optional. `status` is one of `OPEN` / `IN_PROGRESS` / `RESOLVED` / `CLOSED`.
`search` matches the ticket subject or the requester's username, first name, last name, full name,
email, or phone number. `start_date` and `end_date` filter by ticket creation date; the end date
includes the entire day.

| Method | Path | Description |
|---|---|---|
| GET | `/support/tickets` | Filtered/paginated ticket queue (admin only). |
| GET | `/support/tickets/{ticket_id}` | Get a ticket. |
| GET | `/support/tickets/{ticket_id}/messages` | Paginated message history. |
| POST | `/support/tickets/{ticket_id}/messages` | Reply to a ticket over HTTP (same effect as replying over the WebSocket — see the user doc for the WS protocol and attachment flow). Replying as staff auto-flips `OPEN` → `IN_PROGRESS` and clears any pending escalation. |
| POST | `/support/tickets/{ticket_id}/attachments/upload-url` | Get a presigned upload URL for an image/document to attach to your next reply — same flow as the user side, see [`HELP_SUPPORT_USER_API.md`](./HELP_SUPPORT_USER_API.md#31-attaching-an-image-or-document). |
| POST | `/support/tickets/{ticket_id}/assign` | Assign/reassign to a staff member. Body: `{ "admin_id": uuid }` (the field is named `admin_id` for historical reasons, but accepts any staff user — see above). `404` if the target isn't staff. |
| PATCH | `/support/tickets/{ticket_id}/status` | Set status directly. Body: `{ "status": "RESOLVED" }`. Typically used to resolve/close a ticket. Once `RESOLVED`/`CLOSED`, no more messages can be posted to it. |

## 3. Presence

Support Desk members are considered "online" for up to 60 seconds after their last heartbeat. A
WebSocket connection to any ticket automatically refreshes your heartbeat on connect and on every
message/ping you send. If your admin dashboard doesn't have a ticket socket open (e.g. you're just
looking at the queue list), call this periodically instead so you still count as available:

```
POST /support/presence/heartbeat
```

## 4. How escalation works

When a ticket is created, and again every time the **user** sends a new message on it, the system
checks whether it needs to alert staff:

1. It looks up the **"Support Desk"** group (see [`GROUPS_ADMIN_API.md`](./GROUPS_ADMIN_API.md)) and
   checks whether **any** active member currently has a live presence heartbeat.
2. **If no one is online**, an escalation email is sent immediately to every active Support Desk
   member, and the ticket's `escalated_at` is set.
3. **Regardless of step 2**, if the ticket hasn't already escalated (`escalated_at` is still null), a
   delayed check is scheduled via QStash for `support_escalation_minutes` later (default 5 — see
   `app/core/config.py`). When it fires, it re-checks whether the ticket is *still* unanswered
   (`last_admin_reply_at` is null or older than `last_user_message_at`) — if so, it sends the
   escalation email at that point instead.
4. Either path only ever sends **one** email per "unresponsive window": `escalated_at` gates both
   checks. As soon as an admin replies, `escalated_at` is cleared — so if staff go quiet again later
   on the same ticket, it can escalate a second time.

**Local development note**: the delayed QStash check requires `api_base_url` to be a publicly
reachable HTTPS URL (QStash calls back into `POST /support/cron/check-escalation`). Against
`localhost`, scheduling the delayed job fails gracefully (logged as a warning) — only the immediate
"no one online" check will actually fire in local dev.

## 5. Ratings

Ratings are user-submitted (see the user doc) and read-only for admins — they appear as `rating` /
`rating_comment` on `GET /support/tickets/{id}` and in the queue listing once a user has rated a
resolved/closed ticket.
