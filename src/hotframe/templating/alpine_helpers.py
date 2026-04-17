"""
Alpine.js integration helpers for Jinja2 templates.

Provides safe serialization of Python data to Alpine.js x-data attributes.

Usage::

    <div {{ alpine_data({"items": items, "search": "", "loading": false}) }}>
        <input x-model="search">
        <template x-for="item in items">
            <div x-text="item.name"></div>
        </template>
    </div>
"""

from __future__ import annotations

import json
from typing import Any

from markupsafe import Markup


def alpine_data(data: dict[str, Any] | Any) -> Markup:
    """Serialize Python data to Alpine.js x-data attribute.

    Handles:
    - Pydantic models (calls .model_dump())
    - Objects with .to_dict() method
    - Dicts and primitives (JSON serialization)
    - XSS prevention (escapes for HTML attribute context)

    Usage::

        <div {{ alpine_data({"count": 0, "items": items_list}) }}>
    """
    # Handle Pydantic models
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    # Handle objects with a to_dict method
    elif hasattr(data, "to_dict"):
        data = data.to_dict()
    elif not isinstance(data, dict):
        data = {"value": data}

    json_str = json.dumps(data, ensure_ascii=False, default=str)
    # Escape single quotes for HTML attribute context
    escaped = json_str.replace("'", "&#39;")
    return Markup(f"x-data='{escaped}'")


def alpine_show(condition: str) -> Markup:
    """Generate x-show attribute."""
    return Markup(f'x-show="{condition}"')


def alpine_cloak() -> Markup:
    """Generate x-cloak attribute (hides element until Alpine initializes)."""
    return Markup("x-cloak")


# --- Registration ---

ALPINE_HELPERS = {
    "alpine_data": alpine_data,
    "alpine_show": alpine_show,
    "alpine_cloak": alpine_cloak,
}
