import json
import uuid
from typing import Any

import app.core.cache as cache_module


def channel_name(namespace: str, entity_id: uuid.UUID | str) -> str:
    return f"{namespace}:{entity_id}"


async def publish_event(namespace: str, entity_id: uuid.UUID | str, event: dict[str, Any]) -> None:
    """Fans an event out to every WebSocket connection subscribed to this channel,
    across all worker processes. See `app/modules/support/router.py` and
    `app/modules/community/router.py` for the subscriber side.

    Reads `cache_module.redis_client` at call time - see the comment in
    `app/core/presence.py` for why a direct `from ... import redis_client`
    would freeze this at None."""
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.publish(channel_name(namespace, entity_id), json.dumps(event, default=str))
    except Exception:
        pass
