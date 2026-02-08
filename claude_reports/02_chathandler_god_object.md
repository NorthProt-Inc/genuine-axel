# 02. ChatHandler God Object

> 분석 날짜: 2026-02-04
> 분석 범위: `backend/core/chat_handler.py` (938줄), `backend/core/context_optimizer.py`, `backend/core/mcp_client.py`, `backend/llm/router.py`, `backend/api/deps.py`, `backend/api/openai.py`, `backend/memory/unified.py`

## 요약

`ChatHandler` 클래스는 938줄의 단일 파일에 **컨텍스트 빌드, 웹 검색, LLM 스트리밍, 도구 실행 루프(ReAct), XML 태그 필터링, 메모리 영속화**를 모두 포함하고 있다. 핵심 메서드 `process()`는 223~561줄(339줄)에 달하는 거대 메서드로, 하나의 변경 사유(예: 도구 실행 방식 변경)가 이 파일 전체에 영향을 미친다. `self.state`에 대한 참조가 35회로 `AppState`의 모든 필드에 강하게 결합되어 있으며, 이는 단위 테스트를 사실상 불가능하게 만든다.

## 발견사항

### CRITICAL

없음 (보안 취약점이 아닌 설계 문제이므로 CRITICAL은 해당 없음)

### HIGH

- **`process()` 메서드 God Method — 339줄, 6개 책임 혼재** (`chat_handler.py:223-561`)
  - 영향: 대화 파이프라인의 모든 변경이 이 하나의 메서드를 통과함. 스트리밍 로직, 도구 실행 루프, 에러 처리, 후처리가 뒤엉켜 있어 한 부분 수정 시 의도치 않은 사이드 이펙트 위험.
  - 개선안: 6개 단계를 각각 독립 메서드 또는 클래스로 분리
    ```python
    # 현재: process()가 모든 것을 직접 수행
    # 제안: Pipeline 패턴으로 단계 분리

    class ChatPipeline:
        def __init__(self, state):
            self.context_builder = ContextBuilder(state)
            self.tool_executor = ToolExecutor(state)
            self.stream_processor = StreamProcessor()
            self.memory_persister = MemoryPersister(state)

        async def process(self, request: ChatRequest) -> AsyncGenerator[ChatEvent, None]:
            # 1. 컨텍스트 빌드 (현재 263-268줄)
            context = await self.context_builder.build(request)

            # 2. 웹 검색 (현재 270-276줄)
            search = await self.context_builder.web_search(request)

            # 3. LLM 스트리밍 + 도구 루프 (현재 306-452줄)
            async for event in self.tool_executor.react_loop(context, search):
                yield event

            # 4. 후처리 (현재 506-560줄)
            await self.memory_persister.persist(request, response)
    ```

- **`_build_context_and_prompt()` — 170줄, 메모리 3계층 직접 조회** (`chat_handler.py:621-790`)
  - 영향: Working Memory, Session Archive, Long-term Memory, GraphRAG 4가지 메모리 소스의 조회 로직이 한 함수에 인라인되어 있음. 메모리 시스템 변경 시 반드시 이 함수를 수정해야 하며, `MemoryManager`가 이미 존재함에도 불구하고 ChatHandler가 직접 각 계층에 접근.
  - 개선안: `MemoryManager`에 컨텍스트 빌드를 위임
    ```python
    # 현재: ChatHandler가 메모리 각 계층에 직접 접근
    # chat_handler.py:650-722 (72줄)
    if self.state.memory_manager and self.state.memory_manager.working:
        turn_count = self.state.memory_manager.working.get_turn_count()
        # ... working memory 처리
    if config["use_sqlite"] and self.state.memory_manager and self.state.memory_manager.session_archive:
        # ... session archive 처리
    if self.state.long_term_memory:
        # ... long-term memory 처리
    if config["use_graphrag"] and self.state.memory_manager and self.state.memory_manager.graph_rag:
        # ... graphrag 처리

    # 제안: MemoryManager에 위임 (Facade 패턴)
    class MemoryManager:
        async def build_context(self, query: str, config: dict) -> MemoryContext:
            """모든 메모리 계층에서 컨텍스트를 수집"""
            return MemoryContext(
                working=self._get_working_context(config),
                session=self._get_session_context(config),
                longterm=await self._get_longterm_context(query, config),
                graphrag=await self._get_graphrag_context(query, config),
            )

    # ChatHandler에서는:
    memory_context = await self.state.memory_manager.build_context(user_input, config)
    for section_name, content in memory_context.sections():
        optimizer.add_section(section_name, content)
    ```

- **`self.state` 과다 참조 — 35회, `AppState`의 `Any` 타입 의존** (`chat_handler.py` 전체, `backend/api/deps.py:17-34`)
  - 영향: `AppState`의 모든 필드가 `Any` 타입으로 선언되어 있어 (`deps.py:20-27`), `ChatHandler`가 `self.state.memory_manager.working.get_turn_count()` 같은 깊은 속성 체인을 사용할 때 타입 안전성이 전혀 없음. `None` 체크가 곳곳에 반복됨 (예: `self.state.memory_manager and self.state.memory_manager.working`가 6회 반복).
  - 개선안: Protocol 또는 타입 힌트 적용, Null Object 패턴
    ```python
    # 현재: 반복적인 None 체크
    if self.state.memory_manager and self.state.memory_manager.working:
        turn_count = self.state.memory_manager.working.get_turn_count()
    # ... 이 패턴이 6회 이상 반복

    # 제안 1: AppState에 타입 힌트
    @dataclass
    class AppState:
        memory_manager: Optional['MemoryManager'] = None
        long_term_memory: Optional['LongTermMemory'] = None
        identity_manager: Optional['IdentityManager'] = None

    # 제안 2: Null Object 패턴으로 None 체크 제거
    class NullMemoryManager:
        """아무 것도 하지 않는 메모리 매니저"""
        class NullWorking:
            def get_turn_count(self): return 0
            def get_progressive_context(self, **kw): return ""
            session_id = "null"
        working = NullWorking()
        session_archive = None
        graph_rag = None
        def add_message(self, role, content): pass
    ```

- **ReAct 도구 실행 루프의 복잡도** (`chat_handler.py:306-452`)
  - 영향: while 루프 안에 LLM 스트리밍, 텍스트 버퍼링, 도구 감지, 도구 실행, 결과 주입이 모두 중첩됨. 루프 내부의 `try/except`가 2단계 깊이로 중첩되어 (306→313→413) 제어 흐름 추적이 어려움.
  - 개선안: 도구 실행 루프를 별도 클래스로 추출
    ```python
    class ReActLoop:
        """LLM-Tool 반복 실행 엔진"""

        def __init__(self, mcp_client, max_loops=15):
            self.mcp_client = mcp_client
            self.max_loops = max_loops

        async def run(
            self, llm, prompt, system_prompt, **llm_kwargs
        ) -> AsyncGenerator[ChatEvent, None]:
            for loop_count in range(self.max_loops):
                stream_result = await self._stream_once(llm, prompt, system_prompt, **llm_kwargs)

                yield from stream_result.events

                if not stream_result.function_calls:
                    break

                tool_results = await self._execute_tools(stream_result.function_calls)
                prompt = self._inject_results(prompt, tool_results)
    ```

### MEDIUM

- **XML 태그 필터링 하드코딩 — 도구 이름 42줄 인라인** (`chat_handler.py:25-43`)
  - 개선안: MCP 도구 레지스트리에서 도구 이름 목록을 동적으로 가져와 패턴 생성. 현재 도구 추가 시 이 정규식도 수동 업데이트 필요. (이 항목은 #21과 동일하나 ChatHandler 맥락에서 재확인)
    ```python
    # 제안: 도구 레지스트리에서 동적 생성
    async def _build_xml_tag_pattern(tool_names: list[str]) -> re.Pattern:
        tool_pattern = '|'.join(re.escape(name) for name in tool_names)
        return re.compile(
            r'</?(?:' + INTERNAL_TAGS + r'|' + tool_pattern + r')[^>]*>',
            re.IGNORECASE | re.DOTALL
        )
    ```

- **`except Exception` 14회 사용 — 과도한 예외 삼킴** (`chat_handler.py:197,365,428,491,544,611,675,710,721,748,814,870,915,935`)
  - 개선안: 특히 `_format_memory_age()`의 bare `except Exception: return ""`(197줄)은 파싱 실패를 완전히 숨김. 최소한 `ValueError`/`TypeError`로 좁히고 로깅을 추가해야 함.
    ```python
    # 현재 (197줄)
    except Exception:
        return ""

    # 제안
    except (ValueError, TypeError) as e:
        _log.debug("Memory age parse failed", timestamp=timestamp_str, error=str(e))
        return ""
    ```

- **프롬프트 구성 로직 분산 — `_build_context_and_prompt()`와 `_build_final_prompt()` 이중 구조** (`chat_handler.py:621-790`, `818-834`)
  - 개선안: `_build_context_and_prompt()`가 시스템 프롬프트를 구성하고, `_build_final_prompt()`가 사용자 프롬프트를 구성하는데, 두 함수 간 역할 분담이 이름에서 명확하지 않음. `build_system_context()`와 `build_user_prompt()`로 이름을 명확히 하고, 단일 `PromptBuilder` 클래스로 통합 권장.

- **`force_tool_call = "라자냐" in request.user_input` — 매직 문자열 하드코딩** (`chat_handler.py:297`)
  - 개선안: 특정 한국어 단어에 의존하는 하드코딩된 기능 트리거. 설정 파일이나 패턴 목록으로 분리 권장.
    ```python
    # 현재
    force_tool_call = "라자냐" in request.user_input

    # 제안: config로 분리
    FORCE_TOOL_KEYWORDS = {"라자냐"}  # config.py에서 관리
    force_tool_call = any(kw in request.user_input for kw in FORCE_TOOL_KEYWORDS)
    ```

- **지연 import 패턴 — 런타임 import 3건** (`chat_handler.py:292,727,800`)
  - 개선안: `from backend.core.mcp_client import get_mcp_client`(292줄), `from backend.core.tools.system_observer import ...`(727줄), `from backend.protocols.mcp.research_server import _tavily_search`(800줄)가 함수 내부에서 지연 import됨. 순환 의존 해소를 위한 것으로 보이나, 이는 모듈 간 결합도가 높다는 신호. 의존성 주입(DI)으로 전환하면 순환 의존과 지연 import 모두 해소됨.
    ```python
    # 제안: 의존성 주입
    class ChatHandler:
        def __init__(self, state, mcp_client=None, search_fn=None):
            self.state = state
            self.mcp_client = mcp_client or get_mcp_client()
            self.search_fn = search_fn  # 테스트 시 mock 가능
    ```

- **토큰 추정 `len(text) // 4` 반복** (`chat_handler.py:540-541,780,787`, `context_optimizer.py:223,264`)
  - 개선안: `len(text) // 4`가 토큰 추정으로 여러 곳에서 반복됨. `context_optimizer.py`에 `estimate_tokens()`가 이미 있으나 ChatHandler에서는 인라인으로 사용. `estimate_tokens()` 함수를 일관되게 사용해야 함.

### LOW

- **`DEFAULT_CONFIG` 딕셔너리 — 타입 안전성 없음** (`chat_handler.py:134-143`)
  - 개선안: `@dataclass`로 변환하여 타입 안전성과 자동완성 지원.
    ```python
    @dataclass(frozen=True)
    class ChatConfig:
        working_turns: int = 200
        full_turns: int = 80
        use_sqlite: bool = True
        chromadb_limit: int = 100
        use_graphrag: bool = True
        max_context_chars: int = 2_000_000
        session_count: int = 30
        session_budget: int = 60_000
    ```

- **`ClassificationResult` 미활용** (`chat_handler.py:146-150,242-245`)
  - 개선안: `ClassificationResult`가 생성되지만 모든 필드가 `False`로 고정됨. 실제 분류 로직이 없으므로 현재는 데드 코드에 가까움. 분류 로직을 구현하거나 제거 필요.

- **`_select_model()`과 `_determine_tier()` — 단순 상수 반환** (`chat_handler.py:614-619`)
  - 개선안: 각각 `DEFAULT_MODEL`과 `"axel"`만 반환. 확장 포인트로 의도된 것이라면 문서화 필요, 아니면 인라인화 가능.

## 개선 제안

### 종합 리팩토링 방향

ChatHandler의 핵심 문제는 **파이프라인 오케스트레이션**과 **각 단계의 구현**이 분리되지 않은 것이다. 다음 단계적 접근을 권장:

#### Phase 1: 추출 (Extract) — 위험도 낮음
기존 동작을 변경하지 않으면서 메서드를 별도 클래스로 추출:

1. **ContextBuilder**: `_build_context_and_prompt()` + `_build_final_prompt()` → 컨텍스트/프롬프트 구성 전담
2. **ReActLoop**: `process()` 내 while 루프(306-452줄) → 도구 실행 루프 전담
3. **MemoryPersister**: `_post_process()` + `_persist_memory_async()` + `_store_longterm_async()` + `_extract_graph_async()` → 메모리 영속화 전담
4. **StreamFilter**: `_strip_xml_tags()` + `_normalize_spacing()` + `_has_partial_tool_tag()` + 버퍼링 로직 → 스트림 필터링 전담

#### Phase 2: 인터페이스 정의 — 위험도 낮음
각 추출된 클래스에 명확한 인터페이스(Protocol) 정의하여 의존성 주입 가능하게 만듦.

#### Phase 3: 테스트 작성 — 전제 조건
각 분리된 컴포넌트에 대한 단위 테스트 작성. 특히 ReActLoop의 도구 실행 루프와 StreamFilter의 XML 태그 필터링은 테스트 가능해야 함.

### 주의사항
- `process()`가 `AsyncGenerator`를 반환하므로, 분리 시에도 yield 체인이 올바르게 작동하는지 확인 필요
- 지연 import는 순환 의존 때문이므로, 의존성 주입으로 전환 시 app.py의 lifespan에서 주입 순서 정리 필요

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `process()` 분리 (ReActLoop 추출) | **높음** | 339줄 메서드, AsyncGenerator yield 체인, 도구 루프 상태 관리. 테스트 없이 안전한 분리가 어려움 |
| `_build_context_and_prompt()` 분리 (ContextBuilder) | **중간** | 비교적 독립적인 함수. MemoryManager로 위임 가능하나 메모리 접근 패턴 통일 필요 |
| `self.state` None 체크 정리 | **낮음** | Null Object 패턴 적용은 기계적 작업. AppState 타입 힌트도 단순 |
| XML 태그 패턴 동적 생성 | **낮음** | MCP 도구 레지스트리에서 이름 목록 가져오는 것은 간단 |
| 메모리 영속화 분리 (MemoryPersister) | **낮음** | 이미 별도 메서드로 나뉘어 있어 클래스 추출만 하면 됨 |
| `except Exception` 범위 좁히기 | **낮음** | 기계적 작업이지만 14곳을 모두 검토해야 함 |
| 지연 import → 의존성 주입 | **중간** | 순환 의존 해소가 선행되어야 하며 app.py 초기화 순서 조정 필요 |
| `ClassificationResult` 정리 | **낮음** | 미사용 코드 제거 또는 실제 분류 로직 구현 |
