"""Pytest fixtures for Home Assistant module tests."""

import pytest
from unittest.mock import AsyncMock, patch
from backend.core.tools.hass_ops import HASSResult


@pytest.fixture
def mock_hass_api():
    """Patch _hass_api_call to avoid real HTTP calls."""
    with patch(
        "backend.core.tools.hass_ops.api._hass_api_call",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = HASSResult(success=True, message="OK", data={})
        yield mock


@pytest.fixture
def sample_entity_states() -> list[dict]:
    """Sample HA entity state objects for testing."""
    return [
        {
            "entity_id": "light.wiz_rgbw_tunable_77d6a0",
            "state": "on",
            "attributes": {"friendly_name": "Desk Light 1", "brightness": 255},
        },
        {
            "entity_id": "sensor.iphone_battery_level",
            "state": "85",
            "attributes": {
                "friendly_name": "iPhone Battery",
                "unit_of_measurement": "%",
            },
        },
        {
            "entity_id": "sensor.new_unknown_device",
            "state": "42",
            "attributes": {"friendly_name": "New Device"},
        },
    ]
