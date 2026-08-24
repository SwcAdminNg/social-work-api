# Groups — Admin API Reference

Groups are simple, admin-managed named sets of users (e.g. **"Support Desk"**, **"Management"**),
used to target notifications and escalations at the right staff without hard-coding roles. They are
independent of `User.user_type` (`USER`/`INSTRUCTOR`/`ADMIN`) — a group is an organizational/
notification concept, not a permission level.

Base URL prefix: `/groups`.

## Conventions

- **Auth**: every endpoint requires `Authorization: Bearer <token>` for an `ADMIN` user
  (`get_current_admin_user`). There is no non-admin access to groups.
- **Response envelope**: `ApiResponse<T>` for single items, `PaginatedResponse<T>` for lists.
- **Null stripping**: absent/null fields are stripped from JSON responses.

## Seed data

Two groups are created automatically by migration `2ddcdef22856_create_groups_and_group_memberships`:

| Name | Purpose |
|---|---|
| `Support Desk` | Members (of any `user_type`) get **staff access** to every support ticket — the ticket queue, chat WebSocket, assign/resolve, and the escalation email when a ticket goes unanswered. `ADMIN` users always have this access regardless of group membership; adding an `INSTRUCTOR` here is what grants them the same access. See [`HELP_SUPPORT_ADMIN_API.md`](./HELP_SUPPORT_ADMIN_API.md). This is the **only** group the code currently reads. |
| `Management` | A placeholder group with no wired behavior today — nothing in the codebase currently reacts to membership in it. Safe to repurpose or leave empty. |

Deactivating or renaming "Support Desk" does not break anything, but the Help & Support escalation
logic looks it up **by name** (`GroupRepository.get_by_name("Support Desk")`) — if you rename it,
escalation emails silently stop firing (a warning is logged server-side) until either the name is
restored or the escalation lookup is updated.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/groups` | Create a group. Body: `{ "name": str, "description"?: str }`. `409` if the name already exists. |
| GET | `/groups` | Paginated list of all groups. |
| GET | `/groups/{group_id}` | Get one group. |
| PATCH | `/groups/{group_id}` | Partial update (`name`, `description`, `is_active`). |
| POST | `/groups/{group_id}/deactivate` | Sets `is_active=false`. Members are **not** removed — deactivation just stops the group counting for anything that filters on active groups; nothing in the codebase currently does that filtering, so today this is informational only. |
| GET | `/groups/{group_id}/members` | Paginated list of members, each embedding the full `UserReadDTO`. |
| POST | `/groups/{group_id}/members` | Add a user to the group. Body: `{ "user_id": uuid }`. `404` if the group or user doesn't exist, `409` if already a member. |
| DELETE | `/groups/{group_id}/members/{user_id}` | Remove a user from the group (soft-delete of the membership row). `404` if not a member. |
| GET | `/groups/users/{user_id}` | List every group a given user belongs to. |

## Example: adding an admin to Support Desk

```bash
curl -X POST https://api.example.com/groups/{support_desk_group_id}/members \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<admin-user-uuid>"}'
```

Only users added to "Support Desk" this way (and who are `is_active`) are ever emailed by the Help &
Support escalation flow.
