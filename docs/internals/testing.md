# testing.md — Test utilities and fakes

> **Carpeta cubierta:** `src/hotframe/testing/`. Dos archivos:
> `__init__.py`, `test_lazy_imports.py`.
> Fixtures pytest, fakes para los registries, helper para crear
> un app de pruebas con SQLite in-memory y middleware reducido.

---

## 1. `__init__.py` — la API completa

A diferencia de la mayoría de paquetes, aquí **todo el código vive
en `__init__.py`**. La API consiste en:

- `create_test_app(settings=None, **overrides)` — factory de FastAPI
- `create_test_tables()` / `drop_test_tables()` / `cleanup_test_db()`
- `test_db_session()` — async generator
- `FakeEventBus` — registra eventos emitidos
- `FakeHookRegistry` — versión simplificada de `HookRegistry`

`test_lazy_imports.py` es un test interno del paquete (no API).

---

## 2. `create_test_app(settings=None, **overrides)`

```python
def create_test_app(settings=None, **overrides):
    if settings is None:
        test_defaults = {
            "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
            "DEBUG": True,
            "DEPLOYMENT_MODE": "local",
            "SECRET_KEY": "test-secret-key-not-for-production",
            "CSRF_EXEMPT_PREFIXES": ["/"],   # Exempt all routes
            "RATE_LIMIT_API": 999999,
            "RATE_LIMIT_AUTH": 999999,
            "LOG_LEVEL": "WARNING",
        }
        test_defaults.update(overrides)
        settings = HotframeSettings(**test_defaults)
    set_settings(settings)
    return create_app(settings)
```

Decisiones críticas para tests:

1. **SQLite in-memory.** No requiere PostgreSQL local. Cada
   `create_test_app()` arranca con una BD limpia.
2. **CSRF exempt en todas las rutas.** Tests no quieren manejar
   tokens. `CSRF_EXEMPT_PREFIXES=["/"]` matchea todo.
3. **Rate limits a 999999.** Los tests pueden hacer 1000 requests
   sin disparar el limiter.
4. **`LOG_LEVEL=WARNING`** para no llenar el output de pytest con
   info logs.
5. **`SECRET_KEY` fijo.** No queremos randomness en tests — si una
   sesión se firma con clave A y se verifica con clave B, debugear
   sería pesadilla.

### 2.1 Override puntual

```python
app = create_test_app(
    AUTH_USER_MODEL="apps.accounts.models.User",
    LOG_LEVEL="DEBUG",
)
```

Cualquier kwarg se pasa al `HotframeSettings` constructor. Los
defaults se mergean con los overrides.

---

## 3. DB fixtures

### 3.1 `create_test_tables()` y `drop_test_tables()`

```python
async def create_test_tables():
    global _test_engine
    if _test_engine is None:
        _test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def drop_test_tables():
    if _test_engine is not None:
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
```

Crea/borra tablas declaradas en `Base.metadata`. Importa **todos**
tus modelos antes de llamar — el metadata solo conoce las clases
que han sido importadas (cargar el módulo registra la tabla).

### 3.2 `test_db_session()` — async generator

```python
async def test_db_session():
    global _test_engine, _test_session_factory
    if _test_engine is None:
        _test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with _test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    if _test_session_factory is None:
        _test_session_factory = async_sessionmaker(_test_engine, expire_on_commit=False)
    async with _test_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()  # rollback always — no test pollutes the next
```

Patrón pytest:

```python
@pytest.fixture
async def db():
    async for session in test_db_session():
        yield session
```

`rollback` siempre al final — un test no contamina al siguiente
con datos persistidos.

### 3.3 `cleanup_test_db()`

```python
async def cleanup_test_db():
    global _test_engine, _test_session_factory
    if _test_engine is not None:
        await _test_engine.dispose()
        _test_engine = None
        _test_session_factory = None
```

Llama esto en un fixture session-scoped para liberar recursos:

```python
@pytest.fixture(scope="session", autouse=True)
async def _cleanup():
    yield
    await cleanup_test_db()
```

---

## 4. `FakeEventBus`

```python
class FakeEventBus:
    def __init__(self):
        self.events: list[tuple[str, Any]] = []
        self.typed_events: list[Any] = []

    async def emit(self, event_name, data=None, **kwargs):
        self.events.append((event_name, data))

    async def emit_typed(self, event):
        self.typed_events.append(event)

    def reset(self):
        self.events.clear()
        self.typed_events.clear()
```

Uso típico:

```python
async def test_create_user_emits_event():
    bus = FakeEventBus()
    service = UserService(bus=bus, ...)
    await service.create(email="x@y")
    assert any(e[0] == "user.created" for e in bus.events)
```

Note que la API no es 100% compatible con `AsyncEventBus`:

- `emit(event_name, data=None, **kwargs)` recoge `data=None` en
  lugar de los kwargs sueltos. Adapta tus tests.
- No hay `subscribe` — solo registra emisiones. Si tu test requiere
  subscribers, usa `AsyncEventBus` real.

---

## 5. `FakeHookRegistry`

```python
class FakeHookRegistry:
    def __init__(self):
        self._actions: dict[str, list] = {}
        self._filters: dict[str, list] = {}

    async def do_action(self, name, *args, **kwargs):
        for fn in self._actions.get(name, []):
            await fn(*args, **kwargs)

    async def apply_filters(self, name, value, *args, **kwargs):
        for fn in self._filters.get(name, []):
            value = await fn(value, *args, **kwargs)
        return value

    def add_action(self, name, fn, priority=10):
        self._actions.setdefault(name, []).append(fn)

    def add_filter(self, name, fn, priority=10):
        self._filters.setdefault(name, []).append(fn)
```

Versión minimalista del `HookRegistry` real, sin priority sort,
sin module_id tracking, sin error handling. Útil para tests donde
quieres verificar que un callback fue llamado pero no quieres
toda la complejidad del bus real.

---

## 6. Patrón de testing recomendado

### 6.1 `conftest.py` raíz

```python
import pytest
from hotframe.testing import create_test_app, test_db_session, cleanup_test_db
from httpx import AsyncClient

@pytest.fixture
async def app():
    return create_test_app()

@pytest.fixture
async def client(app):
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c

@pytest.fixture
async def db():
    async for session in test_db_session():
        yield session

@pytest.fixture(scope="session", autouse=True)
async def _cleanup():
    yield
    await cleanup_test_db()
```

### 6.2 Test de endpoint

```python
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

### 6.3 Test de service con DB

```python
async def test_create_product(db):
    repo = BaseRepository(Product, db, hub_id=test_hub_id)
    product = await repo.create(name="Camiseta", price=19.99)
    assert product.id is not None
    assert product.name == "Camiseta"
```

### 6.4 Test de event emission

```python
from hotframe.testing import FakeEventBus

async def test_emits_event_on_save(db):
    bus = FakeEventBus()
    service = MyService(db, bus=bus)
    await service.save_thing()
    assert ("thing.saved", None) in bus.events
```

---

## 7. Decisiones de diseño que conviene recordar

1. **SQLite in-memory siempre.** Tests no tocan PostgreSQL. Limita
   features SQLite (no jsonb, no advisory locks) — los tests que
   usen esas features deben mockear o usar PG explícitamente.
2. **CSRF + rate-limit deshabilitados.** Tests son single-purpose,
   no estresan los safeguards.
3. **Rollback siempre.** `test_db_session` rollback al final — no
   cleanup manual.
4. **Singletons globales.** `_test_engine`/`_test_session_factory`
   se crean lazy y persisten entre tests dentro de la session.
   `cleanup_test_db()` los resetea.
5. **`set_settings` antes de `create_app`.** El bootstrap consulta
   `get_settings()` — sin set, te queda settings por defecto que
   puede colisionar.
6. **FakeEventBus es minimal.** No replica priority, wildcards, ni
   typed events. Para esos casos, usa `AsyncEventBus` real.

---

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `RuntimeError: Async fixture not initialized` | Olvidaste `@pytest.fixture(scope="...")` async-aware. | Usa `pytest-asyncio` y marca con `pytest.mark.asyncio`. |
| Tests pisan datos entre sí | No usaste `test_db_session`. | Cambia a esa fixture — siempre rollbackea. |
| `OperationalError: no such column` | Modelo nuevo, no creaste tablas. | Llama `create_test_tables()` o usa `test_db_session` (lo hace al primer uso). |
| `RateLimit 429` en tests | Settings no inicializados con defaults de testing. | `create_test_app(...)` ya los configura. Verifica que pasaste por ahí. |
| `FakeEventBus` no recibe el evento | Tu service tiene un bus distinto al que pasaste. | Verifica DI — el service constructor usa el `bus` que le diste. |
| `cleanup_test_db` no se ejecuta | Falta `autouse=True` o `scope="session"`. | Mira el ejemplo `_cleanup` arriba. |
