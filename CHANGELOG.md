# Changelog

## 0.2.0 (V2 — Datastar migration)

**BREAKING CHANGES — frontend stack reescrito de HTMX/Alpine a Datastar.**

### Added
- `hotframe.reactivity` — fachada sobre `datastar-py>=1.0.0`. Re-exports
  con nombres neutros: `reactive` (`attribute_generator`), `sse_response`
  (decorador), `SSEResponse` (clase), `ServerSentEventGenerator`,
  `read_signals`, `ReadSignals`, `SSE_HEADERS`.
- `hotframe.views.responses` reescrito con detección Datastar:
  - `view` decorator (sustituye a `htmx_view` — alias mantenido para
    backward compat hasta 0.3).
  - `is_reactive_request` (`Datastar-Request` header).
  - `reactive_redirect`, `reactive_refresh`, `reactive_trigger`,
    `reactive_message` — todos vía SSE/`patch_elements`.
- `hotframe.engine.boundary.ModuleBoundaryMiddleware` — aísla excepciones
  de módulos. Threshold 10/60s → marca módulo como `degraded`. Emite
  eventos `module.error` y `module.degraded` por el `AsyncEventBus`.
- `ModuleStatus` Literal en `engine/state.py` con valor `degraded`;
  `ModuleStateDB.set_degraded()`.
- `auth/session_helpers.py` con `get_session_data()` para WebSocket auth
  (Starlette session middleware no expone scope a WS).
- `middleware/observability.py` con `RequestObservabilityMiddleware`
  (binding correlation_id + request duration histogram).
- Dep nueva: `asgi-correlation-id>=4.3.4`.
- `reactive` registrado como global de Jinja2.
- `{% frame %}` reescrito para emitir atributos Datastar:
  - `lazy=True` → `data-on-intersect="@get(url)"`.
  - default → `data-on:load="@get(url)"`.
  - `trigger="click"` → `data-on:click="@get(url)"`.
  - `push_url=True` → `@get(url, {history: 'push'})`.
- `docs/hooks-and-events.md`.
- Tests: `tests/engine/test_boundary.py` (8), `tests/engine/test_unload_leaks.py` (50 ciclos load/unload, RSS estable), `test_frame_extension.py` (9), `test_views.py` reescrito (19).

### Removed
- `hotframe.forms` (FormRenderer) — sin consumidores reales.
- `hotframe.storage` (MediaStorage) — sin consumidores reales.
- `hotframe.auth.jwt` (`create_jwt`, `verify_jwt`) — sin consumidores; usar `pyjwt` directamente cuando se necesite.
- `hotframe.middleware.session` — sustituido por `starlette.middleware.sessions.SessionMiddleware`.
- `hotframe.middleware.request_id` — sustituido por `asgi_correlation_id.CorrelationIdMiddleware`.
- `hotframe.middleware.trailing_slash` — sustituido por `FastAPI(redirect_slashes=True)`.
- `hotframe.middleware.htmx` (`HtmxMiddleware`, `HtmxDetails`) — Datastar usa `Datastar-Request` header.
- `hotframe.middleware.htmx_messages` (`HtmxMessagesMiddleware`) — `add_message` ahora vía `patch_elements`.
- `hotframe.templating.htmx_helpers` (`hx_get`, `hx_post`, `hx_put`, `hx_patch`, `hx_delete`, `hx_trigger`, `hx_indicator`, `hx_vals`).
- `hotframe.templating.alpine_helpers` (`alpine_data`, `alpine_show`, `alpine_cloak`).
- `hotframe.views.streams` (`TurboStream`, `StreamResponse`) — Datastar cubre el mismo caso con N llamadas a `patch_elements` sobre la misma SSE.
- Setting `RATE_LIMIT_HTMX` (los rate limits de `/m/` siguen vía default 300/min en el middleware).
- `is_htmx` global en Jinja context.

### Changed
- `_LAZY_IMPORTS` actualizado: -3 (forms, storage), -9 (HTMX-related vía streams), +7 (reactivity), nuevos canónicos. **Total: 90 símbolos públicos.**
- `CSP_TRUSTED_TYPES` default `True` → `False`. Trusted Types es incompatible con Datastar 1.0 (que usa `Function()` constructor) — la doc oficial Datastar lo confirma. Defensa restante: nonces + CSP, CSRF, Jinja escape, SameSite=Strict, sesión firmada.
- `engine/loader.py`: `gc.collect()` explícito tras unload (fix leaks B y C — closures middleware + clases ORM zombies).
- `asgi.py` simplificado: `ProxyFixMiddleware` solo se aplica si `PROXY_FIX_ENABLED=True` (ECS-slug logic). El caso estándar X-Forwarded-* lo cubre `uvicorn --proxy-headers`.

### Backward compatibility (deprecation path)
Los siguientes símbolos siguen disponibles como aliases en 0.2.0 y se eliminarán en 0.3:
- `htmx_view` → `view`
- `is_htmx_request` → `is_reactive_request`
- `htmx_redirect` → `reactive_redirect`
- `htmx_refresh` → `reactive_refresh`
- `htmx_trigger(event, data)` → mantiene shape legacy (dict payload). Usar `reactive_trigger` para nuevo código.

### Migration notes for downstream apps
1. Actualizar dependencia: `hotframe>=0.2.0`.
2. Sustituir `Datastar-Request` checks por `is_reactive_request(request)`.
3. Cargar `datastar.js` 1.0 en `<head>` (sustituye a `htmx.min.js` + `alpine.min.js` + plugins).
4. Migrar atributos en plantillas:
   - `hx-get="..."` → `data-on:click="@get('...')"` (o el evento que aplique).
   - `x-data="{count: 0}"` → `data-signals="{count: 0}"`.
   - `x-show="..."` → `data-show="..."`.
   - `x-bind:value` → `data-bind="signal_name"`.
5. CSP: añadir `'unsafe-eval'` a `script-src` (Datastar lo requiere).
6. Si usas Trusted Types: NO compatible con Datastar — desactivar.

## 0.1.1
Anterior — ver git log.
