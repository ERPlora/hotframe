# http.md — Authenticated HTTP clients + Angular-style interceptors

> **Carpeta cubierta:** `src/hotframe/http/`. Ocho archivos:
> `__init__.py`, `auth.py`, `interceptors.py`, `builtin_interceptors.py`,
> `client.py`, `registry.py`, `loader.py`, `events.py`.
> Subsistema para hablar con APIs externas (Stripe, marketplace,
> integraciones de partners) con autenticación, retries, circuit
> breakers y refresh de tokens — todo declarativo y reutilizable.

---

## 1. ¿Qué problema resuelve?

Antes había código de este tipo esparcido por los módulos:

```python
client = httpx.AsyncClient()
try:
    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 401:
        token = await refresh_token()
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code == 503:
        await asyncio.sleep(1)
        resp = await client.get(url, ...)
    # ... handling errors ...
finally:
    await client.aclose()
```

Cada módulo reimplementaba auth, retry, refresh. `hotframe.http`
empaqueta todo eso en piezas componibles:

```python
# settings.py
HTTP_INTERCEPTOR_PATHS = ["./apps/integrations/interceptors"]

# apps/integrations/interceptors/stripe.py
from hotframe.http import RetryInterceptor, exponential_backoff
stripe_retry = RetryInterceptor(
    max_attempts=3, retry_on_status={502, 503, 504},
    delay=exponential_backoff(base=0.5, max=8),
    applies_to="stripe",
)

# en código de módulo
client = await app.state.http_clients.get("stripe")
resp = await client.get("/charges/123")   # auth + retry + refresh aplicado
```

---

## 2. `__init__.py` — fachada

Reexporta los símbolos públicos:

- `Auth`, `BearerAuth`, `ApiKeyAuth`, `QueryApiKeyAuth`, `BasicAuth`,
  `HmacAuth`, `CustomAuth`, `NoAuth`
- `AuthenticatedClient`
- `HttpClientRegistry`
- `Interceptor`, `InterceptorBase`, `CallNext` (alias type)
- `RetryInterceptor`, `CircuitBreakerInterceptor`, `RefreshInterceptor`,
  `exponential_backoff`
- `discover_interceptors`
- Constantes de evento: `EVENT_REQUEST_STARTED`, `EVENT_REQUEST_COMPLETED`,
  `EVENT_REQUEST_FAILED`

Toda la API se importa también desde `hotframe` raíz (lazy).

---

## 3. `auth.py` — estrategias de autenticación

### 3.1 Protocolo `Auth`

```python
class Auth(Protocol):
    async def apply(self, request: httpx.Request) -> httpx.Request: ...
```

Cada estrategia muta el `Request` (añade `Authorization`,
`X-API-Key`, etc.) antes de enviarlo.

### 3.2 Implementaciones built-in

| Clase | Cómo aplica |
|---|---|
| `BearerAuth(token)` | `Authorization: Bearer {token}` |
| `ApiKeyAuth(key, header="X-API-Key")` | header personalizable |
| `QueryApiKeyAuth(key, param="api_key")` | añade param a la URL |
| `BasicAuth(username, password)` | `Authorization: Basic {b64}` |
| `HmacAuth(secret, header="X-Signature", algo="sha256")` | firma body+timestamp |
| `CustomAuth(callable)` | callable async que muta el request |
| `NoAuth()` | passthrough — útil para clients sin auth |

### 3.3 `BearerAuth` con token dinámico

Para tokens que rotan:

```python
class _DynamicBearer(Auth):
    def __init__(self, token_provider):
        self.provider = token_provider  # async () -> str
    async def apply(self, request):
        token = await self.provider()
        request.headers["Authorization"] = f"Bearer {token}"
        return request
```

`BearerAuth` acepta `token: str` (estático) o `Callable` (dinámico).
La implementación detecta el caso.

### 3.4 `HmacAuth`

Firma `body + timestamp` con HMAC-SHA256. Útil para webhooks
salientes a partners que verifican firmas (Stripe-style).

```python
sig = hmac.new(secret.encode(), body + timestamp, hashlib.sha256).hexdigest()
request.headers["X-Signature"] = sig
request.headers["X-Timestamp"] = timestamp
```

---

## 4. `interceptors.py` — protocolo + base

### 4.1 `CallNext` y `Interceptor`

```python
CallNext = Callable[[httpx.Request], Awaitable[httpx.Response]]

class Interceptor(Protocol):
    name: str
    async def intercept(self, request: httpx.Request, call_next: CallNext) -> httpx.Response: ...
    def applies_to(self, client_name: str) -> bool: ...
```

Patrón Angular: cada interceptor recibe el request y un `call_next`
que invoca al siguiente interceptor (o al transport). Puedes:

- **Modificar request antes** de `call_next`.
- **Modificar response después** de `call_next`.
- **Reintentar** llamando `call_next` múltiples veces.
- **Cortocircuitar** retornando una response sintética sin llamar `call_next`.

### 4.2 `InterceptorBase`

Helper para implementaciones concretas:

```python
class InterceptorBase:
    def __init__(self, *, name=None, applies_to=None):
        self.name = name or self.__class__.__name__
        self._applies_to = applies_to  # str, list[str], pattern, callable

    def applies_to(self, client_name):
        if self._applies_to is None:
            return True
        if isinstance(self._applies_to, str):
            return fnmatch(client_name, self._applies_to)
        if callable(self._applies_to):
            return self._applies_to(client_name)
        if isinstance(self._applies_to, (list, tuple)):
            return any(fnmatch(client_name, p) for p in self._applies_to)
        return False
```

`applies_to` admite:
- `None` → todos los clients
- `"stripe"` → match exacto
- `"stripe*"` → fnmatch glob
- `["stripe", "twilio"]` → cualquiera de la lista
- `lambda name: name.startswith("payment_")` → callable

---

## 5. `builtin_interceptors.py` — interceptors listos

### 5.1 `RetryInterceptor`

```python
class RetryInterceptor(InterceptorBase):
    def __init__(self, *, max_attempts=3, retry_on_status=(502, 503, 504),
                 retry_on_methods=("GET", "HEAD", "PUT", "DELETE"),
                 delay=lambda n: 1.0, **kwargs):
        ...
    async def intercept(self, request, call_next):
        for attempt in range(self.max_attempts):
            try:
                resp = await call_next(request)
                if resp.status_code not in self.retry_on_status:
                    return resp
                if request.method not in self.retry_on_methods:
                    return resp
            except (httpx.NetworkError, httpx.TimeoutException):
                if attempt == self.max_attempts - 1:
                    raise
            await asyncio.sleep(self.delay(attempt))
        return resp
```

Decisiones:

- **Retry solo en métodos idempotentes** por default. POST no se
  retry porque podría crear un duplicado.
- **`delay(n)` callable** — permite exponential backoff, jitter, etc.
- **Network errors también** se retry — más robustos que solo HTTP.

### 5.2 `exponential_backoff(base, max)`

```python
def exponential_backoff(base=1.0, max=60.0, jitter=True):
    def delay(attempt):
        d = min(max, base * (2 ** attempt))
        if jitter:
            d *= random.uniform(0.5, 1.5)
        return d
    return delay
```

Útil con `RetryInterceptor(delay=exponential_backoff(0.5, 8))`.

### 5.3 `CircuitBreakerInterceptor`

```python
class CircuitBreakerInterceptor(InterceptorBase):
    def __init__(self, *, failure_threshold=5, recovery_timeout=60.0, **kwargs):
        self._state = "closed"  # closed, open, half_open
        self._failures = 0
        self._opened_at = 0
        ...
    async def intercept(self, request, call_next):
        if self._state == "open":
            if time.time() - self._opened_at > self.recovery_timeout:
                self._state = "half_open"
            else:
                raise CircuitOpenError(f"Circuit breaker open for {self.name}")
        try:
            resp = await call_next(request)
            if 200 <= resp.status_code < 500:
                self._on_success()
            else:
                self._on_failure()
            return resp
        except Exception:
            self._on_failure()
            raise
```

Estados:
- **closed**: requests pasan. Si N fallos consecutivos → open.
- **open**: requests rechazadas instantáneamente con `CircuitOpenError`.
  Tras `recovery_timeout` → half_open.
- **half_open**: el siguiente request se intenta. Éxito → closed.
  Fallo → open de nuevo.

### 5.4 `RefreshInterceptor`

Para APIs OAuth donde el access token expira:

```python
class RefreshInterceptor(InterceptorBase):
    def __init__(self, *, on_refresh, refresh_status_codes=(401,), **kwargs):
        self.on_refresh = on_refresh  # async () -> None (rotates auth)
        ...
    async def intercept(self, request, call_next):
        resp = await call_next(request)
        if resp.status_code in self.refresh_status_codes:
            await self.on_refresh()    # rotates the auth strategy
            resp = await call_next(request)  # one retry with fresh token
        return resp
```

Decisión clave: **un solo retry**. Si el refresh tampoco arregla,
falla — no reintenta indefinidamente.

`on_refresh` típicamente actualiza el `BearerAuth.token` global o el
provider:

```python
async def refresh_stripe():
    new_token = await fetch_new_oauth_token()
    stripe_auth.token = new_token

refresh = RefreshInterceptor(on_refresh=refresh_stripe, applies_to="stripe")
```

---

## 6. `client.py` — `AuthenticatedClient`

Wrapper de `httpx.AsyncClient`:

```python
class AuthenticatedClient:
    def __init__(self, base_url, auth, *,
                 interceptors=(), event_bus=None, name="anonymous", **kwargs):
        self._client = httpx.AsyncClient(base_url=base_url, **kwargs)
        self._auth = auth
        self._interceptors = list(interceptors)
        self._bus = event_bus
        self.name = name

    async def request(self, method, url, **kwargs) -> httpx.Response:
        request = self._client.build_request(method, url, **kwargs)
        request = await self._auth.apply(request)

        async def transport(req):
            return await self._client.send(req)

        # Build the chain in reverse — last interceptor wraps the transport
        call_next = transport
        for interceptor in reversed(self._interceptors):
            outer = interceptor
            inner = call_next
            call_next = lambda req, _outer=outer, _inner=inner: _outer.intercept(req, _inner)

        if self._bus:
            await self._bus.emit(EVENT_REQUEST_STARTED, sender=self,
                                 method=method, url=url, client_name=self.name)
        try:
            resp = await call_next(request)
        except Exception as e:
            if self._bus:
                await self._bus.emit(EVENT_REQUEST_FAILED, sender=self,
                                     method=method, url=url, client_name=self.name,
                                     error=str(e))
            raise
        if self._bus:
            await self._bus.emit(EVENT_REQUEST_COMPLETED, sender=self,
                                 method=method, url=url, client_name=self.name,
                                 status_code=resp.status_code)
        return resp

    async def get(self, url, **kw): return await self.request("GET", url, **kw)
    async def post(self, url, **kw): return await self.request("POST", url, **kw)
    # ... put, patch, delete ...
    async def aclose(self): await self._client.aclose()
```

Decisiones:

1. **El auth se aplica una vez por request**, antes de los
   interceptors. Si un interceptor modifica el request (e.g. añade
   un header), respeta lo que ya escribió `auth`.
2. **La cadena se construye en reverse** — `interceptors[0]` es el
   más externo, `interceptors[-1]` envuelve el transport.
3. **Eventos en el `EventBus`** son opcionales. Se emiten solo si
   `event_bus` está conectado al constructor.
4. **El status_code en `EVENT_REQUEST_COMPLETED`** permite a un
   listener detectar fallos sin tener que parsear el evento failed.

---

## 7. `registry.py` — `HttpClientRegistry`

Catalogo per-app vivo en `app.state.http_clients`:

```python
class HttpClientRegistry:
    def __init__(self, *, ambient_interceptors=()):
        self._clients: dict[str, AuthenticatedClient] = {}
        self._ambient = list(ambient_interceptors)

    def register(self, name, client_or_factory, *, interceptors=None):
        if interceptors is None:
            # Auto-apply ambient interceptors that match by name
            interceptors = [i for i in self._ambient if i.applies_to(name)]
        if callable(client_or_factory) and not isinstance(client_or_factory, AuthenticatedClient):
            # Factory pattern — instantiate now with interceptors injected
            client = client_or_factory(interceptors=interceptors)
        else:
            # Direct instance — wrap with interceptors
            client = client_or_factory
            client._interceptors.extend(interceptors)
        self._clients[name] = client

    async def get(self, name) -> AuthenticatedClient:
        if name not in self._clients:
            raise KeyError(f"No HTTP client registered as {name!r}")
        return self._clients[name]

    async def aclose_all(self):
        for client in self._clients.values():
            try:
                await client.aclose()
            except Exception:
                logger.exception("...")
        self._clients.clear()
```

Decisiones:

1. **Ambient interceptors auto-applied**. Si un interceptor declara
   `applies_to="stripe"`, todos los clients registrados como
   `"stripe*"` lo reciben sin escribirlo manualmente.
2. **Factory vs instance.** Pasar `client_or_factory=lambda i: AuthenticatedClient(...)` permite
   construir clients on-demand con interceptors inyectados.
3. **`aclose_all()` en shutdown** — bootstrap lo llama al apagar.

---

## 8. `loader.py` — `discover_interceptors(paths)`

Escanea directorios para autocargar interceptors:

```python
def discover_interceptors(paths: list[Path]) -> list[Interceptor]:
    discovered = []
    for path in paths:
        if not path.exists():
            continue
        for py in path.rglob("*.py"):
            if py.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(
                f"_hotframe_interceptors.{py.stem}", py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr_name in dir(module):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(module, attr_name)
                if _is_interceptor(attr):
                    discovered.append(attr)
    return discovered

def _is_interceptor(obj):
    return hasattr(obj, "intercept") and hasattr(obj, "applies_to") and hasattr(obj, "name")
```

Discovery solo recoge **instancias module-level**, no clases. Patrón
recomendado:

```python
# apps/integrations/interceptors/stripe.py
from hotframe.http import RetryInterceptor, exponential_backoff

stripe_retry = RetryInterceptor(  # ← instancia, no clase
    max_attempts=3,
    delay=exponential_backoff(0.5, 8),
    applies_to="stripe*",
)
```

`bootstrap.lifespan` llama `discover_interceptors(paths)` con
`HTTP_INTERCEPTOR_PATHS` y los pasa al `HttpClientRegistry` como
`ambient_interceptors`.

---

## 9. `events.py` — constantes

```python
EVENT_REQUEST_STARTED = "http.request.started"
EVENT_REQUEST_COMPLETED = "http.request.completed"
EVENT_REQUEST_FAILED = "http.request.failed"
```

Cada evento del bus lleva: `method`, `url`, `client_name`, `status_code`
(en completed), `error` (en failed). Listeners pueden hacer
métricas, logs estructurados, alerting.

`HTTP_CLIENT_EVENTS=False` por defecto — los eventos se emiten solo
si lo activas explícitamente, para no pagar overhead en clients que
no los necesitan.

---

## 10. Cómo se enchufa todo

```
┌─────────────────────────────────────────────────────────────────┐
│ settings.HTTP_INTERCEPTOR_PATHS = ["./apps/integrations/i18ns"] │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ bootstrap.lifespan:                                              │
│   discovered = discover_interceptors(paths)                      │
│   app.state.http_clients = HttpClientRegistry(                   │
│       ambient_interceptors=discovered)                           │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Module code at install time:                                     │
│   registry.register("stripe", AuthenticatedClient(               │
│       base_url="https://api.stripe.com",                         │
│       auth=BearerAuth(api_key)))                                 │
│   # Ambient interceptors with applies_to="stripe*" auto-applied  │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Handler:                                                         │
│   client = await app.state.http_clients.get("stripe")            │
│   resp = await client.post("/charges", json={...})               │
│   # auth + retry + refresh + circuit breaker + events            │
└─────────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Shutdown:                                                        │
│   await app.state.http_clients.aclose_all()                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 11. Decisiones de diseño que conviene recordar

1. **Auth es estrategia, no estado.** `BearerAuth(token=...)` puede
   ser estático o callable. Refresh rota el token, no reemplaza la
   instancia.
2. **Interceptors usan duck-typing.** Cualquier objeto con
   `intercept`, `applies_to`, `name` cumple. No tienes que heredar
   de `InterceptorBase`.
3. **Ambient interceptors auto-aplican.** Configura una vez en
   `HTTP_INTERCEPTOR_PATHS`, registra clients donde sea, los
   interceptors aplican automáticamente.
4. **Retry solo en métodos idempotentes** por default. Si necesitas
   retry de POST, sé explícito.
5. **`RefreshInterceptor` hace UN retry.** No bucle infinito.
6. **Circuit breaker es local al interceptor.** Si tienes múltiples
   workers uvicorn, cada uno tiene su propio estado. Esto es
   intencional — sincronizar requeriría Redis y complicaría
   operaciones.
7. **Eventos opcionales.** `HTTP_CLIENT_EVENTS=False` skipea las
   emisiones por completo.
8. **Discovery solo a instancias module-level.** Permite que el
   developer instancie con la configuración completa antes del boot.

---

## 12. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `KeyError: No HTTP client registered as 'X'` | Olvidaste `register("X", ...)` o se hizo en lifespan después de la primera request. | Registra en `lifespan` antes del yield. |
| `CircuitOpenError` continuo | Threshold demasiado bajo o el endpoint sigue caído. | Sube `failure_threshold` o investiga el endpoint. |
| Retry de POST duplica una creación | Olvidaste limitar `retry_on_methods`. | Añade `retry_on_methods=("GET", "HEAD")` explícitamente. |
| Refresh loop infinito | El nuevo token sigue siendo 401. | `RefreshInterceptor` hace UN retry — chequea `on_refresh` que realmente actualice el token. |
| Interceptor no se aplica al client X | `applies_to` no matchea el name. | Imprime `[(i.name, i.applies_to(name)) for i in registry._ambient]` en boot. |
| Conexiones se acumulan | Olvidaste `aclose_all` en shutdown. | Ya lo hace bootstrap automáticamente. Verifica que no estás creando clients fuera del registry. |
| Discovery no carga `stripe.py` | El archivo empieza con `_` o no exporta una instancia. | Renombra y exporta a nivel de módulo (no dentro de función). |
