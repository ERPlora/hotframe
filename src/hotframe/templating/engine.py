"""
Jinja2 template engine with module template discovery and i18n support.

Creates a Jinja2 environment that:
- Loads templates from the global ``templates/`` directory.
- Auto-discovers ``templates/`` directories inside each module.
- Installs gettext translations so ``_()`` and ``{% trans %}`` work.
- Supports hot-refresh of template directories when modules are loaded/unloaded.

Usage::

    from hotframe.templating.engine import create_template_engine, refresh_template_dirs
    from hotframe.config.settings import get_settings

    settings = get_settings()
    templates = create_template_engine(modules_dir=settings.MODULES_DIR)
    app.state.templates = templates

    # After loading/unloading a module:
    refresh_template_dirs(templates, settings.MODULES_DIR)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# Root templates directory: resolved from the project's working directory,
# not from the hotframe package itself. Like Django, templates/ lives in
# the project root, not inside the framework.
_GLOBAL_TEMPLATE_DIR = Path.cwd() / "templates"


def _collect_template_dirs(modules_dir: Path | None) -> list[str]:
    """Build the ordered list of template directories.

    Order: global templates first (CWD/templates/), then app template
    dirs (apps/*/templates/), then module template dirs.
    """
    dirs: list[str] = []

    # 1. Project-level templates (CWD/templates/)
    if _GLOBAL_TEMPLATE_DIR.exists():
        dirs.append(str(_GLOBAL_TEMPLATE_DIR))

    # 2. App template dirs (apps/*/templates/) — scan apps/ if it exists
    apps_dir = Path.cwd() / "apps"
    if apps_dir.exists():
        for app_dir in sorted(apps_dir.iterdir()):
            if not app_dir.is_dir() or app_dir.name.startswith((".", "_")):
                continue
            tpl_dir = app_dir / "templates"
            if tpl_dir.exists():
                dirs.append(str(tpl_dir))

    # Modules directory — contains both kernel (is_system=True) and dynamic
    # modules downloaded from S3.
    if modules_dir and modules_dir.exists():
        for mod_dir in sorted(modules_dir.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith((".", "_")):
                continue
            tpl_dir = mod_dir / "templates"
            if tpl_dir.exists():
                dirs.append(str(tpl_dir))

    return dirs


def create_template_engine(modules_dir: Path | None = None) -> Jinja2Templates:
    """Create the Jinja2 engine with module template discovery and i18n.

    Args:
        modules_dir: Path to the modules directory (e.g. ``/tmp/modules``).
            Each module's ``templates/`` subdirectory is added to the search path.

    Returns:
        A configured ``Jinja2Templates`` instance with extensions, globals,
        and gettext translations installed.
    """
    template_dirs = _collect_template_dirs(modules_dir)

    from hotframe.templating.frame_extension import FrameExtension

    env = Environment(
        loader=FileSystemLoader(template_dirs),
        autoescape=select_autoescape(["html", "xml"]),
        extensions=[
            "jinja2.ext.i18n",
            "jinja2.ext.do",
            "jinja2.ext.loopcontrols",
            FrameExtension,
        ],
    )

    # Register global functions, filters, and constants.
    from hotframe.templating.extensions import register_extensions

    register_extensions(env)

    # Install gettext translations so {% trans %} and _() work in templates.
    # The translations adapter uses the context-local language (set per-request
    # by LanguageMiddleware), so templates are always rendered in the correct
    # language for each request.
    from hotframe.middleware.i18n_support import get_translations

    env.install_gettext_translations(get_translations())

    templates = Jinja2Templates(env=env)

    logger.info(
        "Template engine created with %d search directories", len(template_dirs)
    )
    return templates


def refresh_template_dirs(templates: Jinja2Templates, modules_dir: Path) -> None:
    """Re-scan module directories and update the template loader.

    Called after module load/unload so new or removed templates take effect
    without restarting the application.
    """
    template_dirs = _collect_template_dirs(modules_dir)
    templates.env.loader = FileSystemLoader(template_dirs)
    logger.info(
        "Template directories refreshed: %d search paths", len(template_dirs)
    )
