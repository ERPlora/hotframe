# SPDX-License-Identifier: Apache-2.0
"""
Kernel module bootstrap.

Discovers and loads kernel modules (those listed in
``settings.KERNEL_MODULE_NAMES``). Kernel modules ship with the
application image and are always active.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def boot_kernel_modules(
    session: AsyncSession,
    loader: Any,
    registry: Any,
    *,
    modules_dir: Path | None = None,
    **extra_fields: Any,
) -> int:
    """Discover and load kernel modules.

    Kernel module names come from ``settings.KERNEL_MODULE_NAMES``.

    Args:
        session: Active DB session.
        loader: ModuleLoader instance.
        registry: ModuleRegistry instance.
        modules_dir: Override for the modules directory.
        **extra_fields: Extra fields to pass to the module state DB
                        (e.g. hub_id for multi-tenant setups).

    Returns:
        Number of kernel modules loaded.
    """
    from hotframe.config.settings import get_settings

    settings = get_settings()
    kernel_names = settings.KERNEL_MODULE_NAMES

    if not kernel_names:
        logger.debug("No kernel modules configured")
        return 0

    base_dir = modules_dir or settings.MODULES_DIR
    loaded = 0

    for name in kernel_names:
        module_dir = base_dir / name
        if not module_dir.exists():
            logger.warning("Kernel module directory not found: %s", module_dir)
            continue

        try:
            await _boot_single_kernel_module(
                session,
                name,
                module_dir,
                loader,
                registry,
                **extra_fields,
            )
            loaded += 1
        except Exception:
            logger.exception("Failed to boot kernel module: %s", name)

    if loaded:
        logger.info("Booted %d kernel module(s): %s", loaded, ", ".join(kernel_names[:loaded]))

    return loaded


async def _boot_single_kernel_module(
    session: AsyncSession,
    name: str,
    module_dir: Path,
    loader: Any,
    registry: Any,
    **extra_fields: Any,
) -> None:
    """Boot a single kernel module."""
    from hotframe.apps.config import load_manifest
    from hotframe.engine.state import ModuleStateDB

    manifest = load_manifest(module_dir / "module.py")
    if manifest is None:
        logger.warning("No valid manifest in kernel module: %s", name)
        return

    state_db = ModuleStateDB()

    existing = await state_db.get_module(session, name, **extra_fields)
    if existing is None:
        await state_db.create(
            session,
            name,
            manifest.MODULE_VERSION,
            status="active",
            is_system=True,
            **extra_fields,
        )
    else:
        if existing.version != manifest.MODULE_VERSION:
            await state_db.set_status(session, name, "active", **extra_fields)
            await state_db.update_manifest(
                session,
                name,
                manifest._asdict() if hasattr(manifest, "_asdict") else {},
                **extra_fields,
            )

    await loader.load_module(name, module_dir, registry)
    logger.info("Kernel module loaded: %s v%s", name, manifest.MODULE_VERSION)
