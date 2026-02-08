# 06. SessionArchive 단일 책임 위반

> 분석 날짜: 2026-02-04
> 분석 범위: `backend/memory/recent.py` (784줄), `backend/api/memory.py`, `backend/memory/unified.py`

## 요약

`SessionArchive` 클래스(784줄)는 **7가지 이상의 책임**을 한 클래스에 혼재하고 있으며, SQLite 연결 관리가 `__del__`에 의존하여 **리소스 누수 위험**이 있습니다. 외부 모듈(`api/memory.py`)이 내부 메서드 `_get_connection()`을 직접 호출하여 **캡슐화 위반**도 심각합니다.

## 발견사항

### HIGH

- **7가지 책임 혼재 (God Class)**: `SessionArchive`가 다음 책임들을 모두 담당 (`backend/memory/recent.py:18-784`)
  - 1) SQLite 연결 관리 (27-46줄) — `_get_connection()`, `close()`
  - 2) 스키마 정의/마이그레이션 (48-163줄) — `_init_db()` 내 5개 테이블, 7개 인덱스
  - 3) 메시지 CRUD (166-270줄) — `save_message_immediate()`, `save_session()`
  - 4) 라우팅 로그 기록 (272-332줄) — `log_interaction()`, interaction_logs 테이블
  - 5) 스타일 분석 (334-364줄) — `_calculate_style_metrics()`, hedge ratio 계산
  - 6) 세션 검색/조회 (366-586줄) — 5개 조회 메서드
  - 7) LLM 기반 요약 (588-735줄) — `summarize_expired()`, `_generate_session_summary()`
  - 영향: 단일 변경이 모든 기능에 영향, 테스트 작성 불가능, 모듈 교체 어려움
  - 개선안:
    ```python
    # 책임 분리 예시
    class SQLiteConnectionManager:
        """연결 풀 및 트랜잭션 관리"""
        def __init__(self, db_path: Path):
            self._pool: Queue[sqlite3.Connection] = Queue(maxsize=5)

        @contextmanager
        def connection(self) -> Iterator[sqlite3.Connection]:
            conn = self._pool.get()
            try:
                yield conn
            finally:
                self._pool.put(conn)

    class SessionRepository:
        """세션/메시지 CRUD만 담당"""
        def __init__(self, conn_manager: SQLiteConnectionManager):
            self._conn = conn_manager

        def save_message(self, session_id: str, role: str, content: str) -> bool:
            ...

    class InteractionLogger:
        """라우팅 로그 전용"""
        def __init__(self, conn_manager: SQLiteConnectionManager):
            self._conn = conn_manager

        def log(self, routing_decision: dict, metrics: dict) -> bool:
            ...

    class SessionSummarizer:
        """LLM 기반 요약 전용"""
        def __init__(self, llm_client, repository: SessionRepository):
            ...
    ```

- **`__del__` 의존 연결 종료**: GC 타이밍에 의존한 리소스 해제 (`backend/memory/recent.py:781-783`)
  ```python
  def __del__(self):
      self.close(silent=True)  # GC 타이밍에 따라 호출 안 될 수 있음
  ```
  - 영향: 멀티스레드/멀티프로세스 환경에서 연결 누수, SQLite 파일 잠금 문제 발생 가능
  - 개선안:
    ```python
    # Context Manager 프로토콜 구현
    class SessionArchive:
        def __enter__(self) -> 'SessionArchive':
            return self

        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            self.close()

        # 또는 atexit 등록
        def __init__(self, ...):
            import atexit
            atexit.register(self.close)

    # 사용
    with SessionArchive() as archive:
        archive.save_message(...)
    # 자동 close 보장
    ```

- **캡슐화 위반 - 내부 메서드 외부 노출**: `api/memory.py`에서 `_get_connection()` 직접 호출 (`backend/api/memory.py:204,226,277`)
  ```python
  # api/memory.py:204
  with state.memory_manager.session_archive._get_connection() as conn:
      conn.row_factory = sqlite3.Row
      cursor = conn.cursor()
      cursor.execute("""SELECT ...""")
  ```
  - 영향: `_get_connection()` 구현 변경 시 외부 코드 깨짐, 트랜잭션 일관성 보장 불가
  - 개선안:
    ```python
    # SessionArchive에 필요한 메서드 추가
    def get_session_messages(self, session_id: str) -> List[Dict]:
        """세션의 모든 메시지 조회"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT role, content, timestamp FROM messages
                WHERE session_id = ? ORDER BY turn_id ASC
            """, (session_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_interaction_stats_by_model(self) -> List[Dict]:
        """모델별 상호작용 통계"""
        with self._get_connection() as conn:
            ...
    ```

- **수동 트랜잭션 관리 불일치**: 일부 메서드만 `BEGIN IMMEDIATE` 사용 (`backend/memory/recent.py:218,641`)
  ```python
  # save_session()에서는 명시적 트랜잭션
  conn.execute("BEGIN IMMEDIATE")  # 218줄

  # 하지만 save_message_immediate()에서는 autocommit
  conn.execute("INSERT ...")  # 188줄
  conn.commit()  # 194줄
  ```
  - 영향: 동시 쓰기 시 race condition 가능, 일관성 없는 트랜잭션 격리
  - 개선안:
    ```python
    @contextmanager
    def _transaction(self):
        """일관된 트랜잭션 관리"""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except:
                conn.rollback()
                raise

    # 모든 쓰기 작업에서 사용
    def save_message_immediate(self, ...):
        with self._transaction() as conn:
            conn.execute("INSERT ...")
    ```

### MEDIUM

- **함수 내부 import**: `_calculate_style_metrics()`와 `get_recent_summaries()`에서 함수 내부 import (`backend/memory/recent.py:345,403,442`)
  ```python
  def _calculate_style_metrics(self, response: str) -> dict:
      import re  # 345줄 - 함수 호출마다 import 체크
      sentences = re.split(r'[.!?。]', response)

  def get_recent_summaries(self, ...):
      from collections import Counter  # 403줄
      import random  # 442줄
  ```
  - 영향: 미미한 성능 저하, 의존성 불명확
  - 개선안: 파일 상단에서 한 번만 import

- **스키마 마이그레이션 하드코딩**: `_init_db()`에서 ALTER TABLE을 try/except로 처리 (`backend/memory/recent.py:67-71`)
  ```python
  try:
      conn.execute("ALTER TABLE sessions ADD COLUMN messages_json TEXT")
      _log.info("Added messages_json column")
  except sqlite3.OperationalError:
      pass  # 이미 존재하면 무시
  ```
  - 영향: 마이그레이션 이력 추적 불가, 복잡한 스키마 변경 시 대응 어려움
  - 개선안:
    ```python
    SCHEMA_VERSION = 2
    MIGRATIONS = {
        1: "ALTER TABLE sessions ADD COLUMN messages_json TEXT",
        2: "CREATE INDEX IF NOT EXISTS idx_new ON ...",
    }

    def _migrate(self, conn):
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current + 1, SCHEMA_VERSION + 1):
            conn.execute(MIGRATIONS[version])
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    ```

- **`row_factory` 반복 설정**: 거의 모든 조회 메서드에서 `conn.row_factory = sqlite3.Row` 반복 (`backend/memory/recent.py:370,385,463,495,522,621`)
  - 영향: 코드 중복, 누락 시 불일치
  - 개선안: `_get_connection()`에서 한 번만 설정하거나 조회 전용 context manager 분리

- **`_generate_session_summary()` 내 LLM import**: 함수 내부에서 LLM 클라이언트 동적 import (`backend/memory/recent.py:725-727`)
  ```python
  from backend.llm import get_llm_client
  llm = get_llm_client("gemini", MESSAGE_SUMMARY_MODEL)
  response = await llm.generate(prompt, max_tokens=300)
  ```
  - 영향: 순환 import 위험, 의존성 불명확
  - 개선안: `SessionSummarizer` 클래스 분리 후 생성자에서 LLM 클라이언트 주입

- **hedge_phrases 하드코딩**: `_calculate_style_metrics()`에 한국어/영어 hedge 구문 하드코딩 (`backend/memory/recent.py:339-343`)
  ```python
  hedge_phrases = [
      "아마도", "것 같아", "것 같습니다", "인 것 같아",
      "I think", "I'm not sure", "maybe", "perhaps",
      ...
  ]
  ```
  - 영향: 언어 추가/수정 시 코드 변경 필요
  - 개선안: config 또는 별도 상수 파일로 분리

### LOW

- **매직 넘버**: 여러 위치에 하드코딩된 숫자들
  - `timeout=10.0` (`backend/memory/recent.py:35`)
  - `PRAGMA busy_timeout=5000` (`backend/memory/recent.py:39`)
  - `limit * 20` (`backend/memory/recent.py:393`)
  - `[:50]` 메시지 제한 (`backend/memory/recent.py:700`)
  - `[:5000]` 프롬프트 길이 제한 (`backend/memory/recent.py:710`)
  - `max_tokens=300` (`backend/memory/recent.py:722,727`)
  - 개선안: 클래스 상수 또는 config로 추출

- **`cleanup_expired()` dead code**: 기능이 비활성화된 채로 존재 (`backend/memory/recent.py:737-740`)
  ```python
  def cleanup_expired(self) -> int:
      _log.debug("cleanup_expired called but message deletion is disabled")
      return 0
  ```
  - 영향: 사용되지 않는 코드로 혼란 유발
  - 개선안: 삭제하거나 `@deprecated` 데코레이터 추가

- **`check_same_thread=False` 사용**: SQLite 멀티스레드 모드 활성화 (`backend/memory/recent.py:34`)
  ```python
  self._connection = sqlite3.connect(
      self.db_path,
      check_same_thread=False,  # 위험할 수 있음
      timeout=10.0
  )
  ```
  - 영향: threading.Lock과 함께 사용 중이라 현재는 안전하나, 락 누락 시 corruption 위험
  - 개선안: 연결 풀링 또는 thread-local 연결 사용

## 개선 제안

### 1. 책임 분리 (Repository 패턴)

```
backend/memory/
├── recent/
│   ├── __init__.py           # SessionArchive (facade)
│   ├── connection.py         # SQLiteConnectionManager
│   ├── repository.py         # SessionRepository, MessageRepository
│   ├── interaction_logger.py # InteractionLogger
│   ├── summarizer.py         # SessionSummarizer
│   └── schema.py             # SchemaManager (마이그레이션)
```

### 2. Context Manager 필수화

```python
# 앱 시작 시
@asynccontextmanager
async def lifespan(app: FastAPI):
    archive = SessionArchive()
    app.state.session_archive = archive
    try:
        yield
    finally:
        archive.close()  # 명시적 종료 보장
```

### 3. API 캡슐화

`api/memory.py`의 직접 SQL 호출을 `SessionArchive` 메서드로 이동:
- `get_session_messages(session_id)` 추가
- `get_interaction_stats()` 추가
- `_get_connection()` → private으로 유지하고 외부 호출 제거

### 4. 우선순위 높은 리팩토링 순서

1. **`__del__` 제거** → Context Manager / atexit 전환 (리소스 누수 방지)
2. **API 캡슐화** → `_get_connection()` 외부 호출 제거
3. **트랜잭션 일관화** → `_transaction()` context manager 도입
4. **책임 분리** → 점진적으로 클래스 추출

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `__del__` → Context Manager | 쉬움 | 인터페이스 변경 없이 내부 구현만 수정 |
| API 캡슐화 (`_get_connection` 외부 호출 제거) | 쉬움 | 3개 호출점만 수정 |
| 트랜잭션 일관화 | 중간 | 모든 쓰기 메서드 수정 필요 |
| 함수 내부 import 제거 | 쉬움 | 단순 코드 이동 |
| 스키마 마이그레이션 시스템 | 중간 | 기존 DB와 호환성 유지 필요 |
| 전체 책임 분리 (Repository 패턴) | 어려움 | 대규모 리팩토링, 테스트 필요 |
