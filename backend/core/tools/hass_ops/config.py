"""Configuration, constants, and type definitions for Home Assistant operations."""

import os
from typing import Optional, Any, Dict
from dataclasses import dataclass
from enum import Enum
from backend.core.tools.hass_device_registry import load_device_config

# Load device config from YAML (single source of truth)
# Lazy-loaded to avoid circular import (config → core → hass_ops → config)
_device_config = None


def _get_device_config():
    global _device_config
    if _device_config is None:
        from backend.config import DATA_ROOT
        _device_config = load_device_config(DATA_ROOT / "hass_devices.yaml")
    return _device_config


COLOR_MAP = {
    "red": [255, 0, 0],
    "green": [0, 255, 0],
    "blue": [0, 0, 255],
    "white": [255, 255, 255],
    "yellow": [255, 255, 0],
    "purple": [128, 0, 128],
    "orange": [255, 165, 0],
    "pink": [255, 192, 203],
    "cyan": [0, 255, 255],
    "warm": [255, 200, 150],
    "warmwhite": [255, 200, 150],
    "warm white": [255, 200, 150],
    "cool": [200, 220, 255],
    # Korean color names
    "빨강": [255, 0, 0],
    "파랑": [0, 0, 255],
    "초록": [0, 255, 0],
    "노랑": [255, 255, 0],
    "분홍": [255, 192, 203],
    "보라": [128, 0, 128],
    "주황": [255, 165, 0],
    "하양": [255, 255, 255],
    "흰색": [255, 255, 255],
}


def get_lights() -> list[str]:
    """Get list of registered light entity IDs."""
    return _get_device_config().lights


def get_other_devices() -> dict:
    """Get dictionary of other registered devices."""
    return _get_device_config().other_devices


def get_sensor_aliases() -> dict:
    """Get sensor alias mappings."""
    return _get_device_config().sensor_aliases


def get_sensor_groups() -> dict:
    """Get sensor group definitions."""
    return _get_device_config().sensor_groups


def _get_hass_config():
    """Lazy import to avoid circular dependency."""
    from backend.config import HASS_TIMEOUT, HASS_MAX_RETRIES
    return HASS_TIMEOUT, HASS_MAX_RETRIES


def _get_hass_credentials() -> tuple[str, Optional[str]]:
    """Get Home Assistant URL and token from environment."""
    from backend.core.logging import get_logger
    
    _log = get_logger("tools.hass.config")
    hass_url = os.getenv("HASS_URL", "http://192.168.1.131:8123")
    hass_token = os.getenv("HASS_TOKEN")
    _log.debug("HASS credentials loaded", url=hass_url)
    return hass_url, hass_token


@dataclass
class HASSResult:
    """Result object for Home Assistant API operations."""
    
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DeviceAction(Enum):
    """Supported device actions."""
    
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
