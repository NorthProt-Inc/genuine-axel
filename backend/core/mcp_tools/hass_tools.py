from typing import Any, Sequence
from mcp.types import TextContent
from . import register_tool
from backend.core.logging.logging import get_logger

_log = get_logger("mcp.hass_tools")

@register_tool(
    "hass_control_light",
    category="hass",
    description="""조명 제어 (WiZ RGB).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "불 켜줘", "불 꺼줘", "조명 켜", "조명 꺼"
- "밝기 조절", "색 바꿔", "빨간색으로"
- "hass_control_light" (도구 이름 직접 언급)

[파라미터]
- entity_id: 'all'(전체) 또는 특정 조명 ID
- action: turn_on / turn_off
- brightness: 0-100 (밝기 %)
- color: 색상 (red, blue, #FF0000 등)

말로만 하지 말고 반드시 function_call 생성할 것.""",
    input_schema={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Light entity (e.g., 'all', 'light.wiz_rgbw_tunable_77d6a0')"},
            "action": {"type": "string", "enum": ["turn_on", "turn_off"], "description": "Action to perform"},
            "brightness": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Brightness percentage (0-100)"},
            "color": {"type": "string", "description": "Color: hex (#FF0000), name (red), or hsl(240,100,50)"}
        },
        "required": ["entity_id", "action"]
    }
)
async def hass_control_light_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Control Home Assistant lights with brightness and color.

    Args:
        arguments: Dict with entity_id, action, brightness, color

    Returns:
        TextContent with operation result
    """
    entity_id = arguments.get("entity_id", "all")
    action = arguments.get("action", "turn_on")
    brightness_pct = arguments.get("brightness")
    color_str = arguments.get("color")
    _log.debug("TOOL invoke", fn="hass_control_light", entity_id=entity_id, action=action, brightness=brightness_pct)

    if action not in ["turn_on", "turn_off"]:
        _log.warning("TOOL fail", fn="hass_control_light", err="invalid action")
        return [TextContent(type="text", text="Error: action must be 'turn_on' or 'turn_off'")]

    if brightness_pct is not None:
        if not isinstance(brightness_pct, (int, float)) or brightness_pct < 0 or brightness_pct > 100:
            _log.warning("TOOL fail", fn="hass_control_light", err="invalid brightness")
            return [TextContent(type="text", text="Error: brightness must be 0-100")]

    try:
        from backend.core.tools.hass_ops import hass_control_light

        result = await hass_control_light(
            entity_id=entity_id,
            action=action,
            brightness=brightness_pct,
            color=color_str
        )

        if result.success:
            _log.info("TOOL ok", fn="hass_control_light", entity_id=entity_id, action=action)
        else:
            _log.warning("TOOL partial", fn="hass_control_light", err=result.error[:100] if result.error else None)

        return [TextContent(type="text", text=result.message)]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_control_light", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ HASS Error: {str(e)}")]

@register_tool(
    "hass_control_device",
    category="hass",
    description="""기기 제어 (팬, 스위치, 가습기).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "팬 켜줘", "팬 꺼줘", "공기청정기 켜"
- "가습기 켜", "스위치 꺼"

[파라미터]
- entity_id: 기기 ID (예: fan.vital_100s_series)
- action: turn_on / turn_off""",
    input_schema={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Device entity (e.g., 'fan.vital_100s_series')"},
            "action": {"type": "string", "enum": ["turn_on", "turn_off"], "description": "Action to perform"}
        },
        "required": ["entity_id", "action"]
    }
)
async def hass_control_device_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Control Home Assistant devices (fans, switches, etc.).

    Args:
        arguments: Dict with entity_id and action

    Returns:
        TextContent with operation result
    """
    entity_id = arguments.get("entity_id", "")
    action = arguments.get("action", "turn_on")
    _log.debug("TOOL invoke", fn="hass_control_device", entity_id=entity_id, action=action)

    if not entity_id:
        _log.warning("TOOL fail", fn="hass_control_device", err="entity_id parameter required")
        return [TextContent(type="text", text="Error: entity_id parameter is required")]

    if action not in ["turn_on", "turn_off"]:
        _log.warning("TOOL fail", fn="hass_control_device", err="invalid action")
        return [TextContent(type="text", text="Error: action must be 'turn_on' or 'turn_off'")]

    try:
        from backend.core.tools.hass_ops import hass_control_device

        result = await hass_control_device(entity_id=entity_id, action=action)

        if result.success:
            _log.info("TOOL ok", fn="hass_control_device", entity_id=entity_id, action=action)
        else:
            _log.warning("TOOL partial", fn="hass_control_device", err=result.error[:100] if result.error else None)

        return [TextContent(type="text", text=result.message)]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_control_device", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ HASS Error: {str(e)}")]

@register_tool(
    "hass_read_sensor",
    category="hass",
    description="""Read sensor values from Home Assistant.

Quick aliases (use these first):
- 'battery': iPhone battery level
- 'printer': All printer info (status, ink levels)
- 'weather': Weather forecast

For unknown entities: Use hass_list_entities(domain='sensor') first to discover available sensors, then use hass_get_state(entity_id) to read them.""",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Sensor alias ('battery', 'printer', 'weather') or full entity_id"}
        },
        "required": ["query"]
    }
)
async def hass_read_sensor_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Read sensor values from Home Assistant.

    Args:
        arguments: Dict with query (alias or entity_id)

    Returns:
        TextContent with sensor value
    """
    query = arguments.get("query", "")
    _log.debug("TOOL invoke", fn="hass_read_sensor", query=query[:50] if query else None)

    if not query:
        _log.warning("TOOL fail", fn="hass_read_sensor", err="query parameter required")
        return [TextContent(type="text", text="Error: query parameter is required")]

    try:
        from backend.core.tools.hass_ops import hass_read_sensor

        result = await hass_read_sensor(query)

        if result.success:
            _log.info("TOOL ok", fn="hass_read_sensor", query=query[:30])
            return [TextContent(type="text", text=result.message)]
        else:
            _log.warning("TOOL partial", fn="hass_read_sensor", query=query[:30], err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"✗ {result.error}")]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_read_sensor", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Sensor Error: {str(e)}")]

@register_tool(
    "hass_get_state",
    category="hass",
    description="Get the raw state of any Home Assistant entity. Returns full state object with attributes.",
    input_schema={
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Full entity ID (e.g., 'light.living_room', 'switch.fan')"}
        },
        "required": ["entity_id"]
    }
)
async def hass_get_state_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Get raw state of any Home Assistant entity.

    Args:
        arguments: Dict with entity_id

    Returns:
        TextContent with full state object and attributes
    """
    entity_id = arguments.get("entity_id", "")
    _log.debug("TOOL invoke", fn="hass_get_state", entity_id=entity_id)

    if not entity_id:
        _log.warning("TOOL fail", fn="hass_get_state", err="entity_id parameter required")
        return [TextContent(type="text", text="Error: entity_id parameter is required")]

    try:
        from backend.core.tools.hass_ops import hass_get_state

        result = await hass_get_state(entity_id)

        if result.success:
            data = result.data
            attrs = data.get("attributes", {})
            state = data.get('state')
            _log.info("TOOL ok", fn="hass_get_state", entity_id=entity_id, state=state)
            output = [
                f"✓ Entity: {entity_id}",
                f"   State: {state}",
                f"   Last Changed: {data.get('last_changed', 'N/A')}",
            ]
            if attrs:
                output.append("   Attributes:")
                for key, value in list(attrs.items())[:10]:
                    output.append(f"     • {key}: {value}")

            return [TextContent(type="text", text="\n".join(output))]
        else:
            _log.warning("TOOL partial", fn="hass_get_state", err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"✗ {result.error}")]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_get_state", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ State Error: {str(e)}")]

@register_tool(
    "hass_list_entities",
    category="hass",
    description="""List available Home Assistant entities.

Without domain: Returns summary of all domains (sensor, light, fan, etc.) with counts.
With domain: Returns all entities in that domain with their states.

Example queries:
- domain=None: Get overview of what's available
- domain='sensor': List all sensors
- domain='light': List all lights
- domain='fan': List all fans (like air purifier)""",
    input_schema={
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Optional: filter by domain (sensor, light, fan, switch, etc.)"}
        },
        "required": []
    }
)
async def hass_list_entities_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """List available Home Assistant entities by domain.

    Args:
        arguments: Dict with optional domain filter

    Returns:
        TextContent with entity list or domain summary
    """
    domain = arguments.get("domain")
    _log.debug("TOOL invoke", fn="hass_list_entities", domain=domain)

    try:
        from backend.core.tools.hass_ops import hass_list_entities

        result = await hass_list_entities(domain)

        if result.success:
            data = result.data

            if domain:

                entities = data.get("entities", [])
                _log.info("TOOL ok", fn="hass_list_entities", domain=domain, res_len=len(entities))
                lines = [f"✓ {domain} entities ({len(entities)} found):"]

                for e in entities[:30]:
                    lines.append(f"  • {e['entity_id']}: {e['state']} ({e['friendly_name']})")

                if len(entities) > 30:
                    lines.append(f"  ... and {len(entities) - 30} more")

                return [TextContent(type="text", text="\n".join(lines))]
            else:

                domains = data.get("domains", {})
                total = data.get('total', 0)
                _log.info("TOOL ok", fn="hass_list_entities", total=total, domains=len(domains))
                lines = [f"✓ Home Assistant Domains ({total} total entities):"]

                for d, count in sorted(domains.items(), key=lambda x: -x[1]):
                    lines.append(f"  • {d}: {count} entities")

                return [TextContent(type="text", text="\n".join(lines))]
        else:
            _log.warning("TOOL partial", fn="hass_list_entities", err=result.error[:100] if result.error else None)
            return [TextContent(type="text", text=f"✗ {result.error}")]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_list_entities", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ List Error: {str(e)}")]


@register_tool(
    "hass_execute_scene",
    category="hass",
    description="""Execute a lighting scene - apply settings to multiple lights at once.

PREDEFINED SCENES:
- 'work': All lights on at 100%, neutral white
- 'relax': All lights at 40%, warm white
- 'night': All lights at 10%, warm orange
- 'off': All lights off

CUSTOM SCENE:
Pass lights array with per-light settings.""",
    input_schema={
        "type": "object",
        "properties": {
            "scene": {
                "type": "string",
                "description": "Predefined scene name: 'work', 'relax', 'night', 'off'",
                "enum": ["work", "relax", "night", "off"]
            },
            "custom_lights": {
                "type": "array",
                "description": "Custom scene: array of {entity_id, brightness, color}",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
                        "color": {"type": "string"}
                    },
                    "required": ["entity_id"]
                }
            }
        },
        "required": []
    }
)
async def hass_execute_scene_tool(arguments: dict[str, Any]) -> Sequence[TextContent]:
    """Execute a predefined or custom lighting scene.

    Args:
        arguments: Dict with scene name or custom_lights array

    Returns:
        TextContent with scene execution result
    """
    scene = arguments.get("scene")
    custom_lights = arguments.get("custom_lights", [])
    _log.debug("TOOL invoke", fn="hass_execute_scene", scene=scene, custom_cnt=len(custom_lights))

    if not scene and not custom_lights:
        _log.warning("TOOL fail", fn="hass_execute_scene", err="scene or custom_lights required")
        return [TextContent(type="text", text="Error: Either 'scene' or 'custom_lights' is required")]

    try:
        from backend.core.tools.hass_ops import hass_control_light

        # Predefined scenes
        SCENES = {
            "work": {"brightness": 100, "color": "white"},
            "relax": {"brightness": 40, "color": "warmwhite"},
            "night": {"brightness": 10, "color": "orange"},
            "off": {"action": "turn_off"},
        }

        results = []

        if scene:
            scene_config = SCENES.get(scene)
            if not scene_config:
                return [TextContent(type="text", text=f"Error: Unknown scene '{scene}'")]

            action = scene_config.get("action", "turn_on")
            result = await hass_control_light(
                entity_id="all",
                action=action,
                brightness=scene_config.get("brightness"),
                color=scene_config.get("color")
            )

            if result.success:
                _log.info("TOOL ok", fn="hass_execute_scene", scene=scene)
                return [TextContent(type="text", text=f"✓ Scene '{scene}' applied to all lights")]
            else:
                _log.warning("TOOL partial", fn="hass_execute_scene", err=result.error[:100] if result.error else None)
                return [TextContent(type="text", text=f"✗ Scene failed: {result.error}")]

        # Custom lights
        for light in custom_lights[:10]:  # Max 10 lights
            entity_id = light.get("entity_id")
            if not entity_id:
                continue

            result = await hass_control_light(
                entity_id=entity_id,
                action="turn_on",
                brightness=light.get("brightness"),
                color=light.get("color")
            )

            status = "✓" if result.success else "✗"
            results.append(f"{status} {entity_id}")

        _log.info("TOOL ok", fn="hass_execute_scene", custom_cnt=len(results))
        return [TextContent(type="text", text=f"Scene applied:\n" + "\n".join(results))]

    except Exception as e:
        _log.error("TOOL fail", fn="hass_execute_scene", err=str(e)[:100])
        return [TextContent(type="text", text=f"✗ Scene Error: {str(e)}")]
