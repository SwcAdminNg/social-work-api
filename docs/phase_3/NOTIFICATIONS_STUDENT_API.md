# Notifications — Student API Reference

Realtime + inbox notifications for the student platform: a bell/inbox icon that updates live over a
WebSocket, backed by a normal paginated REST history so nothing is lost if the socket wasn't open
when something happened. This is the companion to
[`NOTIFICATIONS_ADMIN_API.md`](./NOTIFICATIONS_ADMIN_API.md), which covers the same feature from the
admin dashboard's side — same endpoints, different notification types land on each side.

Base URL prefix for everything below: `/notifications`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: everything below requires `Authorization: Bearer <token>` (or, for the WebSocket, the
  same JWT passed as a `?token=` query param — browsers can't set headers on a WS handshake).
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for the list
  endpoint.
- **`link` is a relative path**, e.g. `/dashboard/certificates/{course_id}` — **prepend this app's
  own origin** when routing (there is no `https://...` baked in, since the same backend also serves
  the admin dashboard, which uses a different origin and route tree). Treat it as a client-side
  router path: `router.push(notification.link)`.
- **`metadata_json`** carries the raw ids behind a notification (e.g. `course_id`, `ticket_id`) in
  case you want to do something smarter than "navigate to `link`" — e.g. update local cache, or
  build your own route instead of trusting the server's.

---

## 1. The notification object

```json
{
  "id": "b6e2a1f0-....",
  "created_at": "2026-09-08T09:12:00Z",
  "type": "COURSE_COMPLETED",
  "title": "Course completed!",
  "body": "Congratulations - you've completed \"Intro to Social Work\".",
  "link": "/dashboard/certificates/4f421cec-....",
  "metadata_json": { "course_id": "4f421cec-...." },
  "is_read": false,
  "read_at": null
}
```

- `read_at` is only present once `is_read` is `true`.
- `body`, `link`, and `metadata_json` can individually be `null` for some types — always render
  `title` alone as a safe fallback.

---

## 2. Reading your notifications (REST)

### 2.1 List, newest first

```
GET /notifications?page=1&page_size=20&unread_only=false
```

```json
{
  "success": true,
  "message": "OK",
  "data": [ { "...": "notification object, see §1" } ],
  "meta": { "page": 1, "page_size": 20, "total_items": 37, "total_pages": 2, "has_next": true, "has_previous": false }
}
```

Pass `unread_only=true` to fetch just the unread ones (e.g. for a dropdown that only shows what's
new, with a separate "view all" screen calling this without the filter).

### 2.2 Unread count (for a badge)

```
GET /notifications/unread-count
```

```json
{ "success": true, "message": "Unread count retrieved successfully", "data": { "unread_count": 4 } }
```

### 2.3 Mark one as read

```
PATCH /notifications/{notification_id}/read
```

```json
{ "success": true, "message": "Notification marked as read", "data": { "...": "updated notification object, is_read: true" } }
```

`404` if the notification doesn't exist or doesn't belong to you.

### 2.4 Mark everything as read

```
POST /notifications/read-all
```

```json
{ "success": true, "message": "All notifications marked as read" }
```

No body. Use this for a "mark all as read" action in the notification panel.

---

## 3. Realtime delivery over WebSocket

```
wss://<host>/notifications/ws?token=<your access token>
```

- The token goes in the query string (same JWT you'd send as `Authorization: Bearer <token>`
  elsewhere) — browsers can't set custom headers on a WS handshake.
- The connection is refused (closes immediately) with code **`4401`** if the token is
  missing/invalid/expired. There's no other rejection case — this socket is scoped to you, not to a
  specific ticket/community that could 403/404.
- This socket is **push-only** — you don't need to send anything on it. Every frame you receive is a
  new notification:

```json
{ "type": "notification", "data": { "...": "notification object, see §1, always is_read: false" } }
```

### Practical notes

- Open this socket once, globally, when the app loads (not per-screen) — e.g. from your root layout
  or a notifications context provider — and keep it open for the session.
- On receiving a `notification` frame: prepend it to your local list, increment the unread badge, and
  optionally show a toast using `title`/`body`.
- If the socket drops, reconnect and call `GET /notifications/unread-count` (and re-fetch page 1 of
  the list if a panel is open) to reconcile anything you missed while disconnected — this socket has
  no replay/backfill of its own, the REST endpoints are your source of truth.
- There's no `ping`/keepalive frame required from the client for this socket (unlike the community
  and support-ticket sockets, which use `ping` to refresh presence) — presence isn't a concept here.

---

## 4. Notification types you'll see

Every `type` below is one you can receive as a student. `link` shows the actual path pattern the
backend sends (already relative — just prepend your origin).

| `type` | Fires when | Example `link` |
|---|---|---|
| `SIGNUP_WELCOME` | Your account is created. | `/dashboard` |
| `LOGIN` | You complete a login (after 2FA). | `/dashboard/settings` |
| `PASSWORD_RESET_REQUESTED` | You requested a password reset email. | `/dashboard/settings` |
| `PASSWORD_RESET_COMPLETED` | Your password was successfully changed. | `/dashboard/settings` |
| `PROFILE_PICTURE_UPDATED` | Your profile picture was updated. | `/dashboard/settings` |
| `TWO_FACTOR_ENABLED` | You finished setting up 2FA (email or authenticator app). | `/dashboard/settings` |
| `ACCOUNT_SUSPENDED` | An admin suspended your account. | `/dashboard/support-tickets` |
| `ACCOUNT_UNSUSPENDED` | An admin lifted a suspension. | `/dashboard` |
| `ROLE_CHANGED` | An admin changed your account role. | `/dashboard/settings` |
| `PAYMENT_SUCCESSFUL` | A course/cart/subscription payment succeeded. | `/dashboard/orders` |
| `SUBSCRIPTION_RENEWED` | Your subscription auto-renewed successfully. | `/dashboard/pricing` |
| `SUBSCRIPTION_RENEWAL_FAILED` | Auto-renewal charge failed (subscription paused). | `/dashboard/pricing` |
| `SUBSCRIPTION_EXPIRING_SOON` | Your subscription expires in ~2 days. | `/dashboard/pricing` |
| `SUBSCRIPTION_EXPIRED` | Your subscription expired (no saved card / renewal failed). | `/dashboard/pricing` |
| `COURSE_ENROLLED` | You enrolled in a course. | `/learn/{course_id}` |
| `COURSE_COMPLETED` | You completed every item in a course. | `/dashboard/certificates/{course_id}` |
| `CERTIFICATE_ISSUED` | Your certificate for a completed course is ready. | `/dashboard/certificates/{course_id}` |
| `LIVE_SESSION_SCHEDULED` | A live session was scheduled for a course you're enrolled in. | `/courses/{slug}/live-session/{item_id}` |
| `LIVE_SESSION_RESCHEDULED` | A live session's date/time changed. | `/courses/{slug}/live-session/{item_id}` |
| `LIVE_SESSION_REMINDER` | A live session you're enrolled for is starting soon. | `/courses/{slug}/live-session/{item_id}` |
| `COURSE_REVIEW_REPLIED` | The instructor/an admin replied to your course review. | `/dashboard/course-catalogue/{course_id}` |
| `COMMUNITY_NEW_MESSAGE` | A new message in a course/custom community you're in (while you weren't actively viewing it). | `/dashboard/community?community_id={community_id}` |
| `SUPPORT_TICKET_MESSAGE` | Support staff replied to your ticket. | `/dashboard/support-tickets/{ticket_id}` |
| `SUPPORT_TICKET_STATUS_CHANGED` | Your ticket's status changed (e.g. resolved/closed). | `/dashboard/support-tickets/{ticket_id}` |

Notes on a couple of these:

- **`COMMUNITY_NEW_MESSAGE`** is intentionally **not** sent for the platform-wide `GENERAL`/`HELP`
  rooms (too high-volume to be a useful notification), and not sent to members who are actively
  online in that room at the moment the message is posted — only to members who'd otherwise miss it.
- **Live session** notifications are also emailed with a calendar invite attached — this in-app
  notification is the lightweight companion, not a replacement for the email.
- Any of the "account" types (`LOGIN`, `PASSWORD_RESET_*`, etc.) can also land on an admin's account,
  since admins are users too — the type list is shared, see the admin doc for the admin-only types.

---

## 5. Endpoint reference

| Endpoint | What it does |
|---|---|
| `GET /notifications` | Paginated list, newest first. `?unread_only=true` to filter. |
| `GET /notifications/unread-count` | Aggregate unread count for a badge. |
| `PATCH /notifications/{id}/read` | Mark one notification read. |
| `POST /notifications/read-all` | Mark every notification read. |
| `WS /notifications/ws?token=...` | Live push of new notifications. Push-only, no frames to send. |

---

## 6. Error responses you should handle

| Status | When |
|---|---|
| `401` | Missing/invalid/expired token (REST: normal `401`; WebSocket: closes with code `4401`). |
| `404` | `PATCH /notifications/{id}/read` on an id that doesn't exist or isn't yours. |

---

## 7. Frontend implementation checklist

- [ ] Global notification bell/badge in the app shell, backed by `GET /notifications/unread-count`
      on load and kept live via the WebSocket (increment on each `notification` frame).
- [ ] Open the WebSocket once at app/session start (not per-screen); reconnect with backoff on drop,
      and re-sync `unread-count` + page 1 of the list on reconnect.
- [ ] Notification panel/dropdown: `GET /notifications` (paginated, infinite scroll for "load more"),
      tapping an item calls `PATCH /notifications/{id}/read` then routes to its `link`.
- [ ] "Mark all as read" action wired to `POST /notifications/read-all`, clearing the badge locally.
- [ ] Render `title` always, `body` when present, and fall back gracefully when `link` is `null`
      (just mark read, don't navigate).
- [ ] Route `link` through your app's own router — it's a relative path, not a full URL.
- [ ] Optional: toast/snackbar on a live `notification` frame using `title`/`body`, with a tap target
      that routes to `link` and marks it read.
