# SPDX-License-Identifier: Apache-2.0
"""
Regression tests for the module metadata lifecycle.

When a module is unloaded, the loader must remove the module's tables
from ``Base.metadata`` and dispose its mapped classes from
``Base.registry``. Otherwise, reinstall raises::

    InvalidRequestError: Table 'module_settings' is already defined for
    this MetaData instance.

These tests exercise the invariant directly via the public surface
(``_register_exported_models`` + ``_drop_module_metadata``) instead of
spinning up FastAPI + ImportManager + sys.modules — that wider scope
already has its own tests in ``test_engine.py``. The contract under
test here is purely: register classes, then drop, then re-register the
same table name without raising.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, String

from hotframe.engine.loader import ModuleLoader
from hotframe.models.base import Base


def _build_loader() -> ModuleLoader:
    """Construct a ModuleLoader with the bare minimum collaborators.

    The collaborators are mocked because the metadata lifecycle methods
    (``_register_exported_models`` and ``_drop_module_metadata``) only
    touch ``self.import_manager`` (for class registration) and
    ``self._module_metadata`` plus ``Base``. Everything else is unused
    by these unit tests.
    """
    app = MagicMock()
    app.routes = []
    return ModuleLoader(
        app=app,
        registry=MagicMock(),
        event_bus=MagicMock(),
        hooks=MagicMock(),
        slots=MagicMock(),
    )


# Monotonic counter so each call produces a unique class name. SQLAlchemy
# raises if you redeclare the same class on ``Base`` while it is still
# registered, and our ``test_no_class_name_collisions`` guard would also
# trip on a stable name reused across tests.
_FAKE_CLASS_COUNTER = 0


def _install_fake_models_module(module_id: str, table_suffix: str) -> type:
    """Build a fake ``modules/<module_id>/models.py`` containing one model.

    Returns the model class. The fake module is registered in
    ``sys.modules`` under ``f"{module_id}.models"`` so the loader's
    ``_register_exported_models`` can pick it up via ``sys.modules.get``.

    The class name is uniquified per call so the cross-module collision
    guard in ``test_no_class_name_collisions`` does not fire for our
    dynamically-built fixture models — those are deliberately throwaway.
    """
    global _FAKE_CLASS_COUNTER
    _FAKE_CLASS_COUNTER += 1
    cls_name = f"FakeModel_{table_suffix}_{_FAKE_CLASS_COUNTER}"

    # Build the model dynamically so each test gets a distinct mapper.
    fake_model = type(
        cls_name,
        (Base,),
        {
            "__tablename__": f"fake_{table_suffix}",
            "__table_args__": {"extend_existing": False},
            "id": Column(Integer, primary_key=True),
            "name": Column(String(50), default=""),
        },
    )

    fake_models_mod = types.ModuleType(f"{module_id}.models")
    fake_models_mod.__dict__[cls_name] = fake_model
    fake_models_mod.__dict__["Base"] = Base  # mimic real module layout
    sys.modules[f"{module_id}.models"] = fake_models_mod

    return fake_model


@pytest.fixture
def cleanup_modules():
    """Snapshot sys.modules so each test undoes its fake module registration."""
    snapshot = set(sys.modules.keys())
    yield
    extras = set(sys.modules.keys()) - snapshot
    for key in extras:
        sys.modules.pop(key, None)


def test_register_then_drop_removes_table_from_metadata(cleanup_modules):
    loader = _build_loader()
    loader.import_manager = MagicMock()  # avoid touching the real registrar

    fake_cls = _install_fake_models_module("metalc_a", "metalc_a")
    table_name = fake_cls.__tablename__

    # Before registration, the table is already in metadata (creating a
    # mapped class registers it eagerly). After _register_exported_models,
    # the loader knows about it.
    assert table_name in Base.metadata.tables
    loader._register_exported_models("metalc_a")
    classes, tables = loader._module_metadata["metalc_a"]
    assert fake_cls in classes
    assert any(t.name == table_name for t in tables)

    # Dropping must remove the table from MetaData AND clear the loader's
    # per-module registry so the next install is a clean slate.
    loader._drop_module_metadata("metalc_a")
    assert table_name not in Base.metadata.tables, (
        "table still in Base.metadata after _drop_module_metadata — "
        "next install will raise 'Table already defined for this MetaData'"
    )
    assert "metalc_a" not in loader._module_metadata


def test_reinstall_does_not_double_register_table(cleanup_modules):
    """Simulate install → unload (drop) → install again — must not raise."""
    loader = _build_loader()
    loader.import_manager = MagicMock()

    # First install
    fake_cls_v1 = _install_fake_models_module("metalc_b", "metalc_b")
    loader._register_exported_models("metalc_b")
    assert fake_cls_v1.__tablename__ in Base.metadata.tables

    # Unload
    loader._drop_module_metadata("metalc_b")
    # Drop sys.modules so the second install starts fresh.
    sys.modules.pop("metalc_b.models", None)
    assert fake_cls_v1.__tablename__ not in Base.metadata.tables

    # Second install — must succeed without raising
    # ``InvalidRequestError: Table 'fake_metalc_b' is already defined``.
    fake_cls_v2 = _install_fake_models_module("metalc_b", "metalc_b")
    loader._register_exported_models("metalc_b")
    assert fake_cls_v2.__tablename__ in Base.metadata.tables
    # Confirm v2 is a different class object than v1 (i.e. truly fresh).
    assert fake_cls_v2 is not fake_cls_v1


def test_drop_is_idempotent_on_unknown_module():
    loader = _build_loader()
    loader.import_manager = MagicMock()
    # Should not raise even though the module was never registered.
    loader._drop_module_metadata("never_loaded_module")
