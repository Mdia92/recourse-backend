"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings, load_uipath_config
from orchestration.routes import router as claims_router
from orchestration.webhooks.router import router as webhooks_router

logger = logging.getLogger("recourse")


def configure_logging(*, debug: bool) -> None:
    """Configure application-wide logging for the API server."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log inbound HTTP requests and response status without exposing secrets."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate environment configuration before accepting traffic."""
    settings = get_settings()
    configure_logging(debug=settings.debug)

    logger.info("Starting %s (%s)", settings.app_name, settings.environment)
    logger.info("Validating UiPath environment configuration...")

    uipath_config = load_uipath_config()
    logger.info(
        "UiPath config validated — organization=%s tenant=%s maestro_base=%s",
        uipath_config.organization_name,
        uipath_config.tenant_name,
        uipath_config.maestro_api_base_url,
    )

    app.state.uipath_config = uipath_config
    app.state.settings = settings

    logger.info("Recourse backend is ready to accept requests")
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        description="Intelligent agent backend for UiPath Maestro Case blueprint",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestLoggingMiddleware)

    application.include_router(claims_router)
    application.include_router(webhooks_router, prefix="/webhooks", tags=["webhooks"])

    @application.get("/health")
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok", "service": settings.app_name}

    return application


app = create_app()
