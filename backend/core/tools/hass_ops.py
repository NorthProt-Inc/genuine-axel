import os
import re
import asyncio
import colorsys
from typing import Optional, List, Any, Dict, Union
from dataclasses import dataclass
from enum import Enum
import httpx
from backend.core.logging import get_logger
from backend.core.utils.http_pool import get_client
from backend.core.utils.circuit_breaker import HASS_CIRCUIT
from backend.core.tools.hass_device_registry import load_device_config

_log = get_logger("tools.hass")

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
    return _get_device_config().lights

def get_other_devices() -> dict:
    return _get_device_config().other_devices

def get_sensor_aliases() -> dict:
    return _get_device_config().sensor_aliases

def get_sensor_groups() -> dict:
    return _get_device_config().sensor_groups

def _get_hass_config():
    """Lazy import to avoid circular dependency."""
    from backend.config import HASS_TIMEOUT, HASS_MAX_RETRIES
    return HASS_TIMEOUT, HASS_MAX_RETRIES

@dataclass
class HASSResult:

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class DeviceAction(Enum):

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"

def parse_color(color_input: str) -> Optional[List[int]]:

    if not color_input:
        return None

    color_input = color_input.strip().lower()

    if color_input in COLOR_MAP:
        return COLOR_MAP[color_input].copy()

    hex_match = re.match(r'^#?([0-9a-f]{6})$', color_input)
    if hex_match:
        hex_str = hex_match.group(1)
        return [int(hex_str[i:i+2], 16) for i in (0, 2, 4)]

    hsl_match = re.match(r'^(?:hsl\()?(\d+)[,\s]+(\d+)[,\s]+(\d+)\)?$', color_input)
    if hsl_match:
        h = int(hsl_match.group(1)) % 360
        s = min(100, max(0, int(hsl_match.group(2)))) / 100
        l = min(100, max(0, int(hsl_match.group(3)))) / 100
        r, g, b = colorsys.hls_to_rgb(h / 360, l, s)
        return [int(r * 255), int(g * 255), int(b * 255)]

    rgb_match = re.match(r'^rgb\((\d+)[,\s]+(\d+)[,\s]+(\d+)\)$', color_input)
    if rgb_match:
        return [
            min(255, max(0, int(rgb_match.group(1)))),
            min(255, max(0, int(rgb_match.group(2)))),
            min(255, max(0, int(rgb_match.group(3))))
        ]

    return None

def _get_hass_credentials() -> tuple[str, Optional[str]]:

    hass_url = os.getenv("HASS_URL", "http://192.168.1.131:8123")
    hass_token = os.getenv("HASS_TOKEN")
    _log.debug("HASS credentials loaded", url=hass_url)
    return hass_url, hass_token

async def _hass_api_call(
    method: str,
    endpoint: str,
    payload: Optional[Dict] = None,
    retries: int = None
) -> HASSResult:
    # Get config values at runtime to avoid circular import
    hass_timeout, hass_max_retries = _get_hass_config()
    if retries is None:
        retries = hass_max_retries

    _log.debug("HASS req", endpoint=endpoint, method=method)

    # Check circuit breaker first
    if not HASS_CIRCUIT.can_execute():
        timeout_remaining = HASS_CIRCUIT.get_timeout_remaining()
        HASS_CIRCUIT.record_rejected()
        _log.warning("HASS circuit open", timeout_remaining=timeout_remaining)
        return HASSResult(
            success=False,
            message="",
            error=f"Home Assistant circuit breaker is OPEN. Retry after {timeout_remaining:.0f}s"
        )

    hass_url, hass_token = _get_hass_credentials()

    if not hass_token:
        _log.error("HASS fail", err="HASS_TOKEN not configured")
        return HASSResult(
            success=False,
            message="",
            error="HASS_TOKEN not configured. Set the HASS_TOKEN environment variable."
        )

    headers = {
        "Authorization": f"Bearer {hass_token}",
        "Content-Type": "application/json"
    }

    last_error = None

    for attempt in range(retries + 1):
        try:
            client = await get_client(
                service="hass",
                base_url=hass_url,
                headers=headers,
                timeout=hass_timeout
            )

            if method.upper() == "GET":
                resp = await client.get(endpoint)
                result = _process_response_httpx(resp, endpoint)
                if result.success:
                    HASS_CIRCUIT.record_success()
                    _log.info("HASS ok", endpoint=endpoint, method=method)
                else:
                    HASS_CIRCUIT.record_failure()
                return result
            elif method.upper() == "POST":
                resp = await client.post(endpoint, json=payload)
                result = _process_response_httpx(resp, endpoint)
                if result.success:
                    HASS_CIRCUIT.record_success()
                    _log.info("HASS ok", endpoint=endpoint, method=method)
                else:
                    HASS_CIRCUIT.record_failure()
                return result
            else:
                _log.error("HASS fail", err=f"Unsupported method: {method}")
                return HASSResult(
                    success=False,
                    message="",
                    error=f"Unsupported HTTP method: {method}"
                )
        except httpx.TimeoutException:
            HASS_CIRCUIT.record_failure()
            last_error = "Connection timeout - Home Assistant may be unreachable"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err="timeout")
        except httpx.RequestError as e:
            HASS_CIRCUIT.record_failure()
            last_error = f"Connection error: {str(e)}"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err=str(e)[:100])
        except Exception as e:
            HASS_CIRCUIT.record_failure()
            last_error = f"Unexpected error: {str(e)}"
            _log.warning("HASS retry", endpoint=endpoint, attempt=attempt+1, err=str(e)[:100])

        if attempt < retries:
            await asyncio.sleep(0.5 * (attempt + 1))

    _log.error("HASS fail", endpoint=endpoint, err=last_error[:100] if last_error else "Unknown")
    return HASSResult(
        success=False,
        message="",
        error=last_error or "Unknown error after retries"
    )

def _process_response_httpx(resp: httpx.Response, endpoint: str = "") -> HASSResult:

    _log.debug("HASS res", endpoint=endpoint, status=resp.status_code)
    if resp.status_code in (200, 201):
        try:
            data = resp.json()
            return HASSResult(
                success=True,
                message="OK",
                data=data
            )
        except Exception:
            return HASSResult(success=True, message="OK", data={})
    elif resp.status_code == 401:
        return HASSResult(
            success=False,
            message="",
            error="Authentication failed - check HASS_TOKEN"
        )
    elif resp.status_code == 404:
        return HASSResult(
            success=False,
            message="",
            error="Entity not found"
        )
    else:
        return HASSResult(
            success=False,
            message="",
            error=f"HASS API error {resp.status_code}: {resp.text[:200]}"
        )

async def hass_control_device(
    entity_id: str,
    action: str,
    brightness: Optional[int] = None,
    color: Optional[Union[str, List[int]]] = None,
    **kwargs: Any
) -> HASSResult:

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

    if brightness is not None and action == "turn_on":
        brightness_255 = int(min(100, max(0, brightness)) * 255 / 100)
        service_data["brightness"] = brightness_255

    if color is not None and action == "turn_on":
        if isinstance(color, str):
            rgb = parse_color(color)
        else:
            rgb = color

        if rgb:
            service_data["rgb_color"] = rgb

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

    return await hass_control_device(entity_id, action, brightness, color)

async def hass_control_all_lights(
    action: str,
    brightness: Optional[int] = None,
    color: Optional[Union[str, List[int]]] = None
) -> HASSResult:

    lights = get_lights()
    _log.info("HASS all lights", action=action, cnt=len(lights))
    results = []

    for i, light_id in enumerate(lights):
        result = await hass_control_device(
            light_id,
            action,
            brightness,
            color
        )
        results.append(result)

        if i < len(lights) - 1:
            await asyncio.sleep(0.05)

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
            message=f" Failed to control all lights",
            error="All light control attempts failed",
            data={"controlled": 0, "total": total}
        )

async def hass_get_state(entity_id: str) -> HASSResult:

    _log.debug("HASS get state", ent=entity_id)

    if not entity_id or "." not in entity_id:
        _log.warning("HASS fail", ent=entity_id, err="Invalid entity_id")
        return HASSResult(
            success=False,
            message="",
            error=f"Invalid entity_id: {entity_id}"
        )

    result = await _hass_api_call("GET", f"/api/states/{entity_id}")

    if result.success and result.data:
        attrs = result.data.get("attributes", {})
        state = result.data.get("state")
        result.message = (
            f"{attrs.get('friendly_name', entity_id)}: "
            f"{state}"
            f"{attrs.get('unit_of_measurement', '')}"
        )
        _log.debug("HASS state ok", ent=entity_id, state=state)

    return result

async def hass_read_sensor(query: str) -> HASSResult:

    _log.debug("HASS read sensor", query=query)
    query = query.lower().strip()

    sensor_groups = get_sensor_groups()
    sensor_aliases = get_sensor_aliases()

    if query in sensor_groups:
        return await _read_sensor_group(query)

    if query in sensor_aliases:
        entity_id = sensor_aliases[query]
    elif query.startswith("sensor.") or query.startswith("binary_sensor."):
        entity_id = query
    else:

        entity_id = f"sensor.{query}"

    return await _read_single_sensor(entity_id)

async def _read_single_sensor(entity_id: str) -> HASSResult:

    _log.debug("HASS read single", ent=entity_id)
    result = await hass_get_state(entity_id)

    if result.success and result.data:
        attrs = result.data.get("attributes", {})
        state = result.data.get("state", "unknown")
        unit = attrs.get("unit_of_measurement", "")
        name = attrs.get("friendly_name", entity_id)

        result.message = f"{name}: {state}{unit}"
        result.data = {
            "entity_id": entity_id,
            "state": state,
            "unit": unit,
            "friendly_name": name,
            "attributes": attrs
        }
        _log.debug("HASS sensor ok", ent=entity_id, state=state)

    return result

async def _read_sensor_group(group_name: str) -> HASSResult:

    _log.debug("HASS read group", group=group_name)
    entity_ids = get_sensor_groups().get(group_name, [])

    if not entity_ids:
        _log.warning("HASS fail", group=group_name, err="Unknown group")
        return HASSResult(
            success=False,
            message="",
            error=f"Unknown sensor group: {group_name}"
        )

    sensors = []
    for entity_id in entity_ids:
        result = await _read_single_sensor(entity_id)
        if result.success:
            sensors.append(result.data)

    if not sensors:
        _log.warning("HASS fail", group=group_name, err="No sensors readable")
        return HASSResult(
            success=False,
            message="",
            error=f"Failed to read any sensors in group '{group_name}'"
        )

    lines = []
    for s in sensors:
        name = s.get("friendly_name", s.get("entity_id", "Unknown"))
        state = s.get("state", "?")
        unit = s.get("unit", "")
        lines.append(f"• {name}: {state}{unit}")

    _log.debug("HASS group ok", group=group_name, cnt=len(sensors))
    return HASSResult(
        success=True,
        message="\n".join(lines),
        data={"group": group_name, "sensors": sensors}
    )

async def get_all_states(known_only: bool = False) -> HASSResult:
    """Get states of Home Assistant entities.

    Args:
        known_only: If True, filter to registered entities only.
            Defaults to False (return all entities).
    """
    _log.debug("HASS get all states", known_only=known_only)
    result = await _hass_api_call("GET", "/api/states")

    if result.success and result.data:
        if known_only:
            known_entities = _get_device_config().known_entities
            filtered = [
                state for state in result.data
                if state.get("entity_id") in known_entities
            ]
            result.data = filtered
            result.message = f"Retrieved {len(filtered)} known entity states"
        else:
            result.message = f"Retrieved {len(result.data)} entity states"
        _log.debug("HASS all states ok", cnt=len(result.data))

    return result

async def hass_list_entities(domain: str = None) -> HASSResult:

    _log.debug("HASS list entities", domain=domain)
    result = await _hass_api_call("GET", "/api/states")

    if not result.success:
        return result

    all_entities = result.data or []

    if domain:

        filtered = [
            {
                "entity_id": e.get("entity_id"),
                "friendly_name": e.get("attributes", {}).get("friendly_name", e.get("entity_id")),
                "state": e.get("state")
            }
            for e in all_entities
            if e.get("entity_id", "").startswith(f"{domain}.")
        ]
        _log.debug("HASS entities ok", domain=domain, cnt=len(filtered))
        return HASSResult(
            success=True,
            message=f"Found {len(filtered)} {domain} entities",
            data={"domain": domain, "entities": filtered}
        )
    else:

        domains = {}
        for e in all_entities:
            entity_id = e.get("entity_id", "")
            if "." in entity_id:
                d = entity_id.split(".")[0]
                domains[d] = domains.get(d, 0) + 1

        _log.debug("HASS entities ok", domains=len(domains), total=len(all_entities))
        return HASSResult(
            success=True,
            message=f"Found {len(all_entities)} total entities across {len(domains)} domains",
            data={"domains": domains, "total": len(all_entities)}
        )
