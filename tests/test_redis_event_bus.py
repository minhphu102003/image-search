import asyncio
import json

import pytest
import redis.asyncio as redis

from image_search.domain.events import ImageIndexedEvent, ImageUploadedEvent
from image_search.infrastructure.redis.event_bus import RedisEventBus

TEST_REDIS_URL = "redis://localhost:6379"


@pytest.fixture
async def event_bus():
    bus = RedisEventBus(TEST_REDIS_URL)
    yield bus
    await bus.close()


@pytest.fixture
async def redis_client():
    client = redis.from_url(TEST_REDIS_URL, decode_responses=True)
    yield client
    await client.close()


async def _cleanup_stream(client: redis.Redis, stream: str) -> None:
    try:
        await client.delete(stream)
    except Exception:
        pass


@pytest.mark.asyncio
async def test_emit_adds_to_stream(event_bus: RedisEventBus, redis_client: redis.Redis) -> None:
    stream = "test:image:uploaded"
    await _cleanup_stream(redis_client, stream)

    event = ImageUploadedEvent(
        image_id="img-test-001",
        file_path="/storage/test.jpg",
        user_id="user-001",
    )
    msg_id = await event_bus.emit(stream, event)

    assert msg_id is not None

    messages = await redis_client.xrange(stream, count=1)
    assert len(messages) == 1
    payload = json.loads(messages[0][1]["data"])
    assert payload["image_id"] == "img-test-001"

    await _cleanup_stream(redis_client, stream)


@pytest.mark.asyncio
async def test_consume_with_ack(event_bus: RedisEventBus, redis_client: redis.Redis) -> None:
    stream = "test:image:consume"
    group = "test-group"
    consumer = "test-consumer"
    await _cleanup_stream(redis_client, stream)

    event = ImageIndexedEvent(image_id="img-001", status="indexed")
    await event_bus.emit(stream, event)

    received = []

    async def handler(payload: dict) -> None:
        received.append(payload)

    # Run consume with a timeout so it doesn't block forever
    async def run_consume():
        await event_bus.consume(stream, group, consumer, handler)

    try:
        await asyncio.wait_for(run_consume(), timeout=3.0)
    except asyncio.TimeoutError:
        pass

    assert len(received) == 1
    assert received[0]["image_id"] == "img-001"

    # Verify message was ACKed
    pending = await redis_client.xpending(stream, group)
    assert pending is None or pending["pending"] == 0

    # Cleanup consumer group
    try:
        await redis_client.xgroup_destroy(stream, group)
    except Exception:
        pass
    await _cleanup_stream(redis_client, stream)


@pytest.mark.asyncio
async def test_dead_letter_after_failures(event_bus: RedisEventBus, redis_client: redis.Redis) -> None:
    stream = "test:image:dead-letter-test"
    dead_stream = f"{stream}:dead-letter"
    group = "test-dl-group"
    consumer = "test-dl-consumer"
    await _cleanup_stream(redis_client, stream)
    await _cleanup_stream(redis_client, dead_stream)

    event = ImageUploadedEvent(
        image_id="img-dl-001",
        file_path="/path",
        user_id="user-001",
    )
    await event_bus.emit(stream, event)

    call_count = 0

    async def failing_handler(payload: dict) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("simulated failure")

    # Manually trigger consume iterations to simulate 3 failures
    # We can't use the infinite loop, so we test _handle_dead_letter directly
    try:
        await redis_client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.ResponseError:
        pass

    # Read and fail 3 times
    for _ in range(3):
        results = await redis_client.xreadgroup(group, consumer, {stream: ">"}, count=1, block=1000)
        if results:
            for _, messages in results:
                for msg_id, fields in messages:
                    try:
                        payload = json.loads(fields["data"])
                        await failing_handler(payload)
                    except Exception as e:
                        await event_bus._handle_dead_letter(stream, group, msg_id, fields, e)

    assert call_count == 3

    # Verify message was moved to dead-letter stream
    dead_messages = await redis_client.xrange(dead_stream, count=10)
    assert len(dead_messages) == 1
    dead_payload = json.loads(dead_messages[0][1]["data"])
    assert dead_payload["image_id"] == "img-dl-001"

    # Cleanup
    try:
        await redis_client.xgroup_destroy(stream, group)
    except Exception:
        pass
    await _cleanup_stream(redis_client, stream)
    await _cleanup_stream(redis_client, dead_stream)


@pytest.mark.asyncio
async def test_consumer_group_auto_creation(event_bus: RedisEventBus, redis_client: redis.Redis) -> None:
    stream = "test:image:group-auto"
    group = "auto-created-group"
    await _cleanup_stream(redis_client, stream)

    event = ImageIndexedEvent(image_id="img-002", status="indexed")
    await event_bus.emit(stream, event)

    received = []

    async def handler(payload: dict) -> None:
        received.append(payload)

    async def run_consume():
        await event_bus.consume(stream, group, "consumer-1", handler)

    try:
        await asyncio.wait_for(run_consume(), timeout=3.0)
    except asyncio.TimeoutError:
        pass

    assert len(received) == 1

    # Verify group exists
    groups = await redis_client.xinfo_groups(stream)
    group_names = [g["name"] for g in groups]
    assert group in group_names

    # Cleanup
    try:
        await redis_client.xgroup_destroy(stream, group)
    except Exception:
        pass
    await _cleanup_stream(redis_client, stream)
