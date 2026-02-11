import os
from dotenv import load_dotenv
from backend.core.logging import get_logger
_log = get_logger("config")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

APP_VERSION = os.getenv("AXNMIHN_VERSION", "1.0")

DEFAULT_GEMINI_MODEL = os.getenv("DEFAULT_GEMINI_MODEL", "gemini-3-flash-preview")
DEFAULT_THINKING_LEVEL = "high"

# Chat response model (separate from utility tasks)
CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-3-flash-preview")
CHAT_THINKING_LEVEL = "high"

MODEL_NAME = CHAT_MODEL
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "3072"))

# Anthropic Chat Model (primary chat provider)
ANTHROPIC_CHAT_MODEL = os.getenv("ANTHROPIC_CHAT_MODEL", "claude-sonnet-4-5-20250929")
ANTHROPIC_THINKING_BUDGET = int(os.getenv("ANTHROPIC_THINKING_BUDGET", "10000"))

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "tavily")

DEEP_SEARCH_ENABLED = os.getenv("DEEP_SEARCH_ENABLED", "True").lower() == "true"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

TIMEZONE = os.getenv("TZ", "America/Vancouver")

AXNMIHN_API_KEY = os.getenv("AXNMIHN_API_KEY") or os.getenv("API_KEY")

CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "")

def get_cors_origins() -> list:
    """Get allowed CORS origins from environment or defaults.

    Returns:
        List of allowed origin URLs
    """
    if CORS_ALLOW_ORIGINS:
        return [origin.strip() for origin in CORS_ALLOW_ORIGINS.split(",") if origin.strip()]
    return [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
BACKEND_ROOT = Path(__file__).parent.resolve()

DATA_ROOT = PROJECT_ROOT / "data"
TEMP_DIR = DATA_ROOT / "tmp"

WORKING_MEMORY_PATH = DATA_ROOT / "working_memory.json"
SQLITE_MEMORY_PATH = DATA_ROOT / "sqlite" / "sqlite_memory.db"
CHROMADB_PATH = DATA_ROOT / "chroma_db"
KNOWLEDGE_GRAPH_PATH = DATA_ROOT / "knowledge_graph.json"

PERSONA_PATH = DATA_ROOT / "dynamic_persona.json"

STORAGE_ROOT = PROJECT_ROOT / "storage"

RESEARCH_INBOX_DIR = STORAGE_ROOT / "research" / "inbox"
RESEARCH_ARTIFACTS_DIR = STORAGE_ROOT / "research" / "artifacts"
RESEARCH_LOG_PATH = STORAGE_ROOT / "research" / "log.md"

CRON_REPORTS_DIR = STORAGE_ROOT / "cron" / "reports"
CRON_LOG_PATH = STORAGE_ROOT / "cron" / "log.md"

SYSTEM_PROMPT_FILE = str(PERSONA_PATH)
LOGS_DIR = PROJECT_ROOT / "logs"

def ensure_data_directories() -> None:
    """Create required data directories if they don't exist."""
    directories = [
        DATA_ROOT,
        TEMP_DIR,
        CHROMADB_PATH,
        STORAGE_ROOT,
        RESEARCH_INBOX_DIR,
        RESEARCH_ARTIFACTS_DIR,
        CRON_REPORTS_DIR,
        LOGS_DIR,
    ]

    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            _log.warning("Failed to create directory", path=str(directory), error=str(e))

ALLOWED_TEXT_EXTENSIONS = ['.py', '.js', '.json', '.txt', '.md', '.html', '.css', '.csv', '.ts', '.tsx']

ALLOWED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp']

def _get_size_bytes(bytes_env: str, mb_env: str, default_mb: int) -> int:
    """Get size in bytes from environment variable.

    Checks bytes_env first, then mb_env (converted to bytes).

    Args:
        bytes_env: Environment variable name for bytes value
        mb_env: Environment variable name for megabytes value
        default_mb: Default size in megabytes if neither env is set

    Returns:
        Size in bytes
    """
    raw_bytes = os.getenv(bytes_env)
    if raw_bytes:
        try:
            return max(0, int(raw_bytes))
        except ValueError:
            _log.warning("Invalid size env", env=bytes_env, value=raw_bytes)
    raw_mb = os.getenv(mb_env)
    if raw_mb:
        try:
            return max(0, int(float(raw_mb) * 1024 * 1024))
        except ValueError:
            _log.warning("Invalid size env", env=mb_env, value=raw_mb)
    return default_mb * 1024 * 1024

MAX_UPLOAD_BYTES = _get_size_bytes("MAX_UPLOAD_BYTES", "MAX_UPLOAD_MB", 25)
MAX_AUDIO_BYTES = _get_size_bytes("MAX_AUDIO_BYTES", "MAX_AUDIO_MB", 25)
MAX_ATTACHMENT_BYTES = _get_size_bytes("MAX_ATTACHMENT_BYTES", "MAX_ATTACHMENT_MB", 25)

def _get_int_env(name: str, default: int) -> int:
    """Get integer value from environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Integer value from env or default
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        _log.warning("Invalid int env", env=name, value=raw)
        return default

# PostgreSQL backend (set DATABASE_URL to enable PG mode, unset to keep SQLite/ChromaDB)
DATABASE_URL = os.getenv("DATABASE_URL")  # e.g. postgresql://axel:pass@localhost:5432/axel
PG_POOL_MIN = _get_int_env("PG_POOL_MIN", 2)
PG_POOL_MAX = _get_int_env("PG_POOL_MAX", 10)

# Context section budgets (chars). 30-turn working memory baseline.
#   working: 30 turns × 2 msgs × ~2K chars ≈ 120K, with headroom
#   long_term: ChromaDB top-20 × ~500 chars + metadata
#   graphrag: entity/relation context, usually compact
BUDGET_SYSTEM_PROMPT = _get_int_env("BUDGET_SYSTEM_PROMPT", 20_000)
BUDGET_TEMPORAL = _get_int_env("BUDGET_TEMPORAL", 5_000)
BUDGET_WORKING_MEMORY = _get_int_env("BUDGET_WORKING_MEMORY", 80_000)
BUDGET_LONG_TERM = _get_int_env("BUDGET_LONG_TERM", 30_000)
BUDGET_GRAPHRAG = _get_int_env("BUDGET_GRAPHRAG", 12_000)
BUDGET_SESSION_ARCHIVE = _get_int_env("BUDGET_SESSION_ARCHIVE", 8_000)

# Legacy token-based aliases (chars / 4) used by memgpt budget_select
# Also includes session archive alias
MEMORY_LONG_TERM_BUDGET = BUDGET_LONG_TERM // 4
MEMORY_TIME_CONTEXT_BUDGET = BUDGET_TEMPORAL // 4
MEMORY_SESSION_ARCHIVE_BUDGET = BUDGET_SESSION_ARCHIVE // 4
CONTEXT_IO_TIMEOUT: float = float(os.getenv("CONTEXT_IO_TIMEOUT", "10.0"))

MAX_CONTEXT_TOKENS = (
    BUDGET_WORKING_MEMORY +
    BUDGET_LONG_TERM +
    BUDGET_TEMPORAL +
    BUDGET_SYSTEM_PROMPT +
    BUDGET_GRAPHRAG
) // 4

MAX_RESEARCH_CONTENT_TOKENS = _get_int_env("MAX_RESEARCH_CONTENT_TOKENS", 150000)

MAX_MEMORY_CONTEXT_CHARS = {
    "axel": _get_int_env("MAX_MEMORY_CONTEXT_CHARS_AXEL", 1_000_000),
}

MAX_SEARCH_CONTEXT_CHARS = _get_int_env("MAX_SEARCH_CONTEXT_CHARS", 300_000)
MAX_CODE_CONTEXT_CHARS = _get_int_env("MAX_CODE_CONTEXT_CHARS", 300_000)
MAX_CODE_FILE_CHARS = _get_int_env("MAX_CODE_FILE_CHARS", 300_000)

# Context building configuration
CONTEXT_WORKING_TURNS = _get_int_env("CONTEXT_WORKING_TURNS", 20)
CONTEXT_FULL_TURNS = _get_int_env("CONTEXT_FULL_TURNS", 6)
CONTEXT_MAX_CHARS = _get_int_env("CONTEXT_MAX_CHARS", 500_000)

def _get_float_env(name: str, default: float) -> float:
    """Get float value from environment variable.

    Args:
        name: Environment variable name
        default: Default value if not set or invalid

    Returns:
        Float value from env or default
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        _log.warning("Invalid float env", env=name, value=raw)
        return default

MEMORY_BASE_DECAY_RATE = _get_float_env("MEMORY_BASE_DECAY_RATE", 0.001)
MEMORY_MIN_RETENTION = _get_float_env("MEMORY_MIN_RETENTION", 0.3)
MEMORY_DECAY_DELETE_THRESHOLD = _get_float_env("MEMORY_DECAY_DELETE_THRESHOLD", 0.03)
MEMORY_SIMILARITY_THRESHOLD = _get_float_env("MEMORY_SIMILARITY_THRESHOLD", 0.90)
MEMORY_MIN_IMPORTANCE = _get_float_env("MEMORY_MIN_IMPORTANCE", 0.55)

# Message archival settings
MESSAGE_ARCHIVE_AFTER_DAYS = _get_int_env("MESSAGE_ARCHIVE_AFTER_DAYS", 7)
MESSAGE_SUMMARY_MODEL = DEFAULT_GEMINI_MODEL

# =============================================================================
# Research & Web Scraping
# =============================================================================
RESEARCH_PAGE_TIMEOUT_MS = _get_int_env("RESEARCH_PAGE_TIMEOUT_MS", 15000)
RESEARCH_NAVIGATION_TIMEOUT_MS = _get_int_env("RESEARCH_NAVIGATION_TIMEOUT_MS", 30000)
RESEARCH_MAX_CONTENT_LENGTH = _get_int_env("RESEARCH_MAX_CONTENT_LENGTH", 75000)
RESEARCH_POLL_INTERVAL = _get_int_env("RESEARCH_POLL_INTERVAL", 30)
RESEARCH_MAX_POLL_TIME = _get_int_env("RESEARCH_MAX_POLL_TIME", 1800)

# =============================================================================
# MCP Tool Visibility (affects MCP schema only, not internal callers)
# =============================================================================
MCP_DISABLED_TOOLS: set[str] = set(
    filter(None, os.getenv("MCP_DISABLED_TOOLS", "").split(","))
)
MCP_DISABLED_CATEGORIES: set[str] = set(
    filter(None, os.getenv("MCP_DISABLED_CATEGORIES", "").split(","))
)

# =============================================================================
# MCP Tool Execution
# =============================================================================
MCP_MAX_TOOL_RETRIES = _get_int_env("MCP_MAX_TOOL_RETRIES", 3)
MCP_TOOL_RETRY_DELAY = _get_float_env("MCP_TOOL_RETRY_DELAY", 0.5)
MCP_MAX_TOOLS = _get_int_env("MCP_MAX_TOOLS", 13)

# =============================================================================
# Home Assistant
# =============================================================================
HASS_TIMEOUT = _get_float_env("HASS_TIMEOUT", 10.0)
HASS_MAX_RETRIES = _get_int_env("HASS_MAX_RETRIES", 2)

# =============================================================================
# Opus Bridge
# =============================================================================
OPUS_DEFAULT_MODEL = os.getenv("OPUS_DEFAULT_MODEL", "opus")
OPUS_COMMAND_TIMEOUT = _get_int_env("OPUS_COMMAND_TIMEOUT", 600)

# =============================================================================
# Context Building
# =============================================================================
CONTEXT_SQL_PERSIST_TURNS = _get_int_env("CONTEXT_SQL_PERSIST_TURNS", 10)

# =============================================================================
# Memory Extraction
# =============================================================================
MEMORY_EXTRACTION_TIMEOUT = _get_int_env("MEMORY_EXTRACTION_TIMEOUT", 120)

# =============================================================================
# Timeouts (canonical source — replaces timeouts.py hardcoded values)
# =============================================================================
TIMEOUT_API_CALL = _get_int_env("TIMEOUT_API_CALL", 180)
TIMEOUT_STREAM_CHUNK = _get_int_env("TIMEOUT_STREAM_CHUNK", 60)
TIMEOUT_FIRST_CHUNK_BASE = _get_int_env("TIMEOUT_FIRST_CHUNK_BASE", 100)
TIMEOUT_MCP_TOOL = _get_int_env("TIMEOUT_MCP_TOOL", 300)
TIMEOUT_DEEP_RESEARCH = _get_int_env("TIMEOUT_DEEP_RESEARCH", 600)
TIMEOUT_HTTP_DEFAULT = _get_float_env("TIMEOUT_HTTP_DEFAULT", 30.0)
TIMEOUT_HTTP_CONNECT = _get_float_env("TIMEOUT_HTTP_CONNECT", 5.0)

# =============================================================================
# SSE Configuration
# =============================================================================
SSE_KEEPALIVE_INTERVAL = _get_int_env("SSE_KEEPALIVE_INTERVAL", 15)
SSE_CONNECTION_TIMEOUT = _get_int_env("SSE_CONNECTION_TIMEOUT", 600)
SSE_RETRY_DELAY = _get_int_env("SSE_RETRY_DELAY", 3000)

# =============================================================================
# Retry Configuration
# =============================================================================
GEMINI_MAX_RETRIES = _get_int_env("GEMINI_MAX_RETRIES", 5)
GEMINI_RETRY_DELAY_BASE = _get_float_env("GEMINI_RETRY_DELAY_BASE", 2.0)
STREAM_MAX_RETRIES = _get_int_env("STREAM_MAX_RETRIES", 5)
EMBEDDING_MAX_RETRIES = _get_int_env("EMBEDDING_MAX_RETRIES", 3)

# =============================================================================
# File / Search Limits
# =============================================================================
MAX_FILE_SIZE = _get_size_bytes("MAX_FILE_SIZE", "MAX_FILE_SIZE_MB", 10)
MAX_LOG_LINES = _get_int_env("MAX_LOG_LINES", 1000)
MAX_SEARCH_RESULTS = _get_int_env("MAX_SEARCH_RESULTS", 100)

# =============================================================================
# ReAct Loop Defaults
# =============================================================================
REACT_MAX_LOOPS = _get_int_env("REACT_MAX_LOOPS", 15)
REACT_DEFAULT_TEMPERATURE = _get_float_env("REACT_DEFAULT_TEMPERATURE", 0.7)
REACT_DEFAULT_MAX_TOKENS = _get_int_env("REACT_DEFAULT_MAX_TOKENS", 16384)

# =============================================================================
# Shutdown Timeouts
# =============================================================================
SHUTDOWN_TASK_TIMEOUT = _get_float_env("SHUTDOWN_TASK_TIMEOUT", 3.0)
SHUTDOWN_SESSION_TIMEOUT = _get_float_env("SHUTDOWN_SESSION_TIMEOUT", 3.0)
SHUTDOWN_HTTP_POOL_TIMEOUT = _get_float_env("SHUTDOWN_HTTP_POOL_TIMEOUT", 2.0)

# =============================================================================
# TTS Configuration
# =============================================================================
TTS_SYNTHESIS_TIMEOUT = _get_float_env("TTS_SYNTHESIS_TIMEOUT", 30.0)
TTS_FFMPEG_TIMEOUT = _get_float_env("TTS_FFMPEG_TIMEOUT", 10.0)
TTS_QUEUE_MAX_PENDING = _get_int_env("TTS_QUEUE_MAX_PENDING", 3)
TTS_IDLE_TIMEOUT = _get_int_env("TTS_IDLE_TIMEOUT", 300)
TTS_SERVICE_URL = os.getenv("TTS_SERVICE_URL", "")
