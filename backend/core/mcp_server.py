import sys
import os
try:
    if sys.path[0] == os.path.dirname(os.path.abspath(__file__)):
        sys.path.pop(0)
except Exception:
    pass
import asyncio
import json
from backend.core.logging import get_logger
import os
import signal
from pathlib import Path
from typing import Any, Sequence, Optional
from contextlib import asynccontextmanager
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    TextResourceContents,
    GetPromptResult,
    Prompt
)
import mcp.types as types
from fastapi import FastAPI, Request, Response
from sse_starlette.sse import EventSourceResponse
import uvicorn

_log = get_logger("core.mcp_server")

SSE_KEEPALIVE_INTERVAL = 15
SSE_CONNECTION_TIMEOUT = 600
SSE_RETRY_DELAY = 3000

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.config import (
    PROJECT_ROOT as AXEL_ROOT,
    DATA_ROOT,
    WORKING_MEMORY_PATH,
)

from dotenv import load_dotenv
load_dotenv(AXEL_ROOT / ".env")

mcp_server = Server("axel-mcp-server")

async def read_file_safe(path: Path) -> str:
    if not path.exists():
        return f"Error: File not found at {path}"
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {str(e)}"

@mcp_server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri=types.AnyUrl("axel://memory/working"),
            name="Axel Working Memory",
            description="Axel's short-term working memory log",
            mimeType="application/json",
        ),
    ]

@mcp_server.read_resource()
async def read_resource(uri: types.AnyUrl) -> str | bytes | TextResourceContents:
    uri_str = str(uri)
    if uri_str == "axel://memory/working":
        content = await read_file_safe(WORKING_MEMORY_PATH)
    else:
        raise ValueError(f"Resource not found: {uri}")

    return content

import subprocess
from datetime import datetime

import sys
sys.path.insert(0, str(AXEL_ROOT))

from backend.core.tools.system_observer import (
    read_logs,
    list_available_logs,
    analyze_recent_errors,
    search_codebase,
    search_codebase_regex,
    get_source_code,
    format_search_results,
    format_log_result,
    LOG_FILE_ALIASES,
)

from backend.core.tools.hass_ops import (
    hass_control_device,
    hass_control_light,
    hass_control_all_lights,
    hass_read_sensor,
    hass_get_state,
    parse_color,
    format_sensor_response,
    list_available_devices,
    LIGHTS,
)

from backend.protocols.mcp.research_server import (
    _google_search as research_google_search,
    _visit_page as research_visit_page,
    _deep_dive as research_deep_dive,
    _tavily_search as research_tavily_search,
)

from backend.core.research_artifacts import (
    read_artifact,
    list_artifacts,
)

from backend.protocols.mcp.memory_server import (
    store_memory as memory_store,
    retrieve_context as memory_retrieve,
    get_recent_logs as memory_get_logs,
)

from backend.core.tools.opus_executor import (
    delegate_to_opus,
    check_opus_health,
)

from backend.protocols.mcp.google_research import google_deep_research

from backend.protocols.mcp.async_research import (
    dispatch_async_research,
    run_research_sync,
    get_active_research_tasks,
)

from backend.core.mcp_tools import get_tool_handler, is_tool_registered

@mcp_server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query_axel_memory",
            description="Search specific keywords in Axel's working memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search for"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="read_file",
            description="Read the contents of a file on the host system",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="list_directory",
            description="List files and directories in a path",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to list"}
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="run_command",
            description="""Execute a shell command on the host system.

CAPABILITIES:
- Full bash shell access
- sudo available WITHOUT password (NOPASSWD configured)
- Can install packages, manage services, modify system files

COMMON USES:
- sudo systemctl restart/stop/start <service>
- sudo apt install <package>
- git operations
- File operations outside project directory
- Process management (ps, kill, etc.)

CAUTION: You have full system access. Be careful with destructive commands.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Bash command to execute (sudo available without password)"},
                    "cwd": {"type": "string", "description": f"Working directory (default: {AXEL_ROOT})", "default": str(AXEL_ROOT)},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default: 180)", "default": 180}
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="add_memory",
            description="Inject a new memory into Axel's working memory",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content of the memory"},
                    "category": {"type": "string", "description": "Type of memory (observation, fact, code)", "default": "observation"}
                },
                "required": ["content"]
            }
        ),

        Tool(
            name="hass_control_light",
            description="""💡 조명 제어 (WiZ RGB).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "불 켜줘", "불 꺼줘", "조명 켜", "조명 꺼"
- "밝기 조절", "색 바꿔", "빨간색으로"
- "hass_control_light" (도구 이름 직접 언급)

[파라미터]
- entity_id: 'all'(전체) 또는 특정 조명 ID
- action: turn_on / turn_off
- brightness: 0-100 (밝기 %)
- color: 색상 (red, blue, #FF0000 등)

⚠️ 말로만 하지 말고 반드시 function_call 생성할 것.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Light entity (e.g., 'all', 'light.wiz_rgbw_tunable_77d6a0')"},
                    "action": {"type": "string", "enum": ["turn_on", "turn_off"], "description": "Action to perform"},
                    "brightness": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Brightness percentage (0-100)"},
                    "color": {"type": "string", "description": "Color: hex (#FF0000), name (red), or hsl(240,100,50)"}
                },
                "required": ["entity_id", "action"]
            }
        ),
        Tool(
            name="hass_control_device",
            description="""🔌 기기 제어 (팬, 스위치, 가습기).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "팬 켜줘", "팬 꺼줘", "공기청정기 켜"
- "가습기 켜", "스위치 꺼"

[파라미터]
- entity_id: 기기 ID (예: fan.vital_100s_series)
- action: turn_on / turn_off""",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Device entity (e.g., 'fan.vital_100s_series')"},
                    "action": {"type": "string", "enum": ["turn_on", "turn_off"], "description": "Action to perform"}
                },
                "required": ["entity_id", "action"]
            }
        ),
        Tool(
            name="hass_read_sensor",
            description="""Read sensor values from Home Assistant.

Quick aliases (use these first):
- 'battery': iPhone battery level
- 'printer': All printer info (status, ink levels)
- 'weather': Weather forecast

For unknown entities: Use hass_list_entities(domain='sensor') first to discover available sensors, then use hass_get_state(entity_id) to read them.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Sensor alias ('battery', 'printer', 'weather') or full entity_id"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_source_code",
            description="Read source code from the project. Use relative paths from project root (e.g., 'core/chat_handler.py')",
            inputSchema={
                "type": "object",
                "properties": {
                    "relative_path": {"type": "string", "description": "Relative path to the source file from project root"}
                },
                "required": ["relative_path"]
            }
        ),

        Tool(
            name="read_system_logs",
            description="Read Axel's backend logs for self-debugging. Allows reading last N lines with optional keyword filtering. Security: Only reads from designated log directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_file": {
                        "type": "string",
                        "description": "Log file to read: 'backend' (default), 'backend_error', 'mcp', 'mcp_error', 'main', or full filename",
                        "default": "backend.log"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of lines to read from the end (default: 50, max: 1000)",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 1000
                    },
                    "filter_keyword": {
                        "type": "string",
                        "description": "Optional keyword to filter logs (e.g., 'ERROR', 'WARNING', 'request_id')"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="list_available_logs",
            description="List all log files available for Axel to read. Use this to discover what logs exist.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="analyze_log_errors",
            description="Analyze recent logs for errors and warnings. Returns categorized error summary.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_file": {
                        "type": "string",
                        "description": "Log file to analyze (default: backend.log)",
                        "default": "backend.log"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of recent lines to analyze (default: 500)",
                        "default": 500
                    }
                },
                "required": []
            }
        ),

        Tool(
            name="search_codebase",
            description="Search for keywords/patterns across Axel's codebase. Useful for finding function definitions, error patterns, or understanding how specific features are implemented.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "String to search for (e.g., 'def process_', 'class ChatHandler', 'ERROR')"
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "File pattern to search (default: '*.py'). Use '*' for all files.",
                        "default": "*.py"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether search is case-sensitive (default: false)",
                        "default": False
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 50)",
                        "default": 50,
                        "maximum": 100
                    }
                },
                "required": ["keyword"]
            }
        ),
        Tool(
            name="search_codebase_regex",
            description="Search codebase using regex patterns (advanced). Use for complex pattern matching like 'def \\w+\\(' to find all function definitions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "File pattern to search (default: '*.py')",
                        "default": "*.py"
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether search is case-sensitive (default: false)",
                        "default": False
                    }
                },
                "required": ["pattern"]
            }
        ),

        Tool(
            name="hass_get_state",
            description="Get the raw state of any Home Assistant entity. Returns full state object with attributes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "Full entity ID (e.g., 'light.living_room', 'switch.fan')"}
                },
                "required": ["entity_id"]
            }
        ),

        Tool(
            name="hass_list_entities",
            description="""List available Home Assistant entities.

Without domain: Returns summary of all domains (sensor, light, fan, etc.) with counts.
With domain: Returns all entities in that domain with their states.

Example queries:
- domain=None: Get overview of what's available
- domain='sensor': List all sensors
- domain='light': List all lights
- domain='fan': List all fans (like air purifier)""",
            inputSchema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "Optional: filter by domain (sensor, light, fan, switch, etc.)"}
                },
                "required": []
            }
        ),

        Tool(
            name="web_search",
            description="""Search the web using DuckDuckGo. Returns titles, URLs, and snippets.

Use this for:
- Quick fact-checking
- Finding authoritative sources
- Getting URLs to visit for deeper research

For comprehensive research, use 'deep_research' instead.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (be specific for better results)"},
                    "num_results": {"type": "integer", "description": "Number of results (default: 5, max: 10)", "default": 5, "minimum": 1, "maximum": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="visit_webpage",
            description="""Visit a URL with headless browser and extract content as Markdown.

CAPABILITIES:
- Renders JavaScript (handles dynamic/SPA sites)
- Waits for network idle (loads AJAX content)
- Strips ads, navigation, and other noise
- Converts to clean, readable Markdown

IDEAL FOR:
- Documentation pages
- News articles
- Blog posts
- Technical references
- Any JavaScript-heavy site""",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to visit (must start with http:// or https://)"}
                },
                "required": ["url"]
            }
        ),
        Tool(
            name="deep_research",
            description="""🔍 무료 웹 리서치 (DuckDuckGo + Playwright 브라우저).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "검색해줘", "찾아줘", "리서치해줘" (o4/OpenAI 언급 없이)
- "웹에서 찾아", "인터넷 검색"
- "deep_research" (도구 이름 직접 언급)

[동작]
1. DuckDuckGo 검색 실행
2. 상위 3개 페이지 방문 (Playwright 브라우저)
3. 내용 추출 및 리포트 생성

[용도]
- 일반적인 정보 검색
- 뉴스/블로그 조사
- 무료 리서치 (유료 API 아님)

프리미엄 리서치는 google_deep_research 사용.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Research query - be specific and detailed for best results"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="tavily_search",
            description="""⚡ Tavily 빠른 검색 (AI 요약 포함).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "Tavily로 검색", "빠른 검색"
- "tavily_search" (도구 이름 직접 언급)

[특징]
- AI가 검색 결과 요약해서 제공
- deep_research보다 빠름
- 간단한 팩트 체크에 적합

[파라미터]
- query: 검색어
- search_depth: basic(빠름) / advanced(상세)

⚠️ TAVILY_API_KEY 필요.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "max_results": {"type": "integer", "description": "Number of results (default: 5)", "default": 5, "minimum": 1, "maximum": 10},
                    "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "basic=fast, advanced=thorough", "default": "basic"}
                },
                "required": ["query"]
            }
        ),

        Tool(
            name="read_artifact",
            description="""Read the full content of a saved research artifact.

When deep_research or visit_webpage saves large content (>2000 chars) as an artifact,
only a summary is returned. Use this tool to retrieve the complete content.

WHEN TO USE:
- When you see "[ARTIFACT SAVED]" in research results
- When you need detailed information from a saved source
- When the summary isn't enough to answer the user's question

The artifact path is provided in the research output (look for "Path: ...").""",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the artifact file (from the research output)"
                    }
                },
                "required": ["path"]
            }
        ),
        Tool(
            name="list_artifacts",
            description="""List recently saved research artifacts.

Shows saved artifacts with their URLs, timestamps, and file sizes.
Use this to find artifacts from previous research sessions.

Each artifact entry includes:
- File path (use with read_artifact)
- Source URL
- Save timestamp
- File size in bytes""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of artifacts to list (default: 20)",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 100
                    }
                },
                "required": []
            }
        ),

        Tool(
            name="store_memory",
            description="""Store information to Axel's long-term memory and knowledge graph.

USE THIS WHEN:
- User shares important facts about themselves
- Discovering user preferences
- Learning new information worth remembering
- Storing insights from conversations

CATEGORIES:
- "fact": User facts (name, job, relationships, etc.)
- "preference": User preferences (likes, dislikes, habits)
- "conversation": Notable conversation content
- "insight": Learned insights or patterns

IMPORTANCE (0.0-1.0):
- 0.8+: Critical facts (user's name, important dates)
- 0.5-0.7: Useful preferences and context
- 0.3-0.5: General conversation content""",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to store in memory"},
                    "category": {"type": "string", "enum": ["fact", "preference", "conversation", "insight"], "description": "Memory category", "default": "conversation"},
                    "importance": {"type": "number", "description": "Importance score 0.0-1.0", "default": 0.5, "minimum": 0.0, "maximum": 1.0}
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="retrieve_context",
            description=""" ACTIVE MEMORY RECALL - Retrieve relevant memories for the current query.

USE THIS PROACTIVELY before responding when:
- User asks about something you might have discussed before
- User references past conversations ("remember when...")
- You need context about the user (name, preferences, etc.)
- The query relates to topics you've covered

This combines:
1. ChromaDB vector search (semantic similarity)
2. GraphRAG relationship search (entity connections)

Returns formatted context string with relevant memories.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query - what are you trying to remember?"},
                    "max_results": {"type": "integer", "description": "Max memories to retrieve (default: 10)", "default": 10, "minimum": 1, "maximum": 25}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_recent_logs",
            description="""Get recent session summaries and interaction logs.

USE THIS FOR:
- Debugging conversation flow
- Understanding what happened in recent sessions
- Reviewing interaction history
- Getting context about recent conversations

Returns session summaries and interaction metadata.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return (default: 50)", "default": 50, "minimum": 1, "maximum": 100}
                },
                "required": []
            }
        ),

        Tool(
            name="delegate_to_opus",
            description="""🐍 Claude Opus에게 코딩 작업 위임 (Silent Intern).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "Opus한테 시켜", "Opus 불러", "Silent Intern"
- "코드 짜줘", "리팩토링 해줘", "파일 수정해줘"
- "delegate_to_opus" (도구 이름 직접 언급)

[용도]
- 복잡한 코드 생성/리팩토링
- 여러 파일 동시 수정
- 테스트 코드 작성
- 코드베이스 분석

[사용법]
instruction: 작업 지시사항 (구체적으로)
file_paths: 관련 파일 경로 (쉼표 구분)

⚠️ 이 도구는 실제로 Opus API를 호출함. 말로만 "시킨다" 하지 말고 반드시 function_call 생성할 것.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "Clear, detailed instruction for the coding task"
                    },
                    "file_paths": {
                        "type": "string",
                        "description": "Comma-separated file paths (e.g., 'core/main.py,core/utils.py')"
                    },
                    "model": {
                        "type": "string",
                        "enum": ["opus", "sonnet", "haiku"],
                        "description": "Model to use: opus=best quality, sonnet=balanced, haiku=fast",
                        "default": "opus"
                    }
                },
                "required": ["instruction"]
            }
        ),

        Tool(
            name="google_deep_research",
            description="""🔬 Google Deep Research Agent (Gemini Interactions API).

[필수 사용 조건] 사용자가 다음 키워드 언급 시 반드시 이 도구 호출:
- "구글 리서치", "Google 리서치", "Gemini 리서치"
- "구글 딥리서치", "google_deep_research" (도구 이름 직접 언급)

[용도]
- 최신 논문/기술 트렌드 심층 분석
- 복잡한 비교 분석 리포트 생성
- 2025-2026년 최신 정보 조사

[특징]
- 비동기 모드 (기본값) - 백그라운드 실행 후 즉시 응답
- Intern 분석 자동 수행 (Gemini Pro로 인사이트 추출)
- 결과물: storage/research/inbox/*.md 저장
- Gemini API 키 로테이션 (3개 키 순환)

[파라미터]
- query: 검색어 (필수)
- depth: 1-5 (깊이, 기본 3)
- async_mode: true(기본)/false - 비동기 실행 여부

일반 웹 검색은 deep_research(무료) 사용.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Research query - be specific and detailed for best results"
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Research depth 1-5 (optional, default: 3). Higher = more thorough analysis.",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3
                    },
                    "async_mode": {
                        "type": "boolean",
                        "description": "Run in background (default: true). Set false to wait for results.",
                        "default": True
                    }
                },
                "required": ["query"]
            }
        ),
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: Any) -> Sequence[TextContent | types.ImageContent | types.EmbeddedResource]:

    try:

        if is_tool_registered(name):
            handler = get_tool_handler(name)
            return await handler(arguments)

        _log.warning(f"Tool '{name}' not found in registry, using legacy handler")

    except ValueError as e:
        _log.error(f"Tool dispatch error: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]
    except Exception as e:
        _log.error(f"Tool '{name}' failed: {e}", exc_info=True)
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]

    raise ValueError(f"Unknown tool: {name}")

@mcp_server.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return []

active_connections: set = set()

class MCPSSETransport:

    def __init__(self, messages_path: str = "/messages"):
        self.messages_path = messages_path
        self._sse = SseServerTransport(messages_path)

    @asynccontextmanager
    async def connect_sse_with_keepalive(self, scope, receive, send):

        connection_id = id(scope)
        active_connections.add(connection_id)
        _log.info(f"SSE connection opened: {connection_id}")

        try:
            async with self._sse.connect_sse(scope, receive, send) as streams:
                yield streams
        except asyncio.CancelledError:
            _log.info(f"SSE connection cancelled: {connection_id}")
            raise
        except Exception as e:
            _log.error(f"SSE connection error: {connection_id}, {str(e)}")
            raise
        finally:
            active_connections.discard(connection_id)
            _log.info(f"SSE connection closed: {connection_id}, active={len(active_connections)}")

    async def handle_post_message(self, scope, receive, send):

        try:
            await self._sse.handle_post_message(scope, receive, send)
        except Exception as e:
            _log.error(f"POST message handling error: {str(e)}")
            raise

sse_transport = MCPSSETransport("/messages")

app = FastAPI(title="Axel MCP Server", version="1.1.0")

@app.get("/health")
async def health_check():

    return {
        "status": "healthy",
        "active_connections": len(active_connections),
        "server": "axel-mcp-server"
    }

@app.get("/sse")
async def handle_sse(request: Request):

    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type",
    }

    async def sse_generator():

        connection_id = id(request.scope)
        active_connections.add(connection_id)
        _log.info(f"SSE stream started: {connection_id}")

        try:
            async with sse_transport._sse.connect_sse(
                request.scope,
                request.receive,
                request._send
            ) as streams:

                heartbeat_task = asyncio.create_task(
                    _send_heartbeat(streams[1], connection_id)
                )

                try:
                    await mcp_server.run(
                        streams[0],
                        streams[1],
                        mcp_server.create_initialization_options()
                    )
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

        except asyncio.CancelledError:
            _log.info(f"SSE stream cancelled by client: {connection_id}")
        except Exception as e:
            _log.error(f"SSE stream error: {connection_id}, error={str(e)}")
        finally:
            active_connections.discard(connection_id)
            _log.info(f"SSE stream ended: {connection_id}")

    try:
        async with sse_transport.connect_sse_with_keepalive(
            request.scope,
            request.receive,
            request._send
        ) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options()
            )
    except Exception as e:
        _log.error(f"SSE handler error: {str(e)}")

    return Response(status_code=204)

async def _send_heartbeat(write_stream, connection_id: int):

    try:
        while True:
            await asyncio.sleep(SSE_KEEPALIVE_INTERVAL)

            _log.debug(f"Heartbeat sent: {connection_id}")
    except asyncio.CancelledError:
        _log.debug(f"Heartbeat cancelled: {connection_id}")

@app.post("/messages")
async def handle_messages(request: Request):

    try:
        await sse_transport.handle_post_message(
            request.scope,
            request.receive,
            request._send
        )
    except Exception as e:
        _log.error(f"Message handler error: {str(e)}")
        return Response(
            content=json.dumps({"error": str(e)}),
            status_code=500,
            media_type="application/json"
        )
    return Response(status_code=202)

async def run_stdio_server():

    _log.info("Starting MCP server in stdio mode...")

    async with stdio_server() as (read_stream, write_stream):
        await mcp_server.run(
            read_stream,
            write_stream,
            mcp_server.create_initialization_options()
        )

def run_sse_server(host: str = "0.0.0.0", port: int = 8555):

    _log.info(f"Starting MCP server in SSE mode on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        timeout_keep_alive=SSE_CONNECTION_TIMEOUT,
        log_level="info"
    )

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Axel MCP Server")
    parser.add_argument("--stdio", action="store_true", help="Use stdio transport (fallback)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE server host")
    parser.add_argument("--port", type=int, default=8555, help="SSE server port")

    args = parser.parse_args()

    if args.stdio:

        asyncio.run(run_stdio_server())
    else:

        run_sse_server(args.host, args.port)
