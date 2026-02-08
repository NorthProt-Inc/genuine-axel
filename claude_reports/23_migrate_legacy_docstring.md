# 23. `migrate_legacy_data` docstring 위치 오류 및 unified.py 가독성

> 분석 날짜: 2026-02-07
> 분석 범위: `backend/memory/unified.py` (489줄), `backend/memory/current.py`, `backend/memory/recent/`, `backend/memory/permanent/`, `backend/memory/memgpt.py`, `backend/memory/graph_rag.py`

## 요약

원래 지적된 `migrate_legacy_data`의 docstring 위치 오류는 **이미 수정**되었습니다 (docstring이 함수 정의 직후 올바른 위치에 존재). 그러나 `unified.py` 전반에서 `_build_smart_context_sync` 70줄/중첩 6단계, `migrate_legacy_data` 호출자 부재(dead code), 매직 문자열 의존 등의 가독성·복잡도 문제가 남아 있습니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **`migrate_legacy_data` 미사용 함수 (Dead Code)**: 프로젝트 전체에서 이 함수를 호출하는 코드가 없습니다. 정의만 존재하며 어디서도 사용되지 않습니다. (`backend/memory/unified.py:413-428`)
  - 영향: `LegacyMemoryMigrator` import도 이 함수를 위해서만 존재하며, 불필요한 의존성과 인지 부하를 유발합니다.
  - 개선안: 함수 삭제 또는 `@deprecated` 마킹. 관련 import도 정리:
    ```python
    # 삭제 대상:
    # from .permanent import LongTermMemory, LegacyMemoryMigrator
    # →
    from .permanent import LongTermMemory

    # 함수 자체도 삭제 가능
    ```

- **`_build_smart_context_sync` 과도한 중첩 (6단계)**: temporal filter 처리 로직이 `if current_query → try → if temporal_filter → if filter_type == "exact"` 순으로 6단계까지 중첩됩니다. (`backend/memory/unified.py:135-203`, 70줄)
  - 영향: 코드 이해에 높은 인지 부하. 새로운 temporal filter 유형 추가 시 중첩이 더 깊어질 위험.
  - 개선안: temporal filter → session context 조회 로직을 별도 메서드로 추출:
    ```python
    def _fetch_session_context(self, temporal_filter: Optional[Dict]) -> Optional[str]:
        """Fetch session context based on temporal filter."""
        if not temporal_filter:
            return self.session_archive.get_recent_summaries(
                10, self.SESSION_ARCHIVE_BUDGET
            )

        filter_type = temporal_filter.get("type")
        if filter_type == "exact":
            return self.session_archive.get_sessions_by_date(
                temporal_filter.get("date"), None, 5,
                self.SESSION_ARCHIVE_BUDGET,
            )
        if filter_type == "range":
            return self.session_archive.get_sessions_by_date(
                temporal_filter.get("from"),
                temporal_filter.get("to"),
                10, self.SESSION_ARCHIVE_BUDGET,
            )
        return self.session_archive.get_recent_summaries(
            10, self.SESSION_ARCHIVE_BUDGET
        )
    ```

### MEDIUM

- **매직 문자열 의존 (`"최근 대화 기록이 없습니다"`)**: session context 유효성 검사가 UI 표시 문자열에 의존합니다. `SessionArchive`의 반환값이 변경되면 이 검사가 무의미해집니다. (`backend/memory/unified.py:187`)
  - 개선안: `SessionArchive`가 빈 결과 시 빈 문자열이나 `None`을 반환하도록 수정하고, 호출자는 단순 falsy 검사로 대체:
    ```python
    # Before:
    if session_context and "최근 대화 기록이 없습니다" not in session_context:

    # After (SessionArchive가 빈 결과 시 None 반환하도록 변경 후):
    if session_context:
    ```

- **`LOG_PATTERNS` 클래스 변수 위치 비표준**: `__init__` 메서드 다음에 클래스 변수가 정의되어 있어 Python 클래스 구조 관례에 맞지 않습니다. 클래스 변수는 `__init__` 앞에 위치하는 것이 표준입니다. (`backend/memory/unified.py:76-82`)
  - 개선안: `LOG_PATTERNS`를 `MAX_CONTEXT_TOKENS` 등 다른 클래스 변수(45-48줄) 바로 뒤로 이동.

- **반환 타입 힌트 누락 (4개 함수)**: `add_message`, `get_working_context`, `_build_smart_context_sync`, `_build_time_context`에 반환 타입이 명시되지 않았습니다. (`backend/memory/unified.py:84,117,135,205`)
  - 개선안:
    ```python
    def add_message(self, role: str, content: str, emotional_context: str = "neutral") -> Optional[TimestampedMessage]:
    def get_working_context(self) -> str:
    def _build_smart_context_sync(self, current_query: str) -> str:
    def _build_time_context(self) -> str:
    ```

- **`migrate_legacy_data` 매개변수 타입 힌트 불완전**: `old_db_path: str = None`은 `Optional[str] = None`이어야 합니다. 반환 타입 `Dict`도 `Dict[str, Any]`로 구체화해야 합니다. (`backend/memory/unified.py:413`)
  - 개선안:
    ```python
    def migrate_legacy_data(
        self, old_db_path: Optional[str] = None, dry_run: bool = True
    ) -> Dict[str, Any]:
    ```

### LOW

- **`context_budget_select`에 불명확한 `None` 인수**: 세 번째 인수로 `None`이 전달되는데, 해당 매개변수의 의미가 호출 코드에서 명확하지 않습니다. 키워드 인수로 전환 권장. (`backend/memory/unified.py:153-158`)
  - 개선안:
    ```python
    selected_memories, tokens_used = self.memgpt.context_budget_select(
        query=current_query,
        budget=self.LONG_TERM_BUDGET,
        exclude_ids=None,
        temporal_filter=temporal_filter,
    )
    ```

- **`save_working_to_disk` bare `except Exception` 반환**: 예외를 무시하고 `False`만 반환하여 어떤 오류인지 추적이 불가합니다. (`backend/memory/unified.py:487-488`)
  - 개선안:
    ```python
    except Exception as e:
        _log.warning("Failed to save working memory", error=str(e))
        return False
    ```

- **관련 memory 모듈 docstring 상태**: `current.py`, `recent/`, `permanent/`, `memgpt.py`, `graph_rag.py`의 docstring은 모두 올바른 위치에 있으며 Google 스타일을 따릅니다. 원래 #23에서 지적된 유형의 문제는 이 파일들에서 발견되지 않았습니다.

## 개선 제안

1. **`_build_smart_context_sync` 분해**: temporal filter 조회(`_fetch_session_context`), long-term memory 조회(`_fetch_long_term_context`), GraphRAG 조회(`_fetch_graph_context`)를 각각 독립 메서드로 추출하면 중첩이 최대 3단계로 줄고, 각 메서드가 20줄 이내의 단순한 함수가 됩니다.

2. **Dead code 정리**: `migrate_legacy_data`와 `LegacyMemoryMigrator` import를 삭제합니다. 마이그레이션이 필요한 시점에 별도 스크립트로 작성하는 것이 클래스의 책임 범위에 적합합니다.

3. **타입 힌트 일괄 보완**: 반환 타입이 누락된 4개 함수에 타입 힌트를 추가하여 코드 네비게이션과 IDE 지원을 개선합니다.

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `migrate_legacy_data` dead code 삭제 | ★☆☆ 쉬움 | 호출자 없으므로 함수와 import만 삭제 |
| `_build_smart_context_sync` 메서드 추출 | ★★☆ 보통 | Extract Method 리팩토링, 테스트 부재 주의 |
| 매직 문자열 제거 | ★★☆ 보통 | `SessionArchive` 반환값 변경 필요, 영향 범위 확인 필요 |
| `LOG_PATTERNS` 위치 이동 | ★☆☆ 쉬움 | 단순 코드 이동 |
| 반환 타입 힌트 추가 | ★☆☆ 쉬움 | 타입 추가만, 동작 변경 없음 |
| bare except 로깅 추가 | ★☆☆ 쉬움 | 한 줄 변경 |
