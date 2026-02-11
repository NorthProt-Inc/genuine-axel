# Logging System

Documentation for the structured logging system in the axnmihn project.

---

## Overview

This logging system provides clean and readable log output:
- Module-specific color output
- Severity-based colors
- Automatic abbreviation conversion
- `@logged` decorator for automatic function entry/exit logging
- Structured key=value format
- Request tracking with elapsed time display
- File rotation (10MB, 5 backups)

---

## Module Color Reference

| Module | Abbreviation | Color | ANSI Code |
|--------|--------------|-------|-----------|
| api | API | Bright Blue | `\033[94m` |
| core | COR | Cyan | `\033[96m` |
| memory | MEM | Light Magenta | `\033[95m` |
| llm | LLM | Light Green | `\033[92m` |
| mcp | MCP | Yellow | `\033[93m` |
| protocols | MCP | Yellow | `\033[93m` |
| media | MED | Orange | `\033[38;5;208m` |
| wake | WAK | Light Red | `\033[91m` |
| tools | TOL | White | `\033[97m` |
| research | RSC | Blue | `\033[38;5;39m` |
| services | SVC | Light Purple | `\033[38;5;147m` |
| app | APP | Cyan | `\033[96m` |
| config | CFG | Cyan | `\033[96m` |
| opus | OPU | Pink | `\033[38;5;213m` |
| tracker | TRK | Gray | `\033[90m` |
| utils | UTL | Light Gray | `\033[37m` |

---

## Severity Levels

| Level | Description | When to Use |
|-------|-------------|-------------|
| **DEBUG** | Detailed diagnostic information | Function entry/exit, internal state inspection |
| **INFO** | Normal operation | Requests/responses, important events |
| **WARNING** | Recoverable issues | Retries, fallback handling |
| **ERROR** | Failures requiring attention | Exceptions, failed operations |
| **CRITICAL** | System failures | Service outages, fatal errors |

### Severity Colors

| Level | Color | ANSI Code |
|-------|-------|-----------|
| DEBUG | Cyan | `\033[36m` |
| INFO | Green | `\033[32m` |
| WARNING | Yellow | `\033[33m` |
| ERROR | Red | `\033[31m` |
| CRITICAL | Magenta | `\033[35m` |

---

## Abbreviation Dictionary

The following abbreviations are automatically applied to keep log messages concise:

### General Terms

| Original | Abbreviation |
|----------|--------------|
| request | req |
| response | res |
| message | msg |
| error | err |
| config | cfg |
| connection | conn |
| timeout | tout |
| memory | mem |
| context | ctx |
| tokens | tok |
| function | fn |
| parameter | param |
| execution | exec |
| initialization | init |
| milliseconds | ms |
| seconds | sec |
| count | cnt |
| length | len |
| session | sess |
| entity | ent |
| device | dev |
| assistant | asst |

### Action-Related

| Original | Abbreviation |
|----------|--------------|
| received | recv |
| sent | sent |
| success | ok |
| failure | fail |
| building | build |
| processing | proc |
| completed | done |
| started | start |
| finished | fin |

### Technical Terms

| Original | Abbreviation |
|----------|--------------|
| database | db |
| query | qry |
| result | res |
| input | in |
| output | out |
| latency | lat |
| duration | dur |
| provider | prov |
| model | mdl |

---

## Usage Examples

### Basic Logger Usage

```python
from backend.core.logging import get_logger

logger = get_logger("api.chat")

# Basic logging
logger.info("Server started", port=8000, env="prod")
logger.debug("Processing request", user_id="abc123")
logger.warning("Rate limit approaching", remaining=10)
logger.error("Connection failed", host="db.local", retry=3)
```

### API Endpoint Logging

```python
from backend.core.logging import get_logger

logger = get_logger("api")

@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    logger.info("Chat request received",
                session=request.session_id,
                model=request.model)

    try:
        result = await process_chat(request)
        logger.info("Chat completed",
                    tokens=result.total_tokens,
                    latency=result.latency_ms)
        return result
    except Exception as e:
        logger.error("Chat failed", error=str(e))
        raise
```

### Core Function Logging

```python
from backend.core.logging import get_logger

logger = get_logger("core.chat_handler")

async def handle_message(message: str, context: dict):
    logger.debug("Processing message",
                 length=len(message),
                 context_keys=list(context.keys()))

    # Processing logic
    result = await generate_response(message, context)

    logger.info("Response generated",
                model=result.model,
                tokens=result.tokens)
    return result
```

### Tool Function Logging

```python
from backend.core.logging import get_logger

logger = get_logger("tools.hass_ops")

async def control_device(entity_id: str, action: str):
    logger.info("Controlling device",
                entity=entity_id,
                action=action)

    try:
        response = await hass_client.call_service(entity_id, action)
        logger.debug("Device responded",
                     state=response.state)
        return response
    except Exception as e:
        logger.error("Device control failed",
                     entity=entity_id,
                     error=str(e))
        raise
```

### @logged Decorator Usage

```python
from backend.core.logging import logged

# Basic usage (entry/exit logs)
@logged()
async def my_function(x, y):
    return x + y

# Include arguments and result
@logged(log_args=True, log_result=True)
def compute(data):
    return process(data)

# Entry log only
@logged(exit=False)
async def fire_and_forget(task):
    await background_task(task)

# Log at INFO level
@logged(level=logging.INFO, log_args=True)
async def important_operation(config: dict):
    return await execute(config)
```

#### @logged Decorator Output Examples

```
14:32:01.234 DEBUG [COR|chat_hand…] → my_function
14:32:01.567 DEBUG [COR|chat_hand…] ← my_function

# With log_args=True
14:32:01.234 DEBUG [COR|chat_hand…] → compute │ data=[3 items]
14:32:01.567 DEBUG [COR|chat_hand…] ← compute │ result=42

# On exception
14:32:01.234 DEBUG [COR|chat_hand…] → my_function
14:32:01.567 ERROR [COR|chat_hand…] ✗ my_function │ error=Connection refused
```

### Logger Naming Convention

Logger names follow the `module.submodule` pattern. The first segment (before `.` or `-`) determines the module color and abbreviation:

```python
# Standard naming — first segment maps to MODULE_COLORS/MODULE_ABBREV
_log = get_logger("services.context")    # SVC (Light Purple)
_log = get_logger("research.browser")    # RSC (Blue)

# Hyphenated names — prefix before first '-' is used for mapping
_log = get_logger("opus-bridge")         # OPU (Pink)
_log = get_logger("rate-limiter")        # RAT (default)
```

---

## Configuration

### Environment Variables

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `LOG_LEVEL` | Log level setting | `INFO` | `DEBUG`, `WARNING`, `ERROR` |
| `LOG_JSON` | Enable JSON logging | `false` | `1`, `true`, `yes` |
| `NO_COLOR` | Disable color output | unset | any value |

### Usage Examples

```bash
# Run with debug level
LOG_LEVEL=DEBUG python -m backend.app

# Enable JSON logging
LOG_JSON=true python -m backend.app

# Disable color (for pipeline use)
NO_COLOR=1 python -m backend.app | tee output.log
```

### Dynamic Level Change

```python
from backend.core.logging import set_log_level

# Change log level at runtime
set_log_level("DEBUG")  # Enable detailed logs
set_log_level("WARNING")  # Show warnings and above only
```

---

## Output Format

### Console Output Format

```
HH:MM:SS.mmm LVL [MOD|submod     ] msg │ k=v k2=v2
```

#### Format Components

| Component | Description | Example |
|-----------|-------------|---------|
| `HH:MM:SS.mmm` | Timestamp (with milliseconds) | `14:32:01.234` |
| `LVL` | Severity level (5 chars) | `DEBUG`, ` INFO`, ` WARN`, `ERROR`, `CRIT!` |
| `MOD` | Module abbreviation (3 chars) | `API`, `COR`, `MEM`, `RSC`, `SVC` |
| `submod` | Submodule name (max 9 chars) | `chat`, `handler` |
| `msg` | Log message | `Server started` |
| `│` | Separator | - |
| `k=v` | Key-value pairs | `port=8000 env=prod` |

### Actual Output Examples

```
14:32:01.234  INFO [API|chat       ] Chat req recv │ sess=abc12345 mdl=gemini-3
14:32:01.456 DEBUG [COR|chat_hand…] → handle_message │ len=128
14:32:02.123  INFO [LLM|clients    ] Response done │ tok=1234 lat=667ms
14:32:02.234  WARN [MEM|permanent  ] Cache miss │ key=user_pref
14:32:02.345 ERROR [API|chat       ] Request fail │ err=timeout
14:32:03.100  INFO [SVC|context    ] Context built │ tok=4500 layers=3
14:32:03.200 DEBUG [RSC|browser    ] Page fetched │ url=https://example.com
14:32:03.300  INFO [OPU|bridge     ] Task delegated │ model=opus
```

### File Log Format

File logs are written to `logs/axnmihn.log` with a detailed timestamp and no colors:

```
2026-02-10 14:32:01.234 INFO    [abc12345│api.chat      ] Chat req recv │ sess=abc12345 mdl=gemini-3
```

### JSON Log Format

When `LOG_JSON=true`, logs are saved to `logs/axnmihn.jsonl` in JSONL format:

```json
{"ts":"2026-02-10T14:32:01.234567-08:00","level":"INFO","logger":"api.chat","msg":"Chat req recv","req":"abc12345","sess":"abc12345","mdl":"gemini-3-flash"}
```

---

## Value Formatting

Log values are automatically formatted for readability:

| Type | Format | Example |
|------|--------|---------|
| `None` | `null` | `value=null` |
| `bool` | `yes`/`no` | `enabled=yes` |
| `int`/`float` | as-is | `count=42`, `ratio=0.95` |
| `list` (0-3 items) | full display | `items=[a, b, c]` |
| `list` (4+ items) | count display | `items=[15 items]` |
| `dict` | key count | `config={5 keys}` |
| `str` (60+ chars) | truncated | `content=Lorem ipsum dolor sit amet...` |

---

## Special Key Highlighting

Certain keys are displayed in different colors for visual distinction:

| Key | Color | Purpose |
|-----|-------|---------|
| `model`, `tier`, `provider` | Light Magenta | LLM-related information |
| `tokens`, `memories`, `working`, `longterm` | Light Cyan | Memory-related information |
| `session` | Light Green | Session identifier |
| `latency` | Yellow | Performance metrics |
| `error` | Red | Error information |

---

## Request Tracking

When a request ID is set, it's automatically included in all logs for that request:

```python
from backend.core.logging import set_request_id, reset_request_id

# At request start
token = set_request_id("req-abc123")

try:
    # All logs within this block include the request ID
    await process_request()
finally:
    # Reset at request end
    reset_request_id(token)
```

Elapsed time is automatically displayed when `request_tracker` is active:

```
14:32:01.234  INFO [API|chat       ] Processing │ +1.2s
14:32:02.456  INFO [API|chat       ] Completed │ +2.4s
```

---

## File Structure

```
backend/
└── core/
    └── logging/
        ├── __init__.py           # Public API exports
        ├── constants.py          # Constants, colors, abbreviations
        ├── formatters.py         # SmartFormatter, PlainFormatter, JsonFormatter
        ├── structured_logger.py  # StructuredLogger, get_logger(), set_log_level()
        ├── decorator.py          # @logged decorator
        ├── logging.py            # Backward compatibility shim
        ├── error_monitor.py      # Error monitoring (기존)
        └── request_tracker.py    # Request tracking (기존)

logs/
├── axnmihn.log           # Structured logger output (rotated, 10MB, 5 backups)
├── backend.log           # Backend plain text log (systemd stdout)
├── backend_error.log     # Backend errors only
├── mcp.log               # MCP server log
├── mcp_error.log         # MCP errors only
├── research.log          # Research MCP log
├── research_error.log    # Research errors only
├── context7_mcp.log      # Context7 MCP log
├── context7_mcp_error.log # Context7 MCP errors only
├── markitdown_mcp.log    # MarkItDown MCP log
├── markitdown_mcp_error.log # MarkItDown MCP errors only
├── wakeword.log          # Wakeword service log
└── night_ops.log         # Night shift automation log
```

### Import 경로

**권장 방법** (패키지 레벨 import):
```python
from backend.core.logging import get_logger, logged, set_log_level
from backend.core.logging import set_request_id, reset_request_id
```

**하위 호환성** (기존 경로, 계속 동작함):
```python
from backend.core.logging.logging import get_logger, logged
```

**고급 사용** (서브모듈 직접 import):
```python
from backend.core.logging.constants import MODULE_COLORS, ABBREV
from backend.core.logging.formatters import SmartFormatter
from backend.core.logging.structured_logger import StructuredLogger
```

---

## Best Practices

### 1. Choose Appropriate Log Levels

```python
# DEBUG: Detailed information for development/debugging
logger.debug("Cache lookup", key=cache_key, hit=cache_hit)

# INFO: Information needed for operational awareness
logger.info("Request processed", duration=elapsed_ms)

# WARNING: Attention needed but service is normal
logger.warning("Retry attempt", attempt=3, max=5)

# ERROR: Failed but service can continue
logger.error("API call failed", service="hass", error=str(e))

# CRITICAL: Service outage level issues
logger.critical("Database connection lost")
```

### 2. Use Structured Data

```python
# Good - structured key-value
logger.info("User action",
            user_id=user.id,
            action="login",
            ip=request.client.host)

# Avoid - string formatting
logger.info(f"User {user.id} logged in from {request.client.host}")
```

### 3. Exclude Sensitive Information

```python
# Good - token masking
logger.debug("Auth request", token=api_key[:8] + "...")

# Avoid - full token exposure
logger.debug("Auth request", token=api_key)  # Dangerous!
```

### 4. Exception Logging

```python
try:
    await risky_operation()
except Exception as e:
    # exception() includes stack trace
    logger.exception("Operation failed", operation="risky")
```

---

## Troubleshooting

### Logs Not Appearing

1. Check `LOG_LEVEL`: Set `LOG_LEVEL=DEBUG`
2. Verify handlers: Ensure logger is properly initialized

### Colors Not Displaying

1. Check `NO_COLOR` environment variable
2. Verify terminal supports ANSI colors
3. Colors auto-disable when output is redirected to file

### File Logs Not Created

1. Verify `logs/` directory exists
2. Check write permissions
3. Check disk space

---

## Changelog

- **v3.1**: 모듈 매핑 확장 — `research`, `services`, `app`, `config`, `opus`, `tracker`, `utils` 색상/약어 추가, 하이픈 로거 이름 지원, 로그 파일 구조 문서 동기화
- **v3.0**: 모듈화 — 549줄 단일 파일을 4개 모듈로 분리 (`constants.py`, `formatters.py`, `structured_logger.py`, `decorator.py`)
- **v2.0**: Added module colors, abbreviation system, @logged decorator
- **v1.0**: Initial structured logging system
