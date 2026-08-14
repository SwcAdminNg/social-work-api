import hashlib
from urllib.parse import quote

# A small curated palette so generated avatars look intentional rather than random.
_AVATAR_PALETTE = [
    "6D28D9", "DB2777", "059669", "2563EB", "D97706",
    "DC2626", "0891B2", "7C3AED", "BE185D", "16A34A",
]


def build_initials_avatar_url(name: str | None) -> str | None:
    """Builds a URL for a generated avatar image showing the first letter of
    `name` on a deterministic background color (same name always gets the same
    color). Returns None if a usable avatar can't be built - callers should
    treat that as "no avatar available" rather than surface an error."""
    try:
        name = (name or "").strip()
        if not name:
            return None
        initial = name[0].upper()
        color_index = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(_AVATAR_PALETTE)
        background = _AVATAR_PALETTE[color_index]
        return (
            "https://ui-avatars.com/api/"
            f"?name={quote(initial)}&background={background}&color=ffffff&size=256&bold=true&length=1"
        )
    except Exception:
        return None
