"""
middleware — ASGI middleware stack for the Hub FastAPI application.

``build_middleware_stack`` registers all standard middlewares in the
correct order onto a ``FastAPI`` instance: session, CSP, CSRF, HTMX
headers, request-id, i18n, rate limiting, body-size limit, proxy fix,
timeout, and trailing-slash redirect. ``MiddlewareStackManager`` handles
hot-reload of per-module middleware when modules are activated or
deactivated at runtime.

Key exports::

    from hotframe.middleware.stack import build_middleware_stack
    from hotframe.middleware.stack_manager import MiddlewareStackManager

Usage::

    build_middleware_stack(app, settings)
    manager = MiddlewareStackManager(app)
    await manager.mount_module_middleware(module_config)
"""
