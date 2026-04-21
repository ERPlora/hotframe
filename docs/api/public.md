# Public API

Every symbol listed below is importable from the top-level `hotframe`
package. Internal submodules are subject to change; the names on this
page are the stable surface that downstream projects (hub, cloud apps,
modules) depend on.

```python
from hotframe import create_app, HotframeSettings, ModuleService, action
```

The pages in the **Guides** section walk through how these pieces fit
together. This reference is auto-generated from the source docstrings —
if anything here is ambiguous, `src/hotframe/<module>.py` is the ground
truth.

---

## Application factory

::: hotframe.bootstrap.create_app

---

## Settings

::: hotframe.config.settings.HotframeSettings
    options:
      show_bases: false
      members: []

::: hotframe.config.settings.get_settings

---

## App & module configuration

::: hotframe.apps.config.AppConfig
    options:
      members: []

::: hotframe.apps.config.ModuleConfig
    options:
      members: []

---

## Service facade

The `ModuleService` base class and the `@action` decorator are the
entry point every module's `services.py` builds on. Convenience helpers
on the base (`success`, `error`, `parse_uuid`, `parse_date`,
`parse_decimal`, `get_or_none`, `get_or_error`, `atomic`) are shown on
the class page.

::: hotframe.apps.service_facade.ModuleService

::: hotframe.apps.service_facade.action

---

## Persistence protocols

Module and app code should depend on these Protocols, not on SQLAlchemy
directly. See the `DB persistence protocols` section of the
[Architecture](../ARCHITECTURE.md) guide.

::: hotframe.db.protocols.ISession
    options:
      members: []

::: hotframe.db.protocols.IQueryBuilder
    options:
      members: []

::: hotframe.db.protocols.IRepository
    options:
      members: []

---

## Query builder & repository

::: hotframe.models.queryset.HubQuery
    options:
      members_order: source

::: hotframe.repository.base.BaseRepository
    options:
      members_order: source

---

## Model bases

::: hotframe.models.base.Base
    options:
      members: []

---

## Views — HTMX & streaming

::: hotframe.views.responses.htmx_view

::: hotframe.views.responses.sse_stream

::: hotframe.views.streams.TurboStream

::: hotframe.views.broadcast.BroadcastHub
    options:
      members_order: source

---

## Signals — events & hooks

::: hotframe.signals.dispatcher.AsyncEventBus
    options:
      members_order: source

::: hotframe.signals.hooks.HookRegistry
    options:
      members_order: source

---

## Templating

::: hotframe.templating.slots.SlotRegistry
    options:
      members_order: source

---

## Module runtime

::: hotframe.engine.module_runtime.ModuleRuntime
    options:
      members:
        - install
        - activate
        - deactivate
        - uninstall
        - update

::: hotframe.engine.state.ModuleStateDB

::: hotframe.engine.pipeline.HotMountPipeline
    options:
      members: []

::: hotframe.engine.marketplace_client.MarketplaceClient
    options:
      members_order: source

---

## Testing utilities

::: hotframe.testing.create_test_app

::: hotframe.testing.FakeEventBus
    options:
      members: []

::: hotframe.testing.FakeHookRegistry
    options:
      members: []
