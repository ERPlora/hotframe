"""
Request ID middleware with observability context binding.

Generates or reads a unique request ID (``X-Request-ID`` header) for every
request.  The ID is stored on ``request.state.request_id`` and echoed back
in the response headers.

Also binds request-scoped context (request_id, hub_id, user_id) into the
observability context (contextvars) so that all downstream logging, tracing,
and metrics automatically include these identifiers.

In production, the ALB/CloudFront may inject the header; if present we reuse
it, otherwise we generate a new one.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from hotframe.utils.observability_context import bind_context, update_context
from hotframe.utils.observability_metrics import get_request_duration_histogram

HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID and bind observability context per request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Reuse upstream ID or generate a new one
        request_id = request.headers.get(HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        # Extract hub_id and user_id if available from request state
        # (set by session/auth middleware that runs after us — we update later)
        hub_id = str(getattr(request.state, "hub_id", "") or "")
        user_id = str(getattr(request.state, "user_id", "") or "")

        with bind_context(request_id=request_id, hub_id=hub_id, user_id=user_id):
            start = time.perf_counter()
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start) * 1000

            # Record request duration metric
            route = request.scope.get("path", request.url.path)
            get_request_duration_histogram().record(
                duration_ms,
                attributes={
                    "http.method": request.method,
                    "http.route": route,
                    "http.status_code": response.status_code,
                },
            )

        response.headers[HEADER] = request_id
        return response


def bind_user_context(user_id: str, hub_id: str = "") -> None:
    """
    Update observability context with user/hub info after authentication.

    Called from auth dependencies or session middleware once the user is known.
    """
    kwargs: dict[str, str] = {}
    if user_id:
        kwargs["user_id"] = user_id
    if hub_id:
        kwargs["hub_id"] = hub_id
    if kwargs:
        update_context(**kwargs)
