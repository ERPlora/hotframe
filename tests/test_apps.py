"""Tests for hotframe.apps."""
from hotframe.apps.config import AppConfig, ModuleConfig, ModuleManifest
from hotframe.apps.registry import ModuleRegistry
from hotframe.apps.service_facade import ModuleService, action


class TestAppConfig:
    def test_app_config_exists(self):
        assert AppConfig is not None

    def test_module_config_exists(self):
        assert ModuleConfig is not None


class TestModuleManifest:
    def test_manifest_has_fields(self):
        assert "MODULE_ID" in ModuleManifest.model_fields
        assert "MODULE_VERSION" in ModuleManifest.model_fields
        assert "DEPENDENCIES" in ModuleManifest.model_fields


class TestModuleRegistry:
    def test_create_registry(self):
        registry = ModuleRegistry()
        assert registry is not None


class TestServiceFacade:
    def test_action_decorator(self):
        class TestService(ModuleService):
            @action(permission="view_test")
            async def list_items(self):
                return []

        assert hasattr(TestService.list_items, "_action_meta")
        assert TestService.list_items._action_meta.permission == "view_test"
        assert TestService.list_items._action_meta.mutates is False

    def test_action_mutates(self):
        class TestService(ModuleService):
            @action(permission="add_test", mutates=True, description="Create item")
            async def create_item(self, name: str):
                pass

        meta = TestService.create_item._action_meta
        assert meta.mutates is True
        assert meta.description == "Create item"
