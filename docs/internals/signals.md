# signals.md — Async event bus, hooks, typed events

> **Carpeta cubierta:** `src/hotframe/signals/`. Seis archivos:
> `__init__.py`, `dispatcher.py`, `hooks.py`, `types.py`,
> `catalog.py`, `builtins.py`.
> Provee dos sistemas pub/sub complementarios: `AsyncEventBus`
> (estilo Django signals + Pydantic typed events) y `HookRegistry`
> (estilo WordPress actions/filters), más helpers para definir
> eventos tipados.

---

## 1. `__init__.py`

Solo docstring. Imports explícitos:

```python
from hotframe.signals.dispatcher import AsyncEventBus
from hotframe.signals.hooks import HookRegistry
from hotframe.signals.types import BaseEvent, register_event, EventRegistry, ValidationMode
```

`catalog.py` y `builtins.py` definen eventos típed predefinidos —
`ModelPostSaveEvent`, etc. Importables vía
`hotframe.signals.catalog`.

---

## 2. `dispatcher.py` — `AsyncEventBus`

### 2.1 Doble interfaz: legacy + typed

```python
# Legacy (string-based):
await bus.subscribe("sale.completed", handler)
await bus.emit("sale.completed", sale_id=uuid, total=99.99)

# Typed (Pydantic):
await bus.subscribe_typed(SaleCompletedEvent, handler)
await bus.emit_typed(SaleCompletedEvent(sale_id=uuid, total=99.99))
```

Ambos comparten la misma pool de handlers — un `emit_typed` también
dispara handlers legacy subscritos al mismo `event_name`, y viceversa.

### 2.2 `HandlerEntry` interno

```python
@dataclass(slots=True)
class HandlerEntry:
    handler: Callable
    priority: int = 10
    module_id: str | None = None
    once: bool = False
    typed: bool = False
```

Cada subscriber se almacena con metadata. `_handlers` es
`dict[str, list[HandlerEntry]]` keyed por event name (puede ser un
pattern fnmatch).

### 2.3 `subscribe(event, handler, *, priority=10, module_id=None, once=False)`

```python
async def subscribe(self, event, handler, *, priority=10, module_id=None, once=False):
    entry = HandlerEntry(handler=handler, priority=priority,
                         module_id=module_id, once=once, typed=False)
    async with self._lock:
        self._handlers.setdefault(event, []).append(entry)
```

`module_id` permite cleanup masivo en `unsubscribe_module`. `once`
auto-unsubscribes después del primer fire.

### 2.4 `emit(event, *, sender=None, error_policy=None, **data)`

Pasos:

1. **Resolver error_policy.** `None` → automático: si event matchea
   `CRITICAL_EVENT_PREFIXES = {"sale.", "payment.", "inventory."}`,
   `fail_fast`. Sino, `collect`.
2. **Match handlers.** Itera `_handlers`, compara con `event` o
   `fnmatch(event, pattern)` (wildcards).
3. **Sort por priority.** Estable — registration order preservado
   en empates.
4. **Emit metric** (counter `event.emit`).
5. **For cada handler:**
   - Si `entry.typed` y existe el typed class registrado, construye
     la instancia con `event_class(**data)` y llama con el objeto.
   - Si no, llama legacy: `handler(event=event, sender=sender, **data)`.
   - Mide duration con `event_handler_duration_histogram`.
   - Captura excepciones, las acumula en `errors`. Si
     `fail_fast`, raise — primero limpia los `once` ya invocados.
6. **Cleanup `once` handlers.**
7. **Devuelve `EmitResult(event, handler_count, errors)`.**

### 2.5 `emit_typed(event)` — variante typed

```python
async def emit_typed(self, event: BaseEvent) -> EmitResult:
    event_name = type(event).event_name
    if not self._registry.is_registered(event_name):
        self._registry.register(type(event))
    # Match handlers, sort, emit metric
    ...
    for entry in matched:
        if entry.typed:
            await entry.handler(event)        # passes the event instance
        else:
            kwargs = event.to_emit_kwargs()    # convert to dict
            await entry.handler(event=event_name, sender=None, **kwargs)
    ...
```

Auto-registra el event class si no estaba. Convierte el event a
kwargs solo si hay subscribers legacy (lazy).

### 2.6 Wildcards y prioridades

```python
await bus.subscribe("user.*", on_user_change)   # cualquier user.*
await bus.subscribe("user.created", on_create, priority=5)  # corre antes
```

Wildcards usan `fnmatch`. `*` no incluye `.`, así que `user.*` sí
coincide con `user.created` pero `user.*.profile` no coincide con
`user.created.profile` (wait, sí coincide — `*` greedy en fnmatch).
Para multi-nivel usa `**` o evita complejidad.

### 2.7 Module cleanup

```python
async def unsubscribe_module(self, module_id: str):
    async with self._lock:
        for pattern, entries in list(self._handlers.items()):
            self._handlers[pattern] = [e for e in entries if e.module_id != module_id]
            if not self._handlers[pattern]:
                del self._handlers[pattern]
```

Lo llama `engine.loader.ModuleLoader.unload_module`. Borra **todos**
los handlers que tenían `module_id=X`.

---

## 3. `hooks.py` — `HookRegistry`

WordPress style: actions (side effects) + filters (transformations).

### 3.1 `add_action(hook, callback, *, priority, module_id)`

```python
def add_action(self, hook, callback, *, priority=10, module_id=None):
    entry = HookEntry(callback=callback, priority=priority, module_id=module_id)
    self._actions.setdefault(hook, []).append(entry)
```

Sync — el registro es sync, la ejecución es async.

### 3.2 `do_action(hook, **kwargs)` — fire-and-forget

```python
async def do_action(self, hook, **kwargs):
    entries = self._actions.get(hook)
    if not entries:
        return ActionResult(hook=hook, callback_count=0, errors=[])
    sorted_entries = sorted(entries, key=lambda e: e.priority)
    errors = []
    for entry in sorted_entries:
        try:
            if iscoroutinefunction(entry.callback):
                await entry.callback(**kwargs)
            else:
                entry.callback(**kwargs)
        except Exception as exc:
            logger.exception(...)
            errors.append(exc)
    return ActionResult(hook=hook, callback_count=len(sorted_entries), errors=errors)
```

Errores **no abortan** la cadena. Cada callback se ejecuta y los
errores se acumulan.

### 3.3 `apply_filters(hook, value, **kwargs)` — chain

```python
async def apply_filters(self, hook, value, **kwargs):
    entries = self._filters.get(hook)
    if not entries:
        return value
    sorted_entries = sorted(entries, key=lambda e: e.priority)
    result = value
    for entry in sorted_entries:
        try:
            if iscoroutinefunction(entry.callback):
                result = await entry.callback(result, **kwargs)
            else:
                result = entry.callback(result, **kwargs)
        except Exception:
            logger.exception(...)
            # Continúa con el `result` actual sin propagar
    return result
```

Cada callback recibe el output del anterior. Si uno falla, el
chain continua con el último `result` válido.

### 3.4 Cuándo usar bus vs hooks

| Caso | Solución |
|---|---|
| Notificar a múltiples observers de un evento | EventBus |
| Permitir a módulos transformar un valor (precio, validación, render) | Hook filter |
| Permitir a módulos reaccionar a un punto del flujo (post-save extra logic) | Hook action |
| Eventos tipados con schema (Pydantic) | EventBus typed |
| Wildcards / patterns | EventBus |

EventBus = "broadcast a quien esté interesado".
Hooks = "puntos de extensión del flujo principal".

---

## 4. `types.py` — typed events (Pydantic)

### 4.1 `BaseEvent`

```python
class BaseEvent(BaseModel):
    model_config = ConfigDict(
        frozen=True,        # immutable después de construirse
        extra="forbid",     # rechaza fields no declarados
    )

    event_name: ClassVar[str]   # subclass debe declarar

    # Auto-populated:
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    hub_id: UUID | None = None
    triggered_by: UUID | None = None
    source_module: str | None = None

    @model_validator(mode="before")
    def _populate_context(cls, data):
        # Si hub_id/triggered_by no están, intenta sacarlos del request_context
        if isinstance(data, dict):
            if data.get("hub_id") is None or data.get("triggered_by") is None:
                from hotframe.utils.observability_context import request_context
                ctx = request_context.get()
                if ctx.hub_id and data.get("hub_id") is None:
                    data["hub_id"] = UUID(ctx.hub_id)
                if ctx.user_id and data.get("triggered_by") is None:
                    data["triggered_by"] = UUID(ctx.user_id)
        return data

    def to_emit_kwargs(self) -> dict:
        return self.model_dump(mode="python")
```

Decisiones:

1. **`frozen=True`** — un event es un hecho inmutable.
2. **`extra="forbid"`** — typo en el name de un campo es un error
   de validación, no un campo silenciosamente ignorado.
3. **Auto-populate hub_id + user_id** desde `request_context` (un
   ContextVar global). Si el handler no tiene contexto (CLI),
   queda `None`.
4. **`to_emit_kwargs()`** convierte el event a dict para handlers
   legacy.

### 4.2 `EventRegistry`

```python
class EventRegistry:
    def __init__(self):
        self._by_name: dict[str, type[BaseEvent]] = {}
        self._by_class: dict[type[BaseEvent], str] = {}

    def register(self, event_class):
        name = event_class.event_name
        if name in self._by_name and self._by_name[name] is not event_class:
            raise ValueError(...)
        self._by_name[name] = event_class
        self._by_class[event_class] = name
        return event_class

    def get_class(self, event_name): return self._by_name.get(event_name)
    def is_registered(self, event_name): return event_name in self._by_name
    def list_schemas(self):
        return {name: cls.model_json_schema() for name, cls in self._by_name.items()}
```

Singleton global `event_registry`. Permite introspección — útil
para construir documentación de eventos:

```python
print(json.dumps(event_registry.list_schemas(), indent=2))
```

### 4.3 `@register_event` decorator

```python
def register_event(cls: type[BaseEvent]) -> type[BaseEvent]:
    return event_registry.register(cls)
```

Uso:

```python
@register_event
class SaleCompletedEvent(BaseEvent):
    event_name = "sales.completed"
    sale_id: UUID
    total: Decimal
```

### 4.4 `ValidationMode`

```python
class ValidationMode(str, Enum):
    STRICT = "strict"
    WARN = "warn"
    PERMISSIVE = "permissive"
```

Controla qué hace `bus` cuando alguien hace `emit()` (legacy) sobre
un nombre que tiene typed class registrado:

- `PERMISSIVE` (default): no se queja.
- `WARN`: log warning con sugerencia de usar `emit_typed`.
- `STRICT`: raise (no implementado en el código actual).

---

## 5. `catalog.py` y `builtins.py` — eventos predefinidos

### 5.1 `catalog.py` — eventos del framework

```python
@register_event
class ModelPreSaveEvent(BaseEvent):
    event_name = "model.pre_save"
    model_name: str
    instance_id: UUID | None = None
    created: bool

@register_event
class ModelPostSaveEvent(BaseEvent):
    event_name = "model.post_save"
    model_name: str
    instance_id: UUID
    created: bool

@register_event
class ModelPreDeleteEvent(BaseEvent):
    event_name = "model.pre_delete"
    model_name: str
    instance_id: UUID

@register_event
class ModelPostDeleteEvent(BaseEvent):
    event_name = "model.post_delete"
    model_name: str
    instance_id: UUID
```

`orm.events.setup_orm_events` los emite en cada save/delete.

### 5.2 `builtins.py` — eventos de subsistemas

Eventos que el resto de hotframe emite y módulos pueden subscribir:

- `module.installed`, `module.activated`, `module.deactivated`,
  `module.updated`, `module.uninstalled` — emitidos por
  `engine.module_runtime`.
- `auth.login.success`, `auth.login.failed`, `auth.logout` — emitidos
  por `apps/accounts` (si se usa el patrón estándar).
- `http.request.started`, `http.request.completed`, `http.request.failed`
  — emitidos por `AuthenticatedClient` cuando `HTTP_CLIENT_EVENTS=True`.

---

## 6. Decisiones de diseño que conviene recordar

1. **`AsyncEventBus` y `HookRegistry` son distintos.** EventBus =
   broadcast, Hooks = extension points específicos del flujo.
2. **EventBus tiene typed + legacy.** Migración gradual.
3. **`emit` no falla por defecto.** Errores se acumulan en
   `EmitResult`. Para `sale.*`, `payment.*`, `inventory.*` →
   `fail_fast` automático.
4. **Wildcards con fnmatch.** `*` es greedy across `.`.
5. **`module_id` en cada handler permite cleanup masivo** en
   uninstall.
6. **`once=True`** para suscripciones one-shot.
7. **Typed events son frozen.** Inmutable. Extra fields son forbid.
8. **Auto-populate de `hub_id`/`triggered_by`** desde
   `request_context` (ContextVar). En CLI quedan None.
9. **`@register_event` es opcional.** Si subscribes typed, se
   registra automáticamente al primer `subscribe_typed`.

---

## 7. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `KeyError 'event_name'` al construir el event | Olvidaste `event_name = "..."` ClassVar. | Añádelo. |
| `Extra inputs are not permitted` | Pasaste un kwarg no declarado. | `extra="forbid"` — añade el field o quita el kwarg. |
| Handlers no se llaman | `subscribe` no fue awaited. | `await bus.subscribe(...)` (es async). |
| `EmitResult.errors` no vacío | Algún handler crasheó. | Mira `errors[0].args` — el log lo registra con full traceback. |
| `fail_fast` lanza pero los siguientes handlers no corren | Es la semántica esperada. | Usa `error_policy="collect"` si quieres todos. |
| Typed event constructor falla con `hub_id=...` no UUID | Debe ser UUID instance. | Convierte: `hub_id=UUID(str_value)`. |
| Hook callback en filter rompe la cadena | Es esperado: log + skip ese callback, sigue con el último `result`. | Si necesitas que la cadena pare, revísate el patrón. |
| `event_name already registered` | Dos clases con el mismo `event_name`. | Renombra o usa la misma clase. |
