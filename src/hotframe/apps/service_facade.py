# SPDX-License-Identifier: Apache-2.0
"""
Module service infrastructure — base class, decorator, and registry.

Modules define service classes inheriting from ``ModuleService`` and
decorate methods with ``@action``. The registry is populated at
module load time.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, get_type_hints
from uuid import UUID

from hotframe.models.queryset import HubQuery
from hotframe.repository.base import BaseRepository, serialize, serialize_list

if TYPE_CHECKING:
    from hotframe.db.protocols import IQueryBuilder, IRepository, ISession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActionMeta:
    permission: str
    mutates: bool = False
    description: str = ""


def action(*, permission: str, mutates: bool = False, description: str = "") -> Any:
    """Decorator that marks a ModuleService method as a callable action with a required permission."""

    def decorator(fn: Any) -> Any:
        fn._action_meta = ActionMeta(
            permission=permission,
            mutates=mutates,
            description=description,
        )
        return fn

    return decorator


class ModuleService:
    """Base class for module services.

    Usage::

        class TodoService(ModuleService):
            module_id = "todo"

            @action(permission="todo.view")
            async def list_todos(self) -> list[dict]:
                return await self.repo(Todo).list()
    """

    module_id: str = ""

    def __init__(self, db: ISession, hub_id: UUID) -> None:
        self.db = db
        self.hub_id = hub_id

    def q(self, model: type) -> IQueryBuilder:
        return HubQuery(model, self.db, self.hub_id)

    def repo(
        self,
        model: type,
        *,
        search_fields: list[str] | None = None,
        default_order: str = "created_at",
    ) -> IRepository:
        """Return a hub-scoped BaseRepository for the given model."""
        return BaseRepository(
            model,
            self.db,
            self.hub_id,
            search_fields=search_fields,
            default_order=default_order,
        )

    @staticmethod
    def serialize(obj: Any, **kwargs: Any) -> dict:
        """Serialize a single ORM object to a plain dict."""
        return serialize(obj, **kwargs)

    @staticmethod
    def serialize_list(items: list, **kwargs: Any) -> list[dict]:
        """Serialize a list of ORM objects to a list of plain dicts."""
        return serialize_list(items, **kwargs)


@dataclass
class ActionEntry:
    method_name: str
    permission: str
    mutates: bool
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceEntry:
    cls: type[ModuleService]
    description: str
    actions: dict[str, ActionEntry] = field(default_factory=dict)


SERVICE_REGISTRY: dict[str, dict[str, ServiceEntry]] = {}


def _extract_parameters(method: Any) -> dict[str, Any]:
    sig = inspect.signature(method)
    try:
        hints = get_type_hints(method)
    except Exception:
        hints = {}

    params: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        info: dict[str, Any] = {}
        hint = hints.get(name)
        if hint is not None:
            info["type"] = _type_to_str(hint)
        if param.default is inspect.Parameter.empty:
            info["required"] = True
        else:
            info["required"] = False
            if param.default is not None:
                info["default"] = param.default
        params[name] = info

    return params


def _type_to_str(t: Any) -> str:
    origin = getattr(t, "__origin__", None)
    if t is str:
        return "string"
    if t is int:
        return "integer"
    if t is float or (hasattr(t, "__name__") and t.__name__ == "Decimal"):
        return "number"
    if t is bool:
        return "boolean"
    if t is UUID:
        return "string (UUID)"
    if origin is list:
        args = getattr(t, "__args__", ())
        if args:
            return f"array of {_type_to_str(args[0])}"
        return "array"
    try:
        from pydantic import BaseModel

        if isinstance(t, type) and issubclass(t, BaseModel):
            return f"object ({t.__name__})"
    except ImportError:
        pass
    if origin is type(str | None):
        args = getattr(t, "__args__", ())
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_str(non_none[0])
    name = getattr(t, "__name__", str(t))
    return name


def register_services(module_id: str) -> int:
    fqn = f"{module_id}.services"
    try:
        mod = importlib.import_module(fqn)
    except ModuleNotFoundError as exc:
        if exc.name == fqn:
            return 0
        logger.exception("Error in services import chain for %s", module_id)
        return 0
    except Exception:
        logger.exception("Error loading services for %s", module_id)
        return 0

    count = 0
    module_services: dict[str, ServiceEntry] = {}

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, type) and issubclass(attr, ModuleService) and attr is not ModuleService:
            attr.module_id = module_id
            service_desc = (attr.__doc__ or "").strip().split("\n")[0]
            actions: dict[str, ActionEntry] = {}
            for method_name in dir(attr):
                method = getattr(attr, method_name, None)
                meta: ActionMeta | None = getattr(method, "_action_meta", None)
                if meta is None:
                    continue
                desc = meta.description or (method.__doc__ or "").strip().split("\n")[0]
                full_perm = f"{module_id}.{meta.permission}"
                actions[method_name] = ActionEntry(
                    method_name=method_name,
                    permission=full_perm,
                    mutates=meta.mutates,
                    description=desc,
                    parameters=_extract_parameters(method),
                )
            if actions:
                module_services[attr_name] = ServiceEntry(
                    cls=attr,
                    description=service_desc,
                    actions=actions,
                )
                count += 1

    if module_services:
        SERVICE_REGISTRY[module_id] = module_services
        logger.info(
            "Registered %d service(s) from %s: %s", count, fqn, ", ".join(module_services.keys())
        )

    return count


def unregister_module_services(module_id: str) -> int:
    entry = SERVICE_REGISTRY.pop(module_id, None)
    if entry:
        count = len(entry)
        logger.debug("Unregistered %d services for %s", count, module_id)
        return count
    return 0


def has_services(module_id: str) -> bool:
    return module_id in SERVICE_REGISTRY


def generate_module_context(module_id: str) -> str:
    services = SERVICE_REGISTRY.get(module_id)
    if not services:
        return ""

    lines: list[str] = []
    for service_name, entry in services.items():
        lines.append(f"### {service_name}")
        if entry.description:
            lines.append(entry.description)
        for action_name, action_def in entry.actions.items():
            params_parts: list[str] = []
            for pname, pinfo in action_def.parameters.items():
                ptype = pinfo.get("type", "any")
                if pinfo.get("required"):
                    params_parts.append(f"{pname}: {ptype}")
                else:
                    default = pinfo.get("default", "")
                    if default != "" and default is not None:
                        params_parts.append(f"{pname}?: {ptype} = {default}")
                    else:
                        params_parts.append(f"{pname}?: {ptype}")
            params_str = ", ".join(params_parts)
            mode = "WRITE" if action_def.mutates else "READ"
            desc = action_def.description or action_name
            lines.append(f"- **{action_name}**({params_str}) → {desc} | {mode}")

    return "\n".join(lines)


def generate_all_contexts() -> dict[str, str]:
    return {module_id: generate_module_context(module_id) for module_id in SERVICE_REGISTRY}
