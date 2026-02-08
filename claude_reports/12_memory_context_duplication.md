# 12. MemoryManager 동기/비동기 컨텍스트 빌드 중복

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/memory/unified.py`, `backend/core/services/context_service.py`, `backend/core/chat_handler.py`, `backend/memory/temporal.py`, `backend/memory/memgpt.py`, `backend/protocols/mcp/server.py`

## 요약

`_build_smart_context_sync()`와 `_build_smart_context_async()`가 동일한 비즈니스 로직을 동기/비동기 두 버전으로 유지하고 있으며, **async 버전은 어디에서도 호출되지 않는 완전한 dead code**입니다. 더 나아가 `ContextService.build()`가 이미 동일 로직을 더 정교하게 재구현하고 있어, 실질적으로 **3중 중복**이 발생하고 있습니다.

## 발견사항

### CRITICAL

(없음)

### HIGH

- **`_build_smart_context_async()` 128줄 dead code**: async 버전 메서드(unified.py:213-341)가 프로젝트 전체에서 **단 한 번도 호출되지 않습니다**. `build_smart_context()`(unified.py:122-134)는 항상 `_build_smart_context_sync()`만 호출하며, `ChatHandler`는 `ContextService.build()`를 사용합니다. (`backend/memory/unified.py:213-341`)
  - 영향: 128줄의 유지보수 부담. sync 버전 변경 시 async 버전도 함께 수정해야 한다는 착각 유발. 실제로 두 버전 간 이미 동작 차이(로깅, 에러 처리)가 발생해 있음.
  - 개선안: `_build_smart_context_async()` 메서드 전체 삭제
    ```python
    # unified.py에서 213~341줄 전체 삭제
    # _build_smart_context_async 메서드 제거
    # 모듈 상단의 import asyncio도 async 메서드가 없다면 불필요
    ```

- **3중 컨텍스트 빌드 중복**: 동일한 "메모리 소스로부터 컨텍스트 조립" 로직이 3곳에 존재합니다. (`backend/memory/unified.py:136-211`, `backend/memory/unified.py:213-341`, `backend/core/services/context_service.py:147-274`)
  - 영향: 메모리 조회 전략 변경 시 최소 2곳(sync + ContextService)을 수정해야 하는 **샷건 수술** 유발. 각 구현의 동작이 미묘하게 다름(아래 상세 비교 참고).
  - 개선안: `ContextService`를 유일한 컨텍스트 빌드 경로로 통합. `_build_smart_context_sync()`는 `ContextService`에 위임하거나, MCP 서버가 직접 `ContextService`를 사용하도록 변경.
    ```python
    # Option A: _build_smart_context_sync()를 ContextService 래퍼로 변경
    def _build_smart_context_sync(self, current_query: str) -> str:
        """Delegate to ContextService for single-source-of-truth context building."""
        import asyncio
        service = ContextService(
            memory_manager=self,
            long_term_memory=self.long_term,
        )
        # 동기 컨텍스트에서 비동기 호출
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                service.build(current_query, tier="standard", model_config=...)
            )
            return result.system_prompt
        finally:
            loop.close()

    # Option B (권장): MCP 서버가 ContextService를 직접 사용
    # backend/protocols/mcp/server.py:441
    # context = await self.context_service.build(query, ...)
    ```

### MEDIUM

- **sync/async 간 동작 불일치 (5곳)**: 두 메서드는 "같은 로직"이지만 실제로 여러 차이가 있어 유지보수 시 혼란 유발 (`backend/memory/unified.py:136-341`)
  - 차이 1: **에러 로깅 레벨 불일치** — sync에서 MemGPT 실패 시 `_log.warning`(167줄), async에서도 `_log.warning`(247줄)이지만, session archive 실패 시 sync는 `_log.debug`(191줄), async도 `_log.debug`(281줄) — 이 경우는 일치하나, GraphRAG에서 sync는 `_log.debug`(199줄), async도 `_log.debug`(293줄)
  - 차이 2: **async 버전에 추가 로깅** — async에만 `_log.debug("MEM longterm_qry", ...)` (320줄), `_log.debug("MEM graph_qry", ...)` (329줄), `_log.debug("MEM context_truncated", ...)` (340줄) 존재. sync에는 이 로그가 없음.
  - 차이 3: **async 버전에 temporal_filter 디버그 로그** — async에만 `if temporal_filter: _log.debug("Temporal filter detected", ...)` (234-235줄) 존재
  - 차이 4: **async에서 `asyncio.gather()` 병렬 실행** — async 버전(296-301줄)은 memgpt, session, graph를 `asyncio.gather()`로 병렬 실행하지만, sync 버전(148-199줄)은 순차 실행. 그러나 async 내부의 각 작업이 `asyncio.to_thread()`를 사용하므로 실질적으로 스레드 풀에서 병렬 실행됨.
  - 차이 5: **async 버전의 이중 None 체크** — `if session_context:` 후 다시 `if session_context and ...`(322-323줄) 중복 체크
  - 개선안: dead code인 async 버전 삭제로 근본 해결

- **truncation 로직 3중 중복**: 동일한 `"\n... (truncated)"` 접미사 + `max_chars` 기반 절단 로직이 unified.py 내 2곳(202-209줄, 332-340줄)과 context_service.py의 `_truncate_text()` 함수(47-61줄)에서 반복됩니다. (`backend/memory/unified.py:202-209`, `backend/memory/unified.py:332-340`, `backend/core/services/context_service.py:47-61`)
  - 개선안: `_truncate_text()`를 공통 유틸리티로 추출하여 단일 구현 사용
    ```python
    # backend/core/utils/text.py (또는 기존 유틸리티에 추가)
    def truncate_text(text: str, max_chars: int, label: str = "") -> str:
        if not text or max_chars <= 0 or len(text) <= max_chars:
            return text or ""
        suffix = "\n... (truncated)"
        keep = max_chars - len(suffix)
        if keep <= 0:
            return text[:max_chars]
        return text[:keep].rstrip() + suffix
    ```

- **`import asyncio` 모듈 내 4회 중복**: 모듈 레벨(1줄)에서 이미 import했으나, 함수 내부에서 3회 더 반복 import합니다. (`backend/memory/unified.py:1,218,468,626`)
  - 개선안: 함수 내부 `import asyncio` 3개소 삭제. 모듈 레벨 import만 유지.

- **`ContextService`와 `_build_smart_context_sync`의 temporal query 처리 불일치**: sync 메서드(150-151줄)는 `parse_temporal_query()`로 temporal filter를 추출하여 memgpt와 session archive에 전달하지만, `ContextService._add_longterm_context()`(276-323줄)는 temporal filter를 전혀 사용하지 않습니다. (`backend/memory/unified.py:150-151` vs `backend/core/services/context_service.py:276-323`)
  - 영향: `ContextService` 경로(ChatHandler 메인 파이프라인)에서는 "어제 뭐 했지?", "지난주 대화" 같은 시간 기반 쿼리의 temporal boost가 적용되지 않음. MCP 서버의 `build_smart_context()` 경로에서만 temporal filter 동작.
  - 개선안: `ContextService._add_longterm_context()`에 temporal filter 지원 추가
    ```python
    async def _add_longterm_context(
        self,
        optimizer: ContextOptimizer,
        user_input: str,
        config: Dict[str, Any]
    ) -> None:
        from backend.memory.temporal import parse_temporal_query
        temporal_filter = parse_temporal_query(user_input)

        # memgpt.context_budget_select()에 temporal_filter 전달
        selected_memories, used_tokens = memgpt.context_budget_select(
            query=user_input,
            token_budget=token_budget,
            temporal_filter=temporal_filter
        )
    ```

- **`ContextService`와 sync 메서드의 session archive 호출 불일치**: sync 메서드(169-186줄)는 temporal filter에 따라 `get_sessions_by_date()` vs `get_recent_summaries()`를 분기하지만, `ContextService`(206-221줄)는 항상 `get_recent_summaries()`만 호출합니다. (`backend/memory/unified.py:169-186` vs `backend/core/services/context_service.py:206-221`)
  - 영향: ChatHandler 경로에서 날짜 기반 세션 검색 불가

### LOW

- **`build_smart_context()` public 메서드의 불필요한 래핑**: `build_smart_context()`(122-134줄)는 단순히 `_build_smart_context_sync()`를 호출하는 1줄짜리 래퍼입니다. 원래 async 분기가 있었을 것으로 추정되나, 현재는 불필요한 간접 호출. (`backend/memory/unified.py:122-134`)

- **async 내부 함수 정의의 복잡성**: `_build_smart_context_async` 내부에 `get_memgpt_context()`, `get_session_archive_context()`, `get_graph_context()` 3개의 내부 async 함수가 정의되어 있으나(237-294줄), 이는 호출되지 않는 dead code의 일부. (`backend/memory/unified.py:237-294`)

## sync vs async 상세 비교표

| 항목 | `_build_smart_context_sync` | `_build_smart_context_async` | `ContextService.build()` |
|------|---------------------------|----------------------------|--------------------------|
| 호출자 | `mcp/server.py:441` | **없음 (dead code)** | `chat_handler.py:197` |
| 실행 모델 | 순차 동기 | `asyncio.gather` 병렬 | 순차 async |
| Temporal filter | O (parse_temporal_query) | O (parse_temporal_query) | **X (미구현)** |
| Session date 분기 | O (exact/range/default) | O (exact/range/default) | **X (항상 recent)** |
| MemGPT 호출 | 직접 동기 | `asyncio.to_thread` | 직접 동기 |
| GraphRAG 호출 | `query_sync` 직접 | `asyncio.to_thread(query_sync)` | `query_sync` 직접 |
| Truncation | 인라인 로직 | 인라인 로직 (동일) | `_truncate_text()` 함수 |
| 추가 로깅 | 최소 | 풍부 (3개 추가) | 중간 |
| 코드 행 수 | 76줄 | 128줄 | 148줄 |

## 개선 제안

### 단기 (즉시 가능)
1. **`_build_smart_context_async()` 삭제** — 128줄의 dead code 제거. 호출자가 없으므로 부작용 없음.
2. **함수 내부 `import asyncio` 3개소 제거** — 모듈 레벨 import로 충분.

### 중기 (ContextService 강화)
3. **`ContextService`에 temporal filter 지원 추가** — `parse_temporal_query()` 호출과 session archive의 날짜 기반 분기 로직을 `ContextService`로 이전. 이렇게 하면 ChatHandler 메인 경로에서도 시간 기반 쿼리가 정상 동작.
4. **truncation 로직 공통 유틸리티 추출** — `context_service.py`의 `_truncate_text()`를 `backend/core/utils/text.py`로 이동하고, unified.py의 인라인 truncation을 이 함수로 대체.

### 장기 (아키텍처 통합)
5. **`_build_smart_context_sync()`를 `ContextService`에 위임** — MCP 서버도 `ContextService`를 사용하도록 변경하여 컨텍스트 빌드 경로를 단일화. 이렇게 하면 메모리 조회 전략 변경 시 1곳만 수정하면 됨.

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `_build_smart_context_async()` 삭제 | **쉬움** | 호출자 없음. 단순 삭제 |
| 함수 내부 `import asyncio` 제거 | **쉬움** | 모듈 레벨에 이미 존재 |
| truncation 유틸리티 추출 | **쉬움** | 순수 함수, 부작용 없음 |
| ContextService에 temporal filter 추가 | **중간** | 기능 추가이지만 패턴이 sync 버전에 이미 구현되어 있어 복사+적용 |
| 컨텍스트 빌드 경로 단일화 | **중간~어려움** | MCP 서버의 동기 컨텍스트에서 async ContextService 호출 시 이벤트 루프 충돌 가능. `asyncio.to_thread` 또는 sync 래퍼 필요 |
