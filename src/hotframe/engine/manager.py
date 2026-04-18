# SPDX-License-Identifier: Apache-2.0
"""
Module Manager — unified service for module lifecycle operations.

Single entry point for both CLI and web UI. Handles:
install, activate, deactivate, uninstall, update, list.

Usage::

    from hotframe.engine.manager import ModuleManager

    manager = ModuleManager(app)
    result = await manager.install("demo")
    result = await manager.deactivate("demo")
    modules = await manager.list()
"""

from __future__ import annotations

import importlib
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _is_zip_path(source: str) -> bool:
    return source.endswith(".zip") and not _is_url(source)


@dataclass
class ModuleInfo:
    """Module state information."""

    name: str
    status: str  # available, installed, active, disabled, error
    version: str = ""
    has_views: bool = True
    has_api: bool = True
    is_system: bool = False
    error: str = ""


@dataclass
class Result:
    """Result of a module operation."""

    ok: bool
    message: str
    module: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class ModuleManager:
    """Unified module lifecycle manager.

    Provides install/activate/deactivate/uninstall operations
    that work identically from CLI and web UI.

    Args:
        app: The FastAPI application instance (needed for route mounting).
             Can be None for CLI-only operations (list, install without mount).
    """

    def __init__(self, app: Any = None) -> None:
        self.app = app
        self._modules_dir = Path("modules")
        # In-memory state (production uses DB via ModuleStateDB)
        self._state: dict[str, ModuleInfo] = {}

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    async def list(self) -> list[ModuleInfo]:
        """List all modules with their current status.

        Scans the modules/ directory and merges with in-memory state.
        """
        result: list[ModuleInfo] = []

        if not self._modules_dir.exists():
            return result

        for mod_dir in sorted(self._modules_dir.iterdir()):
            if not mod_dir.is_dir() or mod_dir.name.startswith((".", "_")):
                continue
            if not (mod_dir / "module.py").exists():
                continue

            name = mod_dir.name

            if name in self._state:
                result.append(self._state[name])
            else:
                # Read module config
                info = self._read_module_info(name, mod_dir)
                result.append(info)

        return result

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    async def install(self, source: str) -> Result:
        """Install a module from a name, local path/zip, or URL.

        Source resolution:
        1. URL (https://...) → download zip → extract to modules/ → install
        2. Local .zip path → extract to modules/ → install
        3. Name only → check settings.MODULE_MARKETPLACE_URL → download
        4. Name only, no marketplace → look in modules/ directory

        Transitions: available → active
        """
        # Resolve source to a module directory
        resolve_result = await self._resolve_source(source)
        if not resolve_result.ok:
            return resolve_result

        name = resolve_result.module
        mod_dir = self._modules_dir / name

        if name in self._state and self._state[name].status == "active":
            return Result(ok=False, message=f"Module '{name}' is already active", module=name)

        # Step 1: Import models
        try:
            importlib.import_module(f"modules.{name}.models")
        except ImportError:
            pass  # No models is fine
        except Exception as exc:
            return Result(ok=False, message=f"Failed to import models: {exc}", module=name)

        # Step 2: Run migration (create tables)
        try:
            from hotframe.config.database import get_engine
            from hotframe.models.base import Base

            engine = get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:
            return Result(ok=False, message=f"Migration failed: {exc}", module=name)

        # Step 3: Mount routes
        mounted = await self._mount_routes(name)

        # Step 4: Update state
        info = self._read_module_info(name, mod_dir)
        info.status = "active"
        self._state[name] = info

        logger.info("Installed module %s (source=%s)", name, source)
        return Result(
            ok=True,
            message=f"Module '{name}' installed and active",
            module=name,
            details={"mounted_routes": mounted, "source": source},
        )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(self, source: str) -> Result:
        """Update a module to a new version.

        Downloads/extracts the new version, backs up the old one,
        replaces files, runs migrations, reloads code.
        Media/data files are NOT affected.

        The module must already be installed (any status).
        """
        # Step 1: Resolve source to get new files
        resolve_result = await self._resolve_source(source)
        if not resolve_result.ok:
            return resolve_result

        name = resolve_result.module
        mod_dir = self._modules_dir / name

        if name not in self._state:
            # Not tracked — maybe it's a fresh install instead
            return await self.install(source)

        old_state = self._state[name]
        old_version = old_state.version
        was_active = old_state.status == "active"

        # Step 2: Backup current module
        backup_dir = self._modules_dir / f".{name}_backup"
        try:
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            shutil.copytree(mod_dir, backup_dir)
        except Exception as exc:
            return Result(ok=False, message=f"Backup failed: {exc}", module=name)

        # Step 3: If source was zip/URL, files are already extracted to mod_dir
        # by _resolve_source. If source was just a name, mod_dir already has
        # the new files (e.g. updated via git pull). Either way, mod_dir is current.

        # Step 4: Reimport models (may have new columns/tables)
        try:
            # Remove old table registrations from SQLAlchemy metadata
            # so the reimport doesn't clash with "already defined" errors
            from hotframe.models.base import Base

            tables_to_remove = [
                t_name for t_name in Base.metadata.tables
                if t_name.startswith(f"{name}_") or t_name == name
            ]
            for t_name in tables_to_remove:
                Base.metadata.remove(Base.metadata.tables[t_name])

            # Force reimport by removing from sys.modules
            import sys

            to_remove = [k for k in sys.modules if k.startswith(f"modules.{name}")]
            for k in to_remove:
                del sys.modules[k]

            importlib.import_module(f"modules.{name}.models")
        except ImportError:
            pass  # No models is fine
        except Exception as exc:
            # Rollback
            shutil.rmtree(mod_dir)
            shutil.copytree(backup_dir, mod_dir)
            shutil.rmtree(backup_dir)
            return Result(ok=False, message=f"Model import failed: {exc}", module=name)

        # Step 5: Run migrations
        try:
            from hotframe.config.database import get_engine
            from hotframe.models.base import Base

            engine = get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception as exc:
            # Rollback
            shutil.rmtree(mod_dir)
            shutil.copytree(backup_dir, mod_dir)
            shutil.rmtree(backup_dir)
            return Result(ok=False, message=f"Migration failed: {exc}", module=name)

        # Step 6: Remount routes if was active
        mounted = []
        if was_active and self.app is not None:
            mounted = await self._mount_routes(name)

        # Step 7: Update state
        info = self._read_module_info(name, mod_dir)
        info.status = old_state.status  # preserve active/disabled status
        self._state[name] = info
        new_version = info.version

        # Step 8: Clean up backup
        shutil.rmtree(backup_dir, ignore_errors=True)

        logger.info("Updated module %s: %s → %s", name, old_version, new_version)
        return Result(
            ok=True,
            message=f"Module '{name}' updated: {old_version} → {new_version}",
            module=name,
            details={
                "old_version": old_version,
                "new_version": new_version,
                "mounted_routes": mounted,
            },
        )

    # ------------------------------------------------------------------
    # Activate
    # ------------------------------------------------------------------

    async def activate(self, name: str) -> Result:
        """Activate a disabled module: remount routes.

        Transitions: disabled → active
        """
        if name not in self._state:
            return Result(ok=False, message=f"Module '{name}' is not installed", module=name)

        state = self._state[name]
        if state.status == "active":
            return Result(ok=False, message=f"Module '{name}' is already active", module=name)

        # Remount routes
        mounted = await self._mount_routes(name)

        state.status = "active"
        logger.info("Activated module %s", name)
        return Result(ok=True, message=f"Module '{name}' activated", module=name,
                      details={"mounted_routes": mounted})

    # ------------------------------------------------------------------
    # Deactivate
    # ------------------------------------------------------------------

    async def deactivate(self, name: str) -> Result:
        """Deactivate a module: unmount routes but keep data and files.

        Transitions: active → disabled
        """
        if name not in self._state:
            return Result(ok=False, message=f"Module '{name}' is not installed", module=name)

        state = self._state[name]
        if state.status != "active":
            return Result(ok=False, message=f"Module '{name}' is not active (status: {state.status})", module=name)

        if state.is_system:
            return Result(ok=False, message=f"Module '{name}' is a system module and cannot be deactivated", module=name)

        # Unmount routes
        await self._unmount_routes(name)

        state.status = "disabled"
        logger.info("Deactivated module %s", name)
        return Result(ok=True, message=f"Module '{name}' deactivated (data preserved)", module=name)

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    async def uninstall(self, name: str, keep_data: bool = False) -> Result:
        """Uninstall a module: unmount routes, optionally drop tables, delete files.

        Transitions: any → removed
        """
        mod_dir = self._modules_dir / name

        if name in self._state and self._state[name].is_system:
            return Result(ok=False, message=f"Module '{name}' is a system module and cannot be uninstalled", module=name)

        # Step 1: Unmount routes (if active)
        if name in self._state and self._state[name].status == "active":
            await self._unmount_routes(name)

        # Step 2: Drop tables (if not keep_data)
        tables_dropped = 0
        if not keep_data:
            try:
                tables_dropped = await self._drop_module_tables(name)
            except Exception as exc:
                logger.warning("Failed to drop tables for %s: %s", name, exc)

        # Step 3: Delete files
        if mod_dir.exists():
            shutil.rmtree(mod_dir)

        # Step 4: Remove from state
        self._state.pop(name, None)

        logger.info("Uninstalled module %s (tables_dropped=%d, keep_data=%s)", name, tables_dropped, keep_data)
        return Result(
            ok=True,
            message=f"Module '{name}' uninstalled",
            module=name,
            details={"tables_dropped": tables_dropped, "data_kept": keep_data},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_module_info(self, name: str, mod_dir: Path) -> ModuleInfo:
        """Read module metadata from module.py."""
        info = ModuleInfo(name=name, status="available")

        try:
            mod = importlib.import_module(f"modules.{name}.module")

            # Find the ModuleConfig subclass
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and hasattr(attr, "name")
                    and getattr(attr, "name", None) == name
                ):
                    info.version = getattr(attr, "version", "")
                    info.has_views = getattr(attr, "has_views", True)
                    info.has_api = getattr(attr, "has_api", True)
                    info.is_system = getattr(attr, "is_system", False)
                    break
        except Exception as exc:
            info.error = str(exc)
            logger.debug("Could not read module info for %s: %s", name, exc)

        return info

    async def _mount_routes(self, name: str) -> list[str]:
        """Mount a module's routers on the app."""
        mounted = []

        if self.app is None:
            return mounted

        # Mount views router
        try:
            mod = importlib.import_module(f"modules.{name}.routes")
            router = getattr(mod, "router", None)
            if router:
                self.app.include_router(router)
                mounted.append("views")
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("Failed to mount views for %s: %s", name, exc)

        # Mount API router
        try:
            mod = importlib.import_module(f"modules.{name}.api")
            api_router = getattr(mod, "api_router", None)
            if api_router:
                self.app.include_router(api_router)
                mounted.append("api")
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("Failed to mount API for %s: %s", name, exc)

        return mounted

    async def _unmount_routes(self, name: str) -> None:
        """Unmount a module's routes from the app.

        Note: FastAPI doesn't support true route removal. We mark the
        module as disabled and the routes will 404 on next request via
        a middleware check. Full unmount requires app restart.
        """
        # For now, log the intent. True hot-unmount is in ModuleRuntime.
        logger.info("Routes for %s marked for unmount (full effect on restart)", name)

    async def _drop_module_tables(self, name: str) -> int:
        """Drop database tables belonging to a module."""
        try:
            importlib.import_module(f"modules.{name}.models")
        except ImportError:
            return 0

        from hotframe.config.database import get_engine
        from hotframe.models.base import Base

        engine = get_engine()
        module_tables = [
            table for table_name, table in Base.metadata.tables.items()
            if table_name.startswith(f"{name}_") or table_name == name
        ]

        if not module_tables:
            return 0

        async with engine.begin() as conn:
            for table in reversed(module_tables):
                await conn.run_sync(
                    lambda sync_conn, t=table: t.drop(sync_conn, checkfirst=True)
                )

        return len(module_tables)

    # ------------------------------------------------------------------
    # Source resolution (URL, zip, marketplace, local)
    # ------------------------------------------------------------------

    async def _resolve_source(self, source: str) -> Result:
        """Resolve a source string to a module name in modules/.

        Resolution order:
        1. URL → download zip → extract
        2. Local .zip → extract
        3. Name → check MODULE_MARKETPLACE_URL in settings → download
        4. Name → check modules/ directory
        """
        # 1. URL
        if _is_url(source):
            return await self._install_from_url(source)

        # 2. Local zip
        if _is_zip_path(source):
            return self._install_from_zip(Path(source))

        # 3. Name — check marketplace URL in settings
        name = source
        try:
            from hotframe.config.settings import get_settings

            settings = get_settings()
            marketplace_url = getattr(settings, "MODULE_MARKETPLACE_URL", "")
            if marketplace_url:
                url = f"{marketplace_url.rstrip('/')}/{name}.zip"
                result = await self._install_from_url(url)
                if result.ok:
                    return result
                logger.debug("Marketplace download failed for %s, trying local", name)
        except Exception:
            pass

        # 4. Local modules/ directory
        mod_dir = self._modules_dir / name
        if mod_dir.exists() and (mod_dir / "module.py").exists():
            return Result(ok=True, message="Found locally", module=name)

        return Result(
            ok=False,
            message=f"Module '{name}' not found — not in modules/, no marketplace URL, not a path or URL",
            module=name,
        )

    async def _install_from_url(self, url: str) -> Result:
        """Download a zip from URL and extract to modules/."""
        import httpx

        logger.info("Downloading module from %s", url)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return Result(
                        ok=False,
                        message=f"Download failed: HTTP {response.status_code} from {url}",
                    )
                content = response.content
        except Exception as exc:
            return Result(ok=False, message=f"Download failed: {exc}")

        # Save to temp file and extract
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            return self._install_from_zip(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _install_from_zip(self, zip_path: Path) -> Result:
        """Extract a zip file into modules/ directory."""
        if not zip_path.exists():
            return Result(ok=False, message=f"Zip file not found: {zip_path}")

        if not zipfile.is_zipfile(zip_path):
            return Result(ok=False, message=f"Not a valid zip file: {zip_path}")

        # Extract to temp dir first to find the module name
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            with zipfile.ZipFile(zip_path, "r") as zf:
                # Security: check for path traversal
                for member in zf.namelist():
                    member_path = Path(member)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        return Result(
                            ok=False,
                            message=f"Zip contains unsafe path: {member}",
                        )
                zf.extractall(tmp_path)

            # Find the module — look for module.py
            # Could be at root of zip or in a subdirectory
            module_py = None
            module_root = None

            # Check root level
            if (tmp_path / "module.py").exists():
                module_root = tmp_path
                module_py = tmp_path / "module.py"
            else:
                # Check one level deep (zip contains a folder)
                for child in tmp_path.iterdir():
                    if child.is_dir() and (child / "module.py").exists():
                        module_root = child
                        module_py = child / "module.py"
                        break

            if module_py is None:
                return Result(
                    ok=False,
                    message="Zip does not contain a module.py — not a valid hotframe module",
                )

            # Derive module name from directory or module.py content
            name = module_root.name

            # If name looks like "demo-1.0.0", strip version
            if "-" in name:
                name = name.rsplit("-", 1)[0]

            # Copy to modules/
            target = self._modules_dir / name
            if target.exists():
                shutil.rmtree(target)

            shutil.copytree(module_root, target)
            logger.info("Extracted module %s from %s", name, zip_path.name)

            return Result(ok=True, message=f"Extracted from {zip_path.name}", module=name)
