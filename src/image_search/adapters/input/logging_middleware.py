"""Logging middleware — logs every request/response with request_id propagation."""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger.info(
            "request_start",
            method=request.method,
            path=str(request.url.path),
            query=str(request.url.query) or None,
            client=request.client.host if request.client else None,
        )

        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_error", method=request.method, path=str(request.url.path))
            raise

        elapsed_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            "request_end",
            method=request.method,
            path=str(request.url.path),
            status=response.status_code,
            latency_ms=elapsed_ms,
        )

        response.headers["X-Request-ID"] = request_id
        structlog.contextvars.unbind_contextvars("request_id")
        return response
