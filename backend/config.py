import os
from dotenv import load_dotenv
from backend.core.logging import get_logger
_logger = get_logger("config")

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

APP_VERSION = os.getenv("AXNMIHN_VERSION", "1.0")

MODEL_NAME = os.getenv("LLM_MODEL", "gemini-3-flash-preview")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "tavily")

DEEP_SEARCH_ENABLED = os.getenv("DEEP_SEARCH_ENABLED", "True").lower() == "true"

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

TIMEZONE = os.getenv("TZ", "America/Vancouver")

AXNMIHN_API_KEY = os.getenv("AXNMIHN_API_KEY") or os.getenv("API_KEY")

CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "")

def get_cors_origins() -> list:

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

    directories = [
        DATA_ROOT,
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
            _logger.warning("Failed to create directory", path=str(directory), error=str(e))

ALLOWED_TEXT_EXTENSIONS = ['.py', '.js', '.json', '.txt', '.md', '.html', '.css', '.csv', '.ts', '.tsx']

ALLOWED_IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.webp']

def _get_size_bytes(bytes_env: str, mb_env: str, default_mb: int) -> int:

    raw_bytes = os.getenv(bytes_env)
    if raw_bytes:
        try:
            return max(0, int(raw_bytes))
        except ValueError:
            _logger.warning("Invalid size env", env=bytes_env, value=raw_bytes)
    raw_mb = os.getenv(mb_env)
    if raw_mb:
        try:
            return max(0, int(float(raw_mb) * 1024 * 1024))
        except ValueError:
            _logger.warning("Invalid size env", env=mb_env, value=raw_mb)
    return default_mb * 1024 * 1024

MAX_UPLOAD_BYTES = _get_size_bytes("MAX_UPLOAD_BYTES", "MAX_UPLOAD_MB", 25)
MAX_AUDIO_BYTES = _get_size_bytes("MAX_AUDIO_BYTES", "MAX_AUDIO_MB", 25)
MAX_ATTACHMENT_BYTES = _get_size_bytes("MAX_ATTACHMENT_BYTES", "MAX_ATTACHMENT_MB", 25)

def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning("Invalid int env", env=name, value=raw)
        return default

MEMORY_WORKING_BUDGET = _get_int_env("MEMORY_WORKING_BUDGET", 150000)
MEMORY_LONG_TERM_BUDGET = _get_int_env("MEMORY_LONG_TERM_BUDGET", 120000)
MEMORY_SESSION_ARCHIVE_BUDGET = _get_int_env("MEMORY_SESSION_ARCHIVE_BUDGET", 90000)
MEMORY_TIME_CONTEXT_BUDGET = _get_int_env("MEMORY_TIME_CONTEXT_BUDGET", 15000)

MAX_CONTEXT_TOKENS = (
    MEMORY_WORKING_BUDGET +
    MEMORY_LONG_TERM_BUDGET +
    MEMORY_SESSION_ARCHIVE_BUDGET +
    MEMORY_TIME_CONTEXT_BUDGET
)

MAX_RESEARCH_CONTENT_TOKENS = _get_int_env("MAX_RESEARCH_CONTENT_TOKENS", 150000)

MAX_MEMORY_CONTEXT_CHARS = {
    "axel": _get_int_env("MAX_MEMORY_CONTEXT_CHARS_AXEL", 2_000_000),
}

MAX_SEARCH_CONTEXT_CHARS = _get_int_env("MAX_SEARCH_CONTEXT_CHARS", 300_000)
MAX_CODE_CONTEXT_CHARS = _get_int_env("MAX_CODE_CONTEXT_CHARS", 300_000)
MAX_CODE_FILE_CHARS = _get_int_env("MAX_CODE_FILE_CHARS", 300_000)

# Memory Decay 설정
def _get_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        _logger.warning("Invalid float env", env=name, value=raw)
        return default

MEMORY_BASE_DECAY_RATE = _get_float_env("MEMORY_BASE_DECAY_RATE", 0.001)
MEMORY_MIN_RETENTION = _get_float_env("MEMORY_MIN_RETENTION", 0.3)
MEMORY_DECAY_DELETE_THRESHOLD = _get_float_env("MEMORY_DECAY_DELETE_THRESHOLD", 0.03)
MEMORY_SIMILARITY_THRESHOLD = _get_float_env("MEMORY_SIMILARITY_THRESHOLD", 0.90)
MEMORY_MIN_IMPORTANCE = _get_float_env("MEMORY_MIN_IMPORTANCE", 0.25)

# 메시지 축약 설정
MESSAGE_ARCHIVE_AFTER_DAYS = _get_int_env("MESSAGE_ARCHIVE_AFTER_DAYS", 7)
MESSAGE_SUMMARY_MODEL = os.getenv("MESSAGE_SUMMARY_MODEL", "gemini-2.0-flash")
