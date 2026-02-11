"""Home Assistant device and light control operations."""

import re
import colorsys
import asyncio
from typing import Optional, List, Any, Dict, Union
from backend.core.logging import get_logger
from .config import HASSResult, DeviceAction, COLOR_MAP, get_lights
from .api import _hass_api_call

_log = get_logger("tools.hass.devices")


def parse_color(color_input: str) -> Optional[List[int]]:
    """Parse color input string to RGB values.
    
    Supports:
    - Named colors (English and Korean)
    - Hex colors (#RRGGBB or RRGGBB)
    - HSL (hsl(H, S, L) or H, S, L)
    - RGB (rgb(R, G, B))
    
    Args:
        color_input: Color string to parse
    
    Returns:
        [R, G, B] list or None if invalid
    """
    if not color_input:
        return None

    color_input = color_input.strip().lower()

    # Check named colors
    if color_input in COLOR_MAP:
        return COLOR_MAP[color_input].copy()

    # Hex color (#RRGGBB or RRGGBB)
    hex_match = re.match(r'^#?([0-9a-f]{6})$', color_input)
    if hex_match:
        hex_str = hex_match.group(1)
        return [int(hex_str[i:i+2], 16) for i in (0, 2, 4)]

    # HSL color
    hsl_match = re.match(r'^(?:hsl\()?(\d+)[,\s]+(\d+)[,\s]+(\d+)\)?$', color_input)
    if hsl_match:
        h = int(hsl_match.group(1)) % 360
        s = min(100, max(0, int(hsl_match.group(2)))) / 100
        lightness = min(100, max(0, int(hsl_match.group(3)))) / 100
        r, g, b = colorsys.hls_to_rgb(h / 360, lightness, s)
        return [int(r * 255), int(g * 255), int(b * 255)]

    # RGB color
    rgb_match = re.match(r'^rgb\((\d+)[,\s]+(\d+)[,\s]+(\d+)\)$', color_input)
    if rgb_match:
        return [
            min(255, max(0, int(rgb_match.group(1)))),
            min(255, max(0, int(rgb_match.group(2)))),
            min(255, max(0, int(rgb_match.group(3))))
        ]

    return None


async def hass_control_device(
    entity_id: str,
    action: str,
    brightness: Optional[int] = None,
    color: Optional[Union[str, List[int]]] = None,
    **kwargs: Any
) -> HASSResult:
    """Control a Home Assistant device.
    
    Args:
        entity_id: Entity ID (e.g., "light.living_room") or "all" for all lights
        action: Action to perform (turn_on, turn_off, toggle)
        brightness: Optional brightness percentage (0-100)
        color: Optional color (name, hex, HSL, RGB, or [R,G,B] list)
        **kwargs: Additional service data parameters
    
    Returns:
        HASSResult with operation status
    """
    _log.info("HASS control", ent=entity_id, action=action)

    if entity_id.lower() == "all":
        return await hass_control_all_lights(action, brightness, color)

    try:
        device_action = DeviceAction(action.lower())
    except ValueError:
        _log.warning("HASS fail", ent=entity_id, err=f"Invalid action: {action}")
        return HASSResult(
            success=False,
            message="",
            error=f"Invalid action '{action}'. Must be: turn_on, turn_off, toggle"
        )

    if "." not in entity_id:
        _log.warning("HASS fail", ent=entity_id, err="Invalid entity_id format")
        return HASSResult(
            success=False,
            message="",
            error=f"Invalid entity_id format: {entity_id}. Expected 'domain.entity'"
        )

    domain = entity_id.split(".")[0]

    service_data: Dict[str, Any] = {"entity_id": entity_id}

    # Add brightness if specified
    if brightness is not None and action == "turn_on":
        brightness_255 = int(min(100, max(0, brightness)) * 255 / 100)
        service_data["brightness"] = brightness_255

    # Add color if specified
    if color is not None and action == "turn_on":
        if isinstance(color, str):
            rgb = parse_color(color)
        else:
            rgb = color

        if rgb:
            service_data["rgb_color"] = rgb

    # Add any additional kwargs
    for key, value in kwargs.items():
        if value is not None:
            service_data[key] = value

    endpoint = f"/api/services/{domain}/{device_action.value}"
    result = await _hass_api_call("POST", endpoint, service_data)

    if result.success:
        extras = []
        if brightness is not None:
            extras.append(f"brightness {brightness}%")
        if color is not None:
            extras.append(f"color {color}")
        extra_msg = f" ({', '.join(extras)})" if extras else ""

        result.message = f" {entity_id} {action} complete{extra_msg}"
        _log.info("HASS ok", ent=entity_id, action=action)
    else:
        result.message = f" Failed to {action} {entity_id}: {result.error}"
        _log.warning("HASS fail", ent=entity_id, err=result.error[:100] if result.error else "Unknown")

    return result


async def hass_control_light(
    entity_id: str,
    action: str,
    brightness: Optional[int] = None,
    color: Optional[str] = None
) -> HASSResult:
    """Control a Home Assistant light (convenience wrapper).
    
    Args:
        entity_id: Light entity ID
        action: Action to perform (turn_on, turn_off, toggle)
        brightness: Optional brightness percentage (0-100)
        color: Optional color string
    
    Returns:
        HASSResult with operation status
    """
    return await hass_control_device(entity_id, action, brightness, color)


async def hass_control_all_lights(
    action: str,
    brightness: Optional[int] = None,
    color: Optional[Union[str, List[int]]] = None
) -> HASSResult:
    """Control all registered lights simultaneously.
    
    Args:
        action: Action to perform (turn_on, turn_off, toggle)
        brightness: Optional brightness percentage (0-100)
        color: Optional color (name, hex, HSL, RGB, or [R,G,B] list)
    
    Returns:
        HASSResult with summary of operations
    """
    lights = get_lights()
    _log.info("HASS all lights", action=action, cnt=len(lights))

    sem = asyncio.Semaphore(5)

    async def _control_one(light_id: str) -> HASSResult:
        async with sem:
            return await hass_control_device(light_id, action, brightness, color)

    results = list(await asyncio.gather(*(_control_one(lid) for lid in lights)))

    success_count = sum(1 for r in results if r.success)
    total = len(lights)

    if success_count == total:
        _log.info("HASS all lights ok", action=action, cnt=success_count)
        return HASSResult(
            success=True,
            message=f" All {total} lights {action} complete",
            data={"controlled": success_count, "total": total}
        )
    elif success_count > 0:
        _log.warning("HASS all lights partial", action=action, ok=success_count, total=total)
        return HASSResult(
            success=True,
            message=f" Partial success: {success_count}/{total} lights {action}",
            data={"controlled": success_count, "total": total}
        )
    else:
        _log.error("HASS all lights fail", action=action)
        return HASSResult(
            success=False,
            message=" Failed to control all lights",
            error="All light control attempts failed",
            data={"controlled": 0, "total": total}
        )
