# 16. app.py 전역 변수와 lifespan 혼재

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/app.py`, `backend/api/deps.py`, `backend/api/__init__.py`, `backend/api/mcp.py`, `backend/api/openai.py`, `backend/api/memory.py`, `backend/api/status.py`, `backend/protocols/mcp/memory_server.py`, `backend/core/chat_handler.py`, `backend/core/services/react_service.py`, `backend/core/services/tool_service.py`

## 요약

`app.py`는 모듈 레벨 전역 변수(`gemini_model`, `memory_manager`, `long_term_memory`)를 `None`으로 선언하고 `init_state()`에 `None`을 전달한 뒤, `lifespan()` 내에서 `global`로 실제 객체를 재할당하는 이중 초기화 패턴을 사용합니다. 이로 인해 `AppState` dataclass와 모듈 전역 변수 사이에 상태 불일치가 발생하며, shutdown 로직에서도 `state.background_tasks`와 `_background_tasks` 사이의 폴백 분기가 존재합니다. `app.state.shutting_down`은 설정되지만 어디에서도 조회되지 않는 dead 상태입니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **이중 상태 관리: 모듈 전역 vs AppState**: `app.py:228-230`에서 `gemini_model = None`, `memory_manager = None`, `long_term_memory = None`을 모듈 레벨에 선언하고, `app.py:238-243`에서 `init_state()`로 `None`을 `AppState`에 전달합니다. 이후 `lifespan()` (`app.py:44,56-58`)에서 `global`로 모듈 전역 변수에 실제 객체를 할당하고, `app.py:80-82`에서 `state`에도 동일 객체를 다시 설정합니다. (`backend/app.py:38-39,44,56-58,80-82,228-243`)
  - 영향: 모듈 전역 변수와 `AppState`의 동일 속성이 **별도의 참조**로 존재합니다. `lifespan()` 이후에는 동기화되지만, 이 사이 기간(모듈 로드 ~ lifespan 시작)에 `state.memory_manager`는 `None`입니다. 다른 모듈이 import 시점에 `get_state().memory_manager`를 캐싱하면 영구적으로 `None`을 참조할 수 있습니다. `memory_server.py:12-15,17-33`이 바로 이 패턴으로, 최초 호출 시 `None`이면 이후에도 업데이트되지 않습니다.
  - 개선안: 모듈 전역 변수를 제거하고 `AppState`만을 단일 진실 원천(Single Source of Truth)으로 사용합니다:
    ```python
    # app.py — 전역 변수 제거
    # 삭제: gemini_model = None / memory_manager = None / long_term_memory = None
    # 삭제: init_state(memory_manager=..., long_term_memory=..., gemini_model=...)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state = get_state()
        state.shutdown_event = asyncio.Event()
        state.background_tasks = []

        try:
            state.gemini_model = GenerativeModelWrapper(client_or_model=DEFAULT_GEMINI_MODEL)
            state.memory_manager = MemoryManager(model=state.gemini_model)
            state.long_term_memory = state.memory_manager.long_term
        except Exception as e:
            _log.warning("APP MemoryManager init failed", error=str(e))

        # ... 나머지 초기화 ...
        yield
        # ... shutdown ...
    ```

- **`init_state()`에 `None` 전달 후 lifespan에서 재할당하는 시간차 문제**: `app.py:238-243`에서 `init_state(memory_manager=None, ...)`가 모듈 로드 시 호출됩니다. FastAPI가 `lifespan()`을 실행하기 전까지 `AppState`의 모든 핵심 서비스가 `None`입니다. 이 시간 동안 `app.py:224`의 `ensure_data_directories()`와 `app.py:226`의 `IdentityManager` 생성은 문제없지만, 만약 라우터 초기화에서 `get_state()`를 호출하면 `None`을 받게 됩니다. (`backend/app.py:238-243`, `backend/api/deps.py:98-107`)
  - 영향: 현재는 모든 API 핸들러가 요청 시점에 `get_state()`를 호출하므로 즉각적 버그는 없습니다. 그러나 `memory_server.py:17-33`의 `_get_memory_components()`는 최초 호출 시 결과를 전역 변수에 캐싱하므로, lifespan 이전에 호출되면 영구적으로 `None`을 반환합니다.
  - 개선안: `memory_server.py`에서 캐싱을 제거하고 매번 `get_state()`에서 가져오거나, `None`일 때 재시도하도록 수정:
    ```python
    # memory_server.py — 캐싱 제거, 매번 조회
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

### MEDIUM

- **shutdown 시 `background_tasks` 폴백 분기**: `app.py:114`에서 `task_list = state.background_tasks if getattr(state, "background_tasks", None) is not None else _background_tasks`로 폴백합니다. `state.background_tasks`는 `app.py:48`에서 `_background_tasks`와 **동일한 리스트 객체**로 설정되므로, 이 분기는 불필요합니다. 그러나 이 폴백의 존재 자체가 두 상태 저장소 간 신뢰 부재를 드러냅니다. (`backend/app.py:114`)
  - 개선안: `_background_tasks` 전역 변수를 제거하고 `state.background_tasks`만 사용. 폴백 분기 삭제.

- **`app.state.shutting_down` dead 상태**: `app.py:51`에서 `app.state.shutting_down = False`로 설정하고, `app.py:106`에서 `True`로 변경합니다. 그러나 프로젝트 전체에서 `shutting_down`을 **조회하는 코드가 없습니다**. Grep 결과 이 두 줄만 존재합니다. (`backend/app.py:51,106`)
  - 개선안: 실제로 shutdown을 감지해야 하는 곳(스트리밍 핸들러, 백그라운드 태스크)에서 활용하거나, 사용하지 않는다면 제거.

- **`_shutdown_event` 이중화**: `app.py:38`에서 모듈 전역 `_shutdown_event`를 선언하고, `app.py:49`에서 `state.shutdown_event`에도 같은 객체를 할당합니다. `_shutdown_event.set()`(`app.py:107`)은 모듈 전역을 통해 호출되지만, `state.shutdown_event`를 통해서도 접근 가능합니다. 동일 객체의 이중 참조는 혼란을 유발합니다. (`backend/app.py:38,45,49,107`)
  - 개선안: 모듈 전역 `_shutdown_event`를 제거하고 `state.shutdown_event`만 사용.

- **`identity_manager`만 lifespan 외부에서 초기화**: `app.py:226`에서 `identity_manager = IdentityManager(...)`가 모듈 로드 시점에 생성됩니다. 반면 `gemini_model`, `memory_manager`는 lifespan 내에서 생성됩니다. 이 불일치는 초기화 책임이 두 곳(모듈 레벨, lifespan)에 분산되었음을 의미합니다. (`backend/app.py:226`)
  - 개선안: 모든 서비스 초기화를 `lifespan()` 안으로 통합하여 초기화 순서를 명확하게 만듦.

- **예외 핸들러의 내부 정보 노출 (17번과 중복 관찰)**: `app.py:212-222`에서 글로벌 예외 핸들러가 `str(exc)`, `type(exc).__name__`, `request.url.path`를 JSON 응답에 포함합니다. 이 분석의 주제와 직접 관련은 없으나, app.py 분석 중 확인된 사항입니다. (`backend/app.py:212-222`)
  - 개선안: 17번 리포트에서 다룸.

### LOW

- **lifespan 내 지연 import**: `app.py:64-65`에서 `from pathlib import Path`와 `from backend.core.utils.file_utils import startup_cleanup`를 lifespan 함수 내에서 import합니다. `Path`는 표준 라이브러리이므로 모듈 상단에서 import하는 것이 관례입니다. (`backend/app.py:64-65`)

- **`ChatHandler` 생성이 매 요청마다 발생**: `openai.py:92`에서 `ChatHandler(get_state())`가 매 API 호출마다 새로 생성됩니다. `ChatHandler`는 stateless orchestrator 역할이므로 현재 구조상 문제는 없지만, 서비스 재생성 비용이 발생합니다. (`backend/api/openai.py:92`)

## 개선 제안

### 핵심 리팩토링: 단일 상태 컨테이너로 통합

현재 상태 관리의 근본 문제는 **모듈 전역 변수**와 **AppState dataclass** 사이의 이중성입니다. 이를 해결하려면:

1. **모듈 전역 변수 완전 제거**: `app.py`의 `gemini_model`, `memory_manager`, `long_term_memory`, `_shutdown_event`, `_background_tasks`를 모두 제거합니다.

2. **`lifespan()`이 유일한 초기화 지점**: 모든 서비스 생성(`IdentityManager` 포함)을 `lifespan()` 안으로 이동합니다. `init_state()` 호출을 제거하거나 lifespan 내부로 이동합니다.

3. **`init_state()` 역할 재정의**: 현재 `init_state()`는 kwargs를 받아 `setattr`로 설정하는 범용 함수입니다. lifespan에서 직접 `state.xxx = yyy`로 설정하면 `init_state()`는 불필요합니다.

4. **`memory_server.py`의 캐싱 제거**: 전역 캐시 대신 매번 `get_state()`를 조회하도록 변경하여 stale reference 문제를 방지합니다.

리팩토링 후 `app.py`의 구조:

```python
# 모듈 레벨: FastAPI 앱 + 미들웨어 + 라우터 등록만
app = FastAPI(title="axnmihn API", version=APP_VERSION, lifespan=lifespan)

@asynccontextmanager
async def lifespan(app: FastAPI):
    state = get_state()

    # 모든 초기화를 여기서 수행
    state.identity_manager = IdentityManager(persona_path=str(PERSONA_PATH))
    state.shutdown_event = asyncio.Event()
    state.background_tasks = []

    try:
        state.gemini_model = GenerativeModelWrapper(...)
        state.memory_manager = MemoryManager(model=state.gemini_model)
        state.long_term_memory = state.memory_manager.long_term
    except Exception as e:
        _log.warning(...)

    # ... startup 로직 ...
    yield
    # ... shutdown 로직 (state.xxx만 참조) ...
```

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| 모듈 전역 변수 제거 + lifespan 통합 | **낮음** | `global` 선언 제거, lifespan 내에서 `state.xxx =` 직접 할당으로 변경. 외부에서 모듈 전역을 import하는 곳이 없음 |
| `_background_tasks` 폴백 분기 제거 | **낮음** | 한 줄 수정 |
| `app.state.shutting_down` 활용 또는 제거 | **낮음** | 2줄 삭제 또는 스트리밍 핸들러에서 조회 로직 추가 |
| `_shutdown_event` → `state.shutdown_event` 통합 | **낮음** | 모듈 전역 제거와 함께 처리 |
| `memory_server.py` 캐싱 제거 | **낮음** | 전역 변수 4개 제거, 함수 내에서 매번 `get_state()` 호출 |
| `identity_manager` 초기화를 lifespan으로 이동 | **낮음** | 2줄 이동 |
| `init_state()` 제거 | **낮음** | 호출처 1곳 삭제, 함수 정의 삭제. `__init__.py`에서 export 제거 |
