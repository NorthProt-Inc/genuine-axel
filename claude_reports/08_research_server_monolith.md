# 08. research_server.py 모놀리스

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/protocols/mcp/research_server.py` (856줄), `backend/core/research_artifacts.py` (210줄), `backend/protocols/mcp/async_research.py` (378줄)

## 요약

research_server.py는 Playwright 브라우저 관리, DuckDuckGo/Tavily 검색, HTML-to-Markdown 파싱, 아티팩트 저장, MCP 도구 스키마, SSE/stdio 전송 계층을 모두 한 파일에 포함한 856줄 모놀리스입니다. 책임이 명확히 분리되지 않아 단일 변경이 여러 기능에 영향을 줄 수 있으며, 특히 브라우저 리소스 관리에서 예외 삼킴으로 인한 누수 위험이 있습니다.

## 발견사항

### CRITICAL

없음

### HIGH

- **7가지 책임 혼재 (God Module)**: 단일 파일에 너무 많은 책임이 집중되어 있습니다. (`research_server.py` 전체)
  - 영향: 검색 로직 변경이 브라우저 관리에 영향, 전송 계층 수정이 도구 로직에 영향 등 샷건 수술(Shotgun Surgery) 유발
  - 책임 목록:
    1. **BrowserManager**: Playwright 생명주기 관리 (74~187줄)
    2. **HTML 처리**: clean_html(), html_to_markdown() (197~263줄)
    3. **검색 엔진**: search_duckduckgo(), _google_search(), _tavily_search() (265~374줄)
    4. **페이지 방문**: _visit_page() (376~449줄)
    5. **Deep Dive**: _deep_dive() (451~540줄)
    6. **MCP 스키마/핸들러**: list_tools(), call_tool() (542~773줄)
    7. **서버 전송 계층**: run_stdio(), run_sse() (775~852줄)
  - 개선안:
    ```python
    # 권장 분리 구조
    backend/protocols/mcp/
    ├── research_server.py       # MCP 스키마 + 전송 계층만
    ├── research/
    │   ├── browser.py           # BrowserManager 클래스
    │   ├── html_parser.py       # clean_html, html_to_markdown
    │   ├── search_engines.py    # DuckDuckGo, Tavily 검색
    │   └── page_visitor.py      # _visit_page, _deep_dive
    ```

- **`import os` 중복**: 5번째 줄과 35번째 줄에 동일한 import 문 (`research_server.py:6,35`)
  - 영향: 코드 품질 저하, 유기적 성장의 흔적
  - 개선안:
    ```python
    # 6줄의 import os 제거하고 35줄만 유지
    # 또는 파일 상단에 통합
    import os  # 한 번만 import
    ```

- **BrowserManager 싱글톤의 이중 체크 비일관성**: `get_instance()` (89~96줄)와 `get_browser_manager()` (190~195줄) 두 곳에서 인스턴스 관리 (`research_server.py:89-96,190-195`)
  - 영향: `browser_manager` 전역 변수와 `BrowserManager._instance` 클래스 변수가 별도로 존재하여 혼란 유발
  - 개선안:
    ```python
    # 전역 변수 제거하고 BrowserManager.get_instance()만 사용
    # 또는 의존성 주입 패턴으로 전환

    # 현재 (혼재)
    browser_manager: Optional[BrowserManager] = None

    async def get_browser_manager() -> BrowserManager:
        global browser_manager
        if browser_manager is None:
            browser_manager = await BrowserManager.get_instance()
        return browser_manager

    # 개선안 (하나만 유지)
    async def get_browser_manager() -> BrowserManager:
        return await BrowserManager.get_instance()  # 클래스 메서드만 사용
    ```

### MEDIUM

- **예외 삼킴으로 인한 잠재적 브라우저 리소스 누수**: 페이지 닫기 실패 시 예외를 로깅만 하고 계속 진행 (`research_server.py:446-449`)
  - 영향: 페이지가 닫히지 않으면 브라우저 컨텍스트에 누적되어 메모리 누수 가능
  - 개선안:
    ```python
    # 현재 코드
    finally:
        if page:
            try:
                await page.close()
            except Exception as e:
                _log.warning("Page close failed, potential leak", ...)

    # 개선안: 강제 정리 시도
    finally:
        if page:
            try:
                await page.close()
            except Exception as e:
                _log.error("Page close failed, forcing context recreation", ...)
                # 심각한 누수 방지를 위해 컨텍스트 재생성 고려
                manager = await get_browser_manager()
                manager._use_count = manager._max_uses  # 다음 요청 시 재시작 트리거
    ```

- **셀렉터 대기 예외 무시**: 콘텐츠 셀렉터 대기 실패 시 완전히 무시 (`research_server.py:402-406`)
  - 영향: 페이지 로딩이 완료되지 않은 상태에서 콘텐츠 추출 시도 가능
  - 개선안:
    ```python
    # 현재 코드
    try:
        await page.wait_for_selector('article, main, ...', timeout=5000)
    except (asyncio.TimeoutError, Exception):
        pass  # 완전히 무시

    # 개선안: 최소한 로깅
    try:
        await page.wait_for_selector('article, main, ...', timeout=5000)
    except asyncio.TimeoutError:
        _log.debug("Content selector timeout, proceeding with available content", url=url[:80])
    except Exception as e:
        _log.debug("Content selector failed", url=url[:80], error=str(e))
    ```

- **Tavily 클라이언트 지연 초기화와 전역 상태**: `_tavily_client` 전역 변수와 `get_tavily_client()` 함수 (`research_server.py:40-52`)
  - 영향: 테스트 격리 어려움, 멀티 워커 환경에서 잠재적 레이스 컨디션
  - 개선안:
    ```python
    # 의존성 주입 또는 싱글톤 패턴으로 통합
    class TavilyClientManager:
        _instance: Optional["TavilyClientManager"] = None
        _lock = asyncio.Lock()

        def __init__(self):
            self._client = None

        @classmethod
        async def get_instance(cls) -> "TavilyClientManager":
            # BrowserManager와 동일한 패턴
            ...
    ```

- **함수명 불일치 (`_google_search` vs DuckDuckGo)**: 함수명이 `_google_search`이지만 실제로는 DuckDuckGo를 사용 (`research_server.py:318-335`)
  - 영향: 코드 가독성 저하, 유지보수 시 혼란
  - 개선안:
    ```python
    # 현재
    async def _google_search(query: str, num_results: int = 5) -> str:
        _log.info("DuckDuckGo search", ...)  # 로그는 DuckDuckGo
        results = await search_duckduckgo(query, num_results)

    # 개선안: 함수명 변경
    async def _web_search(query: str, num_results: int = 5) -> str:
        """Search using available search engine (currently DuckDuckGo)."""
        ...
    ```

- **도구 스키마와 핸들러 분리**: MCP 도구 스키마(542~720줄)와 핸들러(call_tool, 722~773줄)가 같은 파일이지만 도구별로 분리되지 않음 (`research_server.py:542-773`)
  - 영향: 새 도구 추가 시 list_tools()과 call_tool() 모두 수정 필요
  - 개선안:
    ```python
    # 데코레이터 기반 자동 등록
    from dataclasses import dataclass

    @dataclass
    class ResearchTool:
        name: str
        description: str
        input_schema: dict
        handler: Callable

    _tools: dict[str, ResearchTool] = {}

    def tool(name: str, description: str, input_schema: dict):
        def decorator(func):
            _tools[name] = ResearchTool(name, description, input_schema, func)
            return func
        return decorator

    @tool(
        name="google_search",
        description="Search the web...",
        input_schema={...}
    )
    async def _google_search(query: str, num_results: int = 5) -> str:
        ...
    ```

- **USER_AGENTS 하드코딩**: User-Agent 문자열이 코드에 직접 하드코딩되어 있고 버전이 오래됨(Chrome/120.0.0.0) (`research_server.py:54-60`)
  - 영향: 봇 탐지에 걸릴 가능성 증가, 업데이트 시 코드 수정 필요
  - 개선안:
    ```python
    # config.py로 이동 또는 외부 파일에서 로드
    # backend/config.py
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
        ...
    ]

    # 또는 fake_useragent 라이브러리 사용
    from fake_useragent import UserAgent
    ua = UserAgent()
    user_agent = ua.random
    ```

### LOW

- **`import sys` 중복**: 5줄에서 import 후 836줄에서 다시 import (`research_server.py:5,836`)
  - 개선안: 파일 상단의 import만 사용

- **`import time` 함수 내 반복 import**: `_visit_page()`, `_deep_dive()`, `call_tool()` 함수 내에서 각각 `import time` 수행 (`research_server.py:378,453,725`)
  - 개선안: 파일 상단에서 한 번만 import

- **`import urllib.parse` 함수 내 import**: `search_duckduckgo()` 내에서 조건부 import (`research_server.py:299`)
  - 개선안: 이미 상단에서 `from urllib.parse import ...`를 하고 있으므로 통합

- **매직 넘버**: `_max_uses=50` (84줄), `_idle_timeout=300` (86줄), `timeout=5000` (404줄) 등 (`research_server.py:84,86,404`)
  - 개선안: config.py의 기존 RESEARCH_* 설정과 통합

## 개선 제안

### 1단계: 즉시 수정 (영향도 낮음)
1. **import 중복 제거**: `import os`, `import sys`, `import time`, `import urllib.parse` 정리
2. **함수명 수정**: `_google_search` → `_web_search` (또는 주석으로 명확화)
3. **매직 넘버를 config.py로 이동**: `BROWSER_MAX_USES`, `BROWSER_IDLE_TIMEOUT`, `SELECTOR_TIMEOUT`

### 2단계: 모듈 분리 (점진적 리팩토링)
```
backend/protocols/mcp/
├── research_server.py          # MCP 진입점 (스키마, 전송 계층)
├── research/
│   ├── __init__.py
│   ├── browser.py              # BrowserManager
│   ├── html_processor.py       # clean_html, html_to_markdown
│   ├── search/
│   │   ├── __init__.py
│   │   ├── duckduckgo.py       # DuckDuckGo 검색
│   │   └── tavily.py           # Tavily 검색
│   ├── page_visitor.py         # _visit_page
│   └── deep_dive.py            # _deep_dive
```

### 3단계: 데코레이터 기반 도구 등록
- 스키마와 핸들러를 같은 위치에 정의하여 동기화 실수 방지
- `call_tool()`의 if-elif 체인을 동적 디스패치로 교체

### 4단계: 예외 처리 강화
1. 페이지 닫기 실패 시 브라우저 재시작 트리거
2. 셀렉터 대기 실패 로깅 추가
3. Tavily 초기화 실패 시 명확한 에러 메시지

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| import 중복 제거 | 쉬움 | 단순 삭제, 동작 변경 없음 |
| 함수명 변경 | 쉬움 | 내부 함수이므로 외부 영향 없음 |
| 매직 넘버 → config.py | 쉬움 | 기존 패턴 따라 추가만 하면 됨 |
| 전역 변수 정리 | 중간 | browser_manager, _tavily_client 통합 필요 |
| 모듈 분리 | 어려움 | import 경로 변경, 순환 의존성 주의 필요 |
| 데코레이터 기반 등록 | 어려움 | 전체 구조 변경, 테스트 필요 |
| 예외 처리 강화 | 중간 | 동작 변경 수반, 테스트 필요 |
