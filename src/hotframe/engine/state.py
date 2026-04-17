# SPDX-License-Identifier: Apache-2.0
"""
Module state DB — CRUD operations on the module state table.

The model used is resolved from ``settings.MODULE_STATE_MODEL`` or
falls back to the built-in ``Module`` model.
"""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _get_module_model() -> type:
    """Resolve the module state model from settings."""
    from hotframe.config.settings import get_settings

    settings = get_settings()
    if settings.MODULE_STATE_MODEL:
        module_path, class_name = settings.MODULE_STATE_MODEL.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        return getattr(mod, class_name)

    # Fall back to built-in model
    from hotframe.engine.models import Module
    return Module


class ModuleAlreadyInstallingError(Exception):
    pass


class ModuleStateDB:
    """CRUD operations on the module state table."""

    def _model(self) -> type:
        return _get_module_model()

    async def get_active_modules(self, session: AsyncSession, **filters: Any) -> list:
        Model = self._model()
        stmt = select(Model).where(Model.status == "active").order_by(Model.installed_at)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_modules(self, session: AsyncSession, **filters: Any) -> list:
        Model = self._model()
        stmt = select(Model).order_by(Model.installed_at)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_module(self, session: AsyncSession, module_id: str, **filters: Any) -> Any | None:
        Model = self._model()
        stmt = select(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        module_id: str,
        version: str,
        *,
        checksum: str = "",
        status: str = "installing",
        **extra_fields: Any,
    ) -> Any:
        from sqlalchemy.exc import IntegrityError

        Model = self._model()
        module = Model(
            module_id=module_id,
            version=version,
            checksum_sha256=checksum,
            status=status,
            manifest={},
            config={},
            **extra_fields,
        )
        session.add(module)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            raise ModuleAlreadyInstallingError(
                f"Module {module_id} is already being installed by another process"
            ) from None
        logger.info("Created module %s v%s (status=%s)", module_id, version, status)
        return module

    async def activate(
        self, session: AsyncSession, module_id: str,
        manifest_dict: dict[str, Any], **filters: Any,
    ) -> None:
        Model = self._model()
        now = datetime.now(UTC)
        stmt = update(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        stmt = stmt.values(
            status="active", activated_at=now, disabled_at=None,
            manifest=manifest_dict, error_message=None,
        )
        await session.execute(stmt)
        logger.info("Activated module %s", module_id)

    async def deactivate(self, session: AsyncSession, module_id: str, **filters: Any) -> None:
        Model = self._model()
        now = datetime.now(UTC)
        stmt = update(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        stmt = stmt.values(status="disabled", disabled_at=now)
        await session.execute(stmt)
        logger.info("Deactivated module %s", module_id)

    async def set_status(
        self, session: AsyncSession, module_id: str,
        status: str, error: str | None = None, **filters: Any,
    ) -> None:
        Model = self._model()
        values: dict[str, Any] = {"status": status}
        if error is not None:
            values["error_message"] = error
        if status == "active":
            values["activated_at"] = datetime.now(UTC)
            values["disabled_at"] = None
            values["error_message"] = None
        elif status == "disabled":
            values["disabled_at"] = datetime.now(UTC)
        stmt = update(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        stmt = stmt.values(**values)
        await session.execute(stmt)

    async def set_error(
        self, session: AsyncSession, module_id: str,
        error_message: str, **filters: Any,
    ) -> None:
        await self.set_status(session, module_id, "error", error=error_message, **filters)
        logger.error("Module %s error: %s", module_id, error_message)

    async def update_manifest(
        self, session: AsyncSession, module_id: str,
        manifest_dict: dict[str, Any], **filters: Any,
    ) -> None:
        Model = self._model()
        stmt = update(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        stmt = stmt.values(manifest=manifest_dict)
        await session.execute(stmt)

    async def delete(self, session: AsyncSession, module_id: str, **filters: Any) -> None:
        Model = self._model()
        stmt = delete(Model).where(Model.module_id == module_id)
        for key, value in filters.items():
            stmt = stmt.where(getattr(Model, key) == value)
        await session.execute(stmt)
        logger.info("Deleted module %s", module_id)
