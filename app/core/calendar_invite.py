from datetime import datetime
from urllib.parse import quote

from icalendar import Calendar, Event, vCalAddress, vText


def _utc_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    uid: str,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    location_url: str,
    organizer_email: str,
    attendee_email: str,
    attendee_name: str | None = None,
) -> bytes:
    """Builds a standards-compliant .ics invite any calendar app (Google, Outlook,
    Apple) can import - no OAuth/API integration needed on either side.

    Always sets a single ATTENDEE (the recipient this specific .ics is being sent
    to - each recipient needs their own bytes, built separately, not one shared
    file). Without an ATTENDEE, most calendar apps have nothing to match the
    importing person against, so they import the event as a plain entry they own
    outright - which is why "Invite others"/"Add guests" shows up on it. With an
    ATTENDEE (and an ORGANIZER that isn't them), the importing person is
    recognized as a guest of someone else's event instead, which is what hides
    that control - it's an organizer-only affordance in every major calendar app.
    There's no ICS-level equivalent of the Google Calendar API's
    `guestsCanInviteOthers` flag to set this more directly; that flag only exists
    for events created via the API on a calendar the caller controls, not for a
    generically emailed/downloaded .ics."""
    calendar = Calendar()
    calendar.add("prodid", "-//Social Work Nigeria//Live Session//EN")
    calendar.add("version", "2.0")
    calendar.add("method", "REQUEST")

    event = Event()
    event.add("uid", uid)
    event.add("summary", summary)
    event.add("description", description)
    event.add("dtstart", start)
    event.add("dtend", end)
    event.add("dtstamp", datetime.utcnow())
    event.add("location", location_url)
    event.add("organizer", f"mailto:{organizer_email}")

    attendee = vCalAddress(f"mailto:{attendee_email}")
    attendee.params["cn"] = vText(attendee_name or attendee_email)
    attendee.params["role"] = vText("REQ-PARTICIPANT")
    attendee.params["partstat"] = vText("NEEDS-ACTION")
    attendee.params["rsvp"] = vText("TRUE")
    event.add("attendee", attendee, encode=0)

    calendar.add_component(event)

    return calendar.to_ical()


def build_calendar_links(summary: str, description: str, start: datetime, end: datetime, location_url: str) -> dict:
    """One-click 'Add to Calendar' links - plain URL templates, no auth required."""
    dates = f"{_utc_stamp(start)}/{_utc_stamp(end)}"
    google_url = (
        "https://calendar.google.com/calendar/render"
        f"?action=TEMPLATE&text={quote(summary)}&dates={dates}"
        f"&details={quote(description)}&location={quote(location_url)}"
    )
    outlook_url = (
        "https://outlook.live.com/calendar/0/deeplink/compose"
        f"?path=/calendar/action/compose&rru=addevent&subject={quote(summary)}"
        f"&startdt={start.isoformat()}&enddt={end.isoformat()}"
        f"&body={quote(description)}&location={quote(location_url)}"
    )
    return {"google": google_url, "outlook": outlook_url}
