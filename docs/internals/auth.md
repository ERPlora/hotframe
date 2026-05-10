# `auth/` — autenticación, sesión, permisos, CSP/CSRF

Nueve archivos. El **núcleo de seguridad** del framework: hashing
de contraseñas/PIN, gestión de sesión via cookie firmada, dependencias
FastAPI para inyectar usuario y registries, validación CSRF
double-submit, construcción del header CSP.

```
auth/
├── __init__.py            ← (docstring)
├── auth.py                ← bcrypt + sesión (passwords, PIN, get_session_user_id)
├── crypto.py              ← Fernet wrapper (encrypt_secret, decrypt_secret)
├── csp.py                 ← build_csp_header (no es middleware, es el builder)
├── csrf.py                ← CSRFMiddleware (double-submit cookie)
├── current_user.py        ← FastAPI deps: DbSession, CurrentUser, EventBus, ...
├── permissions.py         ← has_permission (fnmatch), require_permission factory
├── rate_limit.py          ← PINRateLimiter (in-memory escalating lockout)
└── session_helpers.py     ← get_session_data (decode cookie SIN middleware HTTP)
```

---

## `auth.py` (~113 LOC)

**Propósito**: Primitivos low-level de hashing y sesión.

### `hash_password` / `verify_password`

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
```

**Detalles**:
- Bcrypt con salt generado por `bcrypt.gensalt()` (default work
  factor de 12 rounds — ~250ms en hardware moderno).
- `verify_password` **nunca lanza**. Si el hash está corrupto o el
  formato es inválido, devuelve `False`. Esto evita 500 cuando un
  user antiguo tiene hash en formato viejo.

### `hash_pin` / `verify_pin`

Idénticas a `hash_password`/`verify_password`. La separación es
**semántica**: PINs son típicamente 4-8 dígitos y se diferencian de
passwords en políticas de uso (rate limit estricto, etc.). El código
es el mismo.

### `get_session_user_id` / `create_session` / `destroy_session`

```python
SESSION_USER_KEY = "user_id"

def get_session_user_id(request: Request) -> UUID | None:
    session = request.session
    raw = session.get(SESSION_USER_KEY)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None

def create_session(request: Request, user_id: UUID) -> None:
    request.session[SESSION_USER_KEY] = str(user_id)

def destroy_session(request: Request) -> None:
    request.session.clear()
```

`request.session` viene de Starlette `SessionMiddleware`. Es un dict
backed por cookie firmada (itsdangerous). Guardamos `user_id` como
string para serializar JSON correctamente; al leer parseamos a UUID.

`destroy_session` limpia todo, no sólo la key del user. Cualquier
otra cosa que metiste (preferencias, csrf_token, etc.) también
desaparece. El middleware emite un `Set-Cookie` con `Max-Age=0` para
borrar la cookie del navegador.

---

## `crypto.py` (~98 LOC)

**Propósito**: Wrapper sobre Fernet para cifrar secretos en la DB.

```python
@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    settings = get_settings()
    if settings.SECRETS_KEY:
        return Fernet(settings.SECRETS_KEY.encode("utf-8"))
    if settings.DEPLOYMENT_MODE != "local":
        raise SecretsKeyMissingError(...)
    # Dev fallback: derivar de SECRET_KEY
    derived = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(derived)
    return Fernet(key)

def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")

def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretDecryptionError(...) from exc

def generate_key() -> str:
    return Fernet.generate_key().decode("utf-8")

def reset_cache() -> None:
    _get_fernet.cache_clear()
```

**Detalles**:

1. **Cache `lru_cache(maxsize=1)`**: una sola instancia Fernet por
   proceso. Importante porque Fernet hace operaciones criptográficas
   en su constructor y crearlo cada llamada sería un cuello.
2. **Strings vacíos no se cifran**: `encrypt_secret("")` devuelve
   `""`. Optimización para campos opcionales que pueden quedar vacíos.
3. **Dev fallback**: en `DEPLOYMENT_MODE=local`, deriva la clave
   Fernet desde `SECRET_KEY` con SHA256. Esto permite arrancar en dev
   sin configurar `SECRETS_KEY`. En producción es **error fatal**.
4. **Excepciones específicas**:
   - `SecretsKeyMissingError` — falta config en prod.
   - `SecretDecryptionError` — ciphertext inválido (clave rotada,
     manipulación, corrupción).

`reset_cache()` es para tests: cuando un test cambia env vars,
necesita forzar la regeneración del Fernet.

**Quién lo usa**: `db/types.py` (`EncryptedString`, `EncryptedText` —
ver [db.md](db.md)).

---

## `csp.py` (~70 LOC)

**Propósito**: Builder del header `Content-Security-Policy`. **No es
el middleware** — es la función que el middleware llama.

```python
def build_csp_header(nonce: str, enforce: bool) -> tuple[str, str]:
    settings = get_settings()
    directives = []

    # script-src
    script_sources = ["'self'", f"'nonce-{nonce}'", "'unsafe-eval'"]
    script_sources += settings.CSP_ALLOWED_SOURCES.get("script", [])
    directives.append(f"script-src {' '.join(script_sources)}")

    # style-src
    style_sources = ["'self'", "'unsafe-inline'"]
    style_sources += settings.CSP_ALLOWED_SOURCES.get("style", [])
    directives.append(f"style-src {' '.join(style_sources)}")

    # img-src
    img_sources = ["'self'", "data:", "blob:"]
    img_sources += settings.CSP_ALLOWED_SOURCES.get("img", [])
    directives.append(f"img-src {' '.join(img_sources)}")

    # connect-src (incluye wss:)
    connect_sources = ["'self'", "wss:"]
    if settings.DEPLOYMENT_MODE == "local":
        connect_sources.append("ws://localhost:*")
    connect_sources += settings.CSP_ALLOWED_SOURCES.get("connect", [])
    directives.append(f"connect-src {' '.join(connect_sources)}")

    directives.append("object-src 'none'")
    directives.append("frame-ancestors 'none'")

    if settings.CSP_TRUSTED_TYPES:
        directives.append("require-trusted-types-for 'script'")
        directives.append("trusted-types default iconify 'allow-duplicates'")

    header_name = "Content-Security-Policy" if enforce else "Content-Security-Policy-Report-Only"
    return header_name, "; ".join(directives)
```

**Detalles**:

- **`'unsafe-eval'`** está en `script-src` deliberadamente. Algunos
  clientes JS lo necesitan (ej. los binders de live.js no, pero otros
  scripts vendor sí). Si tu app no lo necesita, override
  `CSP_ALLOWED_SOURCES["script"]`.
- **`'unsafe-inline'`** en `style-src`: útil porque algunos componentes
  inyectan `<style>` o `style="..."` en runtime. Endurecer requiere
  pasar a nonced styles, lo que es más invasivo.
- **`connect-src wss:`**: el live runtime abre WSS. En dev local
  además permitimos `ws://localhost:*`.
- **`object-src 'none'`**: bloquea `<object>`, `<embed>`, `<applet>`.
  Estos son vectores XSS legacy.
- **`frame-ancestors 'none'`**: nadie puede embeber tu sitio en un
  iframe. Previene clickjacking.
- **Trusted Types** opcional: `require-trusted-types-for 'script'`
  fuerza que cualquier `innerHTML = x` use Trusted Types (más
  estricto). El framework expone los policies `default` (permisivo) y
  `iconify` (para el script de Iconify).

**Detalle importante**: el `enforce` flag cambia entre
`Content-Security-Policy` (rechaza violaciones) y
`Content-Security-Policy-Report-Only` (sólo logea). El default
(`CSP_ENFORCE=False`) es report-only para que puedas ver violaciones
en el navegador console sin romper la app.

---

## `csrf.py` (~111 LOC)

**Propósito**: Middleware double-submit cookie. **El único middleware
que vive en `auth/`** (todos los demás están en `middleware/`).

```python
COOKIE_NAME = "csrf_token"
HEADER_NAME = "x-csrf-token"
FORM_FIELD = "csrf_token"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)

class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, exempt_prefixes: tuple[str, ...] | None = None) -> None:
        super().__init__(app)
        if exempt_prefixes is not None:
            self._exempt_prefixes = exempt_prefixes
        else:
            self._exempt_prefixes = tuple(get_settings().CSRF_EXEMPT_PREFIXES)

    async def dispatch(self, request, call_next):
        # WS upgrades: skip
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        # Static: skip (cacheable)
        if request.url.path.startswith("/static/"):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        new_token = False
        if not token:
            token = generate_csrf_token()
            new_token = True
        request.state.csrf_token = token

        if request.method in _UNSAFE_METHODS and not self._is_exempt(request):
            submitted = await self._get_submitted_token(request)
            if not submitted or not secrets.compare_digest(submitted, token):
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

        response = await call_next(request)
        if new_token:
            response.set_cookie(
                key=COOKIE_NAME, value=token,
                httponly=False, samesite="lax",
                secure=request.url.scheme == "https",
                max_age=86400 * 30,
            )
        return response
```

**Detalles**:

- **WebSocket skip**: WSs no traen el patrón cookie/header CSRF
  estándar. Su autenticación se basa en la cookie de sesión que viaja
  en el handshake.
- **Static skip**: assets cacheables no deben tener `Set-Cookie` (CDN
  no podría compartir entre usuarios).
- **`secrets.compare_digest`**: comparación de tiempo constante,
  inmune a timing attacks.
- **Cookie `httponly=False`**: deliberado. El cliente JS necesita
  leer la cookie para meter el token en el header `X-CSRF-Token` en
  fetch/XHR.
- **`samesite="lax"`**: previene CSRF clásico (cookie no se envía en
  POSTs cross-site).
- **`secure` dinámico**: sólo HTTPS en producción.

**`_get_submitted_token`** intenta header → form field → JSON body.
Cualquiera vale.

**Quién lo usa**: registrado en `settings.MIDDLEWARE` por defecto.
Inyecta `request.state.csrf_token` que `_HotframeTemplates` recoge y
hace disponible como `{{ csrf_token }}` y `{{ csrf_input() }}`.

---

## `current_user.py` (~218 LOC)

**Propósito**: Dependencias FastAPI. Punto único de entrada para
inyectar DB session, usuario autenticado, y registries.

### `get_db` y `DbSession`

```python
async def get_db() -> AsyncGenerator[ISession, None]:
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

DbSession = Annotated[ISession, Depends(get_db)]
```

Patrón estándar:

1. Abre sesión.
2. Yield al handler.
3. Si OK → commit.
4. Si lanzó → rollback + re-raise.

`DbSession` es un type alias para que el handler haga `db: DbSession`
en vez del verbose `db: Annotated[ISession, Depends(get_db)]`.

### `_resolve_user_model()`

```python
def _resolve_user_model() -> type[Any] | None:
    settings = get_settings()
    if not settings.AUTH_USER_MODEL:
        return None
    module_path, class_name = settings.AUTH_USER_MODEL.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)
```

Importa la clase user del dotted path en settings. Devuelve `None`
si no está configurado.

### `get_current_user`

```python
async def get_current_user(request: Request, db: DbSession) -> Any:
    user_id = get_session_user_id(request)
    if user_id is None:
        raise HTTPException(401, "Authentication required")

    UserModel = _resolve_user_model()
    if UserModel is None:
        raise HTTPException(500, "AUTH_USER_MODEL not configured")

    result = await db.execute(
        select(UserModel).where(UserModel.id == user_id, UserModel.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "User not found or deactivated")

    # Resolver permisos (4 estrategias en cascada)
    perms = getattr(request.state, "user_permissions", None) or []
    if not perms:
        if getattr(user, "is_admin", False):
            perms = ["*"]
        elif hasattr(user, "get_permissions"):
            perms = await user.get_permissions() if callable(user.get_permissions) else []
        elif hasattr(user, "role") and hasattr(getattr(user, "role", None), "permissions"):
            role = user.role
            perms = [rp.permission_pattern for rp in role.permissions]

    request.state.user_permissions = perms
    request.state.current_user = user
    return user
```

**Las cuatro estrategias de permisos**:

1. **Cache en `request.state`**: si ya están cargados (otro middleware
   o llamada previa), úsalos.
2. **`user.is_admin`**: si el flag está, dale wildcard `["*"]`.
3. **`user.get_permissions()`**: método configurable (sync o async).
4. **`user.role.permissions`**: relación many-to-many con un `Role`
   que tiene una lista de `permission_pattern`.

Si nada matchea, queda `[]` (sin permisos).

`get_current_user_optional` es idéntico pero devuelve `None` en vez
de levantar 401.

### Type aliases

```python
CurrentUser = Annotated[Any, Depends(get_current_user)]
OptionalUser = Annotated[Any | None, Depends(get_current_user_optional)]
EventBus = Annotated["AsyncEventBus", Depends(get_event_bus)]
Hooks = Annotated["HookRegistry", Depends(get_hooks)]
Slots = Annotated["SlotRegistry", Depends(get_slots)]
```

Type hints para handlers:

```python
@router.get("/profile")
async def profile(user: CurrentUser, db: DbSession, bus: EventBus):
    ...
```

`get_event_bus`, `get_hooks`, `get_slots` simplemente leen
`request.app.state.event_bus`, etc., y levantan 503 si no existen.

---

## `permissions.py` (~116 LOC)

**Propósito**: Wildcard matching + dependency factory.

```python
def has_permission(user_permissions: list[str], required: str) -> bool:
    for perm in user_permissions:
        if perm == "*":
            return True
        if perm == required:
            return True
        if fnmatch(required, perm):
            return True
    return False
```

Tres niveles:

- **Wildcard total**: `"*"`.
- **Match exacto**.
- **fnmatch**: `"inventory.*"` matches `"inventory.view"`.

```python
def require_permission(*perms: str, any_perm: bool = False) -> Any:
    async def _check_permissions(request: Request) -> None:
        from hotframe.auth.auth import get_session_user_id

        user_id = get_session_user_id(request)
        if user_id is None:
            raise HTTPException(403, "Authentication required")

        user_permissions = getattr(request.state, "user_permissions", [])

        if any_perm:
            if not any(has_permission(user_permissions, p) for p in perms):
                raise HTTPException(403, "Insufficient permissions")
        else:
            if not all(has_permission(user_permissions, p) for p in perms):
                raise HTTPException(403, "Insufficient permissions")

    return Depends(_check_permissions)
```

**Factory de dependency**: devuelve un `Depends(...)` listo para
usar. Se enchufa en una ruta:

```python
@router.get(
    "/admin/users",
    dependencies=[Depends(require_permission("admin.manage"))],
)
async def list_users(): ...
```

`any_perm=True` cambia AND→OR.

**Importante**: `require_permission` lee `request.state.user_permissions`
**ya populadas**. Si no se llamó a `get_current_user` antes, la lista
está vacía. Asegúrate de tener `user: CurrentUser` en el handler O
declarar `dependencies=[Depends(get_current_user), Depends(require_permission(...))]`.

---

## `rate_limit.py` (~198 LOC)

**Propósito**: `PINRateLimiter` — rate limit escalado por
device_token o IP, in-memory, para PIN authentication.

```python
class PINRateLimiter:
    THRESHOLDS = [
        (5, 5 * 60),       # 5 intentos  → 5 min lockout
        (10, 30 * 60),     # 10 intentos → 30 min lockout
        (20, None),        # 20 intentos → permanent lock
    ]

    def __init__(self):
        self._records: dict[str, _AttemptRecord] = {}
        self._lock = threading.Lock()

    def check_rate_limit(self, device_token, ip) -> RateLimitResult:
        # Sin mutar estado: ¿está permitido AHORA?
        ...

    def record_failed_attempt(self, device_token, ip) -> RateLimitResult:
        # Incrementa, aplica lock si excede threshold
        ...

    def record_success(self, device_token, ip) -> None:
        # Reset post-login OK
        ...

    def unlock_device(self, device_token, ip) -> None:
        # Admin action
        ...

    def get_status(self, device_token, ip) -> dict:
        # Diagnóstico
        ...

    def clear(self) -> None:
        # Tests
        ...
```

**Detalles**:

- **Keying**: `device_token` preferido (cookie/header), fallback a
  IP, default `"unknown"`.
- **Thresholds en orden inverso**: itera de mayor a menor para
  escalado correcto. 20 intentos → permanent (no temporary lock).
- **Permanent lock**: `locked_until=None` con flag `permanently_locked=True`.
- **`time.monotonic()`**: comparaciones inmunes a clock drift.
- **`threading.Lock`**: simple, contention bajo en PIN auth (un
  intento a la vez por device típico).
- **In-memory**: multi-proceso no funciona. Para multi-worker
  necesitarías Redis. Para un solo proceso por hub está OK.

**Quién lo usa**: instanciado en `app.state.rate_limiter` por
bootstrap. Lo consume el handler de PIN login.

---

## `session_helpers.py` (~55 LOC)

**Propósito**: Decode de cookie de sesión SIN middleware HTTP.
Crítico para WebSocket auth.

```python
def get_session_data(scope_or_request) -> dict[str, Any]:
    settings = get_settings()
    cookie = scope_or_request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not cookie:
        return {}

    signer = TimestampSigner(settings.SECRET_KEY)
    try:
        data = signer.unsign(cookie, max_age=settings.SESSION_MAX_AGE)
        decoded = base64.b64decode(data).decode("utf-8")
        result = json.loads(decoded)
        if isinstance(result, dict):
            return result
    except (BadSignature, ValueError, json.JSONDecodeError):
        return {}
    return {}
```

**Por qué existe**: `starlette.middleware.sessions.SessionMiddleware`
sólo procesa requests HTTP (envía `Set-Cookie` en response). NO toca
el handshake WebSocket. Pero las cookies del cliente SÍ viajan en el
handshake.

Para autenticar un WS, necesitas leer la cookie sin pasar por el
middleware. Este helper hace exactamente eso:

1. Lee la cookie por nombre (`settings.SESSION_COOKIE_NAME`).
2. La des-firma con `TimestampSigner` (mismo algoritmo que Starlette).
3. Decodifica base64 → JSON → dict.
4. Si algo falla, devuelve `{}` (silencioso, no levanta).

**Quién lo usa**: el endpoint `/ws/_live` (live runtime) extrae el
`session_id` con esto en el handshake, antes de que se hayan
procesado middlewares.

---

## Cómo se conecta con el resto

```
Request entra
  ├── CSRFMiddleware (auth/csrf.py)        valida CSRF en POSTs
  ├── CSPMiddleware (middleware/csp.py)    genera nonce + header
  ├── SessionMiddleware (Starlette)        decodifica cookie → request.session
  └── Handler:
       ├── @view → get_session_user_id (auth/auth.py) → redirect a login
       └── user: CurrentUser → get_current_user (auth/current_user.py)
            ├── _resolve_user_model() lee settings.AUTH_USER_MODEL
            ├── DB query: SELECT user WHERE id=? AND is_active
            └── 4 estrategias de permisos → request.state.user_permissions

Para protección de un endpoint:
  @router.get("/x", dependencies=[Depends(require_permission("x.view"))])
                                                ↑
                          permissions.py lee request.state.user_permissions

Para encriptar datos en DB:
  api_key: Mapped[str] = mapped_column(EncryptedString)
                                          ↑
                           db/types.py llama a auth/crypto.py

Para WS:
  /ws/_live handshake
       └── _resolve_session_id() → session_helpers.get_session_data()
                                       ↑
                       lee cookie firmada SIN middleware HTTP
```
