"""Allowlisted JSON request logs; no headers, query values, bodies or tracebacks."""

import json
import logging
import re
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("sibase.requests")
SAFE_PATHS = {
    "/health/live",
    "/health/ready",
    "/api/v1/overview",
    "/api/v1/health",
    "/api/docs",
    "/api/openapi.json",
}


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False


class RequestLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(b"x-request-id", b"").decode("ascii", errors="ignore")
        request_id = supplied if re.fullmatch(r"[a-fA-F0-9-]{36}", supplied) else str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status = 500
        response_started = False

        async def send_response(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-request-id", request_id.encode()),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception:
            # Do not let Uvicorn serialize arbitrary exception text (which can
            # contain connection URLs). The request ID identifies the failure.
            if not response_started:
                response = JSONResponse({"detail": "Internal server error"}, status_code=500)
                await response(scope, receive, send_response)
        finally:
            logger.info(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "event": "http_request",
                        "request_id": request_id,
                        "method": scope["method"],
                        "route": scope["path"] if scope["path"] in SAFE_PATHS else "[unmatched]",
                        "status": status,
                        "duration_ms": round((perf_counter() - started) * 1000),
                    }
                )
            )
