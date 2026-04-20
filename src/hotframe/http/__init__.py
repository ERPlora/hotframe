# SPDX-License-Identifier: Apache-2.0
"""
HTTP subsystem — authenticated, reusable HTTP clients.

A hotframe ``AuthenticatedClient`` wraps ``httpx.AsyncClient`` and
applies an :class:`Auth` strategy on every outgoing request. Clients
are registered by name on ``app.state.http_clients`` so any module,
route, or background task can look them up without re-implementing
authentication, lifecycle, or observability.

See ``docs/HTTP_CLIENTS.md`` for the full design.

Public symbols:

- :class:`AuthenticatedClient` — the client wrapper.
- :class:`HttpClientRegistry` — the per-app registry living on
  ``app.state.http_clients``.
- :class:`Auth` plus the built-in strategies
  (:class:`BearerAuth`, :class:`ApiKeyAuth`, :class:`QueryApiKeyAuth`,
  :class:`BasicAuth`, :class:`HmacAuth`, :class:`CustomAuth`,
  :class:`NoAuth`).
- Event name constants (:data:`EVENT_REQUEST_STARTED`,
  :data:`EVENT_REQUEST_COMPLETED`, :data:`EVENT_REQUEST_FAILED`).
"""

from hotframe.http.auth import (
    ApiKeyAuth,
    Auth,
    BasicAuth,
    BearerAuth,
    CustomAuth,
    HmacAuth,
    NoAuth,
    QueryApiKeyAuth,
)
from hotframe.http.client import AuthenticatedClient
from hotframe.http.events import (
    EVENT_REQUEST_COMPLETED,
    EVENT_REQUEST_FAILED,
    EVENT_REQUEST_STARTED,
)
from hotframe.http.registry import HttpClientRegistry

__all__ = [
    "EVENT_REQUEST_COMPLETED",
    "EVENT_REQUEST_FAILED",
    "EVENT_REQUEST_STARTED",
    "ApiKeyAuth",
    "Auth",
    "AuthenticatedClient",
    "BasicAuth",
    "BearerAuth",
    "CustomAuth",
    "HmacAuth",
    "HttpClientRegistry",
    "NoAuth",
    "QueryApiKeyAuth",
]
