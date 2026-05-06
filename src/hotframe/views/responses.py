# SPDX-License-Identifier: Apache-2.0
"""
Unified ``@view`` decorator and reactive (Datastar) response helpers.

Detects the ``Datastar-Request`` header to decide between full-page and
partial rendering, mirroring the role HTMX used to play. Legacy
``htmx_*`` names are kept as aliases for backward compatibility and will
be removed in 0.3.

Permission resolution is configurable via ``settings.PERMISSION_RESOLVER``.
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import AsyncGenerator, Callable
from functools import lru_cache, wraps
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import TemplateNotFound
from sse_starlette.sse import EventSourceResponse
from starlette.responses import RedirectResponse, Response

from hotframe.auth.auth import get_session_user_id
from hotframe.reactivity import ServerSentEventGenerator, SSEResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission resolution
# ---------------------------------------------------------------------------


async def _resolve_permissions(request: Request, user_id: Any) -> list[str]:
    """Load user permissions via the configured PERMISSION_RESOLVER.

    Falls back to empty list if no resolver is configured.
    """
    from hotframe.config.settings import get_settings

    settings = get_settings()
    if not settings.PERMISSION_RESOLVER:
        return []

    module_path, func_name = settings.PERMISSION_RESOLVER.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    resolver = getattr(mod, func_name)
    return await resolver(request, user_id)


# ---------------------------------------------------------------------------
# Request introspection
# ---------------------------------------------------------------------------


def is_reactive_request(request: Request) -> bool:
    """Return ``True`` when the request was made by a Datastar client.

    Detection is based on the ``Datastar-Request`` header that the
    Datastar runtime attaches to fetch/SSE calls.
    """
    if "Datastar-Request" in request.headers:
        return True
    # Escape hatch for tests / manual calls — same convention as the legacy
    # HTMX path used.
    return request.query_params.get("partial") == "true"


# ---------------------------------------------------------------------------
# Template auto-discovery
# ---------------------------------------------------------------------------


_PARTIAL_PATTERNS = (
    "{module}/partials/{view}_content.html",
    "{module}/partials/{view}.html",
    "{module}/partials/{view}_list.html",
    "{module}/partials/{view}_form.html",
)

_FULL_PATTERNS = (
    "{module}/pages/{view}.html",
    "{module}/pages/{view}_list.html",
    "{module}/pages/{view}_form.html",
    "{module}/pages/list.html",
    "{module}/pages/index.html",
)


_ENV_BY_ID: dict[int, Any] = {}


def _register_env(env: Any) -> int:
    _ENV_BY_ID[id(env)] = env
    return id(env)


@lru_cache(maxsize=512)
def _resolve_template(env_id: int, module_id: str, view_id: str, kind: str) -> str:
    env = _ENV_BY_ID.get(env_id)
    if env is None:
        raise RuntimeError("Jinja2 environment not registered for template resolution")
    patterns = _PARTIAL_PATTERNS if kind == "partial" else _FULL_PATTERNS
    candidates: list[str] = []
    if kind == "full" and view_id == "dashboard":
        candidates.append(f"{module_id}/pages/index.html")
    for pattern in patterns:
        candidates.append(pattern.format(module=module_id, view=view_id))
    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    for name in ordered:
        try:
            env.get_template(name)
            return name
        except TemplateNotFound:
            continue
    return ordered[0]


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def view(
    full_template: str | None = None,
    partial_template: str | None = None,
    module_id: str | None = None,
    view_id: str | None = None,
    login_required: bool = True,
    permissions: list[str] | str | None = None,
) -> Callable:
    """Unified view decorator.

    Replaces the legacy ``@htmx_view``: detects Datastar requests via the
    ``Datastar-Request`` header and renders either the partial template
    (reactive request) or the full page template (regular browser
    navigation). Auth and permission checks are unchanged.
    """
    if isinstance(permissions, str):
        permissions = [permissions]

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Response:
            from hotframe.config.settings import get_settings

            settings = get_settings()

            # 1. Authentication
            if login_required:
                user_id = get_session_user_id(request)
                if user_id is None:
                    if is_reactive_request(request):
                        return reactive_redirect(settings.AUTH_LOGIN_URL)
                    return RedirectResponse(settings.AUTH_LOGIN_URL, status_code=302)

                if permissions:
                    from hotframe.auth.permissions import has_permission

                    user_perms: list[str] | None = getattr(
                        request.state,
                        "user_permissions",
                        None,
                    )
                    if user_perms is None:
                        user_perms = await _resolve_permissions(request, user_id)
                        request.state.user_permissions = user_perms

                    if not all(has_permission(user_perms, p) for p in permissions):
                        if is_reactive_request(request):
                            return reactive_redirect(settings.AUTH_UNAUTHORIZED_URL)
                        return RedirectResponse(settings.AUTH_UNAUTHORIZED_URL, status_code=302)

            # 2. Call the view function
            result = await func(request, *args, **kwargs)

            if isinstance(result, Response):
                return result

            context: dict[str, Any] = result if isinstance(result, dict) else {}

            # 3. Build template context
            from hotframe.templating.globals import get_global_context

            global_ctx = await get_global_context(request)
            merged = {**global_ctx, **context}

            if module_id:
                registry = getattr(request.app.state, "module_registry", None)
                navigation = registry.get_navigation(module_id) if registry else []
                merged["module_id"] = module_id
                merged["view_id"] = view_id
                merged["navigation"] = navigation
                merged["current_view"] = view_id
                merged["current_module"] = module_id

            # 4. Resolve templates
            _full = full_template
            _partial = partial_template

            templates = request.app.state.templates

            if module_id and view_id:
                env_id = _register_env(templates.env)
                if not _partial:
                    _partial = _resolve_template(env_id, module_id, view_id, "partial")
                if not _full:
                    _full = _resolve_template(env_id, module_id, view_id, "full")

            # 5. Render
            if is_reactive_request(request):
                return _render_partial(templates, request, merged, _partial, _full)
            return _render_full(templates, request, merged, _full, _partial)

        return wrapper

    return decorator


# Backward compat alias — to be removed in 0.3.
htmx_view = view


# ---------------------------------------------------------------------------
# Render helpers (private)
# ---------------------------------------------------------------------------


def _render_partial(
    templates: Any,
    request: Request,
    context: dict[str, Any],
    partial: str | None,
    full: str | None,
) -> Response:
    tpl_name = context.pop("template", None) or partial or full
    if not tpl_name:
        return HTMLResponse("No template configured", status_code=500)

    try:
        return templates.TemplateResponse(request, tpl_name, context)
    except Exception as exc:
        logger.error("Template render error in %s: %s", tpl_name, exc)
        return HTMLResponse(
            f'<div class="alert alert-error">'
            f"<strong>Template Error</strong>: {tpl_name}<br>"
            f"<small>{type(exc).__name__}: {exc}</small></div>",
            status_code=500,
        )


def _render_full(
    templates: Any,
    request: Request,
    context: dict[str, Any],
    full: str | None,
    partial: str | None,
) -> Response:
    context["content_template"] = context.pop("template", None) or partial
    tpl_name = full or "page_base.html"
    try:
        return templates.TemplateResponse(request, tpl_name, context)
    except Exception as exc:
        logger.error("Template render error in %s: %s", tpl_name, exc)
        return HTMLResponse(
            f'<div class="alert alert-error">'
            f"<strong>Template Error</strong>: {tpl_name}<br>"
            f"<small>{type(exc).__name__}: {exc}</small></div>",
            status_code=500,
        )


# ---------------------------------------------------------------------------
# Reactive (Datastar) response helpers
# ---------------------------------------------------------------------------


def reactive_redirect(url: str) -> SSEResponse:
    """Server-driven redirect for Datastar clients.

    Emits a single SSE event using ``ServerSentEventGenerator.redirect``.
    """
    return SSEResponse([ServerSentEventGenerator.redirect(url)])


def reactive_refresh() -> SSEResponse:
    """Force a full page reload on the Datastar client.

    Emits an ``execute_script`` SSE event running ``location.reload()``.
    """
    return SSEResponse([ServerSentEventGenerator.execute_script("location.reload()")])


def reactive_trigger(name: str, **detail: Any) -> SSEResponse:
    """Dispatch a custom DOM event on the Datastar client.

    Emits an ``execute_script`` SSE event that calls
    ``window.dispatchEvent(new CustomEvent(name, {detail: ...}))``.
    """
    payload = json.dumps(detail, ensure_ascii=False, default=str)
    script = f"window.dispatchEvent(new CustomEvent({json.dumps(name)}, {{detail: {payload}}}))"
    return SSEResponse([ServerSentEventGenerator.execute_script(script)])


# ---------------------------------------------------------------------------
# Backward-compat shims (legacy HTMX helpers)
# ---------------------------------------------------------------------------


def htmx_redirect(url: str) -> SSEResponse:
    """Legacy alias for :func:`reactive_redirect`. Removed in 0.3."""
    return reactive_redirect(url)


def htmx_refresh() -> SSEResponse:
    """Legacy alias for :func:`reactive_refresh`. Removed in 0.3."""
    return reactive_refresh()


def htmx_trigger(event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Legacy helper that returns a payload dict.

    Kept as a thin compatibility shim for callers still building
    ``HX-Trigger`` style dicts. Removed in 0.3.
    """
    if data:
        return {event: data}
    return {event: True}


def is_htmx_request(request: Request) -> bool:
    """Legacy alias for :func:`is_reactive_request`. Removed in 0.3."""
    return is_reactive_request(request)


# ---------------------------------------------------------------------------
# Flash / inline messages
# ---------------------------------------------------------------------------


def add_message(request: Request, level: str, text: str) -> None:
    """Append a flash message for the current request.

    Public API is unchanged. Internally, when the request is reactive
    (Datastar), the message is emitted as a ``patch_elements`` SSE event
    targeting ``#toast-container``; otherwise it is stored on the
    request for the session-flash middleware to pick up on the next
    full page response.
    """
    if not hasattr(request.state, "_messages"):
        request.state._messages = []
    request.state._messages.append({"level": level, "text": text})


def _toast_html(level: str, text: str) -> str:
    """Render the toast HTML used by reactive flash messages."""
    safe_level = (level or "info").replace('"', "")
    safe_text = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return (
        f'<div class="toast toast-{safe_level}" role="status">{safe_text}</div>'
    )


def reactive_message(level: str, text: str) -> SSEResponse:
    """Standalone reactive toast response.

    Useful when a handler wants to return *only* a toast without going
    through ``add_message`` + middleware. Emits a ``patch_elements`` SSE
    event that appends the toast into ``#toast-container``.
    """
    html = _toast_html(level, text)
    return SSEResponse(
        [
            ServerSentEventGenerator.patch_elements(
                html,
                selector="#toast-container",
                mode="append",
            )
        ]
    )


# ====== SSE Responses ======


async def sse_stream(
    request: Request,
    generator: AsyncGenerator[dict[str, Any] | str, None],
    *,
    event_type: str = "message",
    ping_interval: int = 15,
) -> EventSourceResponse:
    """Wrap an async generator as a Server-Sent Events response with disconnect detection."""

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        try:
            async for chunk in generator:
                if await request.is_disconnected():
                    logger.debug("SSE client disconnected, stopping stream")
                    break

                try:
                    data = (
                        json.dumps(chunk, ensure_ascii=False, default=str)
                        if isinstance(chunk, dict)
                        else str(chunk)
                    )
                except (TypeError, ValueError):
                    logger.warning("Failed to serialize SSE chunk, skipping", exc_info=True)
                    continue
                yield {"event": event_type, "data": data}

            yield {"event": "done", "data": ""}
        except Exception as exc:
            import traceback

            tb = traceback.format_exc()
            logger.error("Error in SSE stream: %s\n%s", exc, tb)
            yield {
                "event": "error",
                "data": json.dumps({"error": f"Internal server error: {exc}"}),
            }

    return EventSourceResponse(
        event_generator(),
        ping=ping_interval,
    )
