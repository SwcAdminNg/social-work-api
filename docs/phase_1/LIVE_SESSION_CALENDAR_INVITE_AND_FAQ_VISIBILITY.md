# Live Session Calendar Invite Fix & FAQ Visibility — Change Notes

No new endpoints here — both changes are internal-behavior fixes to existing features. See
[`HELP_SUPPORT_USER_API.md`](./HELP_SUPPORT_USER_API.md) and
[`HELP_SUPPORT_ADMIN_API.md`](./HELP_SUPPORT_ADMIN_API.md) for the full, up-to-date FAQ API
reference (updated in place) — this doc just explains what changed and why.

## 1. Live session calendar invite: "Invite others" no longer shows up

**Where**: the `.ics` calendar-invite file attached to live-session emails (scheduled,
rescheduled, and external guest invites) — `app/core/calendar_invite.py`,
`app/modules/course/live_session_service.py`.

**The problem**: the `.ics` file built by `build_ics` set an `ORGANIZER` (the support email) but
no `ATTENDEE`. With no `ATTENDEE` for a calendar app to match the importing person against, most
calendar apps (Google Calendar in particular) import the event as a plain personal entry the
importer fully owns — same as if they'd created it themselves from scratch. Owning an event always
comes with "Add guests"/"Invite others", regardless of who the `ORGANIZER` field says — that
control is inherent to being the event's owner in every major calendar app, not something a file
can turn off directly.

**The fix**: `build_ics` now requires an `attendee_email` (+ optional `attendee_name`) and adds a
proper `ATTENDEE` property to the `VEVENT`, distinct from the `ORGANIZER`. With an `ORGANIZER` that
isn't them and an `ATTENDEE` entry that is, the recipient's calendar app now recognizes them as a
**guest of someone else's event**, not its owner — which is what actually hides "Invite others"
for them (an organizer-only affordance everywhere: Google Calendar, Outlook, Apple Calendar). They
still get RSVP controls (Accept/Decline/Maybe), same as any calendar invite.

```python
def build_ics(
    uid: str,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    location_url: str,
    organizer_email: str,
    attendee_email: str,       # new, required
    attendee_name: str | None = None,  # new, optional
) -> bytes: ...
```

**Why the `.ics` is now built per recipient, not once per session**: an `ATTENDEE` is specific to
one person, so a single shared `.ics` (previously built once and reused for every enrolled
student/guest in a notification batch) can no longer work — each recipient needs their own bytes
with their own email as `ATTENDEE`. `LiveSessionService._build_ics_for_recipient(...)` now builds
one per recipient inside the existing notification loops (`notify_enrolled_students`,
`send_external_invites`); nothing about the email-sending flow itself changed otherwise, and
sending is still one email (and thus one `.ics`) per recipient as before — this only changes what's
*inside* each recipient's own attachment.

**What this doesn't (and can't) change**: the "Add to Google Calendar" / "Add to Outlook" links in
the email body (`build_calendar_links`) are unaffected — those are one-click links that create a
*new*, self-owned event directly on the clicking user's own calendar via Google's/Outlook's web
compose screen, so the clicker is always that event's owner and "Invite others" is standard,
expected behaviour there, not something we control. There is also no `.ics`-level equivalent of the
Google Calendar **API's** `guestsCanInviteOthers` flag — that flag only exists for events created
through the Calendar API on a calendar the caller controls (OAuth), not for a generically
emailed/downloaded `.ics` file, which is the integration used here (no calendar OAuth on either
side, by design — see `build_ics`'s docstring).

## 2. FAQ visibility (GENERAL vs ACCOUNT)

**Where**: `app/modules/support/entity.py` (`FAQVisibilityEnum`, new `FAQItem.visibility` column),
`GET /support/faq`.

`FAQItem` gained a `visibility` field, independent of the existing `audience`
(`STUDENT`/`INSTRUCTOR`/`BOTH`) field:

| Value | Meaning |
|---|---|
| `GENERAL` (default) | Public — visible to anyone, no account needed. |
| `ACCOUNT` | Visible only to a signed-in caller (any `UserTypeEnum` — student, instructor, or admin). |

`GET /support/faq` now accepts an **optional** bearer token:

- No token → only `GENERAL` articles.
- Valid token (any account type) → every published article, `GENERAL` and `ACCOUNT` alike.

The `audience` query param still works exactly as before and is independent of `visibility` — it
narrows *which* articles among the ones the caller is already allowed to see, it doesn't grant
access on its own. Existing articles all default to `GENERAL` (migration `3e89f463599d`), so nothing
that was publicly visible before this change became hidden — admins opt specific articles into
`ACCOUNT` going forward via `POST`/`PATCH /support/faq/items`.

Full request/response shapes: [`HELP_SUPPORT_USER_API.md`](./HELP_SUPPORT_USER_API.md#1-browsing-the-faq)
(public side) and [`HELP_SUPPORT_ADMIN_API.md`](./HELP_SUPPORT_ADMIN_API.md#1-faq-management)
(admin CRUD).
