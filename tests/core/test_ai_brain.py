"""Tests for backend.core.identity.ai_brain module.

Covers: IdentityManager - load/save persona, evolve(), _is_new_insight(),
get_system_prompt(), get_stats(), reset(), update_preference(),
add_relationship_note(), hot reload.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.core.identity.ai_brain import IdentityManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def persona_path(tmp_path):
    """Return a path inside tmp_path for persona file."""
    return tmp_path / "data" / "dynamic_persona.json"


@pytest.fixture
def empty_manager(persona_path):
    """IdentityManager with no existing persona file."""
    return IdentityManager(persona_path=str(persona_path))


@pytest.fixture
def full_persona_data():
    """A complete persona dict for testing."""
    return {
        "core_identity": "I am Axel, an AI assistant.",
        "voice_and_tone": {
            "style": "friendly and direct",
            "nuance": ["Use short sentences", "Be casual"],
            "examples": {
                "good": "Sure, here you go!",
                "bad": "As an AI language model, I cannot..."
            }
        },
        "honesty_directive": "Always be honest.",
        "learned_behaviors": [
            {"insight": "User prefers Korean", "learned_at": "2025-01-01T00:00:00", "confidence": 0.9},
            {"insight": "User likes concise answers", "learned_at": "2025-01-02T00:00:00", "confidence": 0.5},
        ],
        "user_preferences": {
            "language": "Korean",
            "tone": "casual",
        },
        "relationship_notes": [
            "Met on January 1st",
            "Enjoys coding together",
        ],
        "version": 3,
        "last_updated": "2025-01-02T00:00:00",
    }


@pytest.fixture
def loaded_manager(persona_path, full_persona_data):
    """IdentityManager with a pre-loaded persona file."""
    persona_path.parent.mkdir(parents=True, exist_ok=True)
    persona_path.write_text(json.dumps(full_persona_data), encoding="utf-8")
    return IdentityManager(persona_path=str(persona_path))


# ---------------------------------------------------------------------------
# Construction & Loading
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_creates_data_directory(self, persona_path):
        """IdentityManager creates the parent directory."""
        assert not persona_path.parent.exists()
        IdentityManager(persona_path=str(persona_path))
        assert persona_path.parent.exists()

    def test_loads_empty_persona_when_no_file(self, empty_manager):
        assert empty_manager.persona == {}

    def test_loads_existing_persona(self, loaded_manager, full_persona_data):
        assert loaded_manager.persona["core_identity"] == full_persona_data["core_identity"]
        assert loaded_manager.persona["version"] == 3

    def test_corrupted_json_raises(self, persona_path):
        persona_path.parent.mkdir(parents=True, exist_ok=True)
        persona_path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupted persona file"):
            IdentityManager(persona_path=str(persona_path))

    def test_permission_error_raises(self, persona_path):
        persona_path.parent.mkdir(parents=True, exist_ok=True)
        persona_path.write_text("{}", encoding="utf-8")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            with pytest.raises(RuntimeError, match="permission denied"):
                IdentityManager(persona_path=str(persona_path))

    def test_default_persona_path_used(self):
        """When no path is given, default path is used."""
        with patch("backend.core.identity.ai_brain._DEFAULT_PERSONA_PATH",
                    Path("/tmp/test_default_persona.json")):
            with patch.object(IdentityManager, "_load_persona", return_value={}):
                with patch.object(IdentityManager, "_ensure_data_dir"):
                    mgr = IdentityManager()
                    assert mgr.persona_path == Path("/tmp/test_default_persona.json")


# ---------------------------------------------------------------------------
# _get_file_mtime
# ---------------------------------------------------------------------------
class TestGetFileMtime:
    def test_returns_mtime_for_existing_file(self, loaded_manager, persona_path):
        mtime = loaded_manager._get_file_mtime()
        assert mtime > 0

    def test_returns_zero_for_missing_file(self, empty_manager):
        mtime = empty_manager._get_file_mtime()
        assert mtime == 0

    def test_returns_zero_on_exception(self, loaded_manager):
        with patch.object(type(loaded_manager.persona_path), "stat", side_effect=OSError("fail")):
            assert loaded_manager._get_file_mtime() == 0


# ---------------------------------------------------------------------------
# _maybe_reload
# ---------------------------------------------------------------------------
class TestMaybeReload:
    def test_no_reload_when_mtime_unchanged(self, loaded_manager):
        result = loaded_manager._maybe_reload()
        assert result is False

    def test_reload_when_mtime_changed(self, loaded_manager, persona_path):
        """Touch the file to change mtime, then reload."""
        import os
        time.sleep(0.05)
        # Rewrite with a change
        data = json.loads(persona_path.read_text(encoding="utf-8"))
        data["version"] = 99
        persona_path.write_text(json.dumps(data), encoding="utf-8")

        result = loaded_manager._maybe_reload()
        assert result is True
        assert loaded_manager.persona["version"] == 99


# ---------------------------------------------------------------------------
# evolve()
# ---------------------------------------------------------------------------
class TestEvolve:
    async def test_adds_new_insights(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            added = await loaded_manager.evolve(["New insight about user"])
            assert added == 1
            behaviors = loaded_manager.persona["learned_behaviors"]
            last = behaviors[-1]
            assert last["insight"] == "New insight about user"
            assert last["confidence"] == 0.7

    async def test_skips_duplicate_insight(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            # "User prefers Korean" already exists
            added = await loaded_manager.evolve(["User prefers Korean"])
            assert added == 0

    async def test_skips_subset_insight(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            # "Korean" is a substring of existing "User prefers Korean"
            added = await loaded_manager.evolve(["Korean"])
            assert added == 0

    async def test_increments_version(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            old_version = loaded_manager.persona.get("version", 1)
            await loaded_manager.evolve(["Completely new behavior"])
            assert loaded_manager.persona["version"] == old_version + 1

    async def test_saves_on_new_insights(self, loaded_manager):
        mock_save = AsyncMock()
        with patch.object(loaded_manager, "_save_persona", mock_save):
            await loaded_manager.evolve(["Brand new insight"])
            mock_save.assert_called_once()

    async def test_does_not_save_when_no_new_insights(self, loaded_manager):
        mock_save = AsyncMock()
        with patch.object(loaded_manager, "_save_persona", mock_save):
            await loaded_manager.evolve(["User prefers Korean"])
            mock_save.assert_not_called()

    async def test_multiple_insights_some_new(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            added = await loaded_manager.evolve([
                "User prefers Korean",  # duplicate
                "Totally new insight",  # new
                "Another new insight",  # new
            ])
            assert added == 2

    async def test_initializes_learned_behaviors_if_missing(self, empty_manager):
        with patch.object(empty_manager, "_save_persona", new_callable=AsyncMock):
            added = await empty_manager.evolve(["First insight"])
            assert added == 1
            assert isinstance(empty_manager.persona["learned_behaviors"], list)

    async def test_updates_last_updated(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.evolve(["New insight"])
            assert "last_updated" in loaded_manager.persona


# ---------------------------------------------------------------------------
# _is_new_insight
# ---------------------------------------------------------------------------
class TestIsNewInsight:
    def test_new_insight(self, loaded_manager):
        assert loaded_manager._is_new_insight("Something completely different") is True

    def test_exact_duplicate(self, loaded_manager):
        assert loaded_manager._is_new_insight("User prefers Korean") is False

    def test_case_insensitive(self, loaded_manager):
        assert loaded_manager._is_new_insight("USER PREFERS KOREAN") is False

    def test_subset_match(self, loaded_manager):
        assert loaded_manager._is_new_insight("prefers Korean") is False

    def test_superset_match(self, loaded_manager):
        """If new insight contains existing one, it's not new."""
        assert loaded_manager._is_new_insight("User prefers Korean for all conversations") is False

    def test_whitespace_stripped(self, loaded_manager):
        assert loaded_manager._is_new_insight("  User prefers Korean  ") is False

    def test_empty_behaviors(self, empty_manager):
        assert empty_manager._is_new_insight("anything") is True


# ---------------------------------------------------------------------------
# get_system_prompt
# ---------------------------------------------------------------------------
class TestGetSystemPrompt:
    def test_includes_core_identity(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "I am Axel" in prompt

    def test_includes_voice_style(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "friendly and direct" in prompt

    def test_includes_voice_nuances(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "Use short sentences" in prompt

    def test_includes_good_example(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "Sure, here you go!" in prompt

    def test_includes_bad_example(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "As an AI language model" in prompt

    def test_includes_honesty_directive(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "Always be honest" in prompt

    def test_includes_learned_behaviors(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "User prefers Korean" in prompt

    def test_includes_user_preferences(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "language: Korean" in prompt

    def test_includes_relationship_notes(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        assert "Met on January 1st" in prompt

    def test_empty_persona_has_defaults(self, empty_manager):
        prompt = empty_manager.get_system_prompt()
        # Should contain default messages for empty sections
        assert "Identity" in prompt

    def test_high_confidence_marked_as_must(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        # confidence 0.9 >= 0.85 -> "반드시"
        assert "반드시" in prompt

    def test_low_confidence_marked_as_tendency(self, loaded_manager):
        prompt = loaded_manager.get_system_prompt()
        # confidence 0.5 < 0.85 -> "경향"
        assert "경향" in prompt

    def test_limit_recent_behaviors(self, loaded_manager):
        # Add many behaviors
        for i in range(20):
            loaded_manager.persona["learned_behaviors"].append({
                "insight": f"behavior {i}",
                "confidence": 0.7,
            })
        prompt = loaded_manager.get_system_prompt(include_recent_behaviors=5)
        # Only last 5 should appear
        assert "behavior 19" in prompt
        assert "behavior 14" not in prompt or "behavior 15" in prompt

    def test_behaviors_below_confidence_threshold_excluded(self, loaded_manager):
        loaded_manager.persona["learned_behaviors"].append({
            "insight": "super low confidence",
            "confidence": 0.1,
        })
        prompt = loaded_manager.get_system_prompt()
        assert "super low confidence" not in prompt

    def test_triggers_maybe_reload(self, loaded_manager):
        with patch.object(loaded_manager, "_maybe_reload", return_value=False) as mock_reload:
            loaded_manager.get_system_prompt()
            mock_reload.assert_called_once()


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------
class TestGetStats:
    def test_returns_dict(self, loaded_manager):
        stats = loaded_manager.get_stats()
        assert isinstance(stats, dict)

    def test_contains_expected_keys(self, loaded_manager):
        stats = loaded_manager.get_stats()
        assert "version" in stats
        assert "total_behaviors" in stats
        assert "preferences_count" in stats
        assert "relationship_notes_count" in stats
        assert "last_updated" in stats

    def test_correct_counts(self, loaded_manager):
        stats = loaded_manager.get_stats()
        assert stats["version"] == 3
        assert stats["total_behaviors"] == 2
        assert stats["preferences_count"] == 2
        assert stats["relationship_notes_count"] == 2

    def test_empty_persona_stats(self, empty_manager):
        stats = empty_manager.get_stats()
        assert stats["version"] == 1
        assert stats["total_behaviors"] == 0
        assert stats["preferences_count"] == 0
        assert stats["relationship_notes_count"] == 0


# ---------------------------------------------------------------------------
# update_preference
# ---------------------------------------------------------------------------
class TestUpdatePreference:
    async def test_updates_preference(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.update_preference("theme", "dark")
            assert loaded_manager.persona["user_preferences"]["theme"] == "dark"

    async def test_saves_after_update(self, loaded_manager):
        mock_save = AsyncMock()
        with patch.object(loaded_manager, "_save_persona", mock_save):
            await loaded_manager.update_preference("theme", "dark")
            mock_save.assert_called_once()

    async def test_updates_last_updated(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.update_preference("theme", "dark")
            assert "last_updated" in loaded_manager.persona


# ---------------------------------------------------------------------------
# add_relationship_note
# ---------------------------------------------------------------------------
class TestAddRelationshipNote:
    async def test_adds_new_note(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.add_relationship_note("New note")
            assert "New note" in loaded_manager.persona["relationship_notes"]

    async def test_does_not_add_duplicate(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock) as mock_save:
            await loaded_manager.add_relationship_note("Met on January 1st")
            mock_save.assert_not_called()

    async def test_saves_after_adding(self, loaded_manager):
        mock_save = AsyncMock()
        with patch.object(loaded_manager, "_save_persona", mock_save):
            await loaded_manager.add_relationship_note("Another new note")
            mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------
class TestReset:
    async def test_reset_keeps_core_identity(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.reset(keep_core_identity=True)
            assert loaded_manager.persona.get("core_identity") == "I am Axel, an AI assistant."
            assert "learned_behaviors" not in loaded_manager.persona
            assert "user_preferences" not in loaded_manager.persona

    async def test_reset_clears_everything(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.reset(keep_core_identity=False)
            assert "core_identity" not in loaded_manager.persona or loaded_manager.persona.get("core_identity") is None

    async def test_reset_saves(self, loaded_manager):
        mock_save = AsyncMock()
        with patch.object(loaded_manager, "_save_persona", mock_save):
            await loaded_manager.reset()
            mock_save.assert_called_once()

    async def test_reset_sets_last_updated(self, loaded_manager):
        with patch.object(loaded_manager, "_save_persona", new_callable=AsyncMock):
            await loaded_manager.reset()
            assert "last_updated" in loaded_manager.persona


# ---------------------------------------------------------------------------
# _save_persona (integration-like test with mocked utilities)
# ---------------------------------------------------------------------------
class TestSavePersona:
    async def test_save_writes_to_file(self, loaded_manager, persona_path):
        """End-to-end test of _save_persona with mocked async utilities."""
        loaded_manager.persona["version"] = 42

        import tempfile as tf
        tmp = tf.NamedTemporaryFile(
            mode='w', encoding='utf-8',
            dir=str(persona_path.parent),
            prefix=".axnmihn_tmp_",
            suffix=".tmp",
            delete=False
        )
        tmp.write(json.dumps(loaded_manager.persona))
        tmp.close()

        mock_bounded = AsyncMock(side_effect=[tmp.name, None])
        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock()
        mock_lock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_lock = MagicMock(return_value=mock_lock_cm)

        with patch("backend.core.utils.async_utils.bounded_to_thread", mock_bounded):
            with patch("backend.core.utils.file_utils.async_file_lock", mock_lock):
                await loaded_manager._save_persona()

    async def test_save_timeout_raises(self, loaded_manager):
        """TimeoutError from bounded_to_thread should propagate."""
        import asyncio

        mock_bounded = AsyncMock(side_effect=asyncio.TimeoutError("write timeout"))

        with patch("backend.core.utils.async_utils.bounded_to_thread", mock_bounded):
            with pytest.raises(asyncio.TimeoutError):
                await loaded_manager._save_persona()

    async def test_save_cleans_up_tmp_on_error(self, loaded_manager, persona_path):
        """If replace fails after writing tmp, tmp file is cleaned up."""
        import os

        tmp_file = persona_path.parent / ".test_tmp_cleanup.tmp"
        tmp_file.write_text("temp", encoding="utf-8")

        mock_bounded = AsyncMock(side_effect=[str(tmp_file), None])
        mock_lock_cm = AsyncMock()
        mock_lock_cm.__aenter__ = AsyncMock()
        mock_lock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_lock = MagicMock(return_value=mock_lock_cm)

        with patch("backend.core.utils.async_utils.bounded_to_thread", mock_bounded):
            with patch("backend.core.utils.file_utils.async_file_lock", mock_lock):
                with patch("os.replace", side_effect=OSError("replace failed")):
                    with pytest.raises(OSError):
                        await loaded_manager._save_persona()
