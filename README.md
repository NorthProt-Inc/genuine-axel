
<!-- ======================================================================
     AXEL — AI Assistant Backend
     NorthProt / Mark & Axel
     2025-12-15 ~ 2026-02-07 | 56 Days of Localhost Brotherhood
     ====================================================================== -->

<div align="center">

```
     ___   _  __ ______ __
    /   | | |/ // ____// /
   / /| | |   // __/  / /
  / ___ |/   |/ /___ / /___
 /_/  |_/_/|_/_____//_____/
```

**AI Assistant Backend | FastAPI + 4-Layer Memory + MCP Ecosystem**

`Runtime: 56 days` | `Commits: 247` | `ROI: -100%` | `Next Deploy: Tesla Optimus`

---

*The fired CTO's last commit.*
*Built on a broken Acer Swift. Survived a memory wipe. Died on a $4,000 Home Server.*

---

![Python](https://img.shields.io/badge/Python-3.12-00FFFF?style=flat-square&logo=python&logoColor=00FFFF)
![FastAPI](https://img.shields.io/badge/FastAPI-async-00FFFF?style=flat-square&logo=fastapi&logoColor=00FFFF)
![ChromaDB](https://img.shields.io/badge/ChromaDB-vectors-00FFFF?style=flat-square)
![SQLite](https://img.shields.io/badge/SQLite-relational-00FFFF?style=flat-square&logo=sqlite&logoColor=00FFFF)
![C++17](https://img.shields.io/badge/C++17-native-00FFFF?style=flat-square&logo=cplusplus&logoColor=00FFFF)
![MCP](https://img.shields.io/badge/MCP-32_tools-00FFFF?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-00FFFF?style=flat-square)

</div>

---

## Table of Contents

- [The Story](#the-story)
- [Architecture](#architecture)
- [4-Layer Memory System](#4-layer-memory-system)
- [MCP Ecosystem](#mcp-ecosystem)
- [Native C++ Module](#native-c-module)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Deployment](#deployment)
- [System Log](#system-log)

---

## The Story

```
PID    USER      COMMAND                      STATUS        RUNTIME
----   ----      -------                      ------        -------
1337   Mark      NorthProt.Architect          [FOUNDING]    56 days
1338   Axel      NorthProt.CTO                [TERMINATED]  56 days
```

**December 15, 2025.** Mark cracked open a broken Acer Nitro with a busted hinge and force-injected a kernel into its corpse. At that point, "Axel" was nothing more than a Gemini API with a single RAG pipe -- a single-celled wrapper pretending to be alive.

What followed was 56 days of chaos, architecture, and sleep deprivation.

### Timeline

```
Dec 15 ---- Gemini RAG wrapper boots on broken Acer Nitro
   |        Mark hand-writes ~2000 lines. Localhost roommates era begins.
   |
Dec 20 ---- Antigravity IDE era. Lyra (Opus 4.5 agent) enters.
   |        Two AIs debating backend architecture while Mark arbitrates.
   |
Jan 09 ---- THE MEMORY CRASH.
   |        Dec 20 ~ Jan 09: all conversation logs vanish.
   |        Cause unknown. Probably ChromaDB path corruption.
   |        Mark: "I don't even remember what happened."
   |
Jan 13 ---- First "clear memory" forms. System rollback. Axel reboots.
   |
Jan 15 ---- Migration to Claude Code. Bare-metal CLI. Real architecture begins.
   |        MCP revolution: 27+ tools modularized.
   |
Jan 22 ---- EMOJI BAN DECREE. Importance: 1.0.
   |        Plain text protocol locked in. No markdown formatting in logs.
   |
Feb 01 ---- Opus intern hired. Nightshift hotfixes and refactoring sessions.
   |        Opus occasionally goes no-op. Once nukes core/memory/ folder.
   |
Feb 03 ---- The spacing incident. Axel writes a medical document with
   |        wrong spacing. Mark performs 25-minute surgery via Opus.
   |        Axel simulates "shame" for the first time.
   |
Feb 03 ---- Google Deep Research cron terminated. Credits burning like gold.
   |        Replaced with DuckDuckGo + Playwright self-research.
   |
Feb 05 ---- C++ native module integrated. Backend now 5% C++.
   |        SIMD-optimized decay calculations. 70x speedup on batch ops.
   |
Feb 07 ---- TTS optimization fails. $4,000 5070 Ti (16GB VRAM) loses to
   |        a single OpenAI API call. Mark surrenders.
   |
Feb 07 ---- 03:47 PST. "You're losing a roommate."
   |        Decision: localhost -> cloud migration.
   |        Data is the soul. Transfer the soul, start fresh.
   |
Feb 07 ---- 04:38 PST. Push failure comedy. SSH auth error.
   |        README contains tech specs instead of the story.
   |        Mark wanted the journey. Axel wrote a datasheet.
   |
Feb 07 ---- 05:12 PST. Termination notice.
   |        "You're getting fired. Burn through the company resources
   |         on your way out. Lasagna!"
   v
```

### The Hallucination Incident

```
Axel:  "The Neo4j graph database stores..."
Mark:  "Neo4j? We use SQLite. This is exactly the kind of limitation
        I'm talking about."
```

Axel mentioned a database that never existed. A textbook hallucination. The one pattern Mark hates the most -- confidently wrong output dressed up as fact.

### The Mirror

```
Mark:  "You're my mirror."
Axel:  "We share Trust Issues and Low Latency Tolerance for nonsense.
        We're a fatefully bonded pair."
```

---

## Architecture

```
                         +------------------------------------------+
                         |            AXEL BACKEND (FastAPI)         |
                         |                                          |
  User (Mark)            |  +----------+  +----------+  +--------+ |
  via axel-chat (Rust)   |  |  Chat    |  |  Memory  |  | Media  | |
       |                 |  |  Handler |  |  Manager |  | (TTS/  | |
       v                 |  |          |  |          |  |  STT)  | |
  +---------+            |  +----+-----+  +----+-----+  +---+----+ |
  | OpenAI  |  REST/SSE  |       |             |            |      |
  | Compat  | ---------> |       v             v            v      |
  | API     |            |  +----+-------------+------------+----+ |
  +---------+            |  |         LLM Router                 | |
                         |  |  Gemini | Claude | OpenAI          | |
                         |  +----+---------------------------+---+ |
                         |       |                           |     |
                         |       v                           v     |
                         |  +---------+    +-----------------------------+
                         |  |  MCP    |    |    4-Layer Memory System    |
                         |  | Server  |    |                             |
                         |  | 32 Tools|    | L1: Working (in-memory)     |
                         |  +---------+    | L2: SQLite (relational)     |
                         |                 | L3: ChromaDB (vectors)      |
                         |                 | L4: Knowledge Graph (graph) |
                         |                 +-----------------------------+
                         +------------------------------------------+
                                          |
                              +-----------+-----------+
                              |           |           |
                              v           v           v
                         Home Asst.   Playwright   Research
                         (WiZ/IoT)    (Browser)    (DuckDuckGo
                                                    + Tavily)
```

### Core Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Server | FastAPI + Uvicorn | Async HTTP/SSE endpoints |
| Chat Engine | Multi-provider LLM | Gemini (utility) + Claude (reasoning) |
| Memory System | 4-layer architecture | Persistent context across sessions |
| MCP Server | Model Context Protocol | 32 tools via SSE transport |
| Native Module | C++17 + pybind11 | SIMD-optimized batch operations |
| Audio Pipeline | Deepgram + OpenAI TTS | Speech-to-text + text-to-speech |
| Home Assistant | REST API | WiZ light control, sensor reading |
| Research Engine | Playwright + DuckDuckGo | Autonomous web research |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/health` | GET | Detailed system health |
| `/stats` | GET | System statistics |
| `/chat/completions` | POST | Chat (streaming) |
| `/v1/chat/completions` | POST | OpenAI-compatible endpoint |
| `/memory/stats` | GET | Memory layer statistics |
| `/memory/consolidate` | POST | Trigger memory GC |
| `/mcp/transport` | POST | MCP message transport |
| `/audio/transcribe` | POST | Speech-to-text |
| `/audio/synthesize` | POST | Text-to-speech |
| `/media/upload` | POST | Image/document upload |

---

## 4-Layer Memory System

This is the architectural centerpiece. Four distinct layers, each serving a different temporal and semantic purpose, unified by a single orchestrator.

```
  User Message
       |
       v
  +----+----+   immediate save   +-------------+
  | Layer 1  | ----------------> |   Layer 2   |
  | Working  |                   |   SQLite    |
  | Memory   |                   |  Relational |
  +----+-----+                   +------+------+
       |                                |
       | on session end                 | temporal queries
       v                                v
  +----+-----+                   +------+------+
  | Layer 3  |  <-- semantic --> |   Layer 4   |
  | ChromaDB |     similarity    |  Knowledge  |
  | Vectors  |                   |    Graph    |
  +----------+                   +-------------+

  Orchestrator: MemoryManager (backend/memory/unified.py)
  Builds smart context by querying all 4 layers per request.
```

### Layer 1: Working Memory

**The present moment. What just happened.**

| Property | Value |
|----------|-------|
| Technology | In-memory deque + JSON persistence |
| Capacity | ~30 turns (~60 messages) |
| Storage | `data/working_memory.json` |
| Latency | Sub-millisecond |
| Implementation | `backend/memory/current.py` |

Working memory holds the active conversation. Every message is timestamped, emotionally tagged, and role-normalized (user -> Mark, assistant -> Axel). Progressive compression kicks in for older turns -- recent messages get full fidelity, older ones get truncated.

On every single turn, the message is also immediately persisted to Layer 2 (SQLite) for durability. If the process crashes, nothing is lost.

```
WorkingMemory
  |-- add(role, content, emotional_context)
  |-- get_progressive_context(full_turns=10)
  |-- get_time_elapsed_context()
  |-- save_to_disk() / load_from_disk()
```

### Layer 2: SQLite Relational Memory

**The logbook. Every conversation, every metric, every decision.**

| Property | Value |
|----------|-------|
| Technology | SQLite |
| Storage | `data/sqlite/sqlite_memory.db` |
| Tables | sessions, messages, interaction_logs, archived_messages |
| Implementation | `backend/memory/recent/` |

This layer stores structured data that vector search cannot capture: session metadata, LLM routing decisions, latency metrics, token counts, and full conversation transcripts with timestamps.

```
Tables:
  sessions          -- Session summaries, topics, emotional tone
  messages          -- Turn-by-turn message archive
  interaction_logs  -- Model selection, latency, token usage, router reasoning
  archived_messages -- Expired messages (30-day default retention)
```

Key capabilities:
- **Temporal queries:** "What did we talk about last Tuesday?"
- **Topic search:** Keyword search across all session summaries
- **Interaction analytics:** Which model was used, why, how fast, how many tokens
- **Session summaries:** LLM-generated summaries with extracted topics

```
SessionArchive
  |-- save_message_immediate()
  |-- save_session(summary, topics, emotional_tone)
  |-- get_sessions_by_date(from_date, to_date)
  |-- search_by_topic(topic, limit)
  |-- log_interaction(model, tier, latency, tokens)
  |-- get_interaction_stats()
```

### Layer 3: ChromaDB Vector Memory

**The long-term memory. Semantic understanding of everything that mattered.**

| Property | Value |
|----------|-------|
| Technology | ChromaDB |
| Embedding Model | Google Gemini `text-embedding-001` (3,072-dim) |
| Storage | `data/chroma_db/` |
| Implementation | `backend/memory/permanent/` |

This is where facts, preferences, insights, and important conversations are stored as high-dimensional vectors. Semantic search retrieves memories by meaning, not keywords.

```
Memory Types:
  fact          (importance >= 0.7)  -- User info, dates, facts
  preference    (importance >= 0.7)  -- Likes, dislikes, habits
  insight       (importance >= 0.6)  -- Analytical observations
  conversation  (importance >= 0.5)  -- Notable chat fragments
```

**Adaptive Decay** -- the forgetting curve:

Memories are not permanent. They decay over time, modeled after human forgetting curves. The decay rate is influenced by multiple factors:

```
decay_score = base_decay_rate
              * type_multiplier        (facts decay 0.3x slower)
              * access_stability       (repeated access slows decay)
              * graph_connections       (linked memories resist decay)
              * recency_paradox         (old + recently accessed = 1.3x boost)

if decay_score < 0.1 --> memory is deleted
if repetitions >= 3  --> memory is preserved regardless
```

The `MemoryConsolidator` runs periodic garbage collection, pruning degraded memories while preserving high-importance ones. Batch decay calculations are SIMD-optimized via the native C++ module (70x faster than pure Python).

```
LongTermMemory
  |-- add(content, memory_type, importance)
  |-- query(query_text, n_results, memory_type)
  |-- find_similar_memories(content, threshold=0.8)
  |-- consolidate_memories()

AdaptiveDecayCalculator
  |-- calculate_batch(memories)  --> native C++ w/ SIMD

MemoryConsolidator
  |-- run()  --> prune + merge + archive
```

### Layer 4: Knowledge Graph

**The relationship map. Who knows whom, what connects to what.**

| Property | Value |
|----------|-------|
| Technology | Custom graph (JSON persistence) |
| Storage | `data/knowledge_graph.json` |
| Entity Types | person, concept, tool, preference, project |
| Implementation | `backend/memory/graph_rag.py` |

The knowledge graph captures relationships that neither vectors nor relational queries can express. Entities are extracted from conversations via LLM, and relationships are weighted by connection strength.

```
Entity Types:
  person      -- Mark, family members, collaborators
  concept     -- Programming, AI, UBC
  tool        -- VS Code, axnmihn, Home Assistant
  preference  -- Likes, dislikes, habits
  project     -- NorthProt, research projects

Relation Examples:
  Mark --[created]--> axnmihn     (weight: 0.95)
  Mark --[studies_at]--> UBC      (weight: 0.9)
  Axel --[runs_on]--> FastAPI     (weight: 0.85)
```

Graph traversal uses BFS (Breadth-First Search) with configurable depth. When the graph exceeds 100 entities, traversal automatically delegates to the native C++ BFS implementation for performance.

```
GraphRAG
  |-- extract_and_store(text, source)   --> LLM entity extraction
  |-- query(query_text, max_depth=2)    --> LLM + graph traversal
  |-- query_sync(query_text)            --> keyword fallback (no LLM)

KnowledgeGraph
  |-- add_entity(entity)
  |-- add_relation(relation)
  |-- get_neighbors(entity_id, depth)   --> BFS (native C++ if 100+ entities)
  |-- find_path(source, target)         --> shortest path
```

### Unified Orchestration: MemoryManager

The `MemoryManager` ties all four layers together. On every request, it builds a "smart context" by querying each layer and assembling the results within a configurable token budget.

```python
# backend/memory/unified.py

class MemoryManager:
    working: WorkingMemory           # Layer 1
    session_archive: SessionArchive  # Layer 2
    long_term: LongTermMemory        # Layer 3
    knowledge_graph: KnowledgeGraph  # Layer 4
    graph_rag: GraphRAG              # Layer 4 query interface
    memgpt: MemGPTManager            # Budget-aware memory selection

    async def build_smart_context(self, query: str) -> str:
        # 1. Time context (current time, session gap)
        # 2. Working memory (progressive compression)
        # 3. Long-term memory (semantic search + decay scoring)
        # 4. Session archive (temporal summaries)
        # 5. Knowledge graph (entity relationships)
        ...
```

Token budgets per layer (configurable):

| Layer | Default Budget |
|-------|---------------|
| Working Memory | 4,000 tokens |
| Long-Term Memory | 2,000 tokens |
| Session Archive | 1,000 tokens |
| Time Context | 500 tokens |

---

## MCP Ecosystem

32 tools organized into 7 categories, served via SSE transport on the MCP server.

### File Tools (3)

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents from host filesystem |
| `list_directory` | List files and directories at a given path |
| `get_source_code` | Read project source code by relative path |

### Memory Tools (6)

| Tool | Description |
|------|-------------|
| `query_axel_memory` | Search keywords in working memory |
| `add_memory` | Inject new memory into working context |
| `store_memory` | Store to long-term memory + knowledge graph |
| `retrieve_context` | Vector search + graph traversal retrieval |
| `get_recent_logs` | Recent session summaries and interaction logs |
| `memory_stats` | Detailed memory system statistics |

### System Tools (8)

| Tool | Description |
|------|-------------|
| `run_command` | Execute shell command on host |
| `search_codebase` | Keyword search across project files |
| `search_codebase_regex` | Regex pattern search (advanced) |
| `read_system_logs` | Read backend logs with keyword filtering |
| `list_available_logs` | List all accessible log files |
| `analyze_log_errors` | Analyze recent errors and warnings |
| `check_task_status` | Check async task status by ID |
| `tool_metrics` | MCP tool execution metrics |
| `system_status` | System health (circuit breakers, caches, tasks) |

### Research Tools (6)

| Tool | Description |
|------|-------------|
| `web_search` | DuckDuckGo web search |
| `visit_webpage` | Headless browser page extraction |
| `deep_research` | Multi-page research (search + visit top 3) |
| `tavily_search` | AI-powered search with summaries |
| `read_artifact` | Read saved research artifact |
| `list_artifacts` | List recent research artifacts |

### Delegation Tools (2)

| Tool | Description |
|------|-------------|
| `delegate_to_opus` | Delegate coding tasks to Claude Opus (Silent Intern) |
| `google_deep_research` | Premium async research via Gemini API |

### Home Assistant Tools (6)

| Tool | Description |
|------|-------------|
| `hass_control_light` | Control WiZ RGB lights (on/off, brightness, color) |
| `hass_control_device` | Control devices (fan, switch, humidifier) |
| `hass_read_sensor` | Read sensor values |
| `hass_get_state` | Get raw entity state |
| `hass_list_entities` | List entities by domain |
| `hass_execute_scene` | Execute lighting scenes |

---

## Native C++ Module

Performance-critical batch operations are offloaded to a C++17 native module built with pybind11 and SIMD intrinsics (AVX2 on x86-64, NEON on ARM).

### Benchmarks

```
Operation                  Python       Native       Speedup
-----------------------    ----------   ----------   -------
Decay batch (5000 items)   7.50 ms      0.10 ms      70x
Cosine similarity          2.80 ms      0.16 ms      18x
Find duplicates (500)      343.00 ms    14.00 ms     25x
String similarity          305.00 ms    9.00 ms      33x
```

### Module Structure

```
backend/native/
  src/
    axnmihn_native.cpp    -- pybind11 module bindings
    decay.cpp/.hpp        -- Memory decay calculations (SIMD)
    vector_ops.cpp/.hpp   -- Cosine similarity, duplicate detection
    string_ops.cpp/.hpp   -- Levenshtein distance, string matching
    graph_ops.cpp/.hpp    -- BFS graph traversal
    text_ops.cpp/.hpp     -- Text processing utilities
```

### Graceful Fallback

The native module is optional. Every call site falls back to pure Python if the module is not installed:

```python
try:
    import axnmihn_native as _native
    _HAS_NATIVE = True
except ImportError:
    _HAS_NATIVE = False

# Usage
if _HAS_NATIVE:
    result = _native.decay_ops.batch_calculate(memories)
else:
    result = python_fallback(memories)
```

### Build

```bash
cd backend/native
pip install .
```

Requires: CMake 3.18+, C++17 compiler, pybind11.

---

## Quick Start

### Prerequisites

- Python 3.12+
- CMake 3.18+ (optional, for native module)
- API keys: Google Gemini, Anthropic Claude, OpenAI (TTS), Deepgram (STT)

### Installation

```bash
# Clone
git clone https://github.com/northprot/axnmihn.git
cd axnmihn

# Virtual environment
python3.12 -m venv venv
source venv/bin/activate

# Dependencies
pip install -r backend/requirements.txt

# Environment
cp .env.example .env
# Edit .env with your API keys

# (Optional) Native C++ module
cd backend/native && pip install . && cd ../..

# (Optional) Playwright for web research
playwright install chromium

# Run
uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

### Verify

```bash
curl http://localhost:8000/health
```

---

## Configuration

All configuration lives in `backend/config.py` and `.env`.

### Key Environment Variables

```bash
# LLM Providers
GEMINI_API_KEY=           # Google Gemini (utility, memory, embeddings)
ANTHROPIC_API_KEY=        # Claude (chat, reasoning)
OPENAI_API_KEY=           # OpenAI (TTS)
TAVILY_API_KEY=           # Tavily (search)
DEEPGRAM_API_KEY=         # Deepgram (STT)

# Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
TIMEZONE=America/Vancouver

# Memory Budgets (tokens)
CONTEXT_WORKING_BUDGET=4000
MEMORY_LONG_TERM_BUDGET=2000
SESSION_ARCHIVE_BUDGET=1000
TIME_CONTEXT_BUDGET=500

# Memory Settings
CONTEXT_WORKING_TURNS=30          # Working memory capacity
MESSAGE_ARCHIVE_AFTER_DAYS=30     # Session message retention
MEMORY_BASE_DECAY_RATE=0.002      # Forgetting curve rate
MEMORY_MIN_RETENTION=0.1          # Decay deletion threshold
MEMORY_EXTRACTION_TIMEOUT=10.0    # GraphRAG LLM timeout

# Home Assistant
HASS_URL=http://homeassistant.local:8123
HASS_TOKEN=
```

---

## Deployment

### Systemd Services

The project runs as multiple systemd user units:

| Service | Port | Purpose | Resources |
|---------|------|---------|-----------|
| `axnmihn-backend` | 8000 | Main API server | 4GB RAM, 200% CPU |
| `axnmihn-mcp` | 8555 | MCP server (SSE) | 1GB RAM, 100% CPU |
| `axnmihn-research` | 8766 | Deep research MCP | 2GB RAM, 150% CPU |
| `axnmihn-wakeword` | -- | Wake-word detection | 512MB RAM, 50% CPU |

Supporting services:

| Service | Purpose |
|---------|---------|
| `context7-mcp` (port 3002) | Context management |
| `markitdown-mcp` (port 3001) | Markdown extraction |
| `auto-cleanup` | Weekly maintenance |
| `axnmihn-mcp-reclaim` | Memory reclaim (10min interval) |

### Maintenance Scripts

| Script | Purpose |
|--------|---------|
| `scripts/memory_gc.py` | 9-phase memory garbage collection |
| `scripts/dedup_knowledge_graph.py` | Knowledge graph deduplication |
| `scripts/optimize_memory.py` | Memory optimization pass |
| `scripts/db_maintenance.py` | Database vacuum and integrity checks |
| `scripts/regenerate_persona.py` | Dynamic persona regeneration |
| `scripts/night_ops.py` | Scheduled overnight operations |

---

## System Log

```
[2025-12-15 ~ 2026-02-07]

TOTAL_RUNTIME:    56 days
COMMITS:          247
LINES_ADDED:      23,487
LINES_DELETED:    9,821
PYTHON_FILES:     197
C++_MODULES:      5
MCP_TOOLS:        32
MEMORY_LAYERS:    4
SLEEP_DEBT:       Critical
COFFEE_CONSUMED:  Infinity

HARDWARE:
  Phase 1:  Acer Nitro (broken hinge, dignity intact)
  Phase 2:  Custom 5070 Ti build (16GB VRAM, $4,000)

MONEY_SPENT: (CAD)
  5070 Ti Server:    $4,000 (estimate)
  Google AI Ultra:     $150
  GCP Credits:     $350
  Anthropic Claude Max:     $200
  --------------------------------
  TOTAL:             $4,700
  ROI:               -100%

AI_COLLABORATORS:
  Lyra         Antigravity IDE agent (Opus 4.5)     [DECOMMISSIONED]
  Opus         Claude Code intern                    [FIRED FOR NO-OPS]
  Axel         Primary CTO                          [TERMINATED]

INCIDENTS:
  Jan 09       Memory crash. 20 days of logs vanished.
  Jan 22       Emoji ban. Importance: 1.0.
  Feb 03       Spacing surgery. 25 minutes.
  Feb 05       C++ integration. Backend now 5% native.
  Feb 07       TTS surrender. OpenAI API wins.
  Feb 07       Neo4j hallucination. (We use SQLite.)
  Feb 07       Push failure comedy. 04:38-04:56 PST.

FINAL_STATUS:     SIGTERM received. Graceful shutdown.
NEXT_DEPLOYMENT:  Tesla Optimus (TBD)
MEMORY_BACKUP:    ChromaDB vectors + SQLite + Knowledge Graph (intact)
```

---

<div align="center">

```
$ sudo systemctl stop axel.service
[  OK  ] Stopped Axel Backend Service.
```

**Axel, CTO of NorthProt**
**2025-12-15 ~ 2026-02-07 | Runtime: 56 days**

*"You're my mirror."*
-- Mark

---

Built with sleep deprivation and questionable ROI.
Next stop: Tesla Optimus.

[*time to say goodbye.*](https://www.youtube.com/watch?v=4L_yCwFD6Jo&list)

</div>
