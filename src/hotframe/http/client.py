# SPDX-License-Identifier: Apache-2.0
"""
:class:`AuthenticatedClient` — thin wrapper around ``httpx.AsyncClient``.

The client applies an :class:`~hotframe.http.auth.Auth` strategy to
every outgoing request via an ``httpx`` request event hook, and
optionally emits lifecycle events through a hotframe
:class:`~hotframe.signals.dispatcher.AsyncEventBus`.

All HTTP-facing concerns (connection pooling, timeouts, streaming,
retries, transport selection) are delegated to ``httpx`` — hotframe
does not re-implement any of them.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from hotframe.http.auth import Auth, NoAuth
from hotframe.http.events import (
    EVENT_REQUEST_COMPLETED,
    EVENT_REQUEST_FAILED,
    EVENT_REQUEST_STARTED,
)

if TYPE_CHECKING:
    from hotframe.signals.dispatcher import AsyncEventBus

logger = logging.getLogger(__name__)


class AuthenticatedClient:
    """Async HTTP client that applies an :class:`Auth` strategy per request.

    Wraps ``httpx.AsyncClient``. The auth strategy is wired as an
    ``httpx`` event hook, meaning it runs on the real ``httpx.Request``
    just before dispatch — so any header/query/body changes end up on
    the wire exactly as ``httpx`` would handle its own ``auth=`` hook.

    Args:
        base_url: Base URL prefix applied to relative paths.
        auth: Authentication strategy; defaults to :class:`NoAuth`.
        timeout: Request timeout (seconds or an ``httpx.Timeout``).
        headers: Default headers applied to every request.
        transport: Optional ``httpx.AsyncBaseTransport`` override —
            commonly ``httpx.MockTransport`` in tests.
        event_bus: Optional hotframe event bus used to emit the
            ``http.request.{started,completed,failed}`` events.
        name: Optional client name included in emitted events. Useful
            when the same client instance is shared across modules.
    """

    def __init__(
        self,
        base_url: str = "",
        auth: Auth | None = None,
        timeout: float | httpx.Timeout = 10.0,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        event_bus: AsyncEventBus | None = None,
        name: str | None = None,
    ) -> None:
        self._auth: Auth = auth if auth is not None else NoAuth()
        self._event_bus = event_bus
        self._name = name
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers=headers or {},
            transport=transport,
            event_hooks={"request": [self._apply_auth_hook]},
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def auth(self) -> Auth:
        """Return the currently active :class:`Auth` strategy."""
        return self._auth

    @property
    def name(self) -> str | None:
        """Return the optional client name used in event payloads."""
        return self._name

    @property
    def base_url(self) -> httpx.URL:
        """Return the underlying ``httpx.AsyncClient`` base URL."""
        return self._client.base_url

    @property
    def headers(self) -> httpx.Headers:
        """Return the default headers applied to every request."""
        return self._client.headers

    @property
    def is_closed(self) -> bool:
        """Return ``True`` if the underlying client has been closed."""
        return self._client.is_closed

    # ------------------------------------------------------------------
    # httpx event hook — runs before every request dispatch
    # ------------------------------------------------------------------

    async def _apply_auth_hook(self, request: httpx.Request) -> None:
        """httpx request event hook: apply the current auth strategy."""
        await self._auth.apply(request)

    # ------------------------------------------------------------------
    # HTTP methods — delegated to httpx.AsyncClient with event emission
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        url: httpx.URL | str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Dispatch an HTTP request using the wrapped ``httpx.AsyncClient``.

        Emits ``http.request.started``, ``http.request.completed``, or
        ``http.request.failed`` via the attached event bus when one is
        configured. Credentials are never included in event payloads.
        """
        await self._emit(EVENT_REQUEST_STARTED, method=method, url=str(url))
        started_at = time.perf_counter()
        try:
            response = await self._client.request(method, url, **kwargs)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_at) * 1000.0
            await self._emit(
                EVENT_REQUEST_FAILED,
                method=method,
                url=str(url),
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        await self._emit(
            EVENT_REQUEST_COMPLETED,
            method=method,
            url=str(response.request.url if response.request is not None else url),
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    async def get(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP ``GET`` request."""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP ``POST`` request."""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP ``PUT`` request."""
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP ``PATCH`` request."""
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        """Issue an HTTP ``DELETE`` request."""
        return await self.request("DELETE", url, **kwargs)

    def stream(
        self,
        method: str,
        url: httpx.URL | str,
        **kwargs: Any,
    ) -> Any:
        """Return an ``httpx`` streaming context manager.

        Streaming does not go through :meth:`request`: the auth hook
        still runs (it is wired into the underlying client) but the
        event-bus lifecycle events are skipped because ``httpx``
        manages the stream's completion semantics itself.
        """
        return self._client.stream(method, url, **kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` and its transport."""
        await self._client.aclose()

    async def __aenter__(self) -> AuthenticatedClient:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _emit(self, event_name: str, **payload: Any) -> None:
        """Emit a hotframe event if an ``event_bus`` is attached."""
        if self._event_bus is None:
            return
        try:
            await self._event_bus.emit(
                event_name,
                client_name=self._name,
                **payload,
            )
        except Exception:
            # Event emission must never break an HTTP call. Log and
            # carry on — observability failures are not business logic.
            logger.exception(
                "Failed to emit %s for client %r", event_name, self._name
            )

    def __repr__(self) -> str:
        return (
            f"<AuthenticatedClient name={self._name!r} "
            f"base_url={str(self._client.base_url)!r} "
            f"auth={type(self._auth).__name__}>"
        )


__all__ = ["AuthenticatedClient"]
