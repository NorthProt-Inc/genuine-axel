# 11. 전역 가변 상태 (Global Mutable State)

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/app.py`, `backend/api/deps.py`, `backend/protocols/mcp/async_research.py`, `backend/protocols/mcp/research_server.py`, `backend/protocols/mcp/memory_server.py`, `backend/core/mcp_client.py`, `backend/core/utils/gemini_wrapper.py`, `backend/core/utils/rate_limiter.py`, `backend/core/utils/task_tracker.py`, `backend/core/utils/async_utils.py`, `backend/core/utils/file_utils.py`, `backend/media/qwen_tts.py`

## 요약

프로젝트 전반에 걸쳐 **13개 이상의 모듈 레벨 전역 가변 변수**와 **15개소의 `global` 키워드 사용**이 확인됩니다. 가장 심각한 문제는 `app.py`에서 `None`으로 초기화한 전역 변수를 `init_state()`에 전달한 뒤, lifespan에서 `global`로 재할당하지만 이미 전달된 `AppState`에는 `None`이 남아있어 이중 업데이트가 필요한 구조입니다. 또한 `async_research.py`의 `_active_tasks` dict은 완료된 태스크 정리에 race condition 가능성이 있으며, 다수의 싱글톤 패턴이 일관성 없이 구현되어 있습니다.

## 발견사항

### CRITICAL

없음

### HIGH

- **`app.py` 이중 상태 관리 — 전역 변수와 AppState 동시 존재**: `app.py:227-242`에서 `gemini_model = None`, `memory_manager = None`, `long_term_memory = None`을 모듈 레벨에 선언하고, `init_state()`에 이 `None` 값을 전달합니다. 이후 `lifespan()` (`app.py:43-81`)에서 `global` 키워드로 이 전역 변수를 실제 객체로 재할당하면서, **동시에** `state.memory_manager = memory_manager` (`app.py:79-81`)로 AppState도 업데이트합니다. (`backend/app.py:43,55-57,79-81,227-242`)
  - 영향: 모듈 로드 시점(227-242줄)과 lifespan 시점(43-81줄)에서 동일한 상태가 두 곳에 존재합니다. lifespan의 `state.xxx = xxx` 업데이트를 빠뜨리면 `get_state()`를 통해 접근하는 17개 API 핸들러가 `None`을 받게 됩니다. 이는 silent failure로 이어지며, `app.py`의 shutdown 로직(123-145줄)은 `get_state()`가 아닌 모듈 레벨 전역 변수를 직접 참조하여 두 상태가 불일치할 수 있습니다.
  - 개선안: 전역 변수를 완전히 제거하고 AppState만 사용합니다.
    ```python
    # app.py — 개선안
    # 모듈 레벨 전역 변수 제거 (gemini_model, memory_manager, long_term_memory 삭제)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = get_state()
        state.shutdown_event = asyncio.Event()
        state.background_tasks = []

        try:
            model_config = get_model()
            state.gemini_model = GenerativeModelWrapper(client_or_model=model_config.model)
            state.memory_manager = MemoryManager(model=state.gemini_model)
            state.long_term_memory = state.memory_manager.long_term
        except Exception as e:
            _log.warning("APP MemoryManager init failed", error=str(e))

        # ... 나머지 startup 로직에서 state.xxx로 접근 ...

        yield

        # shutdown에서도 state.xxx로 접근
        if state.memory_manager:
            state.memory_manager.working.save_to_disk()
            # ...
    ```

- **`init_state()`에 `None` 전달 후 lifespan에서 별도 업데이트 — 초기화 순서 의존성**: `app.py:237-242`의 `init_state()` 호출 시 `gemini_model`, `memory_manager`, `long_term_memory`는 모두 `None`입니다. 실제 초기화는 `lifespan()` 내에서 이루어지며, `deps.py:104`의 `init_state()`는 이미 생성된 `AppState` 싱글톤의 속성을 `setattr`로 설정합니다. `lifespan()` 내에서 `state = get_state()`로 동일 객체를 받아 `state.memory_manager = memory_manager`로 재설정하므로, 최종적으로는 동작하지만 **초기화 흐름이 불명확**합니다. (`backend/app.py:237-242`, `backend/api/deps.py:98-107`)
  - 영향: `init_state()`에서 `None`으로 설정 → lifespan에서 실제 객체로 덮어쓰기 → 이 사이 시점에 `get_state()`를 호출하면 `None`을 받음. 현재는 lifespan 이전에 API 요청이 불가능하므로 실제 버그는 아니나, `init_state()` 호출 자체가 오해의 소지가 큽니다 (`identity_manager`만 유효한 값).
  - 개선안: `init_state()`를 lifespan 내부에서 한 번만 호출하거나, `identity_manager`만 별도로 설정합니다.
    ```python
    # lifespan 내부에서만 init_state() 호출
    async def lifespan(app: FastAPI):
        # ... 초기화 코드 ...
        init_state(
            memory_manager=memory_manager,
            long_term_memory=long_term_memory,
            identity_manager=identity_manager,
            gemini_model=gemini_model,
        )
        yield
    ```

- **`_active_tasks` dict의 비보호 concurrent 접근**: `async_research.py:48`에서 `_active_tasks: dict[str, asyncio.Task] = {}`를 모듈 레벨에 선언합니다. `dispatch_async_research()` (`async_research.py:316`)에서 추가, `_run_research_pipeline()` finally 블록 (`async_research.py:292-293`)에서 삭제, `get_active_research_tasks()` (`async_research.py:56-63`)에서 순회합니다. asyncio는 단일 스레드이므로 dict의 기본 연산은 안전하나, **`get_active_research_tasks()`가 dict를 순회하는 도중 finally 블록에서 `del _active_tasks[task_id]`가 실행되면 RuntimeError가 발생**할 수 있습니다. (`backend/protocols/mcp/async_research.py:48,62,292-293,316`)
  - 영향: `dict changed size during iteration` RuntimeError 가능성. asyncio 단일 스레드에서는 매우 드물지만, `get_active_research_tasks()`가 list comprehension 내에서 `task.done()`, `task.cancelled()`를 호출할 때 이벤트 루프가 전환될 수 있는 이론적 가능성이 있습니다.
  - 개선안: 순회 시 복사본을 사용합니다.
    ```python
    def get_active_research_tasks() -> list[dict]:
        return [
            {"task_id": tid, "done": task.done(), "cancelled": task.cancelled()}
            for tid, task in list(_active_tasks.items())  # .items() 복사
        ]
    ```

### MEDIUM

- **싱글톤 패턴 일관성 부재 — 8가지 다른 구현**: 프로젝트 전반에 싱글톤/지연 초기화 패턴이 최소 8곳에서 사용되지만 구현 방식이 제각각입니다:
  1. `gemini_wrapper.py:16-28` — `threading.Lock` + double-checked locking
  2. `rate_limiter.py:85-99` — 단순 `global` + `None` 체크 (lock 없음)
  3. `task_tracker.py:278-286` — `global` + `None` 체크 (lock 없음)
  4. `mcp_client.py:255-266` — `global` + `None` 체크 (lock 없음)
  5. `async_utils.py:12-20` — `global` + `None` 체크 (lock 없음)
  6. `file_utils.py:86-93` — `global` + `None` 체크 (lock 없음)
  7. `research_server.py:38-49` — `global` + `None` 체크 (lock 없음)
  8. `research_server.py:186-193` — `global` + `None` 체크 (async 컨텍스트)
  - 개선안: 공통 싱글톤 유틸리티를 만들어 통일합니다.
    ```python
    # backend/core/utils/singleton.py
    from typing import TypeVar, Callable, Optional
    import threading

    T = TypeVar("T")

    class Lazy:
        """Thread-safe lazy singleton factory."""
        def __init__(self, factory: Callable[[], T]):
            self._factory = factory
            self._instance: Optional[T] = None
            self._lock = threading.Lock()

        def get(self) -> T:
            if self._instance is None:
                with self._lock:
                    if self._instance is None:
                        self._instance = self._factory()
            return self._instance

        def reset(self):
            """Reset for testing."""
            with self._lock:
                self._instance = None

    # 사용 예:
    _embedding_limiter = Lazy(lambda: TokenBucketRateLimiter(...))
    limiter = _embedding_limiter.get()
    ```

- **`memory_server.py` — 전역 캐시가 AppState와 불일치 가능**: `memory_server.py:12-15`에서 `_memory_manager`, `_long_term_memory`, `_session_archive`, `_graph_rag` 4개를 모듈 레벨 `None`으로 선언하고, `_get_memory_components()` (`memory_server.py:17-33`)에서 `get_state()`로 가져와 전역 변수에 캐싱합니다. 이후 `app.py`에서 `MemoryManager`가 재초기화되어도 이 캐시는 갱신되지 않습니다. (`backend/protocols/mcp/memory_server.py:12-33`)
  - 개선안: 캐시를 제거하고 매번 `get_state()`에서 직접 접근합니다.
    ```python
    def _get_memory_components():
        from backend.api.deps import get_state
        state = get_state()
        return (
            state.memory_manager,
            state.long_term_memory,
            state.memory_manager.session_archive if state.memory_manager else None,
            state.memory_manager.graph_rag if state.memory_manager else None,
        )
    ```

- **`research_server.py` — `browser_manager` 이중 정리 경로**: `browser_manager` 전역 변수가 `shutdown` 이벤트 핸들러 (`research_server.py:816-818`)와 `cleanup()` 함수 (`research_server.py:826-829`) 두 곳에서 정리됩니다. 두 경로 모두 `global browser_manager`로 접근하나, 한쪽에서 `close()` 후 `None`으로 리셋하지 않아 **이중 close** 가능성이 있습니다. (`backend/protocols/mcp/research_server.py:816-818,826-829`)
  - 개선안: close 후 `None`으로 리셋합니다.
    ```python
    async def shutdown():
        global browser_manager
        if browser_manager:
            await browser_manager.close()
            browser_manager = None
    ```

- **테스트 격리 불가능**: 모든 싱글톤/전역 상태에 `reset()` 또는 의존성 주입 메커니즘이 없어 단위 테스트 격리가 불가능합니다. `AppState` dataclass는 교체 가능하나, `deps.py:88`의 모듈 레벨 `state = AppState()`는 `global state`로만 교체할 수 있어 테스트 간 상태 누수가 발생합니다. (`backend/api/deps.py:88,104`, `backend/core/utils/gemini_wrapper.py:16-28` 외 전체)
  - 개선안: `AppState`에 `reset()` 메서드 추가, 또는 `get_state()`를 FastAPI Dependency로 전환합니다.
    ```python
    # deps.py — 테스트 가능한 구조
    _state_override: Optional[AppState] = None

    def get_state() -> AppState:
        return _state_override or state

    def override_state(new_state: AppState):
        """For testing only."""
        global _state_override
        _state_override = new_state
    ```

- **`app.py:37-38` — `_shutdown_event`과 `_background_tasks`가 lifespan과 모듈 레벨에 이중 존재**: `_shutdown_event`과 `_background_tasks`가 모듈 레벨 (`app.py:37-38`)에 선언되고 lifespan에서 재할당되며 (`app.py:44-45`), AppState에도 저장됩니다 (`app.py:47-48`). shutdown 로직 (`app.py:113`)에서는 `state.background_tasks`와 `_background_tasks`를 fallback 체인으로 사용하여 어느 것이 진실의 소스(source of truth)인지 불명확합니다. (`backend/app.py:37-38,44-48,113`)
  - 개선안: AppState만을 유일한 source of truth로 사용합니다.

### LOW

- **`gemini_wrapper.py:22` — 지연된 Lock 생성의 race condition**: `_singleton_lock`이 `None`으로 시작하고 (`gemini_wrapper.py:17`), `get_gemini_wrapper()` 호출 시 `_singleton_lock is None`이면 생성합니다 (`gemini_wrapper.py:22-23`). 두 스레드가 동시에 이 조건을 통과하면 각각 다른 Lock 객체를 생성할 수 있어 double-checked locking의 의미가 사라집니다. (`backend/core/utils/gemini_wrapper.py:16-28`)
  - 개선안: Lock을 모듈 로드 시 즉시 생성합니다.
    ```python
    import threading
    _singleton_lock = threading.Lock()
    _singleton_wrapper: Optional["GenerativeModelWrapper"] = None
    ```

- **`async_utils.py:12` — asyncio.Semaphore의 이벤트 루프 바인딩**: `_thread_semaphore`가 `None`으로 시작하고 첫 호출 시 생성됩니다. asyncio.Semaphore는 특정 이벤트 루프에 바인딩되므로, 루프가 재생성되면 (예: 테스트 환경) 사용 불가합니다. (`backend/core/utils/async_utils.py:12-20`)

## 개선 제안

### 1. AppState를 유일한 상태 컨테이너로 통합

현재 상태가 3곳에 분산되어 있습니다:
1. `app.py` 모듈 레벨 전역 변수 (`gemini_model`, `memory_manager`, `long_term_memory`, `_shutdown_event`, `_background_tasks`)
2. `AppState` dataclass (`deps.py:58-87`)
3. 각 모듈의 로컬 캐시 (`memory_server.py:12-15`, `research_server.py:186` 등)

**권장**: `app.py`의 전역 변수 5개를 삭제하고, lifespan에서 `get_state()`로 얻은 AppState에만 쓰기/읽기합니다. `memory_server.py`의 캐시도 제거합니다.

### 2. 싱글톤 패턴 표준화

8개의 서로 다른 싱글톤 구현을 `Lazy[T]` 또는 `@singleton` 데코레이터로 통일합니다. thread-safe가 필요한 경우 (`gemini_wrapper`)와 asyncio 전용 (`async_utils`)을 구분합니다.

### 3. 테스트 가능성 확보

- `AppState.reset()` 메서드 추가
- 각 싱글톤에 `_reset()` 함수 추가 (테스트 전용)
- `get_state()`를 FastAPI Dependency로 전환하여 테스트 시 `app.dependency_overrides`로 교체 가능하게 합니다

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `app.py` 전역 변수 제거 → AppState 통합 | 중간 | shutdown/startup 로직 전체를 `state.xxx`로 전환 필요. 17개 API 핸들러는 이미 `get_state()` 사용 중이므로 영향 적음 |
| `init_state()` 호출 위치 정리 | 낮음 | lifespan 내부로 이동만 하면 됨 |
| `_active_tasks` dict 순회 안전성 | 낮음 | `list()` 복사 한 줄 추가 |
| 싱글톤 패턴 통일 | 중간 | 8개 모듈 수정 필요하나 각각은 단순한 변경 |
| `memory_server.py` 캐시 제거 | 낮음 | `_get_memory_components()`만 수정 |
| `research_server.py` 이중 정리 수정 | 낮음 | `None` 리셋 한 줄 추가 |
| 테스트 격리 인프라 구축 | 높음 | `AppState`, 모든 싱글톤에 reset 메커니즘 필요. #19(테스트 부재)와 연계 |
| `gemini_wrapper.py` Lock 수정 | 낮음 | Lock을 모듈 레벨로 이동만 하면 됨 |
