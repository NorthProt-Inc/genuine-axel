# 13. 하드코딩된 IoT 디바이스 ID

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/core/tools/hass_ops.py`, `backend/core/mcp_tools/hass_tools.py`, `backend/core/mcp_tools/schemas.py`, `backend/config.py`, `backend/core/mcp_client.py`

## 요약

Home Assistant IoT 디바이스 ID가 `hass_ops.py`에 4개 딕셔너리/리스트(`LIGHTS`, `OTHER_DEVICES`, `SENSOR_ALIASES`, `SENSOR_GROUPS`)로 하드코딩되어 있으며, 동일 entity ID가 MCP 도구 스키마 설명, Pydantic 스키마 예시, Claude 커맨드 파일에 산발적으로 반복됩니다. 디바이스 추가/교체 시 최대 5개 파일을 수정해야 하는 구조이며, `warmwhite` 색상 참조 불일치 버그와 `get_all_states()` 필터링으로 인한 데이터 은닉 문제가 발견되었습니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **`get_all_states()`의 하드코딩 의존 필터링**: `get_all_states()`가 모든 HA 상태를 조회한 뒤 `known_entities`(하드코딩된 ID 합집합)에 포함된 것만 반환합니다 (`hass_ops.py:542-547`). 새 디바이스를 HA에 추가해도 `LIGHTS`, `OTHER_DEVICES`, `SENSOR_ALIASES` 중 하나에 수동으로 등록하지 않으면 이 함수의 결과에서 **영구적으로 은닉**됩니다. LLM이 이 함수로 "전체 상태"를 요청하면 불완전한 정보를 받게 됩니다.
  - 영향: 새 디바이스 추가 시 `get_all_states()`가 반환하는 "전체 상태"가 실제 전체가 아님. LLM 판단 오류 유발 가능.
  - 개선안:
    ```python
    # 옵션 1: 필터링 제거 (모든 상태 반환)
    async def get_all_states() -> HASSResult:
        result = await _hass_api_call("GET", "/api/states")
        if result.success and result.data:
            result.message = f"Retrieved {len(result.data)} entity states"
        return result

    # 옵션 2: 필터 선택적 적용
    async def get_all_states(known_only: bool = False) -> HASSResult:
        result = await _hass_api_call("GET", "/api/states")
        if result.success and result.data:
            if known_only:
                known = set(LIGHTS) | set(OTHER_DEVICES.values()) | set(SENSOR_ALIASES.values())
                result.data = [s for s in result.data if s.get("entity_id") in known]
            result.message = f"Retrieved {len(result.data)} entity states"
        return result
    ```

- **디바이스 레지스트리 부재로 인한 5-파일 샷건 수술**: 디바이스 entity ID가 다음 위치에 분산 하드코딩되어 있어 기기 변경 시 모든 위치를 찾아 수정해야 합니다:
  1. `backend/core/tools/hass_ops.py:15-84` — 4개 딕셔너리/리스트 (소스 오브 트루스)
  2. `backend/core/mcp_tools/hass_tools.py:15` — 스키마 description에 예시 ID
  3. `backend/core/mcp_tools/hass_tools.py:75` — 스키마 description에 예시 ID
  4. `backend/core/mcp_tools/schemas.py:93` — Pydantic 스키마에 예시 ID
  5. `.claude/commands/hass.md:40` — Claude 커맨드 파일에 예시 ID
  - 영향: 디바이스 교체 시 누락된 위치에서 이전 ID가 LLM에게 제안되어 존재하지 않는 디바이스 호출 시도 발생.
  - 개선안: YAML/JSON 설정 파일로 디바이스 레지스트리 분리:
    ```yaml
    # data/hass_devices.yaml
    lights:
      - entity_id: "light.wiz_rgbw_tunable_77d6a0"
        name: "Desk Light 1"
      - entity_id: "light.wiz_rgbw_tunable_77d8f6"
        name: "Desk Light 2"
      # ...

    other_devices:
      printer:
        entity_id: "sensor.brother_mfc_j5855dw"
      air_purifier:
        entity_id: "fan.vital_100s_series"

    sensor_aliases:
      iphone_battery: "sensor.iphone_battery_level"
      phone_battery: "sensor.iphone_battery_level"
      # ...

    sensor_groups:
      battery:
        - "sensor.iphone_battery_level"
      printer:
        - "sensor.mfc_j5855dw_status"
        # ...
    ```
    ```python
    # hass_ops.py에서 로드
    import yaml
    from backend.config import DATA_ROOT

    _DEVICE_CONFIG_PATH = DATA_ROOT / "hass_devices.yaml"

    def _load_device_config() -> dict:
        if _DEVICE_CONFIG_PATH.exists():
            with open(_DEVICE_CONFIG_PATH) as f:
                return yaml.safe_load(f)
        return {"lights": [], "other_devices": {}, "sensor_aliases": {}, "sensor_groups": {}}

    _config = _load_device_config()
    LIGHTS = [d["entity_id"] for d in _config.get("lights", [])]
    OTHER_DEVICES = {k: v["entity_id"] for k, v in _config.get("other_devices", {}).items()}
    SENSOR_ALIASES = _config.get("sensor_aliases", {})
    SENSOR_GROUPS = _config.get("sensor_groups", {})
    ```

### MEDIUM

- **`warmwhite` 색상 참조 불일치 (잠재적 버그)**: `hass_execute_scene_tool()`의 `relax` 씬이 `"warmwhite"` 색상을 사용하지만 (`hass_tools.py:361`), `COLOR_MAP`에 `"warmwhite"` 키가 존재하지 않습니다 (`hass_ops.py:29-52`). 유사한 키는 `"warm": [255, 200, 150]`뿐입니다. `parse_color("warmwhite")`는 이름 매칭, hex 매칭, HSL 매칭, RGB 매칭 모두 실패하여 `None`을 반환합니다. 결과적으로 `relax` 씬 실행 시 색상이 적용되지 않고 brightness만 변경됩니다.
  - 개선안: `COLOR_MAP`에 `"warmwhite"` 추가하거나, 씬의 색상을 `"warm"`으로 변경:
    ```python
    # 옵션 1: COLOR_MAP에 추가
    COLOR_MAP = {
        ...
        "warmwhite": [255, 200, 150],
        "warm white": [255, 200, 150],
    }

    # 옵션 2: 씬 정의 수정
    SCENES = {
        "relax": {"brightness": 40, "color": "warm"},
        ...
    }
    ```

- **`SENSOR_GROUPS`의 entity ID 중복**: `SENSOR_GROUPS["printer"]`와 `SENSOR_GROUPS["printer_ink_all"]`이 잉크 센서 4개를 공유하면서 별도 리스트로 하드코딩되어 있습니다 (`hass_ops.py:68-84`). `printer_ink_all`의 센서가 `printer`의 부분집합이므로, 한쪽만 업데이트하면 불일치가 발생합니다.
  - 개선안:
    ```python
    _PRINTER_INK_SENSORS = [
        "sensor.mfc_j5855dw_black_ink_remaining",
        "sensor.mfc_j5855dw_cyan_ink_remaining",
        "sensor.mfc_j5855dw_magenta_ink_remaining",
        "sensor.mfc_j5855dw_yellow_ink_remaining",
    ]

    SENSOR_GROUPS = {
        "battery": ["sensor.iphone_battery_level"],
        "printer_ink_all": _PRINTER_INK_SENSORS,
        "printer": [
            "sensor.mfc_j5855dw_status",
            *_PRINTER_INK_SENSORS,
            "sensor.mfc_j5855dw_page_counter",
        ],
    }
    ```

- **`hass_ops.py` 내 `HASS_TIMEOUT` 이중 정의**: `hass_ops.py:92`에 `HASS_TIMEOUT = 10.0`이 모듈 레벨 상수로 정의되어 있지만, 실제 런타임에서는 `_get_hass_config()`를 통해 `backend.config.HASS_TIMEOUT`을 가져옵니다 (`hass_ops.py:86-89,156`). 모듈 레벨 `HASS_TIMEOUT`은 사용되지 않는 dead code입니다. 마찬가지로 `MAX_RETRIES = 2` (`hass_ops.py:93`)도 사용되지 않습니다.
  - 개선안: `hass_ops.py:91-93` 삭제.

- **HA API에서 동적 디바이스 검색 가능하나 미활용**: `hass_list_entities()`가 이미 HA API의 `/api/states`를 호출하여 모든 entity를 조회할 수 있습니다 (`hass_ops.py:555-596`). 이를 활용하여 `LIGHTS` 리스트를 자동 생성할 수 있음에도, 하드코딩된 리스트에 의존하고 있습니다.
  - 개선안: 시작 시 또는 주기적으로 HA API에서 `light.wiz_*` 패턴의 entity를 자동 검색:
    ```python
    async def discover_wiz_lights() -> list[str]:
        result = await hass_list_entities("light")
        if result.success:
            entities = result.data.get("entities", [])
            return [
                e["entity_id"] for e in entities
                if e["entity_id"].startswith("light.wiz_")
            ]
        return LIGHTS  # fallback to hardcoded
    ```

### LOW

- **MCP 도구 스키마에 특정 entity ID 노출**: `hass_tools.py:15`의 스키마 description에 `light.wiz_rgbw_tunable_77d6a0`이라는 특정 MAC 주소 기반 ID가 예시로 노출됩니다. 디바이스 교체 시 이 예시가 무효화되어 LLM이 존재하지 않는 ID를 사용할 수 있습니다.
  - 개선안: 일반적 예시로 변경:
    ```python
    "entity_id": {"type": "string", "description": "Light entity (e.g., 'all' for all lights, or specific entity_id from hass_list_entities)"}
    ```

- **`list_available_devices()` 미등록 MCP 도구**: `hass_ops.py:521-533`에 `list_available_devices()`가 정의되어 있으나, MCP 도구로 등록되어 있지 않습니다 (`hass_tools.py`에 `@register_tool` 없음). `__init__.py`에는 export되어 있지만 (`backend/core/tools/__init__.py:29`에는 없음), 실제 호출 경로가 없는 dead code입니다.

- **`hass_control_light()`은 `hass_control_device()`의 단순 래퍼**: `hass_control_light()` (`hass_ops.py:350-357`)는 `hass_control_device()`를 직접 호출하는 1줄 함수입니다. 별도 도구(`hass_control_light` vs `hass_control_device`)로 MCP에 등록되어 있어 유지보수 부담이 늘어나지만, LLM의 도구 선택 편의를 위한 의도적 설계일 수 있습니다.

## 개선 제안

### 핵심 방향: YAML 기반 디바이스 레지스트리 분리

현재 하드코딩된 IoT 디바이스 설정을 `data/hass_devices.yaml`로 분리하는 것이 가장 효과적입니다. 이 접근의 장점:

1. **코드 변경 없이 디바이스 추가/제거**: YAML 파일만 편집하면 됨
2. **단일 소스 오브 트루스**: 5개 파일에 흩어진 entity ID를 하나로 통합
3. **기존 패턴 활용**: `config.py`에 이미 `DATA_ROOT` 경로와 환경 변수 패턴이 확립되어 있음
4. **점진적 적용 가능**: YAML 파일이 없으면 현재 하드코딩된 값을 fallback으로 사용

### 부가 개선

- `warmwhite` 버그를 즉시 수정 (5초 작업)
- `get_all_states()` 필터링 제거 또는 선택적 적용
- dead code(`HASS_TIMEOUT`, `MAX_RETRIES`, `list_available_devices()`) 정리
- `SENSOR_GROUPS`의 잉크 센서 중복 제거

### 장기적으로 고려

디바이스 자동 검색(auto-discovery)은 시작 시 HA API를 호출해야 하므로 HA가 다운된 경우 앱 시작 실패 위험이 있습니다. YAML 기반 정적 설정 + 수동 업데이트가 이 시스템 규모에서는 더 적합합니다.

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `warmwhite` 색상 불일치 수정 | ⭐ 쉬움 | COLOR_MAP에 키 1개 추가 또는 씬 값 변경 |
| dead code 정리 (HASS_TIMEOUT, MAX_RETRIES) | ⭐ 쉬움 | 2줄 삭제 |
| SENSOR_GROUPS 중복 제거 | ⭐ 쉬움 | 공유 리스트 추출 |
| MCP 스키마 예시 일반화 | ⭐ 쉬움 | description 문자열 변경 |
| `get_all_states()` 필터링 개선 | ⭐⭐ 보통 | 함수 시그니처 변경 + 호출자 확인 |
| YAML 디바이스 레지스트리 분리 | ⭐⭐ 보통 | YAML 파일 생성 + 로더 구현 + 기존 상수 교체 |
| `list_available_devices()` dead code 판단 | ⭐ 쉬움 | 호출자 확인 후 삭제 또는 MCP 등록 |
