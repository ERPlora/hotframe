"""Tests for hotframe.engine."""

import inspect

from hotframe.engine.dependency import (
    DependencyManager,
    _parse_dep,
    _version_satisfies,
)
from hotframe.engine.import_manager import ImportManager
from hotframe.engine.pipeline import HotMountPipeline
from hotframe.engine.state import ModuleStateDB


class TestDependencyParsing:
    def test_simple_module(self):
        mid, op, ver = _parse_dep("sales")
        assert mid == "sales"
        assert op is None
        assert ver is None

    def test_with_version(self):
        mid, op, ver = _parse_dep("sales>=1.0.0")
        assert mid == "sales"
        assert op == ">="
        assert ver == "1.0.0"

    def test_exact_version(self):
        mid, op, ver = _parse_dep("inventory==2.1.0")
        assert mid == "inventory"
        assert op == "=="
        assert ver == "2.1.0"


class TestVersionSatisfies:
    def test_gte(self):
        assert _version_satisfies("1.2.0", ">=", "1.0.0") is True
        assert _version_satisfies("1.0.0", ">=", "1.0.0") is True
        assert _version_satisfies("0.9.0", ">=", "1.0.0") is False

    def test_eq(self):
        assert _version_satisfies("1.0.0", "==", "1.0.0") is True
        assert _version_satisfies("1.0.1", "==", "1.0.0") is False

    def test_lt(self):
        assert _version_satisfies("0.9.0", "<", "1.0.0") is True
        assert _version_satisfies("1.0.0", "<", "1.0.0") is False


class TestDependencyManager:
    def test_resolve_load_order_no_deps(self):
        dm = DependencyManager()
        modules = [
            {"module_id": "a", "manifest": {"dependencies": []}},
            {"module_id": "b", "manifest": {"dependencies": []}},
        ]
        ordered = dm.resolve_load_order(modules)
        assert len(ordered) == 2

    def test_resolve_load_order_with_deps(self):
        dm = DependencyManager()
        modules = [
            {"module_id": "b", "manifest": {"dependencies": ["a"]}},
            {"module_id": "a", "manifest": {"dependencies": []}},
        ]
        ordered = dm.resolve_load_order(modules)
        ids = [m["module_id"] for m in ordered]
        assert ids.index("a") < ids.index("b")

    def test_resolve_load_order_missing_dep(self):
        dm = DependencyManager()
        modules = [
            {"module_id": "a", "manifest": {"dependencies": ["missing"]}},
        ]
        ordered = dm.resolve_load_order(modules)
        assert len(ordered) == 0  # excluded because dep is missing

    def test_cycle_detection(self):
        dm = DependencyManager()
        modules = [
            {"module_id": "a", "manifest": {"dependencies": ["b"]}},
            {"module_id": "b", "manifest": {"dependencies": ["a"]}},
        ]
        ordered = dm.resolve_load_order(modules)
        assert len(ordered) == 0  # both excluded due to cycle


class TestEngineImports:
    def test_pipeline(self):
        assert HotMountPipeline is not None

    def test_import_manager(self):
        assert ImportManager is not None


class TestModuleStateDBSignature:
    """
    Regression: ``ModuleRuntime`` callers used to invoke
    ``state.get_module(session, hub_id, module_id)`` — ModuleStateDB.get_module
    only accepts ``(session, module_id, **filters)`` so that pattern raised
    ``TypeError: get_module() takes 3 positional arguments but 4 were given``
    and broke marketplace install. Lock the contract.
    """

    def test_get_module_takes_two_required_positionals(self):
        sig = inspect.signature(ModuleStateDB.get_module)
        params = list(sig.parameters.values())[1:]  # drop ``self``
        # session + module_id are required positional params; everything
        # else (e.g. hub_id) must be passed as a keyword argument.
        assert params[0].name == "session"
        assert params[1].name == "module_id"
        # The trailing **filters slot is what receives ``hub_id``.
        assert any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)

    def test_runtime_callers_use_keyword_for_hub_id(self):
        """``module_runtime.py`` must never pass ``hub_id`` positionally."""
        from pathlib import Path

        runtime_src = (
            Path(__file__).resolve().parent.parent
            / "src" / "hotframe" / "engine" / "module_runtime.py"
        ).read_text(encoding="utf-8")
        # The exact pattern that previously triggered the TypeError.
        assert (
            "self.state.get_module(session, hub_id, module_id)" not in runtime_src
        ), "module_runtime.py reverted to the broken positional get_module() call"
