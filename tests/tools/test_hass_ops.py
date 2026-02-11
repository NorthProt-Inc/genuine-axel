"""Tests for backend.core.tools.hass_ops - Home Assistant operations.

Covers:
- parse_color: named colors, hex, HSL, RGB, Korean names
- HASSResult / DeviceAction dataclasses
- hass_control_device: action dispatch, brightness, color, entity validation
- hass_control_light: delegation to hass_control_device
- hass_control_all_lights: multi-light orchestration
- hass_get_state: entity state retrieval
- hass_read_sensor: alias/group lookup + single sensor read
- _read_sensor_group: group sensor aggregation
- get_all_states: entity state listing with known_only filter
- hass_list_entities: domain filtering
- _hass_api_call: retry logic, circuit breaker, auth headers
- _process_response_httpx: status code handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.core.tools.hass_ops import (
    COLOR_MAP,
    DeviceAction,
    HASSResult,
    _hass_api_call,
    _process_response_httpx,
    get_all_states,
    hass_control_all_lights,
    hass_control_device,
    hass_control_light,
    hass_get_state,
    hass_list_entities,
    hass_read_sensor,
    parse_color,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """Reset HASS circuit breaker before each test."""
    from backend.core.utils.circuit_breaker import HASS_CIRCUIT
    HASS_CIRCUIT.reset()
    yield
    HASS_CIRCUIT.reset()


@pytest.fixture
def mock_hass_api():
    """Patch _hass_api_call to avoid real HTTP calls."""
    mock = AsyncMock(return_value=HASSResult(success=True, message="OK", data={}))
    # Patch in both api and devices modules (they both import _hass_api_call)
    with (
        patch("backend.core.tools.hass_ops.api._hass_api_call", mock),
        patch("backend.core.tools.hass_ops.devices._hass_api_call", mock),
    ):
        yield mock


@pytest.fixture
def mock_device_config():
    """Patch _get_device_config with test devices."""
    config = MagicMock()
    config.lights = ["light.desk_1", "light.desk_2"]
    config.other_devices = {"fan": "fan.bedroom"}
    config.sensor_aliases = {
        "temperature": "sensor.room_temp",
        "humidity": "sensor.room_humidity",
    }
    config.sensor_groups = {
        "environment": ["sensor.room_temp", "sensor.room_humidity"],
    }
    config.known_entities = {"light.desk_1", "light.desk_2", "sensor.room_temp"}

    with patch("backend.core.tools.hass_ops.config._get_device_config", return_value=config):
        yield config


# ---------------------------------------------------------------------------
# parse_color
# ---------------------------------------------------------------------------


class TestParseColor:

    def test_named_color_english(self) -> None:
        assert parse_color("red") == [255, 0, 0]
        assert parse_color("blue") == [0, 0, 255]
        assert parse_color("green") == [0, 255, 0]

    def test_named_color_korean(self) -> None:
        assert parse_color("빨강") == [255, 0, 0]
        assert parse_color("파랑") == [0, 0, 255]
        assert parse_color("노랑") == [255, 255, 0]

    def test_named_color_case_insensitive(self) -> None:
        assert parse_color("RED") == [255, 0, 0]
        assert parse_color("Blue") == [0, 0, 255]

    def test_named_color_whitespace(self) -> None:
        assert parse_color("  red  ") == [255, 0, 0]
        assert parse_color("warm white") == [255, 200, 150]

    def test_hex_with_hash(self) -> None:
        assert parse_color("#ff0000") == [255, 0, 0]
        assert parse_color("#00ff00") == [0, 255, 0]

    def test_hex_without_hash(self) -> None:
        assert parse_color("ff0000") == [255, 0, 0]
        assert parse_color("0000ff") == [0, 0, 255]

    def test_hex_mixed_case(self) -> None:
        assert parse_color("#FF8800") == [255, 136, 0]
        assert parse_color("#aaBBcc") == [170, 187, 204]

    def test_hsl_format(self) -> None:
        result = parse_color("hsl(0, 100, 50)")
        assert result is not None
        assert len(result) == 3
        # Pure red in HSL(0, 100%, 50%)
        assert result[0] == 255  # R should be max

    def test_hsl_without_prefix(self) -> None:
        result = parse_color("120, 100, 50")
        assert result is not None
        # HSL(120, 100%, 50%) = pure green
        assert result[1] > result[0]  # G > R

    def test_rgb_format(self) -> None:
        assert parse_color("rgb(128, 64, 32)") == [128, 64, 32]

    def test_rgb_clamped(self) -> None:
        # Negative values don't match the \d+ regex, so no match
        assert parse_color("rgb(300, -10, 128)") is None
        # Positive out-of-range values are clamped
        result = parse_color("rgb(300, 10, 128)")
        assert result == [255, 10, 128]

    def test_empty_string(self) -> None:
        assert parse_color("") is None

    def test_none_input(self) -> None:
        assert parse_color(None) is None

    def test_unknown_color_name(self) -> None:
        assert parse_color("ultraviolet") is None

    def test_invalid_hex(self) -> None:
        assert parse_color("#gggggg") is None
        assert parse_color("#fff") is None  # too short

    def test_returns_copy_not_reference(self) -> None:
        """Named colors should return a copy so mutations don't affect COLOR_MAP."""
        result = parse_color("red")
        result[0] = 0
        assert COLOR_MAP["red"] == [255, 0, 0]


# ---------------------------------------------------------------------------
# HASSResult / DeviceAction
# ---------------------------------------------------------------------------


class TestDataStructures:

    def test_hass_result_defaults(self) -> None:
        r = HASSResult(success=True, message="OK")
        assert r.data is None
        assert r.error is None

    def test_device_action_values(self) -> None:
        assert DeviceAction.TURN_ON.value == "turn_on"
        assert DeviceAction.TURN_OFF.value == "turn_off"
        assert DeviceAction.TOGGLE.value == "toggle"


# ---------------------------------------------------------------------------
# _process_response_httpx
# ---------------------------------------------------------------------------


class TestProcessResponse:

    def test_200_with_json(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = {"state": "on"}

        result = _process_response_httpx(resp)
        assert result.success is True
        assert result.data == {"state": "on"}

    def test_201_success(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 201
        resp.json.return_value = {}

        result = _process_response_httpx(resp)
        assert result.success is True

    def test_200_invalid_json(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")

        result = _process_response_httpx(resp)
        assert result.success is True
        assert result.data == {}

    def test_401_unauthorized(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401

        result = _process_response_httpx(resp)
        assert result.success is False
        assert "Authentication" in result.error

    def test_404_not_found(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 404

        result = _process_response_httpx(resp)
        assert result.success is False
        assert "not found" in result.error

    def test_500_server_error(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.text = "Internal Server Error"

        result = _process_response_httpx(resp)
        assert result.success is False
        assert "500" in result.error


# ---------------------------------------------------------------------------
# _hass_api_call
# ---------------------------------------------------------------------------


class TestHassApiCall:

    async def test_no_token_returns_error(self) -> None:
        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", None)),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 2)),
        ):
            result = await _hass_api_call("GET", "/api/states")

        assert result.success is False
        assert "HASS_TOKEN" in result.error

    async def test_circuit_breaker_open(self) -> None:
        from backend.core.utils.circuit_breaker import HASS_CIRCUIT

        # Force circuit open
        for _ in range(10):
            HASS_CIRCUIT.record_failure()

        result = await _hass_api_call("GET", "/api/states")

        assert result.success is False
        assert "circuit breaker" in result.error.lower()

    async def test_get_request_success(self) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"entity_id": "light.test"}]

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp

        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", "token123")),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 2)),
            patch("backend.core.tools.hass_ops.api.get_client", new_callable=AsyncMock, return_value=mock_client),
        ):
            result = await _hass_api_call("GET", "/api/states")

        assert result.success is True

    async def test_post_request_success(self) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{}]

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp

        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", "tok")),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 0)),
            patch("backend.core.tools.hass_ops.api.get_client", new_callable=AsyncMock, return_value=mock_client),
        ):
            result = await _hass_api_call("POST", "/api/services/light/turn_on", {"entity_id": "light.desk"})

        assert result.success is True
        mock_client.post.assert_called_once()

    async def test_unsupported_method(self) -> None:
        mock_client = AsyncMock()

        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", "tok")),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 0)),
            patch("backend.core.tools.hass_ops.api.get_client", new_callable=AsyncMock, return_value=mock_client),
        ):
            result = await _hass_api_call("DELETE", "/api/states/x")

        assert result.success is False
        assert "Unsupported" in result.error

    async def test_timeout_retries(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")

        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", "tok")),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 1)),
            patch("backend.core.tools.hass_ops.api.get_client", new_callable=AsyncMock, return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _hass_api_call("GET", "/api/states")

        assert result.success is False
        assert "timeout" in result.error.lower()
        # 1 initial + 1 retry = 2 calls
        assert mock_client.get.call_count == 2

    async def test_request_error_retries(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.RequestError("connection refused")

        with (
            patch("backend.core.tools.hass_ops.api._get_hass_credentials", return_value=("http://hass:8123", "tok")),
            patch("backend.core.tools.hass_ops.api._get_hass_config", return_value=(10.0, 1)),
            patch("backend.core.tools.hass_ops.api.get_client", new_callable=AsyncMock, return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await _hass_api_call("GET", "/api/states")

        assert result.success is False
        assert "Connection error" in result.error


# ---------------------------------------------------------------------------
# hass_control_device
# ---------------------------------------------------------------------------


class TestHassControlDevice:

    async def test_turn_on_light(self, mock_hass_api) -> None:
        result = await hass_control_device("light.desk", "turn_on")

        assert result.success is True
        mock_hass_api.assert_called_once_with(
            "POST", "/api/services/light/turn_on", {"entity_id": "light.desk"}
        )

    async def test_turn_off_light(self, mock_hass_api) -> None:
        result = await hass_control_device("light.desk", "turn_off")

        assert result.success is True
        mock_hass_api.assert_called_once_with(
            "POST", "/api/services/light/turn_off", {"entity_id": "light.desk"}
        )

    async def test_toggle(self, mock_hass_api) -> None:
        result = await hass_control_device("switch.plug", "toggle")

        assert result.success is True

    async def test_with_brightness(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", brightness=50)

        call_args = mock_hass_api.call_args
        payload = call_args[0][2]
        assert "brightness" in payload
        # 50% of 255 = 127
        assert payload["brightness"] == 127

    async def test_brightness_100_percent(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", brightness=100)

        payload = mock_hass_api.call_args[0][2]
        assert payload["brightness"] == 255

    async def test_brightness_0_percent(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", brightness=0)

        payload = mock_hass_api.call_args[0][2]
        assert payload["brightness"] == 0

    async def test_brightness_clamped(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", brightness=150)

        payload = mock_hass_api.call_args[0][2]
        assert payload["brightness"] == 255

    async def test_brightness_ignored_on_turn_off(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_off", brightness=50)

        payload = mock_hass_api.call_args[0][2]
        assert "brightness" not in payload

    async def test_with_string_color(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", color="red")

        payload = mock_hass_api.call_args[0][2]
        assert payload["rgb_color"] == [255, 0, 0]

    async def test_with_list_color(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", color=[128, 64, 32])

        payload = mock_hass_api.call_args[0][2]
        assert payload["rgb_color"] == [128, 64, 32]

    async def test_color_ignored_on_turn_off(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_off", color="red")

        payload = mock_hass_api.call_args[0][2]
        assert "rgb_color" not in payload

    async def test_invalid_action(self) -> None:
        result = await hass_control_device("light.desk", "explode")

        assert result.success is False
        assert "Invalid action" in result.error

    async def test_invalid_entity_id_format(self) -> None:
        result = await hass_control_device("desk_light", "turn_on")

        assert result.success is False
        assert "Invalid entity_id format" in result.error

    async def test_all_keyword_delegates(self, mock_hass_api, mock_device_config) -> None:
        """entity_id='all' delegates to hass_control_all_lights."""
        result = await hass_control_device("all", "turn_on")

        # Should be called for each light in mock_device_config.lights
        assert mock_hass_api.call_count == 2

    async def test_extra_kwargs_passed(self, mock_hass_api) -> None:
        await hass_control_device("light.desk", "turn_on", color_temp=300)

        payload = mock_hass_api.call_args[0][2]
        assert payload["color_temp"] == 300

    async def test_api_failure_message(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=False, message="", error="Connection timeout"
        )
        result = await hass_control_device("light.desk", "turn_on")

        assert result.success is False
        assert "Failed" in result.message

    async def test_success_message_with_extras(self, mock_hass_api) -> None:
        result = await hass_control_device(
            "light.desk", "turn_on", brightness=75, color="blue"
        )

        assert "brightness 75%" in result.message
        assert "color blue" in result.message


# ---------------------------------------------------------------------------
# hass_control_light
# ---------------------------------------------------------------------------


class TestHassControlLight:

    async def test_delegates_to_control_device(self, mock_hass_api) -> None:
        result = await hass_control_light("light.desk", "turn_on", brightness=50, color="red")

        assert result.success is True
        payload = mock_hass_api.call_args[0][2]
        assert payload["entity_id"] == "light.desk"


# ---------------------------------------------------------------------------
# hass_control_all_lights
# ---------------------------------------------------------------------------


class TestHassControlAllLights:

    async def test_all_success(self, mock_hass_api, mock_device_config) -> None:
        result = await hass_control_all_lights("turn_on")

        assert result.success is True
        assert "All 2 lights" in result.message
        assert result.data["controlled"] == 2
        assert result.data["total"] == 2

    async def test_partial_success(self, mock_hass_api, mock_device_config) -> None:
        # First call succeeds, second fails
        mock_hass_api.side_effect = [
            HASSResult(success=True, message="OK", data={}),
            HASSResult(success=False, message="", error="timeout"),
        ]

        result = await hass_control_all_lights("turn_off")

        assert result.success is True
        assert "Partial" in result.message
        assert result.data["controlled"] == 1

    async def test_all_fail(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(success=False, message="", error="down")

        result = await hass_control_all_lights("turn_on")

        assert result.success is False
        assert result.data["controlled"] == 0

    async def test_passes_brightness_and_color(self, mock_hass_api, mock_device_config) -> None:
        await hass_control_all_lights("turn_on", brightness=80, color="blue")

        # Both lights should have been called
        assert mock_hass_api.call_count == 2


# ---------------------------------------------------------------------------
# hass_get_state
# ---------------------------------------------------------------------------


class TestHassGetState:

    async def test_valid_entity(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "on",
                "attributes": {"friendly_name": "Desk Light", "brightness": 200},
            },
        )

        result = await hass_get_state("light.desk")

        assert result.success is True
        assert "Desk Light" in result.message
        assert "on" in result.message

    async def test_invalid_entity_id(self) -> None:
        result = await hass_get_state("noperiod")

        assert result.success is False
        assert "Invalid entity_id" in result.error

    async def test_empty_entity_id(self) -> None:
        result = await hass_get_state("")

        assert result.success is False
        assert "Invalid entity_id" in result.error

    async def test_state_with_unit(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Room Temp",
                    "unit_of_measurement": "C",
                },
            },
        )

        result = await hass_get_state("sensor.temp")
        assert "22.5" in result.message
        assert "C" in result.message


# ---------------------------------------------------------------------------
# hass_read_sensor
# ---------------------------------------------------------------------------


class TestHassReadSensor:

    async def test_alias_lookup(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "22.5",
                "attributes": {
                    "friendly_name": "Room Temp",
                    "unit_of_measurement": "C",
                },
            },
        )

        result = await hass_read_sensor("temperature")

        assert result.success is True
        mock_hass_api.assert_called_with("GET", "/api/states/sensor.room_temp")

    async def test_group_lookup(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "50",
                "attributes": {
                    "friendly_name": "Humidity",
                    "unit_of_measurement": "%",
                },
            },
        )

        result = await hass_read_sensor("environment")

        assert result.success is True
        # Should have called for each sensor in the group
        assert mock_hass_api.call_count == 2

    async def test_direct_entity_id(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "100",
                "attributes": {"friendly_name": "Battery"},
            },
        )

        result = await hass_read_sensor("sensor.battery")

        assert result.success is True
        mock_hass_api.assert_called_with("GET", "/api/states/sensor.battery")

    async def test_binary_sensor_entity_id(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "off",
                "attributes": {"friendly_name": "Motion"},
            },
        )

        result = await hass_read_sensor("binary_sensor.motion")

        assert result.success is True

    async def test_plain_query_prefixed_with_sensor(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "42",
                "attributes": {"friendly_name": "Unknown"},
            },
        )

        await hass_read_sensor("some_random_sensor")

        mock_hass_api.assert_called_with("GET", "/api/states/sensor.some_random_sensor")


# ---------------------------------------------------------------------------
# _read_sensor_group
# ---------------------------------------------------------------------------


class TestReadSensorGroup:

    async def test_unknown_group(self, mock_device_config) -> None:
        from backend.core.tools.hass_ops import _read_sensor_group

        result = await _read_sensor_group("nonexistent_group")

        assert result.success is False
        assert "Unknown sensor group" in result.error

    async def test_all_sensors_fail(self, mock_hass_api, mock_device_config) -> None:
        from backend.core.tools.hass_ops import _read_sensor_group

        mock_hass_api.return_value = HASSResult(success=False, message="", error="fail")

        result = await _read_sensor_group("environment")

        assert result.success is False

    async def test_formats_sensor_lines(self, mock_hass_api, mock_device_config) -> None:
        from backend.core.tools.hass_ops import _read_sensor_group

        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data={
                "state": "22",
                "attributes": {
                    "friendly_name": "Room Temp",
                    "unit_of_measurement": "C",
                },
            },
        )

        result = await _read_sensor_group("environment")

        assert result.success is True
        assert result.data["group"] == "environment"
        assert len(result.data["sensors"]) == 2


# ---------------------------------------------------------------------------
# get_all_states
# ---------------------------------------------------------------------------


class TestGetAllStates:

    async def test_returns_all_states(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data=[
                {"entity_id": "light.desk", "state": "on"},
                {"entity_id": "sensor.temp", "state": "22"},
            ],
        )

        result = await get_all_states()

        assert result.success is True
        assert len(result.data) == 2
        assert "2 entity states" in result.message

    async def test_known_only_filter(self, mock_hass_api, mock_device_config) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data=[
                {"entity_id": "light.desk_1", "state": "on"},
                {"entity_id": "sensor.room_temp", "state": "22"},
                {"entity_id": "sensor.unknown", "state": "42"},
            ],
        )

        result = await get_all_states(known_only=True)

        assert result.success is True
        # Only light.desk_1 and sensor.room_temp are in known_entities
        assert len(result.data) == 2
        assert "2 known entity states" in result.message


# ---------------------------------------------------------------------------
# hass_list_entities
# ---------------------------------------------------------------------------


class TestHassListEntities:

    async def test_list_with_domain_filter(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data=[
                {"entity_id": "light.desk", "state": "on", "attributes": {"friendly_name": "Desk"}},
                {"entity_id": "light.bed", "state": "off", "attributes": {"friendly_name": "Bed"}},
                {"entity_id": "sensor.temp", "state": "22", "attributes": {"friendly_name": "Temp"}},
            ],
        )

        result = await hass_list_entities(domain="light")

        assert result.success is True
        assert result.data["domain"] == "light"
        assert len(result.data["entities"]) == 2

    async def test_list_all_domains(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(
            success=True,
            message="OK",
            data=[
                {"entity_id": "light.desk", "state": "on", "attributes": {}},
                {"entity_id": "sensor.temp", "state": "22", "attributes": {}},
                {"entity_id": "sensor.humid", "state": "50", "attributes": {}},
            ],
        )

        result = await hass_list_entities()

        assert result.success is True
        domains = result.data["domains"]
        assert domains["light"] == 1
        assert domains["sensor"] == 2
        assert result.data["total"] == 3

    async def test_api_failure_propagates(self, mock_hass_api) -> None:
        mock_hass_api.return_value = HASSResult(success=False, message="", error="down")

        result = await hass_list_entities(domain="light")

        assert result.success is False
