import json
import uuid
from typing import Any

import app.core.cache as cache_module


def ticket_channel(ticket_id: uuid.UUID) -> str:
    return f"support:ticket:{ticket_id}"


async def publish_ticket_event(ticket_id: uuid.UUID, event: dict[str, Any]) -> None:
    """Fans a ticket-visible event (new message, status change, assignment) out to
    every WebSocket connection subscribed to this ticket, across all worker
    processes. Called from `SupportService` after every commit that produces a
    client-visible change - see `app/modules/support/router.py` for the
    subscriber side.

    Reads `cache_module.redis_client` at call time - see the comment in
    `app/modules/support/presence.py` for why a direct `from ... import redis_client`
    would freeze this at None."""
    if cache_module.redis_client is None:
        return
    try:
        await cache_module.redis_client.publish(ticket_channel(ticket_id), json.dumps(event, default=str))
    except Exception:
        pass
