import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.config import get_settings
from app.db import dispose_engine, ensure_schema, get_session_factory
from app.errors import register_error_handlers
from app.events import build_event_bus
from app.middleware import RateLimitMiddleware
from app.ratelimit import RateLimiter, RedisRateLimiter
from app.routers import (
    devices,
    enrolments,
    events,
    keys,
    me,
    messages,
    stats,
    webhooks,
    ws,
)
from app.services import ApiKeyService
from app.webhooks import WebhookDispatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("tsunagi")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    bus = build_event_bus(settings.redis_url, settings.event_log_max)
    await bus.start()
    app.state.bus = bus

    if settings.rate_limit_enabled:
        # Reuse the bus's Redis connection so replicas share one budget; without
        # Redis the counters are per-process, which is right for one worker.
        app.state.rate_limiter = (
            RedisRateLimiter(
                bus.redis, settings.rate_limit_requests, settings.rate_limit_window_seconds
            )
            if bus.redis is not None
            else RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
        )
        logger.info(
            "rate limiting: %s requests per %ss",
            settings.rate_limit_requests,
            settings.rate_limit_window_seconds,
        )
    else:
        app.state.rate_limiter = None

    if settings.auto_create_schema:
        await ensure_schema()

    async with get_session_factory()() as session:
        bootstrap_key = await ApiKeyService(session, bus).ensure_bootstrap_key(
            settings.bootstrap_api_key
        )
    if bootstrap_key and not settings.bootstrap_api_key:
        logger.warning(
            "No API keys existed, so an admin key was generated. Store it now, "
            "it will not be shown again: %s",
            bootstrap_key,
        )

    # Started after the bus and before the first request: it subscribes to the
    # bus, and a webhook registered before it is running would simply miss
    # whatever happened in between.
    dispatcher = WebhookDispatcher(bus)
    await dispatcher.start()
    app.state.webhooks = dispatcher

    await bus.emit("SYSTEM_INIT", payload_version=__version__)
    logger.info("tsunagi backend %s ready", __version__)

    try:
        yield
    finally:
        await dispatcher.close()
        await bus.close()
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Tsunagi",
        version=__version__,
        summary="Self-hosted SMS synchronization platform",
        lifespan=lifespan,
    )

    # Added first so it runs innermost, after CORS has had its say: a browser
    # preflight that is rejected without CORS headers surfaces as an opaque
    # network error instead of a readable 429.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    for router in (
        me.router,
        devices.router,
        enrolments.router,
        messages.router,
        keys.router,
        events.router,
        stats.router,
        webhooks.router,
    ):
        app.include_router(router)
    app.include_router(ws.router)

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
