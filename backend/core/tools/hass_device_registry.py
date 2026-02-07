"""YAML-based Home Assistant device registry.

Loads IoT device configuration from a YAML file instead of
hardcoding entity IDs in source code.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.core.logging import get_logger

_log = get_logger("tools.hass_registry")


@dataclass
class DeviceConfig:
    """Parsed device configuration from YAML."""

    lights: list[str] = field(default_factory=list)
    light_names: dict[str, str] = field(default_factory=dict)
    other_devices: dict[str, str] = field(default_factory=dict)
    sensor_aliases: dict[str, str] = field(default_factory=dict)
    sensor_groups: dict[str, list[str]] = field(default_factory=dict)

    @property
    def known_entities(self) -> set[str]:
        """Union of all registered entity IDs."""
        return (
            set(self.lights)
            | set(self.other_devices.values())
            | set(self.sensor_aliases.values())
        )


def load_device_config(config_path: Path) -> DeviceConfig:
    """Load device config from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Parsed DeviceConfig. Returns empty defaults if file is missing.
    """
    if not config_path.exists():
        _log.warning("Device config not found, using defaults", path=str(config_path))
        return DeviceConfig()

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        _log.error("Failed to parse device config", path=str(config_path), err=str(e))
        return DeviceConfig()

    if not raw:
        return DeviceConfig()

    lights_raw = raw.get("lights", [])
    lights = [entry["entity_id"] for entry in lights_raw if "entity_id" in entry]
    light_names = {
        entry["entity_id"]: entry.get("name", entry["entity_id"])
        for entry in lights_raw
        if "entity_id" in entry
    }

    other_raw = raw.get("other_devices", {})
    other_devices = {
        key: val["entity_id"]
        for key, val in other_raw.items()
        if isinstance(val, dict) and "entity_id" in val
    }

    sensor_aliases = raw.get("sensor_aliases", {})
    sensor_groups = raw.get("sensor_groups", {})

    _log.info(
        "Device config loaded",
        lights=len(lights),
        devices=len(other_devices),
        aliases=len(sensor_aliases),
        groups=len(sensor_groups),
    )

    return DeviceConfig(
        lights=lights,
        light_names=light_names,
        other_devices=other_devices,
        sensor_aliases=sensor_aliases,
        sensor_groups=sensor_groups,
    )
