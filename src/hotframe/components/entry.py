# SPDX-License-Identifier: Apache-2.0
"""
Component entry — the in-memory descriptor of a registered component.

A component is a reusable UI unit (``button``, ``card``, ``data_table``)
discovered from an ``apps/{app}/components/{name}/`` or
``modules/{module_id}/components/{name}/`` directory. One definition,
many call sites.

This dataclass is the ``ComponentRegistry`` payload: it carries the
data needed to render the component's template, mount its optional
endpoint, validate its props, and clean up when the owning module is
unloaded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


@dataclass(slots=True)
class ComponentEntry:
    """
    A registered component definition.

    Attributes:
        name: Unique component identifier used by ``render_component(name, ...)``.
        template: Jinja2 template path (relative to the loader's search paths).
        has_endpoint: True if the component exposes an HTTP endpoint via
            ``extra_router`` (for HTMX lazy-load or action handlers).
        render_fn: Optional callable that produces the rendered HTML string.
            When ``None``, the framework renders ``template`` directly.
        extra_router: Optional :class:`fastapi.APIRouter` to mount alongside
            the component. Mounting is handled by the components mounting
            subsystem.
        module_id: Owning module ID, used by
            :meth:`ComponentRegistry.unregister_module` to drop all
            entries registered by a module on unload. ``None`` for
            built-in or project-level components.
        static_dir: Absolute filesystem path to the component's ``static/``
            directory, if any. Populated by the discovery subsystem when
            scoped assets are present.
        props_cls: Optional Pydantic model declared in the component's
            ``component.py``. When set, callers' keyword arguments are
            validated against this class before rendering. ``None`` for
            template-only components.
    """

    name: str
    template: str
    has_endpoint: bool = False
    render_fn: Callable[..., str] | None = None
    extra_router: APIRouter | None = None
    module_id: str | None = None
    static_dir: str | None = None
    props_cls: type | None = None
