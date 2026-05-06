# Hooks and events

Hotframe ships with two complementary extensibility primitives, both
already implemented and battle-tested. This guide is the reference for
module authors — neither system needs to be built; just adopted.

| System | Class | When to use |
|---|---|---|
| Hooks (actions / filters) | `HookRegistry` (`hotframe.signals.hooks`) | A module declares an extension point and other modules plug into it. WordPress-style. |
| Async event bus | `AsyncEventBus` (`hotframe.signals.dispatcher`) | Runtime / cross-cutting events: `module.installed`, `module.error`, `sale.completed`, etc. Supports Pydantic-typed events. |

Both systems track callbacks per `module_id` so the loader can clean
them up on uninstall. You do not have to unsubscribe by hand.

---

## HookRegistry — actions and filters

`HookRegistry` lives at `app.state.hooks` and is exposed via the
`Hooks` dependency in `hotframe.auth.current_user`.

### Filters: chained transformation

A filter takes a value, lets every registered callback transform it,
and returns the final result.

```python
# In module ``invoice``: declare the extension point.
from hotframe import Hooks

async def calculate_total(items, hooks: Hooks):
    base = sum(item.subtotal for item in items)
    return await hooks.apply_filters("invoice.total", base, items=items)
```

```python
# In module ``descuentos_navidad``: plug into it.
from datetime import date

async def descuento_navidad(value, items=None):
    if date.today().month == 12:
        return value * 0.9
    return value


def register_hooks(hooks, module_id: str) -> None:
    hooks.add_filter(
        "invoice.total",
        descuento_navidad,
        priority=10,
        module_id=module_id,
    )
```

The `invoice` module knows nothing about `descuentos_navidad`.
Uninstalling `descuentos_navidad` calls `remove_module_hooks` and the
filter chain returns to the original behaviour automatically.

Lower `priority` values run first (default `10`). Within the same
priority, registration order is preserved.

### Actions: fire-and-forget notifications

```python
# In module ``sales``: announce a domain event.
from hotframe import Hooks

async def complete_sale(sale_id, hooks: Hooks):
    # ... commit DB ...
    await hooks.do_action("sale.completed", sale_id=sale_id)
```

```python
# In module ``loyalty``: subscribe.
async def award_points(sale_id=None):
    ...


def register_hooks(hooks, module_id: str) -> None:
    hooks.add_action(
        "sale.completed",
        award_points,
        priority=10,
        module_id=module_id,
    )
```

Actions return an `ActionResult` summarizing the calls — you typically
ignore it.

### Module discovery

The loader looks for `{module_id}/hooks.py` with a top-level
`register_hooks(hooks, module_id)` function and calls it on load.
Cleanup on uninstall is automatic via `remove_module_hooks(module_id)`.

---

## AsyncEventBus — typed runtime events

The bus lives at `app.state.event_bus` and is exposed as the `EventBus`
dependency. It supports two parallel APIs — pick whichever fits.

### Untyped emit (legacy / quick wins)

```python
from hotframe import EventBus

async def deactivate_module(module_id: str, bus: EventBus):
    await bus.emit("module.deactivated", module_id=module_id)
```

### Typed emit (Pydantic-validated, schema-introspectable)

```python
from hotframe import BaseEvent, EventBus, register_event

@register_event
class SaleCompletedEvent(BaseEvent):
    event_name = "sale.completed"
    sale_id: str
    total: float


async def complete_sale(sale_id, total, bus: EventBus):
    await bus.emit_typed(SaleCompletedEvent(sale_id=sale_id, total=total))
```

Typed handlers receive the Pydantic instance:

```python
async def on_sale(event: SaleCompletedEvent) -> None:
    print(event.total)


await bus.subscribe_typed(SaleCompletedEvent, on_sale, module_id="analytics")
```

Untyped handlers still receive `event=str, sender=None, **data`. The
two APIs share the same handler pool: a typed emit triggers untyped
handlers and vice versa.

### Module discovery

The loader looks for `{module_id}/events.py` with a top-level
`register_events(bus, module_id)` function. Cleanup on uninstall is
automatic via `bus.unsubscribe_module(module_id)`.

### Wildcards

```python
await bus.subscribe("module.*", log_module_lifecycle, module_id="audit")
```

`module.installed`, `module.activated`, `module.degraded`, etc. all
fire the same handler.

---

## Boundary events

The module boundary middleware (`hotframe.engine.boundary`) emits two
events tests and dashboards can hook:

| Event | Payload | When |
|---|---|---|
| `module.error` | `module_id`, `error`, `error_type`, `path`, `method` | Every captured exception inside a module route |
| `module.degraded` | `module_id`, `error`, `threshold`, `window_seconds` | Once the rolling threshold is crossed |

A common dashboard pattern:

```python
async def banner_on_degraded(event, sender=None, module_id=None, **_):
    await broadcast_hub.publish(
        "system",
        f"<div class='banner'>Module {module_id} degraded</div>",
    )


await bus.subscribe("module.degraded", banner_on_degraded, module_id="system")
```

---

## Choosing between hooks and events

- **Hooks** when there is a clear contract (what filter takes / returns,
  or what kwargs an action receives) and you want priority ordering
  for chained transformation. Closest to "WordPress filters/actions".
- **Events** when the producer publishes information and any number of
  consumers may listen, or when you want Pydantic-validated payloads
  that can be schema-introspected.

Both are async-first and thread-unsafe (use them from the asyncio
event loop). Both are cleaned up automatically on module uninstall.

---

## Cleanup contract (for module authors)

You do **not** need to unregister anything explicitly. The loader's
`unload_module` calls:

- `bus.unsubscribe_module(module_id)`
- `hooks.remove_module_hooks(module_id)`
- `slots.unregister_module(module_id)`
- `components.unregister_module(module_id)` (if a registry was injected)

If your `on_deactivate` opens long-lived resources (HTTP clients,
background tasks, file handles), close them there. Anything registered
through the registries above is reclaimed without your intervention.
