"""Tests for MCP schema descriptions - no hardcoded entity IDs."""


class TestSchemaNoHardcodedIds:
    """Schema descriptions should use generic examples, not specific device IDs."""

    def test_light_tool_schema_no_mac_id(self):
        """hass_control_light schema should not contain MAC-based IDs."""
        from backend.core.mcp_tools import hass_tools

        # Access the registered tool's input_schema
        schema_str = str(
            hass_tools.hass_control_light_tool.__wrapped__.__qualname__
            if hasattr(hass_tools.hass_control_light_tool, "__wrapped__")
            else ""
        )
        # Check the actual schema dict passed to @register_tool
        import inspect

        source = inspect.getsource(hass_tools)
        assert "77d6a0" not in source

    def test_device_tool_schema_no_specific_id(self):
        """hass_control_device schema should not contain specific entity IDs."""
        import inspect
        from backend.core.mcp_tools import hass_tools

        source = inspect.getsource(hass_tools)
        assert "vital_100s_series" not in source

    def test_pydantic_schema_no_specific_id(self):
        """Pydantic schema descriptions should use generic examples."""
        from backend.core.mcp_tools.schemas import HassControlDeviceInput

        schema = HassControlDeviceInput.model_json_schema()
        schema_str = str(schema)
        assert "vital_100s_series" not in schema_str
