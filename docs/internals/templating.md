# templating.md — Jinja2 engine, slots, extensions, globals

> **Carpeta cubierta:** `src/hotframe/templating/`. Cinco archivos:
> `__init__.py`, `engine.py`, `slots.py`, `extensions.py`, `globals.py`.
> Crea el `Jinja2Templates` con auto-discovery de directorios,
> i18n, extensiones (`{% component %}`, `{% live %}`, `{% frame %}`),
> filters (currency, dateformat, slugify, etc.), y `SlotRegistry`
> para inyección cross-module de UI.

---

## 1. `__init__.py`

Solo docstring. Importa por ruta explícita:

```python
from hotframe.templating.engine import create_template_engine, refresh_template_dirs
from hotframe.templating.slots import SlotRegistry, SlotEntry
```

---

## 2. `engine.py` — `create_template_engine`

### 2.1 Search paths — orden importante

```python
def _collect_template_dirs(modules_dir):
    dirs = []
    # 1. Project-level: <cwd>/templates/
    if _GLOBAL_TEMPLATE_DIR.exists():
        dirs.append(str(_GLOBAL_TEMPLATE_DIR))
    # 2. Apps: apps/<app>/templates/
    for app_dir in apps_dir.iterdir():
        if (app_dir / "templates").exists():
            dirs.append(str(app_dir / "templates"))
    # 3. Modules: <modules_dir>/<id>/templates/
    for mod_dir in modules_dir.iterdir():
        if (mod_dir / "templates").exists():
            dirs.append(str(mod_dir / "templates"))
    # 4. Component roots
    dirs.append(str(framework_components_root))  # hotframe/components/_builtin
    dirs.append(str(apps_dir))                    # apps/<app>/components/<name>/template.html
    dirs.append(str(modules_dir))                 # modules/<id>/components/<name>/template.html
    return dirs
```

Orden: **el primero gana**. Si dos dirs tienen `index.html`, usa el
primero. Permite a un proyecto override templates de un app/módulo
copiándolos a `templates/`.

### 2.2 Construcción del environment

```python
env = Environment(
    loader=FileSystemLoader(template_dirs),
    autoescape=select_autoescape(["html", "xml"]),
    extensions=[
        "jinja2.ext.i18n",
        "jinja2.ext.do",
        "jinja2.ext.loopcontrols",
        ComponentExtension,         # {% component %}
        LiveExtension,              # {% live %}
    ],
)

install_component_context_tracker(env)   # ver components.md
register_extensions(env)                 # filters, globals, frame ext
register_component_globals(env)          # render_component
env.globals["live_assets"] = live_assets

env.install_gettext_translations(get_translations())  # i18n
```

Decisiones:

1. **Autoescape para HTML/XML** — escapado por defecto. Para
   incluir HTML literal en una variable, usa `Markup(...)` o
   `| safe`.
2. **`jinja2.ext.do`** habilita `{% do ... %}` (statements sin
   output).
3. **`jinja2.ext.loopcontrols`** permite `{% break %}` y
   `{% continue %}`.
4. **`ComponentExtension`** registra el tag `{% component %}`.
   `install_component_context_tracker` parchea `Context` para que
   el tag pueda leer `request`, `csrf_token`, etc. (ver `components.md`).
5. **`LiveExtension`** registra `{% live %}` para cold-loading
   `LiveComponent`s (ver `live.md`).
6. **`install_gettext_translations`** conecta `_(...)` y
   `{% trans %}` con el catalog del `LanguageMiddleware`.

### 2.3 `_HotframeTemplates` subclass

```python
class _HotframeTemplates(Jinja2Templates):
    def TemplateResponse(self, request, name, context=None, **kwargs):
        if context is None:
            context = {}
        if "request" not in context:
            context["request"] = request
        if "csrf_token" not in context:
            csrf_token = getattr(request.state, "csrf_token", "")
            context["csrf_token"] = csrf_token
            context["csrf_input"] = lambda: Markup(
                f'<input type="hidden" name="csrf_token" value="{csrf_token}">'
            ) if csrf_token else lambda: Markup("")
        if "csp_nonce" not in context:
            context["csp_nonce"] = getattr(request.state, "csp_nonce", "")
        return super().TemplateResponse(request, name, context, **kwargs)
```

Magia clave: cada `TemplateResponse` recibe automáticamente
`request`, `csrf_token`, `csrf_input()`, `csp_nonce` sin que el
handler tenga que pasarlos. Templates pueden hacer:

```html
<form method="POST">{{ csrf_input() }}...</form>
<script nonce="{{ csp_nonce }}">...</script>
```

### 2.4 `refresh_template_dirs(templates, modules_dir)`

Re-escanea el filesystem y actualiza el loader del env. Llamado
después de install/uninstall de un módulo (ver
`engine.module_runtime._refresh_templates`).

```python
def refresh_template_dirs(templates, modules_dir):
    new_dirs = _collect_template_dirs(modules_dir)
    templates.env.loader = FileSystemLoader(new_dirs)
    templates.env.cache.clear()  # invalida los compiled templates cached
```

Sin esto, un módulo recién instalado tiene templates en disco pero
Jinja no los ve hasta el siguiente boot.

---

## 3. `slots.py` — `SlotRegistry` (cross-module UI)

### 3.1 ¿Qué resuelve?

Permite a un módulo **inyectar UI** dentro del template de otro
módulo, sin acoplamiento directo. Ejemplo: `loyalty` añade un badge
de puntos en la página de detalles de cliente del módulo `customers`.

### 3.2 La API

```python
class SlotRegistry:
    def register(self, slot_name, template, *,
                 priority=10, module_id=None,
                 context_fn=None, condition_fn=None): ...
    async def get_entries(self, slot_name, request=None, **extra_context):
        # Returns list[(SlotEntry, context_dict)] sorted by priority
    def unregister_module(self, module_id): ...
    def has_content(self, slot_name): ...
    def list_slots(self) -> dict[str, int]: ...
```

### 3.3 Registro

```python
# En modules/loyalty/module.py:
async def on_install(runtime, ...):
    runtime.slots.register(
        "customers_detail_sidebar",
        template="loyalty/partials/customer_badge.html",
        priority=5,
        module_id="loyalty",
        context_fn=lambda request, customer, **kw: {
            "loyalty_points": get_points(customer.id),
        },
        condition_fn=lambda request, customer, **kw: has_loyalty_card(customer.id),
    )
```

- **`priority=5`** se renderiza antes que entries con priority
  default 10.
- **`context_fn`** retorna dict extra que se pasa al template.
  Async o sync.
- **`condition_fn`** decide si renderizar este entry (true/false).
  Útil para mostrar contenido solo a usuarios con cierta licencia
  o feature.

### 3.4 Render en el template

```jinja
{# customers/templates/customers/detail.html #}
<div class="sidebar">
    {% set entries = await render_slot('customers_detail_sidebar', customer=customer) %}
    {% for entry, ctx in entries %}
        {% include entry.template with context %}
    {% endfor %}
</div>
```

`render_slot` está registrado como global Jinja por `globals.py`.
Llama a `slots.get_entries(...)` (async). Cada entry se include con
su context propio + el contexto del template padre.

### 3.5 `get_entries(slot_name, request, **extra)`

```python
async def get_entries(self, slot_name, request=None, **extra_context):
    entries = self._slots.get(slot_name)
    if not entries:
        return []
    sorted_entries = sorted(entries, key=lambda e: e.priority)
    result = []
    for entry in sorted_entries:
        # Check condition
        if entry.condition_fn:
            if iscoroutinefunction(entry.condition_fn):
                visible = await entry.condition_fn(request=request, **extra_context)
            else:
                visible = entry.condition_fn(request=request, **extra_context)
            if not visible:
                continue
        # Resolve context
        ctx = dict(extra_context)
        if entry.context_fn:
            extra = await entry.context_fn(request=request, **extra_context) \
                    if iscoroutinefunction(entry.context_fn) \
                    else entry.context_fn(request=request, **extra_context)
            if isinstance(extra, dict):
                ctx.update(extra)
        result.append((entry, ctx))
    return result
```

Errores en `condition_fn` o `context_fn` se logean y el entry se
skipea — un slot roto no rompe la página.

### 3.6 Cleanup en uninstall

```python
def unregister_module(self, module_id):
    for slot_name in list(self._slots):
        self._slots[slot_name] = [e for e in self._slots[slot_name]
                                   if e.module_id != module_id]
        if not self._slots[slot_name]:
            del self._slots[slot_name]
```

`engine.loader.ModuleLoader.unload_module` lo llama automáticamente.

---

## 4. `extensions.py` — filters, globals, frame ext

### 4.1 `register_extensions(env)`

Registra:

**Filters**:

| Filter | Implementación |
|---|---|
| `currency(amount, code="USD")` | `f"{amount:,.2f} {code}"` con localización |
| `dateformat(dt, fmt="d/m/Y H:i")` | strftime con tokens estilo Django |
| `timesince(dt)` | "3 minutes ago", "yesterday", "2 weeks ago" |
| `truncatewords(text, n)` | Trunca a N palabras + "..." |
| `slugify(text)` | Lowercase, replace spaces with -, strip non-alphanum |

**Globals**:

| Global | Uso |
|---|---|
| `icon(name, size=24)` | Iconify, render `<svg>` con prefijos: `home-outline` (ion default), `material:search`, `hero:check`, `tabler:menu`, `lucide:user`, `fa:settings` |
| `render_component(name, **props)` | Ver `components.md` |
| `live_assets()` | Ver `live.md` |
| `render_slot(slot_name, **ctx)` | Ver `globals.py` |
| `frame_extension` | Tag `{% frame "id" src="..." lazy=true %}` |
| `csrf_input` | Ya inyectado por `_HotframeTemplates` |

### 4.2 `frame_extension` — `{% frame %}`

```jinja
{% frame "user-stats" src="/api/stats/user/123" lazy=true %}
    Loading...
{% endframe %}
```

Renderiza:

```html
<div id="user-stats" data-frame-src="/api/stats/user/123" data-frame-lazy>
    Loading...
</div>
```

El cliente JS (live.js o un helper aparte) detecta `[data-frame-src]`
y hace fetch al endpoint, reemplazando el body con el HTML
respondido. `lazy=true` espera a que esté visible (IntersectionObserver).

Útil para renderizar fragmentos pesados sin bloquear el initial
render.

### 4.3 `render_icon(name, size, prefix_default="ion")`

```python
def render_icon(name, size=24, prefix_default="ion"):
    if ":" in name:
        prefix, icon = name.split(":", 1)
    else:
        prefix, icon = prefix_default, name
    # Map prefix to Iconify collection
    collection = {
        "ion": "ion", "material": "mdi", "hero": "heroicons",
        "tabler": "tabler", "lucide": "lucide", "fa": "fa-solid",
    }.get(prefix, prefix)
    url = f"https://api.iconify.design/{collection}/{icon}.svg?width={size}"
    return Markup(f'<img src="{url}" alt="{name}" width="{size}" height="{size}">')
```

Llamada externa a `api.iconify.design` — los iconos no están
embebidos. Para offline strict, descarga los SVGs y sirve local.

---

## 5. `globals.py` — `render_slot` global

```python
@pass_context
async def render_slot(ctx, slot_name, **kwargs):
    request = ctx.get("request")
    slots: SlotRegistry = ctx["__slots__"]   # injected at render time
    entries = await slots.get_entries(slot_name, request=request, **kwargs)
    out = []
    for entry, slot_ctx in entries:
        template = ctx.environment.get_template(entry.template)
        out.append(template.render(**slot_ctx))
    return Markup("".join(out))
```

`ctx["__slots__"]` debe ser inyectado por el `TemplateResponse` —
hotframe lo hace en boot vía `app.state.slots` accesible por el
template.

---

## 6. Decisiones de diseño que conviene recordar

1. **Multi-search-path con orden explícito.** Project → apps →
   modules → component roots. El primero gana en collisions.
2. **Autoescape on.** Markup explícito o `| safe` para HTML literal.
3. **`_HotframeTemplates` auto-injecta CSRF y CSP.** No tienes que
   pasarlos a cada `TemplateResponse`.
4. **Slots son async.** `render_slot` resuelve `condition_fn` y
   `context_fn` con await si son async.
5. **Frames son una alternativa light a HTMX.** Sin necesidad de
   import HTMX, un fetch-and-replace declarativo.
6. **Icons via Iconify CDN.** Online by default. Para offline,
   descarga los SVGs.
7. **`refresh_template_dirs` invalida el cache.** Crítico tras
   install/uninstall.

---

## 7. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Template not found tras instalar módulo | `refresh_template_dirs` no se llamó. | Lo llama `module_runtime._refresh_templates` automático — verifica logs. |
| HTML escapado en lugar de renderizado | Variable contiene `<...>` y autoescape on. | `{{ var | safe }}` o `Markup(...)` en Python. |
| `csrf_input()` retorna empty | No hay CSRF token en `request.state`. | Verifica `CSRFMiddleware` en stack. |
| Slot no aparece | `condition_fn` retorna False, o `module_id` no registrado. | `print(slots.list_slots())` y revisa entries. |
| `Multiple top-level entries with same name` | Dos templates en distintos dirs con el mismo path. | Renombra o usa el orden de search dirs. |
| Iconify no carga | Sin internet o CSP bloquea `api.iconify.design`. | Añade el dominio a `CSP_ALLOWED_SOURCES["img"]`. |
