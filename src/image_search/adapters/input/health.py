"""Health check endpoint with dependency status."""

from fastapi import APIRouter
from sqlalchemy import text

from image_search.infrastructure.database.connection import async_session

router = APIRouter(tags=["health"])


async def _check_redis() -> str:
    try:
        import redis.asyncio as redis

        from image_search.infrastructure.config import settings

        r = redis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        return "ok"
    except Exception:
        return "error"


async def _check_postgresql() -> str:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


@router.get("/health")
async def health() -> dict[str, object]:
    redis_status = await _check_redis()
    pg_status = await _check_postgresql()

    checks: dict[str, str] = {
        "redis": redis_status,
        "postgresql": pg_status,
    }

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
