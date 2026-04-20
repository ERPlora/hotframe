# HTTP Interceptors

Angular-style request/response middleware for `AuthenticatedClient`.

> Available since **hotframe 0.0.9**.

---

## Introduction

An **interceptor** wraps the dispatch of a single outgoing HTTP request made through an [`AuthenticatedClient`](HTTP_CLIENTS.md). It can:

- inspect or mutate the outgoing `httpx.Request` before it hits the wire,
- inspect or transform the incoming `httpx.Response` before it is returned to the caller,
- short-circuit the call (circuit breaker open, cache hit),
- retry the call (transient 5xx, token refresh on 401) by awaiting `call_next` more than once,
- emit telemetry, apply rate limits, tag requests with correlation IDs, or do anything else that belongs *around* a request.

The design mirrors Angular's `HttpInterceptor`: a chain of independent, composable units, each of which receives the request and a `call_next` callable that advances the chain. The innermost link — the **terminal** — is the actual wire dispatch through `httpx`.

The framework only defines the primitive. Concrete behavior (retry, circuit breaker, refresh) is shipped as ready-to-use classes you can register directly, subclass, or replace with your own.

---

## The `Interceptor` protocol

```python
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

import httpx

CallNext = Callable[[httpx.Request], Awaitable[httpx.Response]]


@runtime_checkable
class Interceptor(Protocol):
    name: str
    applies_to: str | list[str] | Callable[[str], bool]
    order: int

    async def intercept(
        self,
        request: httpx.Request,
        call_next: CallNext,
    ) -> httpx.Response:
        ...
```

| Attribute | Purpose |
|---|---|
| `name` | Unique identifier used for discovery, logging, and deduplication. |
| `applies_to` | Client-name matcher. Either a specific name (`"cloud"`), a list (`["cloud", "stripe"]`), the wildcard `"*"`, or a callable `(name: str) -> bool`. |
| `order` | Ordering hint. **Lower values run further out** in the chain (their body executes earlier on the way down, later on the way up). |
| `intercept` | The wrapper body. Must eventually `await call_next(request)` unless it is deliberately short-circuiting. |

### `InterceptorBase` (optional)

A convenience base class that supplies:

- `order = 100` default,
- a resolved `applies_to_client(client_name)` matcher,
- a pass-through `intercept` that just forwards to `call_next`.

Inheriting from it is not required — any object that satisfies the protocol works.

```python
from hotframe.http import InterceptorBase

class LoggingInterceptor(InterceptorBase):
    name = "logging"
    applies_to = "*"
    order = 50  # run outside retries so each attempt is logged

    async def intercept(self, request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method, request.url, response.status_code, elapsed_ms,
        )
        return response
```

---

## Built-in interceptors

All importable from `hotframe.http`.

### `RetryInterceptor`

Retries the underlying call on transient failures (5xx, `httpx.RequestError`) with configurable back-off.

```python
from hotframe.http import RetryInterceptor, exponential_backoff

retry = RetryInterceptor(
    name="cloud-retry",
    applies_to="cloud",
    max_attempts=3,
    backoff=exponential_backoff(base=0.5, cap=5.0),
    retry_on_status={502, 503, 504},
    order=200,
)
```

| Parameter | Type | Meaning |
|---|---|---|
| `max_attempts` | `int` | Total attempts including the first one. |
| `backoff` | `Callable[[int], float]` | Receives the 1-based attempt number, returns seconds to sleep before the next try. |
| `retry_on_status` | `set[int]` | HTTP codes that trigger a retry. |
| `retry_on_exceptions` | `tuple[type[Exception], ...]` | Exception types that trigger a retry (defaults to `(httpx.RequestError,)`). |

`exponential_backoff(base, cap)` is a helper that returns a callable producing `min(cap, base * 2**(attempt - 1))`.

### `CircuitBreakerInterceptor`

Trips open after a streak of failures and short-circuits subsequent calls for a recovery window. After the window, a single probing request is allowed through; success closes the circuit, failure re-opens it.

```python
from hotframe.http import CircuitBreakerInterceptor

circuit = CircuitBreakerInterceptor(
    name="cloud-circuit",
    applies_to="cloud",
    failure_threshold=5,
    recovery_timeout=60.0,   # seconds
    order=100,               # outermost — cheap short-circuit before anything else
)
```

When the circuit is open, the interceptor raises `httpx.HTTPError("circuit open")` (or a subclass) without invoking `call_next`. Callers see the failure as a normal transport error.

### `RefreshInterceptor`

On a configured "auth expired" status (default `401`), calls a user-supplied async refresh function, updates the credential source, and replays the original request exactly once.

```python
from hotframe.http import RefreshInterceptor

async def refresh_cloud_jwt() -> None:
    """Fetch a new access token and persist it so the Auth strategy re-reads it."""
    ...

refresh = RefreshInterceptor(
    name="cloud-refresh",
    applies_to="cloud",
    refresh=refresh_cloud_jwt,
    refresh_on_status={401},
    order=150,
)
```

`RefreshInterceptor` guards concurrent refreshes with an internal lock so a burst of 401s results in **one** refresh call, not N. After the refresh returns, every waiting request retries with the new credential.

---

## Execution order

`build_chain(interceptors, terminal)` sorts interceptors by `order` **ascending** and composes them so that **lower `order` wraps higher `order`**. The lowest-order interceptor's `intercept` body executes first on the way down and last on the way up.

```
request
  │
  ▼
┌─────────────────────────────┐  order=100
│  CircuitBreakerInterceptor  │
│  ┌─────────────────────────┐│  order=150
│  │   RefreshInterceptor    ││
│  │  ┌────────────────────┐ ││  order=200
│  │  │  RetryInterceptor  │ ││
│  │  │  ┌──────────────┐  │ ││
│  │  │  │   terminal   │  │ ││  httpx.AsyncClient.send
│  │  │  └──────────────┘  │ ││
│  │  └────────────────────┘ ││
│  └─────────────────────────┘│
└─────────────────────────────┘
  │
  ▼
response
```

Why this order for an authenticated backend like Cloud:

- **Circuit (100)** sits outermost so a tripped breaker short-circuits before doing any auth work or retries — cheap and fast when the remote is down.
- **Refresh (150)** sits between circuit and retry so a single 401 triggers exactly one refresh attempt, and that refreshed attempt can still be retried by the retry layer if it transient-fails afterward.
- **Retry (200)** sits innermost so every attempt (including post-refresh) passes through it; retries don't bypass the circuit breaker.

---

## Automatic discovery

Interceptors are discovered and registered at app startup with `discover_interceptors(paths)`:

```python
from hotframe.http import discover_interceptors

interceptors = discover_interceptors([
    "apps/shared/interceptors",   # project-scoped
    "modules/*/interceptors.py",  # module-scoped (one file per module)
])
```

Conventions:

- **`apps/shared/interceptors/*.py`** — project-shipped interceptors. One file per feature (`cloud.py`, `logging.py`, `stripe.py`).
- **`modules/<id>/interceptors.py`** — module-shipped interceptors. Discovered when the module is mounted, unregistered on deactivation.

Each discovered module is scanned for top-level **instances** that satisfy the `Interceptor` protocol. A convention is to export them in a module-level list:

```python
# apps/shared/interceptors/cloud.py
from hotframe.http import (
    CircuitBreakerInterceptor,
    RefreshInterceptor,
    RetryInterceptor,
    exponential_backoff,
)

from apps.shared.http.refresh import refresh_cloud_jwt

CLOUD_INTERCEPTORS = [
    CircuitBreakerInterceptor(
        name="cloud-circuit",
        applies_to="cloud",
        failure_threshold=5,
        recovery_timeout=60.0,
        order=100,
    ),
    RefreshInterceptor(
        name="cloud-refresh",
        applies_to="cloud",
        refresh=refresh_cloud_jwt,
        order=150,
    ),
    RetryInterceptor(
        name="cloud-retry",
        applies_to="cloud",
        max_attempts=3,
        backoff=exponential_backoff(base=0.5, cap=5.0),
        order=200,
    ),
]
```

`discover_interceptors` returns a flat list. The framework applies each interceptor to every registered client whose name matches `applies_to`.

Names are unique: registering two interceptors with the same `name` raises at startup. This prevents accidental duplicates when a module is reloaded.

---

## Client-name matching

The `applies_to` attribute decides which registered clients a given interceptor wraps.

| Shape | Semantics |
|---|---|
| `"*"` | Match every registered client. |
| `"cloud"` | Exact match for the client registered as `"cloud"`. |
| `["cloud", "stripe"]` | Match any name in the list. |
| `lambda name: name.startswith("internal-")` | Delegated decision; receives the client name. |

Interceptors that live inside a module are typically scoped with `applies_to` equal to the module's own client name, so they do not accidentally wrap shared clients registered by other modules.

---

## Writing a custom interceptor

Any object satisfying the protocol works. For example, a minimal rate-limit interceptor that enforces a local token bucket before each request:

```python
import asyncio
import time

from hotframe.http import InterceptorBase


class RateLimitInterceptor(InterceptorBase):
    """Local token bucket: `rate` requests per second, burst `burst`."""

    def __init__(
        self,
        *,
        name: str,
        applies_to: str | list[str],
        rate: float,
        burst: int,
        order: int = 80,
    ) -> None:
        self.name = name
        self.applies_to = applies_to
        self.order = order
        self._rate = rate
        self._tokens = float(burst)
        self._burst = burst
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def intercept(self, request, call_next):
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(
                self._burst,
                self._tokens + (now - self._last) * self._rate,
            )
            self._last = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0
        return await call_next(request)
```

Register it in `apps/shared/interceptors/rate_limit.py` so `discover_interceptors` picks it up automatically.

### Short-circuiting

An interceptor that returns a response without calling `call_next` short-circuits the chain. Use this for cache hits, circuit breakers in the "open" state, or synthetic responses in tests:

```python
class CacheInterceptor(InterceptorBase):
    name = "cache"
    applies_to = "cloud"
    order = 60

    async def intercept(self, request, call_next):
        if request.method == "GET":
            cached = await self._lookup(request.url)
            if cached is not None:
                return cached
        response = await call_next(request)
        if request.method == "GET" and response.status_code == 200:
            await self._store(request.url, response)
        return response
```

### Replaying

Retries and refreshes replay by calling `call_next` more than once. Each call must pass the same (or a freshly built) `httpx.Request`; `httpx` is fine with multiple sends of the same request object as long as the body has not been streamed.

```python
async def intercept(self, request, call_next):
    response = await call_next(request)
    if response.status_code in self._retry_statuses:
        await asyncio.sleep(self._backoff(1))
        response = await call_next(request)
    return response
```

---

## End-to-end example

```python
# main.py
from hotframe import create_app
from hotframe.http import (
    ApiKeyAuth,
    AuthenticatedClient,
    discover_interceptors,
)
from settings import settings

app = create_app(settings)


@app.on_event("startup")
async def _wire_cloud():
    # 1. Register the client
    client = AuthenticatedClient(
        base_url=settings.CLOUD_API_URL,
        auth=ApiKeyAuth(
            source=lambda: settings.HUB_JWT or "",
            header="X-Hub-Token",
        ),
        timeout=10,
        name="cloud",
    )
    app.state.http_clients.register("cloud", client)

    # 2. Discover and attach interceptors
    interceptors = discover_interceptors([
        "apps/shared/interceptors",
        "modules/*/interceptors.py",
    ])
    for interceptor in interceptors:
        app.state.http_clients.attach_interceptor(interceptor)
```

From a route:

```python
@router.get("/dashboard")
async def dashboard(request: Request):
    cloud = request.app.state.http_clients["cloud"]
    resp = await cloud.get("/api/v1/compliance/")
    resp.raise_for_status()
    return {"items": resp.json()}
```

A single `cloud.get(...)` now flows through circuit → refresh → retry → wire, driven entirely by declared interceptors. The call site is unchanged.

---

## Testing

Interceptors are plain async callables with an `intercept(request, call_next)` signature, so they are trivial to exercise in isolation. You do not need a running app or a real network.

### Unit test with a fake `call_next`

```python
import httpx
import pytest

from hotframe.http import RetryInterceptor, exponential_backoff


@pytest.mark.asyncio
async def test_retry_interceptor_retries_on_503():
    calls = 0

    async def call_next(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request)

    interceptor = RetryInterceptor(
        name="t",
        applies_to="*",
        max_attempts=3,
        backoff=lambda attempt: 0.0,  # no sleep in tests
        retry_on_status={503},
    )

    request = httpx.Request("GET", "https://example.com/")
    response = await interceptor.intercept(request, call_next)

    assert response.status_code == 200
    assert calls == 3
```

### Integration test with a mock transport

Wire the full chain on an `AuthenticatedClient` backed by `httpx.MockTransport`:

```python
import httpx

from hotframe.http import (
    AuthenticatedClient,
    CircuitBreakerInterceptor,
    NoAuth,
    RetryInterceptor,
    build_chain,
)


async def test_full_chain(monkeypatch):
    hits = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal hits
        hits += 1
        return httpx.Response(500 if hits < 2 else 200, request=request)

    transport = httpx.MockTransport(handler)
    client = AuthenticatedClient(base_url="https://example.com", auth=NoAuth(), transport=transport)

    # Chain by hand (or via app.state.http_clients.attach_interceptor in production)
    interceptors = [
        CircuitBreakerInterceptor(name="c", applies_to="*", failure_threshold=5, recovery_timeout=10, order=100),
        RetryInterceptor(name="r", applies_to="*", max_attempts=3, backoff=lambda a: 0.0, retry_on_status={500}, order=200),
    ]
    client.set_interceptors(interceptors)

    resp = await client.get("/ping")
    assert resp.status_code == 200
    assert hits == 2
```

### Asserting short-circuits

For interceptors that short-circuit (cache hits, open breakers), assert `call_next` was never awaited:

```python
called = False

async def call_next(request):
    nonlocal called
    called = True
    return httpx.Response(200, request=request)

# ... exercise the interceptor in its short-circuit state ...

assert called is False
```

---

## Design notes

- **Order is global, not per-client.** The chain is rebuilt per client at registration time using the subset of interceptors whose `applies_to` matches the client name. Two clients can end up with different chains even though the interceptor pool is shared.
- **Interceptors are instances, not classes.** `discover_interceptors` registers instances so they can carry per-deployment tuning (thresholds, backoffs, refresh callbacks) without subclassing.
- **No hidden state on the client.** Interceptors attach to a client via an explicit registry call; clients used in isolation (direct `AuthenticatedClient(...)` without a registry) are unwrapped by default.
- **Credentials never flow through interceptor events.** If you emit telemetry from an interceptor, include only method, URL, status, duration, and the interceptor `name`.

---

## See also

- [HTTP clients](HTTP_CLIENTS.md) — `AuthenticatedClient`, `Auth` strategies, registry, lifecycle.
- [Architecture](ARCHITECTURE.md) — where the HTTP subsystem fits in the bootstrap.
