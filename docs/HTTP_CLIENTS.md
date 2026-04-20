# Hotframe HTTP Clients

Authenticated, reusable HTTP clients for hotframe projects and modules.

---

## Introduction

An **HTTP client** in hotframe is a long-lived, authenticated `httpx.AsyncClient` registered under a name on `app.state.http_clients`. Any app, module, or route handler can look up a client by name and call third-party services without re-implementing authentication, retries, timeouts, or observability hooks.

Hotframe has HTTP clients because modules frequently integrate with external systems — payments (Stripe), messaging (WhatsApp, Twilio), analytics, fiscal/invoicing APIs, a sibling cloud backend, or object stores — and every integration needs the same plumbing: inject credentials on each request, recompute them when they rotate, close the underlying connection pool on shutdown, and behave predictably in tests. Doing that once in a shared primitive keeps module code focused on business logic.

### HTTP clients vs direct `httpx`

You can always reach for `httpx.AsyncClient()` directly. The point of a registered client is what happens around the request:

| | Direct `httpx.AsyncClient` | Hotframe HTTP client |
|---|---|---|
| Auth header | You inject manually per request | Auth strategy injects on every request |
| Credential rotation | Restart, refactor, or manual refresh | Strategy re-reads source on each call |
| Lifecycle | You `close()` somewhere (or leak) | Registry closes on shutdown / module deactivate |
| Discovery | Hardcoded in each module | `app.state.http_clients["name"]` anywhere |
| Testing | Mock per call site | Swap one registry entry |
| Observability | You wire logging/metrics yourself | Optional hooks emit events via `EventBus` |

If your code calls an external service more than once, wants a named entry point, or needs to rotate credentials without restarts, register a client.

---

## Core concepts

### `AuthenticatedClient`

A thin wrapper around `httpx.AsyncClient`. It accepts an `Auth` strategy and applies it to every outgoing request. It delegates everything else (connection pooling, streaming, timeouts, transport) to `httpx`.

```python
from hotframe.http import AuthenticatedClient, BearerAuth

client = AuthenticatedClient(
    base_url="https://api.stripe.com",
    auth=BearerAuth(lambda: settings.STRIPE_API_KEY),
    timeout=10,
)

resp = await client.get("/v1/customers/cus_123")
```

### `Auth` strategies

An `Auth` strategy knows **how** to authenticate. It is a small class with one method:

```python
class Auth:
    async def apply(self, request: httpx.Request) -> None: ...
```

Hotframe ships the common strategies. You can subclass `Auth` for anything exotic.

| Strategy | Use case | Example |
|---|---|---|
| `BearerAuth(source)` | `Authorization: Bearer <token>` | OpenAI, Stripe, GitHub |
| `ApiKeyAuth(source, header="X-Api-Key")` | Static key in a custom header | WhatsApp Business, SendGrid |
| `QueryApiKeyAuth(source, param="api_key")` | Key in query string | Legacy APIs |
| `BasicAuth(username, password)` | `Authorization: Basic <base64>` | Old SOAP endpoints |
| `HmacAuth(key_id, secret, algorithm="sha256")` | HMAC-signed requests | AWS-style custom APIs |
| `CustomAuth(callable)` | Anything else — async callable receives the request | SigV4, mutual TLS headers, rotating session cookies |
| `NoAuth()` | Explicit unauthenticated | Public endpoints registered for observability |

`source` is either a string or a callable (sync or async) that returns a string. Using a callable means the strategy re-reads the source on every request, so rotating a secret never requires a restart.

### `HttpClientRegistry`

Lives at `app.state.http_clients`. A typed dict-like object with explicit registration, deregistration, and listing.

```python
registry = app.state.http_clients

registry.register("stripe", client)          # raises if "stripe" already exists
registry.replace("stripe", client)           # overwrites silently
client = registry["stripe"]                  # KeyError if absent
maybe = registry.get("stripe")               # None if absent
names = registry.list_registered()
await registry.unregister("stripe")          # closes the client and drops it
```

The registry is created in `create_app()` and closes every client on application shutdown. Modules are expected to unregister their clients when they deactivate.

---

## Lifecycle

### Project-scoped clients

Register in `main.py` during a startup hook. They live for the whole process:

```python
# main.py
from hotframe import create_app
from hotframe.http import AuthenticatedClient, BearerAuth
from settings import settings

app = create_app(settings)

@app.on_event("startup")
async def _register_cloud_client():
    app.state.http_clients.register(
        "cloud",
        AuthenticatedClient(
            base_url=settings.CLOUD_API_URL,
            auth=BearerAuth(lambda: settings.CLOUD_JWT),
        ),
    )
```

### Module-scoped clients

Register in the module's `AppConfig.on_activate` hook and unregister in `on_deactivate`:

```python
# modules/stripe/module.py
from hotframe import ModuleConfig
from hotframe.http import AuthenticatedClient, BearerAuth

class StripeModule(ModuleConfig):
    module_id = "stripe"

    async def on_activate(self, app):
        from settings import settings
        app.state.http_clients.register(
            "stripe",
            AuthenticatedClient(
                base_url="https://api.stripe.com",
                auth=BearerAuth(lambda: settings.STRIPE_API_KEY),
                timeout=10,
            ),
        )

    async def on_deactivate(self, app):
        await app.state.http_clients.unregister("stripe")
```

If the module is uninstalled or deactivated at runtime, its client is closed automatically. If `on_deactivate` is missing, `ModuleRuntime` invokes `registry.unregister_module(module_id)` as a safety net — clients registered through the module's config are tracked and dropped on deactivation even without an explicit hook.

### Shutdown

`create_app()` wires a shutdown handler that calls `aclose()` on every registered client, regardless of who registered it. You do not close clients manually.

---

## Usage from code

From a route handler:

```python
@router.get("/m/stripe/customers/{id}/")
async def get_customer(request: Request, id: str):
    stripe = request.app.state.http_clients["stripe"]
    resp = await stripe.get(f"/v1/customers/{id}")
    resp.raise_for_status()
    return resp.json()
```

From a service class:

```python
class StripeService(ModuleService):
    async def create_customer(self, email: str) -> dict:
        client = self.request.app.state.http_clients["stripe"]
        resp = await client.post("/v1/customers", data={"email": email})
        resp.raise_for_status()
        return resp.json()
```

From background code without a request (e.g. scheduled task):

```python
async def sync_stripe_nightly(app):
    client = app.state.http_clients["stripe"]
    ...
```

---

## Recipes

### Stripe (bearer token)

```python
AuthenticatedClient(
    base_url="https://api.stripe.com",
    auth=BearerAuth(lambda: settings.STRIPE_API_KEY),
)
```

### WhatsApp Cloud API (bearer token, custom version pin)

```python
AuthenticatedClient(
    base_url="https://graph.facebook.com/v21.0",
    auth=BearerAuth(lambda: settings.WHATSAPP_ACCESS_TOKEN),
)
```

### ERPlora Hub → Cloud (JWT in a custom header)

```python
AuthenticatedClient(
    base_url=settings.CLOUD_API_URL,
    auth=ApiKeyAuth(
        source=lambda: settings.HUB_JWT,
        header="X-Hub-Token",
    ),
)
```

The source is a callable. If `HUB_JWT` is rotated (env var updated + process SIGHUPped, or refreshed by a running task), the next request picks up the new value without any client-side changes.

### SigV4 / AWS-style custom API

```python
class SigV4Auth(Auth):
    def __init__(self, access_key, secret_key, service, region):
        ...

    async def apply(self, request):
        request.headers.update(_sign(request, ...))

AuthenticatedClient(
    base_url="https://my-service.example.com",
    auth=SigV4Auth(...),
)
```

### Dynamic refresh with an expiring token

Use `CustomAuth` to fetch a fresh token on demand:

```python
async def fetch_token():
    if _cache.expired():
        _cache.value = await _refresh_from_oauth_server()
    return _cache.value

AuthenticatedClient(
    base_url="https://api.example.com",
    auth=BearerAuth(fetch_token),
)
```

`BearerAuth` accepts async callables. The client awaits the callable on every request.

---

## Testing

Swap the client with a mock:

```python
import httpx
from hotframe.testing import create_test_app

app = create_test_app()

async def mock_stripe(request):
    return httpx.Response(200, json={"id": "cus_test"})

transport = httpx.MockTransport(mock_stripe)
app.state.http_clients.replace(
    "stripe",
    AuthenticatedClient(base_url="https://api.stripe.com", auth=NoAuth(), transport=transport),
)
```

Or bypass the registry entirely in unit tests:

```python
def test_create_customer(monkeypatch):
    fake = AsyncMock()
    fake.post.return_value = httpx.Response(200, json={"id": "cus_test"})
    monkeypatch.setitem(app.state.http_clients, "stripe", fake)
    ...
```

---

## Observability

Every `AuthenticatedClient` emits events via the app's `EventBus` when observability is enabled (`HotframeSettings.HTTP_CLIENT_EVENTS = True`):

- `http.request.started` — `{client_name, method, url}`
- `http.request.completed` — `{client_name, method, url, status, duration_ms}`
- `http.request.failed` — `{client_name, method, url, error}`

Subscribe the same way as any other event:

```python
@events.subscribe("http.request.failed")
async def _log_http_failures(event):
    logger.error("HTTP %s %s failed: %s", event.method, event.url, event.error)
```

Credentials are never emitted in events — only the client name, method, URL, status, and duration.

---

## Design decisions

| Question | Choice | Rationale |
|---|---|---|
| Registry scope | Global (`app.state.http_clients`) with named entries | Lets any module consume any client; namespacing by module creates discoverability friction |
| Auth API | Strategy classes (`BearerAuth`, `ApiKeyAuth`, …) with a `CustomAuth` escape hatch | Typed, testable, documentable; lambdas alone would stay flexible but hide intent |
| Credential source | Callable in the strategy, re-read per request | Rotation without restart; supports env, secrets manager, DB, in-memory cache |
| Lifecycle | Registry closes clients on shutdown; modules register in `on_activate` / `on_deactivate` | Matches the existing `ModuleConfig` hook model; prevents connection leaks |
| Transport | `httpx` under the hood | Async-native, matches hotframe's stack; tests use `httpx.MockTransport` |
| Retries | Not built in | Out of scope; compose with `tenacity` or `httpx_retries` if needed, per client |
| Observability | Opt-in, emits to `EventBus` | Zero cost when disabled; integrates with existing hook points |

---

## Non-goals

- **Circuit breakers, retries, caching.** Compose with existing libraries per client. The registry does not opinionate.
- **Service discovery.** Names are strings decided by the project and modules.
- **Credential storage.** `Auth` strategies consume a source; they do not fetch from secrets managers directly. Read from your settings layer or a cache of your choosing and pass the result in.
- **Per-request auth overrides.** If one call needs different credentials, instantiate a second client or register a second name.

---

## Migration

### From direct `httpx` calls

Before:

```python
async with httpx.AsyncClient(timeout=10) as client:
    resp = await client.get(
        f"{settings.CLOUD_API_URL}/api/v1/hub/device/metrics/",
        headers={"X-Hub-Token": token},
    )
```

After (one-time registration in `main.py`):

```python
app.state.http_clients.register(
    "cloud",
    AuthenticatedClient(
        base_url=settings.CLOUD_API_URL,
        auth=ApiKeyAuth(source=lambda: settings.HUB_JWT, header="X-Hub-Token"),
        timeout=10,
    ),
)
```

Call sites:

```python
cloud = request.app.state.http_clients["cloud"]
resp = await cloud.get("/api/v1/hub/device/metrics/")
```

### From ad-hoc module clients

If a module currently wires its own `httpx` calls, move them to `on_activate` and `on_deactivate`, register under the module's conventional name (`"stripe"`, `"whatsapp"`, …), and update call sites to look up by name.

---

## Reference

### `AuthenticatedClient`

```python
AuthenticatedClient(
    base_url: str = "",
    auth: Auth = NoAuth(),
    timeout: float | httpx.Timeout = 10,
    headers: dict[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    event_bus: AsyncEventBus | None = None,
    name: str | None = None,
)
```

Proxies `get`, `post`, `put`, `patch`, `delete`, `request`, `stream` from `httpx.AsyncClient`. `aclose()` closes the underlying transport.

### `HttpClientRegistry`

```python
registry.register(name: str, client: AuthenticatedClient) -> None
registry.replace(name: str, client: AuthenticatedClient) -> None
registry.get(name: str) -> AuthenticatedClient | None
registry[name: str] -> AuthenticatedClient  # __getitem__; raises KeyError
registry.unregister(name: str) -> None  # closes the client
registry.unregister_module(module_id: str) -> None  # drops all clients a module registered
registry.list_registered() -> list[str]
await registry.aclose_all()  # called by framework on shutdown
```

### Built-in `Auth` strategies

```python
BearerAuth(source: str | Callable[[], str | Awaitable[str]])
ApiKeyAuth(source: ..., header: str = "X-Api-Key")
QueryApiKeyAuth(source: ..., param: str = "api_key")
BasicAuth(username: str, password: str)
HmacAuth(key_id: str, secret: str, algorithm: str = "sha256")
CustomAuth(apply: Callable[[httpx.Request], Awaitable[None]])
NoAuth()
```
