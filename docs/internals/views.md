# views.md — `@view`, response helpers, BroadcastHub (SSE)

> **Carpeta cubierta:** `src/hotframe/views/`. Tres archivos:
> `__init__.py`, `responses.py`, `broadcast.py`.
> Define el decorador `@view` para HTML routes (auth + perms +
> template auto-discovery), helpers de response (`reactive_redirect`,
> `reactive_refresh`, etc.), y `BroadcastHub` para SSE generic.

---

## 1. `__init__.py`

Solo docstring. Imports explícitos:

```python
from hotframe.views.responses import (
    view, htmx_view, is_reactive_request, is_htmx_request,
    reactive_redirect, reactive_refresh, reactive_trigger, reactive_message,
    htmx_redirect, htmx_refresh, htmx_trigger,
    add_message, sse_stream,
)
from hotframe.views.broadcast import BroadcastHub, broadcast_router, get_broadcast_hub
```

`htmx_*` son aliases legacy de los `reactive_*` — el framework
dejó atrás HTMX como reactividad oficial pero conserva los nombres.

---

## 2. `responses.py` — `@view` y response helpers

### 2.1 El decorador `@view`

```python
def view(full_template=None, partial_template=None,
         module_id=None, view_id=None,
         login_required=True, permissions=None) -> Callable:
    if isinstance(permissions, str):
        permissions = [permissions]

    def decorator(func):
        @wraps(func)
        async def wrapper(request, *args, **kwargs):
            settings = get_settings()

            # 1. Auth check
            if login_required:
                user_id = get_session_user_id(request)
                if user_id is None:
                    return RedirectResponse(settings.AUTH_LOGIN_URL, status_code=302)
                if permissions:
                    user_perms = getattr(request.state, "user_permissions", None)
                    if user_perms is None:
                        user_perms = await _resolve_permissions(request, user_id)
                        request.state.user_permissions = user_perms
                    if not all(has_permission(user_perms, p) for p in permissions):
                        return RedirectResponse(settings.AUTH_UNAUTHORIZED_URL, status_code=302)

            # 2. Call the view function
            result = await func(request, *args, **kwargs)
            if isinstance(result, Response):
                return result   # Pre-built response, pass through

            context = result if isinstance(result, dict) else {}

            # 3. Build template context (page_title, current_path, ...)
            from hotframe.templating.globals import get_global_context
            context.update(await get_global_context(request))

            # 4. Resolve template
            templates = request.app.state.templates
            env_id = _register_env(templates.env)

            template = full_template or context.pop("template", None)
            if template is None and module_id and view_id:
                template = _resolve_template(env_id, module_id, view_id, "full")

            return templates.TemplateResponse(request, template, context)
        return wrapper
    return decorator
```

Decisiones:

1. **Auth + perms primero.** Si falla, redirect (302) — no se
   ejecuta el handler.
2. **Permisos cacheados en `request.state.user_permissions`.** Si
   ya los resolviste en otro middleware, el decorator los reusa.
3. **El handler devuelve un dict** (template context). Si devuelve
   un `Response`, passthrough.
4. **Template se resuelve por convención** vía `_resolve_template`.
5. **Auto-merge de `get_global_context`** — añade `current_path`,
   `page_title`, `messages`, etc.

### 2.2 Auto-discovery de templates

```python
_FULL_PATTERNS = (
    "{module}/pages/{view}.html",
    "{module}/pages/{view}_list.html",
    "{module}/pages/{view}_form.html",
    "{module}/pages/list.html",
    "{module}/pages/index.html",
)

_PARTIAL_PATTERNS = (
    "{module}/partials/{view}_content.html",
    "{module}/partials/{view}.html",
    "{module}/partials/{view}_list.html",
    "{module}/partials/{view}_form.html",
)

@lru_cache(maxsize=512)
def _resolve_template(env_id, module_id, view_id, kind):
    env = _ENV_BY_ID[env_id]
    patterns = _PARTIAL_PATTERNS if kind == "partial" else _FULL_PATTERNS
    candidates = [pat.format(module=module_id, view=view_id) for pat in patterns]
    if kind == "full" and view_id == "dashboard":
        candidates.insert(0, f"{module_id}/pages/index.html")
    for name in candidates:
        try:
            env.get_template(name)
            return name
        except TemplateNotFound:
            continue
    return candidates[0]   # falla mostrando el primer pattern
```

LRU-cache: 512 combinations cached. Borra al `refresh_template_dirs`
del template engine (cache no se invalida automáticamente — pero
en boot se construye con dir actuales, en hot-reload el primer
miss después actualiza).

`view_id="dashboard"` tiene un alias especial — `pages/index.html`
se prueba antes que `pages/dashboard.html`, así un módulo puede
declarar su home en `pages/index.html` directamente.

### 2.3 Response helpers — plain HTTP

```python
def reactive_redirect(url) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)

def reactive_refresh() -> HTMLResponse:
    return HTMLResponse(
        '<meta http-equiv="refresh" content="0">',
        status_code=200,
    )

def reactive_trigger(event_name, **detail) -> HTMLResponse:
    payload = json.dumps({"name": event_name, "detail": detail})
    return HTMLResponse(
        f'<script>window.dispatchEvent(new CustomEvent("{event_name}", {{detail: {json.dumps(detail)}}}));</script>',
        status_code=200,
    )

def reactive_message(level, text) -> HTMLResponse:
    return HTMLResponse(
        f'<div class="toast toast-{level}">{escape(text)}</div>',
        status_code=200,
    )
```

`htmx_redirect` etc. son aliases — `reactive_*` es el nombre canónico
hoy. Decisiones:

1. **303 See Other** para redirects POST→GET. Estándar HTTP, evita
   doble submit.
2. **`<meta refresh>` en lugar de header** — sirve igual y permite
   ver el HTML antes de refrescar.
3. **`reactive_trigger` emite CustomEvent.** Listeners con
   `addEventListener("eventName", ...)`.

`add_message(request, level, text)`:

```python
def add_message(request, level, text):
    if not hasattr(request.state, "_messages"):
        request.state._messages = []
    request.state._messages.append({"level": level, "text": text})
```

Los messages se replayean en el siguiente render via
`get_global_context`.

### 2.4 `is_reactive_request` y `is_htmx_request`

```python
def is_reactive_request(request) -> bool:
    return False     # always — live runtime is over WebSocket
```

Devuelve siempre `False`. Antes detectaba el header `HX-Request` de
HTMX; ahora no se usa porque la reactividad vive en `/ws/_live`.
La función se mantiene para que código legacy `if is_htmx_request(request): ...`
siga funcionando — siempre cae en la rama "full page render".

### 2.5 `sse_stream(generator)` — Server-Sent Events

```python
async def sse_stream(generator: AsyncGenerator) -> EventSourceResponse:
    return EventSourceResponse(generator)
```

Wrapper trivial sobre `sse_starlette.EventSourceResponse`. Útil
para responder con un stream SSE custom (e.g. log tailer):

```python
@router.get("/logs/stream")
async def stream_logs(request):
    async def gen():
        async for line in tail_logs():
            yield {"event": "log", "data": line}
    return await sse_stream(gen())
```

---

## 3. `broadcast.py` — `BroadcastHub`

### 3.1 ¿Qué es?

Topic-based fan-out **process-local** para emitir mensajes a todos
los clients suscritos a un topic via SSE o WS. Diferente del
`AsyncEventBus`: este es para clientes **browser**, no
subscribers Python.

### 3.2 La clase

```python
class BroadcastHub:
    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    async def subscribe(self, topic) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=64)
        self._subscribers[topic].add(queue)
        return queue

    async def unsubscribe(self, topic, queue):
        self._subscribers[topic].discard(queue)
        if not self._subscribers[topic]:
            del self._subscribers[topic]

    async def publish(self, topic, data) -> int:
        subscribers = self._subscribers.get(topic, set())
        delivered, stale = 0, []
        for queue in subscribers:
            try:
                queue.put_nowait(data)
                delivered += 1
            except asyncio.QueueFull:
                logger.warning("SSE queue full for topic=%s", topic)
                stale.append(queue)
        for q in stale:
            subscribers.discard(q)
        return delivered

    def topic_count(self) -> int:
        return len(self._subscribers)
```

Decisiones:

1. **`maxsize=64` por queue.** Si un cliente lento no consume,
   tras 64 mensajes en buffer se descarta el siguiente con
   warning. Evita bloquear al publisher.
2. **Process-local.** Si tienes multiple workers, un publish en uno
   no llega a los clients del otro. Solución: combinar con
   `PgNotifyBridge` para propagar via PostgreSQL LISTEN/NOTIFY.
3. **Cleanup automático.** Cuando un SSE client desconecta, su queue
   queda huérfana — `subscribe` la añadió, `unsubscribe` la quita.
   Si olvidan unsubscribe, GC del queue eventualmente la limpia
   pero el `_subscribers` set la sigue referenciando. Por eso
   exponemos `unsubscribe` y los endpoints lo llaman en `finally`.

### 3.3 Endpoints — `broadcast_router`

```python
broadcast_router = APIRouter(prefix="/stream", tags=["streaming"])

@broadcast_router.get("/{topic}")
async def stream_topic(request, topic, user: CurrentUser):
    hub = get_broadcast_hub(request)
    queue = await hub.subscribe(topic)
    async def gen():
        try:
            while True:
                data = await queue.get()
                yield {"data": data}
        finally:
            await hub.unsubscribe(topic, queue)
    return EventSourceResponse(gen())

@broadcast_router.get("/_mux")
async def stream_mux(request, topics: str, user: CurrentUser):
    """Multiplexed: ?topics=a,b,c yields events with `event` field per topic."""
    topic_list = topics.split(",")
    hub = get_broadcast_hub(request)
    queues = {t: await hub.subscribe(t) for t in topic_list}
    async def gen():
        try:
            while True:
                # Wait for any queue to have data
                done, pending = await asyncio.wait(
                    [q.get() for q in queues.values()],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    data = task.result()
                    yield {"event": ..., "data": data}
        finally:
            for t, q in queues.items():
                await hub.unsubscribe(t, q)
    return EventSourceResponse(gen())

@broadcast_router.websocket("/ws/{topic}")
async def stream_ws(websocket, topic):
    await websocket.accept()
    hub = websocket.app.state.broadcast_hub
    queue = await hub.subscribe(topic)
    try:
        while True:
            data = await queue.get()
            await websocket.send_text(data)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe(topic, queue)
```

Tres formas de conectar:
- **`GET /stream/{topic}`** — un topic, EventSource browser nativo.
- **`GET /stream/_mux?topics=a,b,c`** — multiplexed.
- **`WS /stream/ws/{topic}`** — WebSocket alternativo.

### 3.4 `get_broadcast_hub(request)` helper

```python
def get_broadcast_hub(request) -> BroadcastHub:
    return request.app.state.broadcast_hub
```

`bootstrap.lifespan` lo crea y stash en `app.state.broadcast_hub`.

### 3.5 Uso desde un módulo

```python
@router.post("/m/todos/create")
async def create_todo(request, db: DbSession, ...):
    todo = Todo(...)
    db.add(todo)
    await db.commit()
    rendered = render_todo_html(todo)
    hub = get_broadcast_hub(request)
    await hub.publish("todos", rendered)   # emit to all SSE clients
    return reactive_redirect("/todos")
```

Un cliente browser:

```js
const source = new EventSource('/stream/todos');
source.addEventListener('message', (e) => {
    document.getElementById('todo-list').insertAdjacentHTML('beforeend', e.data);
});
```

---

## 4. Cuándo usar cada cosa

| Necesidad | Solución |
|---|---|
| Renderizar página HTML con auth | `@view(...)` |
| Redirect después de POST | `reactive_redirect("/url")` |
| Mostrar toast | `add_message(...)` o `reactive_message(...)` |
| Reactive UI con state server | `LiveComponent` (ver `live.md`) |
| Push de updates a clients connected | `BroadcastHub.publish` + SSE/WS |
| Eventos in-process Python-to-Python | `AsyncEventBus` (ver `signals.md`) |

---

## 5. Decisiones de diseño que conviene recordar

1. **`@view` es opt-in.** Si quieres control fino, devuelve un
   `Response` directamente. El decorator pasa cualquier Response
   sin tocarlo.
2. **Auth + perms son responsabilidad de `@view`.** Si lo evitas,
   acuérdate de chequear manualmente.
3. **`is_reactive_request` siempre `False`.** Reactividad va por WS,
   no por header.
4. **`reactive_*` son helpers HTTP planos.** Sin headers HTMX,
   sin SSE custom — son standard responses.
5. **`BroadcastHub` es process-local.** Multi-worker requiere
   PgNotify u otra solución de fan-out.
6. **`maxsize=64` por queue.** Cliente lento → mensajes se
   descartan con warning, no bloquean al publisher.
7. **Subscriptions cleanup en `finally`** — crítico para no
   acumular queues fantasma.

---

## 6. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Template not found en `@view` | El path no coincide con los patterns. | Verifica que el módulo tenga `pages/{view}.html`, o pasa `template` en el dict. |
| Auth siempre redirige | Session no inicializada o cookie inválida. | `RobustSessionMiddleware` debería arreglarlo — verifica que está en stack. |
| Permissions chequeados infinitamente | Resolver lanza, fallback a empty list. | Mira el log del `_resolve_permissions`. |
| `BroadcastHub.publish` retorna 0 | Nadie suscrito al topic. | Es esperado — chequea que los clientes están conectados. |
| SSE se desconecta tras 30s | TimeoutMiddleware. | El SSE debe estar en una ruta sin timeout, o sube `TimeoutMiddleware(timeout=...)`. |
| Multi-worker, broadcast no llega a otros workers | Process-local. | Usa PgNotifyBridge para fan-out cross-worker. |
| `is_htmx_request` retorna False siempre | Es esperado — la API se mantiene pero el comportamiento cambió. | Migra a LiveComponent o full-page renders. |
