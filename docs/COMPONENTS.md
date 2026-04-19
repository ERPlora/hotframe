# Hotframe Components

Reusable server-rendered UI widgets for hotframe projects.

---

## Introduction

A **component** is a named, reusable piece of UI with its own template, optional typed props, optional HTTP endpoints, and optional static assets. You write a widget once and invoke it from any template — across apps, modules, and pages — without duplicating HTML, routes, or JavaScript.

Hotframe has components because the alternative — copy-pasting partials, writing ad-hoc macros, or reaching for React — does not fit a server-driven HTMX stack. Components give you the reuse of React while staying inside the Jinja2 + HTMX + Alpine.js world: no build step, CSP-safe, and aware of the framework slice (`request`, `csrf_token`, `csp_nonce`, `user`).

### Components vs slots

Hotframe has two closely named subsystems. They solve opposite problems.

| | Slots (`SlotRegistry`) | Components (`ComponentRegistry`) |
|---|---|---|
| Direction | Modules **push** content into a named extension point | Templates **pull** a named widget into their markup |
| Invocation | Host template iterates `slots.get_entries("dashboard_widgets")` | Template writes `{% component 'media_picker' %}` |
| Owner of the call site | Host app that defines the slot | Consumer template that renders the component |
| Typical use | Plugin-style UI injection (dashboard tiles, settings tabs) | Reusable widgets (buttons, modals, pickers, badges) |
| Lifecycle | Registered once at module load | Discovered and registered once per app/module |

If you are wiring a "my module adds something to the dashboard" feature, use a slot. If you are wiring a "this widget is used on six pages and I'm tired of copy-pasting it", use a component.

---

## Two types of components

Every component has a `template.html`. Whether it also has a `component.py` determines whether it is template-only or Python-declared.

### Template-only

A single `template.html`. Props arrive as template variables; defaults come from Jinja2's `| default(...)` filter. No Python file is required.

```jinja
{# apps/ui/components/button/template.html #}
<button type="{{ type | default('button') }}"
        class="btn btn-{{ variant | default('primary') }}">
    {{ body }}
</button>
```

Usage:

```jinja
{% component 'button' variant='danger' %}Delete{% endcomponent %}
```

### Python-declared

A `component.py` that declares a subclass of `hotframe.Component`. Props become Pydantic fields with runtime validation, typed defaults, and IDE completion. An optional `context()` method returns extra template variables derived from the validated props.

```python
# apps/ui/components/button/component.py
from hotframe import Component

class Button(Component):
    variant: str = "primary"
    type: str = "button"
    disabled: bool = False

    def context(self) -> dict:
        return {"css_class": f"btn btn-{self.variant}"}
```

```jinja
{# apps/ui/components/button/template.html #}
<button type="{{ type }}"
        class="{{ css_class }}"
        {% if disabled %}disabled{% endif %}>
    {{ body }}
</button>
```

Use template-only for trivial widgets (badge, empty state). Use Python-declared when props have constraints, enums, or derived values — letting Pydantic reject bad calls is cheaper than debugging a mis-rendered template.

---

## File layout

One directory per component. The directory name is the component name.

```
components/
  media_picker/
    component.py      # optional — Python-declared with typed props
    template.html     # required — Jinja2 template
    routes.py         # optional — APIRouter auto-mounted under /_components/<name>/
    static/           # optional — served under /_components/<name>/static/
      media_picker.css
      media_picker.js
```

| File | Required | Purpose |
|---|---|---|
| `template.html` | Yes | Jinja2 template rendered by `render_component` or `{% component %}`. |
| `component.py` | No | Declares a `Component` subclass with typed props and optional `context()`. |
| `routes.py` | No | Declares a module-level `router: APIRouter`. Auto-mounted at `/_components/<name>/`. |
| `static/` | No | Per-component static assets. Auto-served at `/_components/<name>/static/`. |

Files other than these four are ignored. Directory names starting with `.` or `_` are skipped (they are reserved for framework internals and bytecode caches).

---

## Template-only components

Use Jinja2 defaults for every optional prop so typos don't blow up rendering:

```jinja
{# empty_state/template.html #}
<div class="empty-state">
    {% if icon %}{{ icon(icon) }}{% endif %}
    <h3>{{ title | default('Nothing here yet') }}</h3>
    {% if description %}<p>{{ description }}</p>{% endif %}
</div>
```

```jinja
{{ render_component('empty_state', title='No orders', icon='cart-outline') }}
```

When to use template-only: pure presentational widgets where every prop maps 1:1 to a template variable and defaults fit naturally into `| default`. Template-only avoids the cost of importing a Python module at discovery time and suits widgets shipped without any logic.

---

## Python components

Subclass `Component` and declare your props:

```python
# components/media_picker/component.py
from hotframe import Component

class MediaPicker(Component):
    folder: str = ""
    multiple: bool = False
    accept: str = "image/*"
    name: str = "media"

    def context(self) -> dict:
        return {"accept_list": self.accept.split(",")}
```

Hotframe finds the first subclass of `Component` in the module and wires it as the component's `props_cls`. On render, hotframe instantiates the class with the caller's kwargs (Pydantic validates and coerces), merges `model_dump()` with whatever `context()` returns, and hands the result to the template.

```jinja
{# components/media_picker/template.html #}
<div class="media-picker"
     data-folder="{{ folder }}"
     data-multiple="{{ multiple | tojson }}">
    <input type="file" name="{{ name }}"
           accept="{{ accept_list | join(',') }}"
           {% if multiple %}multiple{% endif %}>
</div>
```

```jinja
{{ render_component('media_picker', folder='products', multiple=true) }}
```

If `folder=123` is passed, Pydantic rejects it, hotframe logs a warning, and renders a `<!-- component 'media_picker': invalid props (1 error(s)) -->` HTML comment instead of crashing the page.

`context()` must be synchronous. Hotframe's Jinja2 environment is sync and does not support awaiting coroutines from a template.

---

## Endpoints

A component can ship its own HTTP routes. Drop a `routes.py` that declares a module-level `router`:

```python
# components/media_picker/routes.py
from fastapi import APIRouter, UploadFile

router = APIRouter()

@router.post("/upload")
async def upload_media(file: UploadFile):
    # ... storage logic ...
    return {"url": saved_url, "name": file.filename}
```

The router is automatically mounted under `/_components/media_picker/`. The example above becomes `POST /_components/media_picker/upload`. Routes are tagged `component:<name>` in the OpenAPI schema for grouping.

### CSRF and middleware

Component routes are **not** exempt from CSRF. They pass through the normal hotframe middleware stack — CSRF, rate limiting, session, CSP — exactly like a route declared in `apps/<app>/routes.py`. Unsafe HTTP methods (POST, PUT, PATCH, DELETE) must carry a CSRF token; the standard HTMX pattern (`hx-headers='{"X-CSRF-Token": "{{ csrf_token }}"}'` on `<body>`) works as-is.

If a specific path must be exempt, add its full prefix (for example `/_components/webhooks/`) to `settings.CSRF_EXEMPT_PREFIXES`.

---

## Static assets

Put per-component CSS, JavaScript, images, or fonts inside a `static/` directory:

```
components/
  media_picker/
    template.html
    static/
      media_picker.css
      media_picker.js
```

Hotframe serves that directory via FastAPI's `StaticFiles` at `/_components/media_picker/static/`. Reference assets from the component's own template:

```jinja
<link rel="stylesheet" href="/_components/media_picker/static/media_picker.css">
<script nonce="{{ csp_nonce }}" src="/_components/media_picker/static/media_picker.js"></script>
```

Useful when a component ships a non-trivial behavior bundle that does not belong in the global `static/` tree. For tiny snippets, inline them in the template and keep the `static/` folder out.

---

## Template-side API

### `render_component` global

```jinja
{{ render_component('badge', text='New', variant='primary') }}
```

Use when the component takes no body — all state arrives via kwargs.

### `{% component %}` tag

```jinja
{% component 'alert' type='warning' dismissible=true %}
    <strong>Heads up.</strong> Stock is low.
{% endcomponent %}
```

Use when the component renders arbitrary markup inside itself. The body is captured and passed to the template as `{{ body }}` (already marked safe — don't re-escape).

### `attrs` for reserved attributes

Jinja2 does not accept Python reserved words as keyword arguments, so you cannot write `{{ render_component('button', class='btn-primary') }}`. Route HTML attributes through an `attrs` dict:

```jinja
{% component 'button' attrs={'class': 'btn-primary', 'id': 'submit', 'type': 'submit'} %}
    Save
{% endcomponent %}
```

Inside the template:

```jinja
<button {% for k, v in attrs.items() %}{{ k }}="{{ v }}" {% endfor %}>
    {{ body }}
</button>
```

### Context isolation

Components render with an **isolated** context. The parent template's local variables do not leak in. Hotframe copies a small, fixed framework slice:

| Key | What it is |
|---|---|
| `request` | The current `starlette.requests.Request`. |
| `csrf_token` | The current CSRF token string. |
| `csp_nonce` | The per-request CSP nonce for inline scripts and styles. |
| `user` | The resolved current user (or `None`). |
| `is_htmx` | True when the request carries `HX-Request: true`. |
| `current_path` | The request URL path. |

Any other state must be passed explicitly as a prop. This isolation is the feature, not a limitation — it means a component behaves the same regardless of which page renders it.

---

## Discovery

At application startup hotframe scans two roots in order:

1. **App components** — for every subdirectory of `apps/` that has a `components/` directory. Registered with `module_id=None`; the app is part of the project and does not hot-unload.
2. **Module components** — for every loaded module, `<modules_dir>/<module_id>/components/`. Registered with `module_id=<module_id>`.

Hotframe itself does not ship any UI components. To help new projects get started, `hf startproject` generates example `alert` and `badge` components in `apps/shared/components/`. They are plain scaffolding: keep them, change them, or delete them as you see fit.

Module components are discovered by the module loader at install/activate time, not only at boot. Their routers and static directories are mounted into the running app via `mount_component_routers_for_module` and `mount_component_static_for_module`. When a module is deactivated or uninstalled, the loader calls the matching `unmount_component_routers_for_module` and `unmount_component_static_for_module`, and the registry's `unregister_module(module_id)` drops every entry owned by the module. Hot-unload is a first-class lifecycle event — stale mounts do not accumulate.

A name collision (two components trying to register the same name) logs a warning and the second registration overwrites the first. This is intentional to support dev-time module reload, where a module re-imports itself with updated definitions.

---

## Building your first component

Template-only, no Python.

1. Create the directory: `apps/ui/components/notice/`.
2. Add `template.html`:

   ```jinja
   <div class="notice notice-{{ level | default('info') }}" role="status">
       {% if title %}<strong>{{ title }}</strong>{% endif %}
       {{ body }}
   </div>
   ```

3. Restart the dev server. Hotframe logs `Registered 1 component(s) for app 'ui': notice`.
4. Use it from any template:

   ```jinja
   {% component 'notice' level='success' title='Saved' %}
       Your changes are live.
   {% endcomponent %}
   ```

That's the whole workflow for presentational widgets.

---

## Building your first Python component with an endpoint

A live search component that queries the database.

1. Create the directory: `modules/search/components/product_search/`.

2. `component.py`:

   ```python
   from hotframe import Component

   class ProductSearch(Component):
       placeholder: str = "Search products..."
       limit: int = 10

       def context(self) -> dict:
           return {"endpoint": "/_components/product_search/results"}
   ```

3. `template.html`:

   ```jinja
   <div x-data="{ q: '' }">
       <input type="search" placeholder="{{ placeholder }}"
              x-model.debounce.300ms="q"
              hx-get="{{ endpoint }}"
              hx-trigger="input changed delay:300ms"
              hx-target="#product-search-results"
              hx-vals='{"limit": {{ limit }}}'>
       <div id="product-search-results"></div>
   </div>
   ```

4. `routes.py`:

   ```python
   from fastapi import APIRouter, Request
   from hotframe import DbSession

   router = APIRouter()

   @router.get("/results")
   async def results(request: Request, db: DbSession, q: str = "", limit: int = 10):
       # ... query the DB, render a partial template, return HTMLResponse ...
       ...
   ```

5. Activate the module (or restart the dev server). The router is mounted at `/_components/product_search/results`.

6. Use the component:

   ```jinja
   {{ render_component('product_search', limit=20) }}
   ```

---

## Starter components

Hotframe does not ship any UI components with the framework. `hf startproject` creates two example components in the new project at `apps/shared/components/alert/` and `apps/shared/components/badge/` so you can see a working component right after scaffolding. They are plain project files: modify or delete them freely, they are not needed by the framework itself.

### `alert`

```jinja
{% component 'alert' type='warning' dismissible=true %}
    Low stock on three products.
{% endcomponent %}
```

Renders a `<div class="alert alert-warning" role="alert">` with an optional Alpine-powered dismiss button when `dismissible=true`. Body is the alert content. `type` maps to a CSS class (`info`, `success`, `warning`, `danger`, ...) and defaults to `info`.

### `badge`

```jinja
{{ render_component('badge', text='New', variant='primary') }}
```

Renders a `<span class="badge badge-primary">`. `variant` defaults to `default`. No body.

Both starter components use the generic `.alert` / `.badge` class names and rely on your project's CSS for styling. They are meant to be replaced once your design system has its own primitives.

---

## Best practices

- **Keep `context()` synchronous.** The Jinja2 environment is sync. Async work belongs in a route handler that renders the component's template directly, not in the component's own `context()`.
- **Use `attrs={...}` for reserved attributes.** Never try to pass `class`, `type`, or `for` as a kwarg. Jinja2 raises a syntax error.
- **Rely on context isolation.** Don't assume the parent template's `page_title`, `item`, or `form` is visible inside the component. If the component needs it, pass it as a prop.
- **Name components with underscores.** `media_picker`, not `media-picker` or `MediaPicker`. Discovery uses the directory name verbatim as the registry key, and underscores match Python and Jinja identifier conventions.
- **One component per directory.** Two `template.html` files cannot coexist. If you need variants, pass a prop (`variant='compact'`) and branch inside the template.
- **Do not call `render_component` from inside a component template.** Recursive / nested rendering is not supported in 0.0.5 — the current render context is tracked via a single `ContextVar` and nesting can deliver the wrong framework slice to the inner call. Compose at the call site instead.
- **Prefer template-only for pure presentation.** Reach for Python components when you have typed props, validation, or derived values. Template-only avoids an extra import.
- **Namespace module-shipped components.** Prefix with the module id (`sales_order_summary`, not `summary`) to avoid collisions with app components. Name collisions overwrite silently aside from a log warning.

---

## Common pitfalls

- **Forgetting the static URL prefix.** Assets live at `/_components/<name>/static/`, not `/static/`. A broken `<link>` usually means the prefix was dropped.
- **Passing `class="foo"` as a kwarg.** Jinja2 will reject it. Use `attrs={"class": "foo"}` and expand inside the template.
- **Async `context()`.** Not supported. The render path is fully synchronous; awaiting a coroutine inside `context()` raises at render time. Put async work in a route handler.
- **Relying on `GLOBAL_CONTEXT_HOOK`.** The hook fires inside `@htmx_view` responses, not during component rendering. Its output is not part of the component context slice. If you need shared state everywhere, expose it via `request.app.state` and pull it through `request` inside the component.
- **Leaking CSP nonces outside `TemplateResponse`.** Rendering a component standalone (for example via `templates.env.get_template(...).render(...)` from a raw `Response`) bypasses hotframe's `_HotframeTemplates` auto-injection. The component gets no `csp_nonce`. Always return a `TemplateResponse` (or wrap your response in one) when you need the framework slice.

---

## Troubleshooting

**`Unknown component 'foo'` warning in the log.** The name was not registered. Check that the directory exists, the directory name matches the string you passed, `template.html` is present, and the owning app/module has been loaded. A missing `template.html` is logged as `Skipping component 'foo': missing template.html`.

**Component renders as an empty string in production, nothing in the log.** You probably disabled WARNING-level logging. The component rendering functions swallow unknown names on purpose (so a typo does not 500 the page); enable WARNING and retry.

**`<!-- component 'foo': invalid props (N error(s)) -->` HTML comment in the output.** Pydantic rejected the kwargs. Look at the log message — `Component 'foo' prop validation failed: ...` — for the specific field and error.

**`<!-- component 'foo': unexpected kwargs -->` HTML comment in the output.** You passed a keyword that is not declared on the `Component` subclass (Pydantic runs in strict mode for unknown fields by default). Add the field to the component's class, or drop the kwarg at the call site.

**Template file found in search paths but the component is not discovered.** Discovery requires `template.html` *inside a component subdirectory*. A `template.html` at the root of `components/` does not form a component.

**Routes from `routes.py` return 404.** The module owning the component must be active. Check `await runtime.list_modules()`. App components are always mounted at boot.

**Static asset returns 404.** Confirm the `static/` directory exists on disk at module-load time. Discovery records the path; the mount is skipped with a warning if the directory disappeared between discovery and mount.

**Component name collision overwrites silently.** Only a log warning (`Component name collision: 'foo' is being overwritten`) is emitted — this is intentional to allow dev-time reload. If you want hard errors, grep your logs for `Component name collision` in CI.

---

## Comparison with other systems

Developers arriving from other ecosystems recognize the shape of hotframe components. The table maps the surface API, not implementation details.

| Concept | Rails ViewComponent | django-components | Symfony Twig Components | Hotframe |
|---|---|---|---|---|
| Definition language | Ruby class + ERB template | Python class + Django template | PHP class + Twig template | Python class (optional) + Jinja2 template |
| Prop validation | `renders_one / renders_many` + manual | `declared_fields` or manual | PHP type hints + Symfony property-info | Pydantic (`Component` subclass) |
| Body / content block | `content` yielded inside the view | `{% slot %}` tag | `{% block content %}` | `{{ body }}` inside `{% component %}` |
| Named body blocks | `renders_one :header` | `{% slot 'header' %}` | Named `{% block %}`s | Not yet (roadmap) |
| Discovery | `app/components/<name>/` | Django app's `components/` directory | `src/Twig/Components/` | `apps/<app>/components/` + `modules/<id>/components/` |
| HTTP endpoint colocation | No (use a controller) | No (use a URLconf) | Yes (`LiveComponent`) | Yes (colocated `routes.py`) |
| Asset colocation | Preview-only | Via `Media` class | `asset_mapper` | Yes (colocated `static/`) |
| Hot reload | Dev server class reload | Dev server class reload | Dev server class reload | Runtime via `ModuleRuntime` |

Hotframe sits closer to Symfony Live Components than ViewComponent: it colocates template, Python class, HTTP routes, and static assets inside one directory, and it treats module hot-unload as a first-class lifecycle event.

---

## Roadmap

These items are **not** in 0.0.5. The roadmap represents direction, not commitment — confirm status in the issue tracker before building against any of them.

- **Named slots.** Multiple body blocks per component (header, footer, default), analogous to `{% fill %}` in django-components or `renders_one` in ViewComponent.
- **HTML-tag syntax.** A preprocessor that turns `<x-media-picker folder="products" />` into `{{ render_component('media_picker', folder='products') }}`. Lower friction when converting static HTML mockups.
- **Component preview pages.** A Lookbook / Storybook-style index of every registered component with live prop editing. Useful for design-system work and for QA.
- **Auto-documented props.** Use the `Component` subclass's Pydantic schema to render a props table in the preview page (types, defaults, descriptions).

---

## Public API reference

All importable from `from hotframe import X`:

- `Component` — Pydantic base class for Python-declared components.
- `ComponentEntry` — dataclass describing a registered component.
- `ComponentRegistry` — in-memory registry; an instance lives on `app.state.components`.

The mounting helpers (`mount_component_routers`, `unmount_component_routers_for_module`, and friends) are used by hotframe's own bootstrap and module loader. They are exported from `hotframe.components` for advanced use — most applications do not touch them directly.

The Jinja2 template globals and the `{% component %}` tag are installed automatically when `create_template_engine` runs; no wiring is required in your project.
