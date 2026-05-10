# middleware.md — Middleware stack and 14 middleware classes

> **Carpeta cubierta:** `src/hotframe/middleware/`. Catorce archivos:
> `__init__.py`, `stack.py`, `body_limit.py`, `csp.py`,
> `error_pages.py`, `i18n_support.py`, `language.py`,
> `module_middleware.py`, `observability.py`, `proxy_fix.py`,
> `rate_limit.py`, `session_safe.py`, `stack_manager.py`, `timeout.py`.
>
> El stack se monta en orden por `stack.build_middleware_stack` desde
> `settings.MIDDLEWARE`.

---

## 1. `stack.py` — `build_middleware_stack(app, settings)`

```python
def build_middleware_stack(app, settings):
    for dotted_path in reversed(settings.MIDDLEWARE):
        cls = _import_class(dotted_path)
        kwargs = _get_middleware_kwargs(cls, settings)
        app.add_middleware(cls, **kwargs)
```

Decisiones clave:

- **`reversed(MIDDLEWARE)`** — Starlette convention: el último
  añadido es el más externo. La lista en settings es "outermost
  first" (más legible), así que iteramos al revés.
- **`_get_middleware_kwargs`** — diccionario de kwargs por clase.
  Cada middleware "core" tiene su firma; el helper sabe rellenar
  desde settings. Si el middleware es custom, devuelve `{}` y se
  asume sin kwargs.

Mapeo de kwargs:

| Clase | Kwargs |
|---|---|
| `SessionMiddleware`, `RobustSessionMiddleware` | `secret_key`, `max_age`, `session_cookie`, `same_site="strict"`, `https_only` |
| `CSPMiddleware` | `enforce` |
| `APIRateLimitMiddleware` | `api_rate`, `auth_rate` (10000 si DEBUG), `window=60`, `auth_prefixes` |
| `BodyLimitMiddleware` | `max_bytes` |
| `TimeoutMiddleware` | `timeout=30` (segundos) |
| `ModuleMiddlewareManager` | `registry=None` (lo resuelve en runtime de `app.state`) |

---

## 2. `timeout.py` — `TimeoutMiddleware`

Cancela un request que excede N segundos:

```python
class TimeoutMiddleware:
    def __init__(self, app, timeout=30):
        self.app, self.timeout = app, timeout
    async def __call__(self, scope, receive, send):
        try:
            async with asyncio.timeout(self.timeout):
                await self.app(scope, receive, send)
        except TimeoutError:
            ... # responde 504
```

`asyncio.timeout` es Python 3.11+. Si el handler está esperando IO
y no responde en `timeout` segundos, la task se cancela y devuelve
504 Gateway Timeout.

---

## 3. `error_pages.py` — `ErrorPageMiddleware`

Captura excepciones no manejadas y devuelve la página `errors/500.html`
en lugar del traceback default de FastAPI. En API requests
(`/api/*`) responde JSON `{"detail": "Internal server error"}`.

```python
class ErrorPageMiddleware:
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            logger.exception("Unhandled %s: %s", type(e).__name__, e)
            if request.url.path.startswith("/api/"):
                return JSONResponse(...)
            templates = request.app.state.templates
            return templates.TemplateResponse("errors/500.html", ...,
                                               status_code=500)
```

---

## 4. `body_limit.py` — `BodyLimitMiddleware`

Rechaza requests con body > `MAX_REQUEST_BODY` (default 10 MB):

```python
class BodyLimitMiddleware:
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cl = headers.get("content-length")
        if cl and int(cl) > self.max_bytes:
            await send_413(send); return
        # Track body chunks if no content-length:
        ...
```

Protección DoS — un cliente no puede subir 1 GB de body.

---

## 5. `observability.py` — `RequestObservabilityMiddleware`

Emite logs estructurados con `request_id`, `method`, `path`, `status`,
`duration_ms`, `client_ip`. Usa `asgi_correlation_id` para el
request_id (montado antes en el stack).

```python
class RequestObservabilityMiddleware:
    async def dispatch(self, request, call_next):
        t0 = time.monotonic()
        try:
            response = await call_next(request)
            duration = (time.monotonic() - t0) * 1000
            logger.info("%s %s %d %.0fms", request.method, request.url.path,
                        response.status_code, duration)
            return response
        except Exception:
            ... # log con duration y re-raise
```

---

## 6. `rate_limit.py` — `APIRateLimitMiddleware`

In-memory rate limiter (token bucket por IP/path).

```python
class APIRateLimitMiddleware:
    def __init__(self, app, *, api_rate=120, auth_rate=60, window=60,
                 auth_prefixes=()):
        self._buckets = {}  # key=(ip, bucket_name) -> [count, window_start]
    async def dispatch(self, request, call_next):
        bucket = self._classify(request.url.path)  # 'auth', 'view', or 'api'
        rate = self.auth_rate if bucket == "auth" else self.api_rate
        key = (client_ip, bucket)
        if self._is_exceeded(key, rate):
            return JSONResponse({"detail": "Rate limit"}, status_code=429,
                                headers={"Retry-After": "60"})
        return await call_next(request)
```

Tres buckets:
- **`auth`**: paths que coincidan con `auth_prefixes` (ej. `/login`,
  `/register`). Default rate = 60/min.
- **`view`**: paths HTML normales. Internal default = 300/min.
- **`api`**: paths bajo `/api/`. Default rate = 120/min.

In-memory por proceso. No coordinado entre workers — para multi-worker
estricto, usa Redis-backed (no incluido).

`PINRateLimiter` (en `auth/rate_limit.py`) es separado — específico
para login con PIN en el módulo auth.

---

## 7. `csp.py` — `CSPMiddleware`

Añade `Content-Security-Policy` (o `Content-Security-Policy-Report-Only`
si `enforce=False`) basado en `settings.CSP_ALLOWED_SOURCES`.

```python
class CSPMiddleware:
    def __init__(self, app, *, enforce=False):
        self.enforce, self.app = enforce, app
    async def dispatch(self, request, call_next):
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        header_name = "Content-Security-Policy" if self.enforce \
                      else "Content-Security-Policy-Report-Only"
        response.headers[header_name] = build_csp_header(nonce, settings)
        return response
```

`request.state.csp_nonce` lo lee `_HotframeTemplates` para inyectar
en cada `TemplateResponse`. Templates lo usan en `<script nonce="{{
csp_nonce }}">`.

Si `CSP_TRUSTED_TYPES=True`, añade `require-trusted-types-for 'script'`
— pero esto rompe `live.js` + morphdom. Default `False`.

---

## 8. `language.py` — `LanguageMiddleware`

Detecta el idioma preferido y lo guarda en `request.state.language`.
Orden de precedencia:

1. Query param `?lang=es`
2. Cookie `language`
3. `Accept-Language` header
4. `settings.LANGUAGE` fallback

```python
class LanguageMiddleware:
    async def dispatch(self, request, call_next):
        lang = (request.query_params.get("lang")
                or request.cookies.get("language")
                or _parse_accept(request.headers.get("accept-language"))
                or settings.LANGUAGE)
        request.state.language = lang
        return await call_next(request)
```

`i18n_support.py` provee helpers para gettext (`_("text")` con
fallback a strings sin traducir si no hay catálogo).

---

## 9. `i18n_support.py`

Wrappers alrededor de Babel/gettext. Carga catalogues en `apps/<app>/locales/`
y `modules/<id>/locales/`. Provee:

- `_(text)` — traduce el text con el `request.state.language` activo
  (via contextvar).
- `_n(singular, plural, n)` — pluralization.

Activado por `LanguageMiddleware`. Sin él, `_(...)` devuelve el
original sin traducir.

---

## 10. `session_safe.py` — `RobustSessionMiddleware`

Subclase de `SessionMiddleware` de Starlette que captura
`SignatureError` (cookie modificado) y, en lugar de 500, **descarta
la sesión** y deja la request continuar como anónima.

```python
class RobustSessionMiddleware(SessionMiddleware):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except (SignatureError, BadSignature):
            # Wipe and continue
            scope["session"] = {}
            await self._send_clear_cookie(send)
            await super().__call__(scope, receive, send)
```

Útil cuando rotas `SECRET_KEY` — los users con cookies viejos no
ven 500, sino que se loguean como anónimos.

---

## 11. `proxy_fix.py` — `ProxyFixMiddleware`

Específico para el setup de ECS slug detrás de CloudFront:

```
Cliente → CloudFront → ALB → ECS task ("hub-XXXXX-region.elb.amazonaws.com")
```

Reescribe `request.url.netloc` con el dominio público real. Necesario
porque FastAPI no sabe que la URL original era `mihub.example.com` y
no `hub-XXXXX....elb.amazonaws.com` cuando construye redirects o
URLs absolutas.

Activación: `PROXY_FIX_ENABLED=true` + `PROXY_SLUG`, `PROXY_DOMAIN_BASE`,
`PROXY_AWS_REGION`.

---

## 12. `module_middleware.py` — `ModuleMiddlewareManager`

Permite a módulos contribuir sus propios middlewares **sin reiniciar
el server**. El manager mantiene una lista interna y los aplica en
cada request:

```python
class ModuleMiddlewareManager:
    def __init__(self, app, registry=None):
        self.middlewares: list[tuple[str, Middleware]] = []
    async def dispatch(self, request, call_next):
        # Build composed call_next with each module middleware wrapped
        ...
    def register(self, module_id, middleware): ...
    def unregister(self, module_id): ...
```

Cuando un módulo se instala, su `module.py` puede contener:

```python
from hotframe import action
@action("on_install")
async def register_my_middleware(runtime, ...):
    runtime.app.state.module_middleware.register(
        "my_module", MyAuthMiddleware(rate=100))
```

Al desinstalar, `unregister("my_module")` elimina su middleware del
manager.

---

## 13. `stack_manager.py` — helpers de teardown

Funciones utility usadas por `ModuleLoader.unload_module` para
filtrar `app.user_middleware` y quitar contribuciones de un módulo
desinstalado. Complementario a `unmount_component_*` para componentes.

---

## 14. Decisiones que conviene recordar

1. **Stack es declarativo** — `settings.MIDDLEWARE` es la lista
   completa. Override en proyecto si necesitas custom.
2. **Orden importa.** Outermost first. `TimeoutMiddleware` envuelve
   todo; `RobustSessionMiddleware` está al final (más cerca del
   handler).
3. **`asgi_correlation_id` antes de observability.** Para que el
   logger tenga `request_id` ya disponible.
4. **`ModuleBoundaryMiddleware` (engine) está fuera de
   `ModuleMiddlewareManager`** — captura crashes en middlewares de
   módulos.
5. **`CSPMiddleware` siempre genera nonce.** Aunque `enforce=False`,
   el nonce está disponible — útil cuando quieres testear sin romper.
6. **Rate limiter in-memory.** No requiere Redis. Multi-worker no
   coordinado.
7. **`RobustSessionMiddleware`** evita 500 en rotación de keys.

---

## 15. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| 504 Timeout en endpoints lentos | `TimeoutMiddleware(timeout=30)` corta. | Sube el timeout o haz el endpoint async-friendly. |
| 413 Request Entity Too Large | Body > `MAX_REQUEST_BODY`. | Sube `MAX_REQUEST_BODY` en settings. |
| 429 Too Many Requests en dev | `auth_rate` aplicado. | En `DEBUG=True`, `auth_rate=10000` ya está sobrepuesto. Si igual te llega, mira `auth_prefixes`. |
| `request.state.csp_nonce` AttributeError | `CSPMiddleware` no en stack. | Añádelo a `MIDDLEWARE` o usa `getattr(request.state, "csp_nonce", "")`. |
| Login falla tras rotar SECRET_KEY | Sessions viejas inválidas. | `RobustSessionMiddleware` ya lo arregla — verifica que está montado. |
| `_("hello")` devuelve sin traducir | Catalog no compilado o `LanguageMiddleware` ausente. | Compila `.po` → `.mo` y monta el middleware. |
| Module middleware no se aplica | `ModuleMiddlewareManager` no en stack o `register` no se llamó. | Verifica el stack y el `on_install` del módulo. |
