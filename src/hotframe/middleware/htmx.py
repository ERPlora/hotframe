"""
HTMX request detection middleware.

Reads HTMX-specific headers and exposes them on ``request.state.htmx``
as an ``HtmxDetails`` dataclass. Provides a convenience ``is_htmx()`` helper.
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True, slots=True)
class HtmxDetails:
    """Parsed HTMX request headers."""

    is_htmx: bool = False
    target: str | None = None
    trigger: str | None = None
    trigger_name: str | None = None
    boosted: bool = False
    history_restore_request: bool = False
    current_url: str | None = None
    prompt: str | None = None


def is_htmx(request: Request) -> bool:
    """Check if the request is an HTMX request."""
    details: HtmxDetails | None = getattr(request.state, "htmx", None)
    if details is not None:
        return details.is_htmx
    return request.headers.get("HX-Request") == "true"


class HtmxMiddleware(BaseHTTPMiddleware):
    """Parse HTMX headers into ``request.state.htmx``."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        hx_request = request.headers.get("HX-Request", "").lower() == "true"

        request.state.htmx = HtmxDetails(
            is_htmx=hx_request,
            target=request.headers.get("HX-Target"),
            trigger=request.headers.get("HX-Trigger"),
            trigger_name=request.headers.get("HX-Trigger-Name"),
            boosted=request.headers.get("HX-Boosted", "").lower() == "true",
            history_restore_request=request.headers.get("HX-History-Restore-Request", "").lower() == "true",
            current_url=request.headers.get("HX-Current-URL"),
            prompt=request.headers.get("HX-Prompt"),
        )

        return await call_next(request)
