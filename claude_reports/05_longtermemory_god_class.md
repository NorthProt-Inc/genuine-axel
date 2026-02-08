# 05. LongTermMemory God Class

> 분석 날짜: 2026-02-04
> 분석 범위: `backend/memory/permanent.py`, `backend/memory/unified.py`, `backend/memory/memgpt.py`, `backend/memory/graph_rag.py`, `backend/memory/temporal.py`, `backend/core/mcp_tools/memory_tools.py`, `scripts/memory_gc.py`

## 요약

`LongTermMemory` 클래스(270~761줄, 약 490줄)가 **7가지 이상의 책임**을 단일 클래스에 집중하고 있습니다. 임베딩 생성, ChromaDB CRUD, 유사도 기반 중복 검사, adaptive decay 계산, consolidation, 접근 패턴 추적(flush), 통계/컨텍스트 포매팅이 모두 한 클래스에 혼재되어, 임베딩 모델 변경이나 저장소 교체 시 전체 클래스 수정이 필요합니다.

## 발견사항

### CRITICAL

*해당 없음*

### HIGH

- **다중 책임 혼재 (God Class)**: `LongTermMemory` 클래스가 단일 책임 원칙(SRP)을 심각하게 위반 (`permanent.py:270-761`)
  - 영향: 임베딩 모델 교체(Gemini → OpenAI), 벡터DB 교체(ChromaDB → Pinecone), decay 로직 수정 시 모두 이 클래스를 건드려야 함
  - 현재 책임:
    1. **임베딩 생성** (`_get_embedding`, 329-378줄) - rate limiter 포함
    2. **ChromaDB CRUD** (`add`, `query`, `_find_similar`, `_update_repetitions`)
    3. **중복 검사** (`_find_similar`, 481-508줄)
    4. **Repetition 캐싱** (`_repetition_cache`, `_load_repetition_cache`, 296-297줄)
    5. **접근 패턴 추적** (`_pending_access_updates`, `flush_access_updates`, 299-650줄)
    6. **Consolidation/Decay** (`consolidate_memories`, 698-760줄)
    7. **컨텍스트 포매팅** (`get_formatted_context`, 652-674줄)
    8. **통계** (`get_stats`, 676-696줄)
  - 개선안: 아래 클래스로 분리
    ```python
    # backend/memory/embedding_service.py
    class EmbeddingService:
        """임베딩 생성 전담 - 캐시, rate limit 포함"""
        def __init__(self, model: str = "gemini-embedding-001"):
            self._cache: Dict[str, List[float]] = {}
            self._rate_limiter = get_embedding_limiter()

        def get_embedding(self, text: str, task_type: str = "retrieval_document") -> Optional[List[float]]:
            cache_key = f"{hash(text[:500])}:{task_type}"
            if cache_key in self._cache:
                return self._cache[cache_key]
            # ... embedding logic

    # backend/memory/memory_repository.py
    class MemoryRepository:
        """ChromaDB CRUD 전담"""
        def __init__(self, embedding_service: EmbeddingService):
            self.embedding_service = embedding_service
            self.collection = ...

        def add(self, content: str, metadata: dict) -> Optional[str]: ...
        def query(self, query_text: str, n_results: int) -> List[Dict]: ...
        def delete(self, ids: List[str]) -> None: ...

    # backend/memory/decay_calculator.py
    class DecayCalculator:
        """Decay 계산 전담"""
        @staticmethod
        def apply_adaptive_decay(importance: float, created_at: str, ...) -> float: ...

    # backend/memory/consolidator.py
    class MemoryConsolidator:
        """Memory consolidation/eviction 전담"""
        def __init__(self, repository: MemoryRepository, decay_calc: DecayCalculator):
            ...
        def consolidate(self) -> Dict[str, int]: ...
    ```

- **모듈 레벨 함수와 클래스 메서드 혼재**: decay 관련 로직이 모듈 레벨 함수(`apply_adaptive_decay`, 71-135줄)와 클래스 메서드(`consolidate_memories`, 698-760줄)에 흩어져 있음 (`permanent.py:71-135, 698-760`)
  - 영향: decay 로직 변경 시 어디를 수정해야 하는지 불명확
  - 개선안: `DecayCalculator` 클래스로 통합

- **중복된 importance 계산 함수**: `calculate_importance_async`와 `calculate_importance_sync`가 거의 동일한 로직을 async/sync 두 버전으로 유지 (`permanent.py:150-246`)
  - 영향: 중요도 평가 로직 변경 시 두 함수를 모두 수정해야 함
  - 개선안: sync 버전만 유지하고 async에서 `asyncio.to_thread` 호출
    ```python
    async def calculate_importance_async(user_msg: str, ai_msg: str, persona_context: str = "") -> float:
        return await asyncio.to_thread(calculate_importance_sync, user_msg, ai_msg, persona_context)
    ```

- **순환 의존성 위험**: `get_connection_count()` 함수가 `GraphRAG`를 lazy import (`permanent.py:137-146`)
  - 영향: 테스트 격리 어려움, 모듈 로드 순서에 민감
  - 개선안: 의존성 주입(DI) 패턴 적용
    ```python
    class LongTermMemory:
        def __init__(self, graph_rag: Optional[GraphRAG] = None):
            self._graph_rag = graph_rag

        def _get_connection_count(self, memory_id: str) -> int:
            if self._graph_rag:
                return self._graph_rag.get_connection_count(memory_id)
            return 0
    ```

### MEDIUM

- **클래스 레벨 가변 상태 공유**: `_embedding_cache`가 클래스 변수로 선언되어 모든 인스턴스가 공유 (`permanent.py:326-327`)
  - 영향: 멀티 인스턴스 환경에서 예기치 않은 캐시 공유
  - 개선안: `__init__`에서 인스턴스 변수로 초기화
    ```python
    def __init__(self, ...):
        self._embedding_cache: Dict[str, List[float]] = {}  # 인스턴스 변수로
    ```

- **매직 넘버 산재**: 캐시 크기, 타임아웃, threshold 등이 여러 곳에 하드코딩 (`permanent.py:148, 327, 345, 440, 555`)
  - `IMPORTANCE_TIMEOUT_SECONDS = 120` (148줄)
  - `_EMBEDDING_CACHE_SIZE = 256` (327줄)
  - `max_retries = 3` (345줄)
  - `threshold=MemoryConfig.DUPLICATE_THRESHOLD` (440줄) - 이건 config 사용 중
  - `fetch_count = max(n_results + 5, int(n_results * 1.5))` (555줄)
  - 개선안: `MemoryConfig`에 통합
    ```python
    class MemoryConfig:
        EMBEDDING_CACHE_SIZE = 256
        IMPORTANCE_TIMEOUT_SECONDS = 120
        EMBEDDING_MAX_RETRIES = 3
        QUERY_FETCH_BUFFER = 5
    ```

- **`_find_similar` 임베딩 중복 호출**: `add()` 메서드에서 `_find_similar()`와 `_get_embedding()`을 별도로 호출하여 동일 텍스트에 대해 임베딩이 2회 생성될 수 있음 (`permanent.py:440-451`)
  - 개선안: `add()`에서 먼저 임베딩을 생성하고 `_find_similar`에 전달
    ```python
    def add(self, content: str, ...):
        embedding = self._get_embedding(content)
        if not embedding:
            return None

        existing = self._find_similar_with_embedding(content, embedding, threshold=...)
        if existing:
            return existing['id']

        # 이미 생성된 embedding 사용
        self.collection.add(embeddings=[embedding], ...)
    ```

- **Repetition 캐시 무한 증가**: `_repetition_cache`가 메모리에 무한히 쌓일 수 있음 (`permanent.py:296, 380-410`)
  - 영향: 장기 운영 시 메모리 누수
  - 개선안: LRU 캐시 적용 또는 정기적 정리
    ```python
    from functools import lru_cache
    # 또는
    if len(self._repetition_cache) > 10000:
        # 오래된 항목 정리
    ```

- **flush_access_updates 예외 무시**: 개별 업데이트 실패 시 `except Exception: pass`로 완전히 삼킴 (`permanent.py:639-640`)
  - 영향: 접근 통계 손실, 디버깅 불가
  - 개선안: 최소한 warning 로깅
    ```python
    except Exception as e:
        _log.debug("Access update failed", doc_id=doc_id, error=str(e)[:50])
    ```

- **LegacyMemoryMigrator 불완전한 에러 처리**: migrate() 메서드에서 개별 문서 마이그레이션 실패 시 계속 진행하지만 실패 기록이 없음 (`permanent.py:825-877`)
  - 개선안: 실패한 문서 ID 기록
    ```python
    report["failed_ids"] = []
    # ...
    if not doc_id:
        report["failed_ids"].append(results['ids'][i])
    ```

### LOW

- **PromotionCriteria 클래스의 static 남용**: 상태 없는 클래스에 `@classmethod`만 존재 (`permanent.py:248-268`)
  - 개선안: 모듈 레벨 함수로 변환하거나 dataclass로 변환
    ```python
    def should_promote(content: str, repetitions: int, importance: float, force: bool) -> Tuple[bool, str]:
        ...
    ```

- **get_formatted_context 하드코딩된 포맷**: 출력 형식이 메서드 내부에 하드코딩 (`permanent.py:652-674`)
  - 개선안: 별도 Formatter 클래스 또는 템플릿 사용

- **docstring 누락**: 대부분의 메서드에 docstring이 없음
  - 영향: 코드 이해도 저하

## 개선 제안

### 1. 책임 분리를 위한 단계적 리팩토링 전략

**Phase 1: EmbeddingService 추출** (영향 범위: 작음)
```python
# backend/memory/embedding_service.py
class EmbeddingService:
    def __init__(self, model: str = "gemini-embedding-001"):
        self.model = model
        self._cache: Dict[str, List[float]] = {}
        self._cache_max_size = 256
        self._rate_limiter = None

    def get_embedding(self, text: str, task_type: str = "retrieval_document") -> Optional[List[float]]:
        # permanent.py의 _get_embedding 로직 이동
        pass
```

**Phase 2: MemoryRepository 추출** (영향 범위: 중간)
- ChromaDB 연산만 담당
- LongTermMemory가 MemoryRepository를 의존성 주입받음

**Phase 3: DecayCalculator 및 Consolidator 추출** (영향 범위: 중간)
- 모듈 레벨 함수들을 클래스로 그룹화
- `consolidate_memories`를 Consolidator로 이동

### 2. 의존성 주입 패턴 적용

```python
# backend/memory/permanent.py
class LongTermMemory:
    def __init__(
        self,
        embedding_service: EmbeddingService = None,
        graph_rag: GraphRAG = None,
        db_path: str = None,
    ):
        self.embedding_service = embedding_service or EmbeddingService()
        self._graph_rag = graph_rag
        self.db_path = db_path or str(CHROMADB_PATH)
        # ...
```

### 3. async/sync 중복 제거

모든 sync 버전을 기본으로 하고, async 버전은 `asyncio.to_thread` 래퍼로 통일:

```python
# permanent.py
def calculate_importance_sync(...) -> float:
    # 핵심 로직

async def calculate_importance_async(...) -> float:
    return await asyncio.to_thread(calculate_importance_sync, ...)
```

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| EmbeddingService 추출 | 중 | 캐시, rate limiter 포함 로직 분리 필요 |
| MemoryRepository 추출 | 중상 | CRUD 메서드 다수, 테스트 필요 |
| DecayCalculator 추출 | 하 | 이미 모듈 레벨 함수로 존재 |
| Consolidator 추출 | 중 | graph_rag 의존성 처리 필요 |
| async/sync 중복 제거 | 하 | 단순 래퍼 변환 |
| 클래스 변수 → 인스턴스 변수 | 하 | 단순 이동 |
| flush 예외 로깅 | 하 | 한 줄 수정 |

## 관련 파일 영향 분석

| 파일 | 영향도 | 설명 |
|------|--------|------|
| `unified.py` | 높음 | `LongTermMemory` 직접 사용 (23, 61줄) |
| `memgpt.py` | 중간 | `long_term.collection.get()` 직접 접근 (141줄) |
| `memory_gc.py` | 중간 | `LongTermMemory` 인스턴스 생성 (403줄) |
| `memory_tools.py` | 낮음 | `LongTermMemory()` 새 인스턴스 생성 (361줄) |
| `graph_rag.py` | 없음 | 직접 의존 없음 |

## 테스트 전략 권장

리팩토링 전 다음 테스트 케이스 작성 권장:
1. `test_embedding_cache_hit_rate` - 캐시 정상 동작 검증
2. `test_duplicate_detection_threshold` - 중복 검사 threshold 검증
3. `test_adaptive_decay_formula` - decay 계산 정확성
4. `test_consolidation_deletes_low_score` - consolidation 삭제 조건
5. `test_flush_updates_access_time` - flush 동작 검증
