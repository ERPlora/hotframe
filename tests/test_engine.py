"""Tests for hotframe.engine."""

from hotframe.engine.dependency import (
    DependencyManager,
    _parse_dep,
    _version_satisfies,
)
from hotframe.engine.import_manager import ImportManager
from hotframe.engine.pipeline import HotMountPipeline


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
