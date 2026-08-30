import uuid

import app.core.cache as cache_module

_ONLINE_TTL_SECONDS = 60


def _key(namespace: str, user_id: uuid.UUID) -> str:
    return f"{namespace}:online:{user_id}"


async def mark_online(namespace: str, user_id: uuid.UUID) -> None:
    """Refreshes a short-TTL heartbeat key for `user_id` within `namespace`. Called
    on WebSocket connect/ping and from a presence heartbeat endpoint. TTL expiry
    (rather than an explicit disconnect handler) is the primary way a user is
    considered to have gone offline.

    Reads `cache_module.redis_client` at call time (not imported by value) since
    the module-level client is None at import time and only set once `init_redis()`
    runs during app startup - importing the name directly would freeze this at None."""
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.set(_key(namespace, user_id), "1", ex=_ONLINE_TTL_SECONDS)
    except Exception:
        pass


async def mark_offline(namespace: str, user_id: uuid.UUID) -> None:
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.delete(_key(namespace, user_id))
    except Exception:
        pass


async def any_online(namespace: str, user_ids: list[uuid.UUID]) -> bool:
    """True if at least one of `user_ids` currently has a live heartbeat in
    `namespace`. If Redis is unavailable, fail open to False rather than raising."""
    if cache_module.redis_client is None or not user_ids:
        return False
    try:
        values = await cache_module.redis_client.mget([_key(namespace, uid) for uid in user_ids])
        return any(v is not None for v in values)
    except Exception:
        return False


async def online_subset(namespace: str, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Returns the subset of `user_ids` that currently have a live heartbeat in
    `namespace`. Unlike `any_online`, this is used where the caller needs to know
    *which* members are online (e.g. a community's "who's online" list), not just
    whether anyone is."""
    if cache_module.redis_client is None or not user_ids:
        return []
    try:
        values = await cache_module.redis_client.mget([_key(namespace, uid) for uid in user_ids])
        return [uid for uid, v in zip(user_ids, values) if v is not None]
    except Exception:
        return []
