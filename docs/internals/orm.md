# orm.md — Transactions, ORM→EventBus bridge, PG LISTEN/NOTIFY

> **Carpeta cubierta:** `src/hotframe/orm/`. Cuatro archivos:
> `__init__.py`, `transactions.py`, `events.py`, `listeners.py`.
> Capa de conveniencias sobre SQLAlchemy: `atomic()` /
> `on_commit()`, listeners que emiten al EventBus en cada
> insert/update/delete, y un bridge opcional para PG NOTIFY.

---

## 1. `__init__.py`

Solo docstring. Imports explícitos:

```python
from hotframe.orm.transactions import atomic, on_commit
from hotframe.orm.events import setup_orm_events
from hotframe.orm.listeners import PgNotifyBridge
```

---

## 2. `transactions.py` — `atomic` y `on_commit`

### 2.1 `atomic(session)` — context manager

```python
@asynccontextmanager
async def atomic(session: ISession):
    sid = id(session)
    is_nested = session.in_transaction()

    if is_nested:
        async with session.begin_nested():
            yield session
    else:
        async with session.begin():
            yield session

        callbacks = _commit_callbacks.pop(sid, [])
        for cb in callbacks:
            result = cb()
            if hasattr(result, "__await__"):
                await result
```

Decisiones:

1. **Detecta si hay transacción activa.** `in_transaction()` →
   `begin_nested()` (SAVEPOINT). Sin transacción → `begin()` (BEGIN).
2. **`begin_nested` rollback no afecta el resto.** Útil para
   sub-operaciones que pueden fallar sin abortar la transacción
   externa.
3. **`on_commit` callbacks solo se disparan tras commit del
   outermost.** Si el outer hace rollback, los callbacks se
   descartan (no se invocan) porque el dict global se borra solo
   tras `__aexit__` del outer.

### 2.2 `on_commit(session, callback)`

```python
def on_commit(session, callback):
    sid = id(session)
    if sid not in _commit_callbacks:
        _commit_callbacks[sid] = []
    _commit_callbacks[sid].append(callback)
```

Registra callback para "después del commit". El callback puede ser
sync o async. Si la transacción rolls back, no se ejecuta.

### 2.3 Patrón típico

```python
async with atomic(db):
    user = User(email="x@y", hub_id=hub_id)
    db.add(user)
    await db.flush()

    on_commit(db, lambda: send_welcome_email(user.email))
    on_commit(db, lambda: log_audit("user.created", user.id))
```

Si algo falla antes del commit, el email no se envía. Limpio.

### 2.4 Por qué `_commit_callbacks` es global keyed by `id(session)`

`id(session)` es único por instancia de session. El dict global
permite registrar callbacks **sin acoplar el session object** —
cualquier código que reciba la session puede llamar `on_commit`.

Limitación: si dos requests con sessions distintas tienen el mismo
`id(session)` (alta colisión astronómicamente improbable), los
callbacks de uno se mezclan con los del otro. En la práctica, no
ocurre.

---

## 3. `events.py` — `setup_orm_events`

Bridge SQLAlchemy ORM → AsyncEventBus.

### 3.1 ¿Qué emite?

Para cada **insert**, **update**, **delete** sobre cualquier
descendiente de `Base`:

- **Typed events** (`ModelPostSaveEvent`, `ModelPostDeleteEvent`,
  `ModelPreSaveEvent`, `ModelPreDeleteEvent`) — ver `signals.md`.
- **Legacy string events** — `model.pre_save`, `model.post_save`,
  `model.post_delete`, y por table: `{tablename}.created`,
  `{tablename}.updated`, `{tablename}.deleted`.

Ambos se emiten por compatibilidad: nuevos consumers usan typed,
viejos siguen usando los strings.

### 3.2 Listeners conectados

```python
@event.listens_for(target, "before_insert", propagate=True)
def _before_insert(mapper, connection, instance):
    now = datetime.now(UTC)
    if hasattr(instance, "created_at") and instance.created_at is None:
        instance.created_at = now
    if hasattr(instance, "updated_at"):
        instance.updated_at = now
    # Auto-set hub_id from session.info["hub_id"] if not set
    if hasattr(instance, "hub_id") and instance.hub_id is None:
        ctx_hub_id = Session.object_session(instance).info.get("hub_id")
        if ctx_hub_id is not None:
            instance.hub_id = ctx_hub_id
    # Emit typed + legacy
    _emit_typed_async(bus, ModelPreSaveEvent(...))
    _emit_async(bus, "model.pre_save", sender=type(instance), ...)

@event.listens_for(target, "after_insert", propagate=True)
def _after_insert(...): ...

@event.listens_for(target, "before_update", propagate=True)
def _before_update(...): ...   # actualiza updated_at + ModelPreSaveEvent

@event.listens_for(target, "after_update", propagate=True)
def _after_update(...): ...

@event.listens_for(target, "after_delete", propagate=True)
def _after_delete(...): ...
```

### 3.3 Auto-populate de timestamps y `hub_id`

Decisiones:

1. **`created_at` solo si es `None`.** Si ya estaba seteado (e.g. seed
   data con timestamps fijos), no se sobrescribe.
2. **`updated_at` siempre se actualiza** en insert + update.
3. **`hub_id` auto desde `session.info`.** El handler que abre la
   session puede hacer `session.info["hub_id"] = current_hub_id`,
   y todos los `INSERT` heredan automáticamente. Patrón útil para
   eliminar boilerplate.

### 3.4 `_emit_async` con loop detection

```python
def _emit_async(bus, event_name, **kwargs):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop (CLI, migrations) — skip
        return
    loop.create_task(bus.emit(event_name, **kwargs))
```

ORM listeners corren **dentro** de SQLAlchemy, que es síncrono. La
emisión al bus es async. Solución: si hay loop activo (caso normal
de request), schedule task. Sin loop (Alembic, scripts), skip
silencioso con debug log.

### 3.5 Configuración

`bootstrap.lifespan` llama `setup_orm_events(event_bus, base=Base)`.
La firma:

- `bus`: el `AsyncEventBus` que emitirá los eventos.
- `base=None`: si das `Base`, registra solo en sus subclases. Si
  `None`, registra en `Mapper` (todas las clases mapeadas).

`propagate=True` propaga el listener a las subclases — un bug típico
de SQLAlchemy es olvidarlo y que solo `Base` directo emita eventos.

---

## 4. `listeners.py` — `PgNotifyBridge`

Bridge opcional para Postgres `LISTEN/NOTIFY` → AsyncEventBus.
Útil cuando un proceso externo (lambda worker, otro hub) inserta
un row y quieres reaccionar en este proceso sin polling.

### 4.1 La clase

```python
class PgNotifyBridge:
    def __init__(self, dsn, channels, bus, *, event_prefix="pg.notify."):
        self.dsn = dsn  # asyncpg DSN
        self.channels = channels
        self.bus = bus
        self.event_prefix = event_prefix
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self):
        try:
            import asyncpg
        except ImportError:
            logger.warning("asyncpg not installed — PgNotifyBridge disabled")
            return
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass

    async def _listen_loop(self):
        import asyncpg
        conn = await asyncpg.connect(self.dsn)
        for channel in self.channels:
            await conn.add_listener(channel, self._on_notify)
        await self._stop.wait()
        for channel in self.channels:
            await conn.remove_listener(channel, self._on_notify)
        await conn.close()

    def _on_notify(self, conn, pid, channel, payload):
        event_name = f"{self.event_prefix}{channel}"
        asyncio.create_task(self.bus.emit(event_name, payload=payload))
```

### 4.2 Uso

```python
# In a custom lifespan or app.startup
from hotframe.orm.listeners import PgNotifyBridge

bridge = PgNotifyBridge(
    dsn=settings.DATABASE_URL_SYNC.replace("postgresql://", "postgresql://"),
    channels=["events", "alerts"],
    bus=app.state.event_bus,
)
await bridge.start()

# Subscribe to the converted events
@bus.subscribe("pg.notify.events")
async def handle_pg_event(payload):
    ...
```

### 4.3 Cuándo usar `PgNotifyBridge` vs el EventBus interno

| Necesidad | Solución |
|---|---|
| Reaccionar a `INSERT` interno | `setup_orm_events` (automático, in-process) |
| Reaccionar a `INSERT` desde otro proceso | `PgNotifyBridge` + trigger SQL `NOTIFY` |
| Reaccionar a evento de negocio (sin DB) | `bus.emit("custom.event", ...)` |
| Notificación distribuida lightweight | `PgNotifyBridge` (Redis Pub/Sub también vale) |

Nota: PG NOTIFY tiene limit de payload (~8 KB). Para payloads
grandes, escribe a una tabla y usa NOTIFY con solo el `id`.

---

## 5. Cómo se conecta todo

```
SQLAlchemy event ("after_insert")
    │
    ▼
hotframe.orm.events listener   (sync, dentro del flush)
    │
    ▼
_emit_typed_async + _emit_async  (schedula tasks en el loop)
    │
    ▼
AsyncEventBus.emit + emit_typed
    │
    ▼
Subscribers (módulos, apps, plugins)


PostgreSQL NOTIFY 'events', 'payload'
    │
    ▼
asyncpg connection (PgNotifyBridge)
    │
    ▼
_on_notify callback  → asyncio.create_task(bus.emit(...))
    │
    ▼
AsyncEventBus.emit → subscribers
```

---

## 6. Decisiones que conviene recordar

1. **Listeners ORM corren sync.** No puedes hacer await en ellos.
   Schedule tasks en el loop activo.
2. **Sin loop = sin emisión.** En Alembic/CLI, los `_emit_async`
   skipean — esto es deliberado, los listeners no deberían correr
   en migraciones.
3. **Auto-populate de `hub_id` desde `session.info`.** Establece
   `session.info["hub_id"] = X` al inicio del request y olvídate.
4. **Typed + legacy events** se emiten siempre. Compatibilidad
   con consumers que aún no migraron a typed.
5. **`atomic()` detecta nested.** Usa `begin_nested()` (SAVEPOINT)
   si ya hay transacción.
6. **`on_commit` solo dispara tras outer commit.** Rollback descarta
   callbacks.
7. **`PgNotifyBridge` es opcional.** asyncpg es la única dep extra.
   Si no está, el bridge se desactiva con warning.

---

## 7. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Eventos no llegan a subscribers | `setup_orm_events` no fue llamado en lifespan. | Verifica `bootstrap.lifespan` paso 4. |
| `created_at` no se rellena | El listener `before_insert` requiere `Base` correcto. | Asegúrate de que tu modelo hereda de `hotframe.models.base.Base` (o el `Model`). |
| `hub_id` aparece como `None` | No setaste `session.info["hub_id"]`. | Hazlo al principio del request, en un middleware o dependency. |
| `on_commit` callback no corre | La transacción hizo rollback. | Ese es el comportamiento esperado. Si quieres "siempre run", usa `try/finally`. |
| `PgNotifyBridge` no recibe nada | No hay un trigger SQL que haga NOTIFY. | Crea el trigger: `CREATE TRIGGER ... AFTER INSERT EXECUTE FUNCTION pg_notify('events', NEW.id::text)`. |
| Tasks "fire and forget" lostantes | Logs no se ven. | Listeners de bus no devuelven errores al caller — chequea logs estructurados (`logger.exception`). |
| `RuntimeError: no running event loop` en tests | Llamaste `setup_orm_events` sin loop activo. | Hazlo dentro de un test async o usa pytest-asyncio. |
