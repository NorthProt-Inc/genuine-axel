# 03. mcp_server.py 거대 모놀리스

> 분석 날짜: 2026-02-04
> 분석 범위: `backend/core/mcp_server.py` (987줄), `backend/core/mcp_tools/__init__.py`, `backend/core/mcp_tools/system_tools.py`, `backend/core/mcp_tools/file_tools.py`, `backend/core/mcp_tools/hass_tools.py`, `backend/core/mcp_tools/memory_tools.py`, `backend/core/mcp_tools/research_tools.py`, `backend/core/mcp_tools/opus_tools.py`, `backend/core/mcp_tools/schemas.py`, `backend/core/mcp_client.py`

## 요약

`mcp_server.py`는 987줄의 모놀리스로, **25개 도구의 JSON Schema 정의(610줄)**, **도구 디스패치 로직**, **SSE 전송 계층**, **FastAPI 앱 설정**이 단일 파일에 혼재합니다. 이미 `mcp_tools/` 디렉토리에 핸들러 레지스트리가 구현되어 있으나, `mcp_server.py`의 `list_tools()`에 남아있는 610줄의 스키마 정의가 `mcp_tools/` 각 모듈의 `register_tool()`에 전달된 `input_schema`와 **완전 중복**됩니다. 또한 SSE 핸들러가 `handle_sse`와 `_handle_sse_raw`로 거의 동일한 코드가 이중 존재합니다.

## 발견사항

### CRITICAL

- 해당 사항 없음

### HIGH

- **도구 스키마 610줄 완전 중복**: `mcp_server.py:148-758`의 `list_tools()`에 25개 도구의 JSON Schema가 수동으로 정의되어 있으나, 동일한 스키마가 `mcp_tools/` 하위 모듈들의 `register_tool()` 데코레이터에도 `input_schema` 파라미터로 중복 정의되어 있습니다. (`backend/core/mcp_server.py:148-758` vs `backend/core/mcp_tools/system_tools.py:11-37`, `backend/core/mcp_tools/hass_tools.py:8-34`, `backend/core/mcp_tools/research_tools.py:8-26`, `backend/core/mcp_tools/memory_tools.py:21-31` 등)
  - 영향: 도구 추가/수정 시 **두 곳을 동시에 수정**해야 하며, 한쪽만 수정하면 스키마 불일치가 발생합니다. 예를 들어 `mcp_tools/system_tools.py:34`의 `run_command`는 `timeout` 기본값이 120초이지만, `mcp_server.py:205`에서는 180초로 정의되어 **이미 불일치가 존재합니다**. 또한 `mcp_tools/hass_tools.py`에는 `hass_execute_scene`과 `memory_stats` 도구가 등록되어 있으나, `mcp_server.py:list_tools()`에는 이들이 **누락**되어 있습니다.
  - 개선안: `list_tools()`를 레지스트리 기반으로 전환합니다:
    ```python
    # mcp_server.py — list_tools()를 610줄에서 5줄로 축소
    @mcp_server.list_tools()
    async def list_tools() -> list[Tool]:
        from backend.core.mcp_tools import get_tool_schemas
        return get_tool_schemas()
    ```
    `get_tool_schemas()`는 이미 `mcp_tools/__init__.py:137-157`에 구현되어 있으므로, `mcp_server.py`의 수동 스키마 정의 610줄을 완전히 제거할 수 있습니다.

- **SSE 핸들러 코드 이중화**: `handle_sse()` (`mcp_server.py:872-898`)와 `_handle_sse_raw()` (`mcp_server.py:904-929`)가 거의 동일한 로직을 중복 구현합니다. 두 함수 모두 `sse_transport._sse.connect_sse()`를 호출하고 `mcp_server.run()`을 실행하며, 예외 처리와 connection 관리도 동일합니다.
  - 영향: `handle_sse()`는 **어디에서도 호출되지 않는 dead code**입니다. 라우트 설정(`mcp_server.py:941-944`)에서는 `_handle_sse_raw`만 사용합니다. SSE 관련 버그 수정 시 어느 함수를 수정해야 하는지 혼란을 유발합니다.
  - 개선안: 사용되지 않는 `handle_sse()`를 삭제합니다:
    ```python
    # 삭제 대상: mcp_server.py:872-898 전체 (handle_sse 함수)
    # _handle_sse_raw만 유지
    ```

- **세 레이어 분리 부재 (스키마/디스패치/전송)**: 현재 `mcp_server.py`는 (1) 도구 스키마 정의, (2) `call_tool` 디스패치, (3) SSE/stdio 전송 계층, (4) FastAPI 앱 설정이 하나의 파일에 있어, 변경 사유가 다른 코드가 혼재합니다.
  - 영향: 도구 추가(스키마 변경)와 SSE 프로토콜 수정(전송 변경)이 동일 파일을 건드려 **샷건 수술** 발생. 987줄의 단일 파일은 코드 리뷰와 diff 추적이 어렵습니다.
  - 개선안: 3개 모듈로 분리:
    ```
    backend/core/
    ├── mcp_server.py         → MCP Server 초기화 + call_tool (100줄 이내)
    ├── mcp_transport.py      → SSE/stdio 전송 계층 (~150줄)
    └── mcp_tools/
        └── __init__.py       → 도구 레지스트리 (이미 존재)
    ```

### MEDIUM

- **`import os` 중복**: `mcp_server.py:2`와 `mcp_server.py:11`에서 `import os`가 두 번 선언됩니다.
  - 개선안: `mcp_server.py:11`의 중복 `import os` 삭제

- **`import sys` 중복 및 불필요한 sys.path 조작**: `mcp_server.py:1`과 `mcp_server.py:87`에서 `import sys`가 중복되며, `sys.path` 조작이 3곳(`mcp_server.py:4-5`, `mcp_server.py:41-42`, `mcp_server.py:88`)에서 반복됩니다.
  - 영향: 코드 로드 순서에 대한 암묵적 의존성을 생성하고, 어떤 `sys.path` 조작이 실제로 필요한지 판단하기 어렵습니다.
  - 개선안: `sys.path` 조작을 파일 최상단 한 곳으로 통합:
    ```python
    import sys
    import os
    from pathlib import Path

    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    ```

- **`MCPSSETransport` 클래스 미사용**: `mcp_server.py:815-848`의 `MCPSSETransport` 클래스와 `connect_sse_with_keepalive()` 메서드가 정의되어 있고, `sse_transport` 인스턴스가 `mcp_server.py:849`에서 생성됩니다. 그러나 실제 SSE 핸들러(`_handle_sse_raw`)는 `sse_transport._sse`에 직접 접근하여 내부 `SseServerTransport`를 사용하므로, `MCPSSETransport`의 래핑 메서드 `connect_sse_with_keepalive()`와 `handle_post_message()`는 **사용되지 않습니다**.
  - 영향: dead code로 인한 유지보수 부담. 래핑 클래스의 의도(keepalive 등)가 실현되지 않음.
  - 개선안: `MCPSSETransport` 클래스를 삭제하고 `SseServerTransport`를 직접 사용:
    ```python
    sse_transport = SseServerTransport("/messages")
    ```

- **`_send_heartbeat` 함수 미사용**: `mcp_server.py:862-870`의 heartbeat 함수가 정의되어 있으나 어디에서도 호출되지 않습니다.
  - 영향: SSE keepalive를 의도했으나 구현이 완료되지 않은 상태. `SSE_KEEPALIVE_INTERVAL` 상수도 이 함수에서만 참조.
  - 개선안: `_send_heartbeat` 삭제 또는 SSE 핸들러에 통합

- **`read_file_safe` 동기 I/O**: `mcp_server.py:55-61`의 `read_file_safe()`는 `async` 함수로 선언되었으나 내부에서 `path.read_text()` 동기 I/O를 사용합니다. 비동기 이벤트 루프를 블로킹할 수 있습니다.
  - 영향: 대용량 파일 읽기 시 이벤트 루프 블로킹 가능
  - 개선안:
    ```python
    async def read_file_safe(path: Path) -> str:
        if not path.exists():
            return f"Error: File not found at {path}"
        try:
            return await asyncio.to_thread(path.read_text, encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {str(e)}"
    ```

- **스키마 불일치 — `run_command` timeout 기본값**: `mcp_server.py:205`에서 timeout 기본값이 180으로 정의되어 있으나, `mcp_tools/system_tools.py:34`의 `input_schema`에서는 120으로 정의됩니다. `call_tool` 디스패치는 레지스트리(`mcp_tools`)를 통해 핸들러를 실행하므로, 실제 동작은 `system_tools.py:43`의 `arguments.get("timeout", 120)`에 의해 120초가 적용되지만, MCP 클라이언트에게 노출되는 스키마는 `list_tools()`의 180초입니다.
  - 영향: 클라이언트가 180초로 기대하지만 실제 120초에 타임아웃 발생. 디버깅이 어려운 동작 불일치.
  - 개선안: `list_tools()`를 레지스트리 기반으로 전환하면 자동 해결

- **mcp_server.py 상단 import에서 사용되지 않는 import들**: `mcp_server.py:90-143`에서 `system_observer`, `hass_ops`, `research_server`, `research_artifacts`, `memory_server`, `opus_executor`, `google_research`, `async_research` 등을 직접 import하고 있으나, `call_tool()` 디스패치가 레지스트리 기반(`is_tool_registered` → `get_tool_handler`)으로 전환된 이후 이 import들은 **사용되지 않습니다**.
  - 영향: 불필요한 모듈 로드로 인한 시작 시간 증가, 순환 의존성 위험
  - 개선안: `mcp_server.py:84-143`의 60줄에 달하는 미사용 import 블록 전체 삭제

- **`active_connections` 전역 가변 상태**: `mcp_server.py:813`의 `active_connections: set = set()`가 모듈 레벨 전역 변수로 connection 추적에 사용됩니다. `handle_sse`와 `_handle_sse_raw` 양쪽에서 모두 `add`/`discard`를 수행하므로, dead code(`handle_sse`)가 실행되면 중복 추적이 발생합니다.
  - 개선안: `active_connections`를 전송 계층 클래스의 인스턴스 변수로 캡슐화

- **Pydantic 스키마(`schemas.py`) 미활용**: `mcp_tools/schemas.py`에 13개 Pydantic 모델과 `validate_input()` 헬퍼가 정의되어 있으나, 실제 도구 핸들러에서는 `arguments.get()` 방식의 수동 검증만 사용합니다. Pydantic 스키마가 어디에서도 import되지 않습니다.
  - 영향: 타입 안전한 검증 인프라가 존재하지만 활용되지 않아 dead code. 수동 검증 코드가 각 핸들러에 반복됨.
  - 개선안: 각 핸들러에서 `validate_input()`을 사용하도록 통합:
    ```python
    # system_tools.py의 run_command 예시
    from .schemas import RunCommandInput, validate_input

    async def run_command(arguments: dict[str, Any]) -> Sequence[TextContent]:
        ok, result = validate_input(RunCommandInput, arguments)
        if not ok:
            return [TextContent(type="text", text=result)]
        # result는 이제 검증된 RunCommandInput 인스턴스
        command = result.command
        cwd = result.cwd or str(AXEL_ROOT)
        timeout = result.timeout
        ...
    ```

### LOW

- **`except Exception: pass` (예외 삼킴)**: `mcp_server.py:3-7`에서 `sys.path` 정리 실패를 무시합니다. 최소한 debug 로그를 남겨야 합니다.
  - 개선안: `except Exception as e: _log.debug("sys.path cleanup failed", err=str(e))`

- **매직 넘버 `300.0`**: `mcp_server.py:788`의 `timeout=300.0`(도구 실행 타임아웃 5분)이 하드코딩되어 있습니다. `SSE_KEEPALIVE_INTERVAL`처럼 상수로 추출해야 합니다.
  - 개선안: `TOOL_EXECUTION_TIMEOUT = 300` 상수 정의

- **불필요한 `import asyncio` 중복**: `mcp_server.py:8`에서 최상위에 `import asyncio`가 있고, `call_tool()` 내부 `mcp_server.py:771`에서 다시 `import asyncio`를 수행합니다.
  - 개선안: `mcp_server.py:771` 삭제

## 개선 제안

### 1단계: 즉시 가능한 정리 (코드 삭제만으로 ~200줄 감소)
1. **미사용 `handle_sse()` 삭제** (27줄): `mcp_server.py:872-898`
2. **미사용 `MCPSSETransport` 클래스 삭제** (34줄): `mcp_server.py:815-848`
3. **미사용 `_send_heartbeat()` 삭제** (9줄): `mcp_server.py:862-870`
4. **미사용 import 블록 삭제** (60줄): `mcp_server.py:84-143`
5. **중복 `import os`, `import sys`, `import asyncio` 정리** (3줄)

### 2단계: 스키마 통합 (610줄 → 5줄)
1. `list_tools()`를 `get_tool_schemas()` 호출로 교체
2. `mcp_tools/` 각 모듈의 `register_tool()` 스키마가 Single Source of Truth가 됨
3. 이로써 `mcp_server.py`가 987줄 → ~170줄로 축소

### 3단계: 파일 분리
1. SSE/stdio 전송 계층을 `mcp_transport.py`로 분리
2. FastAPI 앱 설정을 전송 모듈에 포함
3. `mcp_server.py`는 MCP Server 인스턴스 생성, 핸들러 등록, 리소스 관리만 담당 (~80줄)

### 4단계: Pydantic 스키마 활용
1. `schemas.py`의 Pydantic 모델을 각 핸들러에 적용
2. 수동 검증 코드 제거로 각 핸들러 10~20줄 축소
3. `register_tool()` 데코레이터에서 Pydantic 모델로부터 JSON Schema 자동 생성 (`model.model_json_schema()`)

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| 미사용 코드 삭제 (handle_sse, MCPSSETransport, _send_heartbeat, imports) | 쉬움 | 호출부 없으므로 삭제만으로 완료. 외부 영향 없음 |
| list_tools() 레지스트리 전환 | 쉬움 | `get_tool_schemas()` 이미 구현됨. 5줄 교체. 단, 스키마 동기화 확인 필요 |
| 중복 import 정리 | 쉬움 | 린터 자동화 가능 |
| SSE 전송 계층 분리 | 보통 | SSE 연결 관리, FastAPI 마운트 로직 이동. 기능적 변경은 아님 |
| Pydantic 스키마 통합 | 보통 | 각 핸들러마다 수정 필요. 13개 모델 × 핸들러 매핑. 테스트 부재로 회귀 위험 |
| `read_file_safe` 비동기화 | 쉬움 | `asyncio.to_thread` 래핑 1줄 변경 |
