# 18. MCPClient 이중 호출 방식

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/core/mcp_client.py`, `backend/core/mcp_server.py`, `backend/protocols/mcp/server.py`, `backend/api/mcp.py`, `backend/core/services/tool_service.py`, `backend/config.py`

## 요약

`MCPClient`는 MCP 도구 호출 시 **직접 import**(in-process)와 **HTTP 폴백**이라는 두 가지 전송 경로를 하나의 클래스에 혼합하고 있으며, HTTP 폴백 경로는 완전히 다른 MCP 서버 구현(`protocols/mcp/server.py`)을 통해 실행되어 **의미적으로 동등하지 않은 두 경로**가 공존합니다. 추가로 `get_gemini_tools()`와 `get_anthropic_tools()`의 도구 우선순위/캐싱 로직이 거의 동일하게 중복되어 있으며, `CORE_TOOLS` 리스트가 하드코딩되어 도구 변경 시 샷건 수술을 유발합니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **직접 호출과 HTTP 폴백이 다른 MCP 서버를 경유**: (`backend/core/mcp_client.py:58-60`, `backend/core/mcp_client.py:134-139`)
  - **직접 경로**: `from backend.core.mcp_server import call_tool` → `mcp_server.py`의 `call_tool()` (라인 118-158) → `mcp_tools/` 레지스트리의 핸들러를 `asyncio.wait_for(handler(args), timeout=300)` 으로 실행
  - **HTTP 폴백 경로**: `POST {base_url}/mcp/execute` → `backend/api/mcp.py:54-78` → `backend/protocols/mcp/server.py`의 `MCPServer.handle_request()` → `protocols/mcp/server.py`에 등록된 도구 핸들러
  - **문제**: 두 경로는 **완전히 다른 도구 레지스트리**를 사용합니다. `core/mcp_server.py`는 `mcp_tools/` 모듈의 레지스트리(~25개 도구)를 사용하고, `protocols/mcp/server.py`는 자체 `_setup_tools()`로 등록한 도구(`search`, `remember` 등 소수)를 사용합니다. HTTP 폴백으로 전환되면 대부분의 도구가 "not found"로 실패합니다.
  - 영향: HTTP 폴백은 사실상 작동하지 않는 dead path. 직접 import가 `ImportError`를 발생시키거나 재시도가 소진되었을 때 HTTP 폴백이 실행되지만, 도구 목록이 다르므로 원하는 도구 실행에 실패할 가능성이 매우 높음.
  - 개선안: Strategy 패턴으로 전송 계층 분리
    ```python
    from abc import ABC, abstractmethod

    class ToolTransport(ABC):
        @abstractmethod
        async def call_tool(self, name: str, arguments: dict) -> dict: ...

        @abstractmethod
        async def list_tools(self) -> list: ...

    class DirectTransport(ToolTransport):
        """In-process direct import call."""
        async def call_tool(self, name: str, arguments: dict) -> dict:
            from backend.core.mcp_server import call_tool as mcp_call_tool
            result = await mcp_call_tool(name, arguments)
            return {"success": True, "result": "\n".join(r.text for r in result if hasattr(r, 'text'))}

        async def list_tools(self) -> list:
            from backend.core.mcp_server import list_tools as mcp_list_tools
            tools = await mcp_list_tools()
            return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema} for t in tools]

    class HTTPTransport(ToolTransport):
        """HTTP-based remote call (should target the SAME tool registry)."""
        def __init__(self, base_url: str):
            self.base_url = base_url
        # ... HTTP 구현

    class MCPClient:
        def __init__(self, transport: ToolTransport):
            self.transport = transport
    ```

- **`get_gemini_tools()`와 `get_anthropic_tools()` 도구 우선순위 로직 중복**: (`backend/core/mcp_client.py:188-255` vs `backend/core/mcp_client.py:257-305`)
  - 두 메서드는 캐시 TTL 확인 → `get_tools_with_schemas()` 호출 → `CORE_TOOLS` 기반 우선순위 정렬 → 도구 개수 제한이라는 **동일한 파이프라인**을 반복합니다. 차이는 마지막 변환 단계(Gemini 포맷 vs Anthropic 포맷)뿐입니다.
  - 영향: 우선순위 로직이나 캐시 정책 변경 시 두 메서드를 모두 수정해야 하는 중복. 한쪽만 수정하면 불일치 발생.
  - 개선안: 공통 파이프라인 추출
    ```python
    async def _get_prioritized_tools(self, force_refresh: bool, max_tools: int) -> list[dict]:
        """Fetch and prioritize tools (common pipeline)."""
        tools = await self.get_tools_with_schemas()
        core = [t for t in tools if t["name"] in CORE_TOOLS]
        other = [t for t in tools if t["name"] not in CORE_TOOLS]
        return (core + other)[:max_tools]

    async def get_gemini_tools(self, force_refresh: bool = False, max_tools: int = None) -> list:
        max_tools = max_tools or MAX_TOOLS
        now = time.time()
        if not force_refresh and self._gemini_tools_cache and (now - self._cache_timestamp) < self.TOOLS_CACHE_TTL:
            return self._gemini_tools_cache[:max_tools]

        tools = await self._get_prioritized_tools(force_refresh, max_tools)
        gemini_functions = [self._to_gemini_format(t) for t in tools]
        self._gemini_tools_cache = gemini_functions
        self._cache_timestamp = now
        return gemini_functions
    ```

### MEDIUM

- **HTTP 폴백의 `ClientSession` 매 호출마다 새로 생성**: (`backend/core/mcp_client.py:133`)
  - `call_tool_http()`가 호출될 때마다 `aiohttp.ClientSession()`을 새로 생성하고 즉시 닫습니다. `aiohttp` 문서에서는 세션 재사용을 강력히 권장하며, 매번 생성/파괴하면 TCP 연결 수립 오버헤드가 발생합니다.
  - 개선안: `MCPClient.__init__`에서 세션을 생성하고 `close()` 메서드로 수명주기 관리:
    ```python
    class MCPClient:
        def __init__(self, base_url: str = None):
            self.base_url = base_url or MCP_SERVER_URL
            self._session: Optional[aiohttp.ClientSession] = None

        async def _get_session(self) -> aiohttp.ClientSession:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

        async def close(self):
            if self._session and not self._session.closed:
                await self._session.close()
    ```

- **`CORE_TOOLS` 리스트 하드코딩**: (`backend/core/mcp_client.py:17-32`)
  - 13개 도구 이름이 리스트로 하드코딩되어 있어, 도구 추가/제거 시 이 파일도 수정해야 합니다. `mcp_tools/` 레지스트리에서 도구 목록을 동적으로 가져오거나, 각 도구에 `priority` 속성을 부여하여 레지스트리에서 자동 정렬하는 것이 바람직합니다.
  - 개선안:
    ```python
    # backend/core/mcp_tools/__init__.py에 priority 지원 추가
    def get_core_tool_names() -> list[str]:
        return [name for name, meta in _registry.items() if meta.get("core", False)]

    # mcp_client.py에서 동적 참조
    from backend.core.mcp_tools import get_core_tool_names
    ```

- **`MAX_TOOL_RETRIES`/`TOOL_RETRY_DELAY` 이중 정의**: (`backend/core/mcp_client.py:14-15`)
  - `config.py`에서 `MCP_MAX_TOOL_RETRIES`와 `MCP_TOOL_RETRY_DELAY`를 import한 뒤, 즉시 로컬 변수 `MAX_TOOL_RETRIES`와 `TOOL_RETRY_DELAY`에 재할당합니다. 이중 정의로 인해 혼란을 유발하며, config 값을 직접 사용하면 됩니다.
  - 개선안: 로컬 앨리어스 제거, `MCP_MAX_TOOL_RETRIES`와 `MCP_TOOL_RETRY_DELAY`를 직접 사용.

- **`list_tools()`와 `get_tools_with_schemas()` 중복**: (`backend/core/mcp_client.py:153-186`)
  - 두 메서드 모두 `from backend.core.mcp_server import list_tools as mcp_list_tools`를 호출하고, 결과를 dict로 변환합니다. 차이는 `input_schema` 포함 여부뿐이며, `list_tools()`는 프로젝트 내에서 호출되지 않아 dead code일 가능성이 높습니다.
  - 개선안: `list_tools()` 사용처 확인 후 dead code이면 삭제. 아니면 `get_tools_with_schemas()`에 `include_schema` 파라미터를 추가하여 통합.

- **Retry 로직이 10번 항목과 동일 패턴 중복**: (`backend/core/mcp_client.py:56-105`)
  - 이전 리뷰 (#10)에서 지적된 retry 패턴(`for attempt in range(1, MAX_RETRIES+1): try/except/sleep`)이 여기서도 그대로 반복됩니다. `backend/core/utils/retry.py`의 유틸리티를 활용하지 않고 있습니다.
  - 개선안: `retry.py`의 `async_retry` 데코레이터 또는 `tenacity` 라이브러리를 활용.

- **`ValueError` catch가 직접 호출 경로에서 무의미**: (`backend/core/mcp_client.py:75-78`)
  - `mcp_server.py:call_tool()`(라인 118-158)은 도구를 찾지 못하면 `ValueError`를 raise하지 않고, `TextContent(text="Error: Unknown tool ...")`를 반환합니다. 따라서 `except ValueError`에 도달하는 경로가 존재하지 않으며, dead code입니다.
  - 개선안: `call_tool()` 반환값에서 에러를 확인하는 방식으로 변경하거나, `mcp_server.py`에서 `ValueError`를 실제로 raise하도록 일관성 확보.

### LOW

- **캐시 TTL이 `TOOLS_CACHE_TTL = 300`(5분)으로 클래스 변수 하드코딩**: (`backend/core/mcp_client.py:37`)
  - 도구 목록은 서버 재시작 없이 변경되지 않으므로 TTL을 config로 빼는 것이 적절하지만, 현재 기능에 문제는 없음.

- **`get_mcp_client()` 싱글톤이 thread-safe하지 않음**: (`backend/core/mcp_client.py:309-318`)
  - `global _client` + `if _client is None` 패턴은 asyncio 단일 스레드 환경에서는 문제없지만, 멀티스레드 환경에서는 race condition이 가능합니다. 현재 단일 워커이므로 실질적 문제 없음.

## 개선 제안

### 1. Strategy 패턴으로 전송 계층 분리

현재 `MCPClient`는 도구 호출(Transport)과 도구 포맷 변환(Formatting) 두 가지 책임을 혼합하고 있습니다. 이를 분리하면:

```
MCPClient (Orchestrator)
├── ToolTransport (Interface)
│   ├── DirectTransport  ← in-process import
│   └── HTTPTransport    ← HTTP 호출 (동일 레지스트리 대상)
├── GeminiFormatter      ← Gemini 포맷 변환
└── AnthropicFormatter   ← Anthropic 포맷 변환
```

### 2. HTTP 폴백 경로의 근본적 재검토

HTTP 폴백이 `protocols/mcp/server.py`(소수의 자체 등록 도구)를 경유하는 현재 구조는 **폴백으로서 의미가 없습니다**. 두 가지 옵션:

- **Option A**: HTTP 폴백 제거 — 직접 import만 사용. 같은 프로세스 내에서 HTTP로 자기 자신을 호출하는 것은 불필요한 복잡성.
- **Option B**: HTTP 폴백이 동일 레지스트리를 사용하도록 수정 — `api/mcp.py`의 `/mcp/execute` 엔드포인트가 `core/mcp_server.py`의 `call_tool()`을 직접 호출하도록 변경.

**Option A를 권장합니다.** 현재 아키텍처에서 `MCPClient`와 `mcp_server.py`는 항상 같은 프로세스에서 실행되므로 HTTP 폴백은 실질적으로 dead path입니다.

### 3. 도구 우선순위 파이프라인 통합

`get_gemini_tools()`와 `get_anthropic_tools()`의 공통 파이프라인(도구 조회 → 우선순위 정렬 → 캐싱)을 하나의 메서드로 추출하고, 마지막 포맷 변환 단계만 분리합니다.

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| Strategy 패턴 전송 분리 | 중 | 인터페이스 추출 + 기존 호출부 2곳(chat_handler, tool_service) 수정 필요 |
| HTTP 폴백 제거 (Option A) | 하 | `call_tool_http()` 및 폴백 분기 삭제, 테스트 없어 회귀 검증 수동 |
| 도구 우선순위 파이프라인 통합 | 하 | 순수 리팩토링, 외부 인터페이스 변경 없음 |
| `CORE_TOOLS` 동적화 | 중 | 레지스트리에 priority 속성 추가 필요, mcp_tools 전 파일 수정 |
| config 앨리어스 정리 | 하 | 단순 rename, 2줄 변경 |
| `aiohttp.ClientSession` 재사용 | 하 | HTTP 폴백 제거 시 불필요. 유지 시에도 `__init__`+`close()` 추가만 |
| `list_tools()` dead code 정리 | 하 | 사용처 확인 후 삭제 |
| `ValueError` dead catch 제거 | 하 | 단순 삭제 또는 로직 일관성 수정 |
