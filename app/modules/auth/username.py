import re
import secrets

from app.modules.user.repository import UserRepository

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _slugify(value: str) -> str:
    return _NON_ALNUM.sub("", value.lower())


def _base_candidates(first_name: str, last_name: str) -> list[str]:
    first = _slugify(first_name)
    last = _slugify(last_name)
    if not first and not last:
        return []

    candidates = [
        f"{first}{last}",
        f"{first}.{last}",
        f"{first}{last[:1]}",
        f"{first[:1]}{last}",
        f"{last}{first}",
    ]
    # Preserve order while dropping duplicates/empties.
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


async def generate_username_suggestions(
    repository: UserRepository, first_name: str, last_name: str, count: int = 5
) -> list[str]:
    """Builds `count` unique, available username suggestions from a first/last name."""
    suggestions: list[str] = []
    base_candidates = _base_candidates(first_name, last_name) or ["user"]

    for base in base_candidates:
        if len(suggestions) >= count:
            break
        if not await repository.username_exists(base):
            suggestions.append(base)

    primary_base = base_candidates[0]
    attempts = 0
    while len(suggestions) < count and attempts < 25:
        attempts += 1
        candidate = f"{primary_base}{secrets.randbelow(900) + 100}"
        if candidate not in suggestions and not await repository.username_exists(candidate):
            suggestions.append(candidate)

    return suggestions[:count]
