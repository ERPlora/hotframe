# Hub-Next → Hotframe Migration Guide

**Date:** 2026-04-17
**Context:** Hotframe is the generic motor extracted from `hub-next/runtime/`. This document
describes every change needed to make hub-next consume hotframe as an installed package
(`pip install hotframe`) instead of carrying a local `runtime/` copy.

---

## 1. Overview

### What changes and why

`hub-next/runtime/` is being extracted into the standalone `hotframe` library. Almost all
files in `runtime/` have direct equivalents in `hotframe/src/hotframe/`. After migration:

- `runtime/` is deleted from the hub-next repo.
- Hub-next adds `hotframe` as a dependency in `pyproject.toml`.
- All `from runtime.X import Y` imports in hub-next become `from hotframe.X import Y`.
- A small set of ERPlora-specific files that previously lived in `runtime/` must be
  recreated in hub-next itself, importing base classes from hotframe.

### Scope by the numbers

| Metric | Value |
|--------|-------|
| Files with `from runtime.` imports (outside `runtime/`) | 371 |
| Total import lines to change | 802 |
| `runtime/` Python files with direct hotframe equivalents | ~97 |
| `runtime/` Python files with no hotframe equivalent (ERPlora-specific) | 4 (plus `routing/websocket.py`) |
| New hub-next files to create | 6 |

---

## 2. Step-by-Step Migration Plan

Execute steps in order. Each step is independently verifiable.

### Step 1 — Install hotframe as a dependency

Edit `hub-next/pyproject.toml`. Until hotframe is published to PyPI, install from the
local path or from the GitHub repo. See section 8 for the exact diff.

### Step 2 — Create the new ERPlora-specific layer

Before deleting `runtime/`, create the hub-next replacement files that contain
ERPlora-specific logic. These files import from `hotframe` and add hub-specific behaviour
on top. See section 6 for the full content of each file.

Files to create:
1. `hub-next/hub/settings.py` — subclass `HotframeSettings` with HUB_* fields
2. `hub-next/hub/bootstrap.py` — ERPlora lifespan (extends hotframe's)
3. `hub-next/hub/auth/current_user.py` — hub-specific user + hub_id resolution
4. `hub-next/hub/templating/globals.py` — hub-specific template context hook
5. `hub-next/hub/signals/builtins.py` — ERPlora domain signals
6. `hub-next/hub/routing/websocket.py` — WebSocket handler (move from `runtime/routing/`)

### Step 3 — Rewire the entry points

Update the hub-next root files:

- `main.py` — change `from runtime.bootstrap import create_app` to
  `from hub.bootstrap import create_app`
- `asgi.py` — change `from runtime.asgi import application` to
  `from hotframe.asgi import application` (and configure proxy settings via settings)
- `settings.py` — change `from runtime.config.settings import get_settings` to
  `from hub.settings import get_settings`
- `manage.py` / `pyproject.toml [project.scripts]` — change `hub = "runtime.management.cli:cli"`
  to `hub = "hotframe.management.cli:app"`

### Step 4 — Global import replacement

Run the sed commands in section 5 to replace all `from runtime.` imports in `apps/`,
`modules/`, and root files.

### Step 5 — Fix the management command

`runtime/management/commands/modules_upgrade.py` contains a hardcoded `from runtime.apps
import ModuleConfig`. After migration this must read `from hotframe.apps import
ModuleConfig`. The file must move to `hub-next/hub/management/commands/modules_upgrade.py`
and use `hotframe` imports. See section 6.6.

### Step 6 — Update pyproject.toml

See section 8. Key changes: add hotframe dependency, update `[project.scripts]`, update
`[tool.hatch.build.targets.wheel]`, update `[tool.coverage.run]`.

### Step 7 — Update .importlinter

The `hub-next/.importlinter` file enforces layer contracts. Update `source_modules` from
`runtime` to `hotframe`. Add a new contract that prevents `hub` (the new ERPlora layer)
from being imported by `hotframe`.

### Step 8 — Delete `runtime/`

Once all imports are replaced and tests pass, delete the entire `runtime/` directory.

```bash
rm -rf hub-next/runtime/
```

### Step 9 — Run the test suite

```bash
cd hub-next
pytest -v
```

Fix any remaining import errors.

### Step 10 — Update CI/CD

- `Dockerfile`: remove any step that installs `runtime/` as a package. Add the hotframe
  install step. If hotframe is not yet on PyPI, add the build step.
- `docker-entrypoint.sh`: the CLI command changes from `hub` (which mapped to
  `runtime.management.cli:cli`) to `hub` (which will now map to `hotframe.management.cli:app`
  via `pyproject.toml`) — keep the same command name, just update the entrypoint mapping.
- GitHub Actions `test.yml`: no changes needed if hotframe is installed correctly.

---

## 3. Files to DELETE from hub-next

The following `runtime/` directories and files are fully replaced by hotframe. Delete them
after the new `hub/` layer is in place and tests pass.

### Entire directories to remove

```
runtime/apps/
runtime/asgi.py
runtime/auth/
runtime/bootstrap.py
runtime/config/
runtime/db/
runtime/dev/
runtime/discovery/     <- EXCEPT: see note below
runtime/engine/
runtime/forms/
runtime/management/    <- EXCEPT management/commands/modules_upgrade.py (must be moved)
runtime/middleware/
runtime/migrations/
runtime/models/
runtime/orm/
runtime/repository/
runtime/signals/       <- EXCEPT: see section 6.5 for ERPlora signals that stay
runtime/templating/    <- EXCEPT: see section 6.4 for hub context hook
runtime/testing/
runtime/utils/
runtime/views/
runtime/__init__.py
```

**Note on `runtime/routing/`:** This directory has no hotframe equivalent. Move its
content to `hub-next/hub/routing/` (see section 6.6).

**Note on `runtime/discovery/bootstrap.py`:** Hotframe has its own
`hotframe/discovery/bootstrap.py` but it is generic. Hub-next's version hardcodes
`KERNEL_MODULE_NAMES = ("assistant",)`. After migration, the kernel module list is
configured via `settings.KERNEL_MODULE_NAMES = ["assistant"]` in `hub/settings.py`.
The hotframe `boot_kernel_modules()` already reads from `settings.KERNEL_MODULE_NAMES`.

### Test files (delete alongside their source files)

All `runtime/*/tests/` directories are deleted together with their parent modules.

---

## 4. Files to KEEP in hub-next (ERPlora-Specific Wrappers)

The following files contain logic that is tightly coupled to ERPlora's data model and
must remain in hub-next. They import from `hotframe` base classes.

| File (new location) | What it does | Hotframe base it uses |
|---------------------|-------------|----------------------|
| `hub/settings.py` | Adds HUB_* fields to HotframeSettings | `hotframe.config.settings.HotframeSettings` |
| `hub/bootstrap.py` | ERPlora lifespan (HubConfig, roles, CloudClient, catalog sync, compliance) | `hotframe.bootstrap.lifespan` / `create_app` |
| `hub/auth/current_user.py` | Adds `hub_id` resolution + multi-tenant user filtering | `hotframe.auth.current_user` (re-exports) |
| `hub/templating/globals.py` | Adds `hub_config`, `business_name`, `HUB_CONFIG`, `HUB_CURRENCY`, `store_config` | Called as `settings.GLOBAL_CONTEXT_HOOK` |
| `hub/signals/builtins.py` | ERPlora domain signals (sales, inventory, customers, etc.) | Standalone — just string constants |
| `hub/routing/websocket.py` | WebSocket handler with ping keepalive for AI assistant | Standalone — no hotframe equivalent |
| `hub/management/commands/modules_upgrade.py` | AST upgrade tool for legacy module.py | Imports `from hotframe.apps import ModuleConfig` |

---

## 5. Import Changes

### The mechanical replacement

Every `from runtime.X import Y` outside of `runtime/` itself must become
`from hotframe.X import Y`. The only exceptions are the files that belong to the new
`hub/` layer (see section 6).

Run these sed commands from `hub-next/`:

```bash
# Dry run first — review output
grep -r "from runtime\." apps/ modules/ main.py asgi.py settings.py manage.py --include="*.py" -l

# Replace in apps/
find apps/ -name "*.py" -exec sed -i 's/from runtime\./from hotframe./g' {} +

# Replace in modules/
find modules/ -name "*.py" -exec sed -i 's/from runtime\./from hotframe./g' {} +

# Replace in root files
sed -i 's/from runtime\./from hotframe./g' main.py asgi.py settings.py manage.py

# Replace bare `import runtime.X` (2 files)
find apps/ modules/ -name "*.py" -exec sed -i 's/import runtime\./import hotframe./g' {} +
```

After running these, manually verify these high-frequency import paths because they touch
ERPlora-specific overrides:

| Old import | New import | Notes |
|------------|-----------|-------|
| `from runtime.config.settings import get_settings` | `from hub.settings import get_settings` | Must use hub's Settings subclass, not hotframe base |
| `from runtime.auth.current_user import CurrentUser, DbSession, HubId` | `from hub.auth.current_user import CurrentUser, DbSession, HubId` | Hub-specific, see section 6.3 |
| `from runtime.templating.globals import get_global_context` | Not needed — called via `settings.GLOBAL_CONTEXT_HOOK` | No direct import in user code |
| `from runtime.bootstrap import create_app` | `from hub.bootstrap import create_app` | ERPlora lifespan |
| `from runtime.signals.builtins import SALES_CREATED, ...` | `from hub.signals.builtins import SALES_CREATED, ...` | ERPlora domain signals |
| `from runtime.routing.websocket import ws_handler, ws_send` | `from hub.routing.websocket import ws_handler, ws_send` | Moved to hub layer |

### Import frequency (top 15 — all become `from hotframe.X`)

These are the most common import targets. All map 1:1 to hotframe:

| Import source | Count | Hotframe equivalent |
|---------------|-------|---------------------|
| `runtime.models.queryset` | 81 | `hotframe.models.queryset` |
| `runtime.models.base` | 68 | `hotframe.models.base` |
| `runtime.auth.current_user` | 64 | `hub.auth.current_user` (hub layer) |
| `runtime.orm.transactions` | 63 | `hotframe.orm.transactions` |
| `runtime.config.settings` | 61 | `hub.settings` (hub layer) |
| `runtime.views.responses` | 44 | `hotframe.views.responses` |
| `runtime.signals.dispatcher` | 42 | `hotframe.signals.dispatcher` |
| `runtime.apps.service_facade` | 37 | `hotframe.apps.service_facade` |
| `runtime.signals.hooks` | 36 | `hotframe.signals.hooks` |
| `runtime.templating.slots` | 33 | `hotframe.templating.slots` |
| `runtime.config.database` | 26 | `hotframe.config.database` |
| `runtime.templating.globals` | 21 | `hotframe.templating.globals` (via hook) |
| `runtime.apps` | 17 | `hotframe.apps` |
| `runtime.auth.auth` | 16 | `hotframe.auth.auth` |
| `runtime.apps.config` | 13 | `hotframe.apps.config` |

**Total: 802 import lines across 371 files** (371 `from runtime.*` files, 2 `import runtime.*` files).

---

## 6. New Files to Create in hub-next

Create a new `hub/` package at `hub-next/hub/`. This is the ERPlora-specific layer that
sits on top of hotframe. Each file below is the complete target content.

### 6.1 `hub-next/hub/__init__.py`

```python
"""ERPlora Hub — application layer."""
```

### 6.2 `hub-next/hub/settings.py`

This subclasses `HotframeSettings` and adds every ERPlora/hub-specific field that was in
`runtime/config/settings.py`. It must use `env_prefix="HUB_"` so existing env vars work
unchanged.

```python
"""
ERPlora Hub settings.

Subclasses HotframeSettings with Hub-specific fields.
All environment variables use the HUB_ prefix (e.g. HUB_HUB_ID, HUB_DATABASE_URL).
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from hotframe.config.settings import HotframeSettings, set_settings


class Settings(HotframeSettings):
    model_config = SettingsConfigDict(
        env_prefix="HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Hub identity ---
    HUB_ID: UUID | None = None
    HUB_JWT: str | None = None
    HUB_REFRESH_TOKEN: str | None = None

    # --- Cloud API ---
    CLOUD_API_URL: str = "http://localhost:8001"
    CLOUD_WS_URL: str = "wss://erplora.com/api/v1/hub/device/assistant/chat/ws/"
    ASSISTANT_PROTOCOL: Literal["ws", "sse"] = "ws"

    # --- AWS / S3 (ERPlora-specific overrides) ---
    S3_MODULES_BUCKET: str = "erplora-storage"
    S3_MEDIA_BUCKET: str = "erplora-storage"
    AWS_REGION: str = "eu-west-1"

    # --- Media storage ---
    MEDIA_STORAGE: str = "local"  # "local" or "s3"

    # --- Bridge (hardware) ---
    BRIDGE_HOST: str = "localhost"
    BRIDGE_PORT: int = 12321

    # --- ERPlora overrides of hotframe defaults ---
    DATABASE_URL: str = "sqlite+aiosqlite:///./hub.db"
    CURRENCY: str = "EUR"
    APP_TITLE: str = "ERPlora Hub"
    OTEL_SERVICE_NAME: str = "erplora-hub"
    PROXY_FIX_ENABLED: bool = False  # set True in production via env
    KERNEL_MODULE_NAMES: list[str] = ["assistant"]

    # --- Hotframe hooks ---
    AUTH_USER_MODEL: str = "apps.accounts.models.LocalUser"
    AUTH_LOGIN_URL: str = "/login/"
    GLOBAL_CONTEXT_HOOK: str = "hub.templating.globals.get_hub_context"
    MODULE_STATE_MODEL: str = "apps.system.models.HubModule"

    @property
    def bridge_url(self) -> str:
        return f"ws://{self.BRIDGE_HOST}:{self.BRIDGE_PORT}"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        set_settings(_settings)  # Register with hotframe's get_settings()
    return _settings


def reset_settings() -> None:
    """Reset cached settings (for testing)."""
    global _settings
    _settings = None
    from hotframe.config.settings import reset_settings as _reset
    _reset()
```

### 6.3 `hub-next/hub/auth/__init__.py` and `hub-next/hub/auth/current_user.py`

Hub-next's user resolution adds `hub_id` resolution (multi-tenant) on top of hotframe's
generic `get_current_user`. The 64 files that import `CurrentUser`, `DbSession`, `HubId`
must now import from `hub.auth.current_user`.

**`hub-next/hub/auth/__init__.py`:**
```python
"""Hub auth layer."""
```

**`hub-next/hub/auth/current_user.py`:**
```python
"""
Hub-specific FastAPI dependency injection providers.

Adds HUB_ID resolution (multi-tenant) on top of hotframe's generic providers.
Routes that need hub_id should import HubId, DbSession, CurrentUser from here.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hotframe.auth.auth import get_session_user_id
from hotframe.auth.current_user import (
    EventBus,
    Hooks,
    Slots,
    get_event_bus,
    get_hooks,
    get_slots,
)

if TYPE_CHECKING:
    from apps.accounts.models import LocalUser
    from hotframe.signals.dispatcher import AsyncEventBus
    from hotframe.signals.hooks import HookRegistry
    from hotframe.templating.slots import SlotRegistry

# Re-export generic registry deps unchanged
__all__ = [
    "HubId", "DbSession", "CurrentUser", "OptionalUser",
    "EventBus", "Hooks", "Slots",
    "get_hub_id", "get_db", "get_current_user", "get_current_user_optional",
    "get_event_bus", "get_hooks", "get_slots",
]


# ---------------------------------------------------------------------------
# Hub identity
# ---------------------------------------------------------------------------

async def get_hub_id(request: Request) -> UUID:
    """
    Resolve the hub_id for the current instance.

    Resolution order:
    1. Session (for multi-hub scenarios)
    2. Settings.HUB_ID (single-hub ECS deployment)
    3. HubConfig singleton in database

    Raises:
        HTTPException 500: If hub_id cannot be resolved.
    """
    from hub.settings import get_settings

    settings = get_settings()

    # 1. Session override
    session: dict = getattr(request.state, "session", {})
    raw = session.get("hub_id")
    if raw:
        try:
            return UUID(str(raw))
        except (ValueError, TypeError):
            pass

    # 2. Settings
    if settings.HUB_ID is not None:
        return settings.HUB_ID

    # 3. Database fallback
    try:
        from hotframe.config.database import get_session_factory
        from apps.configuration.models import HubConfig

        factory = get_session_factory()
        async with factory() as db:
            result = await db.execute(select(HubConfig.hub_id).limit(1))
            hub_id = result.scalar_one_or_none()
            if hub_id:
                return hub_id
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Hub ID not configured — set HUB_HUB_ID env var",
    )


HubId = Annotated[UUID, Depends(get_hub_id)]


# ---------------------------------------------------------------------------
# Database session (with hub_id context for ORM auto-fill)
# ---------------------------------------------------------------------------

async def get_db(hub_id: UUID = Depends(get_hub_id)) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async session with hub_id context for tenant isolation.

    hub_id is stored in session.info["hub_id"] for ORM event listeners.
    """
    from hotframe.config.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        session.info["hub_id"] = hub_id
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Current user (multi-tenant: filters by hub_id)
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    db: DbSession,
    hub_id: UUID = Depends(get_hub_id),
) -> "LocalUser":
    """
    Resolve the authenticated user filtered by hub_id.

    Raises:
        HTTPException 401: If not authenticated or user not found.
    """
    user_id = get_session_user_id(request)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    from apps.accounts.models import LocalUser

    result = await db.execute(
        select(LocalUser).where(
            LocalUser.id == user_id,
            LocalUser.hub_id == hub_id,
            LocalUser.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    perms: list[str] = []
    if user.is_admin:
        perms = ["*"]
    elif user.role and user.role.permissions:
        perms = [rp.permission_pattern for rp in user.role.permissions]
    request.state.user_permissions = perms
    request.state.current_user = user

    return user


async def get_current_user_optional(
    request: Request,
    db: DbSession,
    hub_id: UUID = Depends(get_hub_id),
) -> "LocalUser | None":
    """Same as get_current_user but returns None if not authenticated."""
    user_id = get_session_user_id(request)
    if user_id is None:
        return None

    from apps.accounts.models import LocalUser

    result = await db.execute(
        select(LocalUser).where(
            LocalUser.id == user_id,
            LocalUser.hub_id == hub_id,
            LocalUser.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    if user is not None:
        request.state.user_permissions = getattr(user, "permissions", []) or []
        request.state.current_user = user

    return user


CurrentUser = Annotated["LocalUser", Depends(get_current_user)]
OptionalUser = Annotated["LocalUser | None", Depends(get_current_user_optional)]
```

### 6.4 `hub-next/hub/templating/globals.py`

This file is the ERPlora-specific template context hook. It is **not imported directly**
by any module — instead it is referenced by `settings.GLOBAL_CONTEXT_HOOK =
"hub.templating.globals.get_hub_context"`. Hotframe's `get_global_context` calls this
hook and merges the result.

**`hub-next/hub/templating/__init__.py`:**
```python
"""Hub templating layer."""
```

**`hub-next/hub/templating/globals.py`:**
```python
"""
ERPlora Hub template context hook.

Called by hotframe's get_global_context via settings.GLOBAL_CONTEXT_HOOK.
Adds hub_config, business_name, HUB_CONFIG, HUB_CURRENCY, store_config.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request


async def get_hub_context(request: Request) -> dict[str, Any]:
    """
    Return ERPlora-specific template variables.

    Merged into every template render by hotframe's global context builder.
    """
    from hub.settings import get_settings

    settings = get_settings()
    context: dict[str, Any] = {}

    # Hub configuration
    hub_config = getattr(request.state, "hub_config", None)
    if hub_config:
        context["hub_config"] = hub_config
        context["business_name"] = (
            getattr(hub_config, "business_name", None) or "ERPlora Hub"
        )
    else:
        context["business_name"] = "ERPlora Hub"

    # Legacy alias used by JS snippets: HUB_CONFIG.currency
    context["HUB_CONFIG"] = hub_config
    if hub_config is not None:
        context["HUB_CURRENCY"] = getattr(hub_config, "currency", None) or settings.CURRENCY
    else:
        context["HUB_CURRENCY"] = settings.CURRENCY

    # Store configuration
    store_config = getattr(request.state, "store_config", None)
    if store_config:
        context["store_config"] = store_config

    return context
```

### 6.5 `hub-next/hub/signals/builtins.py`

Hotframe's `hotframe/signals/builtins.py` only contains generic framework signals (model
lifecycle, auth, modules, sync, print). All ERPlora domain signals (sales, inventory,
customers, cash register, invoicing, sections, loyalty, kitchen, payroll, leave, messaging,
delivery) are ERPlora-specific and must live in hub-next.

**`hub-next/hub/signals/__init__.py`:**
```python
"""Hub signals layer."""
```

**`hub-next/hub/signals/builtins.py`:**
```python
"""
ERPlora domain signal constants.

Extends hotframe's framework signals with business domain signals specific
to ERPlora's module ecosystem.

Import framework signals from hotframe:
    from hotframe.signals.builtins import MODEL_POST_SAVE, AUTH_LOGIN, ...

Import domain signals from here:
    from hub.signals.builtins import SALES_CREATED, INVENTORY_STOCK_CHANGED, ...
"""
from __future__ import annotations

# Re-export all framework signals for convenience (single import point)
from hotframe.signals.builtins import (
    AUTH_LOGIN,
    AUTH_LOGOUT,
    MODEL_POST_DELETE,
    MODEL_POST_SAVE,
    MODEL_PRE_DELETE,
    MODEL_PRE_SAVE,
    MODULES_ACTIVATED,
    MODULES_DEACTIVATED,
    MODULES_INSTALLED,
    MODULES_UNINSTALLED,
    MODULES_UPDATED,
    PRINT_COMPLETED,
    PRINT_FAILED,
    PRINT_REQUESTED,
    SYNC_COMPLETED,
    SYNC_FAILED,
    SYNC_STARTED,
    SYSTEM_SIGNALS,
    get_event_class,
    get_signal_event_map,
)

__all__ = [
    # Framework signals (re-exported)
    "MODEL_PRE_SAVE", "MODEL_POST_SAVE", "MODEL_PRE_DELETE", "MODEL_POST_DELETE",
    "AUTH_LOGIN", "AUTH_LOGOUT",
    "MODULES_INSTALLED", "MODULES_ACTIVATED", "MODULES_DEACTIVATED",
    "MODULES_UPDATED", "MODULES_UNINSTALLED",
    "SYNC_STARTED", "SYNC_COMPLETED", "SYNC_FAILED",
    "PRINT_REQUESTED", "PRINT_COMPLETED", "PRINT_FAILED",
    # Domain signals
    "SALES_CREATED", "SALES_COMPLETED", "SALES_CANCELLED", "SALES_REFUNDED",
    "SALE_VOIDED", "SALE_INVOICED",
    "INVENTORY_PRODUCT_CREATED", "INVENTORY_PRODUCT_UPDATED",
    "INVENTORY_PRODUCT_DELETED", "INVENTORY_STOCK_CHANGED", "INVENTORY_LOW_STOCK",
    "CUSTOMERS_CREATED", "CUSTOMERS_UPDATED", "CUSTOMERS_DELETED",
    "CASH_REGISTER_SESSION_OPENED", "CASH_REGISTER_SESSION_CLOSED",
    "CASH_REGISTER_MOVEMENT_CREATED",
    "INVOICING_CREATED", "INVOICING_SENT", "INVOICING_PAID",
    "INVOICE_CREATED", "INVOICE_CANCELLED", "INVOICE_CANCELLATION_REQUESTED",
    "INVOICE_RECTIFIED",
    "SECTIONS_TABLE_OPENED", "SECTIONS_TABLE_CLOSED", "SECTIONS_TABLE_TRANSFERRED",
    "LOYALTY_POINTS_EARNED", "LOYALTY_POINTS_REDEEMED", "LOYALTY_TIER_CHANGED",
    "KITCHEN_ORDER_REQUIRED", "KITCHEN_ORDER_CREATED", "KITCHEN_ORDER_FIRED",
    "KITCHEN_ORDER_READY",
    "PAYROLL_CALCULATION_REQUESTED", "PAYROLL_CALCULATION_COMPLETED",
    "PAYROLL_LINE_REQUESTED",
    "LEAVE_REQUEST_CREATED", "LEAVE_REQUEST_APPROVED", "LEAVE_REQUEST_REJECTED",
    "LEAVE_REQUEST_CANCELLED", "LEAVE_CONFLICTS_DETECTED",
    "SHIFT_CREATE_REQUESTED", "ATTENDANCE_CLOCK_IN_REQUESTED",
    "TIME_CONTROL_CLOCK_IN_REQUESTED",
    "MESSAGING_INBOUND_RECEIVED", "MESSAGING_OUTBOUND_REQUESTED",
    "MESSAGING_OUTBOUND_SENT", "MESSAGING_CONVERSATION_ASSIGNED",
    "MESSAGING_DELIVERY_FAILED",
    "DELIVERY_ORDER_CREATED", "DELIVERY_ORDER_COMPLETED",
]

# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------
SALES_CREATED = "sales.created"
SALES_COMPLETED = "sales.completed"
SALES_CANCELLED = "sales.cancelled"
SALES_REFUNDED = "sales.refunded"
SALE_VOIDED = "sale.voided"
SALE_INVOICED = "sale.invoiced"

# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
INVENTORY_PRODUCT_CREATED = "inventory.product_created"
INVENTORY_PRODUCT_UPDATED = "inventory.product_updated"
INVENTORY_PRODUCT_DELETED = "inventory.product_deleted"
INVENTORY_STOCK_CHANGED = "inventory.stock_changed"
INVENTORY_LOW_STOCK = "inventory.low_stock"

# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------
CUSTOMERS_CREATED = "customers.created"
CUSTOMERS_UPDATED = "customers.updated"
CUSTOMERS_DELETED = "customers.deleted"

# ---------------------------------------------------------------------------
# Cash Register
# ---------------------------------------------------------------------------
CASH_REGISTER_SESSION_OPENED = "cash_register.session_opened"
CASH_REGISTER_SESSION_CLOSED = "cash_register.session_closed"
CASH_REGISTER_MOVEMENT_CREATED = "cash_register.movement_created"

# ---------------------------------------------------------------------------
# Invoicing
# ---------------------------------------------------------------------------
INVOICING_CREATED = "invoicing.created"
INVOICING_SENT = "invoicing.sent"
INVOICING_PAID = "invoicing.paid"
INVOICE_CREATED = "invoice.created"
INVOICE_CANCELLED = "invoice.cancelled"
INVOICE_CANCELLATION_REQUESTED = "invoice.cancellation_requested"
INVOICE_RECTIFIED = "invoice.rectified"

# ---------------------------------------------------------------------------
# Sections (tables, zones)
# ---------------------------------------------------------------------------
SECTIONS_TABLE_OPENED = "sections.table_opened"
SECTIONS_TABLE_CLOSED = "sections.table_closed"
SECTIONS_TABLE_TRANSFERRED = "sections.table_transferred"

# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------
LOYALTY_POINTS_EARNED = "loyalty.points_earned"
LOYALTY_POINTS_REDEEMED = "loyalty.points_redeemed"
LOYALTY_TIER_CHANGED = "loyalty.tier_changed"

# ---------------------------------------------------------------------------
# Kitchen orders
# ---------------------------------------------------------------------------
KITCHEN_ORDER_REQUIRED = "kitchen.order_required"
KITCHEN_ORDER_CREATED = "kitchen.order_created"
KITCHEN_ORDER_FIRED = "kitchen.order_fired"
KITCHEN_ORDER_READY = "kitchen.order_ready"

# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------
PAYROLL_CALCULATION_REQUESTED = "payroll.calculation_requested"
PAYROLL_CALCULATION_COMPLETED = "payroll.calculation_completed"
PAYROLL_LINE_REQUESTED = "payroll.line_requested"

# ---------------------------------------------------------------------------
# Leave & workforce
# ---------------------------------------------------------------------------
LEAVE_REQUEST_CREATED = "leave.request_created"
LEAVE_REQUEST_APPROVED = "leave.request_approved"
LEAVE_REQUEST_REJECTED = "leave.request_rejected"
LEAVE_REQUEST_CANCELLED = "leave.request_cancelled"
LEAVE_CONFLICTS_DETECTED = "leave.conflicts_detected"
SHIFT_CREATE_REQUESTED = "shift.create_requested"
ATTENDANCE_CLOCK_IN_REQUESTED = "attendance.clock_in_requested"
TIME_CONTROL_CLOCK_IN_REQUESTED = "time_control.clock_in_requested"

# ---------------------------------------------------------------------------
# Messaging (unified)
# ---------------------------------------------------------------------------
MESSAGING_INBOUND_RECEIVED = "messaging.inbound_received"
MESSAGING_OUTBOUND_REQUESTED = "messaging.outbound_requested"
MESSAGING_OUTBOUND_SENT = "messaging.outbound_sent"
MESSAGING_CONVERSATION_ASSIGNED = "messaging.conversation_assigned"
MESSAGING_DELIVERY_FAILED = "messaging.delivery_failed"

# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------
DELIVERY_ORDER_CREATED = "delivery.order_created"
DELIVERY_ORDER_COMPLETED = "delivery.order_completed"
```

### 6.6 `hub-next/hub/routing/websocket.py`

This file has no hotframe equivalent — it is moved unchanged from
`runtime/routing/websocket.py` to `hub/routing/websocket.py`. The only change is that
there are no `from runtime.*` imports in it (it is self-contained).

**`hub-next/hub/routing/__init__.py`:**
```python
"""Hub routing utilities."""
```

Copy `runtime/routing/websocket.py` verbatim to `hub/routing/websocket.py`.

### 6.7 `hub-next/hub/bootstrap.py`

This is the most complex file — the ERPlora-specific lifespan. Hotframe's `create_app()`
is the entry point but its lifespan only does generic setup (DB engine, event bus, module
runtime). All of hub-next's ERPlora-specific startup steps must be preserved here.

The strategy is: **call hotframe's `create_app()` then extend it** using FastAPI's
lifespan pattern.

```python
"""
ERPlora Hub application factory.

Wraps hotframe's create_app() and adds ERPlora-specific lifespan:
- HubConfig bootstrap (create on first start, sync JWT tokens)
- Default role seeding
- CloudClient initialization
- Catalog sync from Cloud
- Core service registration
- Compliance event listeners
- MediaService initialization
- Static file mounts
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger("hub")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """ERPlora Hub startup/shutdown lifecycle."""
    t0 = time.monotonic()

    # --- Delegate to hotframe's generic lifespan first ---
    from hotframe.bootstrap import lifespan as _hotframe_lifespan

    async with _hotframe_lifespan(app):

        # All code below runs AFTER hotframe sets up DB engine, event bus,
        # registries, template engine, and module runtime.

        from hub.settings import get_settings
        from hotframe.config.database import get_session_factory

        settings = get_settings()
        event_bus = app.state.event_bus

        # 1b. Import all core models so SQLAlchemy can resolve ForeignKey refs
        __import__("apps.accounts.models")
        __import__("apps.configuration.models")

        # 2. Bootstrap HubConfig (create if not exists, sync JWT tokens)
        if settings.HUB_ID is not None:
            factory = get_session_factory()
            async with factory() as session:
                from apps.configuration.models import HubConfig
                from sqlalchemy import select as _sel

                result = await session.execute(_sel(HubConfig).limit(1))
                hub_config = result.scalar_one_or_none()
                if not hub_config:
                    _jwt = settings.HUB_JWT or ""
                    hub_config = HubConfig(
                        id=settings.HUB_ID,
                        hub_id=settings.HUB_ID,
                        hub_jwt=_jwt,
                        hub_refresh_token=settings.HUB_REFRESH_TOKEN or "",
                        language=settings.LANGUAGE,
                        currency=settings.CURRENCY,
                    )
                    session.add(hub_config)
                    await session.flush()
                    logger.info("HubConfig created for hub %s", settings.HUB_ID)

                # Sync tokens from env vars (Cloud may regenerate on redeploy)
                tokens_changed = False
                if settings.HUB_JWT and hub_config.hub_jwt != settings.HUB_JWT:
                    hub_config.hub_jwt = settings.HUB_JWT
                    tokens_changed = True
                if settings.HUB_REFRESH_TOKEN and hub_config.hub_refresh_token != settings.HUB_REFRESH_TOKEN:
                    hub_config.hub_refresh_token = settings.HUB_REFRESH_TOKEN
                    tokens_changed = True
                if tokens_changed:
                    logger.info("HubConfig tokens synced from env for hub %s", settings.HUB_ID)

                # Ensure default roles
                from apps.accounts.models import Role, RolePermission

                for role_name, role_desc, perm in [
                    ("admin", "Full system access", "*"),
                    ("manager", "Store management access", "*.view_*,*.change_*"),
                    ("employee", "Basic employee access", "*.view_*"),
                ]:
                    role_result = await session.execute(
                        _sel(Role).where(
                            Role.hub_id == settings.HUB_ID,
                            Role.name == role_name,
                        )
                    )
                    if not role_result.scalar_one_or_none():
                        role = Role(
                            hub_id=settings.HUB_ID,
                            name=role_name,
                            role_type="basic",
                            is_system=True,
                            description=role_desc,
                        )
                        session.add(role)
                        await session.flush()
                        session.add(RolePermission(
                            role_id=role.id,
                            permission_pattern=perm,
                        ))

                await session.commit()
                logger.info("Default roles ensured for hub %s", settings.HUB_ID)

        # 3. Initialize CloudClient
        from apps.shared.services import cloud_client as _cc_module
        from apps.shared.services.cloud_client import CloudClient

        cloud_client = CloudClient(app)
        app.state.cloud_client = cloud_client
        _cc_module._client_instance = cloud_client
        logger.info("CloudClient initialized")

        # 4. Catalog sync from Cloud BEFORE module boot
        if settings.HUB_ID is not None:
            factory2 = get_session_factory()
            async with factory2() as sync_session:
                sync_session.info["hub_id"] = settings.HUB_ID
                try:
                    from apps.sync.catalog_sync import sync_catalog
                    result = await sync_catalog(sync_session, settings.HUB_ID)
                    if result.get("error"):
                        logger.warning("Startup catalog sync failed: %s", result["error"])
                    elif result.get("total", 0) > 0:
                        logger.info("Startup catalog sync: %d modules", result["total"])
                except Exception:
                    logger.warning("Startup catalog sync failed — will sync on first visit")

        # 5. Register core services
        from hotframe.apps.service_facade import register_core_services
        register_core_services()

        # 6. Register compliance event listeners
        from apps.system.compliance_resolver import register_events as _reg_compliance
        _reg_compliance(event_bus)

        # 7. Initialize MediaService
        from apps.shared.services.media import MediaService

        storage_mode = "s3" if settings.DEPLOYMENT_MODE == "web" else "local"
        app.state.media = MediaService(
            storage=storage_mode,
            bucket=settings.S3_MEDIA_BUCKET,
            hub_id=str(settings.HUB_ID) if settings.HUB_ID else "dev",
        )

        elapsed = (time.monotonic() - t0) * 1000
        logger.info("ERPlora Hub started in %.0fms", elapsed)

        yield

    logger.info("ERPlora Hub shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the ERPlora Hub FastAPI application."""
    from hub.settings import get_settings
    from hotframe.config.settings import set_settings
    from hotframe.bootstrap import create_app as _hotframe_create_app

    settings = get_settings()
    set_settings(settings)

    # Create app via hotframe (sets up middleware, error handlers, broadcast router)
    app = _hotframe_create_app(settings=settings)

    # Override lifespan with the ERPlora-specific one
    # Note: FastAPI doesn't support replacing lifespan after creation.
    # Instead, recreate with the ERPlora lifespan.
    from hotframe.utils.observability_logging import setup_logging
    from hotframe.utils.observability_telemetry import setup_telemetry

    json_output = settings.LOG_FORMAT == "json" or (
        settings.LOG_FORMAT == "console" and settings.is_production
    )
    setup_logging(log_level=settings.LOG_LEVEL, json_output=json_output)
    try:
        setup_telemetry(
            debug=settings.DEBUG,
            service_name=settings.OTEL_SERVICE_NAME,
        )
    except Exception as exc:
        import logging as _log
        _log.getLogger("hub").warning("Telemetry setup failed: %s", exc)

    app = FastAPI(
        title="ERPlora Hub",
        version="0.1.0",
        docs_url="/api/docs" if settings.DEBUG else None,
        redoc_url="/api/redoc" if settings.DEBUG else None,
        openapi_url="/api/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # Mount static files
    app.mount("/static", StaticFiles(directory="static"), name="static")
    if settings.DEBUG:
        import os
        os.makedirs("/tmp/hub-media", exist_ok=True)
        app.mount("/media", StaticFiles(directory="/tmp/hub-media"), name="media")

    # Middleware stack
    from hotframe.middleware.stack import build_middleware_stack
    build_middleware_stack(app, settings)

    # Rate limiter
    from hotframe.auth.rate_limit import PINRateLimiter
    app.state.rate_limiter = PINRateLimiter()

    # Error handlers (same as hotframe but with ERPlora login URL)
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/login/", status_code=302)

    @app.exception_handler(403)
    async def forbidden_handler(request: Request, exc):
        templates = request.app.state.templates
        nonce = getattr(request.state, "csp_nonce", "")
        return templates.TemplateResponse(
            request, "errors/403.html",
            {"request": request, "csp_nonce": nonce}, status_code=403,
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(request: Request, exc):
        templates = request.app.state.templates
        nonce = getattr(request.state, "csp_nonce", "")
        return templates.TemplateResponse(
            request, "errors/405.html",
            {"request": request, "csp_nonce": nonce}, status_code=405,
        )

    # Broadcast router
    from hotframe.views.broadcast import broadcast_router
    app.include_router(broadcast_router)

    # WebSocket stream
    from fastapi import WebSocket as FastAPIWebSocket
    from hotframe.views.broadcast import ws_broadcast_handler

    @app.websocket("/ws/stream/{topic:path}")
    async def ws_stream(websocket: FastAPIWebSocket, topic: str):
        await ws_broadcast_handler(websocket, topic)

    # Core app routers
    from apps.accounts.routes import router as accounts_router
    from apps.accounts.api import api_router as accounts_api_router
    from apps.main.routes import router as main_router
    from apps.main.compliance_routes import router as compliance_router
    from apps.main.employees_api import api_router as employees_api_router
    from apps.marketplace.routes import router as marketplace_router
    from apps.marketplace.api import api_router as marketplace_api_router
    from apps.configuration.routes import router as config_router
    from apps.configuration.api import api_router as config_api_router
    from apps.sync.routes import router as sync_router
    from apps.system.routes import router as system_router
    from apps.htmx.routes import router as htmx_router
    from apps.public.routes import router as public_router

    for router in [
        accounts_router, accounts_api_router, main_router, compliance_router,
        employees_api_router, marketplace_router, marketplace_api_router,
        config_router, config_api_router, sync_router, system_router,
        htmx_router, public_router,
    ]:
        app.include_router(router)

    return app
```

**Important note on `create_app` duplication:** The current `runtime/bootstrap.py`
`create_app()` creates a single FastAPI instance with `lifespan=lifespan`. Because
FastAPI does not allow replacing the lifespan after instantiation, the hub's `create_app()`
must instantiate FastAPI directly (not delegate to hotframe's `create_app()`), but it
must still call hotframe's middleware builder and observability setup. The lifespan uses
the `async with _hotframe_lifespan(app)` pattern to nest ERPlora setup inside hotframe's
generic startup.

---

## 7. Configuration Changes

### Settings fields comparison

| Field | runtime/config/settings.py | hub/settings.py | Notes |
|-------|---------------------------|-----------------|-------|
| `env_prefix` | `HUB_` | `HUB_` | Unchanged — all env vars keep `HUB_` prefix |
| `DATABASE_URL` | `sqlite+aiosqlite:///./hub.db` | Inherited, overridden default | Same |
| `SECRET_KEY` | Hotframe base | Inherited | No change |
| `DEBUG` | Hotframe base | Inherited | No change |
| `MODULES_DIR` | Hotframe base | Inherited | No change |
| `S3_MODULES_BUCKET` | `erplora-storage` | `erplora-storage` | Override hotframe default |
| `S3_MEDIA_BUCKET` | `erplora-storage` | Added field | New |
| `AWS_REGION` | `eu-west-1` | `eu-west-1` | Override hotframe default |
| `HUB_ID` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `HUB_JWT` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `HUB_REFRESH_TOKEN` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `CLOUD_API_URL` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `CLOUD_WS_URL` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `ASSISTANT_PROTOCOL` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `BRIDGE_HOST` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `BRIDGE_PORT` | Hub-specific | Moved to hub/settings.py | ERPlora-specific |
| `DOMAIN_BASE` | `erplora.com` | Moved to `PROXY_DOMAIN_BASE` | Hotframe uses `PROXY_DOMAIN_BASE` |
| `DEPLOYMENT_MODE` | Hotframe base | Inherited | No change |
| `LANGUAGE` / `CURRENCY` | Hotframe base | Inherited | Default EUR (override) |
| `CSP_ENFORCE` | Hotframe base | Inherited | No change |
| `LOG_LEVEL` / `LOG_FORMAT` | Hotframe base | Inherited | No change |
| `AUTH_USER_MODEL` | N/A | `"apps.accounts.models.LocalUser"` | New — needed by hotframe |
| `AUTH_LOGIN_URL` | N/A | `"/login/"` | New — needed by hotframe |
| `GLOBAL_CONTEXT_HOOK` | N/A | `"hub.templating.globals.get_hub_context"` | New — points to hub layer |
| `MODULE_STATE_MODEL` | N/A | `"apps.system.models.HubModule"` | New — points to ERPlora model |
| `KERNEL_MODULE_NAMES` | Hardcoded in discovery/bootstrap.py | `["assistant"]` | Moved to settings |
| `OTEL_SERVICE_NAME` | Hardcoded in create_app | `"erplora-hub"` | New setting |

### Entry point files

**`hub-next/main.py`** — change to:
```python
from hub.bootstrap import create_app

app = create_app()
```

**`hub-next/asgi.py`** — change to:
```python
from hotframe.asgi import application  # ProxyFixMiddleware applied if PROXY_FIX_ENABLED=true
```

**`hub-next/settings.py`** — change to:
```python
from hub.settings import get_settings, Settings  # noqa: F401

settings = get_settings()
```

---

## 8. pyproject.toml Changes

### Dependencies

Add hotframe as a dependency. Until it is published to PyPI, use a path or git reference:

**Option A — Local path (development):**
```toml
[project]
dependencies = [
    # ... existing deps ...
    "hotframe @ file:///Users/joan/Desktop/code/ERPlora/hotframe",
]
```

**Option B — Git reference (CI/CD, staging):**
```toml
[project]
dependencies = [
    # ... existing deps ...
    "hotframe @ git+ssh://git@github:ERPlora/hotframe.git@main",
]
```

**Option C — PyPI (once published):**
```toml
[project]
dependencies = [
    # ... existing deps ...
    "hotframe>=0.1.0",
]
```

### Remove redundant dependencies

Hotframe already bundles these — they can be removed from hub-next's direct dependencies
(pip will pull them via hotframe's requirements):

- `fastapi>=0.115` — keep (hub-next uses it directly too)
- `sqlalchemy[asyncio]>=2.0` — keep
- `alembic>=1.13` — keep
- `jinja2>=3.1` — keep
- `pydantic-settings>=2.6` — keep
- `typer>=0.15` — keep (hub uses CLI)
- `itsdangerous>=2.2` — can be removed (hotframe dep)
- `bcrypt>=4.2` — keep (hub uses it directly in auth)
- `pyjwt>=2.9` — keep (hub uses it directly)
- `sse-starlette>=2` — can be removed (hotframe dep)
- `watchfiles>=1.0` — keep (dev hot-reload)
- `structlog>=24.4` — can be removed (hotframe dep)
- `opentelemetry-api/sdk>=1.27` — keep (hub needs specific instrumentation packages)

### Scripts and build targets

```toml
[project.scripts]
hub = "hotframe.management.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["hub", "apps"]    # runtime/ removed, hub/ added

[tool.pytest.ini_options]
testpaths = ["tests", "hub"]  # runtime/ → hub/

[tool.coverage.run]
source = ["hub", "apps"]      # runtime/ → hub/
```

---

## 9. Verification Checklist

Work through these checks after completing the migration. All must pass before deleting
`runtime/`.

### 9.1 Import verification

```bash
# No remaining runtime. imports anywhere in hub-next (except inside runtime/ itself)
grep -r "from runtime\." hub-next/ --include="*.py" \
  --exclude-dir=runtime \
  --exclude-dir=__pycache__
# Expected output: empty

grep -r "import runtime\." hub-next/ --include="*.py" \
  --exclude-dir=runtime \
  --exclude-dir=__pycache__
# Expected output: empty
```

### 9.2 New hub/ layer structure

Verify all new files exist:
```bash
ls hub-next/hub/
# Expected: __init__.py  auth/  bootstrap.py  management/  routing/  settings.py  signals/  templating/

ls hub-next/hub/auth/
# Expected: __init__.py  current_user.py

ls hub-next/hub/signals/
# Expected: __init__.py  builtins.py

ls hub-next/hub/templating/
# Expected: __init__.py  globals.py

ls hub-next/hub/routing/
# Expected: __init__.py  websocket.py
```

### 9.3 Settings verification

```bash
cd hub-next
python -c "
from hub.settings import get_settings
s = get_settings()
assert s.AUTH_USER_MODEL == 'apps.accounts.models.LocalUser'
assert s.GLOBAL_CONTEXT_HOOK == 'hub.templating.globals.get_hub_context'
assert s.KERNEL_MODULE_NAMES == ['assistant']
assert s.CURRENCY == 'EUR'
print('Settings OK')
"
```

### 9.4 Hotframe import verification

```bash
python -c "
import hotframe
from hotframe.bootstrap import create_app
from hotframe.config.settings import HotframeSettings
from hotframe.signals.builtins import MODEL_POST_SAVE
from hotframe.auth.current_user import get_current_user
from hotframe.models.base import Base
print('Hotframe imports OK')
"
```

### 9.5 Hub layer import verification

```bash
python -c "
from hub.settings import get_settings
from hub.bootstrap import create_app
from hub.auth.current_user import HubId, CurrentUser, DbSession
from hub.signals.builtins import SALES_CREATED, INVENTORY_STOCK_CHANGED
from hub.templating.globals import get_hub_context
from hub.routing.websocket import ws_handler
print('Hub layer imports OK')
"
```

### 9.6 App creation smoke test

```bash
python -c "
from hub.bootstrap import create_app
app = create_app()
print('App created OK:', app.title)
"
```

### 9.7 Full test suite

```bash
cd hub-next
pytest -v --tb=short 2>&1 | tail -20
# All tests must pass
```

### 9.8 Ruff lint

```bash
cd hub-next
ruff check hub/ apps/ modules/ --select=E,F,I
# Expected: no errors
```

### 9.9 Domain signals re-export

```bash
python -c "
from hub.signals.builtins import (
    SALES_CREATED, INVENTORY_STOCK_CHANGED, CUSTOMERS_CREATED,
    KITCHEN_ORDER_REQUIRED, LEAVE_REQUEST_CREATED, MESSAGING_INBOUND_RECEIVED,
    # Framework signals (re-exported from hotframe)
    MODEL_POST_SAVE, AUTH_LOGIN, MODULES_ACTIVATED,
)
print('All signals OK')
"
```

### 9.10 Module upgrade command

```bash
python -c "
from hub.management.commands.modules_upgrade import upgrade_module
print('Upgrade command import OK')
"
# Verify the file no longer imports from runtime.apps
grep "from runtime" hub-next/hub/management/commands/modules_upgrade.py
# Expected: empty
```

### 9.11 Delete runtime/ (final step)

Only run after all checks above pass:

```bash
cd hub-next
rm -rf runtime/
pytest -v
# Must still pass
```

---

## 10. Known Risks and Edge Cases

### `runtime.management.commands.modules_upgrade` hardcodes `from runtime.apps`

The `render_module_config_class()` function in this file generates Python source code that
contains the literal string `from runtime.apps import ModuleConfig`. After migration, this
generated code will be invalid. The function must be updated to generate
`from hotframe.apps import ModuleConfig` instead.

Locate and fix this line in `hub/management/commands/modules_upgrade.py`:
```python
# OLD (line ~159 in original):
"from runtime.apps import ModuleConfig  # noqa: E402",
# NEW:
"from hotframe.apps import ModuleConfig  # noqa: E402",
```

### Hotframe `get_settings()` vs hub `get_settings()`

Hotframe's `get_settings()` returns `HotframeSettings`. Hub-next's `get_settings()`
returns the `Settings` subclass. Code that calls `from hotframe.config.settings import
get_settings` will get the base class and miss hub-specific fields like `HUB_ID`.

The fix is in `hub/settings.py`: after creating the hub `Settings` instance, call
`hotframe.config.settings.set_settings(settings)` to register it as the singleton.
Hotframe's `get_settings()` then returns the same object. This is already included in the
`hub/settings.py` template in section 6.2.

### `runtime/discovery/bootstrap.py` KERNEL_MODULE_NAMES

The old `KERNEL_MODULES_DIR` was computed as a hardcoded path relative to the file's
location inside `runtime/`. Hotframe's equivalent computes the path from
`settings.MODULES_DIR` or a configurable base. Verify that `hotframe.discovery.bootstrap`
correctly resolves `modules/` relative to hub-next's working directory and that
`settings.KERNEL_MODULE_NAMES = ["assistant"]` is picked up.

### `apps/system/models.py` HubModule vs hotframe built-in Module

Hotframe includes its own `engine/models.py` (a built-in `Module` model). Hub-next uses
`apps.system.models.HubModule` which has additional fields (`is_system`, `error_message`,
`installed_by`, `s3_key`, `s3_etag`, etc.). The setting `MODULE_STATE_MODEL =
"apps.system.models.HubModule"` tells hotframe to use hub-next's model. Verify that
hotframe reads this setting everywhere it queries module state.

### `hub_id` in database sessions

The old `get_db()` in `runtime/auth/current_user.py` stored `session.info["hub_id"]`.
The new `hub/auth/current_user.py` does the same. Any code in `apps/` that imports
`get_db` must import it from `hub.auth.current_user`, not from `hotframe.auth.current_user`
(which does not set hub_id). This is the most likely source of broken multi-tenant
isolation bugs post-migration.

Verify with:
```bash
grep -r "from hotframe.auth.current_user import.*get_db\|DbSession" apps/ --include="*.py"
# Expected: empty — all should come from hub.auth.current_user
```
