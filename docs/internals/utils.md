# utils.md — Observability (logging, metrics, telemetry, context)

> **Carpeta cubierta:** `src/hotframe/utils/`. Cinco archivos:
> `__init__.py`, `observability_context.py`, `observability_logging.py`,
> `observability_metrics.py`, `observability_telemetry.py`.
> Capa de observabilidad: structlog para logs estructurados,
> OpenTelemetry para traces y metrics, y un `RequestContext`
> compartido que viaja por contextvars.

---

## 1. `__init__.py`

Solo docstring. Imports explícitos:

```python
from hotframe.utils.observability_context import request_context, bind_context, update_context
from hotframe.utils.observability_logging import setup_logging, get_logger
from hotframe.utils.observability_telemetry import setup_telemetry, create_event_span, create_hook_span
from hotframe.utils.observability_metrics import (
    get_request_duration_histogram,
    get_module_load_duration_histogram,
    get_event_emit_counter,
    get_event_handler_duration_histogram,
    get_hook_callback_counter,
    get_hook_duration_histogram,
    get_active_modules_counter,
    get_error_counter,
)
```

---

## 2. `observability_context.py` — `RequestContext`

### 2.1 La dataclass

```python
@dataclass(slots=True)
class RequestContext:
    request_id: str = ""
    hub_id: str = ""
    user_id: str = ""
    module_id: str = ""
    trace_id: str = ""

    def bind_dict(self) -> dict[str, str]:
        # Returns only non-empty fields (for structlog binding)
        ...
```

Container "single source of truth" de los identificadores
request-scoped. Los logs, metrics, traces y eventos consultan
`request_context.get()` para enriquecerse automáticamente.

### 2.2 ContextVar

```python
request_context: ContextVar[RequestContext] = ContextVar(
    "request_context",
    default=RequestContext(),
)
```

`ContextVar` es seguro entre tasks asyncio. Cada task hereda el
context activo de su parent, pero modificarlo no afecta al parent
(copia-on-write).

### 2.3 `bind_context(**kwargs)` — context manager

```python
@contextmanager
def bind_context(**kwargs):
    previous = request_context.get()
    new_ctx = RequestContext(
        request_id=kwargs.get("request_id", previous.request_id),
        hub_id=kwargs.get("hub_id", previous.hub_id),
        user_id=kwargs.get("user_id", previous.user_id),
        module_id=kwargs.get("module_id", previous.module_id),
        trace_id=kwargs.get("trace_id", previous.trace_id),
    )
    token = request_context.set(new_ctx)
    try:
        yield new_ctx
    finally:
        request_context.reset(token)
```

Patrón: middleware setea al inicio del request, todo lo downstream
ve el context. Restaura al salir (incluso con excepciones).

```python
# RequestObservabilityMiddleware
with bind_context(request_id=req_id, hub_id=hub_id):
    response = await call_next(request)
    # logs, metrics, traces ven el contexto
```

### 2.4 `update_context(**kwargs)` — sin manager

```python
def update_context(**kwargs):
    current = request_context.get()
    new_ctx = RequestContext(
        request_id=kwargs.get("request_id", current.request_id),
        hub_id=kwargs.get("hub_id", current.hub_id),
        user_id=kwargs.get("user_id", current.user_id),
        ...
    )
    request_context.set(new_ctx)
```

Útil para añadir info **mid-request** (e.g. `user_id` después de
auth):

```python
async def login(request):
    user_id = await authenticate(...)
    update_context(user_id=str(user_id))   # logs from here on include user_id
```

---

## 3. `observability_logging.py` — structlog setup

### 3.1 `setup_logging(*, log_level, json_output)`

```python
def setup_logging(*, log_level="INFO", json_output=False):
    level = getattr(logging, log_level.upper(), logging.INFO)
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_request_context,             # <- inyecta RequestContext fields
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.CallsiteParameterAdder(parameters=[FILENAME, LINENO, FUNC_NAME]),
    ]
    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    structlog.configure(
        processors=[*shared_processors, format_exc_info, ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[ProcessorFormatter.remove_processors_meta, renderer],
        foreign_pre_chain=shared_processors,
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    # Suppress noisy third-party loggers
    for noisy in ("uvicorn.access", "watchfiles", "httpcore", "httpx", "hpack"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
```

Decisiones:

1. **`_add_request_context` processor** — inyecta `request_id`,
   `hub_id`, `user_id`, `module_id`, `trace_id` desde el ContextVar
   en cada log line.
2. **JSON en producción.** Cloud-native log aggregators (Datadog,
   CloudWatch Insights) parsean JSON.
3. **Console colored en dev.** structlog detecta TTY.
4. **Stdlib logging redireccionado** a structlog. `logger.info(...)`
   en código tradicional pasa por el mismo formatter.
5. **Suppress de noisy loggers** (uvicorn.access, httpx) — bajan
   a WARNING para no saturar.
6. **`cache_logger_on_first_use=True`** — evita reconfigurar
   structlog en cada `get_logger` call.

### 3.2 `get_logger(name=None)`

```python
def get_logger(name=None):
    return structlog.get_logger(name)
```

Drop-in replacement de `logging.getLogger`. El BoundLogger devuelto
incluye automáticamente todos los fields del context.

```python
log = get_logger(__name__)
log.info("user_action", action="signup", email="x@y.com")
# Output: {"timestamp":"...","level":"info","logger":"my.module","action":"signup","email":"x@y.com","request_id":"abc","hub_id":"...","user_id":"..."}
```

---

## 4. `observability_metrics.py` — OTEL metrics

Pre-defined instruments lazy-initialized:

```python
def get_request_duration_histogram() -> Histogram:
    """http.server.request.duration in ms"""

def get_module_load_duration_histogram() -> Histogram:
    """hotframe.module.load.duration in ms"""

def get_active_modules_counter() -> UpDownCounter:
    """hotframe.modules.active gauge"""

def get_event_emit_counter() -> Counter:
    """hotframe.events.emitted by event name"""

def get_event_handler_duration_histogram() -> Histogram:
    """hotframe.events.handler.duration ms by event+handler"""

def get_hook_callback_counter() -> Counter:
    """hotframe.hooks.callbacks by hook+type"""

def get_hook_duration_histogram() -> Histogram:
    """hotframe.hooks.duration in ms"""

def get_error_counter() -> Counter:
    """hotframe.errors by error.source + error.type + module_id"""
```

### 4.1 ¿Por qué lazy?

Si OTEL SDK no está configurado (api-only mode sin SDK), las
funciones devuelven instrumentos no-op. Eso significa que escribir:

```python
get_event_emit_counter().add(1, attributes={"event.name": event})
```

es **gratis** si no hay SDK configurado — no allocates, no I/O.

### 4.2 Usados desde

- `signals.dispatcher.AsyncEventBus.emit/emit_typed` — counter +
  duration histogram.
- `signals.hooks.HookRegistry.do_action/apply_filters` — callbacks
  counter + duration.
- `engine.module_runtime.boot/install/etc` — load duration y
  active counter.
- `middleware.observability.RequestObservabilityMiddleware` —
  request duration.
- Cada `error_counter().add(1, ...)` cuando un handler crashea.

---

## 5. `observability_telemetry.py` — OTEL traces

### 5.1 `setup_telemetry(*, service_name, debug, hub_id)`

```python
def setup_telemetry(*, service_name="hub", debug=False, hub_id=""):
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    resource_attrs = {
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: "0.1.0",
    }
    if hub_id:
        resource_attrs["hub.id"] = hub_id
    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    elif debug:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _setup_metrics_provider(otlp_endpoint, resource, debug)
    _auto_instrument_fastapi()
    _auto_instrument_sqlalchemy()
    _auto_instrument_httpx()
```

Decisiones:

1. **Auto-instrumentation de FastAPI, SQLAlchemy, httpx.** Cada
   request, query, y outbound HTTP genera spans automáticos.
2. **Exporter OTLP gRPC** si `OTEL_EXPORTER_OTLP_ENDPOINT` está
   definido. Sin endpoint y `debug=True` → console exporter.
3. **Sin endpoint, sin debug → no exporter.** Spans se generan
   pero no se exportan; cero overhead aparte de la generación.
4. **`hub.id` como resource attribute.** Aparece en cada span;
   utilísimo para filtrar traces por tenant.
5. **`bootstrap.create_app` skipea telemetry bajo pytest** — el
   `BatchSpanProcessor` con console exporter rompía CI.

### 5.2 Helpers de spans custom

```python
def create_event_span(event_name) -> AbstractContextManager[Span]:
    """Span 'event:<name>' para emitir eventos."""

def create_hook_span(hook_name, hook_type) -> AbstractContextManager[Span]:
    """Span 'hook:<name>:<type>' para acciones/filtros."""
```

Los usan `signals.dispatcher` y `signals.hooks` para envolver cada
emisión/invocación. Resultado: en Jaeger/Tempo ves un trace con:

```
HTTP POST /m/sales/create
├─ span: db.execute (CREATE TABLE)
├─ span: event:sale.created
│   ├─ event.handler_count = 3
│   └─ event.error_count = 0
├─ span: hook:sale.before_complete:action
└─ span: http.client (POST stripe/charges)
```

---

## 6. Cómo se enchufa todo

```
┌──────────────────────────────────────────────────────────────┐
│ bootstrap.create_app                                          │
│   setup_logging(log_level=settings.LOG_LEVEL, json_output=...)│
│   setup_telemetry(debug=settings.DEBUG, ...)                  │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│ middleware.RequestObservabilityMiddleware                     │
│   t0 = time.monotonic()                                       │
│   with bind_context(request_id=request_id, ...):              │
│     response = await call_next(request)                       │
│     duration = (time.monotonic() - t0) * 1000                 │
│     get_request_duration_histogram().record(duration, attrs)  │
│     logger.info("...", method=..., status=..., duration=...)  │
└──────────────────────────────────────────────────────────────┘
                          │
                          ▼
        Logs (structlog)         Metrics (OTLP)        Traces (OTLP)
              │                       │                      │
              ▼                       ▼                      ▼
         CloudWatch /             Datadog /              Jaeger /
         Datadog Logs             Prometheus             Tempo
```

Todos comparten el mismo `RequestContext`. Una request_id en logs
te lleva al trace en Jaeger, te lleva al user_id en Datadog metrics.

---

## 7. Decisiones de diseño que conviene recordar

1. **`RequestContext` como single source of truth.** Cada subsystem
   (logs, metrics, traces, signals) lo consulta — coherencia
   garantizada.
2. **Lazy initialization.** Sin SDK → no-op silencioso. Sin
   `OTEL_EXPORTER_OTLP_ENDPOINT` → spans en memoria que se descartan.
3. **Suppress noise.** Stdlib loggers de uvicorn/httpx bajan a
   WARNING para que el pipeline de logs sea readable.
4. **Auto-instrumentation.** FastAPI, SQLAlchemy, httpx generan
   spans sin código custom.
5. **`bind_context` en middleware.** El context activo está
   disponible para todo lo que se ejecute durante el request.
6. **`update_context` para info mid-request.** Patrón "auth tarda
   un poco — añadir user_id cuando se sepa".
7. **`bootstrap` skipea telemetry bajo pytest.** El BatchProcessor
   + console exporter rompía CI con "I/O on closed file".

---

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Logs sin `request_id` | Middleware de correlation no en stack. | Verifica `asgi_correlation_id.CorrelationIdMiddleware` en `MIDDLEWARE`. |
| Spans no aparecen en Jaeger | `OTEL_EXPORTER_OTLP_ENDPOINT` no seteado o exporter no instalado. | Pip install `opentelemetry-exporter-otlp-proto-grpc` y configura env. |
| `user_id` siempre vacío en logs | No llamaste `update_context(user_id=...)` después de auth. | Hazlo en el middleware/dependency de auth. |
| Logs en JSON local en dev | `LOG_FORMAT=json` o `is_production`. | Cambia a `LOG_FORMAT=console`. |
| Tests crashean con "I/O on closed file" | Telemetry intentando exportar tras pytest cierre. | Bootstrap ya skipea con `"pytest" in sys.modules` — verifica que no override. |
| Metrics no aparecen | OTEL metrics provider no inicializado. | Mira `setup_telemetry` — usa `_setup_metrics_provider`. |
| `hub_id` aparece como string vacío | `bind_context` no incluyó `hub_id`. | Setea explícitamente o usa `update_context`. |
