# Hotframe

A modular Python web framework with hot-mount dynamic modules.

**FastAPI + SQLAlchemy + Jinja2 + HTMX + Alpine.js** under a Django-like API, with a module system that installs, updates, activates, and uninstalls Python packages **without restarting the app**.

## At a glance

- **One public API**: `from hotframe import X` — no reaching into private submodules.
- **Auto-discovery**: `apps/*/routes.py` and `apps/*/api.py` are mounted at boot with zero config. No `INSTALLED_APPS`, no manual `include_router`.
- **Dynamic modules**: install at runtime from local filesystem, `.zip` file, URL, or a marketplace. Update and roll back safely via `HotMountPipeline`.
- **Server-driven UI**: full HTMX + Alpine.js layer with Turbo Streams, SSE broadcasting, reusable components, slot injection, and flash messages. No build step.
- **Typed persistence**: `ISession`, `IQueryBuilder[T]`, `IRepository[T]` Protocols decouple your code from SQLAlchemy's session class.
- **Observability built in**: structured logging (`structlog`), OpenTelemetry traces, hooks for events and metrics.

## Install

```bash
pip install hotframe
```

Python 3.12+. Published on PyPI: [https://pypi.org/project/hotframe/](https://pypi.org/project/hotframe/).

## Three-line `main.py`

```python
from hotframe import create_app
from settings import settings
app = create_app(settings)
```

Everything else lives in `settings.py` (database, middleware, modules, auth) and in your `apps/` and `modules/` directories.

## Where to go next

- **[Architecture](ARCHITECTURE.md)** — framework layout, bootstrap sequence, public API tour.
- **[Shell](SHELL.md)** — `hf shell` REPL with the app pre-booted.
- **[Components](COMPONENTS.md)** — reusable server-rendered UI widgets.
- **[HTTP clients](HTTP_CLIENTS.md)** — `AuthenticatedClient`, credential strategies, registry lifecycle.
- **[HTTP interceptors](http-interceptors.md)** — Angular-style request/response pipeline.
- **[Public API reference](api/public.md)** — auto-generated from docstrings.

## Project

- **Source**: [ERPlora/hotframe](https://github.com/ERPlora/hotframe)
- **License**: Apache 2.0
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
- **Contributing**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **Security**: [SECURITY.md](SECURITY.md)
