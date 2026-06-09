import json
from typing import Any, Awaitable, Callable

import redis.asyncio as redis
import structlog
from pydantic import BaseModel

from image_search.domain.events import EventBus

logger = structlog.get_logger()


class RedisEventBus(EventBus):
    def __init__(self, redis_url: str) -> None:
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def emit(self, stream: str, event: BaseModel) -> str:
        payload = event.model_dump_json()
        msg_id = await self.redis.xadd(stream, {"data": payload})
        logger.info("event_emitted", stream=stream, msg_id=msg_id)
        return str(msg_id)

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        while True:
            results = await self.redis.xreadgroup(group, consumer, {stream: ">"}, count=1, block=5000)
            if not results:
                continue

            for _stream_name, messages in results:  # type: ignore[str-unpack]
                for msg_id, fields in messages:  # type: ignore[str-unpack,union-attr]
                    fields_dict: dict[str, Any] = fields  # type: ignore[assignment]
                    try:
                        payload: dict[str, Any] = json.loads(fields_dict["data"])
                        await handler(payload)
                        await self.redis.xack(stream, group, msg_id)
                        logger.info("event_processed", stream=stream, msg_id=msg_id)
                    except Exception as e:
                        logger.error(
                            "event_processing_failed",
                            stream=stream,
                            msg_id=msg_id,
                            error=str(e),
                        )
                        await self._handle_dead_letter(stream, group, msg_id, fields_dict, e)

    async def _handle_dead_letter(
        self,
        stream: str,
        group: str,
        msg_id: str,
        fields: dict[str, Any],
        error: Exception,
    ) -> None:
        pending = await self.redis.xpending_range(stream, group, msg_id, msg_id, 1)
        if pending and int(pending[0]["times_delivered"]) >= 3:
            dead_stream = f"{stream}:dead-letter"
            await self.redis.xadd(
                dead_stream,
                {
                    "original_stream": stream,
                    "original_msg_id": msg_id,
                    "data": fields["data"],
                    "error": str(error),
                },
            )
            await self.redis.xack(stream, group, msg_id)
            logger.warning("message_dead_lettered", stream=stream, msg_id=msg_id)

    async def close(self) -> None:
        await self.redis.close()
