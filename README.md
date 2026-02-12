# Axnmihn

<details open>
<summary><strong>English</strong></summary>

**AI Assistant Backend System**

A modern FastAPI-based AI backend service featuring a 6-layer memory system, MCP ecosystem, and multi-LLM provider integration.

**Tech Stack:** Python 3.12 / FastAPI / PostgreSQL 17 + pgvector / Redis / C++17 Native Module

**License:** MIT

---

## Key Features

- **6-Layer Memory System** — M0(Event Buffer) → M1(Working Memory) → M3(Session Archive) → M4(Long-Term) → M5.1-5.3(MemGPT/GraphRAG/MetaMemory)
- **Multi-LLM Support** — Gemini, Claude, Circuit Breaker & Fallback
- **MCP Ecosystem** — Memory, File, System, Research, Home Assistant integration
- **SIMD Optimization** — C++17 native module (memory decay, vector ops, graph traversal)
- **Voice Pipeline** — Deepgram Nova-3 (STT) + Qwen3-TTS / OpenAI TTS
- **OpenAI-Compatible API** — `/v1/chat/completions` endpoint
- **Adaptive Persona** — Channel-specific AI personality adjustment
- **Context Optimization** — Token-budget-based smart context assembly
- **Channel Adapters** — Discord/Telegram bot integration (streaming message editing, inline commands)

---

## Architecture

### System Overview

```mermaid
graph TB
    subgraph Clients["🖥️ Clients"]
        CLI["axel-chat / CLI"]
        WebUI["Open WebUI"]
        Discord["Discord Bot"]
        Telegram["Telegram Bot"]
    end

    subgraph Backend["⚙️ AXNMIHN Backend (FastAPI :8000)"]
        subgraph Ingress["Ingress Layer"]
            API["API Routers<br/>(REST/SSE/WebSocket)"]
            ChannelMgr["Channel Manager<br/>(Adapter Lifecycle)"]
        end

        subgraph Core["Core Services"]
            ChatHandler["ChatHandler<br/>(Orchestrator)"]
            Context["ContextService<br/>(Budget-aware)"]
            ReAct["ReActLoopService<br/>(≤15 iterations)"]
            Search["SearchService<br/>(Tavily)"]
            ToolExec["ToolExecutionService"]
            MemPersist["MemoryPersistenceService"]
            Emotion["EmotionService"]
        end

        subgraph LLM[]
            Claude["Anthropic<br/>Claude Sonnet 4.5<br/>"]
            Gemini["Google<br/>Gemini 3 Flash<br/>"]
        end

        subgraph Memory["6-Layer Memory System"]
            M0["M0: Event Buffer"]
            M1["M1: Working Memory<br/>(20 turns, JSON)"]
            M3["M3: Session Archive<br/>(PostgreSQL/SQLite)"]
            M4["M4: Long-Term<br/>(ChromaDB/pgvector)"]
            M51["M5.1: MemGPT<br/>(budget selection)"]
            M52["M5.2: GraphRAG<br/>(knowledge graph)"]
            M53["M5.3: MetaMemory<br/>(access patterns)"]
        end

        subgraph MCP["MCP Server (:8555)"]
            MCPTools["Tool Registry<br/>(32 tools)"]
        end

        subgraph Media["Media Pipeline"]
            TTS["TTS<br/>(Qwen3 / OpenAI)"]
            STT["STT<br/>(Deepgram Nova-3)"]
        end
    end

    subgraph External["🔌 External Services"]
        HASS["Home Assistant<br/>(WiZ/IoT)"]
        Playwright["Playwright<br/>(Browser)"]
        TavilyAPI["Tavily API"]
        DDGAPI["DuckDuckGo API"]
        PG["PostgreSQL"]
        Redis["Redis"]
    end

    CLI & WebUI -->|"OpenAI-compat API"| API
    Discord & Telegram -->|"Channel Adapter Protocol"| ChannelMgr
    ChannelMgr --> ChatHandler
    API --> ChatHandler

    ChatHandler --> Context
    ChatHandler --> ReAct
    ChatHandler --> Search
    ChatHandler --> ToolExec
    ChatHandler --> MemPersist
    ChatHandler --> Emotion

    Context --> Memory
    ReAct --> LLM
    ToolExec --> MCP
    MemPersist --> Memory
    ChatHandler --> Media

    MCPTools --> HASS
    MCPTools --> Playwright
    Search --> TavilyAPI
    Search --> DDGAPI

    M3 & M4 & M52 --> PG
    M0 --> M1 --> M3 -->|"consolidation (6h)"| M4
    M1 -->|"auto-promote"| M4
    M4 --> M51 & M52 & M53
    M52 -->|"feedback"| M4
    M53 -->|"hot boost"| M4
```

### Request Flow

```mermaid
sequenceDiagram
    participant C as Client / Channel Bot
    participant A as API / ChannelManager
    participant CH as ChatHandler
    participant CS as ContextService
    participant MM as MemoryManager
    participant RL as ReActLoop
    participant LLM as LLM Router
    participant MCP as MCP Tools

    C->>A: Message (REST/WebSocket/Bot)
    A->>CH: ChatRequest
    CH->>CS: build_smart_context()
    CS->>MM: parallel fetch (M0+M1+M3+M4+M5)
    MM-->>CS: budgeted context
    CS-->>CH: assembled context

    loop ReAct Loop (≤15)
        CH->>RL: reason + act
        RL->>LLM: generate (Claude/Gemini)
        LLM-->>RL: response + tool_calls
        opt Tool Calls
            RL->>MCP: execute tools
            MCP-->>RL: tool results
        end
    end

    CH->>MM: persist (working + session + long-term)
    MM->>LLM: evaluate importance (facts/insights)
    LLM-->>MM: importance scores
    opt importance ≥ 0.6
        MM->>MM: auto-promote to M4
    end
    CH-->>A: streaming response (SSE)
    A-->>C: chunked response
```

### Core Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Server | FastAPI + Uvicorn | Async HTTP/SSE, OpenAI-compatible |
| LLM Router | Gemini 3 Flash + Claude Sonnet 4.5 | Multi-provider, circuit breaker |
| Memory System | 6-layer architecture | Persistent context across sessions |
| MCP Server | Model Context Protocol (SSE) | Tool ecosystem |
| Native Module | C++17 + pybind11 | SIMD-optimized graph/decay ops |
| Audio | Deepgram Nova-3 (STT) + Qwen3-TTS / OpenAI (TTS) | Voice pipeline |
| Home Assistant | REST API | IoT device control |
| Channel Adapters | discord.py + python-telegram-bot | Discord/Telegram bot integration |
| Research | Playwright + Tavily + DuckDuckGo | Web research |

---

## 6-Layer Memory System

The memory system consists of 6 functional layers (M0, M1, M3, M4, M5.1-5.3) orchestrated by `MemoryManager` (`backend/memory/unified/`).

```mermaid
graph TB
    Input["User Message"] --> M0

    subgraph Memory["6-Layer Memory System"]
        M0["M0: Event Buffer<br/><i>real-time event stream</i>"]
        M1["M1: Working Memory<br/><i>in-memory deque (20 turns)</i><br/><i>JSON persistence</i>"]
        M3["M3: Session Archive<br/><i>SQLite / PostgreSQL</i><br/><i>sessions, messages, logs</i>"]
        M4["M4: Long-Term Memory<br/><i>ChromaDB / pgvector</i><br/><i>3072-dim Gemini embeddings</i><br/><i>adaptive decay, dedup</i>"]

        M51["M5.1: MemGPT<br/><i>budget-aware selection</i><br/><i>token-budgeted assembly</i>"]
        M52["M5.2: GraphRAG<br/><i>entity-relation graph</i><br/><i>spaCy NER + LLM extraction</i><br/><i>BFS traversal (C++ for 100+)</i>"]
        M53["M5.3: MetaMemory<br/><i>access pattern tracking</i><br/><i>hot memory detection</i>"]
    end

    M0 --> M1
    M1 -->|"immediate persist"| M3
    M1 -->|"auto-promote<br/>(importance ≥ 0.6)"| M4
    M3 -->|"consolidation (6h)<br/>+ reassessment"| M4
    M4 --> M51
    M4 --> M52
    M4 --> M53
    M52 -->|"connection_count<br/>feedback"| M4
    M53 -->|"hot boost"| M4

    Context["ContextService<br/>build_smart_context()"] -.->|"parallel fetch"| M0 & M1 & M3 & M4 & M51 & M52 & M53
```

### Layer Details

| Layer | File | Storage | Purpose |
|-------|------|---------|---------|
| M0 Event Buffer | `memory/event_buffer.py` | In-memory | Real-time event streaming |
| M1 Working Memory | `memory/current.py` | `data/working_memory.json` | Current conversation buffer (20 turns) |
| M3 Session Archive | `memory/recent/` | `data/sqlite/sqlite_memory.db` | Session summaries, message history |
| M4 Long-Term Memory | `memory/permanent/` | `data/chroma_db/` | Semantic vector search, importance decay |
| M5.1 MemGPT | `memory/memgpt.py` | In-memory | Token-budget selection, topic diversity |
| M5.2 GraphRAG | `memory/graph_rag/` | `data/knowledge_graph.json` | Entity/relation graph, BFS traversal |
| M5.3 MetaMemory | `memory/meta_memory.py` | SQLite | Access frequency, channel diversity |

### Memory Decay

Memories decay over time using an adaptive forgetting curve:

```
decayed_importance = importance * decay_factor

decay_factor = f(
    time_elapsed,           # exponential time decay
    base_rate=0.001,        # configurable via MEMORY_BASE_DECAY_RATE
    access_count,           # repeated access slows decay
    connection_count,       # graph-connected memories resist decay
    memory_type_modifier,   # facts decay slower than conversations
    circadian_stability     # peak-hour boost via apply_circadian_stability()
)

deletion threshold: 0.03   (MEMORY_DECAY_DELETE_THRESHOLD)
min retention: 0.3         (MEMORY_MIN_RETENTION)
similarity dedup: 0.90     (MEMORY_SIMILARITY_THRESHOLD)
```

### Retrieval Scoring

Long-term memory retrieval applies a multi-factor scoring pipeline:

```
effective_score = base_relevance * decay_factor * importance_weight

importance_weight = 0.5 + 0.5 * clamp(importance, 0, 1)   # range: [0.5, 1.0]
```

- **M5 Hot Memory Boost**: Memories flagged as "hot" by MetaMemory receive a score bonus (+0.1)
- **GraphRAG LLM Relevance**: Async queries use LLM-evaluated relevance instead of simple entity-count heuristics

### Context Assembly

`await MemoryManager.build_smart_context()` assembles context from all layers via async parallel fetch (sync wrapper: `build_smart_context_sync()`):

| Section | Default Budget (chars) | Config Key |
|---------|----------------------|------------|
| System Prompt | 20,000 | `BUDGET_SYSTEM_PROMPT` |
| Temporal Context | 5,000 | `BUDGET_TEMPORAL` |
| Working Memory | 80,000 | `BUDGET_WORKING_MEMORY` |
| Long-Term Memory | 30,000 | `BUDGET_LONG_TERM` |
| GraphRAG | 12,000 | `BUDGET_GRAPHRAG` |
| Session Archive | 8,000 | `BUDGET_SESSION_ARCHIVE` |

`ContextService` also fetches M0 (Event Buffer) and M5 (Hot Memories) sections for complete 6-layer coverage.

### Session Management

- **Auto session timeout**: Sessions automatically end after 30 minutes of inactivity
- **Shutdown LLM summary**: On app shutdown, attempts LLM-based session summary (10s timeout, fallback on failure)
- **LLM importance evaluation**: Facts and insights are scored by LLM at session end (fallback: 0.5)
- **Auto-promotion (M2→M3)**: Sessions with LLM importance ≥ 0.6 are automatically promoted to long-term as `conversation` type
- **Memory promotion criteria**: importance ≥ 0.55, or (repetitions ≥ 2 AND importance ≥ 0.35)

### Auto Consolidation

The app runs `consolidate_memories()` automatically every 6 hours. Additionally, `scripts/memory_gc.py` can be registered as a cron job for hash/semantic deduplication.

- **User behavior metrics**: Consolidator collects real user behavior metrics via `collect_behavior_metrics()` for adaptive decay
- **Importance reassessment**: Old memories (>168h) with high access counts are periodically re-evaluated by LLM (batch size: 50)
- **GraphRAG → M3 feedback**: Entity extraction updates `connection_count` on related long-term memories

### PostgreSQL Backend (Optional)

When `DATABASE_URL` is set, the system uses PostgreSQL + pgvector instead of SQLite/ChromaDB:

```
backend/memory/pg/
  connection.py            # PgConnectionManager (connection pool)
  memory_repository.py     # PgMemoryRepository (replaces ChromaDB)
  graph_repository.py      # PgGraphRepository (replaces JSON graph)
  session_repository.py    # PgSessionRepository (replaces SQLite)
  meta_repository.py       # PgMetaMemoryRepository
  interaction_logger.py    # PgInteractionLogger
```

Requires: `pgvector/pgvector:pg17` (see `docker-compose.yml`)

---

## API Endpoints

All endpoints require `Authorization: Bearer <token>` or `X-API-Key` header authentication (except health/status endpoints).

### Health & Status

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Full health check (memory, LLM, modules) |
| `/health/quick` | GET | Minimal liveness check |
| `/metrics` | GET | Prometheus metrics (text format) |
| `/auth/status` | GET | Auth status |
| `/llm/providers` | GET | Available LLM providers |
| `/models` | GET | Available models |

### Chat (OpenAI-Compatible)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/chat/completions` | POST | Chat completion (streaming/non-streaming) |
| `/v1/models` | GET | Available models list |

### WebSocket

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `/ws` | WebSocket | Real-time chat (auth, rate limiting 30msg/min, heartbeat) |

### Memory

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/memory/consolidate` | POST | Trigger decay + persona evolution |
| `/memory/stats` | GET | Memory layer statistics |
| `/memory/search?query=&limit=` | GET | Semantic memory search |
| `/memory/sessions` | GET | Recent session summaries |
| `/memory/session/{session_id}` | GET | Session detail |
| `/memory/interaction-logs` | GET | Interaction logs |
| `/memory/interaction-stats` | GET | Interaction statistics |
| `/session/end` | POST | End current session |

### Audio

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/audio/transcriptions` | POST | STT (Deepgram Nova-3) |
| `/v1/audio/speech` | POST | TTS synthesis |
| `/v1/audio/voices` | GET | Available TTS voices |
| `/transcribe` | POST | Audio file transcription |
| `/upload` | POST | File upload |

### MCP

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp/status` | GET | MCP server status |
| `/mcp/manifest` | GET | MCP tool manifest |
| `/mcp/execute` | POST | Execute MCP tool |

### Code Browsing

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/code/summary` | GET | Codebase summary |
| `/code/files` | GET | Code file listing |

---

## MCP Ecosystem

32 tools served via SSE transport. Categories:

- **System (9):** run_command, search_codebase, search_codebase_regex, read_system_logs, list_available_logs, analyze_log_errors, check_task_status, tool_metrics, system_status
- **Memory (6):** query_axel_memory, add_memory, store_memory, retrieve_context, get_recent_logs, memory_stats
- **File (3):** read_file, list_directory, get_source_code
- **Research (6):** web_search, visit_webpage, deep_research, tavily_search, read_artifact, list_artifacts
- **Home Assistant (6):** hass_control_light, hass_control_device, hass_read_sensor, hass_get_state, hass_list_entities, hass_execute_scene
- **Delegation (2):** delegate_to_opus, google_deep_research

Tool visibility is configurable via `MCP_DISABLED_TOOLS` and `MCP_DISABLED_CATEGORIES` env vars.

---

## Native C++ Module

Performance-critical operations via C++17 + pybind11 + SIMD (AVX2/NEON):

```
backend/native/src/
  axnmihn_native.cpp      # pybind11 bindings
  decay.cpp/.hpp           # Memory decay (SIMD batch)
  vector_ops.cpp/.hpp      # Cosine similarity, duplicate detection
  string_ops.cpp/.hpp      # Levenshtein distance
  graph_ops.cpp/.hpp       # BFS traversal
  text_ops.cpp/.hpp        # Text processing
```

All call sites fall back to pure Python if the module is not installed.

```bash
cd backend/native && pip install .
# Requires: CMake 3.18+, C++17 compiler, pybind11
```

---

## Configuration

### Environment Variables (`.env`)

```bash
# API Keys
GEMINI_API_KEY=your-gemini-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
OPENAI_API_KEY=your-openai-api-key
TAVILY_API_KEY=your-tavily-api-key
DEEPGRAM_API_KEY=your-deepgram-api-key

# Home Assistant
HASS_URL=http://homeassistant.local:8123
HASS_TOKEN=your-hass-long-lived-token

# Server
AXNMIHN_API_KEY=your-api-key
HOST=0.0.0.0
PORT=8000
DEBUG=false
TZ=America/Vancouver

# Models
CHAT_PROVIDER=google
GEMINI_MODEL=gemini-3-flash-preview
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
ANTHROPIC_THINKING_BUDGET=10000
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072

# Memory budgets (chars)
BUDGET_SYSTEM_PROMPT=20000
BUDGET_TEMPORAL=5000
BUDGET_WORKING_MEMORY=80000
BUDGET_LONG_TERM=30000
BUDGET_GRAPHRAG=12000
BUDGET_SESSION_ARCHIVE=8000

# Memory decay
MEMORY_BASE_DECAY_RATE=0.001
MEMORY_MIN_RETENTION=0.3
MEMORY_DECAY_DELETE_THRESHOLD=0.03
MEMORY_SIMILARITY_THRESHOLD=0.90
MEMORY_MIN_IMPORTANCE=0.55

# Context
CONTEXT_WORKING_TURNS=20
CONTEXT_FULL_TURNS=6
CONTEXT_MAX_CHARS=500000

# Providers
DEFAULT_LLM_PROVIDER=gemini
SEARCH_PROVIDER=tavily

# PostgreSQL
DATABASE_URL=postgresql://axel:password@localhost:5432/axel
PG_POOL_MIN=2
PG_POOL_MAX=10

# Docker Compose (docker-compose.yml에서 사용, 선택)
# POSTGRES_USER=axel
# POSTGRES_PASSWORD=change-me-in-production
# POSTGRES_DB=axel

# TTS Configuration
TTS_SERVICE_URL=http://127.0.0.1:8002
TTS_SYNTHESIS_TIMEOUT=30.0
TTS_FFMPEG_TIMEOUT=10.0
TTS_QUEUE_MAX_PENDING=3
TTS_IDLE_TIMEOUT=300

# Channel Adapters (Discord / Telegram)
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_CHANNELS=           # comma-separated channel IDs (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=             # comma-separated usernames (optional)
TELEGRAM_ALLOWED_CHATS=             # comma-separated chat IDs (optional)

# Admin
AXNMIHN_ADMIN_EMAIL=admin@example.com
```

---

## Quick Start

### Option A: Docker (Recommended)

```bash
git clone https://github.com/NorthProt-Inc/axnmihn.git
cd axnmihn

cp .env.example .env
# Edit .env with API keys

docker compose up -d

# Verify
curl http://localhost:8000/health/quick
```

This starts: backend (8000) + MCP (8555) + research (8766) + PostgreSQL (5432) + Redis (6379).

### Option B: Local Development

```bash
git clone https://github.com/NorthProt-Inc/axnmihn.git
cd axnmihn

python3.12 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example .env
# Edit .env with API keys

# (Optional) Native C++ module
cd backend/native && pip install . && cd ../..

# (Optional) Playwright for research
playwright install chromium

# (Optional) PostgreSQL + Redis
docker compose up -d postgres redis

# Run
uvicorn backend.app:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
```

---

## Deployment

### Docker Compose (Full Stack)

```bash
docker compose up -d              # Start all services
docker compose ps                 # Status
docker compose logs backend -f    # Follow backend logs
docker compose down               # Stop all
```

| Service | Port | Image/Target | Resources |
|---------|------|-------------|-----------|
| `backend` | 8000 | Dockerfile → runtime | 4G RAM, 2 CPU |
| `mcp` | 8555 | Dockerfile → runtime | 1G RAM, 1 CPU |
| `research` | 8766 | Dockerfile → research | 2G RAM, 1.5 CPU |

Infrastructure (PostgreSQL, Redis) runs as native systemd services. TTS (GPU-dependent) is commented out in docker-compose.yml. Uncomment if NVIDIA GPU is available.

### Systemd Services (Bare Metal)

| Service | Port | Purpose | Resources |
|---------|------|---------|-----------|
| `axnmihn-backend` | 8000 | FastAPI backend | 4G RAM, 200% CPU |
| `axnmihn-mcp` | 8555 | MCP server (SSE) | 1G RAM, 100% CPU |
| `axnmihn-research` | 8766 | Research MCP | 2G RAM, 150% CPU |
| `axnmihn-tts` | 8002 | TTS microservice (Qwen3-TTS) | 4G RAM, 200% CPU |
| `axnmihn-wakeword` | - | Wakeword detection | 512M RAM, 50% CPU |
| `context7-mcp` | 3002 | Context7 MCP | 1G RAM |
| `markitdown-mcp` | 3001 | Markitdown MCP | 1G RAM |

See [OPERATIONS.md](OPERATIONS.md) for detailed operations guide.

### Maintenance

| Script | Purpose |
|--------|---------|
| `scripts/memory_gc.py` | Memory garbage collection (dedup, decay, oversized removal) |
| `scripts/db_maintenance.py` | SQLite VACUUM, ANALYZE, integrity check |
| `scripts/dedup_knowledge_graph.py` | Knowledge graph deduplication |
| `scripts/regenerate_persona.py` | 7-day incremental persona update |
| `scripts/optimize_memory.py` | 4-phase memory optimization (text cleaning, role normalization) |
| `scripts/cleanup_messages.py` | LLM-powered message cleanup (parallel, checkpointed) |
| `scripts/populate_knowledge_graph.py` | Knowledge graph initial population |
| `scripts/night_ops.py` | Automated night shift research |
| `scripts/run_migrations.py` | Database schema migrations |

---

## Project Structure

```
axnmihn/
├── backend/
│   ├── app.py                    # FastAPI entry point, lifespan
│   ├── config.py                 # All configuration
│   ├── api/                      # HTTP routers (status, chat, memory, mcp, media, audio, openai)
│   ├── core/                     # Core services
│   │   ├── chat_handler.py       # Message routing
│   │   ├── context_optimizer.py  # Context size management
│   │   ├── mcp_client.py        # MCP client
│   │   ├── mcp_server.py        # MCP server setup
│   │   ├── health/              # Health monitoring
│   │   ├── identity/            # AI persona (ai_brain.py)
│   │   ├── intent/              # Intent classification
│   │   ├── logging/             # Structured logging
│   │   ├── mcp_tools/           # Tool implementations
│   │   ├── persona/             # Channel adaptation
│   │   ├── security/            # Prompt defense
│   │   ├── session/             # Session state
│   │   ├── telemetry/           # Interaction logging
│   │   └── utils/               # Cache, retry, HTTP pool, Gemini client, circuit breaker
│   ├── llm/                     # LLM providers (Gemini, Anthropic)
│   ├── media/                   # TTS manager
│   ├── memory/                  # 6-layer memory system
│   │   ├── unified/             # MemoryManager orchestrator (core, facade, context_builder, session)
│   │   ├── event_buffer.py      # M0: Event buffer
│   │   ├── current.py           # M1: Working memory
│   │   ├── recent/              # M3: Session archive (SQLite)
│   │   ├── permanent/           # M4: Long-term (ChromaDB)
│   │   ├── memgpt.py            # M5.1: Budget selection
│   │   ├── graph_rag/           # M5.2: Knowledge graph
│   │   ├── meta_memory.py       # M5.3: Access tracking
│   │   ├── temporal.py          # Time context
│   │   └── pg/                  # PostgreSQL backend (optional)
│   ├── native/                  # C++17 extension module
│   ├── channels/                # Channel adapter system
│   │   ├── protocol.py          # ChannelAdapter Protocol
│   │   ├── manager.py           # Lifecycle management
│   │   ├── message_chunker.py   # Platform message splitting
│   │   ├── bridge.py            # ChatHandler bridge
│   │   ├── discord/bot.py       # Discord adapter
│   │   ├── telegram/bot.py      # Telegram adapter
│   │   └── commands/registry.py # Inline command parser
│   ├── protocols/mcp/           # MCP protocol handlers
│   └── wake/                    # Wakeword + voice conversation
├── tests/                       # pytest suite
├── scripts/                     # Automation scripts
├── data/                        # Runtime data (SQLite, ChromaDB, JSON)
├── logs/                        # Application logs
├── storage/                     # Research artifacts, cron reports
├── Dockerfile                   # Multi-stage (runtime + research)
├── docker-compose.yml           # Full stack (app + PG + Redis)
├── .dockerignore
├── pyproject.toml               # Project metadata
└── .env                         # Environment configuration
```

---

## Documentation

- [OPERATIONS.md](OPERATIONS.md) — Operations guide (KR/EN)
- [AGENTS.md](AGENTS.md) — Custom agent definitions
- [logging.md](logging.md) — Logging system documentation
- [memory-system-analysis.md](memory-system-analysis.md) — Memory system analysis report
- [backend/native/README.md](backend/native/README.md) — C++ native module
- `.github/instructions/` — Development guidelines (TDD, security, performance, error analysis)

---

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'feat: add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

**Commit Convention:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, etc.)

**Code Style:**
- Python: `black` formatting, `ruff` linting, type hints required
- Max 400 lines per function, 800 lines per file
- Protocol-based interfaces, dataclass/pydantic data
- Prefer async def (I/O-bound operations)

---

## License

MIT License - see [LICENSE](LICENSE) for details

---

## Acknowledgments

- **FastAPI** — Modern web framework
- **ChromaDB** — Vector database
- **Anthropic & Google** — LLM APIs
- **Deepgram** — Speech recognition
- **Model Context Protocol** — Tool integration standard

---

**Made by:** NorthProt Inc.  
**Contact:** [GitHub Issues](https://github.com/NorthProt-Inc/axnmihn/issues)

</details>


---

<details>
<summary><strong>한국어</strong></summary>

**AI 어시스턴트 백엔드 시스템**

FastAPI 기반의 AI 백엔드 서비스입니다. 6계층 메모리 시스템, MCP 생태계, 멀티 LLM 프로바이더를 통합한 현대적인 아키텍처를 제공합니다.

**기술 스택:** Python 3.12 / FastAPI / PostgreSQL 17 + pgvector / Redis / C++17 네이티브 모듈

**라이선스:** MIT

---

## 주요 기능

- **6계층 메모리 시스템** — M0(이벤트 버퍼) → M1(워킹 메모리) → M3(세션 아카이브) → M4(장기 메모리) → M5.1-5.3(MemGPT/GraphRAG/MetaMemory)
- **멀티 LLM 지원** — Gemini 3 Flash, Claude Sonnet 4.5, Circuit Breaker & Fallback
- **MCP 생태계** — 메모리, 파일, 시스템, 리서치, Home Assistant 통합
- **SIMD 최적화** — C++17 네이티브 모듈 (메모리 decay, 벡터 연산, 그래프 탐색)
- **음성 파이프라인** — Deepgram Nova-3 (STT) + Qwen3-TTS / OpenAI TTS
- **OpenAI 호환 API** — `/v1/chat/completions` 엔드포인트
- **적응형 페르소나** — 채널별 AI 성격 자동 조정
- **컨텍스트 최적화** — 토큰 예산 기반 스마트 컨텍스트 조립
- **WebSocket 실시간 통신** — 인증, Rate Limiting, Heartbeat 지원 (`/ws`)
- **Prometheus 메트릭스** — `GET /metrics` 엔드포인트 (Counter, Gauge, Histogram)
- **구조화된 에러 계층** — `AxnmihnError` 기반 7계층 에러 분류 (자동 HTTP 상태 매핑)
- **Intent 분류기** — 키워드 기반 6종 인텐트 분류 (chat, search, tool_use, memory_query, command, creative)
- **컴포넌트 헬스체크** — Memory, LLM, PostgreSQL 독립 헬스체크 + latency 추적
- **채널 어댑터** — Discord/Telegram 봇 통합 (스트리밍 메시지 편집, 인라인 커맨드)

---

## 아키텍처

### 시스템 개요

```mermaid
graph TB
    subgraph Clients["🖥️ 클라이언트"]
        CLI["axel-chat / CLI"]
        WebUI["Open WebUI"]
        Discord["Discord 봇"]
        Telegram["Telegram 봇"]
    end

    subgraph Backend["⚙️ AXNMIHN 백엔드 (FastAPI :8000)"]
        subgraph Ingress["인그레스 계층"]
            API["API 라우터<br/>(REST/SSE/WebSocket)"]
            ChannelMgr["채널 매니저<br/>(어댑터 라이프사이클)"]
        end

        subgraph Core["핵심 서비스"]
            ChatHandler["ChatHandler<br/>(오케스트레이터)"]
            Context["ContextService<br/>(예산 기반)"]
            ReAct["ReActLoopService<br/>(≤15 반복)"]
            Search["SearchService<br/>(Tavily)"]
            ToolExec["ToolExecutionService"]
            MemPersist["MemoryPersistenceService"]
            Emotion["EmotionService"]
        end

        subgraph LLM["LLM 라우터 (Circuit Breaker)"]
            Claude["Anthropic<br/>Claude Sonnet 4.5<br/>(채팅)"]
            Gemini["Google<br/>Gemini 3 Flash<br/>(유틸리티)"]
        end

        subgraph Memory["6계층 메모리 시스템"]
            M0["M0: 이벤트 버퍼"]
            M1["M1: 워킹 메모리<br/>(20턴, JSON)"]
            M3["M3: 세션 아카이브<br/>(PostgreSQL/SQLite)"]
            M4["M4: 장기 메모리<br/>(ChromaDB/pgvector)"]
            M51["M5.1: MemGPT<br/>(예산 기반 선택)"]
            M52["M5.2: GraphRAG<br/>(지식 그래프)"]
            M53["M5.3: MetaMemory<br/>(접근 패턴)"]
        end

        subgraph MCP["MCP 서버 (:8555)"]
            MCPTools["도구 레지스트리<br/>(32개 도구)"]
        end

        subgraph Media["미디어 파이프라인"]
            TTS["TTS<br/>(Qwen3 / OpenAI)"]
            STT["STT<br/>(Deepgram Nova-3)"]
        end
    end

    subgraph External["🔌 외부 서비스"]
        HASS["Home Assistant<br/>(WiZ/IoT)"]
        Playwright["Playwright<br/>(브라우저)"]
        TavilyAPI["Tavily API"]
        DDGAPI["DuckDuckGo API"]
        PG["PostgreSQL"]
        Redis["Redis"]
    end

    CLI & WebUI -->|"OpenAI 호환 API"| API
    Discord & Telegram -->|"채널 어댑터 프로토콜"| ChannelMgr
    ChannelMgr --> ChatHandler
    API --> ChatHandler

    ChatHandler --> Context
    ChatHandler --> ReAct
    ChatHandler --> Search
    ChatHandler --> ToolExec
    ChatHandler --> MemPersist
    ChatHandler --> Emotion

    Context --> Memory
    ReAct --> LLM
    ToolExec --> MCP
    MemPersist --> Memory
    ChatHandler --> Media

    MCPTools --> HASS
    MCPTools --> Playwright
    Search --> TavilyAPI
    Search --> DDGAPI

    M3 & M4 & M52 --> PG
    M0 --> M1 --> M3 -->|"통합 (6시간)"| M4
    M1 -->|"자동 프로모션"| M4
    M4 --> M51 & M52 & M53
    M52 -->|"피드백"| M4
    M53 -->|"핫 부스트"| M4
```

### 요청 흐름

```mermaid
sequenceDiagram
    participant C as 클라이언트 / 채널 봇
    participant A as API / ChannelManager
    participant CH as ChatHandler
    participant CS as ContextService
    participant MM as MemoryManager
    participant RL as ReActLoop
    participant LLM as LLM 라우터
    participant MCP as MCP 도구

    C->>A: 메시지 (REST/WebSocket/봇)
    A->>CH: ChatRequest
    CH->>CS: build_smart_context()
    CS->>MM: 병렬 조회 (M0+M1+M3+M4+M5)
    MM-->>CS: 예산 기반 컨텍스트
    CS-->>CH: 조립된 컨텍스트

    loop ReAct 루프 (≤15회)
        CH->>RL: 추론 + 실행
        RL->>LLM: 생성 (Claude/Gemini)
        LLM-->>RL: 응답 + tool_calls
        opt 도구 호출
            RL->>MCP: 도구 실행
            MCP-->>RL: 도구 결과
        end
    end

    CH->>MM: 영속화 (working + session + long-term)
    MM->>LLM: 중요도 평가 (facts/insights)
    LLM-->>MM: importance 점수
    opt importance ≥ 0.6
        MM->>MM: M4로 자동 프로모션
    end
    CH-->>A: 스트리밍 응답 (SSE)
    A-->>C: 청크 응답
```

### 핵심 컴포넌트

| 컴포넌트 | 기술 | 목적 |
|----------|------|------|
| API 서버 | FastAPI + Uvicorn | Async HTTP/SSE/WebSocket, OpenAI 호환 |
| LLM 라우터 | Gemini 3 Flash + Claude Sonnet 4.5 | 멀티 프로바이더, Circuit Breaker |
| 메모리 시스템 | 6계층 아키텍처 | 세션 간 지속적인 컨텍스트 |
| MCP 서버 | Model Context Protocol (SSE) | 도구 생태계 |
| 텔레메트리 | Prometheus 메트릭스 + 에러 계층 | 관측성 + 구조화된 에러 처리 |
| 네이티브 모듈 | C++17 + pybind11 | SIMD 최적화 (그래프/decay) |
| 오디오 | Deepgram Nova-3 (STT) + Qwen3-TTS / OpenAI (TTS) | 음성 파이프라인 |
| 채널 어댑터 | discord.py + python-telegram-bot | Discord/Telegram 봇 통합 |
| Home Assistant | REST API | IoT 디바이스 제어 |
| 리서치 | Playwright + Tavily + DuckDuckGo | 웹 리서치 |

---

## 6계층 메모리 시스템

메모리 시스템은 6개의 기능 계층 (M0, M1, M3, M4, M5.1-5.3)으로 구성되며 `MemoryManager`(`backend/memory/unified/`)가 오케스트레이션합니다.

```mermaid
graph TB
    Input["사용자 메시지"] --> M0

    subgraph Memory["6계층 메모리 시스템"]
        M0["M0: 이벤트 버퍼<br/><i>실시간 이벤트 스트림</i>"]
        M1["M1: 워킹 메모리<br/><i>인메모리 deque (20턴)</i><br/><i>JSON 영속화</i>"]
        M3["M3: 세션 아카이브<br/><i>SQLite / PostgreSQL</i><br/><i>세션, 메시지, 로그</i>"]
        M4["M4: 장기 메모리<br/><i>ChromaDB / pgvector</i><br/><i>3072차원 Gemini 임베딩</i><br/><i>적응형 decay, 중복 제거</i>"]

        M51["M5.1: MemGPT<br/><i>예산 기반 선택</i><br/><i>토큰 예산 조립</i>"]
        M52["M5.2: GraphRAG<br/><i>엔티티-관계 그래프</i><br/><i>spaCy NER + LLM 추출</i><br/><i>BFS 탐색 (100+ 시 C++)</i>"]
        M53["M5.3: MetaMemory<br/><i>접근 패턴 추적</i><br/><i>핫 메모리 감지</i>"]
    end

    M0 --> M1
    M1 -->|"즉시 영속화"| M3
    M1 -->|"자동 프로모션<br/>(importance ≥ 0.6)"| M4
    M3 -->|"통합 (6시간)<br/>+ 재평가"| M4
    M4 --> M51
    M4 --> M52
    M4 --> M53
    M52 -->|"connection_count<br/>피드백"| M4
    M53 -->|"핫 부스트"| M4

    Context["ContextService<br/>build_smart_context()"] -.->|"병렬 조회"| M0 & M1 & M3 & M4 & M51 & M52 & M53
```

### 계층 상세

| 계층 | 파일 | 저장소 | 목적 |
|------|------|--------|------|
| M0 Event Buffer | `memory/event_buffer.py` | 인메모리 | 실시간 이벤트 스트리밍 |
| M1 Working Memory | `memory/current.py` | `data/working_memory.json` | 현재 대화 버퍼 (20턴) |
| M3 Session Archive | `memory/recent/` | `data/sqlite/sqlite_memory.db` | 세션 요약, 메시지 히스토리 |
| M4 Long-Term Memory | `memory/permanent/` | `data/chroma_db/` | 시맨틱 벡터 검색, 중요도 decay |
| M5.1 MemGPT | `memory/memgpt.py` | 인메모리 | 토큰 예산 선택, 주제 다양성 |
| M5.2 GraphRAG | `memory/graph_rag/` | `data/knowledge_graph.json` | 엔티티/관계 그래프, BFS 탐색 |
| M5.3 MetaMemory | `memory/meta_memory.py` | SQLite | 접근 빈도, 채널 다양성 |

### 메모리 Decay

메모리는 적응형 망각 곡선을 사용하여 시간이 지남에 따라 감소합니다:

```
decayed_importance = importance * decay_factor

decay_factor = f(
    time_elapsed,           # 지수적 시간 감소
    base_rate=0.001,        # MEMORY_BASE_DECAY_RATE로 설정
    access_count,           # 반복 접근 시 decay 둔화
    connection_count,       # 그래프 연결된 메모리는 decay 저항
    memory_type_modifier,   # 사실은 대화보다 천천히 decay
    circadian_stability     # 피크 시간대 부스트 (apply_circadian_stability())
)

삭제 임계값: 0.03   (MEMORY_DECAY_DELETE_THRESHOLD)
최소 보존: 0.3      (MEMORY_MIN_RETENTION)
유사도 중복 제거: 0.90  (MEMORY_SIMILARITY_THRESHOLD)
```

### 검색 스코어링

장기 메모리 검색은 다단계 스코어링 파이프라인을 적용합니다:

```
effective_score = base_relevance * decay_factor * importance_weight

importance_weight = 0.5 + 0.5 * clamp(importance, 0, 1)   # 범위: [0.5, 1.0]
```

- **M5 Hot Memory 부스트**: MetaMemory가 "hot"으로 표시한 메모리에 스코어 보너스 (+0.1) 적용
- **GraphRAG LLM 관련성**: 비동기 쿼리에서 엔티티 수 기반 단순 계산 대신 LLM 관련성 평가 사용

### 컨텍스트 조립

`await MemoryManager.build_smart_context()`는 문자 예산 내에서 모든 계층의 컨텍스트를 비동기 병렬로 조립합니다 (sync 래퍼: `build_smart_context_sync()`):

| 섹션 | 기본 예산 (문자) | 설정 키 |
|------|-----------------|---------|
| 시스템 프롬프트 | 20,000 | `BUDGET_SYSTEM_PROMPT` |
| 시간 컨텍스트 | 5,000 | `BUDGET_TEMPORAL` |
| 워킹 메모리 | 80,000 | `BUDGET_WORKING_MEMORY` |
| 장기 메모리 | 30,000 | `BUDGET_LONG_TERM` |
| GraphRAG | 12,000 | `BUDGET_GRAPHRAG` |
| 세션 아카이브 | 8,000 | `BUDGET_SESSION_ARCHIVE` |

`ContextService`는 M0(이벤트 버퍼)과 M5(Hot 메모리) 섹션도 조회하여 완전한 6계층 커버리지를 제공합니다.

### 세션 관리

- **자동 세션 타임아웃**: 30분 비활성 시 현재 세션을 자동 종료하고 새 세션 시작
- **앱 종료 시 LLM 요약**: 종료 시 LLM 기반 세션 요약 시도 (10초 타임아웃, 실패 시 fallback)
- **LLM 중요도 평가**: 세션 종료 시 facts/insights를 LLM으로 중요도 평가 (fallback: 0.5)
- **자동 프로모션 (M2→M3)**: LLM 중요도 ≥ 0.6인 세션은 자동으로 `conversation` 타입 장기 메모리로 승격
- **메모리 승격 기준**: importance ≥ 0.55 또는 (repetitions ≥ 2 AND importance ≥ 0.35)

### 자동 Consolidation

앱 내에서 6시간마다 자동으로 `consolidate_memories()` 실행. 별도로 `scripts/memory_gc.py`를 cron에 등록하여 해시/시맨틱 중복 제거도 수행합니다.

- **사용자 행동 메트릭**: Consolidator가 `collect_behavior_metrics()`로 실제 사용자 행동 메트릭을 수집하여 적응형 decay에 활용
- **중요도 재평가**: 오래된 메모리(>168시간) 중 접근 횟수가 높은 항목을 주기적으로 LLM 재평가 (배치 크기: 50)
- **GraphRAG → M3 피드백**: 엔티티 추출 시 관련 장기 메모리의 `connection_count`를 자동 업데이트

### PostgreSQL 백엔드 (선택)

`DATABASE_URL` 설정 시 SQLite/ChromaDB 대신 PostgreSQL + pgvector 사용:

```
backend/memory/pg/
  connection.py            # PgConnectionManager (연결 풀)
  memory_repository.py     # PgMemoryRepository (ChromaDB 대체)
  graph_repository.py      # PgGraphRepository (JSON 그래프 대체)
  session_repository.py    # PgSessionRepository (SQLite 대체)
  meta_repository.py       # PgMetaMemoryRepository
  interaction_logger.py    # PgInteractionLogger
```

필요: PostgreSQL 17 + pgvector (`systemctl --user start axnmihn-postgres`)

---

## API 엔드포인트

모든 엔드포인트는 `Authorization: Bearer <token>` 또는 `X-API-Key` 헤더 인증이 필요합니다 (헬스/상태 엔드포인트 제외).

### 헬스 & 상태

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/health` | GET | 전체 헬스체크 (메모리, LLM, 모듈, 컴포넌트 latency) |
| `/health/quick` | GET | 최소 생존 확인 |
| `/metrics` | GET | Prometheus 메트릭스 (text format) |
| `/auth/status` | GET | 인증 상태 |
| `/llm/providers` | GET | 사용 가능한 LLM 프로바이더 |
| `/models` | GET | 사용 가능한 모델 |

### 채팅

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/v1/chat/completions` | POST | 채팅 완성 (스트리밍/비스트리밍, OpenAI 호환) |
| `/v1/models` | GET | 사용 가능한 모델 목록 |

### WebSocket

| 엔드포인트 | 프로토콜 | 설명 |
|-----------|---------|------|
| `/ws` | WebSocket | 실시간 채팅 (인증, Rate Limiting 30msg/min, Heartbeat) |

### 메모리

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/memory/consolidate` | POST | Decay + 페르소나 진화 트리거 |
| `/memory/stats` | GET | 메모리 계층 통계 |
| `/memory/search?query=&limit=` | GET | 시맨틱 메모리 검색 |
| `/memory/sessions` | GET | 최근 세션 요약 |
| `/memory/session/{session_id}` | GET | 세션 상세 |
| `/memory/interaction-logs` | GET | 상호작용 로그 |
| `/memory/interaction-stats` | GET | 상호작용 통계 |
| `/session/end` | POST | 현재 세션 종료 |

### 오디오

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/v1/audio/transcriptions` | POST | STT (Deepgram Nova-3) |
| `/v1/audio/speech` | POST | TTS 합성 |
| `/v1/audio/voices` | GET | 사용 가능한 TTS 음성 목록 |
| `/transcribe` | POST | 오디오 파일 트랜스크립션 |
| `/upload` | POST | 파일 업로드 |

### MCP

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/mcp/status` | GET | MCP 서버 상태 |
| `/mcp/manifest` | GET | MCP 도구 매니페스트 |
| `/mcp/execute` | POST | MCP 도구 실행 |

### OpenAI 호환

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/v1/models` | GET | 사용 가능한 모델 목록 |
| `/v1/chat/completions` | POST | 채팅 완성 (스트리밍/비스트리밍) |

### 코드 탐색

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/code/summary` | GET | 코드베이스 요약 |
| `/code/files` | GET | 코드 파일 목록 |

---

## MCP 생태계

SSE 전송을 통해 제공되는 32개 도구. 카테고리:

- **System (9):** run_command, search_codebase, search_codebase_regex, read_system_logs, list_available_logs, analyze_log_errors, check_task_status, tool_metrics, system_status
- **Memory (6):** query_axel_memory, add_memory, store_memory, retrieve_context, get_recent_logs, memory_stats
- **File (3):** read_file, list_directory, get_source_code
- **Research (6):** web_search, visit_webpage, deep_research, tavily_search, read_artifact, list_artifacts
- **Home Assistant (6):** hass_control_light, hass_control_device, hass_read_sensor, hass_get_state, hass_list_entities, hass_execute_scene
- **Delegation (2):** delegate_to_opus, google_deep_research

도구 표시 여부는 `MCP_DISABLED_TOOLS` 및 `MCP_DISABLED_CATEGORIES` 환경 변수로 설정 가능합니다.

---

## 네이티브 C++ 모듈

C++17 + pybind11 + SIMD (AVX2/NEON)를 통한 성능 크리티컬 연산:

```
backend/native/src/
  axnmihn_native.cpp      # pybind11 바인딩
  decay.cpp/.hpp           # 메모리 decay (SIMD 배치)
  vector_ops.cpp/.hpp      # 코사인 유사도, 중복 감지
  string_ops.cpp/.hpp      # Levenshtein 거리
  graph_ops.cpp/.hpp       # BFS 탐색
  text_ops.cpp/.hpp        # 텍스트 처리
```

모듈이 설치되지 않은 경우 모든 호출 지점은 순수 Python으로 폴백됩니다.

```bash
cd backend/native && pip install .
# 필요: CMake 3.18+, C++17 컴파일러, pybind11
```

---

## 설정

### 환경 변수 (`.env`)

```bash
# API Keys
GEMINI_API_KEY=your-gemini-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
OPENAI_API_KEY=your-openai-api-key
TAVILY_API_KEY=your-tavily-api-key
DEEPGRAM_API_KEY=your-deepgram-api-key

# Home Assistant
HASS_URL=http://homeassistant.local:8123
HASS_TOKEN=your-hass-long-lived-token

# Server
AXNMIHN_API_KEY=your-api-key
HOST=0.0.0.0
PORT=8000
DEBUG=false
TZ=America/Vancouver

# Models
CHAT_PROVIDER=google
GEMINI_MODEL=gemini-3-flash-preview
ANTHROPIC_MODEL=claude-sonnet-4-5-20250929
ANTHROPIC_THINKING_BUDGET=10000
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSION=3072

# Memory budgets (chars)
BUDGET_SYSTEM_PROMPT=20000
BUDGET_TEMPORAL=5000
BUDGET_WORKING_MEMORY=80000
BUDGET_LONG_TERM=30000
BUDGET_GRAPHRAG=12000
BUDGET_SESSION_ARCHIVE=8000

# Memory decay
MEMORY_BASE_DECAY_RATE=0.001
MEMORY_MIN_RETENTION=0.3
MEMORY_DECAY_DELETE_THRESHOLD=0.03
MEMORY_SIMILARITY_THRESHOLD=0.90
MEMORY_MIN_IMPORTANCE=0.55

# Context
CONTEXT_WORKING_TURNS=20
CONTEXT_FULL_TURNS=6
CONTEXT_MAX_CHARS=500000

# Providers
DEFAULT_LLM_PROVIDER=gemini
SEARCH_PROVIDER=tavily

# PostgreSQL
DATABASE_URL=postgresql://axel:password@localhost:5432/axel
PG_POOL_MIN=2
PG_POOL_MAX=10

# Docker Compose (docker-compose.yml에서 사용, 선택)
# POSTGRES_USER=axel
# POSTGRES_PASSWORD=change-me-in-production
# POSTGRES_DB=axel

# TTS Configuration
TTS_SERVICE_URL=http://127.0.0.1:8002
TTS_SYNTHESIS_TIMEOUT=30.0
TTS_FFMPEG_TIMEOUT=10.0
TTS_QUEUE_MAX_PENDING=3
TTS_IDLE_TIMEOUT=300

# Channel Adapters (Discord / Telegram)
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_CHANNELS=           # comma-separated channel IDs (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=             # comma-separated usernames (optional)
TELEGRAM_ALLOWED_CHATS=             # comma-separated chat IDs (optional)

# Admin
AXNMIHN_ADMIN_EMAIL=admin@example.com
```

---

## 빠른 시작

### 옵션 A: Systemd 서비스

```bash
git clone https://github.com/NorthProt-Inc/axnmihn.git
cd axnmihn

cp .env.example .env
# .env 파일에서 API 키 설정

# 인프라 서비스 시작
systemctl --user start axnmihn-postgres axnmihn-redis

# 백엔드 시작
systemctl --user start axnmihn-backend axnmihn-mcp axnmihn-research

# 확인
curl http://localhost:8000/health/quick
```

backend (8000) + MCP (8555) + research (8766) + PostgreSQL (5432) + Redis (6379).

### 옵션 B: 로컬 개발

```bash
git clone https://github.com/NorthProt-Inc/axnmihn.git
cd axnmihn

python3.12 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example .env
# .env 파일에서 API 키 설정

# (선택) 네이티브 C++ 모듈
cd backend/native && pip install . && cd ../..

# (선택) 리서치용 Playwright
playwright install chromium

# PostgreSQL + Redis (systemd 서비스)
systemctl --user start axnmihn-postgres axnmihn-redis

# 실행
uvicorn backend.app:app --host 0.0.0.0 --port 8000
curl http://localhost:8000/health
```

---

## 배포

### Systemd 서비스 (기본)

| 서비스 | 포트 | 목적 | 리소스 |
|--------|------|------|--------|
| `axnmihn-backend` | 8000 | FastAPI 백엔드 | 4G RAM, 200% CPU |
| `axnmihn-mcp` | 8555 | MCP 서버 (SSE) | 1G RAM, 100% CPU |
| `axnmihn-research` | 8766 | Research MCP | 2G RAM, 150% CPU |
| `axnmihn-tts` | 8002 | TTS 마이크로서비스 (Qwen3-TTS) | 4G RAM, 200% CPU |
| `axnmihn-wakeword` | - | Wakeword 감지 | 512M RAM, 50% CPU |
| `context7-mcp` | 3002 | Context7 MCP | 1G RAM |
| `markitdown-mcp` | 3001 | Markitdown MCP | 1G RAM |

자세한 운영 가이드는 [OPERATIONS.md](OPERATIONS.md) 참조.

### Docker Compose (선택)

앱 서비스의 Docker 배포도 지원한다. 인프라(PostgreSQL, Redis)는 systemd로 운영하고, 앱만 Docker로 실행하는 하이브리드 구성이 가능하다.

```bash
docker compose up -d              # 앱 서비스 시작
docker compose ps                 # 상태
docker compose logs backend -f    # 백엔드 로그
docker compose down               # 중지
```

| 서비스 | 포트 | 이미지/타겟 | 리소스 |
|--------|------|------------|--------|
| `backend` | 8000 | Dockerfile -> runtime | 4G RAM, 2 CPU |
| `mcp` | 8555 | Dockerfile -> runtime | 1G RAM, 1 CPU |
| `research` | 8766 | Dockerfile -> research | 2G RAM, 1.5 CPU |

### 유지보수

| 스크립트 | 목적 |
|---------|------|
| `scripts/memory_gc.py` | 메모리 가비지 컬렉션 (중복 제거, decay, 초과 크기 제거) |
| `scripts/db_maintenance.py` | SQLite VACUUM, ANALYZE, 무결성 체크 |
| `scripts/dedup_knowledge_graph.py` | 지식 그래프 중복 제거 |
| `scripts/regenerate_persona.py` | 7일 증분 페르소나 업데이트 |
| `scripts/optimize_memory.py` | 4단계 메모리 최적화 (텍스트 정리, 역할 정규화) |
| `scripts/cleanup_messages.py` | LLM 기반 메시지 정리 (병렬, 체크포인트) |
| `scripts/populate_knowledge_graph.py` | 지식 그래프 초기 채우기 |
| `scripts/night_ops.py` | 자동화된 야간 리서치 |
| `scripts/run_migrations.py` | 데이터베이스 스키마 마이그레이션 |

---

## 프로젝트 구조

```
axnmihn/
├── backend/
│   ├── app.py                    # FastAPI 진입점, 라이프스팬
│   ├── config.py                 # 모든 설정
│   ├── api/                      # HTTP 라우터 (status, chat, memory, mcp, media, audio, openai)
│   ├── core/                     # 핵심 서비스
│   │   ├── chat_handler.py       # 메시지 라우팅
│   │   ├── context_optimizer.py  # 컨텍스트 크기 관리
│   │   ├── mcp_client.py        # MCP 클라이언트
│   │   ├── mcp_server.py        # MCP 서버 설정
│   │   ├── health/              # 헬스 모니터링
│   │   ├── identity/            # AI 페르소나 (ai_brain.py)
│   │   ├── intent/              # 의도 분류
│   │   ├── logging/             # 구조화된 로깅
│   │   ├── mcp_tools/           # 도구 구현
│   │   ├── persona/             # 채널 적응
│   │   ├── security/            # 프롬프트 방어
│   │   ├── session/             # 세션 상태
│   │   ├── telemetry/           # 상호작용 로깅
│   │   └── utils/               # 캐시, 재시도, HTTP 풀, Gemini 클라이언트, circuit breaker
│   ├── llm/                     # LLM 프로바이더 (Gemini, Anthropic)
│   ├── media/                   # TTS 관리자
│   ├── memory/                  # 6계층 메모리 시스템
│   │   ├── unified/             # MemoryManager 오케스트레이터 (core, facade, context_builder, session)
│   │   ├── event_buffer.py      # M0: 이벤트 버퍼
│   │   ├── current.py           # M1: 워킹 메모리
│   │   ├── recent/              # M3: 세션 아카이브 (SQLite)
│   │   ├── permanent/           # M4: 장기 (ChromaDB)
│   │   ├── memgpt.py            # M5.1: 예산 선택
│   │   ├── graph_rag/            # M5.2: 지식 그래프
│   │   ├── meta_memory.py       # M5.3: 접근 추적
│   │   ├── temporal.py          # 시간 컨텍스트
│   │   └── pg/                  # PostgreSQL 백엔드 (선택)
│   ├── native/                  # C++17 확장 모듈
│   ├── channels/                # 채널 어댑터 시스템
│   │   ├── protocol.py          # ChannelAdapter Protocol
│   │   ├── manager.py           # 라이프사이클 관리
│   │   ├── message_chunker.py   # 플랫폼별 메시지 분할
│   │   ├── bridge.py            # ChatHandler 브릿지
│   │   ├── discord/bot.py       # Discord 어댑터
│   │   ├── telegram/bot.py      # Telegram 어댑터
│   │   └── commands/registry.py # 인라인 커맨드 파서
│   ├── protocols/mcp/           # MCP 프로토콜 핸들러
│   └── wake/                    # Wakeword + 음성 대화
├── tests/                       # pytest 테스트 스위트
├── scripts/                     # 자동화 스크립트
├── data/                        # 런타임 데이터 (SQLite, ChromaDB, JSON)
├── logs/                        # 애플리케이션 로그
├── storage/                     # 리서치 아티팩트, 크론 보고서
├── Dockerfile                   # 멀티스테이지 (runtime + research)
├── docker-compose.yml           # 전체 스택 (app + PG + Redis)
├── .dockerignore
├── pyproject.toml               # 프로젝트 메타데이터
└── .env                         # 환경 설정
```

---

## 문서

- [OPERATIONS.md](OPERATIONS.md) — 운영 가이드 (한/영)
- [AGENTS.md](AGENTS.md) — 커스텀 에이전트 정의
- [logging.md](logging.md) — 로깅 시스템 문서
- [memory-system-analysis.md](memory-system-analysis.md) — 메모리 시스템 분석 보고서
- [backend/native/README.md](backend/native/README.md) — C++ 네이티브 모듈
- `.github/instructions/` — 개발 지침 (TDD, 보안, 성능, 에러 분석)

---

## 기여

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'feat: add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

**커밋 규칙:** Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, etc.)

**코드 스타일:**
- Python: `black` 포매팅, `ruff` 린트, type hints 필수
- 함수 최대 400줄, 파일 최대 800줄
- Protocol 기반 인터페이스, dataclass/pydantic 데이터
- async def 우선 (I/O-bound 작업)

---

## 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 참조

---

## 감사의 말

- **FastAPI** — 현대적인 웹 프레임워크
- **ChromaDB** — 벡터 데이터베이스
- **Anthropic & Google** — LLM API
- **Deepgram** — 음성 인식
- **Model Context Protocol** — 도구 통합 표준

---

**제작:** NorthProt Inc.  
**문의:** [GitHub Issues](https://github.com/NorthProt-Inc/axnmihn/issues)

</details>
