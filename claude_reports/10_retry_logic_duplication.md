# 10. Retry 로직 중복

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/core/utils/gemini_wrapper.py`, `backend/llm/clients.py`, `backend/core/mcp_client.py`, `backend/core/utils/retry.py`

## 요약
지수 백오프 재시도 로직이 최소 3개 파일에서 거의 동일한 패턴으로 반복 구현되어 있습니다. 특히 `backend/core/utils/retry.py`에 잘 설계된 공통 유틸리티가 이미 존재함에도 불구하고 전혀 활용되지 않고 있어, 재시도 정책 변경 시 여러 파일을 동시에 수정해야 하는 "샷건 수술(Shotgun Surgery)" 문제가 발생합니다.

## 발견사항

### CRITICAL
(없음)

### HIGH

- **완전히 미활용된 retry.py 유틸리티**: (`backend/core/utils/retry.py:1-156`)
  - 영향: 156줄의 잘 설계된 retry 유틸리티(`RetryConfig`, `is_retryable_error()`, `classify_error()`, `calculate_backoff()`, `retry_async()`, `retry_sync()`)가 존재하지만, 프로젝트 어디에서도 사용되지 않음. `__init__.py`에 export까지 되어 있으나 실제 import하는 파일 없음
  - 개선안: gemini_wrapper.py, clients.py, mcp_client.py에서 이 유틸리티를 활용하도록 리팩토링
  ```python
  # 현재 (gemini_wrapper.py:137-194)
  for attempt in range(1, MAX_RETRIES + 1):
      try:
          # ... API 호출 ...
      except Exception as e:
          error_str = str(e).lower()
          retryable = any(x in error_str for x in ['429', 'timeout', '500', ...])
          if not retryable or attempt == MAX_RETRIES:
              raise
          delay = RETRY_DELAY_BASE * (2 ** (attempt - 1)) * (1 + random.uniform(0.1, 0.3))
          time.sleep(delay)

  # 개선안: retry.py 활용
  from backend.core.utils.retry import retry_sync, RetryConfig

  gemini_retry_config = RetryConfig(
      max_retries=5,
      base_delay=2.0,
      jitter=0.3
  )

  def generate_content_sync(...):
      def _call_sdk():
          return self.client.models.generate_content(...)
      return retry_sync(_call_sdk, config=gemini_retry_config)
  ```

- **gemini_wrapper.py 내 6개 메서드에 동일 retry 패턴 중복**: (`backend/core/utils/gemini_wrapper.py`)
  - 영향: 동일한 retry 패턴이 `generate_content_sync()` (137-195), `embed_content()` (212-236), `embed_content_sync()` (252-274), `generate_images()` (287-310), `generate_images_sync()` (322-344) 5개 메서드에 복사-붙여넣기 되어 있음. 약 **150줄의 중복 코드**
  - 개선안: retry 로직을 데코레이터나 헬퍼 함수로 추출
  ```python
  # 데코레이터 패턴 제안
  from functools import wraps
  from backend.core.utils.retry import retry_sync, retry_async, RetryConfig

  GEMINI_RETRY_CONFIG = RetryConfig(max_retries=5, base_delay=2.0, jitter=0.3)

  def with_retry_sync(func):
      @wraps(func)
      def wrapper(*args, **kwargs):
          return retry_sync(lambda: func(*args, **kwargs), config=GEMINI_RETRY_CONFIG)
      return wrapper

  def with_retry_async(func):
      @wraps(func)
      async def wrapper(*args, **kwargs):
          return await retry_async(lambda: func(*args, **kwargs), config=GEMINI_RETRY_CONFIG)
      return wrapper
  ```

### MEDIUM

- **retryable 에러 패턴 목록 불일치**: (여러 파일)
  - 영향: 각 파일마다 retryable로 간주하는 에러 패턴이 미묘하게 다름
    - `gemini_wrapper.py:187`: `['429', 'timeout', '500', '502', '503', 'overloaded', 'resource_exhausted']`
    - `gemini_wrapper.py:298` (generate_images): `['429', 'timeout', '500', '502', '503', 'overloaded']` — `resource_exhausted` 누락
    - `mcp_client.py:83-86`: `['connection', 'timeout', 'busy', 'port', 'address already in use', 'temporarily unavailable', 'resource exhausted']`
    - `clients.py:390-393`: 문자열 검사 방식 자체가 다름 (`is_429 = '429' in error_str or 'resource_exhausted' in error_str`)
    - `retry.py:21-29`: 가장 포괄적 (`ssl`, `certificate`, `handshake` 등 포함)
  - 개선안: `retry.py`의 `RetryConfig.retryable_patterns`을 표준으로 사용하거나, 도메인별 설정을 명시적으로 분리

  ```python
  # config.py에 중앙화
  RETRYABLE_GEMINI_PATTERNS = {'429', '500', '502', '503', 'timeout', 'overloaded', 'resource_exhausted'}
  RETRYABLE_MCP_PATTERNS = {'connection', 'timeout', 'busy', 'port', 'address already in use'}
  ```

- **backoff 배수 불일치**: (여러 파일)
  - 영향: 에러 유형별 backoff 배수가 파일마다 다름
    - `retry.py:67-72`: server_error → 1.5배, rate_limit → 1.0배, timeout → 1.2배
    - `clients.py:427-432`: 503 → 3배(`delay * 3`), timeout → 2배(`delay * 2`), 429 → 1배
    - `gemini_wrapper.py`: 에러 유형 구분 없이 동일 배수
  - 개선안: `retry.py`의 `calculate_backoff()`에 모든 배수 로직 통합

- **import random 중복**: (`backend/core/utils/gemini_wrapper.py:73, 170, 205, 246, 283, 319`)
  - 영향: 함수 내부에서 `import random`을 6번 반복. 파일 상단에서 한 번만 import하면 됨
  - 개선안: 파일 상단으로 이동
  ```python
  # gemini_wrapper.py 상단
  import random  # 추가

  # 각 함수 내부의 import random 제거
  ```

- **clients.py와 gemini_wrapper.py 간 retry 상수 불일치**:
  - 영향:
    - `gemini_wrapper.py:13-14`: `MAX_RETRIES = 5`, `RETRY_DELAY_BASE = 2.0`
    - `clients.py:292`: `MAX_STREAM_RETRIES = 5` (동일하지만 별도 상수)
    - 두 파일이 서로 다른 상수를 사용하며 동기화 보장 없음
  - 개선안: `config.py`에 중앙화하거나 `retry.py`의 `DEFAULT_RETRY_CONFIG` 사용
  ```python
  # config.py 추가
  GEMINI_MAX_RETRIES = _get_int_env("GEMINI_MAX_RETRIES", 5)
  GEMINI_RETRY_DELAY_BASE = _get_float_env("GEMINI_RETRY_DELAY_BASE", 2.0)
  ```

- **mcp_client.py의 이중 fallback 구조**: (`backend/core/mcp_client.py:54-116`)
  - 영향: retry 루프 내에서 실패 시 HTTP fallback을 시도하고, retry 루프 전체 실패 후에도 다시 HTTP fallback 시도. 복잡도 증가 및 중복 fallback
  - 개선안: fallback 로직을 retry 루프 외부로 분리하거나, strategy 패턴 적용

### LOW

- **GeminiRetryExhaustedError 미활용**: (`backend/core/utils/gemini_wrapper.py:30-34`)
  - 영향: 커스텀 예외가 정의되어 있으나, 실제로 발생하는 경우가 드물고(대부분 마지막 예외를 그대로 raise), 호출측에서 이 예외를 catch하는 코드 없음
  - 개선안: 일관되게 사용하거나 제거

- **retry 로깅 형식 불일치**:
  - 영향:
    - `gemini_wrapper.py:182`: `_logger.info("Timeout retry", attempt=attempt, delay=round(delay, 1))`
    - `clients.py:434`: `_log.warning("retry backoff", ...)`
    - `retry.py:102`: `_logger.warning("Retry scheduled", attempt=attempt, ...)`
  - 개선안: 공통 retry 유틸리티 사용 시 자연스럽게 해결됨

## 개선 제안

### 1. retry.py 활용 리팩토링 (권장)

기존 `backend/core/utils/retry.py`가 이미 잘 설계되어 있으므로, 이를 활용하는 것이 가장 효율적입니다:

```python
# backend/core/utils/gemini_wrapper.py 리팩토링 예시

from backend.core.utils.retry import retry_sync, retry_async, RetryConfig, GeminiRetryExhaustedError

# 파일 상단에 Gemini 전용 설정 정의
GEMINI_RETRY_CONFIG = RetryConfig(
    max_retries=5,
    base_delay=2.0,
    max_delay=60.0,
    jitter=0.3,
    retryable_patterns={'429', '500', '502', '503', 'timeout', 'overloaded', 'resource_exhausted'}
)

class GenerativeModelWrapper:
    def embed_content_sync(self, model: str, contents: Any, config: Any = None, task_type: str = None) -> Any:
        if config is None and task_type:
            config = {'task_type': task_type}

        def _call():
            return self.client.models.embed_content(model=model, contents=contents, config=config)

        return retry_sync(_call, config=GEMINI_RETRY_CONFIG)

    async def embed_content(self, model: str, contents: Any, config: Any = None, task_type: str = None) -> Any:
        if config is None and task_type:
            config = {'task_type': task_type}

        async def _call():
            return self.client.models.embed_content(model=model, contents=contents, config=config)

        return await retry_async(_call, config=GEMINI_RETRY_CONFIG)
```

### 2. 도메인별 RetryConfig 분리

```python
# backend/config.py에 추가
from backend.core.utils.retry import RetryConfig

GEMINI_RETRY_CONFIG = RetryConfig(
    max_retries=5,
    base_delay=2.0,
    retryable_patterns={'429', '500', '502', '503', 'timeout', 'overloaded', 'resource_exhausted'}
)

MCP_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=0.5,
    retryable_patterns={'connection', 'timeout', 'busy', 'port', 'address already in use'}
)
```

### 3. 점진적 마이그레이션 전략

1. **1단계**: `mcp_client.py`부터 시작 (가장 간단, ~50줄 절감)
2. **2단계**: `gemini_wrapper.py`의 embed/image 함수들 (~100줄 절감)
3. **3단계**: `clients.py`의 generate_stream (복잡도 높음, Circuit Breaker와 연동 필요)
4. **4단계**: `generate_content_sync`의 timeout 처리 (ThreadPoolExecutor 조합 필요)

## 중복 코드 통계

| 파일 | 중복 retry 블록 | 예상 줄 수 |
|------|----------------|-----------|
| `gemini_wrapper.py` | 6개 메서드 | ~150줄 |
| `clients.py` | 1개 메서드 (generate_stream) | ~70줄 |
| `mcp_client.py` | 1개 메서드 (call_tool) | ~40줄 |
| **총 중복** | **8개 위치** | **~260줄** |

`retry.py` 활용 시 각 위치에서 3-5줄로 축소 가능 → **~200줄 이상 절감** 예상

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| mcp_client.py 리팩토링 | 낮음 | 단순한 retry 패턴, 외부 의존성 적음 |
| gemini_wrapper.py embed/image 메서드 | 낮음 | 동일한 패턴 반복, 단순 대체 가능 |
| gemini_wrapper.py generate_content_sync | 중간 | ThreadPoolExecutor, timeout 처리 복잡 |
| clients.py generate_stream | 높음 | Circuit Breaker, 동적 timeout, wrapper 재생성 로직과 통합 필요 |
| retryable 패턴 통합 | 낮음 | 설정값 통합만 필요 |
