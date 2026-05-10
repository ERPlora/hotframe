# Checkpoints — repaso de la guía

> Preguntas para repasar cada capítulo de la guía. La idea: leer el
> md correspondiente, luego responder las preguntas de su checkpoint
> sin mirar. Si fallas alguna, vuelve a leer la sección concreta.

---

## Cómo usar este archivo

1. Lee `docs/internals/<X>.md`.
2. Sin volver a abrirlo, intenta responder las preguntas del
   checkpoint X.
3. Verifica con el md.
4. Pasa al siguiente.

Cada checkpoint tiene:
- **Conceptos clave** — la lista de cosas que deberías recordar.
- **Preguntas** — preguntas para verificar comprensión.
- **Trampas** — errores comunes que te aseguran que entiendes el
  matiz.

---

## CP-1 · bootstrap.md (top-level: __init__, asgi, bootstrap)

**Conceptos clave**
- Lazy imports en `__init__.py` (PEP 562 `__getattr__`).
- `asgi.py` es el entrypoint de uvicorn (`hotframe.asgi:application`).
- `create_app(settings)` es síncrono; `lifespan` es async.

**Preguntas**
1. ¿Por qué `__init__.py` no importa eager los 80 símbolos?
2. ¿Dónde se mounta `/ws/_live`? ¿Y `/static/hotframe/`?
3. ¿Qué pasos del lifespan son async-only y por qué no caben en
   `create_app`?
4. ¿Por qué telemetry se skipea bajo pytest?
5. ¿En qué paso del lifespan se llama a
   `boot_all_active_modules` y qué hace si falla un módulo?

**Trampas**
- `create_app` arranca el `LiveRuntime`, pero **no abre la WS** —
  eso pasa cuando un cliente se conecta a `/ws/_live`.
- `_auto_discover_apps` corre síncrono dentro de `create_app`, no
  en lifespan. Si tu `AppConfig.ready` es async, se ejecuta con
  `asyncio.run` en un loop transitorio.

---

## CP-2 · config.md (settings + database + paths)

**Conceptos clave**
- `HotframeSettings` extiende `BaseSettings` de Pydantic.
- `get_settings()` y `get_engine()` son singletons.
- `DataPaths` es para caches **efímeros** en `/tmp/`.

**Preguntas**
1. ¿Qué validator se queja si `DEPLOYMENT_MODE=web` sin `SECRETS_KEY`?
2. ¿Por qué `DB_DISABLE_PREPARED_STATEMENTS` existe?
3. ¿Qué hace `pool_pre_ping=True` y por qué pagamos su coste?
4. ¿Cómo override settings en tests sin tocar variables de entorno?
5. ¿Cuál es la diferencia entre `MEDIA_ROOT` (settings) y
   `DataPaths.media`?

**Trampas**
- `get_db()` (FastAPI dependency) hace `commit` al final si no hay
  excepción. Si abres una transacción manual, controla tú el ciclo.
- Subclasing `HotframeSettings` con `env_prefix="MYAPP_"` afecta
  **todos** los campos heredados — `MYAPP_DEBUG`, no `DEBUG`.

---

## CP-3 · auth.md

**Conceptos clave**
- `bcrypt` para passwords (`hash_password`, `verify_password`).
- CSRF double-submit cookie + token in form.
- CSP nonce per request.
- `get_current_user` resuelve user via `AUTH_USER_MODEL`.
- Permissions con `fnmatch` (e.g. `"sales.*"`).
- Encryption Fernet via `SECRETS_KEY`.

**Preguntas**
1. ¿Por qué CSRF usa double-submit cookie en lugar de solo token?
2. ¿Cómo se lee la `csrf_token` en un template y qué auto-inyecta
   `_HotframeTemplates`?
3. ¿Qué hace `session_helpers.get_session_data(websocket)`?
4. `has_permission(["sales.*"], "sales.create")` ¿retorna True?
5. ¿Cómo funciona `EncryptedString(length=512)` y qué pasa si
   `SECRETS_KEY` cambia?

**Trampas**
- `CSP_TRUSTED_TYPES=False` por default — habilitar rompe `live.js`
  + morphdom.
- `PINRateLimiter` es **distinto** del `APIRateLimitMiddleware`.

---

## CP-4 · apps.md

**Conceptos clave**
- `AppConfig` (estática) vs `ModuleConfig` (dinámica con manifest).
- `ModuleManifest` con `MODULE_ID`, version, dependencies.
- `ModuleService` + `@action` para servicios versionados.
- Registries: `AppRegistry` y `ModuleRegistry`.

**Preguntas**
1. ¿Qué exporta `apps/<name>/app.py` y `modules/<id>/module.py`?
2. ¿Cómo se valida una version constraint `">=1.0,<2"`?
3. ¿Para qué sirve `@action("name")` y dónde se persiste su lookup?
4. ¿Qué pasa si `MODULE_ID` del manifest difiere del catalog key?

**Trampas**
- `is_system=True` bloquea `deactivate` y `uninstall` —
  comprobado en `module_runtime`.
- `ModuleConfig` también es subclase de `AppConfig`, pero el
  scanner las distingue por `module.py` vs `app.py`.

---

## CP-5 · components.md

**Conceptos clave**
- Componente = directorio con `template.html` + opcional
  `component.py`/`routes.py`/`static/`.
- Render via `render_component('name', **props)` o tag
  `{% component 'name' %}body{% endcomponent %}`.
- Aislamiento: solo props + framework slice (request, csrf, csp).
- `is_live` distingue `LiveComponent` de `Component` stateless.

**Preguntas**
1. ¿Qué pasa si una macro/componente no tiene `template.html`?
2. ¿Cómo pasas un `class` HTML (palabra reservada) a un componente?
3. ¿Por qué el componente NO ve las variables del template padre
   por default?
4. ¿Qué hace `_TrackingContext` y por qué es necesario?

**Trampas**
- Un componente con prop validation fallida produce un comentario
  HTML, no un 500.
- `{% component %}` y `render_component()` comparten `_render_entry`
  — la diferencia es solo el body block.

---

## CP-6 · db.md

**Conceptos clave**
- Protocols `ISession`/`IQueryBuilder`/`IRepository` (PEP 544).
- `EncryptedString`/`EncryptedText` cifran al insert, descifran al
  read (Fernet).
- `SingletonMixin.get_config(session, hub_id)` — one-row-per-tenant.

**Preguntas**
1. ¿Por qué Protocols y no ABCs?
2. ¿`WHERE encrypted_col = 'foo'` funciona? ¿Por qué?
3. ¿`SingletonMixin` es seguro con concurrencia?
4. `cache_ok=True` en TypeDecorator — ¿qué cambia?

**Trampas**
- `length=512` en `EncryptedString` se refiere al **ciphertext**,
  no al plaintext.
- Si rotas `SECRETS_KEY`, los datos viejos quedan ilegibles. Plan
  de migración necesario.

---

## CP-7 · dev.md

**Conceptos clave**
- `ModuleWatcher` con `watchfiles` (FSEvents/inotify).
- Solo en `DEBUG=True`. Sin watchfiles, log warning + skip.
- Throttle 1s + debounce 300ms para evitar spam.

**Preguntas**
1. ¿Qué archivos se watch (extensiones)?
2. ¿Qué hace `_extract_module_id` y por qué?
3. ¿Por qué el watcher no puede recargar `hotframe/` propio?

**Trampas**
- `ModuleWatcher` no se monta automáticamente en `bootstrap` — es
  opt-in. Tu `main.py` debe llamarlo si lo quieres.

---

## CP-8 · discovery.md

**Conceptos clave**
- `scan(root, *, package_prefix)` retorna list[`DiscoveryResult`].
- Conventions list: `app.py`/`module.py`, `models.py`, `routes.py`,
  `api.py`, `templates/`, `migrations/`, etc.
- `required_exports` semántica at-least-one-of.
- `find_entry_config(result)` extrae la subclase de `AppConfig`.

**Preguntas**
1. ¿Por qué `app.py` XOR `module.py`?
2. `routes.py` exporta `urlpatterns` o `router` — ¿qué error pasa
   si exporta ninguno?
3. ¿Por qué `find_entry_config` usa `importlib.import_module`?
4. ¿Qué errores son fatales y cuáles solo se acumulan en
   `result.errors`?

**Trampas**
- El scanner es side-effect-free **excepto importlib**.
- Errors de `required_exports` son fatales. Errors de import son
  acumulados.

---

## CP-9 · engine.md

**Conceptos clave**
- `ModuleRuntime` orquesta todo el lifecycle.
- `HotMountPipeline` ejecuta phases con LIFO rollback.
- Multi-worker: advisory lock por hub para serializar DB writes.
- Phases del install: DOWNLOADING, VALIDATING, MIGRATING,
  IMPORTING, MOUNTING, STACK_REBUILD.
- `ImportManager` con weakrefs para detectar zombies.

**Preguntas**
1. ¿Qué pasa si una phase falla? ¿En qué orden se deshacen?
2. ¿Por qué advisory lock con `pg_try_advisory_xact_lock`?
3. `_load_from_path` hace `session.rollback()` defensivo — ¿por qué?
4. ¿Qué diferencia `deactivate` de `uninstall` con `cascade`?
5. `PurgeReport.zombies` ¿qué te dice?

**Trampas**
- `uninstall` **nunca** cascade. `deactivate` sí (con flag).
- Workers que pierden el lock siguen montando rutas localmente
  (cada worker su FastAPI), solo skipean DB writes.

---

## CP-10 · http.md

**Conceptos clave**
- `AuthenticatedClient` envuelve httpx.
- Auth strategies (BearerAuth, ApiKeyAuth, HmacAuth, etc.).
- Interceptors estilo Angular: `intercept(req, call_next)`.
- Built-ins: `RetryInterceptor`, `CircuitBreakerInterceptor`,
  `RefreshInterceptor`.
- `discover_interceptors(paths)` para ambient pool.

**Preguntas**
1. ¿En qué orden se aplica auth vs interceptors?
2. `RetryInterceptor` con `retry_on_methods=("GET",)` — ¿qué pasa
   con un POST 503?
3. `CircuitBreaker` open → half_open → closed: ¿en qué condiciones?
4. `RefreshInterceptor` cuántos retries hace tras refresh?
5. ¿Qué significa `applies_to="stripe*"`?

**Trampas**
- Retry default solo en métodos idempotentes — POST no.
- Circuit breaker is local al interceptor — no compartido entre
  workers.

---

## CP-11 · live.md

**Conceptos clave**
- `LiveComponent` hereda de Pydantic, props + state.
- `@event(name)` stamp para handlers async.
- WebSocket `/ws/_live`, JSON envelopes (attach/event/bind/detach).
- `morphdom` cliente preserva focus/scroll.
- State per-WS-session en RAM (sticky implícito).

**Preguntas**
1. ¿Por qué `on_mount` debe ser idempotente?
2. ¿Qué hace `bind` y por qué no re-renderiza?
3. `live.js` reconnect: ¿qué hace al reconectar?
4. ¿Cómo se preservan focus + value de inputs en un re-render?
5. ¿Qué pasa con state si `--workers 4` en uvicorn?

**Trampas**
- No guardes asyncio.Tasks vivos en `self`. Reconnect descarta
  la instancia.
- `bind` actualiza state pero no manda patch — el render llega
  con el siguiente `event`.

---

## CP-12 · management.md (CLI `hf`)

**Conceptos clave**
- Typer con sub-app `hf modules ...`.
- `startproject .` genera en cwd.
- `hf shell` con IPython si está, else builtin.
- `hf modules install` acepta name/zip/URL/marketplace.

**Preguntas**
1. `hf startproject` con `.` ¿qué genera?
2. `hf shell` sin IPython, ¿cómo `await` un coro?
3. `hf modules update` ¿qué pasa si la nueva versión falla?

**Trampas**
- CLI usa el mismo `lifespan` que uvicorn — la BD se abre.
- `--system` flag en `startmodule` marca `is_system=True` en el
  manifest.

---

## CP-13 · middleware.md

**Conceptos clave**
- 12 middleware default en `settings.MIDDLEWARE`.
- Outermost first; `build_middleware_stack` itera reversed.
- `ModuleBoundary` está fuera de `ModuleMiddlewareManager`.
- Rate limiter in-memory por proceso.

**Preguntas**
1. ¿Por qué `RobustSessionMiddleware` está al final del stack?
2. ¿Qué hace `ModuleBoundaryMiddleware`?
3. ¿En `DEBUG=True`, qué `auth_rate` se aplica?
4. ¿Cómo funciona `LanguageMiddleware` con `?lang=es` vs cookie vs
   header?

**Trampas**
- `CORS` se monta **fuera** del stack normal, después.
- `ProxyFixMiddleware` es opt-in via `PROXY_FIX_ENABLED=true`.

---

## CP-14 · migrations.md

**Conceptos clave**
- `alembic_<module_id>` version_table per-module.
- `asyncio.to_thread` porque Alembic es sync.
- `get_sync_db_url` quita `+asyncpg`/`+aiosqlite`.
- `include_object` filter en env.py para no tocar otras tablas.

**Preguntas**
1. ¿Por qué `version_table = f"alembic_{module_id}"`?
2. `downgrade base` ¿revierte qué?
3. ¿Por qué pasamos `engine` por `config.attributes["connection"]`?

**Trampas**
- Si `alembic --autogenerate` ve tablas de otros módulos, intentará
  borrarlas. `include_object` lo evita.

---

## CP-15 · models.md

**Conceptos clave**
- `Model` es la base recomendada (UUID PK + timestamps).
- Mixins: `HubMixin`, `TimestampMixin`, `AuditMixin`,
  `SoftDeleteMixin`.
- `HubQuery` autofiltra `hub_id` y `is_deleted`.
- `get_or_create` race-safe.

**Preguntas**
1. ¿Por qué UUID en client y no auto-increment server?
2. `with_deleted()` ¿qué desactiva?
3. `get_or_create` — ¿qué pasa si dos requests entran a la vez?
4. `delete(id)` sin `SoftDeleteMixin` ¿qué hace?

**Trampas**
- No mezclar `Model` (timestamps incluidos) con `TimestampMixin` —
  duplica columnas.

---

## CP-16 · orm.md

**Conceptos clave**
- `atomic(session)` con SAVEPOINT si nested.
- `on_commit(session, callback)` se descarta en rollback.
- `setup_orm_events` emite typed + legacy events.
- `_emit_async` skipea si no hay event loop.
- `PgNotifyBridge` opcional con asyncpg.

**Preguntas**
1. ¿Cuándo `on_commit` callback no se ejecuta?
2. ¿Por qué `_emit_async` checks `get_running_loop`?
3. ¿Cómo `before_insert` setea `hub_id` automáticamente?
4. `PgNotifyBridge` — ¿multi-process o single-process?

**Trampas**
- Eventos no llegan a subscribers si `setup_orm_events` no fue
  llamado en lifespan.

---

## CP-17 · repository.md

**Conceptos clave**
- `BaseRepository[T]` sobre `HubQuery`.
- `list(...)` retorna `{items, total}`.
- `update(id, **kwargs)` es permissive (ignora kwargs desconocidos).
- `serialize(obj, ...)` UUID → str, Decimal → str, datetime → iso.

**Preguntas**
1. `search_fields` aplica qué tipo de query?
2. ¿Cómo eager-loadear una relación?
3. `update()` con un kwarg que no existe en el modelo — ¿qué pasa?

**Trampas**
- El repo no commitea — solo flush. Tu handler hace commit.

---

## CP-18 · signals.md

**Conceptos clave**
- `AsyncEventBus` con typed (Pydantic) + legacy (string).
- `HookRegistry` actions/filters WordPress style.
- `CRITICAL_EVENT_PREFIXES` auto fail_fast.
- `BaseEvent` frozen, extra="forbid", auto-populate hub_id/user_id.
- `module_id` en handlers permite cleanup en uninstall.

**Preguntas**
1. ¿Cuál es la diferencia entre EventBus y HookRegistry?
2. `await bus.subscribe("user.*", h)` ¿matchea `user.created.profile`?
3. `error_policy="fail_fast"` ¿qué hace con once handlers ya
   invocados?
4. `BaseEvent` con `extra="forbid"` — ¿qué pasa con un kwarg extra?

**Trampas**
- `emit` no falla por default — `EmitResult.errors` los acumula.
- `apply_filters` con un callback que crashea: log + skip,
  continúa con el último `result`.

---

## CP-19 · templating.md

**Conceptos clave**
- Search paths ordenados: project → apps → modules → component
  roots.
- `_HotframeTemplates` auto-injecta CSRF, CSP, request.
- `SlotRegistry` con `condition_fn` y `context_fn` async.
- Extensiones: `{% component %}`, `{% live %}`, `{% frame %}`,
  i18n, `do`, `loopcontrols`.
- Filters: currency, dateformat, timesince, truncatewords, slugify.

**Preguntas**
1. Si dos paths tienen `index.html`, ¿cuál gana?
2. ¿Cómo se invalida el cache de templates tras instalar un módulo?
3. ¿Qué hace `condition_fn` en un slot entry?

**Trampas**
- Autoescape on por default — `{{ var | safe }}` o `Markup(...)`
  para HTML literal.

---

## CP-20 · testing.md

**Conceptos clave**
- `create_test_app(**overrides)` con SQLite in-memory, CSRF disabled,
  rate-limit alto.
- `test_db_session()` rollback siempre al final.
- `FakeEventBus` registra emisiones, no replica priority/wildcards.

**Preguntas**
1. ¿Por qué `CSRF_EXEMPT_PREFIXES=["/"]` en tests?
2. `cleanup_test_db()` cuándo llamarla?
3. `FakeEventBus.emit(event_name, data)` API ¿es 100% compatible
   con `AsyncEventBus.emit`?

**Trampas**
- SQLite no tiene `pg_try_advisory_xact_lock` — el código del
  engine ya skipea.

---

## CP-21 · utils.md

**Conceptos clave**
- `RequestContext` ContextVar — single source of truth para
  request-scoped IDs.
- `setup_logging` con structlog — JSON o console color.
- `setup_telemetry` — OTLP gRPC exporter o console (si DEBUG).
- Auto-instrumentation de FastAPI, SQLAlchemy, httpx.
- Metrics + traces lazy — sin SDK no-op.

**Preguntas**
1. ¿Qué hace `bind_context(request_id=X)` y cuándo restaurar?
2. ¿Cómo añadir `user_id` mid-request?
3. ¿Por qué `bootstrap` skipea telemetry bajo pytest?
4. `get_event_emit_counter` sin SDK ¿qué retorna?

**Trampas**
- `request_id` aparece en logs vía `_add_request_context` processor.
  Si falta, mira que `CorrelationIdMiddleware` esté en stack.

---

## CP-22 · views.md

**Conceptos clave**
- `@view(module_id, view_id, permissions=...)` — auth + perms +
  template auto-discovery.
- `_resolve_template` con LRU cache busca en
  `pages/{view}.html` y variants.
- `reactive_*` helpers son HTTP responses planos.
- `BroadcastHub` process-local fan-out.

**Preguntas**
1. ¿Qué patterns prueba `_resolve_template` para `view_id="dashboard"`?
2. ¿Qué hace `reactive_redirect` (status code)?
3. `BroadcastHub.publish` con queue full — ¿qué pasa?
4. `is_reactive_request(request)` — ¿qué retorna y por qué?

**Trampas**
- `is_htmx_request` siempre `False` — la API se mantiene pero el
  comportamiento cambió. Migra a LiveComponent.

---

## Cierre — preguntas transversales

Cuando hayas pasado los 22 checkpoints, valida que entiendes el
flujo completo:

1. ¿Qué pasa **paso a paso** desde `uvicorn hotframe.asgi:application`
   hasta que un cliente conecta a `/ws/_live`?
2. ¿Qué objetos viven en `app.state` y para qué sirve cada uno?
3. ¿Cuándo usar `AsyncEventBus`, `HookRegistry`, `BroadcastHub`,
   `LiveComponent` events?
4. Si un módulo crashea durante install, ¿en qué orden se
   deshacen las cosas? ¿Qué archivos del filesystem quedan?
5. ¿Por qué hotframe es "stateless" si tiene state en
   `LiveSession.components`?
6. ¿Cómo escalas hotframe a `--workers 4`? ¿Qué necesitas tocar?

Si puedes responder a estas seis sin mirar la guía, dominas
hotframe.
