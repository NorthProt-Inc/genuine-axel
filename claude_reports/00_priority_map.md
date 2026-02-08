# 우선순위 목록 (Priority Map)

> 생성일: 2026-02-04
> 분석 범위: axnmihn 전체 프로젝트 (~90 Python 파일)
> 분석 세션: Session 0 (INIT)

---

## 요약

axnmihn은 기능적으로 잘 작동하는 AI 에이전트 시스템이나, **명령어 인젝션 취약점**, **God Object 패턴**, **광범위한 예외 삼킴**이 주요 리스크입니다. 설계 관점에서 `chat_handler.py`(938줄)와 `mcp_server.py`(987줄)의 거대 파일 분리가 시급하며, 보안 관점에서 `shell=True` 사용이 즉시 수정 대상입니다.

---

### 1. `run_command` 명령어 인젝션 — CRITICAL
- **관점**: 보안
- **범위**: `backend/core/mcp_tools/system_tools.py:57-62`
- **설명**: `subprocess.run(command, shell=True)`로 사용자 입력을 직접 실행합니다. MCP 도구 `run_command`의 설명에 "Full bash shell access"와 "sudo available WITHOUT password"라고 명시되어 있어, LLM이 생성한 임의 명령어가 루트 권한으로 실행될 수 있습니다. 악의적인 프롬프트 인젝션을 통해 시스템 전체가 위험에 노출됩니다.
- **우선순위 근거**: 시스템 전체 탈취 가능한 최고 위험도 취약점. 외부 입력(LLM 출력)이 검증 없이 셸에 전달됨.

### 2. ChatHandler God Object — HIGH
- **관점**: 설계 품질 ★
- **범위**: `backend/core/chat_handler.py` (938줄 전체)
- **설명**: `process()` 메서드(223~561줄, 339줄)에 컨텍스트 빌드, 웹 검색, LLM 스트리밍, 도구 실행 루프, 후처리, 메모리 저장이 모두 집중되어 있습니다. `_build_context_and_prompt()`(621~790줄, 170줄)도 메모리 3계층 조회와 코드 인젝션을 한 함수에서 처리합니다. 단일 책임 원칙(SRP)을 심각하게 위반하며, 테스트가 사실상 불가능합니다.
- **우선순위 근거**: 프로젝트의 핵심 파이프라인으로 모든 변경이 이 파일을 거침. 유지보수 비용이 가장 높은 파일.

### 3. mcp_server.py 거대 모놀리스 — HIGH
- **관점**: 설계 품질 ★
- **범위**: `backend/core/mcp_server.py` (987줄 전체)
- **설명**: 도구 정의 25개(148~758줄, 610줄의 Tool schema), 도구 디스패치(`call_tool`, 761~807줄), SSE 전송 계층(815~947줄), FastAPI 앱 설정이 단일 파일에 혼재합니다. 도구 스키마 변경, 전송 계층 수정, 디스패치 로직 변경이 모두 같은 파일을 건드려 **샷건 수술**이 발생합니다. 또한 `import os`가 1줄과 11줄에 중복, `import sys`가 1줄과 87줄에 중복됩니다.
- **우선순위 근거**: 두 번째로 큰 파일. 도구 추가/수정 시마다 이 파일을 수정해야 하며, 스키마·디스패치·전송이 분리되지 않음.

### 4. 광범위한 예외 삼킴 (except: pass) — HIGH
- **관점**: 버그 & 안정성
- **범위**: 프로젝트 전반 (27개소 이상)
- **설명**: `except Exception: pass` 또는 `except: pass`가 27개 이상 발견됩니다. 특히 `scripts/populate_knowledge_graph.py:112`와 `scripts/dedup_knowledge_graph.py:172,223`에서 bare `except:`를 사용합니다. `backend/core/tools/system_observer.py:298,339`에서 파일 읽기/디렉토리 리스팅 실패를 완전히 무시하며, `backend/memory/permanent.py:639`에서 임베딩 업데이트 실패를 무시합니다. 이로 인해 잠재적 버그가 숨겨지고 디버깅이 극도로 어려워집니다.
- **우선순위 근거**: 데이터 손실/손상을 유발할 수 있는 silent failure. 프로젝트 전반에 걸쳐 광범위하게 퍼져 있음.

### 5. LongTermMemory God Class — HIGH
- **관점**: 설계 품질 ★
- **범위**: `backend/memory/permanent.py` (600줄+)
- **설명**: 임베딩 생성, ChromaDB CRUD, 유사도 기반 중복 검사, decay 계산, consolidation, 접근 패턴 추적, 통계가 모두 한 클래스에 있습니다. EmbeddingService, MemoryRepository, DecayCalculator, Consolidator 등으로 분리할 수 있습니다.
- **우선순위 근거**: 메모리 시스템의 핵심 클래스. 임베딩 모델 변경, 저장소 교체 시 전체 클래스를 수정해야 함.

### 6. SessionArchive 단일 책임 위반 — HIGH
- **관점**: 설계 품질 ★
- **범위**: `backend/memory/recent.py` (784줄)
- **설명**: SQLite 연결 관리, 스키마 마이그레이션, 메시지 CRUD, 세션 저장/검색, 통계 계산, 검색이 한 클래스입니다. `__del__`에 의존한 연결 종료(`recent.py:770-783`)는 GC 타이밍에 따라 리소스 누수를 유발할 수 있습니다. Context manager 미구현.
- **우선순위 근거**: 데이터 지속성 계층의 핵심. SQLite 연결 누수는 파일 잠금 문제로 이어질 수 있음.

### 7. 경로 탐색 취약점 — MEDIUM
- **관점**: 보안
- **범위**: `backend/core/tools/system_observer.py:146-147`
- **설명**: `if ".." in str(log_path)` 같은 단순 문자열 검사로 경로 탐색을 방어하고 있습니다. URL 인코딩, 심볼릭 링크, 유니코드 정규화로 우회 가능합니다. `Path.resolve()`로 정규화 후 허용 디렉토리 범위 내인지 확인해야 합니다.
- **우선순위 근거**: 파일 시스템 접근 도구이므로 민감 파일 노출 위험. 단, MCP 도구를 통해서만 접근 가능하여 직접 외부 노출은 제한적.

### 8. research_server.py 모놀리스 — MEDIUM
- **관점**: 설계 품질 ★
- **범위**: `backend/protocols/mcp/research_server.py` (851줄)
- **설명**: Playwright 브라우저 관리, HTML-to-Markdown 파싱, DuckDuckGo 검색, Tavily 검색, 아티팩트 저장이 한 파일에 있습니다. 브라우저 페이지 닫기 실패 시(`432-444줄`) 예외를 삼켜 리소스 누수가 발생할 수 있습니다.
- **우선순위 근거**: 외부 서비스(Playwright, Tavily)와의 통합 지점. 브라우저 누수는 메모리 문제로 이어짐.

### 9. Opus 코드 중복 (opus_executor vs opus_bridge) — MEDIUM
- **관점**: 중복 (DRY 위반)
- **범위**: `backend/core/tools/opus_executor.py`, `backend/protocols/mcp/opus_bridge.py`
- **설명**: `_build_context_block()`, `_safe_decode()`, `_generate_task_summary()` 함수가 두 파일에 거의 동일하게 복제되어 있습니다. Opus 위임 로직의 이중 구현으로, 한쪽만 수정하면 다른 쪽과 불일치가 발생합니다.
- **우선순위 근거**: 기능 중복으로 인한 불일치 버그 위험. 공통 모듈 추출로 쉽게 해결 가능.

### 10. Retry 로직 중복 — MEDIUM
- **관점**: 중복 (DRY 위반)
- **범위**: `backend/core/utils/gemini_wrapper.py`, `backend/llm/clients.py`, `backend/core/mcp_client.py`
- **설명**: 지수 백오프 재시도 로직(`for attempt in range(1, MAX_RETRIES+1): try/except/sleep`)이 최소 3곳에서 거의 동일하게 반복됩니다. `backend/core/utils/retry.py`가 존재하지만 활용되지 않고 있을 가능성이 있습니다.
- **우선순위 근거**: 재시도 정책 변경 시 여러 파일을 동시 수정해야 하는 샷건 수술 유발.

### 11. 전역 가변 상태 (Global Mutable State) — MEDIUM
- **관점**: 변경 용이성
- **범위**: `backend/app.py:38-39,228-230`, `backend/protocols/mcp/async_research.py:48`, `backend/core/mcp_server.py:813`
- **설명**: `app.py`에서 `_shutdown_event`, `_background_tasks`, `gemini_model`, `memory_manager`, `long_term_memory`이 모듈 레벨 전역 변수로 선언되고 lifespan 내에서 `global`로 재할당됩니다. `async_research.py`의 `_active_tasks: dict`도 전역 가변 상태입니다. 멀티 워커 환경에서 레이스 컨디션 위험이 있으며, 테스트 격리가 어렵습니다.
- **우선순위 근거**: 현재 단일 프로세스이므로 즉각적 위험은 낮으나, 확장 시 심각한 문제 유발.

### 12. MemoryManager 동기/비동기 컨텍스트 빌드 중복 — MEDIUM
- **관점**: 중복 (DRY 위반)
- **범위**: `backend/memory/unified.py:120-195` (sync), `backend/memory/unified.py:197-325` (async)
- **설명**: `_build_smart_context_sync()`와 `_build_smart_context_async()`가 거의 동일한 로직을 동기/비동기 두 버전으로 유지하고 있습니다. 메모리 조회 로직 변경 시 두 함수를 모두 수정해야 합니다.
- **우선순위 근거**: 비즈니스 로직 중복으로 불일치 버그 위험. asyncio.to_thread 래핑으로 통합 가능.

### 13. 하드코딩된 IoT 디바이스 ID — MEDIUM
- **관점**: 변경 용이성
- **범위**: `backend/core/tools/hass_ops.py:15-22`
- **설명**: Home Assistant 조명 엔티티 ID(`light.wiz_rgbw_tunable_77d6a0` 등)가 코드에 직접 하드코딩되어 있습니다. 디바이스 추가/교체 시 코드 수정과 재배포가 필요합니다. Home Assistant API에서 동적으로 조회하거나 설정 파일로 분리해야 합니다.
- **우선순위 근거**: IoT 기기 변경은 빈번하며, 코드 변경 없이 대응할 수 없는 구조.

### 14. 매직 넘버 산재 — MEDIUM
- **관점**: 변경 용이성
- **범위**: `chat_handler.py:289` (MAX_LOOPS=15), `research_server.py:58-60` (PAGE_TIMEOUT_MS=15000 등), `mcp_server.py:36-38` (SSE_KEEPALIVE_INTERVAL=15 등)
- **설명**: 타임아웃, 최대 반복 횟수, 버퍼 크기 등의 운영 파라미터가 각 파일에 로컬 상수로 흩어져 있습니다. `config.py`에 이미 중앙 설정 패턴이 있으나 일부 모듈이 이를 따르지 않습니다.
- **우선순위 근거**: 운영 환경 튜닝 시 여러 파일을 찾아 수정해야 하는 불편. 기존 config 패턴 확장으로 해결 가능.

### 15. MCP 도구 스키마-핸들러 분리 부재 — MEDIUM
- **관점**: 설계 품질 ★
- **범위**: `backend/core/mcp_server.py:148-758`, `backend/core/mcp_tools/`
- **설명**: `mcp_server.py`의 `list_tools()`에 25개 도구의 JSON Schema가 610줄에 걸쳐 정의되어 있고, 실제 핸들러는 `mcp_tools/` 디렉토리에 분리되어 있습니다. 스키마와 핸들러가 별도 파일에 있어 동기화 실수가 발생하기 쉽습니다. 스키마를 핸들러와 같은 위치에 두거나, 데코레이터 기반 자동 등록이 필요합니다.
- **우선순위 근거**: 도구 추가/수정의 주요 접점. 스키마-핸들러 불일치는 런타임 에러로 이어짐.

### 16. app.py 전역 변수와 lifespan 혼재 — MEDIUM
- **관점**: 설계 품질 ★
- **범위**: `backend/app.py:38-39,44,228-243`
- **설명**: 모듈 레벨에서 `gemini_model = None`, `memory_manager = None`을 선언하고 `init_state()`에 전달한 뒤, lifespan에서 `global`로 재할당합니다. 모듈 로드 시점의 `None` 상태와 lifespan 이후의 실제 객체 간의 불일치가 발생하며, `init_state()`에 전달된 `None`이 나중에 업데이트되는지 불명확합니다.
- **우선순위 근거**: 앱 시작 순서에 민감한 버그 유발 가능. state 패턴 정리로 해결 가능.

### 17. 글로벌 예외 핸들러의 내부 정보 노출 — MEDIUM
- **관점**: 보안
- **범위**: `backend/app.py:195-222`
- **설명**: 전역 예외 핸들러가 `str(exc)`, `type(exc).__name__`, `request.url.path`를 JSON 응답에 포함합니다. 프로덕션에서 스택 정보와 내부 에러 메시지가 클라이언트에 노출되어 정보 수집에 활용될 수 있습니다.
- **우선순위 근거**: 현재 내부 사용 시스템이므로 즉각 위험은 낮으나, 외부 노출 시 보안 이슈.

### 18. MCPClient 이중 호출 방식 — MEDIUM
- **관점**: 설계 품질 ★
- **범위**: `backend/core/mcp_client.py`
- **설명**: 직접 import(`from backend.core.mcp_server import call_tool`)와 HTTP 호출을 하나의 클래스에서 혼용합니다. Strategy 패턴으로 분리하여 전송 방식을 설정으로 결정해야 합니다.
- **우선순위 근거**: 두 가지 코드 경로가 공존하여 디버깅 시 혼란 유발.

### 19. 테스트 부재 — HIGH
- **관점**: 변경 용이성
- **범위**: 프로젝트 전체
- **설명**: `tests/` 디렉토리가 존재하지 않으며, 단위 테스트나 통합 테스트가 전혀 없습니다. 핵심 로직(ChatHandler, MemoryManager, MCP 도구)의 변경 시 회귀 검증이 불가능합니다.
- **우선순위 근거**: 리팩토링의 전제 조건. 테스트 없이 #2~#6의 거대 파일 분리는 위험.

### 20. import 중복 및 미사용 — LOW
- **관점**: 불필요한 코드
- **범위**: `backend/core/mcp_server.py:1,11` (`import os` 중복), `backend/core/mcp_server.py:1,87` (`import sys` 중복)
- **설명**: 동일 모듈의 import가 파일 내에서 반복됩니다. 파일이 유기적으로 성장하며 정리되지 않은 흔적입니다.
- **우선순위 근거**: 기능적 영향 없으나 코드 품질 저하. 자동 린터로 쉽게 해결.

### 21. `_XML_TAG_PATTERN` 하드코딩된 도구 이름 — LOW
- **관점**: 변경 용이성
- **범위**: `backend/core/chat_handler.py:25-43`
- **설명**: LLM 출력에서 제거할 XML 태그 패턴에 MCP 도구 이름(`list_directory`, `web_search`, `hass_control_light` 등)이 하드코딩되어 있습니다. 새 도구 추가 시 이 정규식도 수정해야 하며, 누락 시 도구 태그가 사용자에게 노출됩니다.
- **우선순위 근거**: 도구 목록과 동기화 필요. 도구 레지스트리에서 자동 생성하면 해결.

### 22. Home Assistant HTTP 통신 — LOW
- **관점**: 보안
- **범위**: `backend/core/tools/hass_ops.py:138`
- **설명**: `HASS_URL` 기본값이 `http://192.168.1.131:8123`으로 평문 HTTP입니다. 로컬 네트워크 내 통신이지만, Bearer 토큰이 암호화되지 않은 채널로 전송됩니다.
- **우선순위 근거**: 로컬 네트워크 한정이므로 위험도 낮음. HTTPS 전환 권장.

### 23. `migrate_legacy_data` docstring 위치 오류 — LOW
- **관점**: 복잡도 & 가독성
- **범위**: `backend/memory/unified.py:506-508`
- **설명**: `def migrate_legacy_data(self, old_db_path: str = None, dry_run: bool = True) -> Dict:` 직후 `old_db_path = old_db_path or str(CHROMADB_PATH)` 할당이 있고, 그 다음 줄에 docstring `"""Migrate data from old ChromaDB."""`이 있습니다. Python에서 docstring은 함수 정의 직후 첫 번째 표현식이어야 하므로, 이 docstring은 인식되지 않습니다.
- **우선순위 근거**: 기능적 영향 없으나 코드 품질/문서화 문제.

---

## 심각도별 분포

| 심각도 | 항목 수 | 항목 번호 |
|--------|---------|-----------|
| **CRITICAL** | 1 | #1 |
| **HIGH** | 5 | #2, #3, #4, #5, #6, #19 |
| **MEDIUM** | 12 | #7, #8, #9, #10, #11, #12, #13, #14, #15, #16, #17, #18 |
| **LOW** | 4 | #20, #21, #22, #23 |

## 관점별 분포

| 관점 | 항목 수 | 항목 번호 |
|------|---------|-----------|
| 설계 품질 ★ | 8 | #2, #3, #5, #6, #8, #15, #16, #18 |
| 보안 | 3 | #1, #7, #17, #22 |
| 버그 & 안정성 | 1 | #4 |
| 중복 (DRY) | 3 | #9, #10, #12 |
| 변경 용이성 | 5 | #11, #13, #14, #19, #21 |
| 불필요한 코드 | 1 | #20 |
| 복잡도 & 가독성 | 1 | #23 |

---

## 권장 리뷰 순서

1. **#1** → 즉시 수정 (보안 CRITICAL)
2. **#2, #3** → 설계 분석 리포트 (가장 가치 있는 피드백)
3. **#4** → 예외 처리 전수 조사
4. **#19** → 테스트 전략 수립 (리팩토링 전제조건)
5. **#5, #6** → 메모리 계층 리팩토링
6. **#9, #10, #12** → 중복 제거
7. 나머지 MEDIUM → 점진적 개선
