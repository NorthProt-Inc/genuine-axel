# OpenClaw → axnmihn 오케스트레이션 & 자율에이전트 기능 통합 계획

## 문제 정의

axnmihn은 단일 ReAct 루프 기반의 순차적 에이전트 실행만 지원한다.
openclaw에서 검증된 오케스트레이션 패턴(Sub-Agent, Lane 큐잉, Failover, Compaction, Skill System 등)을
**기존 ChatHandler/ReActService 흐름에 유기적으로 통합**하여 자율 에이전트 역량을 강화한다.

## 설계 원칙

- **데드코드 금지**: 모든 새 코드는 기존 흐름에서 즉시 사용되어야 함
- **순수 asyncio**: Celery/Redis 없이 asyncio.Queue, Lock, Semaphore 사용
- **기존 인터페이스 유지**: ChatHandler.process() 시그니처 변경 없음
- **점진적 활성화**: 환경변수 플래그로 기능별 on/off 가능
- **TDD**: 각 기능별 테스트 먼저 작성

## 통합 지점 맵

```
기존 흐름:
  ChatHandler.process()
    → ContextService.build()
    → SearchService (optional)
    → ReActLoopService.run()           ← [Lane 큐잉, Failover, Compaction 통합]
      → ToolExecutionService.execute() ← [Tool Result Guard, SubAgent 도구 추가]
    → MemoryPersistenceService

새로 추가되는 횡단 관심사:
  LLM Router (router.py)               ← [Failover + Auth Profile 순환]
  ContextService._build_system_prompt() ← [Skill System 프롬프트 주입]
  app.py lifespan                       ← [Lane Manager, Scheduler, SubAgent Registry 초기화]
  config.py                             ← [ORCHESTRATION_* 환경변수]
```

---

## Phase 1: 인프라 기반 — Failover & Resilience

### 1-1. Failover Error 분류 체계 (`backend/core/errors.py` 확장)

**변경 파일**: `backend/core/errors.py`
**통합 지점**: 기존 `ProviderError`, `TransientError` 확장

- `FailoverReason` enum 추가: `billing`, `rate_limit`, `auth`, `timeout`, `context_overflow`, `overload`
- `FailoverError(ProviderError)` 서브클래스: reason, provider, model, profile_id 속성
- `classify_failover_reason(error: Exception) -> FailoverReason | None` 유틸리티 함수
- 기존 `ProviderError`를 던지는 모든 곳에서 `FailoverError`로 세분화

### 1-2. Auth Profile Manager (`backend/llm/auth_profiles.py` 신규)

**신규 파일**: `backend/llm/auth_profiles.py`
**통합 지점**: `backend/llm/router.py`의 `get_model()` → 클라이언트 생성 시 auth profile 주입

- `AuthProfile` dataclass: id, provider, api_key, last_used, failure_reason, cooldown_until
- `AuthProfileManager` 클래스:
  - `get_active_profile(provider: str) -> AuthProfile`
  - `mark_failure(profile_id: str, reason: FailoverReason)` → 쿨다운 설정
  - `rotate_profile(provider: str) -> AuthProfile` → 다음 사용 가능한 프로파일
  - `is_in_cooldown(profile_id: str) -> bool`
- `config.py`에 `AUTH_PROFILES` 환경변수 추가 (JSON 또는 콤마 구분 키 목록)
- **즉시 사용**: `get_llm_client()` 팩토리에서 AuthProfileManager를 통해 API 키 선택

### 1-3. LLM Router Failover 통합 (`backend/llm/router.py` 수정)

**변경 파일**: `backend/llm/router.py`, `backend/llm/base.py`
**통합 지점**: `BaseLLMClient.generate_stream()` 래핑

- `FailoverLLMClient(BaseLLMClient)` 래퍼: 내부 클라이언트를 감싸고 failover 로직 실행
  - `generate_stream()` 오버라이드: FailoverError 발생 시 auth profile 순환 → 재시도
  - `max_failover_attempts` (기본 3)
  - billing/auth → 프로파일 순환, rate_limit → 백오프, context → compaction 시그널
- `get_llm_client()` 팩토리 수정: `FailoverLLMClient`로 래핑하여 반환
- **즉시 사용**: 모든 LLM 호출이 자동으로 failover 혜택을 받음

---

## Phase 2: 실행 제어 — Lane 큐잉 & Compaction

### 2-1. Lane Manager (`backend/core/orchestration/lane_manager.py` 신규)

**신규 파일**: `backend/core/orchestration/lane_manager.py`
**통합 지점**: `ReActLoopService.run()` 진입부에서 Lane 획득

- `LaneType` enum: `session`, `global_`, `nested`, `subagent`
- `LaneManager` 클래스:
  - 내부: `Dict[str, asyncio.Lock]` (세션별 락), `asyncio.Semaphore` (글로벌 동시성)
  - `acquire_lane(session_id: str, lane_type: LaneType) -> AsyncContextManager`
  - `get_active_count() -> Dict[LaneType, int]` (모니터링용)
- config: `LANE_GLOBAL_CONCURRENCY` (기본 5), `LANE_SESSION_CONCURRENCY` (기본 1)
- **즉시 사용**: `ReActLoopService.run()` 시작 시 `async with lane_manager.acquire_lane(session_id, LaneType.session):`

### 2-2. Context Compaction (`backend/core/orchestration/compaction.py` 신규)

**신규 파일**: `backend/core/orchestration/compaction.py`
**통합 지점**: `ReActLoopService.run()` 루프 내 context_overflow 에러 핸들링

- `CompactionStrategy` Protocol: `compact(messages: list[dict]) -> list[dict]`
- `SummarizeCompaction(CompactionStrategy)`:
  - 오래된 턴을 LLM 요약으로 대체 (유틸리티 모델 사용)
  - 도구 결과 트렁케이션 (큰 결과 → 요약)
  - 최근 N턴은 보존 (기본 5)
- `TruncateCompaction(CompactionStrategy)`: 단순 앞부분 잘라내기 (폴백)
- `compact_on_overflow(messages, strategy) -> CompactResult`
  - `CompactResult`: compacted_messages, removed_count, summary
- config: `COMPACTION_STRATEGY` (summarize|truncate), `COMPACTION_PRESERVE_TURNS` (기본 5)
- **즉시 사용**: ReAct 루프에서 `ProviderError(context_overflow)` 캐치 → compaction 실행 → 재시도

### 2-3. Tool Result Guard (`backend/core/orchestration/tool_result_guard.py` 신규)

**신규 파일**: `backend/core/orchestration/tool_result_guard.py`
**통합 지점**: `ToolExecutionService._execute_single()` 반환값 후처리

- `ToolResultGuard` 클래스:
  - `cap_result_size(result: str, budget: int = 100_000) -> str`
  - 비례적 트렁케이션: 결과가 budget 초과 시 줄바꿈 경계에서 자르기
  - 절단 시 `[truncated — use offset/limit parameters]` 알림 추가
  - `cap_batch_results(results: list[ToolResult], total_budget: int) -> list[ToolResult]`
- config: `TOOL_RESULT_MAX_CHARS` (기본 100,000)
- **즉시 사용**: `ToolExecutionService._execute_single()` 에서 `mcp_client.call_tool()` 결과를 `ToolResultGuard.cap_result_size()`로 래핑

### 2-4. ReActLoopService 통합 수정 (`backend/core/services/react_service.py` 수정)

**변경 파일**: `backend/core/services/react_service.py`

- `run()` 메서드 진입부: `lane_manager.acquire_lane()` 추가
- 루프 내 에러 핸들링:
  - `FailoverError(context_overflow)` → `compact_on_overflow()` 호출 → 루프 재시작
  - `FailoverError(rate_limit)` → asyncio.sleep(백오프) → 재시도
- 도구 실행 결과: `ToolResultGuard.cap_result_size()` 적용
- 새 `ChatEvent` 타입: `COMPACTION_START`, `COMPACTION_END` (클라이언트 알림용)

---

## Phase 3: 자율 에이전트 — Sub-Agent & Skill System

### 3-1. Sub-Agent Registry (`backend/core/orchestration/subagent_registry.py` 신규)

**신규 파일**: `backend/core/orchestration/subagent_registry.py`
**통합 지점**: `app.py` lifespan에서 초기화, MCP 도구로 노출

- `SubAgentRun` dataclass:
  - run_id, parent_session_id, child_session_id, task, status, result, created_at
- `SubAgentRegistry` 클래스:
  - `register_run(parent_id, task, model_override?) -> SubAgentRun`
  - `get_run(run_id) -> SubAgentRun | None`
  - `list_runs(parent_id?) -> list[SubAgentRun]`
  - `mark_completed(run_id, result: str)`
  - `mark_failed(run_id, error: str)`
  - `cleanup_completed(max_age_seconds: int = 3600)`
  - 내부 저장: `Dict[str, SubAgentRun]` (인메모리, 단일 서버 충분)
- **즉시 사용**: MCP spawn_agent 도구 + ChatHandler에서 서브에이전트 결과 수신

### 3-2. Sub-Agent Spawning MCP 도구 (`backend/core/mcp_tools/agent_tools.py` 신규)

**신규 파일**: `backend/core/mcp_tools/agent_tools.py`
**통합 지점**: MCP 도구 등록 (기존 도구 등록 패턴 따름)

- `spawn_agent` 도구:
  - 파라미터: task (str), model_override (optional), timeout_seconds (기본 120)
  - 실행: 새 asyncio.Task로 ChatHandler.process() 호출 (격리된 세션)
  - 결과: SubAgentRegistry에 등록, 완료 시 부모 세션에 알림
  - 재귀 방지: 중첩 깊이 제한 (MAX_SUBAGENT_DEPTH = 3)
- `list_agents` 도구: 활성 서브에이전트 목록 조회
- `get_agent_result` 도구: 완료된 서브에이전트 결과 조회
- config: `SUBAGENT_ENABLED` (기본 true), `MAX_SUBAGENT_DEPTH` (기본 3), `SUBAGENT_TIMEOUT` (기본 120)
- **즉시 사용**: MCP 도구로 등록 → ReAct 루프에서 AI가 자율적으로 호출

### 3-3. Skill System (`backend/core/orchestration/skill_system.py` 신규)

**신규 파일**: `backend/core/orchestration/skill_system.py`
**통합 지점**: `ContextService._build_system_prompt()` → 스킬 섹션 주입

- `SkillMetadata` dataclass: skill_key, description, emoji, always_load, requires
- `SkillEntry` dataclass: name, path, metadata, content (lazy)
- `SkillLoader` 클래스:
  - `load_skills(skills_dir: str) -> list[SkillEntry]` — SKILL.md 프론트매터 파싱
  - `resolve_skills_prompt(entries: list[SkillEntry]) -> str` — 시스템 프롬프트 섹션 생성
  - `get_skill_content(skill_key: str) -> str` — 레이지 로딩 (AI가 read 도구로 요청 시)
- 스킬 디렉토리: `data/skills/` (프로젝트 루트)
- **즉시 사용**: ContextService.build()에서 시스템 프롬프트에 available_skills 섹션 추가
- 초기 스킬: `research` (기존 리서치 기능), `home-assistant` (기존 HASS 기능), `code-review` (코드 분석)

### 3-4. Agent-to-Agent 메시징 (`backend/core/orchestration/agent_messaging.py` 신규)

**신규 파일**: `backend/core/orchestration/agent_messaging.py`
**통합 지점**: SubAgent 결과 전달, MCP 도구

- `AgentMessage` dataclass: from_session, to_session, content, message_type (result|request|notification)
- `AgentMessageBus` 클래스:
  - `send(message: AgentMessage)`
  - `subscribe(session_id: str) -> AsyncGenerator[AgentMessage]`
  - `get_pending(session_id: str) -> list[AgentMessage]`
  - 내부: `Dict[str, asyncio.Queue]` (세션별 메시지 큐)
- ACL: `can_send(from_session, to_session) -> bool` — 부모-자식 관계만 허용
- **즉시 사용**: spawn_agent 완료 시 결과를 부모 세션에 전달

---

## Phase 4: 스케줄링 & 스트리밍

### 4-1. Agent Scheduler (`backend/core/orchestration/scheduler.py` 신규)

**신규 파일**: `backend/core/orchestration/scheduler.py`
**통합 지점**: `app.py` lifespan에서 시작, MCP 도구로 노출

- `ScheduledJob` dataclass: job_id, schedule_type (at|every|cron), task, next_run, session_id
- `AgentScheduler` 클래스:
  - `add_job(schedule, task, session_id) -> ScheduledJob`
  - `remove_job(job_id)`
  - `list_jobs(session_id?) -> list[ScheduledJob]`
  - `start()` / `stop()` — asyncio.Task 기반 루프
  - 내부: 힙 기반 다음 실행 시간 관리
- 스케줄 타입:
  - `at`: 일회성 (Unix timestamp)
  - `every`: 반복 (seconds 간격)
  - `cron`: 크론 표현식 (croniter 라이브러리)
- 작업 타입:
  - `system_event`: 세션에 시스템 메시지 주입
  - `agent_turn`: 격리된 에이전트 실행 (spawn_agent와 유사)
- config: `SCHEDULER_ENABLED` (기본 true), `SCHEDULER_MAX_JOBS` (기본 50)
- **즉시 사용**: MCP 도구로 등록 → AI가 "30분 후에 리마인더" 같은 요청 처리
- **기존 통합**: memory consolidation (현재 6시간 배치)을 스케줄러로 이관

### 4-2. Block Reply Pipeline 개선 (`backend/core/services/react_service.py` 수정)

**변경 파일**: `backend/core/services/react_service.py`, `backend/api/websocket.py`

- `BlockChunker` 클래스 (react_service.py 내부):
  - 스트리밍 토큰을 블록 단위로 버퍼링 (문단/코드블록 경계)
  - 타임아웃 기반 플러시 (300ms)
  - `ChatEvent` 에 `block_id`, `is_final_block` 메타데이터 추가
- WebSocket 엔드포인트에 블록 버퍼링 적용
- **즉시 사용**: 기존 스트리밍이 토큰 → 블록 단위로 개선됨

### 4-3. Cron MCP 도구 (`backend/core/mcp_tools/scheduler_tools.py` 신규)

**신규 파일**: `backend/core/mcp_tools/scheduler_tools.py`

- `schedule_task` 도구: add_job 래핑
- `list_scheduled` 도구: list_jobs 래핑
- `cancel_scheduled` 도구: remove_job 래핑
- **즉시 사용**: MCP 도구 등록 → AI가 자율적으로 스케줄링

---

## Phase 5: 설정 & 초기화 통합

### 5-1. Config 확장 (`backend/config.py` 수정)

모든 새 기능의 환경변수를 추가:

```python
# Orchestration
LANE_GLOBAL_CONCURRENCY = int(os.getenv("LANE_GLOBAL_CONCURRENCY", "5"))
LANE_SESSION_CONCURRENCY = int(os.getenv("LANE_SESSION_CONCURRENCY", "1"))

# Failover
AUTH_PROFILES = os.getenv("AUTH_PROFILES", "")  # JSON or comma-separated
FAILOVER_MAX_ATTEMPTS = int(os.getenv("FAILOVER_MAX_ATTEMPTS", "3"))
FAILOVER_COOLDOWN_SECONDS = int(os.getenv("FAILOVER_COOLDOWN_SECONDS", "3600"))

# Compaction
COMPACTION_STRATEGY = os.getenv("COMPACTION_STRATEGY", "summarize")
COMPACTION_PRESERVE_TURNS = int(os.getenv("COMPACTION_PRESERVE_TURNS", "5"))

# Tool Result
TOOL_RESULT_MAX_CHARS = int(os.getenv("TOOL_RESULT_MAX_CHARS", "100000"))

# Sub-Agent
SUBAGENT_ENABLED = os.getenv("SUBAGENT_ENABLED", "true").lower() == "true"
MAX_SUBAGENT_DEPTH = int(os.getenv("MAX_SUBAGENT_DEPTH", "3"))
SUBAGENT_TIMEOUT = int(os.getenv("SUBAGENT_TIMEOUT", "120"))

# Skill System
SKILLS_DIR = os.getenv("SKILLS_DIR", "data/skills")
SKILLS_ENABLED = os.getenv("SKILLS_ENABLED", "true").lower() == "true"

# Scheduler
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
SCHEDULER_MAX_JOBS = int(os.getenv("SCHEDULER_MAX_JOBS", "50"))
```

### 5-2. App Lifespan 통합 (`backend/app.py` 수정)

lifespan 함수에 추가:

```python
# startup
lane_manager = LaneManager()
subagent_registry = SubAgentRegistry()
agent_message_bus = AgentMessageBus()
scheduler = AgentScheduler()
skill_loader = SkillLoader()

if config.SCHEDULER_ENABLED:
    await scheduler.start()

# shutdown
if config.SCHEDULER_ENABLED:
    await scheduler.stop()
```

### 5-3. MCP 도구 등록 통합

기존 MCP 도구 등록 패턴에 따라 새 도구 등록:
- `agent_tools.py` → spawn_agent, list_agents, get_agent_result
- `scheduler_tools.py` → schedule_task, list_scheduled, cancel_scheduled

---

## 파일 변경 요약

### 수정 파일 (기존 코드에 통합)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/core/errors.py` | FailoverReason enum, FailoverError 클래스 추가 |
| `backend/llm/router.py` | FailoverLLMClient 래핑, AuthProfile 통합 |
| `backend/llm/base.py` | generate_stream failover 에러 전파 개선 |
| `backend/core/services/react_service.py` | Lane 큐잉, Compaction, Tool Guard, 블록 스트리밍 |
| `backend/core/services/tool_service.py` | ToolResultGuard 적용 |
| `backend/core/services/context_service.py` | Skill 프롬프트 섹션 주입 |
| `backend/config.py` | ORCHESTRATION_* 환경변수 추가 |
| `backend/app.py` | lifespan에 오케스트레이션 컴포넌트 초기화 |

### 신규 파일
| 파일 | 역할 |
|------|------|
| `backend/llm/auth_profiles.py` | Auth Profile 관리 |
| `backend/core/orchestration/__init__.py` | 오케스트레이션 패키지 |
| `backend/core/orchestration/lane_manager.py` | Lane 기반 동시성 제어 |
| `backend/core/orchestration/compaction.py` | Context 자동 압축 |
| `backend/core/orchestration/tool_result_guard.py` | 도구 결과 크기 제한 |
| `backend/core/orchestration/subagent_registry.py` | Sub-Agent 레지스트리 |
| `backend/core/orchestration/agent_messaging.py` | Agent-to-Agent 메시징 |
| `backend/core/orchestration/skill_system.py` | Skill 레이지 로딩 |
| `backend/core/orchestration/scheduler.py` | 크론/스케줄링 |
| `backend/core/mcp_tools/agent_tools.py` | spawn_agent 등 MCP 도구 |
| `backend/core/mcp_tools/scheduler_tools.py` | 스케줄링 MCP 도구 |
| `data/skills/research/SKILL.md` | 리서치 스킬 정의 |
| `data/skills/home-assistant/SKILL.md` | HASS 스킬 정의 |
| `data/skills/code-review/SKILL.md` | 코드 리뷰 스킬 정의 |

### 테스트 파일
| 파일 | 커버리지 대상 |
|------|--------------|
| `tests/core/orchestration/test_lane_manager.py` | Lane 큐잉 |
| `tests/core/orchestration/test_compaction.py` | Context 압축 |
| `tests/core/orchestration/test_tool_result_guard.py` | 결과 제한 |
| `tests/core/orchestration/test_subagent_registry.py` | Sub-Agent 관리 |
| `tests/core/orchestration/test_agent_messaging.py` | A2A 메시징 |
| `tests/core/orchestration/test_skill_system.py` | Skill 로딩 |
| `tests/core/orchestration/test_scheduler.py` | 스케줄링 |
| `tests/llm/test_auth_profiles.py` | Auth Profile |
| `tests/llm/test_failover.py` | Failover 래퍼 |
| `tests/mcp_tools/test_agent_tools.py` | Agent MCP 도구 |
| `tests/mcp_tools/test_scheduler_tools.py` | Scheduler MCP 도구 |

---

## 구현 순서 (의존성 기반 Wave)

### Wave 1 — 독립 인프라 (병렬 가능)
- [ ] 1-1. FailoverReason + FailoverError (errors.py)
- [ ] 2-1. LaneManager
- [ ] 2-3. ToolResultGuard
- [ ] 5-1. Config 확장

### Wave 2 — Wave 1 의존 (병렬 가능)
- [ ] 1-2. AuthProfileManager (→ FailoverReason 사용)
- [ ] 2-2. CompactionStrategy (→ Config 사용)
- [ ] 3-1. SubAgentRegistry
- [ ] 3-4. AgentMessageBus

### Wave 3 — 기존 코드 통합 (순차)
- [ ] 1-3. FailoverLLMClient (→ AuthProfile + FailoverError)
- [ ] 2-4. ReActService 통합 (→ Lane + Compaction + ToolGuard)
- [ ] ToolExecutionService 통합 (→ ToolGuard)

### Wave 4 — 자율 에이전트 (Wave 3 의존)
- [ ] 3-2. spawn_agent MCP 도구 (→ SubAgentRegistry + ReActService)
- [ ] 3-3. Skill System (→ ContextService)
- [ ] 4-1. AgentScheduler
- [ ] 4-3. Scheduler MCP 도구

### Wave 5 — 마무리 통합
- [ ] 5-2. app.py lifespan 통합
- [ ] 5-3. MCP 도구 등록
- [ ] 4-2. Block Reply Pipeline
- [ ] 초기 스킬 파일 작성 (research, home-assistant, code-review)

---

## 리스크 & 완화

| 리스크 | 영향 | 완화 |
|--------|------|------|
| Lane 락 데드락 | 에이전트 행 | 타임아웃 + 강제 릴리스 (60s) |
| Compaction 품질 | 컨텍스트 손실 | 최근 5턴 보존 + 요약 검증 |
| Sub-Agent 무한 재귀 | 리소스 고갈 | MAX_DEPTH=3, 타임아웃 120s |
| Scheduler 메모리 누수 | OOM | MAX_JOBS=50, 완료 작업 1h 후 정리 |
| 기존 테스트 깨짐 | 회귀 | Wave별 `pytest` 전체 실행 확인 |

## 의존성 추가

```
croniter>=1.0.0  # cron 표현식 파싱 (scheduler용)
```
