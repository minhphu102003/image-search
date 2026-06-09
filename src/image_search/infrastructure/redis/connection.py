import redis.asyncio as redis

from image_search.infrastructure.config import settings
from image_search.infrastructure.redis.event_bus import RedisEventBus


async def create_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)


def create_event_bus() -> RedisEventBus:
    return RedisEventBus(settings.redis_url)
