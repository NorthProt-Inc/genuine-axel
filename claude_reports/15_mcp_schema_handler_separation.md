# 15. MCP 도구 스키마-핸들러 분리 부재

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/core/mcp_tools/__init__.py`, `backend/core/mcp_tools/schemas.py`, `backend/core/mcp_tools/memory_tools.py`, `backend/core/mcp_tools/file_tools.py`, `backend/core/mcp_tools/system_tools.py`, `backend/core/mcp_tools/hass_tools.py`, `backend/core/mcp_tools/opus_tools.py`, `backend/core/mcp_tools/research_tools.py`, `backend/core/tools/opus_executor.py`, `backend/core/mcp_server.py`, `backend/core/mcp_client.py`

## 요약

MCP 도구의 스키마(input_schema)가 **3곳에 독립적으로 정의**되어 있어 동기화 불일치가 이미 발생하고 있습니다. 350줄의 `schemas.py` Pydantic 모델은 완전한 dead code이며, 각 핸들러 함수 내부에서 수동 검증 로직이 중복 구현되어 있습니다. `register_tool` 데코레이터 패턴은 잘 설계되어 있으나, 스키마 정의와 검증이 통합되지 않아 설계 의도가 반감되고 있습니다.

## 발견사항

### CRITICAL

없음

### HIGH

- **schemas.py 350줄 완전 dead code**: `schemas.py`의 13개 Pydantic 모델(`HassControlLightInput`, `StoreMemoryInput`, `WebSearchInput` 등)과 `validate_input()` 함수가 프로젝트 전체에서 **단 한 곳도 import/사용되지 않음** (`backend/core/mcp_tools/schemas.py:1-350`)
  - 영향: 350줄의 유지보수 부담, Pydantic 검증 기능(타입 변환, 범위 검증, 커스텀 validator)이 완전히 활용되지 않음. 개발자가 schemas.py를 수정해도 실제 동작에 전혀 영향 없어 혼란 유발
  - 개선안: schemas.py의 Pydantic 모델을 각 핸들러에서 활용하거나, dead code로 삭제

    ```python
    # 방법 1: 핸들러에서 Pydantic 검증 활용
    from backend.core.mcp_tools.schemas import StoreMemoryInput, validate_input

    @register_tool("store_memory", category="memory", ...)
    async def store_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
        ok, result = validate_input(StoreMemoryInput, arguments)
        if not ok:
            return [TextContent(type="text", text=result)]
        # result는 이제 검증된 StoreMemoryInput 인스턴스
        content = result.content
        category = result.category.value
        importance = result.importance
        ...
    ```

    ```python
    # 방법 2 (권장): Pydantic 모델에서 input_schema를 자동 생성
    from backend.core.mcp_tools.schemas import StoreMemoryInput

    @register_tool(
        "store_memory",
        category="memory",
        description="Store to long-term memory",
        input_schema=StoreMemoryInput.model_json_schema(),  # 자동 생성!
    )
    async def store_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
        validated = StoreMemoryInput(**arguments)  # Pydantic 검증
        ...
    ```

- **`delegate_to_opus` 스키마 3중 정의 및 불일치**: 동일 도구의 스키마가 3곳에 존재하며 내용이 불일치
  - 영향: 어느 스키마가 실제로 사용되는지 혼란, LLM이 잘못된 스키마를 참조하면 런타임 에러
  - 불일치 상세:

    | 속성 | `opus_tools.py:12-31` (실사용) | `opus_executor.py:404-425` (미사용) | `schemas.py:312-326` (미사용) |
    |------|------|------|------|
    | `file_paths` type | `string` (comma-separated) | `array` of strings | `string` (optional) |
    | `model` enum | `["opus", "sonnet", "haiku"]` | `["opus", "sonnet"]` (haiku 불가) | `["opus", "sonnet", "haiku"]` |
    | `description` | 12자 간략 | 400자+ 상세 | 50자 중간 |

  - 개선안: 하나의 정의만 유지하고 나머지 삭제

    ```python
    # opus_tools.py에서만 정의 (Single Source of Truth)
    @register_tool(
        "delegate_to_opus",
        category="delegation",
        description="...",
        input_schema={
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "..."},
                "file_paths": {
                    "type": "array",  # 통일: array 타입
                    "items": {"type": "string"},
                    "description": "File paths relative to project root"
                },
                "model": {
                    "type": "string",
                    "enum": ["opus", "sonnet", "haiku"],  # 통일
                }
            },
            "required": ["instruction"]
        }
    )
    ```

    그리고 `opus_executor.py:370-426`의 `get_mcp_tool_definition()` 함수를 삭제

### MEDIUM

- **핸들러 내 수동 검증 중복**: 32개 핸들러 함수 각각에서 파라미터 존재 여부, 타입, 범위를 수동으로 검증하는 보일러플레이트 코드가 반복됨
  - 예: `memory_tools.py:38,88,166-180,238-244,295-297`, `system_tools.py:53-55,57-59,138-144,258-260,364-367`, `hass_tools.py:38-40,42-45,94-100,149-151`, `research_tools.py:41-47,97-103,140-141,178-193`, `file_tools.py:29-31,90-91,148-150`
  - 패턴:
    ```python
    # 모든 핸들러에 반복되는 패턴 (~5줄 × 32 = ~160줄 중복)
    query = arguments.get("query", "")
    if not query:
        return [TextContent(type="text", text="Error: query parameter is required")]
    ```
  - 개선안: `register_tool` 데코레이터에 Pydantic 검증 통합

    ```python
    def register_tool(name, *, input_schema=None, pydantic_model=None, ...):
        def decorator(func):
            @wraps(func)
            async def wrapper(arguments):
                # 자동 검증
                if pydantic_model:
                    try:
                        validated = pydantic_model(**arguments)
                        return await func(validated)
                    except ValidationError as e:
                        return [TextContent(type="text", text=f"Validation Error: {e}")]
                return await func(arguments)
            ...
        return decorator
    ```

- **`timeout` 기본값 불일치**: `run_command`의 `timeout` 기본값이 input_schema에서는 `180` (`system_tools.py:34`)이지만 핸들러 코드에서는 `120` (`system_tools.py:50`)으로 다름
  - `system_tools.py:34`: `"default": 180`
  - `system_tools.py:50`: `timeout = arguments.get("timeout", 120)`
  - 개선안: 한 곳에서만 기본값 정의

    ```python
    DEFAULT_TIMEOUT = 180
    # schema에서 "default": DEFAULT_TIMEOUT
    # 핸들러에서 arguments.get("timeout", DEFAULT_TIMEOUT)
    ```

- **`get_mcp_tool_definition()` dead code**: `opus_executor.py:370-426`의 57줄 함수가 `__init__.py`에서 export되지만 실제 호출처 없음 (`backend/core/tools/__init__.py:38`에서 alias만 존재)
  - `backend/core/tools/opus_executor.py:370-426`
  - `backend/core/tools/__init__.py:38`: `get_mcp_tool_definition as get_opus_tool_definition`
  - 개선안: 삭제 (실제 스키마는 `opus_tools.py`의 `register_tool` 데코레이터로 관리)

- **`_read_file_safe` 중복**: `mcp_server.py:70-77`과 `memory_tools.py:12-19`에 동일 함수가 중복 정의됨. 미세한 차이: mcp_server.py는 `asyncio.to_thread`로 async 래핑, memory_tools.py는 sync `path.read_text()` 직접 호출
  - `backend/core/mcp_server.py:70-77`
  - `backend/core/mcp_tools/memory_tools.py:12-19`
  - 개선안: 공통 유틸리티로 통합하거나, memory_tools.py에서도 `asyncio.to_thread` 사용

- **`add_memory`와 `store_memory`의 category enum 불일치**: 같은 "메모리 저장" 기능이지만 허용 카테고리가 다름
  - `add_memory` (`memory_tools.py:92`): `["observation", "fact", "code"]`
  - `store_memory` (`memory_tools.py:153,170`): `["fact", "preference", "conversation", "insight"]`
  - `schemas.py` `MemoryCategory` (`schemas.py:28-33`): `["fact", "preference", "conversation", "insight"]`
  - `schemas.py` `AddMemoryInput` (`schemas.py:159-163`): `["observation", "fact", "code"]`
  - 영향: 각 도구의 목적이 다르므로 의도적 차이일 수 있으나, 두 도구 모두 working memory에 저장하는 기능으로 혼동 유발

### LOW

- **`input_schema` dict 리터럴 산재**: 32개 도구의 JSON Schema가 각 `_tools.py` 파일에 인라인 dict로 흩어져 있어, 스키마 규격 변경(예: 전체 도구에 `additionalProperties: false` 추가) 시 32곳을 수동 수정해야 함
  - `memory_tools.py` 6개, `hass_tools.py` 6개, `system_tools.py` 9개, `opus_tools.py` 2개, `file_tools.py` 3개, `research_tools.py` 6개 = **총 32개 인라인 스키마**
  - 개선안: Pydantic `model_json_schema()` 활용으로 자동 생성

- **`hass_execute_scene`의 SCENES dict 중복**: `hass_tools.py:359-364`의 predefined scenes 정의가 `hass_ops.py`의 scene 로직과 별도로 관리됨
  - `backend/core/mcp_tools/hass_tools.py:359-364`

## 개선 제안

### 1단계: Dead code 정리 (즉시)
- `schemas.py`의 Pydantic 모델 중 사용되지 않는 것들을 삭제하거나, 2단계에서 활용할 준비
- `opus_executor.py:370-426`의 `get_mcp_tool_definition()` 삭제
- `backend/core/tools/__init__.py:38`의 alias 삭제

### 2단계: 스키마 자동 생성 (중기)
Pydantic 모델에서 JSON Schema를 자동 생성하는 패턴으로 전환:

```python
# schemas.py에 정의
class StoreMemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    category: MemoryCategory = Field(default=MemoryCategory.CONVERSATION)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)

# memory_tools.py에서 활용
@register_tool(
    "store_memory",
    category="memory",
    description="Store to long-term memory",
    input_schema=StoreMemoryInput.model_json_schema(),
)
async def store_memory(arguments: dict[str, Any]) -> Sequence[TextContent]:
    validated = StoreMemoryInput(**arguments)
    # 수동 검증 코드 불필요
    ...
```

이렇게 하면:
- 스키마와 검증이 **한 곳(Pydantic 모델)**에서 관리됨
- `register_tool` 데코레이터의 `input_schema`가 자동 생성됨
- 핸들러 내 수동 검증 보일러플레이트 ~160줄 제거 가능
- 타입 안전성 향상 (Pydantic의 자동 타입 변환, 범위 검증, 커스텀 validator)

### 3단계: 자동 검증 통합 (중기)
`register_tool` 데코레이터에 Pydantic 모델을 전달하여 자동 검증 + 에러 포맷팅:

```python
def register_tool(name, *, pydantic_model=None, ...):
    def decorator(func):
        # input_schema 자동 생성
        schema = pydantic_model.model_json_schema() if pydantic_model else input_schema

        @wraps(func)
        async def wrapper(arguments):
            if pydantic_model:
                try:
                    validated = pydantic_model(**arguments)
                    return await func(validated)
                except ValidationError as e:
                    return [TextContent(type="text", text=f"Validation Error: {e}")]
            return await func(arguments)
        ...
    return decorator
```

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `schemas.py` dead code 삭제 | 쉬움 | 단순 파일 삭제, 사용처 없음 |
| `get_mcp_tool_definition()` dead code 삭제 | 쉬움 | 함수 삭제 + `__init__.py` alias 삭제 |
| `delegate_to_opus` 스키마 통일 | 쉬움 | `opus_tools.py`의 스키마만 유지, `file_paths`를 `array`로 통일 |
| `timeout` 기본값 통일 | 쉬움 | 상수 하나로 통일 |
| `_read_file_safe` 중복 제거 | 쉬움 | 한 곳에서 import |
| Pydantic `model_json_schema()` 활용 | 보통 | schemas.py 모델이 이미 존재하므로 연결만 필요. 단, 32개 핸들러 수정 필요 |
| `register_tool` 자동 검증 통합 | 보통 | 데코레이터 수정 + 핸들러 시그니처 변경(dict → Pydantic model) |
| 수동 검증 보일러플레이트 제거 | 보통 | 자동 검증 통합 후 32개 핸들러에서 수동 검증 코드 제거 |
