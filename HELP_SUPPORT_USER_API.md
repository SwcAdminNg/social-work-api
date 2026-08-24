# Help & Support — User API Reference

The end-user side of the GoDaddy/Namecheap-style help center: browse the FAQ first, and if that
doesn't resolve things, open a ticket and chat with Support Desk staff in real time. A separate doc
covers the admin/staff side (queue management, escalation rules) —
[`HELP_SUPPORT_ADMIN_API.md`](./HELP_SUPPORT_ADMIN_API.md).

Base URL prefix: `/support`.

## Conventions

- **Auth**: `GET /support/faq` is public (no `Authorization` header needed) — everything else
  requires `Authorization: Bearer <token>` for any authenticated user.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for lists.
- **Null stripping**: absent/null fields are stripped from JSON responses.

## 1. Browsing the FAQ

```
GET /support/faq
```

No auth required. Returns every published FAQ category with its published items, in display order:

```json
{
  "success": true,
  "message": "FAQ retrieved successfully",
  "data": [
    {
      "id": "...",
      "name": "Getting Started",
      "order": 1,
      "items": [
        { "id": "...", "category_id": "...", "question": "How do I reset my password?", "answer": "...", "order": 0, "is_published": true }
      ]
    }
  ]
}
```

## 2. Opening a ticket

```
POST /support/tickets
{ "subject": "Can't access my course", "message": "The video won't load" }
```

Creates a new ticket (status `OPEN`) with your message as the first entry, and immediately checks
whether Support Desk staff are available — if not, they're emailed right away (see the admin doc for
the exact rule). You get back the created ticket, including its `id`, which you'll use for chatting.

## 3. Chatting in real time (WebSocket)

```
wss://api.example.com/support/tickets/{ticket_id}/ws?token=<your-access-token>
```

Browsers can't set an `Authorization` header on a WebSocket handshake, so the JWT access token is
passed as a `token` query parameter instead — the same token you use for `Authorization: Bearer`.

The server rejects the handshake (before accepting the connection) if:
- the token is missing/invalid/expired,
- the ticket doesn't exist,
- you're not the ticket's owner (and not an admin).

**Sending a message** — send a JSON text frame:
```json
{ "type": "message", "body": "Still stuck, any update?" }
```

**Receiving messages** — every message on the ticket (including your own, once persisted, and the
other party's) arrives as:
```json
{ "type": "message", "data": { "id": "...", "ticket_id": "...", "sender_id": "...", "sender_type": "USER", "body": "...", "created_at": "...", "sender": { ...UserReadDTO } } }
```

Other event types you may receive on the same socket: `{"type": "assigned", "admin_id": "..."}` and
`{"type": "status_changed", "status": "RESOLVED"}`.

**Keeping the connection alive / marking yourself active**: optionally send `{"type": "ping"}`
periodically — it refreshes your presence heartbeat but otherwise does nothing.

**If your message is rejected** (e.g. the ticket was just closed), you'll receive an error frame
instead of a `message` echo:
```json
{ "type": "error", "detail": "This ticket is closed - please start a new ticket" }
```

### HTTP fallback

If you're not using WebSockets (e.g. a simple integration, or a push-notification-driven client),
you can send and read messages over plain HTTP instead:

| Method | Path | Description |
|---|---|---|
| GET | `/support/tickets/{ticket_id}/messages` | Paginated message history. |
| POST | `/support/tickets/{ticket_id}/messages` | Send a message. Body: `{ "body": str }`. Same validation/escalation rules as the WebSocket path. |

## 4. Managing your tickets

| Method | Path | Description |
|---|---|---|
| GET | `/support/tickets/mine` | Paginated list of your own tickets. |
| GET | `/support/tickets/{ticket_id}` | Get one of your tickets (or any ticket, if you're an admin). |

A ticket's `status` is one of `OPEN` → `IN_PROGRESS` (once an admin first replies) → `RESOLVED` /
`CLOSED` (set by an admin). Once `RESOLVED` or `CLOSED`, the ticket is terminal — you can't post more
messages to it (`409`); open a new ticket instead.

## 5. Rating your support experience

Once a ticket is `RESOLVED` or `CLOSED`, you can rate it:

```
POST /support/tickets/{ticket_id}/rating
{ "rating": 5, "comment": "Fast and helpful!" }
```

- `rating` is required, 1–5.
- `comment` is optional, up to 1000 characters.
- `400` if the ticket hasn't been resolved/closed yet.
- `409` if you've already rated this ticket — rating is one-time per ticket.
