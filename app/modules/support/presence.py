import uuid

import app.core.cache as cache_module

_ONLINE_KEY_PREFIX = "support:online:"
_ONLINE_TTL_SECONDS = 60


def _key(user_id: uuid.UUID) -> str:
    return f"{_ONLINE_KEY_PREFIX}{user_id}"


async def mark_online(user_id: uuid.UUID) -> None:
    """Refreshes a short-TTL heartbeat key for `user_id`. Called on WebSocket
    connect/ping and from the `/support/presence/heartbeat` endpoint. TTL expiry
    (rather than an explicit disconnect handler) is the primary way a user is
    considered to have gone offline.

    Reads `cache_module.redis_client` at call time (not imported by value) since
    the module-level client is None at import time and only set once `init_redis()`
    runs during app startup - importing the name directly would freeze this at None."""
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.set(_key(user_id), "1", ex=_ONLINE_TTL_SECONDS)
    except Exception:
        pass


async def mark_offline(user_id: uuid.UUID) -> None:
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.delete(_key(user_id))
    except Exception:
        pass


async def any_online(user_ids: list[uuid.UUID]) -> bool:
    """True if at least one of `user_ids` currently has a live heartbeat. If Redis
    is unavailable, fail open to False so escalation still fires rather than
    silently going quiet - the emailed staff will just see a duplicate case."""
    if cache_module.redis_client is None or not user_ids:
        return False
    try:
        values = await cache_module.redis_client.mget([_key(uid) for uid in user_ids])
        return any(v is not None for v in values)
    except Exception:
        return False
