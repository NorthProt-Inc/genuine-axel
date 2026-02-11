"""Home Assistant operations - Refactored package structure.

This package provides Home Assistant integration with support for:
- Device and light control
- Sensor reading and grouping
- State queries and entity listing
- Circuit breaker protection
- Retry logic and connection pooling

Original monolithic file (559 lines) split into:
- config.py: Configuration, constants, types (~60 lines)
- api.py: Low-level API calls (~150 lines)
- devices.py: Device and light control (~200 lines)
- sensors.py: Sensor operations (~150 lines)

All imports from backend.core.tools.hass_ops work unchanged for backward compatibility.
"""

# Re-export config and types
from .config import (
    HASSResult,
    DeviceAction,
    COLOR_MAP,
    get_lights,
    get_other_devices,
    get_sensor_aliases,
    get_sensor_groups,
    _get_hass_config,
    _get_hass_credentials,
    _get_device_config,
)

# Re-export API functions
from .api import (
    _hass_api_call,
    _process_response_httpx,
    hass_get_state,
    get_all_states,
    hass_list_entities,
)

# Re-export device control
from .devices import (
    parse_color,
    hass_control_device,
    hass_control_light,
    hass_control_all_lights,
)

# Re-export sensor operations
from .sensors import (
    hass_read_sensor,
    _read_single_sensor,
    _read_sensor_group,
)

__all__ = [
    # Types and config
    "HASSResult",
    "DeviceAction",
    "COLOR_MAP",
    "get_lights",
    "get_other_devices",
    "get_sensor_aliases",
    "get_sensor_groups",
    "_get_hass_config",
    "_get_hass_credentials",
    "_get_device_config",
    # API functions
    "_hass_api_call",
    "_process_response_httpx",
    "hass_get_state",
    "get_all_states",
    "hass_list_entities",
    # Device control
    "parse_color",
    "hass_control_device",
    "hass_control_light",
    "hass_control_all_lights",
    # Sensor operations
    "hass_read_sensor",
    "_read_single_sensor",
    "_read_sensor_group",
]
