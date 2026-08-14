def format_estimated_duration(total_minutes: int) -> str:
    """Human-friendly duration string that steps up a unit as the total grows:
    minutes -> hours (>= 60 min) -> days (>= 24 hr) -> weeks (>= 7 days). Shows
    up to two units, e.g. "45 mins", "2 hrs 15 mins", "3 days 4 hrs", "1 week 2 days"."""
    if total_minutes <= 0:
        return "0 mins"

    minutes = total_minutes % 60
    hours_total = total_minutes // 60

    if hours_total == 0:
        return f"{minutes} min" if minutes == 1 else f"{minutes} mins"

    hours = hours_total % 24
    days_total = hours_total // 24

    if days_total == 0:
        parts = [f"{hours} hr" if hours == 1 else f"{hours} hrs"]
        if minutes:
            parts.append(f"{minutes} min" if minutes == 1 else f"{minutes} mins")
        return " ".join(parts)

    days = days_total % 7
    weeks = days_total // 7

    if weeks == 0:
        parts = [f"{days_total} day" if days_total == 1 else f"{days_total} days"]
        if hours:
            parts.append(f"{hours} hr" if hours == 1 else f"{hours} hrs")
        return " ".join(parts)

    parts = [f"{weeks} week" if weeks == 1 else f"{weeks} weeks"]
    if days:
        parts.append(f"{days} day" if days == 1 else f"{days} days")
    return " ".join(parts)
