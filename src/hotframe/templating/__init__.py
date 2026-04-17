"""
templating — Jinja2 template engine with HTMX and Alpine.js extensions.

``create_template_engine`` builds a ``Jinja2Templates`` instance with all
module template directories pre-registered and returns it ready to use
with FastAPI. ``register_extensions`` installs the full suite of Jinja2
globals and filters: ``url_for``, ``static_url``, ``render_icon``,
``slugify``, ``currency``, ``dateformat``, ``timesince``, HTMX helpers,
Alpine helpers, and slot rendering.

Key exports::

    from hotframe.templating.engine import create_template_engine, refresh_template_dirs
    from hotframe.templating.extensions import register_extensions

Usage::

    templates = create_template_engine(modules_dir=Path("/app/modules"))
    return templates.TemplateResponse(request, "sales/index.html", context)
"""
