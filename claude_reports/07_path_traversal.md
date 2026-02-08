# 07 경로 탐색 취약점 (Path Traversal)

> 분석 날짜: 2026-02-05
> 분석 범위:
> - `backend/core/tools/system_observer.py`
> - `backend/core/utils/path_validator.py`
> - `backend/core/mcp_tools/file_tools.py`
> - `backend/core/utils/opus_file_validator.py`

## 요약

프로젝트 전반에 걸쳐 경로 검증 로직이 불일치하며, `system_observer.py`의 `".." in str(path)` 방식은 URL 인코딩, 심볼릭 링크, 유니코드 정규화 공격에 취약합니다. 반면 `path_validator.py`는 더 견고한 패턴을 제공하나 일부 모듈에서 활용되지 않습니다.

## 발견사항

### HIGH

- **취약한 경로 탐색 검사 (검사 순서 오류)**: `_validate_log_path()`에서 `.resolve()` 호출 **후에** `".." in str(log_path)` 검사를 수행합니다. (`backend/core/tools/system_observer.py:144-147`)
  - 영향: `resolve()` 후에는 이미 `..`가 정규화되어 사라지므로, 이 검사는 원본 입력 `log_path`에 대해서만 의미가 있음. 그러나 현재 코드는 원본 문자열을 검사하므로 URL 인코딩(`%2e%2e` 또는 `%2f`)이나 유니코드 정규화 공격에는 우회 가능
  - 개선안:
    ```python
    # 변경 전 (system_observer.py:143-147)
    try:
        resolved = Path(log_path).resolve()
        if ".." in str(log_path):
            return False, None, "Path traversal not allowed"

    # 변경 후 - 정규화된 경로가 허용 디렉토리 내인지만 확인
    try:
        resolved = Path(log_path).resolve()
        # ".." 문자열 검사 제거, relative_to() 검사로 충분함
        for allowed_dir in ALLOWED_LOG_DIRS:
            try:
                resolved.relative_to(allowed_dir.resolve())
                if resolved.exists() and resolved.is_file():
                    return True, resolved, None
            except ValueError:
                continue
    ```

- **심볼릭 링크 미검증**: `resolve()`는 심볼릭 링크를 따라가므로, 허용 디렉토리 내에 악의적인 심볼릭 링크가 있으면 외부 파일 접근 가능 (`backend/core/tools/system_observer.py:144`, `backend/core/utils/path_validator.py:54`, `backend/core/utils/opus_file_validator.py:25-27`)
  - 영향: 공격자가 `logs/` 디렉토리 내에 심볼릭 링크를 생성할 수 있다면 `/etc/shadow` 등 민감 파일 접근 가능
  - 개선안:
    ```python
    # 심볼릭 링크 검사 추가
    def _validate_log_path(log_path: str) -> tuple[bool, Optional[Path], Optional[str]]:
        # ... 기존 코드 ...
        resolved = Path(log_path).resolve()

        # 심볼릭 링크 검사 추가
        if Path(log_path).is_symlink():
            return False, None, "Symbolic links not allowed"

        # 또는 resolve(strict=True) 사용 (Python 3.6+)
        # 단, 파일이 반드시 존재해야 함
    ```

- **경로 검증 로직 불일치 (일관성 부재)**: `path_validator.py`에 견고한 검증 함수가 있으나, `system_observer.py`는 자체 검증 로직 사용 (`backend/core/tools/system_observer.py:131-160` vs `backend/core/utils/path_validator.py:32-79`)
  - 영향: 보안 정책이 파편화되어 있어 일부 모듈만 수정해도 전체 보안에 구멍이 생김
  - 개선안:
    ```python
    # system_observer.py에서 path_validator 사용
    from backend.core.utils.path_validator import validate_path, sanitize_path

    def _validate_log_path(log_path: str) -> tuple[bool, Optional[Path], Optional[str]]:
        # 별칭 처리
        if log_path.lower() in LOG_FILE_ALIASES:
            log_path = LOG_FILE_ALIASES[log_path.lower()]

        # 파일명만 있는 경우
        if "/" not in log_path and "\\" not in log_path:
            for log_dir in ALLOWED_LOG_DIRS:
                candidate = log_dir / log_path
                if candidate.exists():
                    return True, candidate, None
            return False, None, f"Log file '{log_path}' not found"

        # 전체 경로 - path_validator 사용
        log_path = sanitize_path(log_path)
        is_valid, error = validate_path(
            log_path,
            allow_outside_project=False,
            operation="read"
        )
        if not is_valid:
            return False, None, error

        resolved = Path(log_path).resolve()

        # 로그 디렉토리 내인지 추가 검증
        for allowed_dir in ALLOWED_LOG_DIRS:
            try:
                resolved.relative_to(allowed_dir.resolve())
                if resolved.exists() and resolved.is_file():
                    return True, resolved, None
            except ValueError:
                continue

        return False, None, "Path outside allowed log directories"
    ```

### MEDIUM

- **null 바이트 인젝션 미검증**: `system_observer.py`에서 null 바이트 검사 누락. `path_validator.py:44-46`에는 검사가 있으나 `system_observer.py`에는 없음 (`backend/core/tools/system_observer.py:131-160`)
  - 개선안:
    ```python
    def _validate_log_path(log_path: str) -> tuple[bool, Optional[Path], Optional[str]]:
        # null 바이트 검사 추가
        if "\x00" in log_path:
            return False, None, "Invalid characters in path (null byte)"
        # ... 기존 코드 ...
    ```

- **`get_source_code()` 경로 검증 부재**: `system_observer.py:517-537`의 `get_source_code()`는 `ALLOWED_CODE_DIRS` 검사만 하고, `path_validator`나 `..` 검사 없음
  - 영향: `core/../../../etc/passwd` 같은 입력으로 우회 가능할 수 있음 (단, `_is_code_file_allowed()`에서 확장자 검사가 어느 정도 방어)
  - 개선안:
    ```python
    def get_source_code(relative_path: str) -> Optional[str]:
        # 경로 정규화 및 검증 추가
        if ".." in relative_path or "\x00" in relative_path:
            return None

        full_path = (AXEL_ROOT / relative_path).resolve()

        # resolve 후에도 AXEL_ROOT 내에 있는지 확인
        try:
            full_path.relative_to(AXEL_ROOT)
        except ValueError:
            return None

        # ... 기존 검사 ...
    ```

- **ALLOWED_DIRECTORIES에 `/tmp` 포함**: `path_validator.py:12`에서 `/tmp`를 허용 디렉토리로 포함. 다른 프로세스가 `/tmp`에 악의적 심볼릭 링크를 생성할 수 있음
  - 개선안:
    ```python
    # /tmp 대신 전용 임시 디렉토리 사용
    ALLOWED_DIRECTORIES: List[Path] = [
        Path("/home/northprot/projects/axnmihn"),
        Path("/home/northprot/.axel"),
        Path("/home/northprot/.axel/tmp"),  # 전용 tmp
    ]
    ```

- **예외 삼킴으로 우회 가능성 은폐**: `_search_file()`에서 예외 발생 시 `pass`로 삼킴 (`backend/core/tools/system_observer.py:339-341`)
  - 개선안:
    ```python
    except Exception as e:
        logger.warning(f"Failed to search file {file_path}: {e}")
        return []
    ```

### LOW

- **Windows 경로 구분자 처리 불일치**: `system_observer.py:136`에서 `"\\" not in log_path` 검사는 있으나, 일반적인 경로 정규화에서는 이미 처리됨. 불필요한 중복 검사
  - 개선안: `pathlib.Path`가 OS별 경로 구분자를 자동 처리하므로 별도 검사 불필요

- **`FORBIDDEN_PATTERNS` 우회 가능**: `path_validator.py:14-26`의 금지 패턴은 대소문자 무시하지만, `.ENV.BACKUP` 같은 변형에 취약할 수 있음
  - 개선안: 정규표현식 기반 패턴 매칭 또는 더 포괄적인 패턴 목록

## 개선 제안

### 1. 중앙 집중식 경로 검증 레이어 구축

모든 파일 시스템 접근이 단일 검증 레이어를 통과하도록 구조화:

```python
# backend/core/security/path_security.py (신규)
from pathlib import Path
from typing import Optional, Tuple, List
from enum import Enum

class PathAccessType(Enum):
    READ_LOG = "read_log"
    READ_CODE = "read_code"
    READ_ANY = "read_any"
    WRITE = "write"

class PathSecurityManager:
    """중앙 집중식 경로 보안 관리자"""

    ALLOWED_PATHS = {
        PathAccessType.READ_LOG: [
            Path("/home/northprot/projects/axnmihn/logs"),
            Path("/home/northprot/projects/axnmihn/data/logs"),
        ],
        PathAccessType.READ_CODE: [
            Path("/home/northprot/projects/axnmihn"),
        ],
        # ... 다른 접근 타입 ...
    }

    @classmethod
    def validate(
        cls,
        path_str: str,
        access_type: PathAccessType
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """경로 검증의 단일 진입점"""

        # 1. 기본 검증
        if not path_str or not isinstance(path_str, str):
            return False, None, "Invalid path"

        # 2. 위험 문자 검사
        if "\x00" in path_str:
            return False, None, "Null byte in path"

        # 3. 정규화
        try:
            path = Path(path_str)
            if path.is_symlink():
                return False, None, "Symbolic links not allowed"
            resolved = path.resolve()
        except Exception as e:
            return False, None, f"Path error: {e}"

        # 4. 허용 디렉토리 검사
        allowed_dirs = cls.ALLOWED_PATHS.get(access_type, [])
        for allowed_dir in allowed_dirs:
            try:
                resolved.relative_to(allowed_dir)
                return True, resolved, None
            except ValueError:
                continue

        return False, None, "Path outside allowed directories"
```

### 2. 기존 모듈 마이그레이션

`system_observer.py`, `file_tools.py`, `opus_file_validator.py`가 모두 `PathSecurityManager`를 사용하도록 변경

### 3. 심볼릭 링크 정책 명시

심볼릭 링크를 허용할지, 거부할지 프로젝트 전체에 일관된 정책 수립

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| `.resolve()` 후 `..` 검사 제거 | 쉬움 | 단순 코드 제거 |
| null 바이트 검사 추가 | 쉬움 | 한 줄 추가 |
| 심볼릭 링크 검사 추가 | 쉬움 | 조건문 하나 추가 |
| `path_validator.py` 통합 사용 | 중간 | 여러 모듈 수정 필요 |
| 중앙 집중식 보안 레이어 | 어려움 | 새 아키텍처, 전체 리팩토링 |
| `/tmp` 제거 및 전용 디렉토리 | 중간 | 기존 사용처 파악 필요 |

## 위험도 평가

- **현재 위험도**: MEDIUM
  - MCP 도구를 통해서만 접근 가능 (직접 외부 노출 없음)
  - LLM이 악의적 경로를 생성해야 하므로 프롬프트 인젝션이 선행되어야 함
- **잠재적 위험도**: HIGH
  - 프롬프트 인젝션 성공 시 민감 파일 접근 가능
  - 심볼릭 링크 공격 시 `/etc/shadow` 등 시스템 파일 노출 가능

## 참고: 양호한 구현 사례

`file_tools.py`는 `path_validator.py`를 적절히 활용하고 있어 비교적 안전합니다:

```python
# file_tools.py:33-38 - 좋은 패턴
path_str = sanitize_path(path_str)
is_valid, error = validate_path(path_str, operation="read")
if not is_valid:
    return [TextContent(type="text", text=f"Error: {error}")]
```

이 패턴을 `system_observer.py`에도 적용하는 것이 권장됩니다.
