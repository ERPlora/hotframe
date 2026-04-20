<p align="center">
  <img src="https://raw.githubusercontent.com/ERPlora/hotframe/main/logo.png" alt="HotFrame" width="200">
</p>


<p align="center">
  <strong>Modular Python web framework with hot-mount dynamic modules.</strong>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python 3.12+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-green.svg" alt="License"></a>
  <a href="https://pypi.org/project/hotframe/"><img src="https://img.shields.io/pypi/v/hotframe.svg" alt="PyPI"></a>
</p>

---

## What is hotframe

hotframe is a Python web framework that unifies FastAPI, SQLAlchemy 2.0, Jinja2, HTMX, and Alpine.js under Django-like ergonomics. It adds a hot-mount module engine — load and unload plugins at runtime without restarting the process — and a Turbo/Livewire-style HTMX layer for server-driven UI. Built for teams who want the productivity of Rails or Django with the async performance of FastAPI.

---

## Quickstart

```
pip install hotframe
```

```
hf startproject myapp
cd myapp
hf runserver
```

```
INFO     hotframe.core - Loading kernel modules...
INFO     hotframe.modules - Mounted: core, auth, admin (3 modules)
INFO     hotframe.server - Uvicorn running on http://127.0.0.1:8000
INFO     hotframe.server - Press CTRL+C to quit
```

The CLI installs two aliases: `hf` (short) and `hotframe` (explicit).

---

## Key Features

- **Hot-mount dynamic modules** — Load and unload Python modules at runtime via a DB registry with topological dependency resolution. No process restart required.

- **HTMX layer (Turbo/Livewire-style)** — `@htmx_view` decorator, named frames, TurboStream responses, out-of-band swaps, and server-sent event broadcasting. Build rich UIs without writing JavaScript.

- **Django-like ergonomics** — `AppConfig`, `settings.py`, management commands, scaffolding CLI. Familiar conventions so teams onboard in minutes, not days.

- **AsyncEventBus + HookRegistry** — WordPress-style actions and filters across modules. Decouple features without tight imports. Fully async-native.

- **SQLAlchemy 2.0 + Alembic** — Async sessions, per-module migration namespaces, and automatic migration discovery. No shared migration root.

- **Jinja2 + Alpine.js integration** — Template inheritance, context processors, CSP-safe nonce injection, and Alpine.js wired out of the box.

- **OpenTelemetry observability** — Traces, metrics, and structured logs built into the request lifecycle. Zero extra setup for OTLP exporters.

- **CLI scaffolding** — `hf startproject`, `hf startapp`, `hf startmodule`, `hf makemigrations`, `hf migrate`. Generate production-ready skeletons from the command line.

- **Interactive shell** — `hf shell` opens a Python REPL with the app fully booted: `app`, `settings`, `db`, `events`, `hooks`, `slots`, and `runtime` are pre-loaded. Use it for ad-hoc queries, slot debugging, or inspecting module state. Install `pip install "hotframe[shell]"` for the optional IPython backend with auto-await.

- **Reusable components** — Server-rendered UI widgets with a required `template.html` and optional Pydantic-typed props, colocated HTTP routes, and per-component static assets. Apps and hot-mount modules contribute components; `hf startproject` scaffolds `alert` and `badge` as editable examples. Invoke from any template via `{{ render_component('name', ...) }}` or `{% component 'name' %}...{% endcomponent %}`.

- **HTTP client subsystem** — `AuthenticatedClient` wraps `httpx.AsyncClient` with pluggable `Auth` strategies (`BearerAuth`, `ApiKeyAuth`, `BasicAuth`, `HmacAuth`, `CustomAuth`) and a per-app registry on `app.state.http_clients`. Since 0.0.9, an Angular-style **interceptor pipeline** layers `RetryInterceptor`, `CircuitBreakerInterceptor`, and `RefreshInterceptor` (plus any custom interceptor) around every registered client, auto-discovered from `apps/shared/interceptors/` and `modules/*/interceptors.py`. See [docs/HTTP_CLIENTS.md](docs/HTTP_CLIENTS.md) and [docs/http-interceptors.md](docs/http-interceptors.md).

---

## Comparison

| Feature | Rails Turbo | Laravel Livewire | Phoenix LiveView | Django + htmx | **hotframe** |
|---|---|---|---|---|---|
| Language | Ruby | PHP | Elixir | Python | **Python** |
| Server-driven UI | Yes | Yes | Yes | Partial | **Yes** |
| Hot-reload modules | No | No | No | No | **Yes** |
| Async-native | No | No | Yes | No | **Yes** |
| ORM | ActiveRecord | Eloquent | Ecto | Django ORM | **SQLAlchemy 2.0** |
| Per-module migrations | No | No | No | No | **Yes** |
| Plugin hooks system | No | No | No | No | **Yes** |
| CLI scaffolding | Yes | Yes | Yes | Yes | **Yes** |
| PyPI installable | No | No | No | Yes | **Yes** |

---

## Minimal Example

Define a module with a model, a route, and a template in under 20 lines:

```python
# modules/blog/module.py
from hotframe import ModuleConfig

class BlogModule(ModuleConfig):
    name = "blog"
    version = "1.0.0"
    dependencies = ["core", "auth"]
```

```python
# modules/blog/models.py
from hotframe import Base
from sqlalchemy.orm import Mapped, mapped_column

class Post(Base):
    __tablename__ = "blog_posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    body: Mapped[str]
```

```python
# modules/blog/routes.py
from fastapi import APIRouter, Request
from hotframe import htmx_view, DbSession
from .models import Post

router = APIRouter()

@router.get("/blog")
@htmx_view(module_id="blog", view_id="list")
async def post_list(request: Request, db: DbSession):
    posts = await db.execute(select(Post))
    return {"posts": posts.scalars().all()}
```

```html
<!-- modules/blog/templates/blog/index.html -->
<div hx-get="/blog" hx-trigger="every 30s" hx-swap="innerHTML">
  {% for post in posts %}
    <article>{{ post.title }}</article>
  {% endfor %}
</div>
```

---

## Architecture Overview

hotframe is organized in three layers:

**Runtime layer** — the framework kernel. Boots FastAPI, wires middleware, initializes the DB engine, and exposes the public API (`@htmx_view`, `router`, `settings`, `EventBus`, `HookRegistry`).

**Module layer** — each module is a Python package with a `ModuleConfig` subclass, its own models, views, templates, migrations, and static assets. The module engine resolves dependency order, mounts routes and Alembic migration contexts, and registers hook namespaces. Modules can be installed, uninstalled, enabled, and disabled at runtime via the admin API without touching the running process.

**HTMX layer** — sits on top of FastAPI responses. The `@htmx_view` decorator detects `HX-Request` headers and returns partial renders or full-page responses automatically. TurboStream helpers produce `text/vnd.turbo-stream.html` responses for out-of-band DOM updates. The `EventBus` integrates with server-sent events for real-time broadcasting to named HTMX frames.

The CLI (`hf`) is a Typer application that wraps Uvicorn, Alembic, and the scaffolding generators. It reads `settings.py` from the project root and discovers modules automatically from the `modules/` directory.

---

## Documentation

Documentation is available in the [docs/](docs/) directory.

- [Architecture](docs/ARCHITECTURE.md)
- [Components](docs/COMPONENTS.md)
- [Shell](docs/SHELL.md)
- [HTTP clients](docs/HTTP_CLIENTS.md)
- [HTTP interceptors](docs/http-interceptors.md)
- [Changelog](docs/CHANGELOG.md)
- [Security policy](docs/SECURITY.md)

---

## License

[Apache 2.0](LICENSE). Copyright 2026 ERPlora.

---

## Contributing

See [CONTRIBUTING.md](docs/CONTRIBUTING.md). Feedback and issue reports are welcome while the project is in pre-alpha. Code contributions open on first stable release.
