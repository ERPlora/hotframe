# config.md — Settings, async DB engine, ephemeral paths

> **Carpeta cubierta:** `src/hotframe/config/`. Cuatro archivos:
> `__init__.py`, `settings.py`, `database.py`, `paths.py`.
> Este subsistema es la **única fuente de verdad de la configuración**.
> Todo el framework (auth, middleware, engine, live runtime…) lee de
> `get_settings()` o de `get_engine()` / `get_session_factory()`.

---

## 1. `__init__.py` — descripción del paquete

Solo docstring + reexports implícitos. Documenta:

- `HotframeSettings` y `get_settings()` viven en `settings.py`.
- `get_engine`, `get_session_factory`, `dispose_engine` viven en
  `database.py`.
- `paths.py` define rutas efímeras solo para caches locales (`/tmp/...`).

No hace imports al cargar — los consumidores importan rutas explícitas.
Eso evita un ciclo circular entre `bootstrap` y `config` cuando el
lazy import de `__init__.py` raíz consulta `HotframeSettings`.

---

## 2. `settings.py` — `HotframeSettings(BaseSettings)`

### 2.1 Por qué Pydantic Settings

- **Validación al arrancar.** Si `LOG_LEVEL=NOPE`, fallas en
  `HotframeSettings()` antes de tocar nada — no llegas a un crash
  intermitente cuando alguien intenta logear.
- **Tipado.** Cada campo tiene tipo. mypy puede detectar errores de
  configuración en consumidores.
- **Carga desde `.env`** con `SettingsConfigDict(env_file=".env")`,
  case-insensitive.
- **Subclasing por proyecto.** El usuario hace
  `class Settings(HotframeSettings): ...` y añade sus propios campos
  con `env_prefix="MY_APP_"`. Lo que define hotframe nunca colisiona
  con lo del usuario.

### 2.2 Lista completa de campos

Agrupados por bloque:

#### Apps
| Campo | Tipo | Default | Comentario |
|---|---|---|---|
| `EXTRA_ROUTERS` | `list[str]` | `[]` | Routers fuera de `apps/`. Dotted path al objeto `APIRouter`. |

#### Database
| Campo | Tipo | Default | Comentario |
|---|---|---|---|
| `DATABASE_URL` | `str` | `sqlite+aiosqlite:///./app.db` | URL completa con driver async (`postgresql+asyncpg://`, `sqlite+aiosqlite://`, etc.). |
| `DB_POOL_SIZE` | `int` | `10` | Tamaño base del pool (no aplica a SQLite). |
| `DB_MAX_OVERFLOW` | `int` | `20` | Conexiones extra sobre el pool (no aplica a SQLite). |
| `DB_POOL_RECYCLE` | `int` | `3600` | Cierra conexiones más viejas de N segundos. |
| `DB_POOL_TIMEOUT` | `int` | `30` | Espera N segundos por una conexión libre. |
| `DB_ECHO` | `bool` | `False` | Si `True`, SQLAlchemy logea cada SQL. Solo en dev. |
| `DB_DISABLE_PREPARED_STATEMENTS` | `bool` | `False` | Para AWS RDS Proxy / PgBouncer en transaction-mode. |
| `MAX_REQUEST_BODY` | `int` | `10 MB` | Lo aplica `BodyLimitMiddleware`. |

#### Security
| Campo | Tipo | Default | Comentario |
|---|---|---|---|
| `SECRET_KEY` | `str` | `secrets.token_urlsafe(64)` | Firma sesiones, CSRF, JWTs. |
| `SECRETS_KEY` | `str | None` | `None` | Fernet key (32 bytes b64 url-safe). Obligatorio en `DEPLOYMENT_MODE!='local'`. |
| `DEBUG` | `bool` | `True` | Activa `/api/docs`, traces, mensajes de error verbosos. |

#### Modules
| Campo | Tipo | Default |
|---|---|---|
| `MODULES_DIR` | `Path` | `./modules` |
| `MODULES_CACHE_DIR` | `Path` | `/tmp/hotframe-modules` |
| `MODULE_SOURCE` | `str` | `"filesystem"` (or `"s3"`, `"http"`) |
| `MODULE_MARKETPLACE_URL` | `str` | `""` |
| `S3_MODULES_BUCKET` | `str` | `""` |
| `AWS_REGION` | `str` | `"us-east-1"` |
| `MODULE_STATE_MODEL` | `str` | `""` |

#### Static / Media
| Campo | Tipo | Default |
|---|---|---|
| `STATIC_ROOT` | `Path` | `./static` |
| `STATIC_URL` | `str` | `/static/` |
| `MEDIA_ROOT` | `Path` | `./media` |
| `MEDIA_STORAGE` | `str` | `local` (or `s3`) |
| `MEDIA_S3_BUCKET` | `str` | `""` |
| `MEDIA_URL` | `str` | `/media/` |

#### Deployment / Locale
| Campo | Tipo | Default |
|---|---|---|
| `DEPLOYMENT_MODE` | `Literal["local", "web"]` | `local` |
| `LANGUAGE` | `str` | `en` |
| `CURRENCY` | `str` | `USD` |
| `APP_TITLE` | `str` | `Hotframe App` |

#### CORS
| Campo | Tipo | Default |
|---|---|---|
| `CORS_ORIGINS` | `list[str]` | `[]` (CORS deshabilitado) |
| `CORS_METHODS` | `list[str]` | `[GET, POST, PUT, PATCH, DELETE, OPTIONS]` |
| `CORS_HEADERS` | `list[str]` | `["*"]` |
| `CORS_CREDENTIALS` | `bool` | `True` |

#### CSP / CSRF / Session
| Campo | Tipo | Default |
|---|---|---|
| `CSP_ENFORCE` | `bool` | `False` |
| `CSP_TRUSTED_TYPES` | `bool` | `False` |
| `CSP_ALLOWED_SOURCES` | `dict[str, list[str]]` | `{script:[], style:[], connect:[], img:[], font:[]}` |
| `CSRF_EXEMPT_PREFIXES` | `list[str]` | `[/api/, /health, /static/]` |
| `SESSION_COOKIE_NAME` | `str` | `session` |
| `SESSION_MAX_AGE` | `int` | `2592000` (30 días) |

#### Rate limiting
| Campo | Tipo | Default |
|---|---|---|
| `RATE_LIMIT_API` | `int` | `120` (req/min) |
| `RATE_LIMIT_AUTH` | `int` | `60` |
| `RATE_LIMIT_AUTH_PREFIXES` | `list[str]` | `[]` |

#### Logging / Observability
| Campo | Tipo | Default |
|---|---|---|
| `LOG_LEVEL` | `str` | `INFO` |
| `LOG_FORMAT` | `Literal["console", "json"]` | `console` |
| `OTEL_SERVICE_NAME` | `str` | `hotframe` |

#### Middleware
| Campo | Tipo | Default |
|---|---|---|
| `MIDDLEWARE` | `list[str]` | 12 dotted paths (ver §2.4) |

#### Auth
| Campo | Tipo | Default |
|---|---|---|
| `AUTH_USER_MODEL` | `str` | `""` (e.g. `apps.accounts.models.User`) |
| `AUTH_LOGIN_URL` | `str` | `/login` |
| `AUTH_UNAUTHORIZED_URL` | `str` | `/unauthorized` |

#### Proxy
| Campo | Tipo | Default |
|---|---|---|
| `PROXY_FIX_ENABLED` | `bool` | `False` |
| `PROXY_SLUG` | `str` | `""` |
| `PROXY_DOMAIN_BASE` | `str` | `""` |
| `PROXY_AWS_REGION` | `str` | `""` |

#### HTTP clients
| Campo | Tipo | Default |
|---|---|---|
| `HTTP_CLIENT_EVENTS` | `bool` | `False` |
| `HTTP_INTERCEPTOR_PATHS` | `list[str]` | `[]` |

#### Hooks
| Campo | Tipo | Default |
|---|---|---|
| `GLOBAL_CONTEXT_HOOK` | `str` | `""` (dotted path a `async (request) -> dict`) |
| `PERMISSION_RESOLVER` | `str` | `""` (dotted path a `async (request, user_id) -> list[str]`) |

### 2.3 Validators

```python
@field_validator("LOG_LEVEL")
def _normalize_log_level(cls, v):
    v = v.upper()
    if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(...)
    return v
```

```python
@field_validator("MODULES_DIR", "MODULES_CACHE_DIR", mode="before")
def _resolve_path(cls, v):
    return Path(v).resolve()
```

```python
@model_validator(mode="after")
def _validate_secrets_key(self):
    if self.DEPLOYMENT_MODE != "local" and not self.SECRETS_KEY:
        raise ValueError("SECRETS_KEY is required in non-local deployments...")
    if self.SECRETS_KEY:
        decoded = base64.urlsafe_b64decode(self.SECRETS_KEY)
        if len(decoded) != 32:
            raise ValueError(...)
    return self
```

Las dos `@property` finales (`is_sqlite`, `is_production`) son helpers
sin estado para el resto del framework.

### 2.4 Lista por defecto de `MIDDLEWARE`

Importa-se "outermost first" (la primera procesa la request antes que
nadie y la response al final).

```python
MIDDLEWARE = [
    "hotframe.middleware.timeout.TimeoutMiddleware",
    "hotframe.middleware.error_pages.ErrorPageMiddleware",
    "hotframe.middleware.body_limit.BodyLimitMiddleware",
    "asgi_correlation_id.CorrelationIdMiddleware",
    "hotframe.middleware.observability.RequestObservabilityMiddleware",
    "hotframe.middleware.rate_limit.APIRateLimitMiddleware",
    "hotframe.engine.boundary.ModuleBoundaryMiddleware",
    "hotframe.middleware.module_middleware.ModuleMiddlewareManager",
    "hotframe.auth.csrf.CSRFMiddleware",
    "hotframe.middleware.language.LanguageMiddleware",
    "hotframe.middleware.csp.CSPMiddleware",
    "hotframe.middleware.session_safe.RobustSessionMiddleware",
]
```

Notas clave:

- `ModuleBoundaryMiddleware` está **fuera** de
  `ModuleMiddlewareManager` para capturar excepciones generadas por
  cualquier middleware contribuido por un módulo.
- `RobustSessionMiddleware` está al final (más cerca del handler) para
  que el cookie de sesión esté disponible en cuanto el handler corra,
  pero se firme correctamente solo si todo lo anterior tuvo éxito.
- `CSRFMiddleware` está **dentro** de `ModuleMiddlewareManager` —
  módulos pueden añadir endpoints exempt vía `CSRF_EXEMPT_PREFIXES`.

### 2.5 Singletons

```python
_settings: HotframeSettings | None = None

def get_settings() -> HotframeSettings:
    global _settings
    if _settings is None:
        _settings = HotframeSettings()
    return _settings

def set_settings(settings):  # called by create_app(settings)
    global _settings
    _settings = settings

def reset_settings():  # for tests
    global _settings
    _settings = None
```

`create_app(settings)` puede inyectar settings custom (p.ej. en tests)
porque llama a `set_settings` antes de cualquier `get_settings()`. Una
vez seteado, `get_settings()` siempre devuelve el mismo objeto.

### 2.6 Cómo extender en un proyecto

```python
# my_project/settings.py
from pathlib import Path
from pydantic_settings import SettingsConfigDict
from hotframe.config.settings import HotframeSettings


class Settings(HotframeSettings):
    model_config = SettingsConfigDict(env_prefix="MYAPP_", env_file=".env")

    # Custom fields (env vars: MYAPP_TENANT_ID, MYAPP_STRIPE_KEY)
    TENANT_ID: str = ""
    STRIPE_KEY: str = ""

    # Override defaults
    DATABASE_URL: str = "postgresql+asyncpg://localhost/myapp"
    AUTH_USER_MODEL: str = "apps.accounts.models.User"


settings = Settings()  # Validates everything at import time
```

`main.py`:

```python
from hotframe import create_app
from settings import settings

app = create_app(settings)
```

---

## 3. `database.py` — `AsyncEngine`, `AsyncSession`, `get_db`

### 3.1 Lo que expone

```python
get_engine()           -> AsyncEngine          # singleton
get_session_factory()  -> async_sessionmaker   # singleton
get_db()               -> AsyncGenerator[AsyncSession, None]  # FastAPI dep
dispose_engine()       -> None                 # llamado en shutdown
```

### 3.2 `get_engine()` — construcción del engine

```python
def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"echo": settings.DB_ECHO}

        if not settings.is_sqlite:
            kwargs.update(
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_recycle=settings.DB_POOL_RECYCLE,
                pool_pre_ping=True,                  # 1
                pool_timeout=settings.DB_POOL_TIMEOUT,
            )
            if settings.DB_DISABLE_PREPARED_STATEMENTS \
               and "asyncpg" in settings.DATABASE_URL:    # 2
                kwargs["connect_args"] = {
                    "prepared_statement_cache_size": 0,
                    "statement_cache_size": 0,
                }
        else:
            kwargs["connect_args"] = {"check_same_thread": False}  # 3

        _engine = create_async_engine(settings.DATABASE_URL, **kwargs)
    return _engine
```

Decisiones:

1. **`pool_pre_ping=True`** — antes de devolverte una conexión, manda
   `SELECT 1` para detectar conexiones muertas (cierres de
   PgBouncer/RDS Proxy). Pequeño coste por request, pero evita errores
   de "connection has been closed" en producción.
2. **`prepared_statement_cache_size=0`** — necesario en pollers
   transaction-mode (RDS Proxy, PgBouncer en transaction pooling). El
   pooler rota la conexión backend entre transacciones, invalidando
   cualquier prepared statement cacheado. asyncpg usa esta caché por
   defecto, así que la deshabilitamos explícitamente cuando el flag
   está activo.
3. **SQLite** — `check_same_thread=False` necesario para que un
   `AsyncSession` pueda compartirse entre tareas sin que SQLite se
   queje.

### 3.3 `get_session_factory()`

```python
def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,         # importante
        )
    return _session_factory
```

`expire_on_commit=False` significa que después de un `commit()` los
objetos siguen "vivos" — si los seguías usando para acceder a atributos,
no necesitas re-fetch. Esto se alinea con cómo escribimos handlers
(commit y luego seguimos usando los objetos para construir la
respuesta).

### 3.4 `get_db()` — la dependencia FastAPI

```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

Patrón "abrir + commit/rollback". Cada request abre una sesión nueva
(no se reutiliza entre requests), commitea al final si todo va bien,
o hace rollback si el handler lanza.

`auth/current_user.py` exporta el alias `DbSession = Annotated[ISession, Depends(get_db)]`,
así los proyectos no importan ni `AsyncSession` ni el protocolo:

```python
from hotframe import DbSession

@router.get("/items")
async def list_items(db: DbSession):
    result = await db.execute(...)
```

`db` se tipa como `ISession` (el protocolo), no `AsyncSession`. Tu
código no depende de SQLAlchemy.

### 3.5 `dispose_engine()`

```python
async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
```

Cierra el pool y resetea los singletons. Llamado por `bootstrap.py`
en shutdown — y por `hotframe.testing.create_test_app` entre tests
para que cada test arranque con un engine limpio.

### 3.6 Errores típicos

| Síntoma | Causa | Fix |
|---|---|---|
| `prepared statement "X" already exists` en producción | RDS Proxy + asyncpg sin `DB_DISABLE_PREPARED_STATEMENTS=true`. | Activa el flag en task definition. |
| `pool reached limit` | Demasiadas requests concurrentes con pool pequeño. | Sube `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`, o investiga handlers que se "olvidan" la session abierta. |
| `Connection has been closed` | Conexión TCP cortada por el proxy. | `pool_pre_ping=True` ya está activo; verifica `pool_recycle` < timeout del proxy. |
| `Database engine initialized: sqlite+aiosqlite:///./app.db` en prod | Olvidaste `DATABASE_URL` en task definition. | Configura el env var. |

---

## 4. `paths.py` — `DataPaths` (rutas efímeras)

### 4.1 Filosofía

> Hotframe es 100% stateless. DB + S3 son las únicas fuentes de
> verdad. El filesystem local es **caché y temp**.

Los containers de ECS/Fargate son efímeros — cualquier archivo escrito
en `/tmp` puede desaparecer al siguiente reinicio. Esta clase
**explicita** ese contrato.

### 4.2 La clase `DataPaths`

```python
class DataPaths:
    def __init__(self, base: Path | None = None):
        if base is not None:
            self._base = base.resolve()
        elif env := os.environ.get("DATA_PATH"):
            self._base = Path(env).resolve()
        else:
            self._base = Path("/tmp/hotframe-data")
```

Tres niveles de precedencia:

1. Argumento explícito al constructor (tests).
2. Env var `DATA_PATH` (override de despliegue).
3. Fallback `/tmp/hotframe-data` (default seguro: efímero).

### 4.3 Properties

| Property | Path | Uso |
|---|---|---|
| `base` | `_base` | Raíz |
| `media` | `/tmp/hotframe-media` | Caché local de media (solo dev — prod usa S3) |
| `modules` | `/tmp/modules` | Caché de código de módulos descargados de S3 |
| `reports` | `_base/reports` | Generación temporal de reports (final → S3) |
| `temp` | `_base/temp` | General temp |
| `cache` | `_base/cache` | General cache |

Todas son `cached_property`, así que se evalúan una vez y se
"congelan" en la instancia.

### 4.4 `ensure_dirs()`

```python
def ensure_dirs(self) -> None:
    for d in self.all_dirs:
        d.mkdir(parents=True, exist_ok=True)
```

Crea todos los directorios. Lo llaman las pruebas y los managers que
necesitan escribir antes de leer. En producción no se llama desde
boot porque los path-de-tmp se crean lazy al primer uso.

### 4.5 Singleton

```python
_data_paths: DataPaths | None = None

def get_data_paths() -> DataPaths:
    global _data_paths
    if _data_paths is None:
        _data_paths = DataPaths()
    return _data_paths

def reset_data_paths() -> None:
    global _data_paths
    _data_paths = None
```

Mismo patrón que `get_settings()`.

### 4.6 ¿Cuándo usar `DataPaths` vs `settings.MEDIA_ROOT`?

- **`settings.MEDIA_ROOT`**: lo que el sysadmin configura — punto de
  montaje "oficial" para `/media/`. En dev suele apuntar a `./media`.
- **`DataPaths.media`**: caché efímera local. Si `MediaService`
  descarga de S3 una imagen para servirla, la cachea aquí.

El uso típico en producción: `MEDIA_ROOT` apunta a S3 indirectamente
(via `MediaStorage` con backend S3), y `DataPaths` siempre es `/tmp`.

---

## 5. Cómo se usan estos archivos

### 5.1 Quién llama `get_settings()`

Casi todo. `bootstrap.lifespan` (paso 6 según `bootstrap.md`),
`auth.csrf.CSRFMiddleware.__init__`, `engine.module_runtime`,
`live.runtime`, etc. Todos consultan settings en el primer uso y
cachean si necesitan campos múltiples.

### 5.2 Quién llama `get_engine()` / `get_session_factory()`

- `bootstrap.lifespan` — inicializa el engine al arrancar.
- `bootstrap.lifespan` (paso 13) — abre una `boot_session` para
  `runtime.boot_all_active_modules`.
- `engine.module_runtime` cuando necesita escribir el state de un
  módulo en la tabla `module`.
- `migrations.runner` para correr Alembic.

### 5.3 Quién llama `get_db()`

Cualquier handler FastAPI con `db: DbSession`. La dependency injection
de FastAPI hace el resto. **Nunca** se llama directamente desde código
síncrono ni desde lifespan — usa `get_session_factory()` ahí.

### 5.4 Quién llama `DataPaths`

`MediaStorage`, `engine.s3_source.S3ModuleSource` (caché de zips
descargados), `engine.marketplace_client` (caché de manifests), tests.

---

## 6. Recetas habituales

### 6.1 Tests con DB en memoria

```python
from hotframe.config.database import dispose_engine
from hotframe.config.settings import reset_settings

@pytest.fixture(autouse=True)
async def _reset():
    reset_settings()
    yield
    await dispose_engine()
```

`reset_settings()` borra el singleton para que el siguiente test pueda
importar settings frescos. `dispose_engine()` cierra el pool (necesario
si el test creó tablas y queremos un engine nuevo).

### 6.2 Settings con prefix

```python
class Settings(HotframeSettings):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")
    TENANT_ID: str = ""

# Reads MYAPP_TENANT_ID, MYAPP_DATABASE_URL, MYAPP_DEBUG, ...
```

Los campos de `HotframeSettings` también respetan el prefix — así un
proyecto puede tener `MYAPP_DEBUG=false` sin colisión con otros
servicios en el mismo entorno.

### 6.3 Override puntual en lifespan

```python
@asynccontextmanager
async def custom_lifespan(app):
    settings = get_settings()
    if settings.is_production:
        # Inicializaciones extra
        ...
    yield
```

`get_settings()` ya está cacheado en este punto, así que múltiples
llamadas son baratas.
