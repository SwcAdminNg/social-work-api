from datetime import datetime
from urllib.parse import quote

from icalendar import Calendar, Event


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
) -> bytes:
    """Builds a standards-compliant .ics invite any calendar app (Google, Outlook,
    Apple) can import - no OAuth/API integration needed on either side."""
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
