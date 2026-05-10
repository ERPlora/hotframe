# Hotframe — Internal Guide

> **Versión:** 1.0.0
> **PyPI:** https://pypi.org/project/hotframe/
> **Repo:** https://github.com/hotframe/hotframe
>
> Esta guía cubre **toda la arquitectura interna** del framework,
> archivo por archivo. Está organizada **por carpeta de
> `src/hotframe/`** — cada `internals/<carpeta>.md` cubre una
> carpeta del source tree con secciones por archivo.

---

## Cómo leer esta guía

Hotframe es un framework con muchas piezas que encajan en un orden
preciso. Recomendación de lectura:

1. **Empezar por `bootstrap.md`** — entiendes el orden de arranque
   y dónde se enchufa cada subsistema.
2. **`config.md`** — entiendes settings, DB engine, paths.
3. **`models.md`, `db.md`, `repository.md`, `orm.md`** — capa de
   persistencia.
4. **`signals.md`** — pub/sub, eventos tipados, hooks.
5. **`templating.md`, `views.md`** — render HTML.
6. **`components.md`** — componentes reutilizables stateless.
7. **`live.md`** — componentes stateful (LiveView).
8. **`auth.md`** — sesiones, CSRF, CSP, password, permissions.
9. **`http.md`** — clientes HTTP autenticados con interceptors.
10. **`engine.md`** — el corazón del hot-mount de módulos.
11. **`apps.md`** — `AppConfig`, `ModuleConfig`, registries, services.
12. **`discovery.md`** — escáner del filesystem.
13. **`migrations.md`** — Alembic per-module.
14. **`middleware.md`** — los 14 middlewares + stack builder.
15. **`management.md`** — la CLI `hf`.
16. **`dev.md`** — hot-reload watcher.
17. **`utils.md`** — observabilidad (logs, metrics, traces).
18. **`testing.md`** — fixtures y fakes para tests.

Después de eso, ya has visto todo el árbol. Cada md es
auto-contenido — puedes saltar a uno concreto si solo te interesa
una parte.

---

## Índice por carpeta de `src/hotframe/`

| Archivo de la guía | Carpeta de src | Qué cubre |
|---|---|---|
| [bootstrap.md](internals/bootstrap.md) | `__init__.py`, `asgi.py`, `bootstrap.py` | Lazy public API, ASGI entrypoint, `create_app` + lifespan |
| [config.md](internals/config.md) | `config/` | `HotframeSettings`, async DB engine, ephemeral paths |
| [auth.md](internals/auth.md) | `auth/` | Sesión, password (bcrypt), JWT, CSRF, CSP, current_user, permissions, rate-limit, encrypt |
| [apps.md](internals/apps.md) | `apps/` | `AppConfig`, `ModuleConfig`, registries, `ModuleService` + `@action` |
| [components.md](internals/components.md) | `components/` | Componentes UI reutilizables (stateless), JinjaX-like tag |
| [db.md](internals/db.md) | `db/` | Protocolos `ISession`/`IQueryBuilder`/`IRepository`, encrypted types, singletons |
| [dev.md](internals/dev.md) | `dev/` | `ModuleWatcher` (hot-reload con watchfiles) |
| [discovery.md](internals/discovery.md) | `discovery/` | Escáner de apps/módulos, `Convention` table |
| [engine.md](internals/engine.md) | `engine/` | El orquestador `ModuleRuntime`, `ModuleLoader`, `HotMountPipeline`, `ImportManager`, S3, marketplace |
| [http.md](internals/http.md) | `http/` | `AuthenticatedClient`, interceptors (Retry/CircuitBreaker/Refresh), registry |
| [live.md](internals/live.md) | `live/` | `LiveComponent`, WebSocket runtime, morphdom, `live.js` |
| [management.md](internals/management.md) | `management/` | CLI `hf` (Typer): startproject/startapp/startmodule/runserver/migrate/shell |
| [middleware.md](internals/middleware.md) | `middleware/` | 14 middleware classes + `build_middleware_stack` |
| [migrations.md](internals/migrations.md) | `migrations/` | Per-module Alembic runner, version_table aislado |
| [models.md](internals/models.md) | `models/` | `Base`, `Model`, mixins (Hub/Timestamp/Audit/SoftDelete), `HubQuery` |
| [orm.md](internals/orm.md) | `orm/` | `atomic`, `on_commit`, ORM→EventBus bridge, `PgNotifyBridge` |
| [repository.md](internals/repository.md) | `repository/` | `BaseRepository[T]` con CRUD tipado, paginación, search |
| [signals.md](internals/signals.md) | `signals/` | `AsyncEventBus`, `HookRegistry`, typed events Pydantic |
| [templating.md](internals/templating.md) | `templating/` | Jinja2 engine + i18n + extensiones, `SlotRegistry`, filters, globals |
| [testing.md](internals/testing.md) | `testing/` | `create_test_app`, `test_db_session`, `FakeEventBus`/`FakeHookRegistry` |
| [utils.md](internals/utils.md) | `utils/` | Observability: structlog, OTEL traces+metrics, `RequestContext` |
| [views.md](internals/views.md) | `views/` | `@view` decorator, response helpers, `BroadcastHub` (SSE) |

---

## Diagrama global del flow

```
┌────────────────────────────────────────────────────────────────────┐
│ uvicorn hotframe.asgi:application                                  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ create_app(settings)                                                │
│   ├─ setup_logging                                                  │
│   ├─ setup_telemetry (skip under pytest)                            │
│   ├─ build_middleware_stack                                         │
│   ├─ broadcast_router, live_router, /health                         │
│   ├─ _auto_discover_apps  (apps/*/routes.py + api.py)              │
│   ├─ Static files (cached)                                          │
│   └─ Error handlers (401→login, 403/405→template)                  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ lifespan startup                                                    │
│   ├─ DB engine (lazy)                                               │
│   ├─ EventBus, Hooks, Slots, Components                             │
│   ├─ BroadcastHub                                                   │
│   ├─ setup_orm_events  (SA → EventBus bridge)                       │
│   ├─ HttpClientRegistry + discover_interceptors                     │
│   ├─ Templates engine (Jinja2 + JinjaX + i18n + extensions)         │
│   ├─ LiveRuntime (sessions WS)                                      │
│   ├─ ModuleRuntime (orchestrator)                                   │
│   ├─ Discover app components, mount routers/static                  │
│   ├─ boot_all_active_modules (multi-worker advisory lock)           │
│   └─ yield                                                          │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Per-request flow                                                    │
│                                                                     │
│   HTTP request                                                      │
│      │                                                              │
│      ▼                                                              │
│   Middleware stack (outermost first):                               │
│     Timeout → ErrorPage → BodyLimit → CorrelationId →               │
│     Observability → RateLimit → ModuleBoundary →                    │
│     ModuleMiddlewareManager → CSRF → Language →                     │
│     CSP → RobustSession                                             │
│      │                                                              │
│      ▼                                                              │
│   Route resolver → Handler                                          │
│      │                                                              │
│      ▼                                                              │
│   @view: auth + perms → call handler → resolve template →          │
│         render with auto context (csrf_token, csp_nonce, request)  │
│      │                                                              │
│      ▼                                                              │
│   Response (HTML/JSON/Redirect/etc.)                                │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Live runtime (in parallel — WebSocket)                              │
│                                                                     │
│   Client opens WS /ws/_live                                         │
│      │                                                              │
│      ▼                                                              │
│   LiveSession (one per connection)                                  │
│      ├─ attach: instantiate component, run on_mount, send patch    │
│      ├─ event: dispatch to @event handler, re-render, send patch   │
│      ├─ bind: setattr on state (no re-render)                      │
│      └─ detach: run on_unmount, drop instance                      │
└────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│ Module install (e.g. via hf modules install)                        │
│                                                                     │
│   ModuleRuntime.install                                             │
│      ├─ HotMountPipeline:                                           │
│      │     DOWNLOADING → VALIDATING → MIGRATING →                   │
│      │     IMPORTING → MOUNTING → STACK_REBUILD                     │
│      ├─ Each phase has a RollbackHandle (LIFO undo on failure)      │
│      ├─ ModuleLoader: importlib + app.include_router +              │
│      │     discover components + register signals/hooks/slots       │
│      └─ Emit module.installed event                                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## Conceptos clave que conviene tener claros

### 1. Apps vs Modules

- **Apps** (`apps/<name>/`): estáticas, parte del proyecto, no se
  hot-unmountan. Se descubren y montan en `_auto_discover_apps`
  durante `create_app`.
- **Modules** (`modules/<id>/`): dinámicos, se instalan/activan/
  desactivan/desinstalan en runtime. Tienen un manifest (`module.py`)
  con `MODULE_ID`, version, dependencies, hooks de ciclo de vida.

### 2. Tres registries en `app.state`

- `app.state.event_bus` — `AsyncEventBus` (pub/sub).
- `app.state.hooks` — `HookRegistry` (actions/filters WordPress style).
- `app.state.slots` — `SlotRegistry` (cross-module UI injection).
- `app.state.components` — `ComponentRegistry` (UI components).
- `app.state.module_runtime` — `ModuleRuntime` (orquestador).
- `app.state.module_registry` — `ModuleRegistry` (estado de módulos
  cargados).
- `app.state.live` — `LiveRuntime` (LiveComponent sessions).
- `app.state.http_clients` — `HttpClientRegistry`.
- `app.state.broadcast_hub` — `BroadcastHub` (SSE generic).
- `app.state.templates` — `Jinja2Templates` con auto-discovery.

### 3. Tres tipos de "pub/sub"

| Sistema | Para qué | Cuando usar |
|---|---|---|
| `AsyncEventBus` | Eventos in-process Python ↔ Python | Reaccionar a save/delete, eventos de negocio |
| `HookRegistry` | Extension points específicos | Permitir a módulos modificar valores o reaccionar a flow |
| `BroadcastHub` | Push a clientes browser | SSE/WS de log streams, notificaciones |
| `LiveComponent` events | Click/submit en UI reactivo | Estado server-side por componente |

### 4. Persistencia: capas

```
Pydantic (settings, schemas, events)
     │
     ▼
HotframeSettings → Settings management
     │
     ▼
SQLAlchemy 2.0 (declarative_base, mapped_column)
     │
     ▼
Base / Model / Mixins (UUID PK, timestamps, hub_id)
     │
     ▼
HubQuery (chainable, auto hub_id + soft-delete filter)
     │
     ▼
BaseRepository (CRUD tipado con paginación)
     │
     ▼
Handler usa `db: DbSession` (typed as ISession)
```

### 5. Lifecycle de un módulo

```
        ┌─────────────────┐
        │  not installed  │
        └────────┬────────┘
                 │ install
                 ▼
        ┌─────────────────┐
        │   installing    │   <- DB row created, code unpacked
        └────────┬────────┘
                 │ migrate + on_install
                 ▼
        ┌─────────────────┐
        │     active      │   <- routes mounted, events subscribed
        └────────┬────────┘
                 │ deactivate (or boot)
                 ▼
        ┌─────────────────┐
        │    disabled     │   <- code on disk, DB row exists, NOT loaded
        └────────┬────────┘
                 │ activate
                 ▼
        ┌─────────────────┐
        │     active      │
        └────────┬────────┘
                 │ uninstall (only if no dependents)
                 ▼
        ┌─────────────────┐
        │  not installed  │   <- DB row deleted, code optionally kept
        └─────────────────┘
                 ▲
                 │ error
        ┌────────┴────────┐
        │      error      │   <- DB row exists with error_message
        └─────────────────┘
```

---

## Referencias rápidas

### Comandos `hf`

```bash
hf startproject <name>
hf startapp <name>
hf startmodule <name> [--api-only] [--system]
hf modules list
hf modules install|update|activate|deactivate|uninstall <source>
hf runserver
hf migrate
hf makemigrations
hf shell [--plain] [--no-startup]
hf version
```

### Settings esenciales

```python
DATABASE_URL = "postgresql+asyncpg://..."
SECRET_KEY = "<64-char>"
SECRETS_KEY = "<32-byte Fernet base64>"  # required if not local
DEBUG = True | False
DEPLOYMENT_MODE = "local" | "web"
APP_TITLE = "..."
AUTH_USER_MODEL = "apps.accounts.models.User"
MODULES_DIR = "./modules"
MODULE_MARKETPLACE_URL = "https://..."
HTTP_INTERCEPTOR_PATHS = ["./apps/integrations/interceptors"]
MIDDLEWARE = [...]   # 12 middlewares default
```

### API pública (61 símbolos)

Importables desde `hotframe`:

```python
from hotframe import (
    create_app,
    HotframeSettings, get_settings,
    AppConfig, ModuleConfig,
    Base, Model, HubBaseModel, TimeStampedModel, ActiveModel,
    HubMixin, TimestampMixin, AuditMixin, SoftDeleteMixin,
    HubQuery,
    BaseRepository,
    ISession, IQueryBuilder, IRepository,
    AsyncEventBus, HookRegistry,
    BaseEvent, register_event,
    setup_orm_events,
    view, htmx_view, is_reactive_request, is_htmx_request,
    reactive_redirect, reactive_refresh, reactive_trigger, reactive_message,
    add_message, sse_stream, BroadcastHub,
    SlotRegistry,
    Component, ComponentEntry, ComponentRegistry,
    LiveComponent, LiveSession, LiveRuntime, event,
    DbSession, CurrentUser, OptionalUser,
    EventBus, Hooks, Slots,
    get_db, get_current_user,
    get_session_user_id, hash_password, verify_password,
    has_permission, require_permission,
    ModuleService, action,
    ModuleStateDB, HotMountPipeline, ImportManager, MarketplaceClient,
    get_engine, get_session_factory,
    AuthenticatedClient, HttpClientRegistry,
    BearerAuth, ApiKeyAuth, QueryApiKeyAuth, BasicAuth, HmacAuth, CustomAuth, NoAuth,
    Interceptor, InterceptorBase, CallNext,
    RetryInterceptor, CircuitBreakerInterceptor, RefreshInterceptor,
    exponential_backoff, discover_interceptors,
)
```

---

## Próximos pasos

- Si quieres **revisar un tema con preguntas**: ver `CHECKPOINTS.md`.
- Si quieres **construir tu primer proyecto**: `hf startproject .`
  y mira `apps/` y `settings.py` generados.
- Si quieres **publicar un módulo**: lee `engine.md` (la sección
  "Lifecycle de un módulo") y `apps.md` (sección
  "ModuleConfig manifest").
