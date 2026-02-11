"""Home Assistant sensor reading and group operations."""

from backend.core.logging import get_logger
from .config import HASSResult, get_sensor_groups, get_sensor_aliases
from .api import hass_get_state

_log = get_logger("tools.hass.sensors")


async def hass_read_sensor(query: str) -> HASSResult:
    """Read a sensor or sensor group by name/alias/entity_id.
    
    Supports:
    - Sensor groups (e.g., "temperature", "climate")
    - Sensor aliases from configuration
    - Direct entity IDs (e.g., "sensor.living_room_temp")
    - Partial names (auto-prefixed with "sensor.")
    
    Args:
        query: Sensor identifier (group, alias, entity_id, or name)
    
    Returns:
        HASSResult with sensor data or group data
    """
    _log.debug("HASS read sensor", query=query)
    query = query.lower().strip()

    sensor_groups = get_sensor_groups()
    sensor_aliases = get_sensor_aliases()

    # Check if it's a sensor group
    if query in sensor_groups:
        return await _read_sensor_group(query)

    # Resolve alias or build entity_id
    if query in sensor_aliases:
        entity_id = sensor_aliases[query]
    elif query.startswith("sensor.") or query.startswith("binary_sensor."):
        entity_id = query
    else:
        # Auto-prefix with sensor.
        entity_id = f"sensor.{query}"

    return await _read_single_sensor(entity_id)


async def _read_single_sensor(entity_id: str) -> HASSResult:
    """Read a single sensor's state.
    
    Args:
        entity_id: Sensor entity ID
    
    Returns:
        HASSResult with sensor state and attributes
    """
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
    """Read all sensors in a sensor group.
    
    Args:
        group_name: Name of the sensor group
    
    Returns:
        HASSResult with list of sensor data
    """
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
        if s is None:
            continue
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
