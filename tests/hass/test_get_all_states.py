"""Tests for get_all_states function."""

import pytest
from unittest.mock import AsyncMock, patch
from backend.core.tools.hass_ops import HASSResult


@pytest.fixture
def mock_api_all_states():
    """Mock _hass_api_call returning mixed known/unknown entities."""
    with patch(
        "backend.core.tools.hass_ops.api._hass_api_call",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = HASSResult(
            success=True,
            message="OK",
            data=[
                {"entity_id": "light.wiz_rgbw_tunable_77d6a0", "state": "on"},
                {"entity_id": "sensor.iphone_battery_level", "state": "85"},
                {"entity_id": "sensor.new_unknown_device", "state": "42"},
                {"entity_id": "switch.something_new", "state": "off"},
            ],
        )
        yield mock


class TestGetAllStates:
    """get_all_states should support filtered and unfiltered modes."""

    @pytest.mark.asyncio
    async def test_default_returns_all_entities(self, mock_api_all_states):
        """Default: return ALL entities, not just known ones."""
        from backend.core.tools.hass_ops import get_all_states

        result = await get_all_states()
        entity_ids = [s["entity_id"] for s in result.data]
        assert "sensor.new_unknown_device" in entity_ids
        assert "switch.something_new" in entity_ids
        assert len(result.data) == 4

    @pytest.mark.asyncio
    async def test_known_only_filters_to_registered(self, mock_api_all_states):
        """known_only=True: return only registered entities."""
        from backend.core.tools.hass_ops import get_all_states

        result = await get_all_states(known_only=True)
        entity_ids = [s["entity_id"] for s in result.data]
        assert "sensor.new_unknown_device" not in entity_ids
        assert "switch.something_new" not in entity_ids
        assert "light.wiz_rgbw_tunable_77d6a0" in entity_ids

    @pytest.mark.asyncio
    async def test_api_failure_propagated(self):
        """API failures should be returned as-is."""
        with patch(
            "backend.core.tools.hass_ops.api._hass_api_call",
            new_callable=AsyncMock,
            return_value=HASSResult(success=False, message="", error="timeout"),
        ):
            from backend.core.tools.hass_ops import get_all_states

            result = await get_all_states()
            assert not result.success
