# live.md — Stateful WebSocket-driven components (LiveView)

> **Carpeta cubierta:** `src/hotframe/live/`. Diez archivos:
> `__init__.py`, `base.py`, `decorators.py`, `protocol.py`, `diff.py`,
> `session.py`, `runtime.py`, `ws.py`, `jinja_ext.py`, `assets.py`,
> más `static/live.js` y `static/morphdom.min.js` vendorizados.
> Es la implementación de **server-driven reactive UI** estilo Phoenix
> LiveView, sin escribir JS y sin Datastar/HTMX.

---

## 1. ¿Qué hace este subsistema?

Permite escribir componentes **stateful en Python** cuyo HTML se
re-renderiza en el server y se envía al cliente como patches via
WebSocket. El cliente (`live.js`) aplica los patches con `morphdom`
preservando focus/scroll/selection.

```python
class TodoList(LiveComponent):
    user_id: int       # prop
    items: list = []   # state

    async def on_mount(self):
        self.items = await Todo.where(user_id=self.user_id).all()

    @event("toggle")
    async def toggle(self, todo_id: str):
        t = next(x for x in self.items if str(x.id) == todo_id)
        t.done = not t.done
        await t.save()
```

```jinja
{# template.html #}
<ul>
{% for todo in items %}
  <li><input type="checkbox" {% if todo.done %}checked{% endif %}
      data-on:click="toggle:{{ todo.id }}"> {{ todo.text }}</li>
{% endfor %}
</ul>
```

```jinja
{# page.html #}
{{ live_assets() }}
{% live "todo_list" user_id=user.id %}
```

Cada click manda `{"t":"event","cid":"...","n":"toggle","p":"42"}`
por WS. El handler corre, se re-renderiza, vuelve un `{"t":"patch",
"cid":"...","html":"<ul>..."}` y morphdom lo aplica.

---

## 2. `__init__.py` — fachada

```python
from hotframe.live.base import LiveComponent
from hotframe.live.decorators import event, get_event_name
from hotframe.live.runtime import LiveRuntime, get_runtime
from hotframe.live.session import LiveSession
from hotframe.live.ws import live_router

__all__ = ["LiveComponent", "LiveRuntime", "LiveSession",
           "event", "get_event_name", "get_runtime", "live_router"]
```

Toda la API pública vive aquí. Re-exportada desde `hotframe` raíz.

---

## 3. `base.py` — `LiveComponent`

Hereda de `pydantic.BaseModel`. Construido con campos como props +
state, decoradores `@event`, hooks `on_mount`/`on_unmount`.

### 3.1 La clase

```python
class LiveComponent(BaseModel):
    model_config = {
        "validate_assignment": True,    # types checked on every mutation
        "arbitrary_types_allowed": True,
    }

    _events: ClassVar[dict[str, Callable]] = {}
    _cid: PrivateAttr = PrivateAttr(default="")
    _session: PrivateAttr = PrivateAttr(default=None)
    _component_name: PrivateAttr = PrivateAttr(default="")
    _last_html: PrivateAttr = PrivateAttr(default=None)

    @property
    def cid(self) -> str: return self._cid
    @property
    def session(self): return self._session

    async def on_mount(self): pass
    async def on_unmount(self): pass

    def render_context(self) -> dict:
        ctx = self.model_dump()
        ctx.update(self.extra_context())
        return ctx

    def extra_context(self) -> dict:
        return {}

    async def navigate(self, url: str):
        if self._session: await self._session.send_nav(url)

    async def toast(self, message, level="info"):
        if self._session: await self._session.send_toast(level, message)
```

### 3.2 `__init_subclass__` — recolecta `@event` handlers

```python
def __init_subclass__(cls, **kwargs):
    super().__init_subclass__(**kwargs)
    cls._events = {}
    for name in dir(cls):
        attr = getattr(cls, name, None)
        event_name = getattr(attr, "__hf_live_event__", None)
        if event_name is None:
            continue
        if not asyncio.iscoroutinefunction(attr):
            raise TypeError(
                f"@event handler {cls.__name__}.{name} must be async")
        cls._events[event_name] = attr
```

Cada subclase tiene su propio `_events` dict. La clase base lo
inicializa vacío para que un subclass no herede los events del
padre — son tabla isolada.

`render_context()` se llama desde `diff.render_component_inner` para
construir el contexto pasado al template.

`navigate()` y `toast()` se invocan desde dentro de un event
handler para emitir mensajes server→cliente que `live.js` interpreta.

### 3.3 `validate_assignment=True`

Cualquier `self.value = "not-int"` con `value: int` lanza
`ValidationError`. Garantiza que el state nunca queda en estado
inválido entre eventos.

---

## 4. `decorators.py` — `@event(name)`

```python
def event(name: str):
    def decorator(fn):
        fn.__hf_live_event__ = name
        return fn
    return decorator

def get_event_name(fn) -> str | None:
    return getattr(fn, "__hf_live_event__", None)
```

Decisión: **stamp en lugar de wrap**. La función queda tal cual,
solo con un atributo `__hf_live_event__`. `__init_subclass__` la
recoge. Sin wrap → no overhead, no polución de signatures.

---

## 5. `protocol.py` — wire format

TypedDicts para validación estática:

### Cliente → Server

```python
class AttachMessage(TypedDict):
    t: Literal["attach"]
    cid: str
    name: str
    props: dict

class EventMessage(TypedDict):
    t: Literal["event"]
    cid: str
    n: str  # event name
    p: Any  # payload (string or object)

class BindMessage(TypedDict):
    t: Literal["bind"]
    cid: str
    f: str  # field name
    v: Any  # value

class DetachMessage(TypedDict):
    t: Literal["detach"]
    cid: str
```

### Server → Cliente

```python
class PatchMessage(TypedDict):
    t: Literal["patch"]
    cid: str
    html: str

class NavMessage(TypedDict):
    t: Literal["nav"]
    url: str

class ErrMessage(TypedDict):
    t: Literal["err"]
    cid: str | None
    code: str  # not_found | props | mount | not_attached | handler
    msg: str

class ToastMessage(TypedDict):
    t: Literal["toast"]
    level: str
    msg: str
```

Helpers `make_patch(cid, html) -> PatchMessage`, `make_err(...)`, etc.
Single-letter type discriminator (`t`) por economía en ancho de banda.

---

## 6. `diff.py` — render

```python
async def render_component_inner(env, instance) -> str:
    """Render only the component's template, without the wrapper."""
    template_path = f"{instance._component_name}/template.html"
    template = env.get_template(template_path)
    ctx = instance.render_context()
    return template.render(**ctx)

def wrap_with_envelope(name, cid, props, inner_html) -> str:
    """Wrap with <div data-hf-cid=...> envelope for cold load."""
    props_json = json.dumps(props)
    return (f'<div data-hf-cid="{cid}" data-hf-component="{name}" '
            f'data-hf-props=\'{escape(props_json)}\'>{inner_html}</div>')

async def render_initial_html(env, name, props, registry) -> tuple[str, str]:
    """Cold-load path: instantiate, mount, render, wrap."""
    entry = registry.get(name)
    instance = entry.props_cls(**props)
    cid = f"c-{uuid.uuid4().hex[:8]}"
    instance._cid = cid
    instance._component_name = name
    await instance.on_mount()
    inner = await render_component_inner(env, instance)
    return cid, wrap_with_envelope(name, cid, props, inner)
```

Decisión: el HTML **inicial** se envuelve con el `data-hf-cid`
envelope, pero los **patches** posteriores son solo el inner HTML
(morphdom recibe el contenido del wrapper, no el wrapper).

---

## 7. `session.py` — `LiveSession` (per-WS)

```python
class LiveSession:
    def __init__(self, session_id, websocket, runtime):
        self.id = session_id
        self.ws = websocket
        self.runtime = runtime
        self.components: dict[str, LiveComponent] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def handle_message(self, msg: dict):
        match msg.get("t"):
            case "attach": await self._attach(msg)
            case "event":  await self._event(msg)
            case "bind":   await self._bind(msg)
            case "detach": await self._detach(msg)
            case _: logger.warning("Unknown msg type: %r", msg.get("t"))

    async def _attach(self, msg):
        entry = self.runtime.registry.get(msg["name"])
        if not entry or not entry.is_live:
            return await self._send_err(msg["cid"], "not_found",
                                        f"Component {msg['name']!r} not found")
        try:
            instance = entry.props_cls(**msg.get("props", {}))
        except ValidationError as e:
            return await self._send_err(msg["cid"], "props", str(e))
        instance._cid = msg["cid"]
        instance._component_name = msg["name"]
        instance._session = self
        try:
            await instance.on_mount()
        except Exception as e:
            return await self._send_err(msg["cid"], "mount", str(e))
        self.components[msg["cid"]] = instance
        await self._render_and_send(instance)

    async def _event(self, msg):
        cid = msg["cid"]
        instance = self.components.get(cid)
        if not instance:
            return await self._send_err(cid, "not_attached", "...")
        handler = type(instance)._events.get(msg["n"])
        if not handler:
            return await self._send_err(cid, "not_found", f"Unknown event {msg['n']!r}")
        async with self._locks.setdefault(cid, asyncio.Lock()):
            try:
                await self._invoke_handler(handler, instance, msg.get("p"))
            except Exception as e:
                return await self._send_err(cid, "handler", str(e))
            await self._render_and_send(instance)

    async def _bind(self, msg):
        instance = self.components.get(msg["cid"])
        if not instance: return
        try:
            setattr(instance, msg["f"], msg["v"])
            # bind never triggers re-render
        except ValidationError as e:
            await self._send_err(msg["cid"], "props", str(e))

    async def _detach(self, msg):
        instance = self.components.pop(msg["cid"], None)
        if instance:
            try:
                await instance.on_unmount()
            except Exception:
                logger.exception("...")

    async def _invoke_handler(self, handler, instance, payload):
        sig = inspect.signature(handler)
        params = list(sig.parameters.values())[1:]  # skip self
        if not params:
            return await handler(instance)
        if len(params) == 1:
            return await handler(instance, payload)
        # Multi-arg: payload must be a dict
        if isinstance(payload, dict):
            return await handler(instance, **payload)
        raise TypeError(f"Handler expects dict payload, got {type(payload)}")

    async def _render_and_send(self, instance):
        html = await render_component_inner(self.runtime.env, instance)
        if html == instance._last_html:
            return  # no-op skip
        instance._last_html = html
        await self.ws.send_json({"t": "patch", "cid": instance._cid, "html": html})

    async def send_nav(self, url):
        await self.ws.send_json({"t": "nav", "url": url})

    async def send_toast(self, level, msg):
        await self.ws.send_json({"t": "toast", "level": level, "msg": msg})

    async def shutdown(self):
        for inst in list(self.components.values()):
            try: await inst.on_unmount()
            except Exception: logger.exception("...")
        self.components.clear()
```

Decisiones:

1. **`asyncio.Lock` por `cid`.** Eventos del mismo componente se
   serializan — no hay concurrencia interna.
2. **Diff trivial.** Comparamos `html == _last_html`; si idéntico,
   no enviamos patch. Reduce trafico cuando un evento no cambia el
   render.
3. **Errores categorizados.** `not_found`, `props`, `mount`,
   `not_attached`, `handler` — el cliente puede actuar distinto en
   cada caso.
4. **`bind` nunca re-renderiza.** Es un signal "actualiza state, no
   pintes". Útil para inputs que no quieres rerender en cada keystroke.

---

## 8. `runtime.py` — `LiveRuntime` (per-app)

```python
class LiveRuntime:
    def __init__(self, registry, env):
        self.registry = registry
        self.env = env
        self._sessions: dict[str, LiveSession] = {}

    async def open_session(self, session_id, websocket) -> LiveSession:
        session = LiveSession(session_id, websocket, self)
        self._sessions[session_id] = session
        return session

    async def close_session(self, session_id):
        session = self._sessions.pop(session_id, None)
        if session: await session.shutdown()

    async def shutdown(self):
        for session in list(self._sessions.values()):
            await session.shutdown()
        self._sessions.clear()


def get_runtime(request_or_app) -> LiveRuntime:
    """Helper to retrieve the runtime from request.app.state.live."""
```

Singleton del proceso. `bootstrap.lifespan` lo crea con
`LiveRuntime(components_registry, jinja_env)` y lo guarda en
`app.state.live`.

---

## 9. `ws.py` — `/ws/_live` endpoint

```python
live_router = APIRouter()

@live_router.websocket("/ws/_live")
async def live_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = await _resolve_session_id(websocket)
    runtime: LiveRuntime = websocket.app.state.live
    session = await runtime.open_session(session_id, websocket)
    try:
        while True:
            msg = await websocket.receive_json()
            await session.handle_message(msg)
    except WebSocketDisconnect:
        pass
    finally:
        await runtime.close_session(session_id)


async def _resolve_session_id(websocket) -> str:
    # 4 fallback levels:
    # 1. SignedSession cookie (Starlette session middleware)
    # 2. Custom Authorization header (for tests / non-cookie clients)
    # 3. Query param ?session_id=...
    # 4. random UUID4 fallback
```

`session_id` identifica la sesión a través de reconexiones. Si el
cliente reabre el WS (reconnect), `live.js` envía `attach` por cada
componente visible — el server reconstruye desde props +
`on_mount` (idempotente by design).

---

## 10. `jinja_ext.py` — `{% live %}` tag

```python
class LiveExtension(Extension):
    tags = {"live"}
    def parse(self, parser):
        # Parse: {% live "name" prop1=val1 prop2=val2 %}
        ...
        return CallBlock(self.call_method("_render_live", ...), ...)

    def _render_live(self, name, **props):
        env = self.environment
        registry = env.globals.get("_hotframe_components")
        runtime = ... # resolve from env or app
        cid, html = _run_async(render_initial_html(env, name, props, registry))
        return Markup(html)


def _run_async(coro):
    """Run a coroutine from sync code — uses asyncio.run if no loop running,
    otherwise creates a new loop on a thread."""
```

`_run_async` resuelve el problema de "Jinja es sync, `on_mount` es
async". Si no hay loop, usa `asyncio.run`. Si hay (raro en SSR puro),
lo dispatch a un thread con su propio loop.

---

## 11. `assets.py` — `live_assets()` Jinja global

```python
def live_assets(static_url="/static/hotframe") -> Markup:
    return Markup(
        f'<script src="{static_url}/morphdom.min.js" defer></script>\n'
        f'<script src="{static_url}/live.js" defer></script>'
    )

def register_live_globals(env):
    env.globals["live_assets"] = live_assets
```

Llamado desde el template: `{{ live_assets() }}` dentro de `<head>`.
Dos `<script>` con `defer` para que carguen en orden y no bloqueen
el parse.

---

## 12. `static/live.js` — el cliente (335 LOC ES5)

Sin TypeScript, sin build — JS plano que funciona en todos los
navegadores modernos.

### 12.1 Clase `LiveClient`

```javascript
class LiveClient {
  constructor(endpoint = "/ws/_live") {
    this.endpoint = endpoint;
    this.queue = [];          // outgoing events while disconnected
    this.backoffMs = 250;
    this.maxBackoff = 10000;
    this.bindDebounce = {};   // per-element timers
    this.connect();
    document.addEventListener("DOMContentLoaded", () => this.attachAll());
    this.bindEvents();
  }

  connect() {
    const url = (location.protocol === "https:" ? "wss:" : "ws:") +
                "//" + location.host + this.endpoint;
    this.ws = new WebSocket(url);
    this.ws.onopen = () => {
      this.backoffMs = 250;
      this.queue.forEach(m => this.ws.send(JSON.stringify(m)));
      this.queue = [];
      this.attachAll();
    };
    this.ws.onmessage = (e) => this.handle(JSON.parse(e.data));
    this.ws.onclose = () => {
      setTimeout(() => this.connect(), this.backoffMs);
      this.backoffMs = Math.min(this.maxBackoff, this.backoffMs * 2);
    };
  }

  send(msg) {
    if (this.ws && this.ws.readyState === 1) {
      this.ws.send(JSON.stringify(msg));
    } else {
      this.queue.push(msg);
    }
  }
}
```

### 12.2 Attach loop

```javascript
attachAll() {
  document.querySelectorAll("[data-hf-cid]").forEach(el => {
    const props = JSON.parse(el.getAttribute("data-hf-props") || "{}");
    this.send({
      t: "attach",
      cid: el.getAttribute("data-hf-cid"),
      name: el.getAttribute("data-hf-component"),
      props: props,
    });
  });
}
```

### 12.3 Event capture

```javascript
bindEvents() {
  document.addEventListener("click", (e) => {
    const target = e.target.closest("[data-on\\:click]");
    if (!target) return;
    const expr = target.getAttribute("data-on:click");
    const [name, payload] = expr.split(":", 2);
    const cid = this._findCid(target);
    this.send({t: "event", cid, n: name, p: payload || null});
  });
  document.addEventListener("submit", (e) => {
    const form = e.target.closest("[data-on\\:submit]");
    if (!form) return;
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    this.send({t: "event", cid: this._findCid(form),
               n: form.getAttribute("data-on:submit"), p: data});
  });
  document.addEventListener("input", (e) => {
    const el = e.target.closest("[data-bind]");
    if (!el) return;
    const field = el.getAttribute("data-bind");
    const cid = this._findCid(el);
    clearTimeout(this.bindDebounce[cid + ":" + field]);
    this.bindDebounce[cid + ":" + field] = setTimeout(() => {
      this.send({t: "bind", cid, f: field, v: el.value});
    }, 250);
  });
}

_findCid(el) {
  const wrapper = el.closest("[data-hf-cid]");
  return wrapper ? wrapper.getAttribute("data-hf-cid") : null;
}
```

### 12.4 Patch handler con morphdom

```javascript
handle(msg) {
  switch (msg.t) {
    case "patch": {
      const wrapper = document.querySelector(`[data-hf-cid="${msg.cid}"]`);
      if (!wrapper) return;
      morphdom(wrapper, "<div data-hf-cid='" + msg.cid + "'>" + msg.html + "</div>", {
        onBeforeElUpdated: (from, to) => {
          // Preserve focus on inputs
          if (from === document.activeElement) {
            to.value = from.value;
            to.selectionStart = from.selectionStart;
            to.selectionEnd = from.selectionEnd;
          }
          return true;
        },
      });
      break;
    }
    case "nav": window.location.href = msg.url; break;
    case "toast": dispatchEvent(new CustomEvent("hf:toast", {detail: msg})); break;
    case "err": console.error("[hotframe.live]", msg); break;
  }
}

new LiveClient();
```

`onBeforeElUpdated` preserva focus, value y selección de inputs —
crítico para que escribir en un input no se rompa al re-render.

---

## 13. Decisiones de diseño que conviene recordar

1. **Sticky session implícito.** State vive en RAM por WS. Multi-worker
   sin sticky requiere Redis (no implementado).
2. **`on_mount` debe ser idempotente.** Reconexión re-llama
   `on_mount` — diseña tu state para que pueda reconstruirse desde
   props + DB.
3. **No guardes asyncio.Tasks vivos en `self`.** Reconnect descarta
   la instancia. Tasks que sobreviven causan leaks.
4. **`bind` no re-renderiza.** Es signal de input → state. El render
   sigue solo cuando el siguiente `event` llega.
5. **Lock por `cid`.** Eventos del mismo componente se serializan.
6. **Diff trivial (html ==).** No AST tag-and-track como Phoenix.
   Si el render rinde idéntico, no hay patch.
7. **`@event` stamp, no wrap.** Cero overhead.
8. **`live.js` es ES5 vendorizado.** Sin TypeScript, sin build, sin
   versiones JS rotas. ~12 KB con morphdom incluido.
9. **`__init_subclass__`** construye `_events` en cada subclase. Si
   un subclass redefine un handler, sobreescribe.
10. **Reactividad solo en hub-side.** Cloud sigue con Datastar/HTMX
    según `.todo/`. Live runtime es solo para hotframe consumidores.

---

## 14. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| Componente no monta — `not_found` | El name no está registrado o no es subclase de `LiveComponent`. | Verifica discovery: `print(registry.list_components())`. |
| `props` error en attach | Props no validan contra Pydantic. | Mira `msg.msg` — lista los campos inválidos. |
| `mount` error | Excepción en `on_mount`. | Logs del server tienen el traceback. Casi siempre es DB. |
| Reconexión pierde state | `on_mount` no es idempotente o tira de DB que cambió. | Reescribe `on_mount` para que sea reconstruible. |
| Focus se pierde al re-render | El input se reemplaza. | morphdom debería preservarlo — verifica que el input tiene `id` o `name`. |
| Eventos lentos | Renders pesados (DB queries, etc.). | Mueve I/O fuera de `on_mount` con caching, o splittea en componentes más pequeños. |
| WS se desconecta tras 30s | Proxy con timeout corto. | Configura el proxy (CloudFront, nginx) con timeout >5min. |
| Multi-worker, state pierde | Sin sticky sessions. | Configura sticky en LB o migra a Redis-backed sessions. |
