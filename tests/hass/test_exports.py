"""Tests for hass_ops module exports and dead code."""


class TestDeadCodeRemoved:
    """Dead functions should be removed from the module."""

    def test_list_available_devices_removed(self):
        """list_available_devices is dead code (not registered as MCP tool)."""
        from backend.core.tools import hass_ops

        assert not hasattr(hass_ops, "list_available_devices")
