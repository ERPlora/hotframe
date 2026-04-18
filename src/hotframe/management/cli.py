# SPDX-License-Identifier: Apache-2.0
"""
Hotframe CLI — project management commands.

Usage::

    hf startproject myapp
    hf startapp accounts
    hf startmodule blog
    hf runserver
    hf migrate
    hf makemigrations
"""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import typer

app = typer.Typer(
    name="hotframe",
    help="Hotframe — Modular Python web framework CLI.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# startproject
# ---------------------------------------------------------------------------

@app.command()
def startproject(name: str) -> None:
    """Create a new hotframe project. Use '.' to create in the current directory."""
    if name == ".":
        project_dir = Path.cwd()
        name = project_dir.name
        # Check it's empty enough (allow .venv, pyproject.toml, uv.lock)
        existing = {p.name for p in project_dir.iterdir()} - {".venv", "pyproject.toml", "uv.lock", ".git", ".gitignore", "__pycache__", ".python-version"}
        if existing:
            typer.echo(f"Error: directory is not empty. Found: {', '.join(sorted(existing))}", err=True)
            raise typer.Exit(1)
    else:
        project_dir = Path(name)
        if project_dir.exists():
            typer.echo(f"Error: directory '{name}' already exists.", err=True)
            raise typer.Exit(1)
        project_dir.mkdir(parents=True)

    # main.py
    (project_dir / "main.py").write_text(dedent('''\
        from hotframe import create_app
        from settings import settings

        app = create_app(settings)
    '''))

    # asgi.py
    (project_dir / "asgi.py").write_text(dedent('''\
        from main import app  # noqa: F401
        # uvicorn asgi:app
    '''))

    # settings.py
    (project_dir / "settings.py").write_text(dedent(f'''\
        from hotframe import HotframeSettings
        from pydantic_settings import SettingsConfigDict


        class Settings(HotframeSettings):
            model_config = SettingsConfigDict(
                env_prefix="{name.upper()}_",
                env_file=".env",
                env_file_encoding="utf-8",
                case_sensitive=False,
                extra="ignore",
            )

            APP_TITLE: str = "{name.replace("_", " ").title()}"


        settings = Settings()
    '''))

    # manage.py
    (project_dir / "manage.py").write_text(dedent('''\
        #!/usr/bin/env python
        """Management CLI — delegates to hotframe."""
        from hotframe.management.cli import app

        if __name__ == "__main__":
            app()
    '''))

    # .env
    (project_dir / ".env").write_text(dedent('''\
        # Database (SQLite for development)
        DATABASE_URL=sqlite+aiosqlite:///./app.db
        SECRET_KEY=change-me-in-production
        DEBUG=true
    '''))

    # .gitignore
    (project_dir / ".gitignore").write_text(dedent('''\
        # Python
        __pycache__/
        *.py[cod]
        *.egg-info/
        dist/
        build/
        .venv/

        # Cache (pytest, ruff, mypy)
        .cache/

        # Environment
        .env

        # Database
        *.db
        *.sqlite3

        # IDE
        .vscode/
        .idea/
    '''))

    # pyproject.toml — skip if already exists (user may have uv.lock, custom deps)
    if not (project_dir / "pyproject.toml").exists():
        (project_dir / "pyproject.toml").write_text(dedent(f'''\
            [project]
            name = "{name}"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = [
                "hotframe",
            ]

            [project.optional-dependencies]
            dev = [
                "pytest>=8.0",
                "pytest-asyncio>=0.24",
                "ruff>=0.7",
            ]

            [tool.pytest.ini_options]
            asyncio_mode = "auto"
            testpaths = ["tests"]
            cache_dir = ".cache/pytest"

            [tool.ruff]
            cache-dir = ".cache/ruff"
            line-length = 100

            [tool.mypy]
            cache_dir = ".cache/mypy"
        '''))

    # apps/ directory
    apps_dir = project_dir / "apps"
    apps_dir.mkdir(exist_ok=True)
    (apps_dir / "__init__.py").write_text("")

    # apps/shared/ — base app with welcome page
    shared_dir = apps_dir / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "__init__.py").write_text("")

    (shared_dir / "app.py").write_text(dedent(f'''\
        from hotframe import AppConfig


        class SharedConfig(AppConfig):
            name = "shared"
            verbose_name = "{name.replace("_", " ").title()} Shared"

            def ready(self):
                pass
    '''))

    (shared_dir / "routes.py").write_text(dedent('''\
        """Shared routes — index page and base endpoints."""
        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse

        router = APIRouter()


        @router.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Index page — proves the app is running."""
            templates = getattr(request.app.state, "templates", None)
            if templates:
                return templates.TemplateResponse(
                    request, "shared/index.html",
                    {"request": request, "app_title": request.app.title},
                )
            return HTMLResponse(
                f"<h1>{request.app.title}</h1>"
                f"<p>Powered by <a href=\\"https://github.com/ERPlora/hotframe\\">hotframe</a></p>"
            )
    '''))

    # apps/shared/templates/
    shared_tpl = shared_dir / "templates" / "shared"
    shared_tpl.mkdir(parents=True)

    (shared_tpl / "base.html").write_text(dedent(f'''\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{{% block title %}}{name.replace("_", " ").title()}{{% endblock %}}</title>
            <script src="https://unpkg.com/htmx.org@2.0.4"></script>
            <style>
                body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
            </style>
            {{% block head %}}{{% endblock %}}
        </head>
        <body hx-boost="true">
            {{% block content %}}{{% endblock %}}
        </body>
        </html>
    '''))

    (shared_tpl / "index.html").write_text(dedent('''\
        {% extends "shared/base.html" %}

        {% block content %}
        <h1>{{ app_title }}</h1>
        <p>Your hotframe application is running.</p>
        <hr>
        <h3>Next steps</h3>
        <ul>
            <li><code>hf startapp accounts</code> — create your first app</li>
            <li><code>hf startmodule blog</code> — create a dynamic module</li>
            <li>Edit <code>settings.py</code> to configure your project</li>
        </ul>
        <p><small>Powered by <a href="https://github.com/ERPlora/hotframe">hotframe</a></small></p>
        {% endblock %}
    '''))

    (shared_tpl.parent / "errors").mkdir()
    for code, msg in [("404", "Page not found"), ("500", "Server error")]:
        ((shared_tpl.parent / "errors") / f"{code}.html").write_text(dedent(f'''\
            {{% extends "shared/base.html" %}}
            {{% block title %}}{code} - {msg}{{% endblock %}}
            {{% block content %}}<h1>{code}</h1><p>{msg}</p>{{% endblock %}}
        '''))

    # modules/ directory
    modules_dir = project_dir / "modules"
    modules_dir.mkdir(exist_ok=True)

    # tests/ directory
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "conftest.py").write_text(dedent('''\
        """Shared test fixtures."""
        import pytest

        from hotframe.testing import create_test_app, test_db_session


        @pytest.fixture
        async def app():
            """Create a test application."""
            return create_test_app()


        @pytest.fixture
        async def db(app):
            """Create a test database session."""
            async for session in test_db_session():
                yield session
    '''))

    typer.echo(f"Created project '{name}'")
    if name != project_dir.name or str(project_dir) != str(Path.cwd()):
        typer.echo(f"  cd {name}")
    typer.echo("  hf runserver")


# ---------------------------------------------------------------------------
# startapp
# ---------------------------------------------------------------------------

@app.command()
def startapp(name: str) -> None:
    """Create a new app inside apps/."""
    app_dir = Path("apps") / name
    if app_dir.exists():
        typer.echo(f"Error: app '{name}' already exists.", err=True)
        raise typer.Exit(1)

    app_dir.mkdir(parents=True)

    (app_dir / "__init__.py").write_text("")

    (app_dir / "app.py").write_text(dedent(f'''\
        from hotframe import AppConfig


        class {name.title().replace("_", "")}Config(AppConfig):
            name = "{name}"
            verbose_name = "{name.replace("_", " ").title()}"

            def ready(self):
                pass
    '''))

    (app_dir / "models.py").write_text(dedent('''\
        """SQLAlchemy models."""
        from hotframe import Base
        # Define your models here
    '''))

    (app_dir / "routes.py").write_text(dedent(f'''\
        """HTMX views."""
        from fastapi import APIRouter

        router = APIRouter(prefix="/{name}", tags=["{name}"])
    '''))

    (app_dir / "api.py").write_text(dedent(f'''\
        """REST API endpoints."""
        from fastapi import APIRouter

        api_router = APIRouter(prefix="/api/v1/{name}", tags=["{name}"])
    '''))

    templates_dir = app_dir / "templates" / name
    templates_dir.mkdir(parents=True)
    (templates_dir / "pages").mkdir()
    (templates_dir / "partials").mkdir()

    migrations_dir = app_dir / "migrations"
    migrations_dir.mkdir()

    tests_dir = app_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    typer.echo(f"Created app 'apps/{name}/'")


# ---------------------------------------------------------------------------
# startmodule
# ---------------------------------------------------------------------------

@app.command()
def startmodule(
    name: str,
    api_only: bool = typer.Option(False, "--api-only", help="API only, no HTMX views"),
    system: bool = typer.Option(False, "--system", help="System module, no views or API"),
) -> None:
    """Create a new dynamic module inside modules/.

    Examples::

        hf startmodule blog              # views + API (default)
        hf startmodule payments --api-only   # API only
        hf startmodule audit --system        # system module
    """
    mod_dir = Path("modules") / name
    if mod_dir.exists():
        typer.echo(f"Error: module '{name}' already exists.", err=True)
        raise typer.Exit(1)

    has_views = not api_only and not system
    has_api = not system
    class_name = name.title().replace("_", "")
    verbose = name.replace("_", " ").title()

    mod_dir.mkdir(parents=True)

    (mod_dir / "__init__.py").write_text("")

    # module.py
    (mod_dir / "module.py").write_text(dedent(f'''\
        from hotframe import ModuleConfig


        class {class_name}Module(ModuleConfig):
            name = "{name}"
            verbose_name = "{verbose}"
            version = "1.0.0"
            is_system = {system}
            has_views = {has_views}
            has_api = {has_api}
            requires_restart = False
            dependencies = []

            async def ready(self) -> None:
                pass

            async def install(self, ctx) -> None:
                pass

            async def uninstall(self, ctx) -> None:
                pass
    '''))

    # models.py
    (mod_dir / "models.py").write_text(dedent('''\
        """SQLAlchemy models."""
        from hotframe import Base
        # Define your models here
    '''))

    # routes.py (views)
    if has_views:
        (mod_dir / "routes.py").write_text(dedent(f'''\
            """HTMX views for {verbose}."""
            from fastapi import APIRouter, Request
            from fastapi.responses import HTMLResponse

            router = APIRouter(prefix="/m/{name}", tags=["{name}"])


            @router.get("/", response_class=HTMLResponse)
            async def index(request: Request):
                """Module landing page."""
                return request.app.state.templates.TemplateResponse(
                    request, "{name}/pages/index.html", {{
                        "request": request,
                        "module_name": "{verbose}",
                    }},
                )
        '''))

        # Template
        templates_dir = mod_dir / "templates" / name
        templates_dir.mkdir(parents=True)
        (templates_dir / "pages").mkdir()
        (templates_dir / "partials").mkdir()
        (templates_dir / "pages" / "index.html").write_text(dedent(f'''\
            {{% extends "shared/base.html" %}}
            {{% block title %}}{verbose}{{% endblock %}}
            {{% block content %}}
            <h1>{verbose}</h1>
            <p>Module <strong>{name}</strong> is installed and running.</p>
            <p><a href="/">&larr; Home</a></p>
            {{% endblock %}}
        '''))

    # api.py
    if has_api:
        (mod_dir / "api.py").write_text(dedent(f'''\
            """REST API for {verbose}."""
            from fastapi import APIRouter

            api_router = APIRouter(prefix="/api/v1/{name}", tags=["{name}"])


            @api_router.get("/")
            async def list_items():
                """List items."""
                return {{"module": "{name}", "items": []}}
        '''))

    # migrations/
    migrations_dir = mod_dir / "migrations"
    migrations_dir.mkdir()

    # tests/
    tests_dir = mod_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    parts = []
    if has_views:
        parts.append("views")
    if has_api:
        parts.append("API")
    if system:
        parts.append("system")
    mode = " + ".join(parts) if parts else "minimal"

    typer.echo(f"Created module 'modules/{name}/' ({mode})")


# ---------------------------------------------------------------------------
# modules (subcommand group)
# ---------------------------------------------------------------------------

modules_app = typer.Typer(help="Module lifecycle management.")
app.add_typer(modules_app, name="modules")


@modules_app.command("list")
def modules_list() -> None:
    """List all modules and their status."""
    import asyncio

    async def _list():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        modules = await manager.list()

        if not modules:
            typer.echo("No modules found in modules/")
            return

        typer.echo(f"{'Module':<20} {'Status':<12} {'Version':<10} {'Views':<6} {'API':<6}")
        typer.echo("-" * 60)
        for m in modules:
            views = "yes" if m.has_views else "no"
            api = "yes" if m.has_api else "no"
            status = m.status
            if m.is_system:
                status += " (system)"
            typer.echo(f"{m.name:<20} {status:<12} {m.version:<10} {views:<6} {api:<6}")

    asyncio.run(_list())


@modules_app.command("install")
def modules_install(name: str) -> None:
    """Install and activate a module."""
    import asyncio

    async def _install():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        result = await manager.install(name)

        if result.ok:
            typer.echo(f"OK: {result.message}")
        else:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(1)

    asyncio.run(_install())


@modules_app.command("update")
def modules_update(source: str) -> None:
    """Update a module to a new version."""
    import asyncio

    async def _update():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        result = await manager.update(source)

        if result.ok:
            typer.echo(f"OK: {result.message}")
        else:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(1)

    asyncio.run(_update())


@modules_app.command("activate")
def modules_activate(name: str) -> None:
    """Activate a disabled module."""
    import asyncio

    async def _activate():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        result = await manager.activate(name)

        if result.ok:
            typer.echo(f"OK: {result.message}")
        else:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(1)

    asyncio.run(_activate())


@modules_app.command("deactivate")
def modules_deactivate(name: str) -> None:
    """Deactivate an active module (keeps data)."""
    import asyncio

    async def _deactivate():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        result = await manager.deactivate(name)

        if result.ok:
            typer.echo(f"OK: {result.message}")
        else:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(1)

    asyncio.run(_deactivate())


@modules_app.command("uninstall")
def modules_uninstall(
    name: str,
    keep_data: bool = typer.Option(False, "--keep-data", help="Keep database tables"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Uninstall a module (removes files, optionally drops tables)."""
    import asyncio

    if not yes:
        confirm = typer.confirm(
            f"Uninstall module '{name}'?"
            + (" (keeping data)" if keep_data else " (including database tables)")
        )
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    async def _uninstall():
        from hotframe.engine.manager import ModuleManager

        manager = ModuleManager()
        result = await manager.uninstall(name, keep_data=keep_data)

        if result.ok:
            typer.echo(f"OK: {result.message}")
            if result.details.get("tables_dropped"):
                typer.echo(f"  Dropped {result.details['tables_dropped']} table(s)")
        else:
            typer.echo(f"Error: {result.message}", err=True)
            raise typer.Exit(1)

    asyncio.run(_uninstall())


# ---------------------------------------------------------------------------
# runserver
# ---------------------------------------------------------------------------

@app.command()
def runserver(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = True,
) -> None:
    """Start the development server."""
    import sys

    import uvicorn

    # Ensure CWD is in sys.path so uvicorn can import main.py
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    typer.echo(f"Starting server at http://{host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
    )


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------

@app.command()
def migrate() -> None:
    """Run database migrations (Alembic upgrade head)."""
    typer.echo("Running migrations...")
    try:
        import asyncio

        from hotframe.migrations.runner import run_core_migrations

        asyncio.run(run_core_migrations())
        typer.echo("Migrations complete.")
    except ImportError:
        typer.echo("Migration runner not available. Run alembic directly:")
        typer.echo("  alembic upgrade head")


# ---------------------------------------------------------------------------
# makemigrations
# ---------------------------------------------------------------------------

@app.command()
def makemigrations(message: str = "auto") -> None:
    """Generate new migration (Alembic revision --autogenerate)."""
    typer.echo(f"Generating migration: {message}")
    try:
        os.system(f'alembic revision --autogenerate -m "{message}"')
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show hotframe version."""
    from hotframe import __version__

    typer.echo(f"hotframe {__version__}")


if __name__ == "__main__":
    app()
