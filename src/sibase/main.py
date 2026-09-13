from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sibase import __version__
from sibase.config import Settings
from sibase.logging import RequestLogMiddleware, configure_logging
from sibase.models import Overview
from sibase.monitor import Monitor


def create_app(settings: Settings | None = None, monitor: Monitor | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.monitor = monitor or Monitor(settings or Settings.load())
        yield
        await app.state.monitor.close()

    app = FastAPI(
        title="SiBase Control API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        description="Local Phase 1 health/read-only API. No platform identity or provisioning yet.",
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "api", "dashboard", "testserver"],
    )
    app.add_middleware(RequestLogMiddleware)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ready")
    @app.get("/api/v1/health")
    async def ready(request: Request) -> JSONResponse:
        result = await request.app.state.monitor.platform()
        return JSONResponse(
            {"status": "ready" if result.status == "up" else "not_ready"},
            status_code=200 if result.status == "up" else 503,
        )

    @app.get("/api/v1/overview", response_model=Overview)
    async def overview(request: Request) -> Overview:
        result: Overview = await request.app.state.monitor.overview()
        return result

    return app
