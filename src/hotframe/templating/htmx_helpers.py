"""
Jinja2 helper functions for generating HTMX attributes.

Registered as Jinja2 globals so they're available in all templates.
Reduce boilerplate and prevent typos in hx-* attributes.

Usage in templates::

    <button {{ hx_delete(url_for('todo.delete', id=todo.id), confirm="Delete?") }}>
        Delete
    </button>

    <form {{ hx_post(url_for('todo.create'), target="#todo-list", swap="beforeend") }}>
        ...
    </form>

    <input {{ hx_get(url_for('search'), trigger="input changed delay:300ms", target="#results") }}>
"""

from __future__ import annotations

from markupsafe import Markup


def _build_attrs(**kwargs: str | bool | None) -> Markup:
    """Build a space-separated string of HTML attributes."""
    parts: list[str] = []
    for key, value in kwargs.items():
        if value is None or value is False:
            continue
        if value is True:
            parts.append(key)
        else:
            parts.append(f'{key}="{value}"')
    return Markup(" ".join(parts))


def hx_get(
    url: str,
    *,
    target: str | None = None,
    swap: str | None = None,
    trigger: str | None = None,
    push_url: bool = False,
    indicator: str | None = None,
    confirm: str | None = None,
    vals: str | None = None,
    select: str | None = None,
) -> Markup:
    """Generate hx-get with optional attributes."""
    return _build_attrs(
        **{
            "hx-get": url,
            "hx-target": target,
            "hx-swap": swap,
            "hx-trigger": trigger,
            "hx-push-url": "true" if push_url else None,
            "hx-indicator": indicator,
            "hx-confirm": confirm,
            "hx-vals": vals,
            "hx-select": select,
        }
    )


def hx_post(
    url: str,
    *,
    target: str | None = None,
    swap: str | None = None,
    trigger: str | None = None,
    push_url: bool = False,
    indicator: str | None = None,
    confirm: str | None = None,
    encoding: str | None = None,
) -> Markup:
    """Generate hx-post with optional attributes."""
    return _build_attrs(
        **{
            "hx-post": url,
            "hx-target": target,
            "hx-swap": swap,
            "hx-trigger": trigger,
            "hx-push-url": "true" if push_url else None,
            "hx-indicator": indicator,
            "hx-confirm": confirm,
            "hx-encoding": encoding,
        }
    )


def hx_put(url: str, **kwargs: str | bool | None) -> Markup:
    """Generate hx-put with optional attributes."""
    return _build_attrs(
        **{
            "hx-put": url,
            **{f"hx-{k.replace('_', '-')}": v for k, v in kwargs.items()},
        }
    )


def hx_patch(url: str, **kwargs: str | bool | None) -> Markup:
    """Generate hx-patch with optional attributes."""
    return _build_attrs(
        **{
            "hx-patch": url,
            **{f"hx-{k.replace('_', '-')}": v for k, v in kwargs.items()},
        }
    )


def hx_delete(
    url: str,
    *,
    target: str | None = None,
    swap: str | None = None,
    confirm: str | None = None,
) -> Markup:
    """Generate hx-delete with optional attributes."""
    return _build_attrs(
        **{
            "hx-delete": url,
            "hx-target": target,
            "hx-swap": swap or "outerHTML",
            "hx-confirm": confirm,
        }
    )


def hx_trigger(event: str) -> Markup:
    """Generate hx-trigger attribute."""
    return Markup(f'hx-trigger="{event}"')


def hx_indicator(selector: str) -> Markup:
    """Generate hx-indicator attribute for loading states."""
    return Markup(f'hx-indicator="{selector}"')


def hx_vals(data: dict) -> Markup:
    """Generate hx-vals attribute with JSON data."""
    import json

    return Markup(f"hx-vals='{json.dumps(data)}'")


# --- Registration ---

HTMX_HELPERS = {
    "hx_get": hx_get,
    "hx_post": hx_post,
    "hx_put": hx_put,
    "hx_patch": hx_patch,
    "hx_delete": hx_delete,
    "hx_trigger": hx_trigger,
    "hx_indicator": hx_indicator,
    "hx_vals": hx_vals,
}
