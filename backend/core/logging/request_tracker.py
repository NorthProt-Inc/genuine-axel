import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
from contextvars import ContextVar
from .logging import get_logger, Colors

_logger = get_logger("tracker")

_current_request: ContextVar[Optional['RequestTracker']] = ContextVar('current_request', default=None)

@dataclass
class RequestTracker:

    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:6])
    input_preview: str = ""
    start_time: float = field(default_factory=time.time)

    gateway_intent: str = ""
    gateway_model: str = ""
    gateway_ms: float = 0

    memory_longterm: int = 0
    memory_working: int = 0
    memory_tokens: int = 0

    llm_model: str = ""
    llm_tokens: int = 0
    llm_ms: float = 0

    search_query: str = ""
    search_results: int = 0
    search_ms: float = 0

    tts_chars: int = 0
    tts_ms: float = 0

    hass_action: str = ""

    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000

def start_request(user_input: str) -> RequestTracker:

    preview = user_input[:30] + "..." if len(user_input) > 30 else user_input
    preview = preview.replace("\n", " ")

    tracker = RequestTracker(input_preview=preview)
    _current_request.set(tracker)
    return tracker

def get_tracker() -> Optional[RequestTracker]:

    return _current_request.get()

def log_gateway(intent: str, model: str, elapsed_ms: float):

    tracker = get_tracker()
    if tracker:
        tracker.gateway_intent = intent
        tracker.gateway_model = model
        tracker.gateway_ms = elapsed_ms

def log_memory(longterm: int = 0, working: int = 0, tokens: int = 0):

    tracker = get_tracker()
    if tracker:
        tracker.memory_longterm = longterm
        tracker.memory_working = working
        tracker.memory_tokens = tokens

def log_search(query: str, results: int, elapsed_ms: float):

    tracker = get_tracker()
    if tracker:
        tracker.search_query = query
        tracker.search_results = results
        tracker.search_ms = elapsed_ms

def end_request():

    tracker = get_tracker()
    if not tracker:
        return

    total_ms = tracker.elapsed_ms()

    lines = []

    lines.append(f"{Colors.DIM}{'─' * 60}{Colors.RESET}")
    lines.append(f"REQ [{tracker.request_id}] \"{tracker.input_preview}\"")

    if tracker.gateway_intent:
        lines.append(
            f"├─ Gateway: {tracker.gateway_intent} → "
            f"{Colors.INFO}{tracker.gateway_model}{Colors.RESET} "
            f"{Colors.DIM}({tracker.gateway_ms:.0f}ms){Colors.RESET}"
        )

    if tracker.hass_action:
        lines.append(f"├─ Action: {Colors.WARNING}{tracker.hass_action}{Colors.RESET}")

    if tracker.memory_longterm > 0 or tracker.memory_working > 0:
        lines.append(
            f"├─ Memory: {tracker.memory_longterm} long-term, "
            f"{tracker.memory_working} working "
            f"{Colors.DIM}({tracker.memory_tokens:,} tokens){Colors.RESET}"
        )

    if tracker.search_results > 0:
        lines.append(
            f"├─ Search: {tracker.search_results} results "
            f"{Colors.DIM}({tracker.search_ms:.0f}ms){Colors.RESET}"
        )

    if tracker.llm_model:
        lines.append(
            f"├─ LLM: {Colors.INFO}{tracker.llm_model}{Colors.RESET} "
            f"({tracker.llm_tokens:,} tokens, {tracker.llm_ms/1000:.1f}s)"
        )

    if tracker.tts_chars > 0:
        lines.append(
            f"├─ TTS: {tracker.tts_chars} chars "
            f"{Colors.DIM}({tracker.tts_ms/1000:.1f}s){Colors.RESET}"
        )

    total_s = total_ms / 1000
    status = "Done"
    lines.append(f"└─ {status} ({total_s:.1f}s total)")

    summary = "\n".join(lines)
    _logger.info("REQ summary", summary=summary)

    _current_request.set(None)

class track_request:

    def __init__(self, user_input: str):
        self.user_input = user_input
        self.tracker = None

    def __enter__(self) -> RequestTracker:
        self.tracker = start_request(self.user_input)
        return self.tracker

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            _logger.error("REQ error", error=str(exc_val)[:100])
        end_request()
        return False
