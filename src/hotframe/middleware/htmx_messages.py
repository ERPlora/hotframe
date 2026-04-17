"""
HTMX flash messages middleware.

For HTMX requests, flash messages are delivered via the ``HX-Trigger``
response header so the frontend can display toasts without a full page reload.

Usage in views::

    from hotframe.middleware.htmx_messages import add_message

    add_message(request, "success", "Producto creado correctamente")
    add_message(request, "error", "No se pudo guardar")
"""

from __future__ import annotations

import json
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


def add_message(request: Request, level: str, text: str) -> None:
    """
    Add a flash message to the current request.

    Args:
        request: The current request.
        level: Message level (``success``, ``error``, ``warning``, ``info``).
        text: Human-readable message text.
    """
    messages: list[dict[str, str]] = getattr(request.state, "_messages", None) or []
    messages.append({"level": level, "text": text})
    request.state._messages = messages


def get_messages(request: Request) -> list[dict[str, str]]:
    """Retrieve and clear flash messages from the request."""
    messages: list[dict[str, str]] = getattr(request.state, "_messages", None) or []
    request.state._messages = []
    return messages


class HtmxMessagesMiddleware(BaseHTTPMiddleware):
    """Inject flash messages into HX-Trigger header for HTMX requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Initialize message storage
        request.state._messages = []

        response = await call_next(request)

        messages = getattr(request.state, "_messages", None)
        if not messages:
            return response

        # Only inject HX-Trigger for HTMX requests
        htmx_details = getattr(request.state, "htmx", None)
        is_htmx = htmx_details and htmx_details.is_htmx

        if is_htmx:
            # Merge with any existing HX-Trigger header
            existing = response.headers.get("HX-Trigger")
            trigger_data: dict[str, Any] = {}
            if existing:
                try:
                    trigger_data = json.loads(existing)
                except (json.JSONDecodeError, TypeError):
                    # Existing value is a simple event name string
                    trigger_data = {existing: None}

            trigger_data["showMessages"] = messages
            response.headers["HX-Trigger"] = json.dumps(trigger_data)
        else:
            # For non-HTMX requests, store messages in session for next page load
            session: dict[str, Any] | None = getattr(request.state, "session", None)
            if session is not None:
                existing_messages: list[dict[str, str]] = session.get("_flash_messages", [])
                existing_messages.extend(messages)
                session["_flash_messages"] = existing_messages

        return response
