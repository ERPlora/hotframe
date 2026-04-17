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
    """Create a new hotframe project."""
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

    # pyproject.toml
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
    apps_dir.mkdir()
    (apps_dir / "__init__.py").write_text("")

    # modules/ directory
    modules_dir = project_dir / "modules"
    modules_dir.mkdir()

    # tests/ directory
    tests_dir = project_dir / "tests"
    tests_dir.mkdir()
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
    typer.echo(f"  cd {name}")
    typer.echo("  python -m venv .venv && source .venv/bin/activate")
    typer.echo("  pip install -e '.[dev]'")
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
def startmodule(name: str) -> None:
    """Create a new dynamic module inside modules/."""
    mod_dir = Path("modules") / name
    if mod_dir.exists():
        typer.echo(f"Error: module '{name}' already exists.", err=True)
        raise typer.Exit(1)

    mod_dir.mkdir(parents=True)

    (mod_dir / "__init__.py").write_text("")

    (mod_dir / "module.py").write_text(dedent(f'''\
        from hotframe import ModuleConfig


        class {name.title().replace("_", "")}Module(ModuleConfig):
            name = "{name}"
            verbose_name = "{name.replace("_", " ").title()}"
            version = "1.0.0"
            is_system = False
            requires_restart = False
            dependencies = []

            async def ready(self) -> None:
                pass

            async def install(self, ctx) -> None:
                pass

            async def uninstall(self, ctx) -> None:
                pass
    '''))

    (mod_dir / "models.py").write_text(dedent('''\
        """SQLAlchemy models."""
        from hotframe import Base
        # Define your models here
    '''))

    (mod_dir / "routes.py").write_text(dedent(f'''\
        """HTMX views."""
        from fastapi import APIRouter
        from hotframe import htmx_view

        router = APIRouter(prefix="/m/{name}", tags=["{name}"])
    '''))

    (mod_dir / "api.py").write_text(dedent(f'''\
        """REST API endpoints."""
        from fastapi import APIRouter

        api_router = APIRouter(prefix="/api/v1/{name}", tags=["{name}"])
    '''))

    templates_dir = mod_dir / "templates" / name
    templates_dir.mkdir(parents=True)
    (templates_dir / "pages").mkdir()
    (templates_dir / "partials").mkdir()

    migrations_dir = mod_dir / "migrations"
    migrations_dir.mkdir()

    tests_dir = mod_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    typer.echo(f"Created module 'modules/{name}/'")


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
    import uvicorn

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
