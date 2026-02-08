# 17. 글로벌 예외 핸들러의 내부 정보 노출

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/app.py:195-222`, `backend/api/audio.py`, `backend/api/memory.py`, `backend/api/openai.py`, `backend/api/mcp.py`, `backend/config.py`

## 요약

글로벌 예외 핸들러(`app.py:195-222`)가 `str(exc)`, `type(exc).__name__`, `request.url.path`를 JSON 응답에 그대로 포함하여 내부 구현 세부사항을 클라이언트에 노출합니다. 이 패턴은 글로벌 핸들러에만 국한되지 않고, `backend/api/` 전반의 8개 이상 엔드포인트에서 `str(e)`를 응답 본문에 직접 포함하는 동일한 안티패턴이 반복됩니다. 환경별(dev/prod) 에러 응답 분기가 없어, 프로덕션 환경에서도 동일한 수준의 내부 정보가 노출됩니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **글로벌 예외 핸들러의 예외 메시지·타입 직접 노출**: 500 응답에 `str(exc)`, `type(exc).__name__`을 포함합니다. DB 연결 오류 시 호스트·포트·DB 경로, API 클라이언트 오류 시 API 키 일부, 파일 시스템 오류 시 내부 경로 등이 노출될 수 있습니다. (`backend/app.py:215-221`)
  - 영향: 공격자가 내부 기술 스택, 파일 구조, DB 위치, 사용 중인 라이브러리 버전을 추론할 수 있음. CWE-209 (Generation of Error Message Containing Sensitive Information)
  - 개선안:
    ```python
    import os

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import traceback
        req_id = getattr(request.state, "request_id", None) or get_request_id()

        _log.error(
            "APP unhandled exception",
            path=str(request.url.path),
            error_type=type(exc).__name__,
            error=str(exc),
            traceback=traceback.format_exc(),
            request_id=req_id,
        )

        headers = {"X-Request-ID": req_id} if req_id else None

        # 프로덕션에서는 내부 정보 숨김
        is_dev = os.getenv("ENV", "dev") == "dev"
        content = {
            "error": "Internal Server Error",
            "request_id": req_id,
        }
        if is_dev:
            content["message"] = str(exc) if str(exc) else "Unknown error"
            content["type"] = type(exc).__name__
            content["path"] = str(request.url.path)

        return JSONResponse(
            status_code=500,
            headers=headers,
            content=content,
        )
    ```

- **API 라우터 전반의 `str(e)` 응답 노출 패턴 (8개소 이상)**: `backend/api/` 디렉토리 전반에서 예외 메시지를 클라이언트 응답에 직접 포함하는 패턴이 반복됩니다. 글로벌 핸들러와 별개로, 개별 라우터 수준에서도 동일한 문제가 존재합니다:
  - `backend/api/audio.py:117` — `detail=f"TTS error: {str(e)}"`
  - `backend/api/audio.py:161` — `detail=f"STT error: {str(e)}"`
  - `backend/api/memory.py:126` — `{"message": str(e)}`
  - `backend/api/memory.py:142` — `{"error": str(e)}`
  - `backend/api/memory.py:220` — `{"error": str(e)}`
  - `backend/api/memory.py:236` — `{"error": str(e)}`
  - `backend/api/memory.py:251` — `{"error": str(e)}`
  - `backend/api/openai.py:324` — `f"Stream error: {str(e)[:100]}"`
  - 영향: 공격자가 특정 엔드포인트에 조작된 입력을 보내 내부 에러 메시지를 유도하여 정보를 수집할 수 있음 (error-based information disclosure). 특히 `memory.py`에서 5개소가 `str(e)`를 직접 반환하여 SQLite 에러 메시지(파일 경로, 스키마 구조 포함 가능)가 노출될 수 있음
  - 개선안: 공통 에러 응답 유틸리티를 만들어 환경별 분기:
    ```python
    # backend/api/utils.py에 추가
    import os

    def safe_error_response(
        error: Exception,
        default_msg: str = "An error occurred",
        status_code: int = 500,
    ) -> dict:
        """Return error response with appropriate detail level."""
        is_dev = os.getenv("ENV", "dev") == "dev"
        if is_dev:
            return {"status": "error", "message": str(error)}
        return {"status": "error", "message": default_msg}

    def safe_http_exception(
        error: Exception,
        default_msg: str = "Internal server error",
        status_code: int = 500,
    ) -> HTTPException:
        """Create HTTPException with environment-appropriate detail."""
        is_dev = os.getenv("ENV", "dev") == "dev"
        detail = f"{default_msg}: {str(error)}" if is_dev else default_msg
        return HTTPException(status_code=status_code, detail=detail)
    ```

### MEDIUM

- **환경별 에러 응답 분기 메커니즘 부재**: `config.py`에 `ENV` 환경변수를 읽는 코드가 없으며, `app.py:85`에서 `os.getenv("ENV", "dev")`로 로깅 목적으로만 참조합니다. 프로덕션/개발 환경을 구분하는 중앙화된 설정이 없어, 에러 노출 수준을 환경에 따라 조절할 수 없습니다. (`backend/config.py` 전체, `backend/app.py:85`)
  - 개선안: `config.py`에 환경 모드 추가:
    ```python
    # backend/config.py
    ENV = os.getenv("ENV", "dev")
    IS_PRODUCTION = ENV in ("prod", "production")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    ```

- **`request.url.path` 노출**: 에러 응답에 요청 경로를 포함합니다. 이 자체는 치명적이지 않으나, 숨겨진 내부 엔드포인트나 경로 패턴이 확인 응답을 통해 노출될 수 있습니다. (`backend/app.py:219`)
  - 개선안: 프로덕션에서는 `path` 필드를 응답에서 제거하고, 로그에만 기록

- **`traceback.format_exc()`의 함수 내부 import**: `traceback` 모듈을 예외 핸들러 내부에서 매번 import합니다. 기능적 문제는 없으나, 모듈 상단에서 import하는 것이 관례적이며 약간의 런타임 오버헤드가 있습니다. (`backend/app.py:198`)
  - 개선안: 파일 상단으로 `import traceback` 이동

- **에러 응답 스키마 불일치**: 글로벌 핸들러는 `{"error", "message", "type", "path", "request_id"}` 필드를 사용하고, `memory.py`는 `{"status", "message"}` 또는 `{"error"}`, `audio.py`는 HTTPException의 `{"detail"}`, `mcp.py`는 `{"detail": "MCP execution failed"}` (제네릭 메시지)를 사용합니다. 클라이언트 측에서 일관된 에러 처리가 어렵습니다.
  - 영향: 클라이언트 코드가 에러 형식을 예측할 수 없어 에러 처리 로직이 복잡해짐
  - 개선안: 프로젝트 전체에 걸쳐 통일된 에러 응답 스키마를 정의:
    ```python
    # backend/api/utils.py에 추가
    from pydantic import BaseModel

    class ErrorResponse(BaseModel):
        error: str
        message: str
        request_id: str | None = None
    ```

### LOW

- **`mcp.py`의 대조적으로 안전한 에러 처리**: `mcp.py:78`에서는 `detail="MCP execution failed"`로 제네릭 메시지를 사용하여 내부 정보를 노출하지 않습니다. 이것이 올바른 패턴이지만, 프로젝트 내에서 일관되게 적용되지 않고 있습니다. (`backend/api/mcp.py:78`)

- **로그의 과도한 에러 정보**: `_log.error()` 호출에서 `traceback=tb`로 전체 트레이스백을 구조화 로그에 포함합니다. 로그 집계 시스템(예: CloudWatch, ELK)에서 이 정보가 적절히 접근 제어되는지 확인이 필요합니다. (`backend/app.py:202-208`)

## 개선 제안

### 1. 환경 모드 중앙화 (가장 먼저)
`config.py`에 `ENV`/`IS_PRODUCTION` 설정을 추가하여, 에러 응답의 상세도를 환경에 따라 조절하는 기반을 마련합니다.

### 2. 글로벌 예외 핸들러 개선
프로덕션에서는 `request_id`만 포함한 제네릭 에러 응답을 반환하고, 개발 환경에서만 상세 정보를 포함합니다. `request_id`를 통해 서버 로그에서 상세 에러를 추적할 수 있으므로 디버깅 능력은 유지됩니다.

### 3. 공통 에러 응답 유틸리티 도입
`safe_error_response()`와 `safe_http_exception()` 같은 유틸리티를 만들어, API 라우터 전체에서 일관되게 사용합니다. 이를 통해:
- 환경별 분기를 한 곳에서 관리
- 에러 응답 스키마 통일
- 개별 라우터의 `str(e)` 직접 노출 제거

### 4. 점진적 적용 경로
1. `config.py`에 `ENV`/`IS_PRODUCTION` 추가 (1줄)
2. 글로벌 핸들러 수정 (가장 높은 영향)
3. `audio.py`의 HTTPException 2개소 수정
4. `memory.py`의 5개소 수정
5. `openai.py`의 스트림 에러 1개소 수정

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| 글로벌 예외 핸들러 환경별 분기 | 쉬움 | `os.getenv("ENV")` 체크 추가만으로 해결. 기존 로직 유지 |
| config.py에 ENV 설정 추가 | 쉬움 | 1-2줄 추가 |
| API 라우터 str(e) 제거 (8개소) | 쉬움 | 각각 1줄 수정. 제네릭 메시지로 교체 |
| 공통 에러 응답 유틸리티 도입 | 보통 | 유틸리티 작성 후 8개소+ 일괄 교체 필요 |
| 에러 응답 스키마 통일 | 보통 | 클라이언트 측 에러 처리 코드도 함께 확인/수정 필요 |
