# 14. 매직 넘버 산재

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/config.py`, `backend/core/utils/timeouts.py`, `backend/core/mcp_transport.py`, `backend/core/mcp_server.py`, `backend/core/services/react_service.py`, `backend/core/tools/hass_ops.py`, `backend/core/tools/system_observer.py`, `backend/core/mcp_tools/file_tools.py`, `backend/core/context_optimizer.py`, `backend/core/utils/gemini_wrapper.py`, `backend/llm/clients.py`, `backend/protocols/mcp/research_server.py`, `backend/memory/graph_rag.py`, `backend/memory/permanent/decay_calculator.py`, `backend/memory/permanent/embedding_service.py`, `backend/memory/recent/connection.py`, `backend/app.py`, `backend/wake/conversation.py` 외 다수

## 요약

프로젝트에는 `config.py`(환경변수 기반)와 `timeouts.py`(dataclass 기반) 두 개의 중앙 설정 패턴이 존재하나, 대다수 모듈이 이를 무시하고 로컬에서 매직 넘버를 하드코딩하고 있다. 타임아웃 값만 20개소 이상, 재시도 횟수 5개소, 파일 크기 제한 2개소가 중복 정의되어 있어, 운영 파라미터 변경 시 **샷건 수술**이 불가피하다. 특히 `hass_ops.py`는 config import 함수를 정의해놓고도 모듈 레벨에서 동일 값을 재하드코딩하는 이중 구조를 보인다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **설정 체계 파편화 — 3개의 독립적 설정 소스**: config.py(환경변수), timeouts.py(frozen dataclass), 개별 모듈 로컬 상수가 공존하며 어디에 무엇을 정의해야 하는지 컨벤션이 없다.
  - `backend/config.py` — 환경변수 기반 `_get_int_env()`, `_get_float_env()` 패턴 (253줄)
  - `backend/core/utils/timeouts.py` — `@dataclass(frozen=True)` 패턴 (30줄)
  - 각 모듈 로컬 상수 — `MAX_FILE_SIZE`, `MAX_RETRIES`, `SSE_*` 등
  - 영향: 새로운 설정값 추가 시 어떤 패턴을 따라야 할지 불명확. 설정 변경 시 3곳을 모두 확인해야 함.
  - 개선안: `timeouts.py`를 `config.py`에 통합하거나, config.py에 `TIMEOUTS` 섹션을 추가하여 단일 진실의 원천(Single Source of Truth) 확립
    ```python
    # config.py에 통합
    # =============================================================================
    # Timeouts (merged from timeouts.py)
    # =============================================================================
    TIMEOUT_API_CALL = _get_int_env("TIMEOUT_API_CALL", 180)
    TIMEOUT_STREAM_CHUNK = _get_int_env("TIMEOUT_STREAM_CHUNK", 60)
    TIMEOUT_FIRST_CHUNK_BASE = _get_int_env("TIMEOUT_FIRST_CHUNK_BASE", 100)
    TIMEOUT_MCP_TOOL = _get_int_env("TIMEOUT_MCP_TOOL", 300)
    TIMEOUT_SSE_CONNECTION = _get_int_env("TIMEOUT_SSE_CONNECTION", 600)
    TIMEOUT_SSE_KEEPALIVE = _get_int_env("TIMEOUT_SSE_KEEPALIVE", 15)
    ```

- **hass_ops.py 이중 정의 패턴**: config import 함수를 정의해놓고 모듈 레벨에서 동일 값을 하드코딩 (`backend/core/tools/hass_ops.py:86-93`)
  - 영향: `_get_hass_config()`는 런타임에 config.py 값을 가져오지만, 모듈 레벨 `HASS_TIMEOUT = 10.0`, `MAX_RETRIES = 2`도 존재. 어떤 코드 경로가 어떤 값을 사용하는지 혼란.
  - 개선안: 모듈 레벨 하드코딩 제거, config에서 직접 import
    ```python
    # hass_ops.py — 개선안
    from backend.config import HASS_TIMEOUT, HASS_MAX_RETRIES
    # 모듈 레벨 HASS_TIMEOUT = 10.0, MAX_RETRIES = 2 삭제
    ```

- **MAX_FILE_SIZE 2중 정의**: 동일한 `10 * 1024 * 1024` 값이 두 파일에 독립 정의
  - `backend/core/tools/system_observer.py:14` — `MAX_FILE_SIZE = 10 * 1024 * 1024`
  - `backend/core/mcp_tools/file_tools.py:10` — `MAX_FILE_SIZE = 10 * 1024 * 1024`
  - 영향: 한쪽만 변경 시 불일치 발생. 파일 크기 정책이 파편화됨.
  - 개선안: config.py에 단일 정의 후 양쪽에서 import
    ```python
    # config.py
    MAX_FILE_SIZE = _get_int_env("MAX_FILE_SIZE", 10 * 1024 * 1024)
    ```

- **재시도 횟수 5개소 독립 정의**: 모듈마다 다른 이름/값으로 최대 재시도 횟수를 정의
  - `backend/core/utils/gemini_wrapper.py:13` — `MAX_RETRIES = 5`
  - `backend/llm/clients.py:292` — `MAX_STREAM_RETRIES = 5` (함수 내부)
  - `backend/core/tools/hass_ops.py:93` — `MAX_RETRIES = 2`
  - `backend/memory/permanent/embedding_service.py:101` — `max_retries = 3` (로컬 변수)
  - `backend/config.py:226` — `MCP_MAX_TOOL_RETRIES = 3` (환경변수 기반, 미활용)
  - 영향: 재시도 정책 통일 불가능. `retry.py` 유틸리티가 존재하나 대부분 미사용(#10 리포트 참조).
  - 개선안: 서비스별 재시도 설정을 config.py에 그룹화
    ```python
    # config.py
    GEMINI_MAX_RETRIES = _get_int_env("GEMINI_MAX_RETRIES", 5)
    GEMINI_STREAM_MAX_RETRIES = _get_int_env("GEMINI_STREAM_MAX_RETRIES", 5)
    EMBEDDING_MAX_RETRIES = _get_int_env("EMBEDDING_MAX_RETRIES", 3)
    ```

### MEDIUM

- **SSE 설정 하드코딩**: `mcp_transport.py`에서 SSE 관련 상수를 환경변수 없이 직접 정의 (`backend/core/mcp_transport.py:26-28`)
  - `SSE_KEEPALIVE_INTERVAL = 15` (초)
  - `SSE_CONNECTION_TIMEOUT = 600` (초, 10분)
  - `SSE_RETRY_DELAY = 3000` (밀리초)
  - 개선안: config.py의 `_get_int_env()` 패턴 활용

- **MCP 도구 타임아웃 하드코딩**: 5분(300초) 타임아웃이 config 없이 직접 코드에 삽입 (`backend/core/mcp_server.py:140`)
  - `timeout=300.0` in `asyncio.wait_for(handler(arguments), timeout=300.0)`
  - 개선안: `MCP_TOOL_TIMEOUT = _get_int_env("MCP_TOOL_TIMEOUT", 300)` → config.py

- **ReAct 루프 매직 넘버**: max_loops, temperature, max_tokens가 dataclass 기본값으로 하드코딩 (`backend/core/services/react_service.py:49-53`)
  - `max_loops: int = 15`
  - `temperature: float = 0.7`
  - `max_tokens: int = 16384`
  - 개선안: config.py에서 기본값을 import하여 사용
    ```python
    from backend.config import REACT_MAX_LOOPS, REACT_DEFAULT_TEMPERATURE, REACT_DEFAULT_MAX_TOKENS
    ```

- **Context Optimizer 티어 예산 하드코딩**: 5개 섹션의 `max_chars`가 코드 내 직접 정의 (`backend/core/context_optimizer.py:22-60`)
  - `system_prompt: 20_000`, `temporal: 5_000`, `working_memory: 150_000`, `long_term: 50_000`, `graphrag: 20_000`
  - config.py의 `MEMORY_WORKING_BUDGET = 150000` 등과 **의미적 중복** (단위가 토큰 vs 문자로 다르지만, 별도 관리가 혼란 유발)
  - 개선안: config.py에 `CONTEXT_BUDGET_*` 계열 상수 추가

- **GraphRAG 탐색 제한 매직 넘버 산재**: 엔티티, 깊이, 경로 제한이 함수 파라미터 기본값과 슬라이싱으로 흩어짐 (`backend/memory/graph_rag.py`)
  - `max_entities: int = 5` (`:467`)
  - `max_depth: int = 2` (`:497`)
  - `matches[:2]` (`:509`), `query_entities[:3]` (`:515`)
  - `entity_ids[:3]`, `entity_ids[i+1:4]` (`:529-530`)
  - `relations[:10]` (`:537`), `paths[:5]` (`:541`), `paths[:3]` (`:591`)
  - `importance_threshold: float = 0.6` (`:343`)
  - `existing.weight += 0.1` (`:118`)
  - 개선안: GraphRAG 전용 설정 dataclass 도입
    ```python
    @dataclass
    class GraphRAGConfig:
        max_entities: int = 5
        max_depth: int = 2
        max_relations: int = 10
        max_paths: int = 5
        importance_threshold: float = 0.6
        weight_increment: float = 0.1
    ```

- **Decay 계산 매직 넘버**: 메모리 타입별 decay 배율과 recency boost가 딕셔너리 리터럴로 하드코딩 (`backend/memory/permanent/decay_calculator.py:24-29, 152-153`)
  - `"fact": 0.3`, `"preference": 0.5`, `"insight": 0.7`, `"conversation": 1.0`
  - `hours_passed > 168` (1주일), `last_access_hours < 24`, `recency_boost = 1.3`
  - 개선안: config.py에 decay 관련 섹션 추가하거나 별도 `decay_config.py` 분리

- **system_observer.py 로컬 상수 집합**: 파일/로그/검색 제한이 config 미연동 (`backend/core/tools/system_observer.py:14-20`)
  - `MAX_FILE_SIZE = 10 * 1024 * 1024`
  - `MAX_LOG_LINES = 1000`
  - `MAX_SEARCH_RESULTS = 100`
  - `SEARCH_CONTEXT_LINES = 2`
  - 개선안: config.py에 통합

- **gemini_wrapper.py 타임아웃/재시도**: timeouts.py가 존재하지만 이를 사용하지 않음 (`backend/core/utils/gemini_wrapper.py:12-14`)
  - `DEFAULT_TIMEOUT_SECONDS = 120.0` — timeouts.py의 `API_CALL = 180`과 **값 불일치** (120초 vs 180초)
  - `MAX_RETRIES = 5` — 독립 정의
  - `RETRY_DELAY_BASE = 2.0` — 독립 정의
  - 영향: wrapper와 clients.py가 서로 다른 타임아웃 사용. 동일 Gemini API 호출에 대해 120초/180초 불일치.
  - 개선안: `from backend.core.utils.timeouts import TIMEOUTS` 사용

- **research_server.py 이중 할당**: config.py에서 import한 후 동일 이름의 로컬 상수에 재할당 (`backend/protocols/mcp/research_server.py:60-63`)
  - `PAGE_TIMEOUT_MS = RESEARCH_PAGE_TIMEOUT_MS` — 불필요한 앨리어싱
  - `NAVIGATION_TIMEOUT_MS = RESEARCH_NAVIGATION_TIMEOUT_MS` — 불필요한 앨리어싱
  - `MAX_CONTENT_LENGTH = RESEARCH_MAX_CONTENT_LENGTH` — 불필요한 앨리어싱
  - 개선안: config import를 직접 사용하거나, 앨리어스 제거

- **DuckDuckGo HTTP 타임아웃 하드코딩**: config.py/timeouts.py 미참조 (`backend/protocols/mcp/research_server.py:280`)
  - `timeout=15` — aiohttp 세션 타임아웃
  - 개선안: `TIMEOUTS.HTTP_DEFAULT` 또는 config.py에서 관리

### LOW

- **로깅 슬라이싱 길이 불일치**: 로그에서 문자열을 자르는 길이가 모듈마다 다름
  - `session_id[:8]` — 세션 ID 프리뷰 (다수 파일)
  - `query[:80]`, `url[:100]`, `url[:80]`, `url[:50]` — URL/쿼리 프리뷰 (research_server.py 내에서도 불일치)
  - `error[:100]`, `error[:200]`, `error[:300]` — 에러 메시지 프리뷰
  - 개선안: 로깅 유틸리티에 `preview(text, length=80)` 함수 도입 (선택적)

- **BrowserManager 상수 하드코딩**: 브라우저 관련 운영 파라미터가 인스턴스 속성으로 직접 할당 (`backend/protocols/mcp/research_server.py:82-84`)
  - `self._max_uses = 50` — 브라우저 재시작 기준 사용 횟수
  - `self._idle_timeout: int = 300` — 유휴 타임아웃 (5분)
  - 개선안: config.py에 `BROWSER_MAX_USES`, `BROWSER_IDLE_TIMEOUT` 추가

- **ChatRequest 기본값**: dataclass 기본값이 코드에 직접 정의 (`backend/core/chat_handler.py:59-60`)
  - `temperature: float = 0.7`
  - `max_tokens: int = 16384`
  - 이는 API 요청의 기본값으로, config 통합은 선택적

- **app.py shutdown 타임아웃**: 셧다운 시퀀스 타임아웃이 하드코딩 (`backend/app.py:118,134,149`)
  - `timeout=3.0` (백그라운드 태스크), `timeout=3.0` (세션), `timeout=2.0` (HTTP pool)
  - 개선안: `SHUTDOWN_TASK_TIMEOUT`, `SHUTDOWN_SESSION_TIMEOUT` 등 config.py에 추가

## 개선 제안

### 1단계: 설정 체계 통일 (가장 중요)

현재 3개 설정 소스(`config.py`, `timeouts.py`, 로컬 상수)를 2단계로 정리:

1. **`timeouts.py`를 `config.py`에 흡수**: timeouts.py의 frozen dataclass를 config.py의 `_get_int_env()` 패턴으로 변환. 환경변수로 오버라이드 가능하게.
2. **config.py에 섹션별 네임스페이스 추가**: `TIMEOUT_*`, `RETRY_*`, `LIMIT_*` 접두사로 운영 파라미터를 그룹화.

### 2단계: 로컬 하드코딩 제거

- 각 모듈의 로컬 매직 넘버를 config.py import로 교체.
- `hass_ops.py`의 이중 정의 패턴 제거.
- `system_observer.py`, `file_tools.py`의 `MAX_FILE_SIZE` 중복 제거.

### 3단계: 도메인 설정 dataclass 도입

GraphRAG, Decay, BrowserManager 같은 복잡한 설정은 전용 dataclass로 관리:

```python
# config.py 또는 별도 파일
@dataclass(frozen=True)
class GraphRAGConfig:
    max_entities: int = 5
    max_depth: int = 2
    max_relations: int = 10
    importance_threshold: float = 0.6

@dataclass(frozen=True)
class DecayConfig:
    fact_rate: float = 0.3
    preference_rate: float = 0.5
    insight_rate: float = 0.7
    conversation_rate: float = 1.0
    recency_hours: int = 24
    recency_boost: float = 1.3
```

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| timeouts.py → config.py 통합 | 낮음 | 기존 `_get_int_env` 패턴 재활용, import 경로만 변경 |
| hass_ops.py 이중 정의 제거 | 낮음 | 3줄 삭제, 1줄 import 수정 |
| MAX_FILE_SIZE 중복 제거 | 낮음 | config.py에 1줄 추가, 2파일에서 import 변경 |
| 재시도 횟수 config.py 통합 | 낮음 | 상수 5개 추가, 각 모듈에서 import 변경 |
| SSE/MCP 타임아웃 config 통합 | 낮음 | 상수 3~4개 추가, import 변경 |
| ReAct/Context Optimizer 기본값 config화 | 중간 | dataclass 기본값을 config import로 교체, 테스트 필요 |
| GraphRAG 설정 dataclass 도입 | 중간 | 함수 시그니처 변경 필요, 호출부 모두 수정 |
| Decay 설정 분리 | 중간 | decay_calculator.py 리팩토링 필요 |
| gemini_wrapper.py 타임아웃 불일치 해소 | 낮음 | timeouts.py import 추가, 값 검증 필요 |
| research_server.py 불필요한 앨리어싱 제거 | 낮음 | 3줄 삭제, 참조부 이름 변경 |
