# Notifications — Admin API Reference

Realtime + inbox notifications for the admin dashboard: every admin gets their own notification feed
(new sign-ups, payments, support tickets, reviews, contact messages, etc.), delivered live over a
WebSocket and backed by the same paginated REST history used on the student side. This is the
companion to [`NOTIFICATIONS_STUDENT_API.md`](./NOTIFICATIONS_STUDENT_API.md) — **the endpoints,
auth model, response shapes, and WebSocket protocol are identical**; the only difference is which
`type`s land in an admin's feed vs. a student's. Read that doc for the full endpoint/WebSocket
mechanics — this doc focuses on what's admin-specific.

Base URL prefix for everything below: `/notifications`.

> ℹ️ Global response quirk: the API strips null/absent fields from JSON output. If a field isn't in
> the response, treat it as `null`/unset — don't treat its absence as an error.

---

## Conventions

- **Auth**: `Authorization: Bearer <token>` for an authenticated admin user (or the same JWT as a
  `?token=` query param for the WebSocket). There's no separate "admin" auth mode for this feature —
  an admin is just a `User` whose `user_type` is `ADMIN`, and notifications are addressed to a
  specific `user_id` the same way as on the student side.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for the list.
- **`link` is a relative path** into the admin dashboard's own route tree, e.g.
  `/dashboard/user-management/{user_id}` — prepend this app's own origin when routing.
- **Fan-out**: "admin" notifications aren't a special broadcast channel — when something needs every
  admin's attention, the backend writes one notification row **per active admin** and pushes each of
  them over their own `notifications/ws` connection. From the frontend's perspective this is no
  different from any other notification arriving in your feed.

---

## 1. The notification object

Identical shape to the student side — see
[`NOTIFICATIONS_STUDENT_API.md` §1](./NOTIFICATIONS_STUDENT_API.md#1-the-notification-object):

```json
{
  "id": "b6e2a1f0-....",
  "created_at": "2026-09-08T09:12:00Z",
  "type": "NEW_SUPPORT_TICKET",
  "title": "New support ticket",
  "body": "A new ticket was opened: \"Can't access my course\".",
  "link": "/dashboard/help-support/tickets/9c31....",
  "metadata_json": { "ticket_id": "9c31...." },
  "is_read": false,
  "read_at": null
}
```

---

## 2. REST endpoints & WebSocket

Exactly the same four REST endpoints and the same `WS /notifications/ws?token=...` protocol as the
student side — no admin-specific variants. See
[`NOTIFICATIONS_STUDENT_API.md` §2–3](./NOTIFICATIONS_STUDENT_API.md#2-reading-your-notifications-rest)
for full request/response detail. Quick reference:

| Endpoint | What it does |
|---|---|
| `GET /notifications` | Paginated list, newest first. `?unread_only=true` to filter. |
| `GET /notifications/unread-count` | Aggregate unread count for a badge. |
| `PATCH /notifications/{id}/read` | Mark one notification read. |
| `POST /notifications/read-all` | Mark every notification read. |
| `WS /notifications/ws?token=...` | Live push: `{ "type": "notification", "data": {...} }`. |

---

## 3. Notification types you'll see

### 3.1 Admin/back-office types (sent to every active admin)

These fire once and are written to **every currently-active admin's** feed — any admin can act on
them, so treat the first one to open it as having "claimed" it (there's no dedicated
claim/dismiss step beyond the normal `is_read` flag, which is per-admin anyway).

| `type` | Fires when | Example `link` |
|---|---|---|
| `NEW_USER_SIGNUP` | A new user (student) signs up. | `/dashboard/user-management/{user_id}` |
| `NEW_PAYMENT` | Any user completes a successful payment (course, cart, or subscription). | `/dashboard/payments` |
| `NEW_CONTACT_MESSAGE` | Someone submits the public contact-us form. | `/dashboard/contact-messages` |
| `NEW_SUPPORT_TICKET` | A user opens a new support ticket. | `/dashboard/help-support/tickets/{ticket_id}` |
| `NEW_COURSE_REVIEW` | A student submits a new course review. | `/dashboard/reviews` |
| `ADMIN_INVITE_ACCEPTED` | An invited admin finishes setting up their account and goes active. | `/dashboard/user-management` |

### 3.2 Directed to one specific admin

| `type` | Recipient | Fires when | Example `link` |
|---|---|---|---|
| `ADMIN_INVITED` | The invitee | You were just invited as an admin. | `/dashboard` (before they've even logged in — see note below) |
| `SUPPORT_TICKET_ASSIGNED` | The assignee | A ticket is assigned/reassigned to you. | `/dashboard/help-support/tickets/{ticket_id}` |
| `SUPPORT_TICKET_MESSAGE` | The ticket's assigned admin | The student replies to a ticket that's assigned to you. **Only sent if the ticket has an assigned admin** — an unassigned ticket relies on `NEW_SUPPORT_TICKET` having already alerted everyone. | `/dashboard/help-support/tickets/{ticket_id}` |

> **`ADMIN_INVITED`** is written at invite time, before the invitee has a password/can log in yet —
> it'll just be sitting in their feed the first time they log in post-acceptance. Don't rely on it
> for anything time-sensitive; the actual invite flow is driven by the emailed link, not this
> notification.

### 3.3 Account-level types (any admin, since an admin is a `User` too)

Same list as the student doc's §4 — `SIGNUP_WELCOME` doesn't apply to admins (they're created via
invite, not sign-up), but everything else can land on an admin's own feed the same way it would a
student's:

`LOGIN`, `PASSWORD_RESET_REQUESTED`, `PASSWORD_RESET_COMPLETED`, `PROFILE_PICTURE_UPDATED`,
`TWO_FACTOR_ENABLED`, `ACCOUNT_SUSPENDED`, `ACCOUNT_UNSUSPENDED`, `ROLE_CHANGED`.

These all link into the admin's own `/dashboard/profile` or `/dashboard/settings` — treat them the
same as any other notification; no special handling needed.

---

## 4. Error responses you should handle

| Status | When |
|---|---|
| `401` | Missing/invalid/expired token (REST: normal `401`; WebSocket: closes with code `4401`). |
| `404` | `PATCH /notifications/{id}/read` on an id that doesn't exist or isn't yours. |

---

## 5. Frontend implementation checklist

- [ ] Notification bell in the admin dashboard's top bar, badge from
      `GET /notifications/unread-count`, kept live via `WS /notifications/ws`.
- [ ] Route the §3.1 "back-office" types to their obvious destination screens (payments table,
      user management row, ticket detail, reviews queue, contact messages) via `link` — these are
      the ones worth a toast/desktop-notification treatment since they're actionable queue items.
- [ ] `NEW_SUPPORT_TICKET` and `SUPPORT_TICKET_ASSIGNED`/`SUPPORT_TICKET_MESSAGE` are good candidates
      for a distinct visual treatment (e.g. a separate "Support" filter/tab in the notification
      panel) since they're the highest-frequency admin-facing type in most deployments.
- [ ] Same "mark all read" / per-item mark-read / infinite-scroll list behavior as the student
      client — see [`NOTIFICATIONS_STUDENT_API.md` §7](./NOTIFICATIONS_STUDENT_API.md#7-frontend-implementation-checklist),
      it applies unchanged here.
- [ ] Since several admins can receive the *same* back-office event (e.g. `NEW_SUPPORT_TICKET` fans
      out to all admins), don't assume "unread count > 0 for me" means "nobody's looked at this yet"
      globally — it only reflects this admin's own read state.
