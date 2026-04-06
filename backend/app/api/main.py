"""
EWC Compute Platform — FastAPI application entry point.

Startup sequence:
  1. Load settings from environment (pydantic-settings)
  2. Connect to MongoDB Atlas (motor)
  3. Connect to Redis (job queue health check)
  4. Mount API routers
  5. Configure OpenTelemetry tracing

All routes are versioned under /api/v1/.
The /health endpoint is unversioned for infrastructure liveness probes.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import auth, health, projects, twins
from app.core.config import settings
from app.core.cache import close_redis, init_redis
from app.core.database import close_db, init_db
from app.core.logging import configure_logging
from app.core.middleware import AuditLogMiddleware, RequestTracingMiddleware
from app.core.telemetry import configure_telemetry

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""
    configure_logging()
    configure_telemetry()

    logger.info(
        "ewc_compute.startup",
        environment=settings.APP_ENV,
        version=settings.APP_VERSION,
    )

    await init_db()
    logger.info("ewc_compute.db.connected", db=settings.MONGODB_DB_NAME)

    await init_redis()
    logger.info("ewc_compute.cache.connected", url=settings.REDIS_URL)

    yield

    await close_db()
    await close_redis()
    logger.info("ewc_compute.shutdown")


def create_application() -> FastAPI:
    """Factory function — returns a configured FastAPI application instance."""
    app = FastAPI(
        title="EWC Compute Platform",
        description=(
            "General-purpose digital industrial engineering platform. "
            "Digital Twin Engine · Sim Templates · KPI Dashboards · Physical AI Assistant."
        ),
        version=settings.APP_VERSION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.APP_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Custom middleware ──────────────────────────────────────────────────
    app.add_middleware(RequestTracingMiddleware)   # Adds trace-id to every request
    app.add_middleware(AuditLogMiddleware)         # Logs write operations for audit trail

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(health.router)                            # /health  (unversioned)
    app.include_router(auth.router,     prefix="/api/v1")        # /api/v1/auth/*
    app.include_router(projects.router, prefix="/api/v1")        # /api/v1/projects/*
    app.include_router(twins.router,    prefix="/api/v1")        # /api/v1/twins/*

    return app


app = create_application()
