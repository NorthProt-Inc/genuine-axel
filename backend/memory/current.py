from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Deque
from pathlib import Path
import threading
import uuid
import json
from backend.config import WORKING_MEMORY_PATH, CONTEXT_WORKING_TURNS, CONTEXT_SQL_PERSIST_TURNS
from backend.core.utils.timezone import now_vancouver, ensure_aware
from backend.core.logging import get_logger

_log = get_logger("memory.current")

def normalize_role(role: str) -> str:
    role_lower = role.lower()
    if role_lower == "user":
        return "Mark"
    elif role_lower in ("assistant", "ai"):
        return "Axel"
    return role

@dataclass
class TimestampedMessage:
    role: str
    content: str
    timestamp: datetime = field(default_factory=now_vancouver)
    emotional_context: str = "neutral"

    def get_relative_time(self, reference: Optional[datetime] = None) -> str:
        ref = reference or now_vancouver()
        ts = ensure_aware(self.timestamp)
        elapsed = ref - ts

        if elapsed < timedelta(seconds=30):
            return "방금"
        elif elapsed < timedelta(minutes=1):
            return f"{int(elapsed.total_seconds())}초 전"
        elif elapsed < timedelta(hours=1):
            return f"{int(elapsed.total_seconds() / 60)}분 전"
        elif elapsed < timedelta(days=1):
            return f"{int(elapsed.total_seconds() / 3600)}시간 전"
        elif elapsed < timedelta(days=7):
            return f"{elapsed.days}일 전"
        else:
            return self.timestamp.strftime("%Y-%m-%d")

    def get_absolute_time(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d %H:%M:%S")

    def format_for_context(self, include_time: bool = True) -> str:
        if include_time:
            return f"[{self.get_relative_time()} | {self.timestamp.strftime('%H:%M')}] {self.role}: {self.content}"
        return f"{self.role}: {self.content}"

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "emotional_context": self.emotional_context,
        }

class WorkingMemory:
    MAX_TURNS = CONTEXT_WORKING_TURNS
    SQL_PERSIST_TURNS = CONTEXT_SQL_PERSIST_TURNS
    PERSISTENCE_PATH = str(WORKING_MEMORY_PATH)

    def __init__(self):
        self._messages: Deque[TimestampedMessage] = deque(maxlen=self.MAX_TURNS * 2)
        self._lock = threading.Lock()
        self.session_id: str = str(uuid.uuid4())
        self.session_start: datetime = now_vancouver()
        self.last_activity: datetime = now_vancouver()

    @property
    def messages(self) -> List[TimestampedMessage]:
        with self._lock:
            return list(self._messages)

    def add(self, role: str, content: str, emotional_context: str = "neutral") -> TimestampedMessage:
        normalized_role = normalize_role(role)

        msg = TimestampedMessage(
            role=normalized_role,
            content=content,
            timestamp=now_vancouver(),
            emotional_context=emotional_context
        )
        with self._lock:
            self._messages.append(msg)
        self.last_activity = now_vancouver()

        _log.debug("msg added", role=normalized_role, content_len=len(content))
        return msg

    def get_context(self, max_turns: Optional[int] = None) -> str:
        turns = max_turns or self.MAX_TURNS

        recent = self.messages[-(turns * 2):]

        _log.debug("ctx returned", turns=len(recent) // 2)

        return "\n".join([
            msg.format_for_context(include_time=True)
            for msg in recent
        ])

    def get_time_elapsed_context(self) -> str:
        with self._lock:
            if not self._messages:
                return " 첫 대화 시작 - 자연스럽게 인사해."
            last_msg = self._messages[-1]

        ts = ensure_aware(last_msg.timestamp)
        elapsed = now_vancouver() - ts

        if elapsed < timedelta(seconds=30):
            return ""
        elif elapsed < timedelta(minutes=5):
            mins = int(elapsed.total_seconds() / 60)
            return f" 잠깐 {mins}분간 멈춤 - 이전 맥락 바로 이어서."
        elif elapsed < timedelta(hours=1):
            mins = int(elapsed.total_seconds() / 60)
            return f" {mins}분 후 대화 재개 - 같은 맥락 유지, 인사 불필요."
        elif elapsed < timedelta(hours=6):
            hours = int(elapsed.total_seconds() / 3600)
            return f" {hours}시간 만에 대화 재개 - 가벼운 안부 후 이전 주제로."
        elif elapsed < timedelta(days=1):
            hours = int(elapsed.total_seconds() / 3600)
            return f" {hours}시간 만에 대화 재개 - 새 세션 느낌, 밥/컨디션 물어보기."
        else:
            return f" {elapsed.days}일 만에 대화 재개 - 오랜만이니 안부부터 시작."

    def get_messages(self) -> List[TimestampedMessage]:
        with self._lock:
            return list(self._messages)

    def flush(self) -> List[TimestampedMessage]:
        with self._lock:
            messages = list(self._messages)
            self._messages.clear()
        return messages

    def reset_session(self) -> str:
        old_id = self.session_id
        self.session_id = str(uuid.uuid4())
        self.session_start = now_vancouver()
        self.last_activity = now_vancouver()
        with self._lock:
            self._messages.clear()
        return old_id

    def get_turn_count(self) -> int:
        """Get number of conversation turns."""
        # PERF-029: Don't copy entire deque just to count
        with self._lock:
            return len(self._messages) // 2

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    def __bool__(self) -> bool:
        with self._lock:
            return len(self._messages) > 0

    def get_progressive_context(self, full_turns: int = 10) -> str:
        messages = self.messages
        full_count = full_turns * 2

        if len(messages) <= full_count:

            _log.debug("progressive ctx", compressed_cnt=0, full_cnt=len(messages))
            return "\n".join([m.format_for_context() for m in messages])

        older = messages[:-full_count]
        recent = messages[-full_count:]

        compressed = []
        for m in older:
            if m.role in ("user", "Mark"):

                summary = m.content[:500] + "..." if len(m.content) > 500 else m.content
            else:

                summary = m.content[:300] + "..." if len(m.content) > 300 else m.content
            compressed.append(f"[{m.get_relative_time()}] {m.role}: {summary}")

        full = [m.format_for_context() for m in recent]

        _log.debug("progressive ctx", compressed_cnt=len(older), full_cnt=len(recent))

        return "\n".join(compressed + full)

    def get_messages_for_sql(self, max_turns: Optional[int] = None) -> List[TimestampedMessage]:
        turns = max_turns or self.SQL_PERSIST_TURNS
        return self.messages[-(turns * 2):]

    def save_to_disk(self, path: Optional[str] = None) -> bool:
        path = path or self.PERSISTENCE_PATH
        try:
            with self._lock:
                data = {
                    "session_id": self.session_id,
                    "session_start": self.session_start.isoformat(),
                    "last_activity": self.last_activity.isoformat(),
                    "messages": [msg.to_dict() for msg in self._messages],
                    "saved_at": now_vancouver().isoformat(),
                    "version": "1.0"
                }
                msg_cnt = len(self._messages)

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            _log.info("save ok", msg_cnt=msg_cnt, path=path)
            return True
        except Exception as e:
            _log.info("save fail", error=str(e), path=path)
            return False

    def load_from_disk(self, path: Optional[str] = None) -> bool:
        path = path or self.PERSISTENCE_PATH
        try:
            if not Path(path).exists():
                _log.info("load fail", error="file not found", path=path)
                return False

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            with self._lock:
                self._messages.clear()
                self.session_id = data.get("session_id", str(uuid.uuid4()))
                self.session_start = datetime.fromisoformat(data.get("session_start", now_vancouver().isoformat()))
                self.last_activity = datetime.fromisoformat(data.get("last_activity", now_vancouver().isoformat()))

                for msg_data in data.get("messages", []):
                    msg = TimestampedMessage(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        timestamp=datetime.fromisoformat(msg_data["timestamp"]),
                        emotional_context=msg_data.get("emotional_context", "neutral")
                    )
                    self._messages.append(msg)

                msg_cnt = len(self._messages)

            _log.info("load ok", msg_cnt=msg_cnt, path=path)
            return True
        except Exception as e:
            _log.info("load fail", error=str(e), path=path)
            return False
