"""Tests for Plugin System (Wave 3.2)."""

import pytest

from backend.core.plugin.types import PluginManifest, PluginPermission
from backend.core.plugin.registry import PluginRegistry


class TestPluginManifest:

    def test_create_manifest(self):
        m = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
        )
        assert m.name == "test-plugin"
        assert m.version == "1.0.0"

    def test_permissions_default_empty(self):
        m = PluginManifest(name="test", version="1.0.0", description="Test")
        assert m.permissions == []

    def test_with_permissions(self):
        m = PluginManifest(
            name="test",
            version="1.0.0",
            description="Test",
            permissions=[PluginPermission.MEMORY_READ, PluginPermission.TOOL_REGISTER],
        )
        assert len(m.permissions) == 2


class TestPluginPermission:

    def test_has_expected_values(self):
        assert PluginPermission.MEMORY_READ.value == "memory:read"
        assert PluginPermission.MEMORY_WRITE.value == "memory:write"
        assert PluginPermission.TOOL_REGISTER.value == "tool:register"
        assert PluginPermission.NETWORK.value == "network"


class TestPluginRegistry:

    def test_register_plugin(self):
        registry = PluginRegistry()
        manifest = PluginManifest(name="p1", version="1.0.0", description="Plugin 1")
        registry.register(manifest)
        assert registry.get("p1") == manifest

    def test_unregister_plugin(self):
        registry = PluginRegistry()
        manifest = PluginManifest(name="p1", version="1.0.0", description="Plugin 1")
        registry.register(manifest)
        registry.unregister("p1")
        assert registry.get("p1") is None

    def test_list_plugins(self):
        registry = PluginRegistry()
        registry.register(PluginManifest(name="a", version="1.0", description="A"))
        registry.register(PluginManifest(name="b", version="2.0", description="B"))
        names = [m.name for m in registry.list_all()]
        assert set(names) == {"a", "b"}

    def test_duplicate_register_replaces(self):
        registry = PluginRegistry()
        registry.register(PluginManifest(name="p1", version="1.0", description="Old"))
        registry.register(PluginManifest(name="p1", version="2.0", description="New"))
        assert registry.get("p1").version == "2.0"

    def test_unregister_nonexistent_no_error(self):
        registry = PluginRegistry()
        registry.unregister("does_not_exist")

    def test_has_plugin(self):
        registry = PluginRegistry()
        registry.register(PluginManifest(name="p1", version="1.0", description="P"))
        assert registry.has("p1") is True
        assert registry.has("p2") is False
