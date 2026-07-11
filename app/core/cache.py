import json
from typing import Any, Optional

import redis.asyncio as redis
from app.core.config import settings

# Global redis client instance
redis_client: Optional[redis.Redis] = None

async def init_redis() -> None:
    global redis_client
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    # Test connection
    try:
        await redis_client.ping()
        print("Connected to Redis successfully.")
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
        redis_client = None

async def close_redis() -> None:
    global redis_client
    if redis_client is not None:
        await redis_client.aclose()

async def get_cache(key: str) -> Optional[Any]:
    if redis_client is None:
        return None
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        # Silently fail on cache errors to not break the app
        print(f"Redis get error: {e}")
    return None

async def set_cache(key: str, value: Any, expire: int = 300) -> None:
    if redis_client is None:
        return
    try:
        data = json.dumps(value)
        await redis_client.set(key, data, ex=expire)
    except Exception as e:
        print(f"Redis set error: {e}")

async def delete_cache(pattern: str) -> None:
    if redis_client is None:
        return
    try:
        # For simple keys
        if '*' not in pattern:
            await redis_client.delete(pattern)
            return
            
        # For patterns
        cursor = '0'
        while cursor != 0:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis_client.delete(*keys)
    except Exception as e:
        print(f"Redis delete error: {e}")
