# components.md — Reusable UI components subsystem

> **Carpeta cubierta:** `src/hotframe/components/`. Ocho archivos:
> `__init__.py`, `base.py`, `entry.py`, `registry.py`, `discovery.py`,
> `mounting.py`, `rendering.py`, `jinja_ext.py`.
> Cubre los **componentes reutilizables stateless** — el equivalente
> server-side a un "function component" de React. Para componentes
> stateful (LiveView), ver `live.md`.

---

## 1. ¿Qué problema resuelve este subsistema?

Antes de los componentes, una macro Jinja como `{{ button(...) }}`
era el patrón estándar — pero las macros tienen tres limitaciones:

1. **No hay validación de props.** Si pasas `button(varient="primary")`
   (typo), ni Jinja ni Python te avisan.
2. **No tienen ciclo de vida.** No pueden montar/desmontar un router,
   ni servir static propio.
3. **Difíciles de empaquetar.** Una macro vive en un `.html` suelto;
   un módulo no puede "shipear" un set coherente de UI.

`hotframe.components` introduce el **componente como unidad
empaquetada** con:

- **Carpeta dedicada** — `apps/<app>/components/<name>/` o
  `modules/<id>/components/<name>/`.
- **Schema Pydantic opcional** (`component.py` con clase
  `Component`).
- **Router opcional** (`routes.py` con `router: APIRouter`).
- **Static propio opcional** (`static/`).
- **Auto-discovery** al boot + en `module install`.
- **Auto-cleanup** en `module uninstall`.

Templates pueden invocarlos de dos formas:

```jinja
{# Función (sin body) #}
{{ render_component('badge', text='New', variant='primary') }}

{# Tag (con body) #}
{% component 'alert' type='warning' dismissible=true %}
    Stock is low
{% endcomponent %}
```

---

## 2. `__init__.py` — fachada del paquete

Reexporta todo lo público:

```python
from hotframe.components.base import Component
from hotframe.components.entry import ComponentEntry
from hotframe.components.mounting import (
    mount_component_routers, mount_component_routers_for_module,
    mount_component_static, mount_component_static_for_module,
    unmount_component_router, unmount_component_routers_for_module,
    unmount_component_static, unmount_component_static_for_module,
)
from hotframe.components.registry import ComponentRegistry
```

Note que `discover_*` y `render_component` **no** se reexportan aquí —
son utilizados solo por `bootstrap.py` (discovery) y por el motor de
templates (rendering). El usuario nunca los importa.

---

## 3. `base.py` — la clase `Component`

```python
class Component(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    def context(self) -> dict:
        return {}
```

### 3.1 Decisiones

- **Es `BaseModel` puro de Pydantic.** No hereda nada extra. Quien
  declare props, lo hace como un Pydantic normal: tipos, validators,
  defaults, alias, etc.
- **`arbitrary_types_allowed=True`.** Permite props como
  `request: Request`, `db: AsyncSession`, etc. Sin esto, Pydantic
  rechazaba clases no-pydantic.
- **`context()` opcional.** Si necesitas valores derivados:

  ```python
  class MediaPicker(Component):
      path: str
      multiple: bool = False
      accept: str = "image/*"

      def context(self):
          return {"accept_list": self.accept.split(",")}
  ```

  El template recibe `path`, `multiple`, `accept` **y** `accept_list`.
- **Sync, no async.** Jinja2 environment de hotframe es sync, así que
  `context()` también lo es. Si necesitas I/O dentro de un componente,
  estás en territorio de `LiveComponent`.

### 3.2 Cuándo NO usar `Component`

- Si no necesitas validación: declara solo `template.html` (template-only).
  Usa Jinja `{{ var | default('x') }}` para defaults.
- Si necesitas estado server-side persistente entre eventos: usa
  `LiveComponent`. Hereda de Pydantic también pero por el camino del
  live runtime, no del registry de componentes stateless.

---

## 4. `entry.py` — `ComponentEntry`

Dataclass `slots=True` que describe un componente registrado:

```python
@dataclass(slots=True)
class ComponentEntry:
    name: str
    template: str
    has_endpoint: bool = False
    render_fn: Callable[..., dict[str, Any]] | None = None
    extra_router: APIRouter | None = None
    module_id: str | None = None
    static_dir: str | None = None
    props_cls: type | None = None
    is_live: bool = False
```

### 4.1 Cada campo, qué hace y quién lo lee

- `name`: identificador único. Lo que el template usa
  (`render_component('button', ...)`).
- `template`: ruta Jinja relativa al loader. Ej:
  `"ui/button/template.html"`.
- `has_endpoint`: `True` si tiene `routes.py`. Es solo "informativo"
  para introspección — el mounting decide en base a `extra_router`.
- `render_fn`: opcional. Si está, se llama con los props y retorna el
  dict de contexto. Si es `None`, los props pasan crudos al template.
- `extra_router`: el `APIRouter` cargado de `routes.py`, o `None`.
  `mounting.py` lo monta en `/_components/<name>/`.
- `module_id`: dueño del componente. `None` para apps. Lo usa
  `ComponentRegistry.unregister_module` para barrer todo lo que un
  módulo registró.
- `static_dir`: ruta absoluta a `static/` si existe. `mounting.py`
  monta StaticFiles en `/_components/<name>/static/`.
- `props_cls`: subclase de `Component` o `LiveComponent`, si la había.
- `is_live`: `True` si `props_cls` es subclase de `LiveComponent`.
  Set por discovery, leído por mounting/rendering para evitar el
  `issubclass` en cada render.

### 4.2 Por qué `slots=True`

Más rápido en construcción y acceso, menor memoria (sin `__dict__`).
Para una dataclass leída en cada render del template, el coste se nota.

---

## 5. `registry.py` — `ComponentRegistry`

Diccionario plano `dict[str, ComponentEntry]` con:

```python
class ComponentRegistry:
    def __init__(self):
        self._components: dict[str, ComponentEntry] = {}

    def register(self, entry, *, module_id=None) -> None: ...
    def unregister(self, name: str) -> None: ...
    def unregister_module(self, module_id: str) -> None: ...
    def get(self, name: str) -> ComponentEntry | None: ...
    def has(self, name: str) -> bool: ...
    def list_components(self) -> list[ComponentEntry]: ...
    def clear(self) -> None: ...
    def __len__(self), __contains__(self, name), __repr__(self): ...
```

### 5.1 Decisiones

- **Sobreescritura con warning.** Si ya hay un componente con el
  mismo `name`:

  ```python
  if entry.name in self._components:
      previous = self._components[entry.name]
      logger.warning(
          "Component name collision: %r is being overwritten "
          "(previous module=%s, new module=%s)",
          entry.name, previous.module_id, entry.module_id,
      )
  self._components[entry.name] = entry
  ```

  Es intencional: en dev, recargar un módulo redefine sus componentes.
  Si fuera un error duro, cada hot-reload crashearía. La advertencia
  es suficiente para detectar conflictos reales en prod.

- **`unregister_module(module_id)`** itera el dict, recoge todas las
  entries con ese `module_id`, y las borra. Llamado por
  `ModuleLoader` en uninstall y en rollback de install fallido.

- **`module_id` se puede sobrescribir en `register()`.** Si pasas
  `register(entry, module_id="X")`, hace `entry.module_id = X`. Esto
  garantiza que la entry que termine en el registry siempre tenga su
  ownership correcto, aunque el caller lo haya construido sin
  setearlo.

- **Sin lock.** Discovery corre síncronamente en single thread (boot
  + module install path). Si en el futuro alguien quiere registrar en
  caliente desde un handler async, habría que añadir un `asyncio.Lock`.

---

## 6. `discovery.py` — escaneo del filesystem

Sin estado. Funciones puras que escanean carpetas y devuelven
`ComponentEntry`s. Las funciones públicas son:

- `discover_components(root, *, module_id, template_search_prefix, import_prefix)`
- `discover_module_components(registry, module_dir, module_id)`
- `discover_app_components(registry, apps_dir, app_name)`
- `discover_apps_components(registry, apps_dir)` — barrido de todos los apps

### 6.1 `discover_components(root, ...)` — el motor

Para cada subdirectorio inmediato de `root`:

1. **Skip dotfiles y `_*`** (incluye `__pycache__`).
2. **Requiere `template.html`.** Sin él, log warning + skip.
3. **`component.py` opcional** — si existe:
   - `_load_module_from_file` con `importlib.util.spec_from_file_location`
     (porque `modules/<id>/components/<name>/component.py` no está en
     `sys.path` como package dotted).
   - `_find_component_class` busca primera clase declarada en el
     fichero que sea subclase de `Component` o `LiveComponent` (no la
     base misma).
4. **Live detection** — si `props_cls` es subclase de `LiveComponent`,
   se marca `is_live=True`. Import local de `LiveComponent` para
   evitar import circular (`live` importa de `components`).
5. **`routes.py` opcional** — si existe, importa y busca atributo
   módulo `router`. Si lo hay, `extra_router=router` y
   `has_endpoint=True`.
6. **`static/` opcional** — si existe la subcarpeta, `static_dir=str(path)`.
7. **Construye `ComponentEntry`** con todo lo anterior + `render_fn` que
   sale de `_build_render_fn(props_cls)`.

### 6.2 `_build_render_fn(props_cls)`

```python
def _build_render_fn(props_cls):
    if props_cls is None:
        return None
    from hotframe.live.base import LiveComponent
    if issubclass(props_cls, LiveComponent):
        return None  # live runtime tiene su propio path
    if not issubclass(props_cls, Component):
        return None  # clase desconocida → fallback template-only

    def render_fn(**props):
        instance = props_cls(**props)
        context = instance.model_dump()
        extra = instance.context()
        if extra:
            context.update(extra)
        return context

    return render_fn
```

Patrón clave: `model_dump()` produce el dict puro de campos validados,
y `context()` añade derivados encima. Si el component no override
`context()`, el dict resultante es solo los props.

### 6.3 `_load_module_from_file` — import outside sys.path

Modules viven en `modules/<id>/components/<name>/component.py`. Esa
ruta no es un paquete normalmente importable. Solución:

```python
def _load_module_from_file(py_path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module    # cachea por nombre arbitrario
    spec.loader.exec_module(module)
    return module
```

Importante: **se cachea en `sys.modules`** con un nombre del namespace
`_hotframe_components.<id>.<name>.component`. Esto evita que cada
discovery re-ejecute el módulo y respeta los imports relativos
internos del componente.

`ImportManager` de `engine` rastrea estos nombres para limpiar al
desinstalar el módulo.

### 6.4 `discover_module_components` vs `discover_app_components`

Son wrappers de `discover_components` con diferencias:

| | `discover_module_components` | `discover_app_components` |
|---|---|---|
| Path raíz | `<module_dir>/components/` | `<apps_dir>/<app_name>/components/` |
| `module_id` | el módulo | `None` (apps no se desmontan) |
| `template_search_prefix` | `<module_id>/components` | `<app_name>/components` |
| `import_prefix` | `_hotframe_components.<id>` | `_hotframe_app_components.<app_name>` |
| Cuándo corre | en `module install` | en boot (lifespan paso 12) |

`discover_apps_components(registry, apps_dir)` es un wrapper más:
itera todos los apps y llama a `discover_app_components` para cada uno.

### 6.5 `_template_path_for(component_dir, prefix)`

Calcula el path del template tal como lo verá el Jinja loader.
- Sin prefix: `name/template.html`.
- Con prefix `<id>/components`: `<id>/components/name/template.html`.

Esto debe coincidir con cómo el `templating.engine` arma sus
`FileSystemLoader` (apps_dir + cada module root como search paths).

---

## 7. `mounting.py` — montaje y desmontaje en FastAPI

Encarga de meter en `app.router.routes` los routers y los static de
los componentes. Sin esto, los components con `routes.py` no están
disponibles aunque estén registrados.

### 7.1 Convención de paths

- Routers: `/_components/<name>/...`
- Static: `/_components/<name>/static/...`

El prefijo `/_components/` está reservado. **No hay CSRF exempt
automático** — un POST a un component endpoint pasa por el mismo
middleware stack que cualquier ruta. Si un componente necesita
exempt (ej. webhook entrante), tiene que añadirse a
`CSRF_EXEMPT_PREFIXES`.

### 7.2 Funciones públicas

Cuatro pares (`mount_*` / `unmount_*` × routers/static), más versiones
"para un solo módulo":

- `mount_component_routers(app, registry)` — monta todos.
- `mount_component_routers_for_module(app, registry, module_id)` —
  solo los del módulo X (usado en `module install`).
- `unmount_component_router(app, name)` — quita uno.
- `unmount_component_routers_for_module(app, module_id)` — quita
  todos los de un módulo.
- `mount_component_static(app, registry)`, `mount_component_static_for_module(...)`,
  `unmount_component_static(app, name)`, `unmount_component_static_for_module(app, module_id)`.

### 7.3 Cómo desmonta — mutación in-place de `app.router.routes`

FastAPI/Starlette no tienen API "remove route". `mounting.py` mira la
lista de routes:

```python
def unmount_component_router(app, name):
    prefix = f"/_components/{name}"
    prefix_slash = f"{prefix}/"
    routes = app.router.routes
    original = len(routes)
    routes[:] = [
        route for route in routes
        if not _matches_component_subtree(_route_path(route), prefix, prefix_slash)
    ]
    removed = original - len(routes)
    if removed:
        app.openapi_schema = None  # fuerza regeneración de OpenAPI
    return removed > 0
```

`_matches_component_subtree(path, prefix, prefix_slash)` retorna `True`
si `path == prefix` (caso raro: ruta exacta sin slash final) o si
`path.startswith(prefix_slash)` (todo lo demás).

`unmount_component_routers_for_module(app, module_id)` lee `app.state.components`
para resolver qué names pertenecen al módulo (las routes solo guardan
el path, no el `module_id`). Por eso **debe llamarse antes** de
`registry.unregister_module(module_id)` — si limpias el registry
primero, ya no puedes resolver los names.

### 7.4 Static — `Mount` directo

```python
app.router.routes.append(
    Mount(
        path,
        app=StaticFiles(directory=str(directory)),
        name=f"component-static-{name}",
    )
)
```

`Mount` es de Starlette (no `app.mount` de FastAPI), porque:
1. Necesitamos meterlo en `app.router.routes` directamente para poder
   filtrarlo en unmount.
2. `app.mount` añade además a `app.routes` (la lista pública), que
   siempre redirige a `app.router.routes`. Resultado idéntico, pero
   menos indirección.

`_mount_single_static` también valida que la carpeta exista en disco
y rechaza el mount si no — un componente que declara `static/` y
luego no lo trae avisa con warning en vez de fallar.

### 7.5 OpenAPI invalidation

`app.openapi_schema = None` después de un mount/unmount. Sin esto,
FastAPI cachea el schema generado y los endpoints recién montados no
aparecen en `/api/openapi.json` (ni en `/api/docs`).

---

## 8. `rendering.py` — `render_component()` global

```python
@pass_context
def render_component(ctx: Context, __component_name__: str, /, **props) -> Markup:
    registry = _registry_from_context(ctx)
    if registry is None:
        return Markup("")
    entry = registry.get(__component_name__)
    if entry is None:
        logger.warning("Unknown component %r", __component_name__)
        return Markup("")
    return _render_entry(ctx.environment, ctx, entry, props)


def register_component_globals(env: Environment) -> None:
    env.globals["render_component"] = render_component
```

### 8.1 Decisiones

- **`@pass_context`** — el primer arg es el `Context` activo de
  Jinja2. Necesario para leer la "framework slice".
- **`__component_name__` positional-only** — usando `/` después.
  Razón: si el componente tiene una prop llamada `name`, `name="x"`
  no colisiona con el dispatch.
- **Componente no encontrado → `Markup("")`** + warning. No crashea
  la página; un typo en producción genera un hueco vacío y un log,
  no un 500.

### 8.2 Framework slice

```python
_FRAMEWORK_CONTEXT_KEYS = (
    "request", "csrf_token", "csp_nonce", "user", "current_path",
)

def _framework_slice(ctx):
    return {key: ctx.get(key) for key in _FRAMEWORK_CONTEXT_KEYS if key in ctx}
```

**El componente NO ve** las variables del template padre (ej. `todos`
declarado en la página). Recibe **solo** sus props validadas + estos
5 keys del marco. Esto es **aislamiento por defecto** — evita
sorpresas como "el componente lee mal una var por colisión de nombre".

### 8.3 `_render_entry` — el render real

```python
def _render_entry(env, ctx, entry, props, body=None):
    render_fn = entry.render_fn
    if render_fn is not None:
        try:
            context = render_fn(**props)
        except ValidationError as exc:
            return Markup(f"<!-- component {entry.name!r}: invalid props ... -->")
        except TypeError as exc:
            return Markup(f"<!-- component {entry.name!r}: unexpected kwargs -->")
    else:
        context = dict(props)

    context.update(_framework_slice(ctx))
    if body is not None:
        context["body"] = Markup(body)

    template = env.get_template(entry.template)
    return Markup(template.render(**context))
```

Errores de Pydantic (`ValidationError`) y kwargs sobrantes
(`TypeError`) se interceptan y se devuelven como **comentarios HTML**.
Los logs sí incluyen el `exc_info`, así que en dev se ven en consola
y en prod aparecen en CloudWatch.

`Markup(template.render(...))` marca el resultado como seguro (Jinja
no escapa el HTML del componente) — el componente es responsable de
escapar lo que reciba en sus props.

---

## 9. `jinja_ext.py` — el tag `{% component %}`

Una extensión Jinja2 que añade el tag `{% component 'name' k=v %}body{% endcomponent %}`.

### 9.1 Por qué es un tag y no una macro

- Macros no aceptan body de bloque.
- Macros no validan kwargs (Pydantic).
- Macros viven en otro template, lo que complica el discovery.

### 9.2 La parte del parser

```python
class ComponentExtension(Extension):
    tags = {"component"}

    def parse(self, parser):
        lineno = next(parser.stream).lineno
        name_expr = parser.parse_expression()
        kwargs = []
        while parser.stream.current.type != "block_end":
            if parser.stream.skip_if("comma"):
                continue
            if parser.stream.current.test("name"):
                key = parser.stream.expect("name").value
                parser.stream.expect("assign")
                value = parser.parse_expression()
                kwargs.append(nodes.Keyword(key, value, lineno=value.lineno))
            else:
                break
        body = parser.parse_statements(("name:endcomponent",), drop_needle=True)
        call = self.call_method("_render_component", [name_expr], kwargs)
        return nodes.CallBlock(call, [], [], body).set_lineno(lineno)
```

Lee la primera expresión (el nombre), luego pares `key=value` separados
por comas opcionales, y empaqueta el body como un `CallBlock`. Cuando
Jinja ejecuta el bloque, llama `_render_component(name, **kwargs, caller=lambda: body_html)`.

### 9.3 La parte del runtime — `_render_component`

```python
def _render_component(self, __component_name__, /, *, caller=None, **props):
    env = self.environment
    registry = env.globals.get("_hotframe_components")
    if registry is None:
        logger.warning("...")
        return Markup("")
    entry = registry.get(__component_name__)
    if entry is None:
        logger.warning(...)
        return Markup("")
    body = caller() if caller is not None else ""
    ctx = _current_render_context()
    return _render_entry(env, ctx, entry, props, body=str(body))
```

`caller()` ejecuta el body block y devuelve el HTML como string. Se
pasa a `_render_entry` como `body=...` para que termine en
`context["body"]` dentro del template.

### 9.4 El problema del Context — `_TrackingContext`

Aquí hay un truco subtle. El `Extension` recibe un `Environment`
(no un `Context`), y los call blocks no propagan el Context activo
de Jinja. Pero `_render_entry` necesita el Context para sacar la
framework slice (`request`, `csrf_token`, etc.).

Solución: parchear la `context_class` del environment al boot:

```python
def install_component_context_tracker(env):
    original_context_class = env.context_class
    if getattr(original_context_class, "_hotframe_patched", False):
        return  # idempotente

    class _TrackingContext(original_context_class):
        _hotframe_patched = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _current_ctx.set(self)

    env.context_class = _TrackingContext
```

Cada vez que Jinja construye un Context (al renderizar un template),
el subclase publica `self` en un `ContextVar`. El `_render_component`
luego lee `_current_ctx.get()` para conseguir el Context.

`ContextVar` es seguro entre tareas asyncio — cada `asyncio.Task`
tiene su propio scope, así que dos requests concurrentes no se
roban el Context.

`_EmptyCtx` es el fallback cuando `_render_component` se invoca
fuera de un render (raro, principalmente tests). Implementa `get` y
`__contains__` para que `_framework_slice` no crashee.

---

## 10. Flujo completo — del filesystem al HTML renderizado

```
1. BOOT (lifespan)
   discover_apps_components(registry, ./apps)
       └─ for each app:
            discover_app_components(registry, ./apps, name)
                └─ discover_components(./apps/name/components, ...)
                    └─ for each subdir:
                         _load_module_from_file(component.py)
                         _find_component_class(module)
                         _build_render_fn(props_cls)
                         _load_router(routes.py)
                         build ComponentEntry
                         registry.register(entry)
   mount_component_routers(app, registry)
   mount_component_static(app, registry)

2. MODULE INSTALL (engine.module_runtime.install)
   discover_module_components(registry, modules/X, module_id="X")
   mount_component_routers_for_module(app, registry, "X")
   mount_component_static_for_module(app, registry, "X")

3. RENDER (any TemplateResponse)
   render_component('button', label='OK', variant='primary')
       └─ registry.get('button') -> entry
       └─ _render_entry(env, ctx, entry, props={...})
              └─ render_fn(**props) -> {label, variant, ...validated}
              └─ _framework_slice(ctx) -> {request, csrf_token, ...}
              └─ env.get_template(entry.template).render(...)

4. MODULE UNINSTALL
   unmount_component_routers_for_module(app, "X")
   unmount_component_static_for_module(app, "X")
   registry.unregister_module("X")
```

---

## 11. Decisiones de diseño que conviene recordar

1. **Aislamiento por defecto.** Un componente solo ve sus props +
   framework slice. Si necesita más, lo declara como prop.
2. **Errores no fatales.** `ValidationError` y `TypeError` en props
   se vuelven comentarios HTML + log. Una página nunca crashea por
   un componente con typo.
3. **Mismo prefijo `/_components/<name>` para router y static.**
   Permite teardown atómico — borras el subtree y desaparecen ambos.
4. **`is_live` precomputado.** Se setea en discovery para que el
   render path stateless no tenga que importar `LiveComponent` ni
   hacer `issubclass` en cada llamada.
5. **Discovery usa nombres únicos en `sys.modules`** —
   `_hotframe_components.<id>.<name>.component` — para que el
   `ImportManager` del engine los pueda barrer en uninstall.
6. **`{% component %}` y `render_component()` comparten `_render_entry`.**
   Una sola lógica de validación + render — el tag solo añade el body.
7. **Idempotencia.** `install_component_context_tracker` y
   `_mount_single_static` chequean si ya hicieron su trabajo y son
   no-op en segunda llamada. Permite re-bootstrap en tests sin
   acumular estado.

---

## 12. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Componente no aparece en `/_components/` | No tiene `routes.py` o el módulo no exporta `router`. | Confirma que `routes.py` define un `APIRouter` literalmente llamado `router`. |
| `Unknown component 'foo'` | No está registrado o se renderiza antes del boot. | Verifica que la carpeta tiene `template.html` y que el discovery la procesó (mira logs). |
| `Component 'foo' prop validation failed` | Pasaste un kwarg con tipo erróneo. | Mira el comentario HTML resultante; explica el campo y el error. |
| El componente ve variables del padre que no debería | No deberían — quizás las pasaste explícitamente. | Recuerda: solo props + framework slice. |
| `class` no es kwarg válido en `{% component %}` | Jinja rechaza palabras reservadas. | `attrs={'class': 'btn'}` y dentro del template `{{ attrs | xmlattr }}`. |
| Static no carga | El directorio no existía al boot. | Crea el directorio y reinicia. `_mount_single_static` no monta carpetas inexistentes. |

