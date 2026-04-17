"""
forms — server-side form rendering for HTMX-driven forms.

``FormRenderer`` wraps a Jinja2 environment and provides ``render_field``
and ``render_form`` helpers that produce HTML form widgets consistent with
the UX CSS library. Designed to be used inside ``htmx_view`` handlers to
re-render individual fields on validation errors without a full page reload.

Key exports::

    from hotframe.forms.rendering import FormRenderer

Usage::

    renderer = FormRenderer(templates.env)
    html = renderer.render_field("name", value=data["name"], errors=errors)
"""
