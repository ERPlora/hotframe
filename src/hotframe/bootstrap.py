# SPDX-License-Identifier: Apache-2.0
"""
FastAPI application factory with lifespan management.

Creates the application, initializes core systems on startup,
and cleans up resources on shutdown. Application-specific setup
(routers, models, services) is done by the user in their project.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from hotframe.config.settings import HotframeSettings

logger = logging.getLogger("hotframe")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    t0 = time.monotonic()

    # 1. Initialize database engine
    from hotframe.config.database import get_engine

    engine = get_engine()
    logger.info("Database engine initialized: %s", engine.url.render_as_string(hide_password=True))

    # 2. Create core registries
    from hotframe.signals.dispatcher import AsyncEventBus
    from hotframe.signals.hooks import HookRegistry
    from hotframe.templating.slots import SlotRegistry

    event_bus = AsyncEventBus()
    hooks = HookRegistry()
    slots = SlotRegistry()

    # 2b. Create broadcast hub (SSE/WS real-time fan-out)
    from hotframe.views.broadcast import BroadcastHub

    broadcast_hub = BroadcastHub()
    app.state.broadcast_hub = broadcast_hub

    # 3. Setup ORM event listeners (SQLAlchemy -> EventBus bridge)
    from hotframe.models.base import Base
    from hotframe.orm.events import setup_orm_events

    setup_orm_events(event_bus, base=Base)

    # 4. Store core systems on app.state for dependency injection
    app.state.event_bus = event_bus
    app.state.hooks = hooks
    app.state.slots = slots

    # 5. Initialize Jinja2 template engine
    from hotframe.config.settings import get_settings
    from hotframe.templating.engine import create_template_engine

    settings = get_settings()
    app.state.templates = create_template_engine(modules_dir=settings.MODULES_DIR)

    # 6. Initialize ModuleRuntime
    from hotframe.engine.module_runtime import ModuleRuntime

    runtime = ModuleRuntime(app, settings, event_bus, hooks, slots)
    app.state.module_runtime = runtime
    app.state.module_registry = runtime.registry

    elapsed = (time.monotonic() - t0) * 1000
    logger.info("Application started in %.0fms", elapsed)

    yield

    # --- SHUTDOWN ---
    if app.state.module_runtime is not None:
        await app.state.module_runtime.shutdown()

    from hotframe.config.database import dispose_engine

    await dispose_engine()
    logger.info("Application shutdown complete")


def create_app(settings: HotframeSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings instance. If None, loads from
                  environment using ``HotframeSettings()``.

    Returns:
        Configured FastAPI application.
    """
    from hotframe.config.settings import get_settings, set_settings

    if settings is not None:
        set_settings(settings)
    settings = get_settings()

    # --- Observability ---
    from hotframe.utils.observability_logging import setup_logging
    from hotframe.utils.observability_telemetry import setup_telemetry

    json_output = settings.LOG_FORMAT == "json" or (
        settings.LOG_FORMAT == "console" and settings.is_production
    )
    setup_logging(log_level=settings.LOG_LEVEL, json_output=json_output)
    try:
        setup_telemetry(
            debug=settings.DEBUG,
            service_name=settings.OTEL_SERVICE_NAME,
        )
    except Exception as exc:
        logger.warning("Telemetry setup failed (non-fatal): %s", exc)

    app = FastAPI(
        title=settings.APP_TITLE,
        version="0.1.0",
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # --- Middleware stack (from settings.MIDDLEWARE) ---
    from hotframe.middleware.stack import build_middleware_stack

    build_middleware_stack(app, settings)

    # --- CORS (optional — enabled when CORS_ORIGINS is set) ---
    if settings.CORS_ORIGINS:
        from starlette.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_methods=settings.CORS_METHODS,
            allow_headers=settings.CORS_HEADERS,
            allow_credentials=settings.CORS_CREDENTIALS,
        )

    # --- Proxy fix (optional) ---
    if settings.PROXY_FIX_ENABLED:
        from hotframe.middleware.proxy_fix import ProxyFixMiddleware

        app.add_middleware(
            ProxyFixMiddleware,
            slug=settings.PROXY_SLUG,
            domain_base=settings.PROXY_DOMAIN_BASE,
            ecs_region=settings.PROXY_AWS_REGION,
        )

    # --- Rate limiter singleton ---
    from hotframe.auth.rate_limit import PINRateLimiter

    app.state.rate_limiter = PINRateLimiter()

    # --- Broadcast router (SSE real-time) ---
    from hotframe.views.broadcast import broadcast_router

    app.include_router(broadcast_router)

    # --- Health check ---
    @app.get("/health", tags=["system"])
    async def health():
        return {"status": "ok"}

    # --- Auto-discover app routers ---
    _auto_discover_apps(app)

    # --- Static files ---
    from pathlib import Path as _Path

    from fastapi.staticfiles import StaticFiles

    static_root = _Path(settings.STATIC_ROOT).resolve()
    if static_root.exists():
        app.mount(settings.STATIC_URL, StaticFiles(directory=str(static_root)), name="static")

    # --- Media files (local dev only) ---
    if settings.MEDIA_STORAGE == "local" and settings.DEBUG:
        media_root = _Path(settings.MEDIA_ROOT).resolve()
        media_root.mkdir(parents=True, exist_ok=True)
        app.mount(settings.MEDIA_URL, StaticFiles(directory=str(media_root)), name="media")

    # --- Error handlers ---
    login_url = settings.AUTH_LOGIN_URL

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        from starlette.responses import RedirectResponse

        return RedirectResponse(url=login_url, status_code=302)

    @app.exception_handler(403)
    async def forbidden_handler(request: Request, exc):
        templates = request.app.state.templates
        nonce = getattr(request.state, "csp_nonce", "")
        return templates.TemplateResponse(
            request, "errors/403.html",
            {"request": request, "csp_nonce": nonce},
            status_code=403,
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc):
        templates = request.app.state.templates
        nonce = getattr(request.state, "csp_nonce", "")
        return templates.TemplateResponse(
            request, "errors/405.html",
            {"request": request, "csp_nonce": nonce},
            status_code=405,
        )

    return app


# ---------------------------------------------------------------------------
# App auto-discovery
# ---------------------------------------------------------------------------


def _auto_discover_apps(app: FastAPI) -> None:
    """Auto-discover and mount app routers from apps/ directory.

    Scans ``apps/*/`` for ``routes.py`` (HTMX views) and ``api.py``
    (REST API) and mounts any ``router`` / ``api_router`` found.

    Also calls ``AppConfig.ready()`` if ``app.py`` defines one.

    If ``settings.INSTALLED_APPS`` is set, only those apps are loaded
    (in that order). Otherwise, all apps in ``apps/`` are loaded
    alphabetically.
    """
    import importlib
    from pathlib import Path

    from hotframe.config.settings import get_settings

    settings = get_settings()
    apps_dir = Path.cwd() / "apps"

    if not apps_dir.exists():
        return

    # Auto-discover all apps
    app_names = sorted(
        d.name
        for d in apps_dir.iterdir()
        if d.is_dir()
        and not d.name.startswith((".", "_"))
        and (d / "__init__.py").exists()
        )

    mounted = []

    for name in app_names:
        app_dir = apps_dir / name
        if not app_dir.exists():
            logger.warning("INSTALLED_APPS: app '%s' not found in apps/", name)
            continue

        # Mount views router (routes.py → router)
        try:
            mod = importlib.import_module(f"apps.{name}.routes")
            router = getattr(mod, "router", None)
            if router:
                app.include_router(router)
                mounted.append(name)
        except ImportError:
            pass
        except Exception:
            logger.exception("Failed to load routes for app '%s'", name)

        # Mount API router (api.py → api_router)
        try:
            mod = importlib.import_module(f"apps.{name}.api")
            api_router = getattr(mod, "api_router", None)
            if api_router:
                app.include_router(api_router)
        except ImportError:
            pass
        except Exception:
            logger.exception("Failed to load API for app '%s'", name)

        # Call AppConfig.ready() if defined
        try:
            mod = importlib.import_module(f"apps.{name}.app")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and hasattr(attr, "ready")
                    and hasattr(attr, "name")
                    and getattr(attr, "name", None) == name
                ):
                    config = attr()
                    if callable(config.ready):
                        config.ready()
                    break
        except ImportError:
            pass
        except Exception:
            logger.exception("Failed to call ready() for app '%s'", name)

    # Mount extra routers from settings
    for dotted_path in settings.EXTRA_ROUTERS:
        try:
            module_path, attr_name = dotted_path.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            router = getattr(mod, attr_name)
            app.include_router(router)
            mounted.append(f"extra:{dotted_path}")
        except Exception:
            logger.exception("Failed to load extra router: %s", dotted_path)

    if mounted:
        logger.info("Auto-discovered %d app(s): %s", len(mounted), ", ".join(mounted))
