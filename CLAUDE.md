# CLAUDE.md — Hotframe Framework

Hotframe is a modular Python web framework with hot-mount dynamic modules.
FastAPI + SQLAlchemy + Jinja2 + HTMX + Alpine.js under a Django-like API.

**Repo:** https://github.com/ERPlora/hotframe
**License:** Apache 2.0
**Python:** 3.12+
**Source:** `src/hotframe/`

---

## DO NOT DUPLICATE — What Already Exists

Before implementing anything, check if hotframe already provides it:

| Need | Already exists | Where |
|---|---|---|
| CSRF protection | CSRFMiddleware + auto-inject in templates | `auth/csrf.py`, `templating/engine.py` |
| Rate limiting | APIRateLimitMiddleware (API, HTMX, auth buckets) | `middleware/rate_limit.py` |
| Session (signed cookie) | SessionMiddleware | `middleware/session.py` |
| CSP headers | CSPMiddleware + build_csp_header | `middleware/csp.py`, `auth/csp.py` |
| HTMX detection | HtmxMiddleware + HtmxDetails | `middleware/htmx.py` |
| Flash messages | add_message + HtmxMessagesMiddleware | `middleware/htmx_messages.py` |
| Password hashing | hash_password, verify_password (bcrypt) | `auth/auth.py` |
| JWT | create_jwt, verify_jwt | `auth/jwt.py` |
| Permissions | has_permission (fnmatch), require_permission | `auth/permissions.py` |
| User resolution | get_current_user (from AUTH_USER_MODEL setting) | `auth/current_user.py` |
| DB session | get_db, DbSession (async SQLAlchemy) | `auth/current_user.py` |
| Encrypted fields | EncryptedString, EncryptedText (Fernet) | `db/types.py` |
| Singleton model | SingletonMixin (one row per tenant) | `db/singletons.py` |
| Query builder | HubQuery (chainable, auto hub_id filter) | `models/queryset.py` |
| CRUD repository | BaseRepository (list, get, create, update, delete) | `repository/base.py` |
| Event bus | AsyncEventBus (subscribe, emit, wildcard, priority) | `signals/dispatcher.py` |
| Hook system | HookRegistry (add_action, add_filter, do_action, apply_filters) | `signals/hooks.py` |
| Typed events | BaseEvent + @register_event (Pydantic) | `signals/types.py`, `signals/catalog.py` |
| ORM events | setup_orm_events (pre/post save/delete auto-emitted) | `orm/events.py` |
| Transactions | atomic() context manager | `orm/transactions.py` |
| PG LISTEN/NOTIFY | PgNotifyBridge (optional, needs asyncpg) | `orm/listeners.py` |
| Module install | ModuleManager (install/activate/deactivate/uninstall) | `engine/manager.py` |
| Module hot-mount | HotMountPipeline, ImportManager | `engine/pipeline.py`, `engine/import_manager.py` |
| Module runtime | ModuleRuntime (full lifecycle orchestrator) | `engine/module_runtime.py` |
| Module state DB | ModuleStateDB (CRUD on module table) | `engine/state.py` |
| Dependencies | DependencyManager (topological sort, version checks) | `engine/dependency.py` |
| S3 source | S3ModuleSource (download, cache, verify) | `engine/s3_source.py` |
| Template engine | auto-discovery of apps/*/templates/ + modules | `templating/engine.py` |
| HTMX view decorator | @htmx_view (auth, perms, full/partial render) | `views/responses.py` |
| Turbo Streams | TurboStream + StreamResponse (OOB swaps) | `views/streams.py` |
| SSE streaming | sse_stream + BroadcastHub | `views/responses.py`, `views/broadcast.py` |
| HTMX helpers | hx_get, hx_post, hx_delete, etc. (Jinja globals) | `templating/htmx_helpers.py` |
| Alpine helpers | alpine_data, alpine_show, alpine_cloak | `templating/alpine_helpers.py` |
| Frame tag | {% frame "id" src="/url" lazy=true %} | `templating/frame_extension.py` |
| Slots (cross-module UI) | SlotRegistry (register, get_entries) | `templating/slots.py` |
| Icons | render_icon (Iconify, 6 icon sets) | `templating/extensions.py` |
| Filters | currency, dateformat, timesince, truncatewords, slugify | `templating/extensions.py` |
| Form rendering | FormRenderer (Pydantic → HTML) | `forms/rendering.py` |
| CLI | hf startproject/startapp/startmodule/modules/runserver/migrate | `management/cli.py` |
| Dev autoreload | ModuleWatcher (filesystem watcher) | `dev/autoreload.py` |
| Migrations | ModuleMigrationRunner, MultiNamespaceRunner | `migrations/runner.py` |
| Testing | create_test_app, FakeEventBus, FakeHookRegistry | `testing/__init__.py` |
| Observability | setup_logging, setup_telemetry (OTEL) | `utils/observability_*.py` |

---

## Architecture

```
hotframe/
  apps/          ← AppConfig, ModuleConfig, registry, service_facade
  auth/          ← session, password, JWT, CSRF, CSP, permissions, user resolution
  config/        ← settings (Pydantic), database (SQLAlchemy engine), paths
  db/            ← singletons, encrypted types
  dev/           ← autoreload watcher
  discovery/     ← scanner, kernel module bootstrap
  engine/        ← ModuleManager, ModuleRuntime, pipeline, import_manager, state, S3
  forms/         ← FormRenderer
  management/    ← CLI (Typer)
  middleware/    ← 14 middleware classes + stack builder
  migrations/    ← Alembic runner (single + multi-namespace)
  models/        ← Base, mixins, HubQuery
  orm/           ← transactions, ORM→EventBus bridge, PG LISTEN/NOTIFY
  repository/    ← BaseRepository (typed CRUD)
  signals/       ← AsyncEventBus, HookRegistry, typed events
  templating/    ← Jinja2 engine, HTMX/Alpine helpers, slots, frames, icons
  testing/       ← test utilities + fakes
  utils/         ← observability (logging, metrics, telemetry)
  views/         ← @htmx_view, TurboStream, SSE, BroadcastHub
```

---

## Public API (53 symbols)

All importable from `from hotframe import X`:

| Symbol | Module |
|---|---|
| create_app | bootstrap |
| HotframeSettings, get_settings | config.settings |
| AppConfig, ModuleConfig | apps.config |
| Base, HubBaseModel, TimeStampedModel, ActiveModel | models.base |
| HubMixin, TimestampMixin, AuditMixin, SoftDeleteMixin | models.mixins |
| HubQuery | models.queryset |
| BaseRepository | repository.base |
| AsyncEventBus | signals.dispatcher |
| HookRegistry | signals.hooks |
| BaseEvent, register_event | signals.types |
| setup_orm_events | orm.events |
| htmx_view, is_htmx_request | views.responses |
| htmx_redirect, htmx_refresh, htmx_trigger | views.responses |
| add_message, sse_stream | views.responses |
| TurboStream, StreamResponse | views.streams |
| BroadcastHub | views.broadcast |
| SlotRegistry | templating.slots |
| get_session_user_id, hash_password, verify_password | auth.auth |
| has_permission, require_permission | auth.permissions |
| DbSession, CurrentUser, OptionalUser | auth.current_user |
| EventBus, Hooks, Slots | auth.current_user |
| get_db, get_current_user | auth.current_user |
| ModuleService, action | apps.service_facade |
| ModuleStateDB | engine.state |
| HotMountPipeline | engine.pipeline |
| ImportManager | engine.import_manager |
| FormRenderer | forms.rendering |
| get_engine, get_session_factory | config.database |

---

## Settings (HotframeSettings)

Projects subclass `HotframeSettings` and set their own `env_prefix`.

### Core
| Field | Type | Default |
|---|---|---|
| DATABASE_URL | str | sqlite+aiosqlite:///./app.db |
| SECRET_KEY | str | auto-generated |
| DEBUG | bool | True |
| DEPLOYMENT_MODE | str | "local" |
| APP_TITLE | str | "Hotframe App" |
| LOG_LEVEL | str | "INFO" |

### Modules
| Field | Type | Default |
|---|---|---|
| MODULES_DIR | Path | ./modules |
| MODULE_SOURCE | str | "filesystem" |
| MODULE_MARKETPLACE_URL | str | "" |
| KERNEL_MODULE_NAMES | list[str] | [] |
| MODULE_STATE_MODEL | str | "" |

### Auth
| Field | Type | Default |
|---|---|---|
| AUTH_USER_MODEL | str | "" |
| AUTH_LOGIN_URL | str | "/login" |
| PERMISSION_RESOLVER | str | "" |

### Middleware
| Field | Type | Default |
|---|---|---|
| MIDDLEWARE | list[str] | 12 middleware classes |
| CSRF_EXEMPT_PREFIXES | list[str] | ["/api/", "/health", "/static/"] |
| RATE_LIMIT_API | int | 120 |
| SESSION_COOKIE_NAME | str | "session" |

### Extension Points
| Field | Type | Default |
|---|---|---|
| GLOBAL_CONTEXT_HOOK | str | "" |
| CSP_EXTRA_SCRIPT_SRC | list[str] | [] |
| CSP_EXTRA_CONNECT_SRC | list[str] | [] |
| PROXY_FIX_ENABLED | bool | False |

---

## HTMX Layer (Turbo/Livewire equivalent)

This is hotframe's differentiator — a complete server-driven UI layer.

### @htmx_view decorator

```python
@router.get("/m/todo/list/")
@htmx_view(module_id="todo", view_id="list", permissions="todo.view")
async def todo_list(request):
    return {"todos": await get_todos(), "page_title": "Todos"}
```

Handles: auth check, permission check, HTMX vs direct detection, template auto-discovery, full/partial render, OOB tabbar swap, page title via HX-Trigger.

Template auto-discovery patterns:
- Partial: `{module}/partials/{view}.html`
- Full: `{module}/pages/{view}.html`

### TurboStream (multi-fragment responses)

```python
return StreamResponse(
    TurboStream.append("#todo-list", html=rendered_item),
    TurboStream.text("#todo-count", str(count)),
    TurboStream.remove("#empty-state"),
)
```

Actions: `append`, `prepend`, `replace`, `update`, `remove`, `before`, `after`, `morph`, `text`

### Broadcasting (real-time)

```python
# Publish
hub = get_broadcast_hub(request)
await hub.publish("todos", TurboStream.append("#list", html=item_html).to_oob_html())

# Subscribe in template
{{ stream_from("todos") }}
```

SSE endpoint: `GET /stream/{topic}` | Multiplexed: `GET /stream/_mux?topics=a,b,c` | WebSocket: `/ws/stream/{topic}`

### Jinja HTMX Helpers

```html
<button {{ hx_delete(url_for('todo.delete', id=todo.id), confirm="Sure?") }}>
<input {{ hx_get(url_for('search'), trigger="input changed delay:300ms", target="#results") }}>
<form {{ hx_post(url_for('todo.create'), target="#list", swap="beforeend") }}>
```

All: `hx_get`, `hx_post`, `hx_put`, `hx_patch`, `hx_delete`, `hx_trigger`, `hx_indicator`, `hx_vals`

### Jinja Alpine Helpers

```html
<div {{ alpine_data({"count": 0, "open": false}) }}>
<div {{ alpine_show("count > 0") }} {{ alpine_cloak() }}>
```

### {% frame %} tag (Turbo Frames equivalent)

```html
{% frame "comments" src="/api/comments" lazy=true %}
    <div class="skeleton"></div>
{% endframe %}
```

Params: `src`, `lazy`, `swap`, `trigger`, `target`, `push_url`

### SlotRegistry (cross-module UI injection)

```python
# Module registers a slot contribution
slots.register("dashboard_widgets", "loyalty/partials/widget.html", module_id="loyalty", priority=5)

# Template renders slot
{% for entry, ctx in slot_entries %}
    {% include entry.template with context %}
{% endfor %}
```

### Flash Messages

```python
add_message(request, "success", "Item created")
# HTMX: injected as HX-Trigger: {"showMessages": [...]}
# Non-HTMX: stored in session flash for next page
```

### Icons (Iconify)

```html
{{ icon("home-outline") }}              {# Ionicons #}
{{ icon("material:search", size=20) }}  {# Material Design #}
{{ icon("hero:check") }}                {# Heroicons #}
```

Prefixes: ion (default), material→mdi, hero→heroicons, tabler, lucide, fa→fa-solid

### Template Auto-injection

Every `TemplateResponse` automatically gets:
- `csrf_token` — raw token string
- `csrf_input()` — callable returning hidden input
- `csp_nonce` — CSP nonce

Base template pattern:
```html
<body hx-boost="true" hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'>
```

### Filters

| Filter | Example | Output |
|---|---|---|
| currency | `{{ 9.99 \| currency("EUR") }}` | 9,99 EUR |
| dateformat | `{{ dt \| dateformat("d/m/Y H:i") }}` | 17/04/2026 14:30 |
| timesince | `{{ dt \| timesince }}` | 3 minutes |
| truncatewords | `{{ text \| truncatewords(10) }}` | First ten words... |
| slugify | `{{ "Hello World" \| slugify }}` | hello-world |

---

## ModuleManager API

```python
from hotframe.engine.manager import ModuleManager

manager = ModuleManager(app=request.app)  # web
manager = ModuleManager()                  # CLI

modules = await manager.list()                          # list all
result = await manager.install("demo")                  # from modules/
result = await manager.install("/tmp/demo.zip")         # from zip
result = await manager.install("https://example.com/d.zip")  # from URL
result = await manager.activate("demo")                 # disabled → active
result = await manager.deactivate("demo")               # active → disabled
result = await manager.uninstall("demo", keep_data=True)  # remove
```

Install source resolution:
1. URL → download zip → extract → install
2. .zip path → extract → install
3. Name + MODULE_MARKETPLACE_URL → download from marketplace
4. Name → look in modules/ directory

---

## CLI Commands

```bash
hf startproject <name>          # create project (use . for current dir)
hf startapp <name>              # create app in apps/
hf startmodule <name>           # create module (--api-only, --system)
hf modules list                 # show all modules + status
hf modules install <source>     # install (name, .zip, URL)
hf modules activate <name>      # disabled → active
hf modules deactivate <name>    # active → disabled
hf modules uninstall <name>     # remove (--keep-data, --yes)
hf runserver                    # uvicorn with reload
hf migrate                      # alembic upgrade head
hf makemigrations               # alembic revision --autogenerate
hf version                      # show version
```

---

## Bootstrap — What create_app Does

1. Setup logging + OpenTelemetry
2. Create FastAPI app
3. Build middleware stack from settings.MIDDLEWARE
4. Optional ProxyFixMiddleware
5. Include broadcast_router (SSE)
6. Add /health endpoint
7. Register error handlers (401→redirect, 403/405→template)

### Lifespan (startup)
1. Initialize async DB engine
2. Create AsyncEventBus, HookRegistry, SlotRegistry, BroadcastHub
3. Setup ORM→EventBus bridge (auto-emit on model save/delete)
4. Store all on app.state
5. Create Jinja2 template engine (auto-discovers apps/*/templates/)
6. Create ModuleRuntime
7. Yield (app is live)

### Shutdown
1. ModuleRuntime.shutdown()
2. Dispose DB engine

---

## Testing Utilities

```python
from hotframe.testing import create_test_app, test_db_session, FakeEventBus

# Create test app (SQLite in-memory, CSRF disabled, rate limits maxed)
app = create_test_app()

# DB session with auto-rollback
async for session in test_db_session():
    ...

# Fake event bus for assertions
bus = FakeEventBus()
await bus.emit("test.event", data={"key": "value"})
assert bus.events == [("test.event", {"key": "value"})]
```

---

## Key Principles

1. The dev imports everything from `hotframe` — one public API
2. Each app/module is self-contained (templates, static, migrations, tests inside)
3. Settings is the single interface between app and framework
4. Modules are dynamic (install/uninstall at runtime)
5. Apps are static (discovered at boot)
6. HTMX + Alpine.js for frontend — no React, no Vue, no build step
7. Server-driven UI — HTML over the wire, not JSON APIs
