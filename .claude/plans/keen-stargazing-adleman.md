# TTS Hang Fix + Idle Unload + Process Isolation

## Context

`axnmihn-backend.service` 메모리 2.9G + swap 1.1G 사용 확인. 원인은 TTS 요청 시 Qwen3-TTS 모델(~600MB) + PyTorch/CUDA 런타임(~1.5GB)이 Lazy 싱글톤으로 영구 상주하기 때문.
추가로 TTS 엔드포인트에 timeout/queue limit/disconnect 감지가 없어 Open WebUI의 문장별 동시 요청이 쌓이면 무한 대기 발생.

---

## Phase 1: TTS Hang Fix

### 1.1 Config 추가 — `backend/config.py` (line 318 뒤)

```python
# TTS Configuration
TTS_SYNTHESIS_TIMEOUT = _get_float_env("TTS_SYNTHESIS_TIMEOUT", 30.0)
TTS_FFMPEG_TIMEOUT = _get_float_env("TTS_FFMPEG_TIMEOUT", 10.0)
TTS_QUEUE_MAX_PENDING = _get_int_env("TTS_QUEUE_MAX_PENDING", 3)
TTS_IDLE_TIMEOUT = _get_int_env("TTS_IDLE_TIMEOUT", 300)  # Phase 2에서 사용
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")  # Phase 3에서 사용
```

### 1.2 `backend/media/qwen_tts.py` 수정

- `QueueFullError` exception 추가
- `Qwen3TTS.synthesize()` 변경:
  - `threading.Lock`으로 보호하는 `_pending` 카운터 추가
  - `_pending >= TTS_QUEUE_MAX_PENDING` 시 `QueueFullError` raise
  - `asyncio.wait_for(..., timeout=TTS_SYNTHESIS_TIMEOUT)` 감싸기
  - `finally`에서 `_pending` 감소

### 1.3 `backend/api/audio.py` 수정

- `create_speech()`:
  - `Request` 파라미터 추가 → `await raw_request.is_disconnected()` 체크
  - `QueueFullError` → HTTP 429
  - `asyncio.TimeoutError` → HTTP 504
- `convert_wav_to_mp3()`:
  - `tempfile.mktemp()` → `tempfile.NamedTemporaryFile(delete=False)`
  - `subprocess.run(..., timeout=TTS_FFMPEG_TIMEOUT)`
  - `asyncio.to_thread()`로 감싸서 이벤트 루프 블로킹 방지

---

## Phase 2: Idle Unload

### 2.1 새 파일 `backend/media/tts_manager.py`

BrowserManager 패턴 (`protocols/mcp/research/browser.py:86-105`) 참고:

- `TTSManager` 클래스:
  - `_last_used: float` — 마지막 TTS 사용 시각
  - `_idle_checker: asyncio.Task | None` — 60초마다 idle 체크
  - `touch()` — `_last_used` 갱신, idle checker 없으면 시작
  - `_unload()` — `_lazy_model.reset()`, `_lazy_voice_prompt.reset()`, `torch.cuda.empty_cache()`, `gc.collect()`
  - `shutdown()` — idle checker 취소, 모델 해제

### 2.2 `backend/media/qwen_tts.py` 연동

- `_synthesize_sync()` 첫 줄에 `get_tts_manager().touch()` 호출
- `_lazy_tts_manager` 싱글톤 추가

### 2.3 `backend/app.py` shutdown 연동 (line 127 뒤)

- `_lazy_tts_manager._instance` 직접 접근 (get() 아닌 — shutdown에서 불필요한 생성 방지)
- `await mgr.shutdown()` with timeout

---

## Phase 3: Process Isolation

### 3.1 유틸 분리 — 새 파일 `backend/media/tts_utils.py`

`audio.py`에서 `clean_text_for_tts()`와 `convert_wav_to_mp3()` 추출

### 3.2 TTS 마이크로서비스 — 새 파일 `backend/media/tts_service.py`

- 독립 FastAPI 앱: `python -m backend.media.tts_service 127.0.0.1 8001`
- `POST /v1/audio/speech` — Phase 1 보호 + Phase 2 idle unload 내장
- `GET /health` — systemd healthcheck용
- torch/CUDA import이 이 프로세스에서만 발생

### 3.3 `backend/api/audio.py` → dual-mode 프록시

```python
if TTS_SERVICE_URL:
    return await _proxy_to_tts_service(request, raw_request)
else:
    return await _synthesize_in_process(request, raw_request)
```

프록시는 `http_pool.get_client("tts", ...)` 사용 (기존 패턴)

### 3.4 systemd unit — `~/.config/systemd/user/axnmihn-tts.service`

- `MemoryMax=4G`, `MemoryHigh=3G`
- 로그: `logs/tts.log`, `logs/tts_error.log`
- `Restart=on-failure`

### 3.5 메인 서비스 조정

- `axnmihn-backend.service`: `MemoryMax=6G→4G`, `MemoryHigh=5G→3G`
- `.env`에 `TTS_SERVICE_URL=http://127.0.0.1:8001` 추가

---

## 수정 파일 요약

| 파일 | 변경 |
|------|------|
| `backend/config.py` | TTS_* 상수 5개 추가 |
| `backend/media/qwen_tts.py` | QueueFullError, pending 카운터, timeout, touch() |
| `backend/api/audio.py` | disconnect 감지, timeout, 429/504, async mp3 변환, proxy mode |
| `backend/media/tts_manager.py` | **신규** — idle unload 관리자 |
| `backend/media/tts_utils.py` | **신규** — clean_text/convert_mp3 추출 |
| `backend/media/tts_service.py` | **신규** — 독립 TTS FastAPI 서비스 |
| `backend/app.py` | shutdown에 TTS cleanup 추가 |
| `~/.config/systemd/user/axnmihn-tts.service` | **신규** — TTS 전용 systemd unit |
| `~/.config/systemd/user/axnmihn-backend.service` | 메모리 제한 조정, TTS_SERVICE_URL 환경변수 |
| `.env.example` | TTS 관련 환경변수 문서화 |

## Verification

1. **Phase 1 테스트**: 5개 동시 TTS 요청 → 3개 처리, 2개 429 응답 확인
2. **Phase 2 테스트**: TTS 1회 호출 후 5분 대기 → 로그에 "idle unload" 확인, 메모리 감소 확인
3. **Phase 3 테스트**: `systemctl --user start axnmihn-tts` → 별도 PID 확인, 메인 프로세스 ~200MB 유지
