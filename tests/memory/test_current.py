"""Tests for backend.memory.current — WorkingMemory and TimestampedMessage.

Uses tmp_path for file persistence tests. Mocks now_vancouver for
deterministic timestamps.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backend.core.utils.timezone import VANCOUVER_TZ
from backend.memory.current import (
    WorkingMemory,
    TimestampedMessage,
    normalize_role,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _ts(y=2025, mo=3, d=15, h=12, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=VANCOUVER_TZ)


FROZEN_NOW = _ts()


@pytest.fixture
def wm():
    """Fresh WorkingMemory with frozen timestamps."""
    with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
        return WorkingMemory()


# ── normalize_role ───────────────────────────────────────────────────────

class TestNormalizeRole:

    def test_user_becomes_mark(self):
        assert normalize_role("user") == "Mark"

    def test_user_case_insensitive(self):
        assert normalize_role("User") == "Mark"

    def test_assistant_becomes_axel(self):
        assert normalize_role("assistant") == "Axel"

    def test_ai_becomes_axel(self):
        assert normalize_role("ai") == "Axel"
        assert normalize_role("AI") == "Axel"

    def test_unknown_role_passthrough(self):
        assert normalize_role("system") == "system"
        assert normalize_role("admin") == "admin"


# ── TimestampedMessage ───────────────────────────────────────────────────

class TestTimestampedMessage:

    def test_default_values(self):
        msg = TimestampedMessage(role="Mark", content="hello", timestamp=FROZEN_NOW)
        assert msg.role == "Mark"
        assert msg.content == "hello"
        assert msg.emotional_context == "neutral"
        assert msg.timestamp == FROZEN_NOW

    def test_get_relative_time_just_now(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(seconds=10)
        assert msg.get_relative_time(ref) == "방금"

    def test_get_relative_time_seconds(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(seconds=45)
        result = msg.get_relative_time(ref)
        assert "초 전" in result

    def test_get_relative_time_minutes(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(minutes=15)
        result = msg.get_relative_time(ref)
        assert "분 전" in result

    def test_get_relative_time_hours(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(hours=5)
        result = msg.get_relative_time(ref)
        assert "시간 전" in result

    def test_get_relative_time_days(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(days=3)
        result = msg.get_relative_time(ref)
        assert "일 전" in result

    def test_get_relative_time_over_week(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        ref = FROZEN_NOW + timedelta(days=10)
        result = msg.get_relative_time(ref)
        assert "2025-03-15" in result

    def test_get_absolute_time(self):
        msg = TimestampedMessage(role="Mark", content="hi", timestamp=FROZEN_NOW)
        assert msg.get_absolute_time() == "2025-03-15 12:00:00"

    def test_format_for_context_with_time(self):
        msg = TimestampedMessage(role="Mark", content="hello", timestamp=FROZEN_NOW)
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            result = msg.format_for_context(include_time=True)
        assert "Mark: hello" in result
        assert "12:00" in result

    def test_format_for_context_without_time(self):
        msg = TimestampedMessage(role="Mark", content="hello", timestamp=FROZEN_NOW)
        result = msg.format_for_context(include_time=False)
        assert result == "Mark: hello"

    def test_to_dict(self):
        msg = TimestampedMessage(
            role="Mark", content="hello", timestamp=FROZEN_NOW, emotional_context="happy"
        )
        d = msg.to_dict()
        assert d["role"] == "Mark"
        assert d["content"] == "hello"
        assert d["emotional_context"] == "happy"
        assert "timestamp" in d


# ── WorkingMemory basic operations ───────────────────────────────────────

class TestWorkingMemoryBasic:

    def test_initial_state(self, wm):
        assert len(wm) == 0
        assert not wm
        assert wm.messages == []
        assert wm.get_turn_count() == 0

    def test_add_message(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            msg = wm.add("user", "hello")
        assert msg.role == "Mark"
        assert msg.content == "hello"
        assert len(wm) == 1
        assert wm

    def test_add_normalizes_role(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            msg1 = wm.add("user", "hi")
            msg2 = wm.add("assistant", "hey")
        assert msg1.role == "Mark"
        assert msg2.role == "Axel"

    def test_add_with_emotional_context(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            msg = wm.add("user", "I'm sad", emotional_context="sad")
        assert msg.emotional_context == "sad"

    def test_turn_count(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
            wm.add("assistant", "hello")
            wm.add("user", "how are you?")
        # 3 messages => 1.5 turns => 1
        assert wm.get_turn_count() == 1

    def test_messages_returns_copy(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        msgs = wm.messages
        assert len(msgs) == 1
        msgs.clear()
        assert len(wm.messages) == 1  # original not affected


# ── get_context ──────────────────────────────────────────────────────────

class TestGetContext:

    def test_empty_context(self, wm):
        assert wm.get_context() == ""

    def test_context_includes_messages(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hello")
            wm.add("assistant", "hi there")
        ctx = wm.get_context()
        assert "hello" in ctx
        assert "hi there" in ctx

    def test_context_respects_max_turns(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            for i in range(20):
                wm.add("user", f"msg {i}")
                wm.add("assistant", f"reply {i}")
        ctx = wm.get_context(max_turns=2)
        lines = [l for l in ctx.strip().split("\n") if l]
        assert len(lines) == 4  # 2 turns * 2 messages


# ── get_time_elapsed_context ─────────────────────────────────────────────

class TestTimeElapsedContext:

    def test_no_messages_returns_first_conversation(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            result = wm.get_time_elapsed_context()
        assert "첫 대화" in result

    def test_within_30_seconds_empty(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(seconds=10)):
            result = wm.get_time_elapsed_context()
        assert result == ""

    def test_within_5_minutes(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(minutes=3)):
            result = wm.get_time_elapsed_context()
        assert "분간 멈춤" in result

    def test_within_1_hour(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(minutes=30)):
            result = wm.get_time_elapsed_context()
        assert "분 후 대화 재개" in result

    def test_within_6_hours(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(hours=3)):
            result = wm.get_time_elapsed_context()
        assert "시간 만에 대화 재개" in result
        assert "가벼운 안부" in result

    def test_within_1_day(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(hours=10)):
            result = wm.get_time_elapsed_context()
        assert "시간 만에 대화 재개" in result
        assert "새 세션" in result

    def test_over_1_day(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hi")
        with patch("backend.memory.current.now_vancouver",
                   return_value=FROZEN_NOW + timedelta(days=3)):
            result = wm.get_time_elapsed_context()
        assert "일 만에 대화 재개" in result


# ── flush / reset / get_messages ─────────────────────────────────────────

class TestFlushAndReset:

    def test_flush_returns_and_clears(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "a")
            wm.add("assistant", "b")
        flushed = wm.flush()
        assert len(flushed) == 2
        assert len(wm) == 0

    def test_get_messages_returns_copy(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hello")
        msgs = wm.get_messages()
        assert len(msgs) == 1
        msgs.pop()
        assert len(wm.get_messages()) == 1

    def test_reset_session_new_id(self, wm):
        old_id = wm.session_id
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "data")
        returned_id = wm.reset_session()
        assert returned_id == old_id
        assert wm.session_id != old_id
        assert len(wm) == 0


# ── Progressive context ─────────────────────────────────────────────────

class TestProgressiveContext:

    def test_few_messages_no_compression(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hello")
            wm.add("assistant", "hi")
        result = wm.get_progressive_context(full_turns=10)
        assert "hello" in result
        assert "hi" in result

    def test_many_messages_compresses_older(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            for i in range(30):
                wm.add("user", f"user msg {i}")
                wm.add("assistant", f"assistant response {i} " + "x" * 400)
        # full_turns=2 means only last 4 messages are full
        result = wm.get_progressive_context(full_turns=2)
        assert "user msg 29" in result
        assert "assistant response 29" in result

    def test_long_user_message_truncated_in_compressed(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            long_msg = "a" * 600
            wm.add("user", long_msg)
            wm.add("assistant", "ok")
            wm.add("user", "recent")
            wm.add("assistant", "got it")
        result = wm.get_progressive_context(full_turns=1)
        # The older user message (600 chars) should be truncated to 500 + "..."
        assert "..." in result

    def test_long_assistant_message_truncated_in_compressed(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "q")
            wm.add("assistant", "b" * 400)
            wm.add("user", "recent")
            wm.add("assistant", "got it")
        result = wm.get_progressive_context(full_turns=1)
        assert "..." in result


# ── get_messages_for_sql ─────────────────────────────────────────────────

class TestGetMessagesForSql:

    def test_returns_last_n_turns(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            for i in range(20):
                wm.add("user", f"q{i}")
                wm.add("assistant", f"a{i}")
        result = wm.get_messages_for_sql(max_turns=3)
        assert len(result) == 6  # 3 turns * 2

    def test_defaults_to_sql_persist_turns(self, wm):
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            for i in range(30):
                wm.add("user", f"q{i}")
                wm.add("assistant", f"a{i}")
        result = wm.get_messages_for_sql()
        expected_len = min(wm.SQL_PERSIST_TURNS * 2, len(wm.messages))
        assert len(result) == expected_len


# ── Disk persistence ─────────────────────────────────────────────────────

class TestDiskPersistence:

    def test_save_and_load_roundtrip(self, wm, tmp_path):
        path = str(tmp_path / "wm.json")
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "hello")
            wm.add("assistant", "hi there")
        assert wm.save_to_disk(path) is True

        wm2 = WorkingMemory()
        assert wm2.load_from_disk(path) is True
        assert len(wm2) == 2
        msgs = wm2.messages
        assert msgs[0].role == "Mark"
        assert msgs[0].content == "hello"
        assert msgs[1].role == "Axel"

    def test_save_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "wm.json")
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm = WorkingMemory()
            wm.add("user", "test")
        assert wm.save_to_disk(path) is True
        assert (tmp_path / "sub" / "dir" / "wm.json").exists()

    def test_load_nonexistent_returns_false(self, wm, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        assert wm.load_from_disk(path) is False

    def test_load_corrupted_json_returns_false(self, wm, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, 'w') as f:
            f.write("not json")
        assert wm.load_from_disk(path) is False

    def test_save_preserves_session_metadata(self, wm, tmp_path):
        path = str(tmp_path / "wm.json")
        session_id = wm.session_id
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "data")
        wm.save_to_disk(path)

        with open(path, 'r') as f:
            data = json.load(f)
        assert data["session_id"] == session_id
        assert data["version"] == "1.0"
        assert "saved_at" in data

    def test_load_restores_session_id(self, wm, tmp_path):
        path = str(tmp_path / "wm.json")
        original_id = wm.session_id
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm.add("user", "data")
        wm.save_to_disk(path)

        wm2 = WorkingMemory()
        wm2.load_from_disk(path)
        assert wm2.session_id == original_id

    def test_load_with_emotional_context(self, tmp_path):
        path = str(tmp_path / "wm.json")
        data = {
            "session_id": "test-123",
            "session_start": FROZEN_NOW.isoformat(),
            "last_activity": FROZEN_NOW.isoformat(),
            "messages": [
                {
                    "role": "Mark",
                    "content": "I'm happy",
                    "timestamp": FROZEN_NOW.isoformat(),
                    "emotional_context": "happy",
                }
            ],
        }
        with open(path, 'w') as f:
            json.dump(data, f)

        wm = WorkingMemory()
        assert wm.load_from_disk(path) is True
        assert wm.messages[0].emotional_context == "happy"

    def test_load_missing_emotional_context_defaults_neutral(self, tmp_path):
        path = str(tmp_path / "wm.json")
        data = {
            "session_id": "test-456",
            "session_start": FROZEN_NOW.isoformat(),
            "last_activity": FROZEN_NOW.isoformat(),
            "messages": [
                {
                    "role": "Mark",
                    "content": "hello",
                    "timestamp": FROZEN_NOW.isoformat(),
                }
            ],
        }
        with open(path, 'w') as f:
            json.dump(data, f)

        wm = WorkingMemory()
        assert wm.load_from_disk(path) is True
        assert wm.messages[0].emotional_context == "neutral"


# ── Deque maxlen behavior ───────────────────────────────────────────────

class TestDequeMaxlen:

    def test_messages_capped_at_maxlen(self, wm):
        """Adding more than MAX_TURNS*2 messages should drop oldest."""
        maxlen = wm.MAX_TURNS * 2
        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            for i in range(maxlen + 10):
                wm.add("user", f"msg {i}")
        assert len(wm) == maxlen


# ── Thread safety ────────────────────────────────────────────────────────

class TestThreadSafety:

    def test_concurrent_adds(self):
        """Multiple threads adding messages should not raise or corrupt state."""
        import threading

        with patch("backend.memory.current.now_vancouver", return_value=FROZEN_NOW):
            wm = WorkingMemory()
            total_msgs = 4  # per thread, kept small to stay within maxlen
            num_threads = 5
            expected_total = total_msgs * num_threads  # 20, within maxlen of 40

            def add_msgs(n):
                for i in range(n):
                    wm.add("user", f"t-{threading.current_thread().name}-{i}")

            threads = [threading.Thread(target=add_msgs, args=(total_msgs,)) for _ in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(wm) == expected_total
