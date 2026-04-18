# SPDX-License-Identifier: Apache-2.0
"""
Unified ``@htmx_view`` decorator and HTMX response helpers.

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


def is_htmx_request(request: Request) -> bool:
    """Check whether the current request was made by HTMX.

    Returns ``True`` for HTMX requests but ``False`` for boosted requests.
    """
    htmx = getattr(request.state, "htmx", None)
    if htmx and htmx.is_htmx:
        return not htmx.boosted
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


def htmx_view(
    full_template: str | None = None,
    partial_template: str | None = None,
    module_id: str | None = None,
    view_id: str | None = None,
    login_required: bool = True,
    permissions: list[str] | str | None = None,
) -> Callable:
    """Unified view decorator for all views."""
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
                    htmx_details = getattr(request.state, "htmx", None)
                    if htmx_details and htmx_details.is_htmx:
                        return htmx_redirect(settings.AUTH_LOGIN_URL)
                    return RedirectResponse(settings.AUTH_LOGIN_URL, status_code=302)

                if permissions:
                    from hotframe.auth.permissions import has_permission

                    user_perms: list[str] = getattr(
                        request.state,
                        "user_permissions",
                        None,
                    )
                    if user_perms is None:
                        user_perms = await _resolve_permissions(request, user_id)
                        request.state.user_permissions = user_perms

                    if not all(has_permission(user_perms, p) for p in permissions):
                        htmx_details = getattr(request.state, "htmx", None)
                        if htmx_details and htmx_details.is_htmx:
                            return htmx_redirect(settings.AUTH_UNAUTHORIZED_URL)
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
            if is_htmx_request(request):
                return _render_htmx(templates, request, merged, _partial, _full, module_id)
            return _render_full(templates, request, merged, _full, _partial)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Render helpers (private)
# ---------------------------------------------------------------------------


def _render_htmx(
    templates: Any,
    request: Request,
    context: dict[str, Any],
    partial: str | None,
    full: str | None,
    module_id: str | None,
) -> Response:
    tpl_name = context.pop("template", None) or partial or full
    if not tpl_name:
        return HTMLResponse("No template configured", status_code=500)

    try:
        response = templates.TemplateResponse(request, tpl_name, context)
    except Exception as exc:
        logger.error("Template render error in %s: %s", tpl_name, exc)
        return HTMLResponse(
            f'<div class="alert alert-error">'
            f"<strong>Template Error</strong>: {tpl_name}<br>"
            f"<small>{type(exc).__name__}: {exc}</small></div>",
            status_code=500,
        )

    page_title = context.get("page_title")
    if page_title:
        response.headers["HX-Trigger"] = json.dumps({"pageTitle": str(page_title)})

    body = response.body.decode("utf-8")

    if context.get("navigation"):
        try:
            oob_html = templates.env.get_template("partials/tabbar_oob.html").render(**context)
            body += oob_html
        except Exception:
            logger.debug("tabbar_oob.html not found, skipping OOB swap")
    else:
        body += (
            '<footer id="global-tabbar-footer" class="m-2 rounded-box" hx-swap-oob="true"></footer>'
        )

    headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}

    return HTMLResponse(
        content=body,
        status_code=response.status_code,
        headers=headers,
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
# Response helpers
# ---------------------------------------------------------------------------


def htmx_redirect(url: str) -> HTMLResponse:
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = url
    return response


def htmx_refresh() -> HTMLResponse:
    response = HTMLResponse("")
    response.headers["HX-Refresh"] = "true"
    return response


def htmx_trigger(event: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    if data:
        return {event: data}
    return {event: True}


def add_message(request: Request, level: str, text: str) -> None:
    if not hasattr(request.state, "_messages"):
        request.state._messages = []
    request.state._messages.append({"level": level, "text": text})


# ====== SSE Responses ======


async def sse_stream(
    request: Request,
    generator: AsyncGenerator[dict[str, Any] | str, None],
    *,
    event_type: str = "message",
    ping_interval: int = 15,
) -> EventSourceResponse:
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
