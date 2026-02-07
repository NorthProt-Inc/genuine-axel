---
description: 조명/기기 빠른 제어
argument-hint: <device> <action> [value]
allowed-tools: [mcp__axel-mcp__hass_control_light, mcp__axel-mcp__hass_control_device, mcp__axel-mcp__hass_list_entities, mcp__axel-mcp__hass_get_state]
---

# /hass - Home Assistant 빠른 제어

## 사용법
- `/hass light on` - 모든 조명 켜기
- `/hass light off` - 모든 조명 끄기
- `/hass light on 80` - 조명 80% 밝기로 켜기
- `/hass light red` - 조명 빨간색으로
- `/hass fan on` - 공기청정기 켜기
- `/hass fan off` - 공기청정기 끄기
- `/hass status` - 전체 상태 확인
- `/hass list` - 사용 가능한 기기 목록

## 인자: $ARGUMENTS
- device: `light`, `fan`, `all`, `status`, `list`
- action: `on`, `off`
- value: 밝기(0-100) 또는 색상(red, blue, #FF0000 등)

## 동작

### light on [밝기] [색상]
MCP 도구 `mcp__axel-mcp__hass_control_light` 사용:
- entity_id: "all" (모든 조명)
- action: "turn_on"
- brightness: 지정된 값 또는 100
- color: 지정된 색상 (선택)

### light off
MCP 도구 `mcp__axel-mcp__hass_control_light` 사용:
- entity_id: "all"
- action: "turn_off"

### fan on/off
MCP 도구 `mcp__axel-mcp__hass_control_device` 사용:
- entity_id: air purifier entity (from hass_list_entities)
- action: "turn_on" 또는 "turn_off"

### status
MCP 도구 `mcp__axel-mcp__hass_list_entities` 사용:
- domain 없이 호출하여 전체 요약

### list
MCP 도구 `mcp__axel-mcp__hass_list_entities` 사용:
- domain: "light" 및 "fan" 순차 호출

## 색상 지원
- 이름: red, blue, green, yellow, purple, orange, white, warm, cool
- Hex: #FF0000, #00FF00, #0000FF 등
- HSL: hsl(240,100,50)

## 출력 형식
```
✅ 조명 켜짐 (밝기: 80%, 색상: warm white)
```
또는
```
## Home Assistant 상태

### 조명
| 이름 | 상태 | 밝기 |
|------|------|------|
| WiZ RGB | on | 80% |

### 기기
| 이름 | 상태 |
|------|------|
| 공기청정기 | off |
```

## 관련 명령어
- 없음 (독립 기능)
