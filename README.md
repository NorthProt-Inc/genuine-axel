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
|   |  +--------+ +--------+ +--------+ +--------+ +--------+ +--------+ |   |
|   |  | Main   | |Research| | Memory | | Opus   | |Context7| |Markit- | |   |
|   |  | MCP    | |  MCP   | |  MCP   | | Bridge | |  MCP   | | down   | |   |
|   |  | :8555  | | :8766  | | (int)  | | (CLI)  | | :3002  | | :3001  | |   |
|   |  +--------+ +--------+ +--------+ +--------+ +--------+ +--------+ |   |
|   +---------------------------------------------------------------------+   |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

## Core Components

### 1. Chat Pipeline (`backend/core/chat_handler.py`)

Simplified pipeline following the **"Think -> Tool -> Speak"** pattern.

| Stage | Description |
|-------|-------------|
| **Context Optimizer** | Configurable context window management |
| **MCP Tool Execution** | Tool invocation and result integration |
| **Response Stream** | SSE-based real-time response |

**Default Context Configuration:**
```python
# From config.py - single source of truth
CONTEXT_WORKING_TURNS = 30
CONTEXT_FULL_TURNS = 10
CONTEXT_MAX_CHARS = 500_000
```

### 2. Memory System (`backend/memory/`)

3-layer memory architecture with integrated short-term, session, and long-term memory management.

| Layer | Storage | Purpose | Token Budget |
|-------|---------|---------|--------------|
| **Working Memory** | JSON | Current conversation context | 150,000 tokens |
| **Session Archive** | SQLite | Session summaries and metadata | Permanent |
| **Long-term Memory** | ChromaDB | Vector search-based long-term memory | 120,000 tokens |

**Key Modules:**
- `permanent/` - Modular long-term memory system (ChromaDB integration)
  - `facade.py` - Main LongTermMemory facade
  - `config.py` - Memory configuration
  - `decay_calculator.py` - Adaptive decay calculations
  - `embedding_service.py` - Embedding generation with caching
  - `repository.py` - ChromaDB CRUD operations
  - `consolidator.py` - Memory cleanup and consolidation
  - `importance.py` - Importance scoring
  - `migrator.py` - Legacy data migration
  - `protocols.py` - Interface definitions
- `recent.py` - Session archive and summarization
- `graph_rag.py` - Knowledge Graph-based relational memory
- `unified.py` - Unified interface
- `memgpt.py` - MemGPT-style self-editing memory
- `current.py` - Working memory management
- `temporal.py` - Temporal indexing

### 3. Identity & Persona (`backend/core/identity/`)

AI persona and identity management system.

- `ai_brain.py` - Dynamic persona loading and evolution
- Daily persona updates (`scripts/evolve_persona_24h.py`)
- Regenerate persona (`scripts/regenerate_persona.py`)

### 4. Services Layer (`backend/core/services/`)

Modular services extracted from ChatHandler for better testability and separation of concerns.

| Service | Description |
|---------|-------------|
| `SearchService` | Memory and knowledge search operations |
| `MemoryPersistenceService` | Memory storage and retrieval |
| `ContextService` | Context building and classification |
| `ToolExecutionService` | MCP tool execution management |
| `ReActLoopService` | ReAct reasoning loop orchestration |

### 5. Filters (`backend/core/filters/`)

Stream filters for LLM output processing.

| Module | Description |
|--------|-------------|
| `xml_filter.py` | XML tag stripping and normalization |

### 6. MCP Server Ecosystem

Six independent MCP servers handling their respective domains.

#### Main MCP Server (`backend/core/mcp_server.py`) - Port 8555
- System observation tools (log analysis, codebase search)
- Home Assistant device control
- Memory access and storage
- SSE transport via `mcp_transport.py`

#### Modular MCP Tools (`backend/core/mcp_tools/`)
Modularized tool system:

| Module | Description |
|--------|-------------|
| `schemas.py` | Tool schema definitions and validation |
| `file_tools.py` | File read/write/search |
| `hass_tools.py` | Home Assistant device control |
| `memory_tools.py` | Memory store/search/management |
| `research_tools.py` | Web search/page analysis |
| `system_tools.py` | System monitoring/log analysis |
| `opus_tools.py` | Claude Opus delegation |

**Tool Registry Pattern:**
```python
from backend.core.mcp_tools import register_tool

@register_tool("my_tool", category="custom")
async def my_tool(arguments: dict) -> Sequence[TextContent]:
    ...
```

#### Research MCP Server (`backend/protocols/mcp/research_server.py`) - Port 8766
- **Playwright**-based headless browser
- DuckDuckGo search + page crawling
- Tavily API integration (optional)
- Google Deep Research agent

#### Memory MCP Server (`backend/protocols/mcp/memory_server.py`)
- `retrieve_context` - Relevant memory retrieval
- `store_memory` - Long-term memory storage
- GraphRAG query interface

#### Opus Bridge (`backend/protocols/mcp/opus_bridge.py`)
- Coding task delegation via Claude CLI
- Automatic file context collection
- Silent Intern pattern implementation

#### Context7 MCP Server - Port 3002
- Supergateway-based Streamable HTTP transport
- Real-time programming library documentation search
- Auto-restart every 6 hours (process leak prevention)

#### Markitdown MCP Server - Port 3001
- Supergateway-based Streamable HTTP transport
- URL/file to Markdown conversion
- Auto-restart every 4 hours (process leak prevention)

### 7. LLM Integration (`backend/llm/`)

| Component | Description |
|-----------|-------------|
| `router.py` | Model configuration |
| `clients.py` | LLM client (Google Gemini) |

**Model Configuration:**
```python
MODEL_NAME = "gemini-3-flash-preview"
EMBEDDING_MODEL = "models/gemini-embedding-001"
```

**Resilience Patterns:**
- **Circuit Breaker** - Auto-handling of 429 (Rate Limit), 503 (Server Error), Timeout
- **Adaptive Timeout** - Dynamic timeout based on tool count and recent latency
- **Cooldown** - Automatic cooldown on failure (300s/60s/30s)

### 8. Error Handling (`backend/core/errors.py`)

Centralized exception handling system:
- Custom error class definitions
- Error monitoring (`core/logging/error_monitor.py`)
- Request tracking (`core/logging/request_tracker.py`)

### 9. Home Assistant Integration (`backend/core/tools/hass_ops.py`)

Direct IoT device control:
- Lighting control (WiZ RGB) - color, brightness, on/off
- Fan/air purifier control
- Sensor reading (battery, weather, printer status)

---

## Tech Stack

| Category | Technology |
|----------|------------|
| **Runtime** | Python 3.12, FastAPI, Uvicorn |
| **LLM** | Google Gemini 3 Flash |
| **Embedding** | Gemini Embedding 001 |
| **Memory** | ChromaDB (Vector), SQLite (Session) |
| **MCP Protocol** | mcp>=1.0.0, sse-starlette>=2.0.0 |
| **MCP Transport** | SSE (Server-Sent Events), Supergateway |
| **Search** | Playwright, DuckDuckGo, Tavily API, Google Deep Research |
| **IoT** | Home Assistant REST API |
| **Audio** | Deepgram Nova-3 (STT), Qwen3 TTS (Local) |
| **Infrastructure** | Systemd User Services, Docker Rootless, Pop!_OS |

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
|   |   +-- mcp_server.py      # Main MCP server (:8555)
|   |   +-- mcp_client.py      # MCP client
|   |   +-- mcp_transport.py   # SSE transport layer
|   |   +-- context_optimizer.py # Context management
|   |   +-- errors.py          # Custom exceptions
|   |   +-- research_artifacts.py # Research output management
|   |   +-- identity/          # Persona management
|   |   |   +-- ai_brain.py    # Dynamic persona
|   |   +-- filters/           # LLM output stream filters
|   |   |   +-- xml_filter.py  # XML tag processing
|   |   +-- services/          # Modular services
|   |   |   +-- search_service.py        # Search operations
|   |   |   +-- memory_persistence_service.py # Memory persistence
|   |   |   +-- context_service.py       # Context building
|   |   |   +-- tool_service.py          # Tool execution
|   |   |   +-- react_service.py         # ReAct loop
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
|   |   +-- permanent/         # Long-term memory (ChromaDB)
|   |   |   +-- facade.py      # Main LongTermMemory class
|   |   |   +-- config.py      # Memory configuration
|   |   |   +-- decay_calculator.py # Adaptive decay
|   |   |   +-- embedding_service.py # Embedding generation
|   |   |   +-- repository.py  # ChromaDB operations
|   |   |   +-- consolidator.py # Memory consolidation
|   |   |   +-- importance.py  # Importance scoring
|   |   |   +-- migrator.py    # Legacy migration
|   |   |   +-- protocols.py   # Interface definitions
|   |   +-- recent.py          # Session archive
|   |   +-- unified.py         # Unified interface
|   |   +-- graph_rag.py       # Knowledge Graph
|   |   +-- memgpt.py          # Self-editing memory
|   |   +-- current.py         # Working memory
|   |   +-- temporal.py        # Temporal indexing
|   +-- protocols/              # Communication Protocols
|   |   +-- mcp/               # Model Context Protocol
|   |       +-- server.py      # Base MCP server
|   |       +-- research_server.py # Deep research (:8766)
|   |       +-- memory_server.py # Memory access
|   |       +-- async_research.py # Async research
|   |       +-- opus_bridge.py # Opus delegation
|   |       +-- google_research.py # Google research
|   +-- media/                  # Audio processing
|   |   +-- qwen_tts.py        # Qwen3 TTS (local GPU)
|   +-- wake/                   # Wakeword detection
|   +-- app.py                 # FastAPI entry point
|   +-- config.py              # Centralized configuration
+-- scripts/                    # Automation & maintenance
|   +-- memory_gc.py           # Memory garbage collection
|   +-- night_ops.py           # Night batch operations
|   +-- regenerate_persona.py  # Persona regeneration
|   +-- evolve_persona_24h.py  # Daily persona evolution
|   +-- axel_chat.py           # CLI chat interface
|   +-- cleanup_messages.py    # Message cleanup utility
|   +-- populate_knowledge_graph.py # Knowledge graph population
|   +-- dedup_knowledge_graph.py # Knowledge graph deduplication
|   +-- db_maintenance.py      # Database maintenance
|   +-- run_migrations.py      # Database migrations
|   +-- cron_memory_gc.sh      # Memory GC cron wrapper
|   +-- cron_audio_cleanup.sh  # Audio/log cache cleanup
+-- data/                       # Runtime data
|   +-- working_memory.json    # Session memory
|   +-- chroma_db/             # Vector DB
|   +-- sqlite/                # Structured memory
|   +-- knowledge_graph.json   # Knowledge graph
|   +-- dynamic_persona.json   # Dynamic persona
+-- storage/                    # Research artifacts & reports
|   +-- research/              # Research outputs
|   |   +-- inbox/             # Deep research results
|   |   +-- artifacts/         # Saved web content
|   +-- cron/                  # Cron job results
|       +-- reports/           # Cron report files
+-- logs/                       # Application logs
+-- tests/                      # Test suite
```

---

## Installation

### Prerequisites
- Python 3.12+
- Node.js 22+ (for Context7, Markitdown MCP)
- `ffmpeg` (audio processing)
- Home Assistant instance (optional, for IoT)
- NVIDIA GPU (optional, for local Qwen3 TTS)

### Setup

```bash
# 1. Clone repository
git clone https://github.com/NorthProt/axnmihn.git
cd axnmihn

# 2. Environment setup
cp .env.example .env
# Configure API keys: GEMINI_API_KEY, etc.

# 3. Install dependencies
python -m venv ~/projects-env
source ~/projects-env/bin/activate
pip install -r backend/requirements.txt

# 4. Run backend
python -m backend.app

# 5. (Optional) Install systemd user services
cp scripts/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now axnmihn-backend axnmihn-mcp axnmihn-research
```

### Key Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Google Gemini API key |
| `LLM_MODEL` | Model name (default: gemini-3-flash-preview) |
| `SEARCH_PROVIDER` | Search provider (tavily/duckduckgo) |
| `HASS_URL` | Home Assistant URL |
| `HASS_TOKEN` | Home Assistant long-lived token |
| `AXNMIHN_API_KEY` | Backend API authentication key |

### Systemd Services

#### Core Services
| Service | Port | Description |
|---------|------|-------------|
| `axnmihn-backend.service` | 8000 | Main FastAPI backend |
| `axnmihn-mcp.service` | 8555 | Main MCP server (SSE) |
| `axnmihn-research.service` | 8766 | Research MCP server |
| `axnmihn-wakeword.service` | Systemd | Wakeword detection |

#### MCP Extension Services
| Service | Port | Description |
|---------|------|-------------|
| `context7-mcp.service` | 3002 | Context7 docs search (Supergateway) |
| `markitdown-mcp.service` | 3001 | URL/file to Markdown (Supergateway) |

#### Infrastructure
| Service | Description |
|---------|-------------|
| `docker.service` | Docker Rootless (Home Assistant, etc.) |

---

## Key Design Decisions

### Single Model Architecture
Simplified to a single Gemini model instead of complex multi-model routing. Memory optimization is handled by the MCP `retrieve_context` tool.

### Circuit Breaker Pattern
Auto-detection and cooldown for 429/503/Timeout errors on LLM API calls. Prevents cascading failures.

### Adaptive Timeout
Dynamic timeout calculation based on tool count and latency of the last 10 requests.

### End Resource Starvation
Tier settings significantly expanded to utilize modern LLMs' large context windows (100k-2M tokens).

### Compression-Free Recent Turns
Last N turns preserved in full without compression.

### Async Deep Research
Google Deep Research runs asynchronously in the background.

### Modular MCP Architecture
MCP tools organized with `@register_tool` decorator-based registry. Tools auto-register and are separated by category for maintainability.

### Supergateway for External MCPs
External MCP servers like Context7 and Markitdown use Supergateway for stdio→Streamable HTTP conversion. Timer-based auto-restart prevents process leaks.

### Modular Permanent Memory
Long-term memory refactored from monolithic `permanent.py` to a modular `permanent/` package with clear separation of concerns (embedding, decay, consolidation, repository).

---

## Acknowledgments

- Built with [Claude Code](https://claude.ai/claude-code) by Anthropic

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
