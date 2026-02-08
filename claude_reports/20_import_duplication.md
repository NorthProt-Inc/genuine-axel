# 20. import 중복 및 미사용

> 분석 날짜: 2026-02-06
> 분석 범위: backend/ 전체 (~90 Python 파일), scripts/ 디렉토리

## 요약

AST 기반 정적 분석으로 프로젝트 전반의 import 위생 상태를 점검했습니다. 모듈-레벨 미사용 import 1건, 함수-내부 중복 lazy import ~25건이 발견되었습니다. 대부분은 기능적 영향이 없는 코드 정리 수준이나, **`memory_server.py`의 `from datetime import datetime, timezone`가 4개 함수에서 반복**되는 패턴과 **`unified.py`의 `import asyncio` 3중 중복**이 가독성을 저해합니다.

## 발견사항

### CRITICAL

없음

### HIGH

없음

### MEDIUM

- **`app.py` 미사용 import `get_model`**: `from backend.llm.router import get_model`을 import하지만 파일 내 어디에서도 사용하지 않습니다 (`backend/app.py:23`)
  - 개선안: 해당 import 라인 제거
  ```python
  # 제거:
  # from backend.llm.router import get_model
  ```

- **`memory_server.py` `datetime`/`timezone` 4중 lazy import**: 동일한 `from datetime import datetime, timezone`이 4개 함수(`_parse_timestamp`, `_format_temporal_label`, `_format_relative_time`, `get_sort_timestamp`)에서 반복됩니다 (`backend/protocols/mcp/memory_server.py:115,186,217,252`)
  - 개선안: 모듈 상단에 한 번만 import
  ```python
  # memory_server.py 상단에 추가:
  from datetime import datetime, timezone

  # 각 함수 내부의 'from datetime import datetime, timezone' 제거
  ```

- **`unified.py` `import asyncio` 3중 lazy import**: 이미 모듈 상단(1줄)에서 `import asyncio`를 하고 있으면서, 함수 내부에서 3회 더 반복합니다 (`backend/memory/unified.py:1,214,464,622`)
  - 개선안: 함수 내부의 `import asyncio` 3건 제거 (모듈-레벨 import로 충분)
  ```python
  # unified.py:214, 464, 622에서 각각 제거:
  # import asyncio
  ```

- **`graph_rag.py` `import os` 2중 lazy import**: `pathlib`을 사용하지 않고 `os` 모듈을 `save()`와 `_load()` 두 메서드에서 각각 lazy import합니다 (`backend/memory/graph_rag.py:272,308`)
  - 개선안: 모듈 상단에 `import os`를 한 번 추가하고 함수 내부 import 제거. 또는 이미 import된 `pathlib.Path` 사용
  ```python
  # graph_rag.py 상단에 추가:
  import os

  # 또는 pathlib으로 전환:
  # save() 내:
  Path(self.persist_path).parent.mkdir(parents=True, exist_ok=True)
  # _load() 내:
  if not Path(self.persist_path).exists():
  ```

- **`llm/clients.py` `GenerativeModelWrapper` 2중 lazy import**: `__init__`과 retry 로직에서 각각 lazy import합니다 (`backend/llm/clients.py:237,358`)
  - 영향: 순환 import 회피 목적의 의도적 패턴이나, 같은 클래스 내 2곳에서 동일 import 반복
  - 개선안: `__init__` 시점에 `self._wrapper_cls = GenerativeModelWrapper`로 캐싱하여 retry에서 재사용
  ```python
  def __init__(self, model: str = None):
      from backend.core.utils.gemini_wrapper import GenerativeModelWrapper
      self._wrapper_cls = GenerativeModelWrapper
      self.wrapper = self._wrapper_cls(model_name=model)
      ...

  # retry 시:
  self.wrapper = self._wrapper_cls(model_name=self.model_name)
  ```

### LOW

- **`research_server.py` `import sys` 함수 내 중복**: 모듈 상단(12줄)과 `main()` 함수(346줄)에서 중복 import (`backend/protocols/mcp/research_server.py:12,346`)
  - 개선안: `main()` 내 `import sys` 제거

- **`file_utils.py` `bounded_to_thread` 3중 lazy import**: 같은 파일 내 3개 위치에서 동일한 `from backend.core.utils.async_utils import bounded_to_thread`를 반복합니다 (`backend/core/utils/file_utils.py:59,149,167`)
  - 개선안: 순환 import 회피 목적이라면 파일 상단에서 조건부 import 사용
  ```python
  # file_utils.py 상단:
  from typing import TYPE_CHECKING
  if not TYPE_CHECKING:
      # 런타임에만 import (순환 import 방지)
      pass
  # 또는 함수 첫 호출 시 모듈-레벨 변수에 캐싱
  ```

- **`file_utils.py` `fcntl` 2중 lazy import**: `_acquire_os_lock`과 `_release_os_lock`에서 각각 import (`backend/core/utils/file_utils.py:99,122`)
  - 영향: Windows 호환성을 위한 의도적 lazy import 패턴이므로 합당함
  - 개선안: 모듈 상단에서 `try: import fcntl; except ImportError: fcntl = None`으로 통합
  ```python
  try:
      import fcntl
  except ImportError:
      fcntl = None  # Windows
  ```

- **`llm/clients.py` `base64` 2중 lazy import**: `generate_stream`과 `generate` 메서드에서 각각 import (`backend/llm/clients.py:258,503`)
  - 개선안: 모듈 상단에 `import base64` 추가 (경량 표준 라이브러리)

- **`memory/memgpt.py` `get_memory_age_hours` 2중 lazy import**: 두 메서드에서 동일 함수를 반복 import (`backend/memory/memgpt.py:150,260`)
  - 개선안: 모듈 상단에서 import

- **`protocols/mcp/async_research.py` `time` 2중 lazy import**: 두 함수에서 `import time` 반복 (`backend/protocols/mcp/async_research.py:224,356`)
  - 개선안: 모듈 상단에 `import time` 추가

- **`memory/permanent/importance.py` `get_gemini_wrapper` 2중 lazy import**: 두 메서드에서 동일 함수 반복 import (`backend/memory/permanent/importance.py:27,89`)
  - 개선안: 순환 import 회피 목적이라면 `__init__` 시 캐싱

- **`scripts/memory_gc.py` `datetime`·`chromadb` 2중 lazy import**: 스크립트 내 다른 함수에서 각각 반복 (`scripts/memory_gc.py:365,412` — datetime / `scripts/memory_gc.py:724,816` — chromadb)
  - 개선안: 스크립트 상단에 import 통합

- **`research_server.py` backward-compatible aliases**: `_google_search`, `_tavily_search`, `_visit_page`, `_deep_dive` 4개 alias가 정의됨 (`backend/protocols/mcp/research_server.py:36-40`)
  - 영향: `__init__.py`와 테스트에서 사용 중이므로 즉시 제거 불가
  - 개선안: 테스트와 `__init__.py`를 원본 이름으로 업데이트 후 aliases 제거

## 개선 제안

### 1. 모듈-레벨 미사용 import 정리
`app.py:23`의 `get_model` import를 제거합니다. 자동 린터(ruff, flake8)를 CI에 추가하면 이런 문제를 지속적으로 방지할 수 있습니다.

### 2. Lazy import 통합 패턴 도입
현재 lazy import가 2~4중으로 반복되는 파일들이 있습니다. 두 가지 접근을 권장합니다:

**표준 라이브러리는 모듈 상단으로 이동:**
- `datetime`, `asyncio`, `os`, `time`, `base64` 등 — lazy import의 이점이 거의 없음

**순환 import 회피가 필요한 경우 캐싱 패턴 사용:**
```python
_bounded_to_thread = None

def _get_bounded_to_thread():
    global _bounded_to_thread
    if _bounded_to_thread is None:
        from backend.core.utils.async_utils import bounded_to_thread
        _bounded_to_thread = bounded_to_thread
    return _bounded_to_thread
```

### 3. 린터 도입
`ruff`를 프로젝트에 도입하여 `F401`(unused import), `F811`(redefined unused variable from import) 규칙을 자동 검사합니다:

```toml
# pyproject.toml
[tool.ruff.lint]
select = ["F401", "F811", "I"]  # unused imports, redefined, isort
```

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `app.py` 미사용 `get_model` 제거 | 쉬움 | 1줄 삭제 |
| `memory_server.py` datetime 통합 | 쉬움 | 상단 1줄 추가, 4줄 삭제 |
| `unified.py` asyncio 중복 제거 | 쉬움 | 3줄 삭제 (이미 상단에 import 있음) |
| `graph_rag.py` os import 통합 | 쉬움 | 상단 1줄 추가, 2줄 삭제 |
| `llm/clients.py` lazy import 정리 | 보통 | 순환 import 확인 후 캐싱 패턴 적용 필요 |
| `file_utils.py` bounded_to_thread 통합 | 보통 | 순환 import 구조 확인 필요 |
| backward-compatible aliases 제거 | 보통 | 테스트 및 `__init__.py` 동시 수정 필요 |
| ruff 린터 도입 | 쉬움 | pyproject.toml 설정 + pre-commit hook |
