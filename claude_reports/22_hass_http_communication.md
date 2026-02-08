# 22. Home Assistant HTTP 통신

> 분석 날짜: 2026-02-06
> 분석 범위: `backend/core/tools/hass_ops.py`, `backend/core/mcp_tools/hass_tools.py`, `backend/core/utils/http_pool.py`, `backend/core/utils/circuit_breaker.py`, `backend/core/utils/timeouts.py`, `backend/config.py`, `.env.example`

## 요약

Home Assistant와의 HTTP 통신이 평문(HTTP)으로 이루어져 Bearer 토큰이 네트워크에 노출되며, HTTP 클라이언트 풀의 구조적 결함으로 인해 자격 증명 변경 시 stale 클라이언트가 재사용됩니다. 또한 `_get_hass_config()`의 lazy import 패턴이 로컬 상수에 의해 가려지는(shadowing) 구조적 혼란이 존재합니다.

## 발견사항

### CRITICAL

(해당 없음)

### HIGH

- **HTTP 평문 통신으로 Bearer 토큰 노출**: `HASS_URL` 기본값이 `http://192.168.1.131:8123`이며, `.env.example`에서도 `http://homeassistant.local:8123`으로 안내합니다. 모든 HASS API 호출에서 `Authorization: Bearer {hass_token}` 헤더가 암호화 없이 전송됩니다. (`backend/core/tools/hass_ops.py:144`, `backend/core/tools/hass_ops.py:184`)
  - 영향: 로컬 네트워크 내 ARP 스푸핑이나 패킷 스니핑으로 HASS 장기 토큰(long-lived access token) 탈취 가능. 탈취된 토큰으로 Home Assistant 전체 제어 가능 (도어락, 보안 시스템 포함)
  - 개선안:
    ```python
    # config.py에 HASS URL 설정 추가
    HASS_URL = os.getenv("HASS_URL", "http://192.168.1.131:8123")
    HASS_REQUIRE_HTTPS = os.getenv("HASS_REQUIRE_HTTPS", "false").lower() == "true"

    # hass_ops.py에서 HTTPS 검증 추가
    def _get_hass_credentials() -> tuple[str, Optional[str]]:
        hass_url = os.getenv("HASS_URL", "http://192.168.1.131:8123")
        hass_token = os.getenv("HASS_TOKEN")

        if not hass_url.startswith("https://"):
            _log.warning("HASS insecure", msg="Using HTTP for HASS communication. "
                        "Set HASS_URL to https:// for secure token transmission")

        return hass_url, hass_token
    ```

- **http_pool 클라이언트 stale 자격 증명 문제**: `get_client()`는 서비스 이름 기준으로 클라이언트를 캐싱하는데, 첫 호출 시의 `base_url`과 `headers`로 고정됩니다. 이후 `HASS_URL`이나 `HASS_TOKEN` 환경 변수가 변경되어도 기존 클라이언트가 이전 자격 증명으로 계속 사용됩니다. (`backend/core/utils/http_pool.py:24-37`)
  - 영향: 토큰 교체(rotation) 시 서비스 재시작 필수. 런타임 중 토큰 교체 불가
  - 개선안:
    ```python
    async def get_client(
        service: str = "default",
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.AsyncClient:
        async with _lock:
            existing = _clients.get(service)
            # base_url 변경 시 기존 클라이언트 폐기
            if existing and base_url and str(existing.base_url) != base_url:
                await existing.aclose()
                del _clients[service]
                existing = None

            if service not in _clients:
                service_timeout = timeout or SERVICE_TIMEOUTS.get(service, SERVICE_TIMEOUTS["default"])
                _clients[service] = httpx.AsyncClient(
                    base_url=base_url,
                    headers=headers,
                    limits=POOL_LIMITS,
                    timeout=httpx.Timeout(service_timeout, connect=5.0),
                    follow_redirects=True,
                )
            return _clients[service]
    ```

### MEDIUM

- **`_get_hass_config()` lazy import가 로컬 상수에 의해 가려짐(shadowing)**: `hass_ops.py:86-93`에서 `_get_hass_config()`이 `config.py`의 `HASS_TIMEOUT`과 `HASS_MAX_RETRIES`를 lazy import하지만, 바로 아래(92-93줄)에 동일 이름의 모듈-레벨 상수 `HASS_TIMEOUT = 10.0`과 `MAX_RETRIES = 2`가 정의되어 있습니다. `_get_hass_config()`를 호출하지 않는 코드는 로컬 상수를 참조하게 되어 혼란을 줍니다. 실제로 `_hass_api_call()`은 `_get_hass_config()`를 호출하므로 런타임 값은 정상이나, 코드 가독성이 심각하게 저하됩니다. (`backend/core/tools/hass_ops.py:86-93`)
  - 개선안: 로컬 상수를 제거하고, `_get_hass_config()`만 사용하거나, `config.py`에서 직접 import:
    ```python
    # 로컬 상수 제거 후 직접 import (순환 의존이 없다면)
    from backend.config import HASS_TIMEOUT, HASS_MAX_RETRIES
    # 또는 _get_hass_config()만 유지하고 로컬 상수 제거
    ```

- **`_get_hass_credentials()` 매 호출마다 환경 변수 조회**: `_hass_api_call()`이 매 요청마다 `os.getenv("HASS_URL")`과 `os.getenv("HASS_TOKEN")`을 호출합니다. 환경 변수 조회 자체는 저렴하나, `http_pool`이 첫 호출의 URL/헤더를 캐싱하므로 두 번째 이후 호출에서 `base_url`이 달라져도 무시됩니다. 즉, 환경 변수를 매번 조회하지만 실제로는 반영되지 않는 "거짓 동적성(false dynamism)"입니다. (`backend/core/tools/hass_ops.py:142-147`, `backend/core/utils/http_pool.py:25-26`)
  - 개선안: 자격 증명을 앱 시작 시 1회 로드하거나, http_pool에서 URL 변경 감지를 구현

- **`hass_execute_scene`에서 `"warmwhite"` 색상이 `COLOR_MAP`에 없음**: `hass_tools.py:361`에서 "relax" 씬이 `color: "warmwhite"`를 사용하지만, `COLOR_MAP`(`hass_ops.py:29-51`)에는 `"warm"`(255,200,150)만 존재하고 `"warmwhite"`는 없습니다. `parse_color("warmwhite")`는 `None`을 반환하므로 relax 씬에서 색상이 적용되지 않습니다. (`backend/core/mcp_tools/hass_tools.py:361`, `backend/core/tools/hass_ops.py:29-51`)
  - 개선안:
    ```python
    # COLOR_MAP에 warmwhite 추가
    COLOR_MAP = {
        ...
        "warm": [255, 200, 150],
        "warmwhite": [255, 200, 150],  # relax 씬에서 사용
        ...
    }
    ```

- **HASS API 응답 본문 누출**: `_process_response_httpx()`에서 실패 시 `resp.text[:200]`을 에러 메시지에 포함합니다. HASS API가 에러 응답에 내부 정보를 포함할 경우 이것이 MCP 도구 결과를 통해 LLM에 노출되고, 최종적으로 사용자 응답에 포함될 수 있습니다. (`backend/core/tools/hass_ops.py:276`)
  - 개선안: `resp.text` 대신 상태 코드와 사전 정의된 메시지만 반환

### LOW

- **`hass_control_all_lights()`가 순차 호출로 지연 발생**: 6개 조명을 `for` 루프와 `asyncio.sleep(0.05)` 딜레이로 순차 제어합니다. `asyncio.gather()`로 병렬 호출하면 응답 시간을 ~80% 단축할 수 있습니다. (`backend/core/tools/hass_ops.py:368-378`)

- **`hass_control_device`에 `toggle` 액션이 정의되어 있으나 MCP 스키마에서 미노출**: `DeviceAction` enum에 `TOGGLE`이 있고 `hass_control_device()`에서 처리 가능하나, `hass_control_device` MCP 도구 스키마의 action enum은 `["turn_on", "turn_off"]`만 허용합니다. `hass_control_light`도 동일합니다. (`backend/core/tools/hass_ops.py:105-107`, `backend/core/mcp_tools/hass_tools.py:77,38`)

- **`.env.example`의 `HASS_URL` 기본값이 코드 기본값과 불일치**: `.env.example`는 `http://homeassistant.local:8123`, 코드 기본값은 `http://192.168.1.131:8123`. 사용자가 `.env`를 설정하지 않으면 코드 기본값이 적용되어 혼란 가능. (`.env.example:7`, `backend/core/tools/hass_ops.py:144`)

- **`config.py`의 `HASS_TIMEOUT`/`HASS_MAX_RETRIES`와 `timeouts.py`의 `HTTP_HASS` 이중 정의**: `config.py:250`에 `HASS_TIMEOUT = 10.0`, `timeouts.py:16`에 `HTTP_HASS = 10.0`으로 동일 값이 두 곳에 정의되어 있습니다. 현재 `http_pool.py`는 `timeouts.py`를, `hass_ops.py`는 `config.py`를 참조하므로 값이 다르게 변경될 위험이 있습니다. (`backend/config.py:250`, `backend/core/utils/timeouts.py:16`)

## 개선 제안

### 1. HTTPS 전환 (최우선)
Home Assistant에 SSL/TLS를 설정하고 `HASS_URL`을 `https://`로 전환합니다. Let's Encrypt + Nginx reverse proxy, 또는 HA 내장 SSL 기능을 활용할 수 있습니다. 코드 변경 없이 환경 변수만 바꾸면 되므로 가장 효율적입니다.

### 2. HTTP 경고 로깅
HTTPS 전환이 즉시 불가능한 경우, 최소한 HTTP 사용 시 시작 시점에 경고 로그를 출력하여 인지할 수 있도록 합니다.

### 3. http_pool 자격 증명 갱신 메커니즘
현재 `http_pool.py`의 "생성 후 영구 캐싱" 패턴을 개선하여, 자격 증명 변경을 감지하거나, HASS 전용 클라이언트를 매 요청 시 헤더를 업데이트하는 방식으로 변경합니다.

### 4. 설정 일원화
`HASS_TIMEOUT` 설정이 `config.py`, `timeouts.py`, `hass_ops.py`(로컬 상수) 3곳에 산재합니다. `config.py`를 단일 소스로 통일하고, `timeouts.py`는 `config.py`를 참조하도록 변경합니다.

### 5. warmwhite 버그 수정
`COLOR_MAP`에 `"warmwhite"` 항목을 추가하여 relax 씬이 의도대로 동작하도록 수정합니다. 이것은 기능 버그이므로 보안과 별개로 즉시 수정이 바람직합니다.

## 수정 난이도

| 항목 | 난이도 | 이유 |
|------|--------|------|
| HTTPS 전환 | 중 | HA 측 SSL 설정 필요, 코드는 환경 변수 변경만 |
| HTTP 경고 로깅 | 하 | `_get_hass_credentials()`에 3줄 추가 |
| http_pool stale 클라이언트 | 중 | 기존 클라이언트 폐기 로직 + 테스트 필요 |
| 로컬 상수 shadowing 제거 | 하 | 2줄 삭제 |
| warmwhite COLOR_MAP 추가 | 하 | 1줄 추가 |
| HASS 응답 본문 누출 제한 | 하 | `resp.text[:200]`을 상태 코드만으로 교체 |
| 조명 병렬 제어 | 하 | `asyncio.gather()` 적용 |
| toggle 액션 스키마 노출 | 하 | enum에 "toggle" 추가 |
| .env.example 기본값 통일 | 하 | 문서 수정 |
| 타임아웃 설정 일원화 | 중 | 3개 파일 동시 변경, 의존 관계 확인 필요 |
