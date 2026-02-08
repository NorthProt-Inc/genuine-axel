# 09. Opus 코드 중복 (DRY 위반)

> 분석 날짜: 2026-02-05
> 분석 범위: `backend/core/tools/opus_executor.py`, `backend/protocols/mcp/opus_bridge.py`, `backend/core/tools/opus_delegate.py`, `backend/core/filters/xml_filter.py`

## 요약

Opus 위임 로직이 3개 파일(`opus_executor.py`, `opus_bridge.py`, `opus_delegate.py`)에 걸쳐 중복 구현되어 있습니다. `_build_context_block()`, `_safe_decode()`, `_generate_task_summary()`, `_run_claude_cli()` 함수가 거의 동일한 코드로 복제되어 있으며, XML 태그 필터링 로직도 `opus_executor.py`와 `xml_filter.py`에 이중 정의되어 있습니다. 한쪽 수정 시 다른 쪽과 불일치가 발생하는 **샷건 수술(Shotgun Surgery)** 안티패턴의 전형적인 사례입니다.

## 발견사항

### HIGH

- **`_build_context_block()` 완전 중복**: `opus_executor.py:55-88`과 `opus_bridge.py:32-65`가 **34줄 완전 동일**
  - 영향: 파일 검증 로직 변경 시 두 파일 모두 수정 필요. `MAX_FILES`, `MAX_TOTAL_CONTEXT` 상수 변경 시 불일치 위험
  - 개선안: 공통 모듈 `backend/core/utils/opus_context.py`로 추출

  ```python
  # backend/core/utils/opus_context.py
  from typing import List, Tuple
  from backend.core.utils.opus_file_validator import (
      AXEL_ROOT, OPUS_MAX_FILES, OPUS_MAX_TOTAL_CONTEXT,
      validate_opus_file_path, read_opus_file_content,
  )

  def build_context_block(file_paths: List[str]) -> Tuple[str, List[str], List[str]]:
      """Build context string from file paths for Opus delegation."""
      if not file_paths:
          return "", [], []

      context_parts, included, errors = [], [], []
      total_size = 0

      for file_path in file_paths[:OPUS_MAX_FILES]:
          is_valid, resolved, error = validate_opus_file_path(file_path)
          if not is_valid:
              errors.append(error)
              continue

          content = read_opus_file_content(resolved)
          content_size = len(content.encode('utf-8'))

          if total_size + content_size > OPUS_MAX_TOTAL_CONTEXT:
              errors.append(f"Context limit reached, skipping: {file_path}")
              continue

          relative_path = str(resolved.relative_to(AXEL_ROOT))
          context_parts.append(f"### File: {relative_path}\n```\n{content}\n```\n")
          included.append(relative_path)
          total_size += content_size

      if len(file_paths) > OPUS_MAX_FILES:
          errors.append(f"Too many files ({len(file_paths)}), limited to {OPUS_MAX_FILES}")

      return "\n".join(context_parts), included, errors
  ```

- **`_safe_decode()` 완전 중복**: `opus_executor.py:90-97`과 `opus_bridge.py:67-74`가 **8줄 완전 동일**
  - 영향: 인코딩 지원 추가/변경 시 두 파일 모두 수정 필요
  - 개선안: `backend/core/utils/encoding.py`로 추출하거나 기존 유틸리티에 통합

  ```python
  # backend/core/utils/encoding.py
  def safe_decode(data: bytes, encodings: tuple = ("utf-8", "cp949", "latin-1")) -> str:
      """Decode bytes with multiple encoding fallbacks."""
      for encoding in encodings:
          try:
              return data.decode(encoding)
          except UnicodeDecodeError:
              continue
      return data.decode("utf-8", errors="replace")
  ```

- **`_generate_task_summary()` 완전 중복**: `opus_executor.py:99-143`과 `opus_bridge.py:76-122`가 **45줄 거의 동일** (차이점: `opus_bridge.py`는 함수 내부에서 `import re`)
  - 영향: 요약 패턴 추가/변경 시 두 파일 모두 수정 필요. 현재도 `opus_bridge.py:89`에서 함수 내부 `import re`로 미세한 차이 발생
  - 개선안: `backend/core/utils/opus_context.py`에 함께 추출

  ```python
  # backend/core/utils/opus_context.py (계속)
  import re

  ACTION_PATTERNS = [
      (r'\b(refactor|rewrite)\b', 'Refactoring'),
      (r'\b(add|implement|create)\b', 'Implementing'),
      (r'\b(fix|debug|resolve)\b', 'Fixing'),
      (r'\b(update|modify|change)\b', 'Updating'),
      (r'\b(review|analyze)\b', 'Analyzing'),
      (r'\b(test|write test)\b', 'Writing tests for'),
      (r'\b(document|docstring)\b', 'Documenting'),
      (r'\b(optimize|improve)\b', 'Optimizing'),
  ]

  def generate_task_summary(instruction: str, max_length: int = 60) -> str:
      """Generate a short summary for logging from instruction text."""
      instruction_lower = instruction.lower()
      action_prefix = "Processing"

      for pattern, action in ACTION_PATTERNS:
          if re.search(pattern, instruction_lower):
              action_prefix = action
              break

      # ... (나머지 로직 동일)
  ```

- **`_run_claude_cli()` 완전 중복**: `opus_executor.py:145-281`과 `opus_bridge.py:124-261`가 **137줄 거의 동일**
  - 영향: CLI 호출 로직, 타임아웃 처리, 에러 핸들링, 폴백 로직 변경 시 두 파일 모두 수정 필요
  - 주요 차이점:
    - `opus_executor.py:21`: `DEFAULT_MODEL = "opus"` (로컬 상수)
    - `opus_bridge.py:28`: `DEFAULT_MODEL = OPUS_DEFAULT_MODEL` (config에서 import)
    - `opus_executor.py:53`: `COMMAND_TIMEOUT = 600` (로컬 상수)
    - `opus_bridge.py:30`: `COMMAND_TIMEOUT = OPUS_COMMAND_TIMEOUT` (config에서 import)
  - 개선안: `opus_executor.py`도 config에서 상수를 import하고, `_run_claude_cli()`를 공통 모듈로 추출

### MEDIUM

- **`delegate_to_opus()` 3중 정의**: 동일한 이름의 함수가 3곳에 존재
  - `opus_executor.py:283-336`: 완전한 구현
  - `opus_bridge.py`: `run_opus_task` 도구로 내부 구현
  - `opus_delegate.py:64-79`: `opus_bridge`를 호출하는 래퍼

  **호출 관계**:
  ```
  mcp_tools/opus_tools.py:81 → opus_executor.delegate_to_opus()
  opus_delegate.py:64 → opus_bridge._run_claude_cli(), _build_context_block()
  ```
  - 영향: `opus_tools.py`는 `opus_executor`를, `opus_delegate.py`는 `opus_bridge`를 사용 → 로직 분기 발생
  - 개선안: `opus_executor.py`를 단일 진실 소스(Single Source of Truth)로 지정하고, 나머지는 래퍼로 단순화

- **XML 태그 필터링 중복 정의**: `opus_executor.py:24-51`와 `backend/core/filters/xml_filter.py:12-130`
  - `opus_executor.py`: 17개 태그 하드코딩, 패턴 직접 정의
  - `xml_filter.py`: 태그 집합으로 분리, 동적 패턴 빌드, 더 완전한 구현 (52개 태그)
  - 영향: `opus_executor.py`의 `_strip_xml_tags()`가 필터링하는 태그 목록이 `xml_filter.py`보다 적음 → 태그 누락 가능
  - 개선안: `opus_executor.py`에서 `xml_filter.strip_xml_tags()` 직접 import

  ```python
  # opus_executor.py 수정
  from backend.core.filters.xml_filter import strip_xml_tags

  # 기존 _strip_xml_tags() 함수와 _XML_TAG_PATTERN, _TOOL_BLOCK_PATTERN 삭제
  ```

- **`get_mcp_tool_definition()` 2중 정의**: `opus_executor.py:400-456`과 `opus_delegate.py:164-220`
  - 두 함수가 **완전히 동일한 도구 스키마 반환** (56줄)
  - 영향: 도구 설명/스키마 변경 시 두 파일 모두 수정 필요
  - 개선안: `opus_types.py`에 스키마 상수로 추출

- **`list_opus_capabilities()` 2중 정의**: `opus_executor.py:377-398`과 `opus_delegate.py:138-162`
  - 내용은 유사하나 `opus_delegate.py`는 하드코딩된 값 사용
  - 개선안: 공통 상수에서 값을 가져오도록 통일

- **`check_opus_health()` 2중 정의**: `opus_executor.py:338-375`과 `opus_delegate.py:81-136`
  - `opus_executor.py`: CLI 버전 체크만
  - `opus_delegate.py`: SSE 서버 체크 → 실패 시 CLI 체크 (더 완전)
  - 영향: 헬스 체크 로직 불일치
  - 개선안: `opus_delegate.py` 버전을 표준으로 채택

### LOW

- **상수 불일치**: `DEFAULT_MODEL`과 `COMMAND_TIMEOUT`이 `opus_executor.py`에서는 로컬 하드코딩, `opus_bridge.py`에서는 config import
  - `opus_executor.py:21,53`: 로컬 상수
  - `opus_bridge.py:28,30`: `from backend.config import OPUS_DEFAULT_MODEL, OPUS_COMMAND_TIMEOUT`
  - 개선안: 모든 파일에서 `config.py`의 값을 사용

- **`import re` 위치 불일치**: `opus_executor.py:3` (파일 상단) vs `opus_bridge.py:89` (함수 내부)
  - 스타일 일관성 문제
  - 개선안: 파일 상단으로 통일

## 개선 제안

### 아키텍처 재구성

현재 Opus 위임 시스템은 다음과 같은 혼란스러운 구조입니다:

```
현재 구조 (문제):
├── opus_executor.py    # 독립적인 완전 구현 A
├── opus_bridge.py      # 독립적인 완전 구현 B (MCP 서버용)
├── opus_delegate.py    # B를 호출하는 래퍼
├── opus_tools.py       # A를 호출하는 MCP 도구
└── xml_filter.py       # 별도 XML 필터 (opus_executor와 중복)
```

**권장 구조**:

```
제안 구조:
backend/core/utils/
├── opus_context.py         # 공통 유틸리티 (build_context_block, safe_decode, generate_task_summary)
└── opus_cli_runner.py      # _run_claude_cli() - 단일 구현

backend/core/tools/
├── opus_executor.py        # 공개 API (delegate_to_opus, check_opus_health, list_opus_capabilities)
└── opus_types.py           # 데이터 타입 + MCP 스키마 상수

backend/protocols/mcp/
└── opus_bridge.py          # MCP 서버 (opus_executor를 import하여 사용)

backend/core/mcp_tools/
└── opus_tools.py           # MCP 도구 (opus_executor를 import하여 사용)
```

### 구체적 리팩토링 단계

1. **Phase 1: 공통 유틸리티 추출**
   - `opus_context.py` 생성: `build_context_block()`, `safe_decode()`, `generate_task_summary()`
   - 두 파일에서 공통 함수를 import로 대체

2. **Phase 2: CLI 러너 통합**
   - `opus_cli_runner.py` 생성: `run_claude_cli()`
   - `opus_executor.py`와 `opus_bridge.py`에서 import

3. **Phase 3: XML 필터 통합**
   - `opus_executor.py`에서 `_strip_xml_tags()` 삭제
   - `xml_filter.strip_xml_tags()` import

4. **Phase 4: 상수 통합**
   - `opus_executor.py`의 로컬 상수를 `config.py` import로 대체

5. **Phase 5: `opus_delegate.py` 단순화**
   - `opus_executor.py`를 직접 호출하도록 변경
   - 중복 함수 제거

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `_build_context_block()` 추출 | 쉬움 | 순수 함수, 의존성 없음 |
| `_safe_decode()` 추출 | 쉬움 | 8줄, 의존성 없음 |
| `_generate_task_summary()` 추출 | 쉬움 | 순수 함수, `re` 외 의존성 없음 |
| `_run_claude_cli()` 추출 | 중간 | 137줄, 비동기, 로깅 의존성 |
| XML 필터 통합 | 쉬움 | import 변경만 필요 |
| `opus_delegate.py` 단순화 | 중간 | 호출 관계 파악 필요 |
| 상수 통합 | 쉬움 | import 변경만 필요 |
| 전체 아키텍처 재구성 | 어려움 | 호출 관계 복잡, 테스트 필요 |

## 중복 코드 통계

| 함수 | 중복 위치 | 중복 줄 수 |
|------|-----------|-----------|
| `_build_context_block()` | 2곳 | 34줄 × 2 = 68줄 |
| `_safe_decode()` | 2곳 | 8줄 × 2 = 16줄 |
| `_generate_task_summary()` | 2곳 | 45줄 × 2 = 90줄 |
| `_run_claude_cli()` | 2곳 | 137줄 × 2 = 274줄 |
| `get_mcp_tool_definition()` | 2곳 | 56줄 × 2 = 112줄 |
| `list_opus_capabilities()` | 2곳 | 21줄 × 2 = 42줄 |
| `check_opus_health()` | 2곳 | 38줄 × 2 = 76줄 |
| XML 필터 패턴 | 2곳 | ~28줄 × 2 = 56줄 |
| **합계** | | **~734줄** |

**총 ~367줄의 중복 코드**가 단일 구현으로 줄일 수 있습니다.
