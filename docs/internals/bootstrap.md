# bootstrap.md — Top-level package, ASGI entrypoint, application factory

> **Carpeta cubierta:** `src/hotframe/` (raíz). Tres archivos:
> `__init__.py`, `asgi.py`, `bootstrap.py`.
> Estos son los archivos que se importan primero cuando alguien hace
> `import hotframe` o cuando uvicorn arranca `hotframe.asgi:application`.
> Conviene entenderlos antes que los subsistemas porque dictan **cuándo**
> y **en qué orden** se inicializa todo lo demás.

---

## 1. `__init__.py` — fachada pública con lazy imports

### 1.1 ¿Qué hace?

Es **el único punto de entrada público** del framework. Define:

1. `__version__ = "1.0.0"` — string usado por `hf version`, telemetría, y
   los headers `Server:` que pueda emitir el deployment.
2. Un dict `_LAZY_IMPORTS: dict[str, str]` con ~80 nombres exportados,
   cada uno mapeado a su módulo real.
3. Un `__getattr__(name)` a nivel de módulo (PEP 562) que resuelve el
   import en el **primer acceso** y lo cachea en `sys.modules`.
4. `__all__ = [*_LAZY_IMPORTS.keys(), "__version__"]` para que
   `from hotframe import *` exponga la API completa.

### 1.2 ¿Por qué lazy?

Si `hotframe/__init__.py` importara los 80 símbolos al cargar:

- `import hotframe` arrastraría toda la dependencia transitiva
  (SQLAlchemy, FastAPI, Pydantic, jinjax, datastar — etc.) **antes** de
  que el usuario haya tocado settings.
- Ciclos de import: `hotframe.bootstrap` necesita `hotframe.config`,
  que necesita `hotframe.utils.observability_logging`. Si todo se carga
  eagerly desde `__init__.py`, cualquier nuevo símbolo puede romper el
  orden.
- Tests lentos: cada test que hace `import hotframe` paga el coste
  completo aunque solo use `Base`.

Con `__getattr__`, `import hotframe` toca solo el dict y `from hotframe
import Base` carga `hotframe.models.base` la primera vez y nada más.

### 1.3 Mapa rápido de qué expone cada bloque

```
Bootstrap        -> create_app
Settings         -> HotframeSettings, get_settings
Apps             -> AppConfig, ModuleConfig
Models           -> Base, Model, HubBaseModel (alias), TimeStampedModel,
                    ActiveModel, HubMixin, TimestampMixin, AuditMixin,
                    SoftDeleteMixin, HubQuery
Repository       -> BaseRepository
DB Protocols     -> ISession, IQueryBuilder, IRepository,
                    IExecuteResult, IScalarResult
Signals          -> AsyncEventBus, HookRegistry, BaseEvent, register_event
ORM              -> setup_orm_events
Views            -> view, htmx_view (alias), is_reactive_request,
                    is_htmx_request, reactive_redirect/refresh/trigger/message,
                    htmx_redirect/refresh/trigger (aliases),
                    add_message, sse_stream, BroadcastHub
Templating       -> SlotRegistry
Components       -> Component, ComponentRegistry, ComponentEntry
Auth helpers     -> get_session_user_id, hash_password, verify_password,
                    has_permission, require_permission
DI dependencies  -> DbSession, CurrentUser, OptionalUser,
                    EventBus, Hooks, Slots, get_db, get_current_user
Services         -> ModuleService, action
Engine           -> ModuleStateDB, HotMountPipeline, ImportManager,
                    MarketplaceClient
Config           -> get_engine, get_session_factory
HTTP             -> AuthenticatedClient, HttpClientRegistry, Auth,
                    BearerAuth, ApiKeyAuth, QueryApiKeyAuth, BasicAuth,
                    HmacAuth, CustomAuth, NoAuth,
                    Interceptor, InterceptorBase, CallNext,
                    RetryInterceptor, CircuitBreakerInterceptor,
                    RefreshInterceptor, exponential_backoff,
                    discover_interceptors
Live runtime     -> LiveComponent, LiveSession, LiveRuntime, event
```

### 1.4 Decisiones estables

- **Aliases preservados.** `HubBaseModel` apunta al mismo objeto que
  `Model` (que a su vez es `Base` con conveniencias). Evita romper
  proyectos que importaban el nombre viejo en versiones < 1.0.
- **`htmx_*` como alias de `reactive_*`.** El framework abandonó HTMX
  como motor de reactividad y migró a WebSocket+morphdom (`live/`),
  pero la API conserva los nombres `htmx_redirect`, `htmx_view`,
  `is_htmx_request`, etc. para que módulos viejos sigan funcionando
  al ser importados — lo único que cambia es el comportamiento (ahora
  son redirects HTTP normales, no responses con `HX-Redirect`).
- **No se exporta nada de `engine.pipeline.HotMountState`, ni de
  `engine.import_manager`.** Internas — pueden cambiar entre versiones.

### 1.5 Cómo añadir un símbolo nuevo a la API pública

```python
# Antes
_LAZY_IMPORTS: dict[str, str] = {
    ...
}

# Después
_LAZY_IMPORTS: dict[str, str] = {
    ...
    "MyNewThing": "hotframe.subsystem.module",
}
```

`__all__` se reconstruye automáticamente. No olvides actualizar
`hotframe/CLAUDE.md` (sección "Public API") para que los agentes
sepan que existe.

---

## 2. `asgi.py` — punto de entrada para uvicorn

### 2.1 Contenido completo

```python
from hotframe.bootstrap import create_app
application = create_app()
```

Tres líneas. Hay un docstring explicando que el rewrite de
`X-Forwarded-*` lo hace uvicorn con `--proxy-headers`, y que el
hotframe-específico (`ProxyFixMiddleware`, slug ECS) se activa con
`PROXY_FIX_ENABLED`.

### 2.2 ¿Por qué existe un `asgi.py` aparte?

- **Convención de despliegue.** uvicorn/gunicorn/hypercorn esperan un
  módulo con un atributo a nivel de módulo que sea la app. La
  convención más estable es `<package>.asgi:application`.
- **Separación de responsabilidad.** `create_app()` puede recibir
  settings explícitos en tests (`create_app(test_settings)`); aquí no
  los pasamos para que produzca uno cargado del entorno. Si un proyecto
  necesita configuración custom en producción, escribe su propio
  `myproject/asgi.py` que llame a `create_app(MySettings())`.

### 2.3 Cuándo NO usarlo

- Tests: `from hotframe.testing import create_test_app` (no toca
  variables de entorno reales, fija SQLite in-memory, deshabilita CSRF
  y rate-limits).
- Scripts CLI: `hf shell`, `hf migrate`, etc. No arrancan ASGI; cargan
  settings y abren conexiones DB, pero no hay servidor HTTP.

---

## 3. `bootstrap.py` — fábrica `create_app` y lifespan

### 3.1 Estructura del archivo

```
bootstrap.py
├── lifespan(app)               # async context manager con startup/shutdown
├── create_app(settings=None)   # fábrica síncrona
└── _auto_discover_apps(app)    # helper de create_app
```

`create_app` devuelve una `FastAPI` lista para servir. El lifespan
corre cuando uvicorn la arranca (`startup`) y cuando se apaga
(`shutdown`).

### 3.2 `create_app(settings=None)` — fase **síncrona**

Esta función es **síncrona** porque uvicorn la llama antes de levantar
el event loop. Todo lo que dependa de I/O asíncrona (DB, lectura de
state inicial de módulos) va al lifespan.

Pasos en orden:

1. **Resolver settings.** Si el caller pasa `settings`, lo registra como
   singleton vía `set_settings`. Después llama a `get_settings()` para
   leer el singleton.
2. **Configurar logging y telemetría.** Decide JSON vs console basado
   en `LOG_FORMAT` y `is_production`. Telemetría OTEL se salta bajo
   pytest (causaba errores "I/O operation on closed file" porque el
   `BatchSpanProcessor` escribe en stderr después de que pytest cierre
   su capture stream).
3. **Crear `FastAPI(...)`** con docs en `/api/docs`, `/api/redoc`,
   `/api/openapi.json` solo cuando `DEBUG=True`.
4. **Construir el middleware stack** llamando a
   `build_middleware_stack(app, settings)` (ver `middleware.md`).
5. **CORSMiddleware opcional** — solo se monta si `CORS_ORIGINS` no
   está vacío. Es la primera middleware que se añade después del stack
   normal porque CORS necesita ver la request antes que cualquier otro.
6. **ProxyFixMiddleware opcional** — si `PROXY_FIX_ENABLED`, montaje
   con slug + dominio base + región AWS. Hace la reescritura específica
   ECS (`hub-<slug>-<region>.elb.amazonaws.com` → host público).
7. **Rate limiter singleton.** Crea `PINRateLimiter()` y lo guarda en
   `app.state.rate_limiter`. Se usa para login con PIN.
8. **`broadcast_router`** (SSE generic). Endpoint `/stream/{topic}` y
   `/stream/_mux?topics=a,b,c`.
9. **`live_router`** (`/ws/_live`). El endpoint WebSocket para los
   `LiveComponent`.
10. **`/health`** — responde `{"status": "ok"}`.
11. **`_auto_discover_apps(app)`** — escanea `apps/` y monta `routes.py`
    + `api.py` (ver §3.4).
12. **Static files.** Monta `STATIC_ROOT` en `STATIC_URL` con la
    subclase `CachedStaticFiles` (Cache-Control: max-age=31536000,
    immutable).
13. **Hotframe-shipped static** — monta `hotframe/live/static/` en
    `/static/hotframe/`. Sirve `live.js` y `morphdom.min.js`.
14. **Media files** — solo en `MEDIA_STORAGE=local` y `DEBUG=True`.
    En prod, S3 + CloudFront.
15. **Error handlers** para 401 (redirect a `AUTH_LOGIN_URL`, JSON si
    `/api/`), 403 (template `errors/403.html`), 405 (template
    `errors/405.html`).

Nota: el orden importa. `_auto_discover_apps` debe correr **después**
de los routers internos (`broadcast_router`, `live_router`) porque
FastAPI resuelve rutas por orden de registro y un app de usuario que
declarara `/health` lo sobrescribiría — algo deseable, así el usuario
puede customizar el health check si quiere.

### 3.3 `lifespan(app)` — fase **asíncrona**

Cuando uvicorn arranca y entra al event loop, ejecuta el `__aenter__`
del `lifespan`:

1. **DB engine.** `get_engine()` devuelve el `AsyncEngine` singleton
   (ver `config.md`).
2. **Core registries.** Crea `AsyncEventBus`, `HookRegistry`,
   `SlotRegistry`, `ComponentRegistry`. Son objetos puramente Python,
   sin conexión a nada externo.
3. **`BroadcastHub`.** Hub de SSE/WS para fan-out de eventos custom
   (logs en vivo, notificaciones).
4. **`setup_orm_events(event_bus, base=Base)`.** Conecta los hooks de
   SQLAlchemy (`after_insert`, `after_update`, `after_delete`) al event
   bus, de modo que cualquier `INSERT/UPDATE/DELETE` emite
   `<table>.created/updated/deleted` automáticamente.
5. **Stash en `app.state`** — `event_bus`, `hooks`, `slots`,
   `components`. Las dependencias de FastAPI los consultan vía
   `request.app.state.X`.
6. **Settings.** Nuevamente vía `get_settings()`. Se cachean.
7. **`HttpClientRegistry`.**
   1. Lee `HTTP_INTERCEPTOR_PATHS` de settings.
   2. Llama a `discover_interceptors(paths)` — escanea cada path,
      importa cada `.py`, recolecta atributos de módulo que cumplan
      el protocolo `Interceptor`.
   3. Crea `HttpClientRegistry(ambient_interceptors=discovered)` y
      lo guarda en `app.state.http_clients`.
   4. La lista cruda queda en `app.state.http_interceptors` por si
      alguien quiere inspeccionarla.
8. **`create_template_engine(...)`.** Construye el `Jinja2Templates`
   con autodiscovery de `apps/*/templates/`, módulos, JinjaX,
   extensiones (frame, live, slots), filters (currency, dateformat,
   slugify), globals (csrf, csp_nonce, render_component).
9. **`app.state.templates.env.globals["_hotframe_components"] = components`** — expone el registry
   al motor de plantillas para que `{% component %}` y `{% live %}`
   resuelvan entries sin acceder a `app.state` durante el render.
10. **`LiveRuntime(components, env)`.** Crea el runtime de
    `LiveComponent` (sesiones WS, cache de templates, dispatch).
    Guardado en `app.state.live`.
11. **`ModuleRuntime`.** Constructor recibe `(app, settings, event_bus,
    hooks, slots, components=...)`. Es el orquestador de los módulos
    dinámicos. `app.state.module_runtime` y
    `app.state.module_registry` quedan apuntando a él y a su registry
    interno.
12. **Component discovery (`apps/`).** Escanea `apps/*/components/`,
    los registra en `components`, monta sus routers
    (`/_components/<name>/`) y su `static/` (`/_components/<name>/static/`).
13. **`runtime.boot_all_active_modules(boot_session)`.** Lee la tabla
    `module` con `status='active'`, instala el código de cada uno en
    `sys.modules`, monta routers, registra slots/hooks/components.
    Falla → log y sigue (un módulo roto no impide arrancar).
14. **Log y `yield`.** El framework está vivo.

Cuando uvicorn apaga (Ctrl+C, SIGTERM, etc.), corre el bloque después
del `yield`:

1. `module_runtime.shutdown()` — pasa cada módulo activo por
   `on_shutdown` y libera referencias.
2. `live_runtime.shutdown()` — drena cada `LiveSession`, ejecuta
   `on_unmount` en cada componente y vacía dicts.
3. `http_clients.aclose_all()` — cierra cada cliente httpx
   registrado (clientes que el usuario haya olvidado cerrar).
4. `dispose_engine()` — cierra el pool SQLAlchemy.

### 3.4 `_auto_discover_apps(app)` — escáner de `apps/`

Síncrono (corre dentro de `create_app`). Pasos:

1. Si no existe `./apps`, retorna.
2. Lista directorios bajo `apps/` que no empiezan por `.` o `_` y que
   tienen `__init__.py`. Los ordena alfabéticamente.
3. Para cada `name`:
   - Intenta importar `apps.<name>.routes` y, si tiene `router`,
     lo registra con `app.include_router(router)`.
   - Intenta importar `apps.<name>.api` y, si tiene `api_router`,
     lo registra con `app.include_router(api_router)`.
   - Intenta importar `apps.<name>.app` y busca cualquier subclase
     de `AppConfig` cuyo atributo `name` coincida con `name`.
     Si la encuentra y tiene `ready()`, la llama.
     - Si `ready` es `async def`, la corre en un loop transitorio
       (`asyncio.run`) — porque seguimos en fase síncrona.
     - Si es `def`, la llama directamente.
4. Para cada path en `EXTRA_ROUTERS`, hace `module_path,
   attr_name = path.rsplit('.', 1)`, importa, llama a
   `app.include_router(getattr(mod, attr_name))`.
5. Logea `Auto-discovered N app(s): a, b, c`.

### 3.5 Decisiones notables

- **`CachedStaticFiles`** subclassea `StaticFiles` de Starlette y añade
  `Cache-Control: public, max-age=31536000, immutable` a TODA respuesta.
  Esto vale para assets fingerprinted (`bundle.abc123.js`); para HTML
  no aplica porque el HTML no se sirve como static.
- **Telemetría OTEL desactivada bajo pytest.** Detecta `"pytest" in
  sys.modules` y se salta `setup_telemetry`. El motivo: el
  `BatchSpanProcessor` con consola exporter spawnea un thread que
  escribe stderr después de que pytest cierre su captura, generando
  tracebacks "I/O operation on closed file" que rompían CI aunque los
  tests pasaran.
- **`AsyncSession` ↔ `ISession`.** En el paso 13 (boot active modules)
  hay un `# type: ignore[arg-type]` porque `AsyncSession` cumple
  estructuralmente el protocolo `ISession` pero mypy no puede verlo
  sin un cast — y no queremos colar tipos SQLAlchemy en la API pública
  de boot.
- **`/health` se registra antes que `_auto_discover_apps`** para
  asegurar que existe siempre, pero como FastAPI permite colisiones,
  un app que registre `/health` lo puede sobrescribir.

### 3.6 Errores comunes al arrancar

| Síntoma | Causa típica | Diagnóstico |
|---|---|---|
| `SECRETS_KEY is required in non-local deployments.` | `DEPLOYMENT_MODE=web` sin `SECRETS_KEY`. | Generar Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `Database engine initialized: sqlite+aiosqlite:///./app.db` en producción | Olvidaste `DATABASE_URL` en el entorno. | Settings carga `.env` y default sqlite. Configura task definition. |
| `Boot: failed to mount active modules` | Tabla `module` con un row apuntando a un código que ya no existe. | Mira el traceback completo (lo logea con `exception`). El servidor sigue arrancando porque está envuelto en try/except. |
| Templates 404 | Olvidaste poner `__init__.py` en `apps/myapp/`. | `_auto_discover_apps` solo lista directorios con `__init__.py`. |
| `Auto-discovered 0 app(s)` | `apps/` no existe o está vacío. | Crea uno con `hf startapp <name>`. |

---

## 4. Cómo se relacionan estos tres archivos

```
┌─────────────────────────────────────────────────────────────────┐
│ uvicorn hotframe.asgi:application --port 8000                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ asgi.py                                                          │
│   from hotframe.bootstrap import create_app                      │
│   application = create_app()    # SYNC                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ bootstrap.create_app(settings=None)                              │
│   1. Resolve settings (or read env)                              │
│   2. Setup logging + OTEL                                        │
│   3. FastAPI(...)                                                │
│   4. build_middleware_stack                                      │
│   5. CORS, ProxyFix (if enabled)                                 │
│   6. Rate limiter, broadcast_router, live_router, /health        │
│   7. _auto_discover_apps                                         │
│   8. Static, media                                               │
│   9. Error handlers                                              │
│   10. return FastAPI                                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ bootstrap.lifespan(app)         (called by uvicorn at startup)   │
│   1. DB engine                                                   │
│   2. EventBus, Hooks, Slots, Components, BroadcastHub            │
│   3. setup_orm_events                                            │
│   4. HttpClientRegistry + discover_interceptors                  │
│   5. Template engine                                             │
│   6. LiveRuntime                                                 │
│   7. ModuleRuntime                                               │
│   8. Component discovery (apps)                                  │
│   9. Boot active modules                                         │
│   yield                                                          │
│   10. Shutdown: module_runtime, live_runtime, http_clients, db   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Each request goes through:                                       │
│   middleware stack -> router -> handler -> response              │
│                                                                  │
│ Public API (`from hotframe import X`) is resolved by             │
│ `__init__.__getattr__` lazily on first access.                   │
└─────────────────────────────────────────────────────────────────┘
```

Si entiendes este orden, entiendes el resto del framework — todo lo
demás son subsistemas que se enchufan en alguno de estos pasos.
