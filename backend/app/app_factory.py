from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.database import engine
from app.redis_runtime import redis_readiness_probe

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]
ReadinessCheck = Callable[[], bool]
logger = logging.getLogger(__name__)
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def create_api_app(
    service_name: str,
    *,
    lifespan: Lifespan | None = None,
    readiness_checks: dict[str, ReadinessCheck] | None = None,
) -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} · {service_name}",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_observability(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed service=%s method=%s path=%s request_id=%s",
                service_name,
                request.method,
                request.url.path,
                request_id,
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        logger.info(
            "request_completed service=%s method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
            service_name,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "Kai Gong Ba", "service": service_name}

    @app.get("/api/ready", tags=["health"])
    def readiness() -> JSONResponse:
        dependencies: dict[str, str] = {}
        ready = True
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            dependencies["database"] = "ok"
        except SQLAlchemyError:
            dependencies["database"] = "unavailable"
            ready = False
        if settings.redis_url:
            try:
                dependencies["redis"] = (
                    "ok" if redis_readiness_probe() else "unavailable"
                )
            except RedisError:
                dependencies["redis"] = "unavailable"
            ready = ready and dependencies["redis"] == "ok"
        else:
            dependencies["redis"] = "not_configured"
            ready = ready and settings.runtime_environment not in {"staging", "production"}
        for dependency_name, check in (readiness_checks or {}).items():
            try:
                available = bool(check())
            except Exception:
                logger.exception(
                    "readiness_check_failed service=%s dependency=%s",
                    service_name,
                    dependency_name,
                )
                available = False
            dependencies[dependency_name] = "ok" if available else "unavailable"
            ready = ready and available
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "app": "Kai Gong Ba",
                "service": service_name,
                "dependencies": dependencies,
            },
        )

    return app
