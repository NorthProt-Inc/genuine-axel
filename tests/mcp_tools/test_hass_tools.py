"""Tests for backend.core.mcp_tools.hass_tools.

Covers hass_control_light, hass_control_device, hass_read_sensor,
hass_get_state, hass_list_entities, and hass_execute_scene handlers.
All downstream hass_ops calls are mocked.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared stub for HASSResult (avoids importing real hass_ops which needs env)
# ---------------------------------------------------------------------------

@dataclass
class _HASSResult:
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# hass_control_light_tool
# ---------------------------------------------------------------------------


class TestHassControlLight:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_control_light_tool
        self.tool = hass_control_light_tool

    async def test_invalid_action(self):
        result = await self.tool({"entity_id": "light.desk", "action": "blink"})
        assert "action must be" in result[0].text

    async def test_invalid_brightness_negative(self):
        result = await self.tool({
            "entity_id": "light.desk", "action": "turn_on", "brightness": -5
        })
        assert "brightness must be 0-100" in result[0].text

    async def test_invalid_brightness_over_100(self):
        result = await self.tool({
            "entity_id": "light.desk", "action": "turn_on", "brightness": 200
        })
        assert "brightness must be 0-100" in result[0].text

    async def test_invalid_brightness_string(self):
        result = await self.tool({
            "entity_id": "light.desk", "action": "turn_on", "brightness": "high"
        })
        assert "brightness must be 0-100" in result[0].text

    async def test_successful_turn_on(self):
        mock_result = _HASSResult(success=True, message="light.desk turn_on complete")
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "light.desk", "action": "turn_on"})
            assert "turn_on complete" in result[0].text

    async def test_successful_turn_off(self):
        mock_result = _HASSResult(success=True, message="light.desk turn_off done")
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "light.desk", "action": "turn_off"})
            assert "turn_off done" in result[0].text

    async def test_control_failure(self):
        mock_result = _HASSResult(
            success=False, message="Failed", error="Entity not found"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "light.unknown", "action": "turn_on"})
            assert "Failed" in result[0].text

    async def test_control_with_brightness_and_color(self):
        mock_result = _HASSResult(success=True, message="OK (brightness 80%, color red)")
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            result = await self.tool({
                "entity_id": "light.desk",
                "action": "turn_on",
                "brightness": 80,
                "color": "red",
            })
            # Verify kwargs were passed correctly
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["brightness"] == 80
            assert call_kwargs["color"] == "red"
            assert "OK" in result[0].text

    async def test_exception_returns_hass_error(self):
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            side_effect=ConnectionError("unreachable"),
        ):
            result = await self.tool({"entity_id": "light.desk", "action": "turn_on"})
            assert "HASS Error" in result[0].text
            assert "unreachable" in result[0].text


# ---------------------------------------------------------------------------
# hass_control_device_tool
# ---------------------------------------------------------------------------


class TestHassControlDevice:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_control_device_tool
        self.tool = hass_control_device_tool

    async def test_missing_entity_id(self):
        result = await self.tool({"entity_id": "", "action": "turn_on"})
        assert "entity_id parameter is required" in result[0].text

    async def test_invalid_action(self):
        result = await self.tool({"entity_id": "fan.purifier", "action": "toggle"})
        assert "action must be" in result[0].text

    async def test_successful_device_control(self):
        mock_result = _HASSResult(success=True, message="fan.purifier turn_on complete")
        with patch(
            "backend.core.tools.hass_ops.hass_control_device",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "fan.purifier", "action": "turn_on"})
            assert "turn_on complete" in result[0].text

    async def test_device_failure(self):
        mock_result = _HASSResult(
            success=False, message="Failed", error="Device offline"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_control_device",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "switch.tv", "action": "turn_off"})
            assert "Failed" in result[0].text

    async def test_exception_returns_hass_error(self):
        with patch(
            "backend.core.tools.hass_ops.hass_control_device",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            result = await self.tool({"entity_id": "fan.x", "action": "turn_on"})
            assert "HASS Error" in result[0].text


# ---------------------------------------------------------------------------
# hass_read_sensor_tool
# ---------------------------------------------------------------------------


class TestHassReadSensor:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_read_sensor_tool
        self.tool = hass_read_sensor_tool

    async def test_missing_query(self):
        result = await self.tool({"query": ""})
        assert "query parameter is required" in result[0].text

    async def test_no_query_key(self):
        result = await self.tool({})
        assert "query parameter is required" in result[0].text

    async def test_successful_sensor_read(self):
        mock_result = _HASSResult(success=True, message="Temperature: 22.5C")
        with patch(
            "backend.core.tools.hass_ops.hass_read_sensor",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"query": "battery"})
            assert "22.5" in result[0].text

    async def test_sensor_read_failure(self):
        mock_result = _HASSResult(
            success=False, message="", error="Sensor not available"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_read_sensor",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"query": "nonexistent"})
            assert "Sensor not available" in result[0].text

    async def test_sensor_exception(self):
        with patch(
            "backend.core.tools.hass_ops.hass_read_sensor",
            new_callable=AsyncMock,
            side_effect=RuntimeError("connection refused"),
        ):
            result = await self.tool({"query": "battery"})
            assert "Sensor Error" in result[0].text


# ---------------------------------------------------------------------------
# hass_get_state_tool
# ---------------------------------------------------------------------------


class TestHassGetState:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_get_state_tool
        self.tool = hass_get_state_tool

    async def test_missing_entity_id(self):
        result = await self.tool({"entity_id": ""})
        assert "entity_id parameter is required" in result[0].text

    async def test_no_entity_id_key(self):
        result = await self.tool({})
        assert "entity_id parameter is required" in result[0].text

    async def test_successful_state_read(self):
        mock_result = _HASSResult(
            success=True,
            message="OK",
            data={
                "state": "on",
                "last_changed": "2024-01-01T00:00:00",
                "attributes": {
                    "brightness": 255,
                    "friendly_name": "Desk Light",
                },
            },
        )
        with patch(
            "backend.core.tools.hass_ops.hass_get_state",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "light.desk"})
            text = result[0].text
            assert "Entity: light.desk" in text
            assert "State: on" in text
            assert "brightness" in text
            assert "Desk Light" in text

    async def test_state_read_no_attributes(self):
        mock_result = _HASSResult(
            success=True,
            message="OK",
            data={
                "state": "off",
                "last_changed": "2024-01-01",
                "attributes": {},
            },
        )
        with patch(
            "backend.core.tools.hass_ops.hass_get_state",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "switch.fan"})
            text = result[0].text
            assert "State: off" in text
            # No "Attributes:" section when empty
            assert "Attributes:" not in text

    async def test_state_read_failure(self):
        mock_result = _HASSResult(
            success=False, message="", error="Entity not found"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_get_state",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"entity_id": "sensor.missing"})
            assert "Entity not found" in result[0].text

    async def test_state_exception(self):
        with patch(
            "backend.core.tools.hass_ops.hass_get_state",
            new_callable=AsyncMock,
            side_effect=ValueError("bad"),
        ):
            result = await self.tool({"entity_id": "light.x"})
            assert "State Error" in result[0].text


# ---------------------------------------------------------------------------
# hass_list_entities_tool
# ---------------------------------------------------------------------------


class TestHassListEntities:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_list_entities_tool
        self.tool = hass_list_entities_tool

    async def test_list_with_domain_filter(self):
        mock_result = _HASSResult(
            success=True,
            message="OK",
            data={
                "entities": [
                    {
                        "entity_id": "light.desk",
                        "state": "on",
                        "friendly_name": "Desk Light",
                    },
                    {
                        "entity_id": "light.ceiling",
                        "state": "off",
                        "friendly_name": "Ceiling",
                    },
                ]
            },
        )
        with patch(
            "backend.core.tools.hass_ops.hass_list_entities",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"domain": "light"})
            text = result[0].text
            assert "light entities" in text
            assert "2 found" in text
            assert "light.desk" in text
            assert "Desk Light" in text

    async def test_list_without_domain_shows_domains(self):
        mock_result = _HASSResult(
            success=True,
            message="OK",
            data={
                "domains": {"light": 5, "sensor": 20, "fan": 1},
                "total": 26,
            },
        )
        with patch(
            "backend.core.tools.hass_ops.hass_list_entities",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({})
            text = result[0].text
            assert "Home Assistant Domains" in text
            assert "26 total" in text
            assert "sensor" in text

    async def test_list_failure(self):
        mock_result = _HASSResult(
            success=False, message="", error="Connection failed"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_list_entities",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({})
            assert "Connection failed" in result[0].text

    async def test_list_exception(self):
        with patch(
            "backend.core.tools.hass_ops.hass_list_entities",
            new_callable=AsyncMock,
            side_effect=RuntimeError("network down"),
        ):
            result = await self.tool({})
            assert "List Error" in result[0].text


# ---------------------------------------------------------------------------
# hass_execute_scene_tool
# ---------------------------------------------------------------------------


class TestHassExecuteScene:

    @pytest.fixture(autouse=True)
    def _import_tool(self):
        from backend.core.mcp_tools.hass_tools import hass_execute_scene_tool
        self.tool = hass_execute_scene_tool

    async def test_no_scene_and_no_custom_lights(self):
        result = await self.tool({})
        assert "scene" in result[0].text.lower() or "custom_lights" in result[0].text.lower()

    async def test_predefined_scene_work(self):
        mock_result = _HASSResult(success=True, message="OK")
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            result = await self.tool({"scene": "work"})
            text = result[0].text
            assert "work" in text.lower()
            assert "applied" in text.lower()
            # work scene should call with brightness=100
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["brightness"] == 100

    async def test_predefined_scene_off(self):
        mock_result = _HASSResult(success=True, message="OK")
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_fn:
            result = await self.tool({"scene": "off"})
            text = result[0].text
            assert "off" in text.lower()
            call_kwargs = mock_fn.call_args.kwargs
            assert call_kwargs["action"] == "turn_off"

    async def test_predefined_scene_failure(self):
        mock_result = _HASSResult(
            success=False, message="", error="HASS unreachable"
        )
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await self.tool({"scene": "relax"})
            assert "failed" in result[0].text.lower() or "HASS unreachable" in result[0].text

    async def test_custom_lights(self):
        call_count = 0

        async def mock_control(**kwargs):
            nonlocal call_count
            call_count += 1
            return _HASSResult(success=True, message="OK")

        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            side_effect=mock_control,
        ):
            result = await self.tool({
                "custom_lights": [
                    {"entity_id": "light.desk", "brightness": 50, "color": "blue"},
                    {"entity_id": "light.ceiling", "brightness": 80},
                ]
            })
            text = result[0].text
            assert "light.desk" in text
            assert "light.ceiling" in text
            assert call_count == 2

    async def test_custom_lights_skips_missing_entity_id(self):
        call_count = 0

        async def mock_control(**kwargs):
            nonlocal call_count
            call_count += 1
            return _HASSResult(success=True, message="OK")

        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            side_effect=mock_control,
        ):
            result = await self.tool({
                "custom_lights": [
                    {"brightness": 50},  # No entity_id - should be skipped
                    {"entity_id": "light.desk"},
                ]
            })
            assert call_count == 1

    async def test_custom_lights_partial_failure(self):
        calls = []

        async def mock_control(**kwargs):
            entity_id = kwargs.get("entity_id", "")
            calls.append(entity_id)
            if entity_id == "light.broken":
                return _HASSResult(success=False, message="failed", error="timeout")
            return _HASSResult(success=True, message="OK")

        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            side_effect=mock_control,
        ):
            result = await self.tool({
                "custom_lights": [
                    {"entity_id": "light.desk"},
                    {"entity_id": "light.broken"},
                ]
            })
            text = result[0].text
            # Both should appear with their status markers
            assert "light.desk" in text
            assert "light.broken" in text

    async def test_custom_lights_max_10(self):
        call_count = 0

        async def mock_control(**kwargs):
            nonlocal call_count
            call_count += 1
            return _HASSResult(success=True, message="OK")

        lights = [{"entity_id": f"light.l{i}"} for i in range(15)]
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            side_effect=mock_control,
        ):
            await self.tool({"custom_lights": lights})
            assert call_count == 10  # Capped at 10

    async def test_scene_exception(self):
        with patch(
            "backend.core.tools.hass_ops.hass_control_light",
            new_callable=AsyncMock,
            side_effect=RuntimeError("crash"),
        ):
            result = await self.tool({"scene": "work"})
            assert "Scene Error" in result[0].text
