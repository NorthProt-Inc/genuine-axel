# axnmihn (Axel)

> **"Not just an Assistant, but a Co-Founder."**
> An autonomous AI agent system built for high-context interaction, memory persistence, and hardware control.

**Environment:** Ubuntu 24.04 + Systemd

---

## Architecture Overview

```
+-----------------------------------------------------------------------------+
|                              axnmihn System                                 |
+-----------------------------------------------------------------------------+
|                                                                             |
|   +-------------+     +-------------+     +-------------+                   |
|   |   Client    |---->|  FastAPI    |---->|  LLM Client |                   |
|   |  (API/Web)  |     |  Backend    |     | (Gemini 3)  |                   |
|   +-------------+     +------+------+     +------+------+                   |
|                              |                   |                          |
|                              v                   v                          |
|   +---------------------------------------------------------------------+   |
|   |                      ChatHandler Pipeline                           |   |
|   |  +---------+    +---------+    +---------+    +---------+          |   |
|   |  | Context |--->|   MCP   |--->|   LLM   |--->|Response |          |   |
|   |  |Optimizer|    | Tools   |    |  Stream |    |   SSE   |          |   |
|   |  +---------+    +---------+    +---------+    +---------+          |   |
|   +---------------------------------------------------------------------+   |
|                              |                                              |
|          +-------------------+-------------------+                          |
|          v                   v                   v                          |
|   +-------------+     +-------------+     +-------------+                   |
|   |   Memory    |     |  Research   |     |    HASS     |                   |
|   |   System    |     |   Server    |     |  Control    |                   |
|   | (3-Layer)   |     | (Playwright)|     |  (IoT)      |                   |
|   +-------------+     +-------------+     +-------------+                   |
|                                                                             |
|   +---------------------------------------------------------------------+   |
|   |                        MCP Server Ecosystem                         |   |
|   |  +----------+  +----------+  +----------+  +----------+             |   |
|   |  |  Main    |  | Research |  |  Memory  |  |  Opus    |             |   |
|   |  |  MCP     |  |   MCP    |  |   MCP    |  |  Bridge  |             |   |
|   |  +----------+  +----------+  +----------+  +----------+             |   |
|   +---------------------------------------------------------------------+   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## Core Components


### 2. Memory System (`backend/memory/`)

3-계층 메모리 아키텍처로 단기/세션/장기 기억을 통합 관리.

| Layer | Storage | Purpose | Token Budget |
|-------|---------|---------|--------------|
| **Working Memory** | JSON | 현재 대화 컨텍스트 | 150,000 tokens |
| **Session Archive** | SQLite | 세션 요약 및 메타데이터 | Permanent |
| **Long-term Memory** | ChromaDB | 벡터 검색 기반 장기 기억 | 120,000 tokens | 

**Key Modules:**
- `permanent.py` - ChromaDB 통합 장기 메모리
- `recent.py` - 세션 아카이브 및 요약
- `graph_rag.py` - Knowledge Graph 기반 관계형 기억
- `unified.py` - 통합 인터페이스
- `memgpt.py` - MemGPT 스타일 self-editing memory
- `current.py` - 워킹 메모리 관리
- `temporal.py` - 시간 기반 인덱싱

### 3. Identity & Persona (`backend/core/identity/`)

AI 페르소나 및 정체성 관리 시스템.

- `ai_brain.py` - 동적 페르소나 로드 및 진화
- 일일 페르소나 업데이트 (`scripts/evolve_persona_24h.py`)

### 4. MCP Server Ecosystem

4개의 독립 MCP 서버가 각자의 도메인을 담당.

#### Main MCP Server (`backend/core/mcp_server.py`)
- 시스템 관찰 도구 (로그 분석, 코드베이스 검색)
- Home Assistant 기기 제어
- 메모리 접근 및 저장

#### Modular MCP Tools (`backend/core/mcp_tools/`)
모듈화된 도구 시스템:

| Module | Description |
|--------|-------------|
| `schemas.py` | 도구 스키마 정의 및 검증 |
| `file_tools.py` | 파일 읽기/쓰기/검색 |
| `hass_tools.py` | Home Assistant 기기 제어 |
| `memory_tools.py` | 메모리 저장/검색/관리 |
| `research_tools.py` | 웹 검색/페이지 분석 |
| `system_tools.py` | 시스템 모니터링/로그 분석 |
| `opus_tools.py` | Claude Opus 위임 |

**Tool Registry Pattern:**
```python
from backend.core.mcp_tools import register_tool

@register_tool("my_tool", category="custom")
async def my_tool(arguments: dict) -> Sequence[TextContent]:
    ...
```

#### Research MCP Server (`backend/protocols/mcp/research_server.py`)
- **Playwright** 기반 헤드리스 브라우저
- DuckDuckGo 검색 + 페이지 크롤링
- Tavily API 통합 (선택적)
- Google Deep Research 에이전트

#### Memory MCP Server (`backend/protocols/mcp/memory_server.py`)
- `retrieve_context` - 관련 메모리 검색
- `store_memory` - 장기 메모리 저장
- GraphRAG 쿼리 인터페이스

#### Opus Bridge (`backend/protocols/mcp/opus_bridge.py`)
- Claude CLI를 통한 코딩 작업 위임
- 파일 컨텍스트 자동 수집
- Silent Intern 패턴 구현

### 5. LLM Integration (`backend/llm/`)

| Component | Description |
|-----------|-------------|
| `router.py` | 모델 설정 |
| `clients.py` | LLM 클라이언트 (Google Gemini) |

**Model Configuration:**
```python
MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL = "models/gemini-embedding-001"
```

**Resilience Patterns:**
- **Circuit Breaker** - 429 (Rate Limit), 503 (Server Error), Timeout 자동 처리
- **Adaptive Timeout** - 도구 개수와 최근 지연 시간 기반 동적 타임아웃
- **Cooldown** - 실패 시 자동 쿨다운 (300s/60s/30s)

### 6. Error Handling (`backend/core/errors.py`)

중앙화된 예외 처리 시스템:
- 커스텀 에러 클래스 정의
- 에러 모니터링 (`core/logging/error_monitor.py`)
- 요청 추적 (`core/logging/request_tracker.py`)

### 7. Home Assistant Integration (`backend/core/tools/hass_ops.py`)

IoT 기기 직접 제어:
- 조명 제어 (WiZ RGB) - 색상, 밝기, on/off
- 팬/공기청정기 제어
- 센서 읽기 (배터리, 날씨, 프린터 상태)

---

## Tech Stack

| Category | Technology |
|----------|------------|
| **Runtime** | Python 3.12, FastAPI, Uvicorn |
| **LLM** | Google Gemini 3 Flash |
| **Embedding** | Gemini Embedding 001 |
| **Memory** | ChromaDB (Vector), SQLite (Session) |
| **MCP Protocol** | mcp>=1.0.0, sse-starlette>=2.0.0 |
| **Search** | Playwright, DuckDuckGo, Tavily API |
| **IoT** | Home Assistant REST API |
| **Audio** | Deepgram Nova-3 (STT), Local LLM TTS |
| **Infrastructure** | Systemd, Pop!_OS |

---

## Directory Structure

```
axnmihn/
+-- backend/                    # Python Backend (FastAPI)
|   +-- api/                    # REST API Routers
|   |   +-- openai.py          # OpenAI-compatible endpoints
|   |   +-- audio.py           # TTS/STT routing
|   |   +-- memory.py          # Memory API
|   |   +-- media.py           # Media handling
|   |   +-- mcp.py             # MCP endpoints
|   |   +-- chat.py            # Chat routing
|   |   +-- status.py          # Health checks
|   |   +-- deps.py            # Dependencies
|   |   +-- utils.py           # API utilities
|   +-- core/                   # Core Logic
|   |   +-- chat_handler.py    # Main chat pipeline
|   |   +-- mcp_server.py      # Main MCP server
|   |   +-- mcp_client.py      # MCP client
|   |   +-- context_optimizer.py # Context management
|   |   +-- errors.py          # Custom exceptions
|   |   +-- research_artifacts.py # Research output management
|   |   +-- identity/          # Persona management
|   |   |   +-- ai_brain.py    # Dynamic persona
|   |   +-- mcp_tools/         # Modular MCP tools
|   |   |   +-- __init__.py    # Tool registry
|   |   |   +-- schemas.py     # Tool schemas
|   |   |   +-- file_tools.py  # File operations
|   |   |   +-- hass_tools.py  # Home Assistant
|   |   |   +-- memory_tools.py # Memory access
|   |   |   +-- research_tools.py # Web research
|   |   |   +-- system_tools.py # System monitoring
|   |   |   +-- opus_tools.py  # Opus delegation
|   |   +-- tools/             # Tool implementations
|   |   |   +-- hass_ops.py    # Home Assistant ops
|   |   |   +-- system_observer.py # Self-debugging
|   |   |   +-- opus_executor.py # Opus CLI bridge
|   |   |   +-- opus_delegate.py # Opus delegation logic
|   |   |   +-- opus_types.py  # Opus type definitions
|   |   +-- logging/           # Logging infrastructure
|   |   |   +-- logging.py     # Main logger
|   |   |   +-- error_monitor.py # Error tracking
|   |   |   +-- request_tracker.py # Request tracking
|   |   +-- utils/             # Wrappers & helpers
|   |       +-- async_utils.py
|   |       +-- cache.py       # Caching utilities
|   |       +-- circuit_breaker.py # Circuit breaker pattern
|   |       +-- file_utils.py
|   |       +-- gemini_wrapper.py
|   |       +-- http_pool.py
|   |       +-- rate_limiter.py
|   |       +-- retry.py
|   |       +-- task_tracker.py # Background task tracking
|   |       +-- text_utils.py  # Text processing
|   |       +-- timeouts.py
|   |       +-- timezone.py
|   +-- llm/                    # LLM Provider Clients
|   |   +-- clients.py         # Gemini client
|   |   +-- router.py          # Model config
|   +-- memory/                 # 3-Layer Memory System
|   |   +-- permanent.py       # Long-term (ChromaDB)
|   |   +-- recent.py          # Session archive
|   |   +-- unified.py         # Unified interface
|   |   +-- graph_rag.py       # Knowledge Graph
|   |   +-- memgpt.py          # Self-editing memory
|   |   +-- current.py         # Working memory
|   |   +-- temporal.py        # Temporal indexing
|   +-- protocols/              # Communication Protocols
|   |   +-- mcp/               # Model Context Protocol
|   |       +-- server.py      # Base MCP server
|   |       +-- research_server.py # Deep research
|   |       +-- memory_server.py # Memory access
|   |       +-- async_research.py # Async research
|   |       +-- opus_bridge.py # Opus delegation
|   |       +-- google_research.py # Google research
|   +-- media/                  # Audio processing
|   +-- wake/                   # Wakeword detection
|   +-- app.py                 # FastAPI entry point
|   +-- config.py              # Centralized configuration
+-- scripts/                    # Automation & maintenance
|   +-- memory_gc.py           # Memory garbage collection
|   +-- night_ops.py           # Night batch operations
|   +-- regenerate_persona.py  # Persona regeneration
|   +-- evolve_persona_24h.py  # Daily persona evolution
+-- data/                       # Runtime data
|   +-- working_memory.json    # Session memory
|   +-- chroma_db/             # Vector DB
|   +-- sqlite/                # Structured memory
|   +-- knowledge_graph.json   # Knowledge graph
|   +-- dynamic_persona.json   # Dynamic persona
+-- storage/                    # Research artifacts & reports
|   +-- research/              # Research outputs
|   +-- cron/                  # Cron job results
+-- logs/                       # Application logs
```

---

## Installation

### Prerequisites
- Python 3.12+
- `ffmpeg` (audio processing)
- Home Assistant instance (optional, for IoT)

### Setup

```bash
# 1. Clone repository
git clone https://github.com/NorthProt/axnmihn.git
cd axnmihn

# 2. Environment setup
cp .env.example .env
# Configure API keys: GEMINI_API_KEY, etc.

# 3. Install dependencies
pip install -r backend/requirements.txt

# 4. Run backend
python -m backend.app

# 5. (Optional) Run MCP servers as systemd services
sudo cp scripts/*.service /etc/systemd/system/
sudo systemctl enable --now axnmihn-mcp axnmihn-research
```

### Key Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `LLM_MODEL` | Model name (default: gemini-3-flash-preview) |
| `SEARCH_PROVIDER` | Search provider (tavily/duckduckgo) |
| `HASS_URL` | Home Assistant URL |
| `HASS_TOKEN` | Home Assistant long-lived token |

### Systemd Services

| Service | Description |
|---------|-------------|
| `axnmihn-mcp.service` | Main MCP server |
| `axnmihn-research.service` | Research MCP server |
| `axnmihn-wake.service` | Wakeword detection |

---

## Key Design Decisions

### Single Model Architecture
복잡한 멀티-모델 라우팅 대신 단일 Gemini 모델로 단순화. 메모리 최적화는 MCP `retrieve_context` 도구가 담당.

### Circuit Breaker Pattern
LLM API 호출 시 429/503/Timeout 에러 자동 감지 및 쿨다운. 연쇄 실패 방지.

### Adaptive Timeout
도구 개수와 최근 10개 요청의 지연 시간을 기반으로 동적 타임아웃 계산.

### End Resource Starvation
현대 LLM의 큰 컨텍스트 윈도우(100k-2M tokens)를 활용하도록 tier 설정 대폭 확대.

### Compression-Free Recent Turns
최근 N턴은 압축 없이 전체 보존.

### Async Deep Research
Google Deep Research를 백그라운드에서 비동기 실행.

### Modular MCP Architecture
MCP 도구를 `@register_tool` 데코레이터 기반 레지스트리로 구성. 도구 추가 시 자동 등록되며, 카테고리별 분리로 유지보수성 향상.

